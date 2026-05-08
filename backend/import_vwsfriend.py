#!/usr/bin/env python3
"""
Import historical data from a VWsFriend PostgreSQL backup into the VW-Dash SQLite DB.

Prerequisites: the Docker container 'vwsfriend-tmp' must be running with the backup
already restored (done by the setup instructions). Run from the backend/ directory:

    python import_vwsfriend.py [--docker CONTAINER] [--db PATH]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, VehicleSnapshot, ChargingSession, Trip


def pg_copy(container: str, table: str, columns: str) -> list[dict]:
    """Stream a COPY TO STDOUT from the container and return rows as dicts."""
    query = f"\\COPY (SELECT {columns} FROM {table}) TO STDOUT CSV HEADER"
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", "vwsfriend", "-c", query],
        capture_output=True, text=True, check=True,
    )
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def _ts(val: str | None) -> datetime | None:
    """Parse a PostgreSQL timestamp string (with or without tz) to a naive UTC datetime."""
    if not val or val.strip() == "":
        return None
    val = val.strip()
    # Normalise short tz offsets like +00 / -05 → +00:00 / -05:00
    import re
    val = re.sub(r"([+-]\d{2})$", r"\1:00", val)
    # Try ISO-like formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(val, fmt)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
    raise ValueError(f"Cannot parse timestamp: {val!r}")


def _float(val: str | None) -> float | None:
    if val is None or val.strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _int(val: str | None) -> int | None:
    if val is None or val.strip() == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def import_snapshots(container: str, session: Session) -> int:
    rows = pg_copy(
        container, "battery",
        '"carCapturedTimestamp", "currentSOC_pct", "cruisingRangeElectric_km"',
    )
    count = 0
    for r in rows:
        ts = _ts(r.get("carCapturedTimestamp"))
        if ts is None:
            continue
        soc = _int(r.get("currentSOC_pct"))
        range_km = _int(r.get("cruisingRangeElectric_km"))
        snap = VehicleSnapshot(
            recorded_at=ts,
            soc_pct=float(soc) if soc is not None else None,
            range_km=float(range_km) if range_km is not None else None,
            range_miles=round(range_km * 0.621371, 1) if range_km is not None else None,
        )
        session.add(snap)
        count += 1
    session.flush()
    return count


def _build_battery_index(container: str) -> tuple[list[datetime], list[int]]:
    """Return (sorted timestamps, soc_pct values) for fast binary-search lookup."""
    rows = pg_copy(
        container, "battery",
        '"carCapturedTimestamp", "currentSOC_pct"',
    )
    pairs = []
    for r in rows:
        ts = _ts(r.get("carCapturedTimestamp"))
        soc = _int(r.get("currentSOC_pct"))
        if ts is not None and soc is not None:
            pairs.append((ts, soc))
    pairs.sort(key=lambda p: p[0])
    times = [p[0] for p in pairs]
    socs = [p[1] for p in pairs]
    return times, socs


def _soc_at(times: list[datetime], socs: list[int], ts: datetime, before: bool) -> float | None:
    """Find the SOC reading closest to ts. before=True: last reading <= ts; False: first >= ts."""
    if not times:
        return None
    idx = bisect.bisect_right(times, ts)
    if before:
        i = idx - 1
    else:
        i = idx
    if 0 <= i < len(socs):
        return float(socs[i])
    return None


def import_trips(container: str, session: Session) -> int:
    times, socs = _build_battery_index(container)

    rows = pg_copy(
        container, "trips",
        '"startDate", "endDate", start_position_latitude, start_position_longitude, '
        "destination_position_latitude, destination_position_longitude, "
        "start_mileage_km, end_mileage_km",
    )
    count = 0
    for r in rows:
        started = _ts(r.get("startDate"))
        ended = _ts(r.get("endDate"))
        if started is None:
            continue

        start_km = _int(r.get("start_mileage_km"))
        end_km = _int(r.get("end_mileage_km"))
        distance_km: float | None = None
        distance_miles: float | None = None
        if start_km is not None and end_km is not None and end_km > start_km:
            distance_km = float(end_km - start_km)
            distance_miles = round(distance_km * 0.621371, 1)

        soc_start = _soc_at(times, socs, started, before=True)
        soc_end = _soc_at(times, socs, ended, before=False) if ended else None

        trip = Trip(
            started_at=started,
            ended_at=ended,
            distance_km=distance_km,
            distance_miles=distance_miles,
            soc_start_pct=soc_start,
            soc_end_pct=soc_end,
            start_lat=_float(r.get("start_position_latitude")),
            start_lon=_float(r.get("start_position_longitude")),
            end_lat=_float(r.get("destination_position_latitude")),
            end_lon=_float(r.get("destination_position_longitude")),
        )
        session.add(trip)
        count += 1
    session.flush()
    return count


def import_charging(container: str, session: Session, battery_kwh: float = 77.0) -> int:
    rows = pg_copy(
        container, "charging_sessions",
        'started, ended, "startSOC_pct", "endSOC_pct", "realCharged_kWh", '
        '"maximumChargePower_kW", acdc, "realCost_ct", "pricePerKwh_ct"',
    )
    count = 0
    for r in rows:
        started = _ts(r.get("started"))
        ended = _ts(r.get("ended"))
        if started is None:
            continue

        start_soc = _int(r.get("startSOC_pct"))
        end_soc = _int(r.get("endSOC_pct"))
        kwh = _float(r.get("realCharged_kWh"))

        # Estimate kWh from SOC delta when meter data is unavailable
        if kwh is None and start_soc is not None and end_soc is not None and end_soc > start_soc:
            kwh = round((end_soc - start_soc) / 100 * battery_kwh, 2)

        # realCost_ct is in öre (hundredths of SEK); divide by 100
        cost_ct = _int(r.get("realCost_ct"))
        cost: float | None = None
        if cost_ct:
            cost = round(cost_ct / 100, 2)
        else:
            # Try price × estimated kWh
            price_ct = _float(r.get("pricePerKwh_ct"))
            if price_ct and kwh:
                cost = round(price_ct * kwh / 100, 2)

        acdc = (r.get("acdc") or "").upper() or None

        cs = ChargingSession(
            started_at=started,
            ended_at=ended,
            soc_start_pct=float(start_soc) if start_soc is not None else None,
            soc_end_pct=float(end_soc) if end_soc is not None else None,
            kwh_added=kwh,
            range_added_km=None,
            peak_power_kw=_float(r.get("maximumChargePower_kW")),
            charge_type=acdc if acdc else None,
            cost=cost,
        )
        session.add(cs)
        count += 1
    session.flush()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import VWsFriend data into VW-Dash SQLite")
    parser.add_argument("--docker", default="vwsfriend-tmp", help="Docker container name")
    parser.add_argument("--db", default="data/vwdash.db", help="Path to SQLite DB")
    parser.add_argument("--battery-kwh", type=float, default=77.0,
                        help="Usable battery capacity in kWh for estimating charge amounts (default: 77)")
    parser.add_argument("--wipe", action="store_true", help="Wipe existing data before importing")
    args = parser.parse_args()

    # Verify Docker container is running
    check = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", args.docker],
        capture_output=True, text=True,
    )
    if check.returncode != 0 or check.stdout.strip() != "true":
        print(f"Error: Docker container '{args.docker}' is not running.")
        print("Start it with: docker start vwsfriend-tmp")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if args.wipe:
            print("Wiping existing data...")
            for model in (VehicleSnapshot, Trip, ChargingSession):
                session.query(model).delete()
            session.flush()

        print("Importing vehicle snapshots from battery table...")
        n_snaps = import_snapshots(args.docker, session)
        print(f"  {n_snaps} snapshots")

        print("Importing trips...")
        n_trips = import_trips(args.docker, session)
        print(f"  {n_trips} trips")

        print(f"Importing charging sessions (battery={args.battery_kwh} kWh)...")
        n_charging = import_charging(args.docker, session, battery_kwh=args.battery_kwh)
        print(f"  {n_charging} charging sessions")

        session.commit()

    print(f"\nDone. Imported {n_snaps} snapshots, {n_trips} trips, {n_charging} charging sessions.")
    print("You can stop the Docker container with: docker stop vwsfriend-tmp && docker rm vwsfriend-tmp")


if __name__ == "__main__":
    main()
