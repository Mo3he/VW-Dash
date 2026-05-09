#!/usr/bin/env python3
"""
Import historical data from a VWsFriend PostgreSQL backup into the VW-Dash SQLite DB.

Two modes:
  1. File-based (UI / API): pass a .vwsfrienddbbackup file path to import_from_backup().
     Requires pg_restore to be on PATH (included in the Docker image).
  2. Docker-based (CLI): the backup must already be restored into a running container.
     Run from the backend/ directory:
         python import_vwsfriend.py [--docker CONTAINER] [--db PATH]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import re
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, VehicleSnapshot, ChargingSession, Trip


# ─── Low-level data extraction ───────────────────────────────────────────────

def pg_copy(container: str, table: str, columns: str) -> list[dict]:
    """Stream a COPY TO STDOUT from a Docker container running psql."""
    query = f"\\COPY (SELECT {columns} FROM {table}) TO STDOUT CSV HEADER"
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", "vwsfriend", "-c", query],
        capture_output=True, text=True, check=True,
    )
    return list(csv.DictReader(io.StringIO(result.stdout)))


def pg_restore_copy(backup_path: str, table: str) -> list[dict]:
    """Extract all rows from a table using pg_restore (no running DB needed)."""
    result = subprocess.run(
        ["pg_restore", "--data-only", f"--table={table}", "-f", "-", backup_path],
        capture_output=True, text=True,
    )
    # pg_restore exits non-zero for harmless warnings — ignore exit code,
    # but raise if we got nothing and stderr looks fatal.
    if not result.stdout and result.returncode != 0:
        raise RuntimeError(f"pg_restore failed: {result.stderr[:500]}")

    rows: list[dict] = []
    columns: list[str] | None = None
    in_copy = False

    for line in result.stdout.splitlines():
        if not in_copy:
            if re.match(r"^COPY\s+", line, re.IGNORECASE) and "FROM stdin" in line:
                m = re.search(r"\(([^)]+)\)", line)
                if m:
                    columns = [c.strip().strip('"') for c in m.group(1).split(",")]
                    in_copy = True
        else:
            if line == "\\.":
                in_copy = False
            elif columns:
                values = line.split("\t")
                rows.append({
                    col: (None if val == "\\N" else val)
                    for col, val in zip(columns, values)
                })

    return rows


# ─── Type helpers ─────────────────────────────────────────────────────────────

def _ts(val: str | None) -> datetime | None:
    if not val or val.strip() == "":
        return None
    val = val.strip()
    val = re.sub(r"([+-]\d{2})$", r"\1:00", val)
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


# ─── SOC index ────────────────────────────────────────────────────────────────

def _build_battery_index(rows: list[dict]) -> tuple[list[datetime], list[int]]:
    pairs = []
    for r in rows:
        ts = _ts(r.get("carCapturedTimestamp"))
        soc = _int(r.get("currentSOC_pct"))
        if ts is not None and soc is not None:
            pairs.append((ts, soc))
    pairs.sort(key=lambda p: p[0])
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _soc_at(times: list[datetime], socs: list[int], ts: datetime, before: bool) -> float | None:
    if not times:
        return None
    idx = bisect.bisect_right(times, ts)
    i = idx - 1 if before else idx
    return float(socs[i]) if 0 <= i < len(socs) else None


# ─── Import functions (accept pre-fetched rows) ───────────────────────────────

def _import_snapshot_rows(rows: list[dict], session: Session) -> int:
    count = 0
    for r in rows:
        ts = _ts(r.get("carCapturedTimestamp"))
        if ts is None:
            continue
        soc = _int(r.get("currentSOC_pct"))
        range_km = _int(r.get("cruisingRangeElectric_km"))
        session.add(VehicleSnapshot(
            recorded_at=ts,
            soc_pct=float(soc) if soc is not None else None,
            range_km=float(range_km) if range_km is not None else None,
            range_miles=round(range_km * 0.621371, 1) if range_km is not None else None,
        ))
        count += 1
    session.flush()
    return count


def _import_trip_rows(rows: list[dict], battery_rows: list[dict], session: Session, battery_kwh: float = 77.0) -> int:
    times, socs = _build_battery_index(battery_rows)
    count = 0
    for r in rows:
        started = _ts(r.get("startDate"))
        ended = _ts(r.get("endDate"))
        if started is None:
            continue
        start_km = _int(r.get("start_mileage_km"))
        end_km = _int(r.get("end_mileage_km"))
        distance_km = distance_miles = None
        if start_km is not None and end_km is not None and end_km > start_km:
            distance_km = float(end_km - start_km)
            distance_miles = round(distance_km * 0.621371, 1)

        soc_start = _soc_at(times, socs, started, before=True)
        soc_end = _soc_at(times, socs, ended, before=False) if ended else None

        kwh_used = None
        efficiency = None
        if soc_start is not None and soc_end is not None and soc_start > soc_end:
            kwh_used = round((soc_start - soc_end) / 100.0 * battery_kwh, 2)
            if distance_km and distance_km > 0:
                efficiency = round(kwh_used / distance_km * 100, 1)

        avg_speed = None
        if distance_km and ended:
            duration_h = (ended - started).total_seconds() / 3600
            if duration_h > 0:
                avg_speed = round(distance_km / duration_h, 1)

        session.add(Trip(
            started_at=started,
            ended_at=ended,
            distance_km=distance_km,
            distance_miles=distance_miles,
            soc_start_pct=soc_start,
            soc_end_pct=soc_end,
            kwh_used=kwh_used,
            efficiency_kwh_100km=efficiency,
            avg_speed_kmh=avg_speed,
            start_lat=_float(r.get("start_position_latitude")),
            start_lon=_float(r.get("start_position_longitude")),
            end_lat=_float(r.get("destination_position_latitude")),
            end_lon=_float(r.get("destination_position_longitude")),
        ))
        count += 1
    session.flush()
    return count


def _import_charging_rows(
    rows: list[dict],
    session: Session,
    battery_kwh: float,
    epa_range_km: float = 410.0,
    electricity_rate: float = 0.13,
) -> int:
    count = 0
    for r in rows:
        started = _ts(r.get("started"))
        ended = _ts(r.get("ended"))
        if started is None:
            continue
        start_soc = _int(r.get("startSOC_pct"))
        end_soc = _int(r.get("endSOC_pct"))
        kwh = _float(r.get("realCharged_kWh"))
        if kwh is None and start_soc is not None and end_soc is not None and end_soc > start_soc:
            kwh = round((end_soc - start_soc) / 100 * battery_kwh, 2)

        range_added = None
        if start_soc is not None and end_soc is not None and end_soc > start_soc:
            range_added = round((end_soc - start_soc) / 100.0 * epa_range_km, 1)

        cost_ct = _int(r.get("realCost_ct"))
        price_ct = _float(r.get("pricePerKwh_ct"))
        cost: float | None = None
        rate_used: float | None = None
        if cost_ct is not None:
            cost = round(cost_ct / 100, 2)
            if kwh and kwh > 0:
                rate_used = round(cost / kwh, 4)
        elif price_ct is not None and kwh:
            rate_used = price_ct / 100
            cost = round(kwh * rate_used, 2)
        elif kwh:
            rate_used = electricity_rate
            cost = round(kwh * electricity_rate, 2)

        acdc = (r.get("acdc") or "").upper() or None
        session.add(ChargingSession(
            started_at=started,
            ended_at=ended,
            soc_start_pct=float(start_soc) if start_soc is not None else None,
            soc_end_pct=float(end_soc) if end_soc is not None else None,
            kwh_added=kwh,
            range_added_km=range_added,
            peak_power_kw=_float(r.get("maximumChargePower_kW")),
            charge_type=acdc if acdc else None,
            cost=cost,
            cost_per_kwh=rate_used,
        ))
        count += 1
    session.flush()
    return count


# ─── High-level entry points ──────────────────────────────────────────────────

def import_from_backup(
    backup_path: str,
    db_path: str = "data/vwdash.db",
    battery_kwh: float = 77.0,
    wipe: bool = False,
) -> dict:
    """Import VWsFriend data from a pg_dump custom-format file. Returns counts."""
    battery_rows = pg_restore_copy(backup_path, "battery")
    trip_rows = pg_restore_copy(backup_path, "trips")
    charging_rows = pg_restore_copy(backup_path, "charging_sessions")

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if wipe:
            for model in (VehicleSnapshot, Trip, ChargingSession):
                session.query(model).delete()
            session.flush()

        n_snaps = _import_snapshot_rows(battery_rows, session)
        n_trips = _import_trip_rows(trip_rows, battery_rows, session)
        n_charging = _import_charging_rows(charging_rows, session, battery_kwh)
        session.commit()

    return {"snapshots": n_snaps, "trips": n_trips, "charging_sessions": n_charging}


# ─── Docker-based helpers (used by the CLI) ───────────────────────────────────

def import_snapshots(container: str, session: Session) -> int:
    rows = pg_copy(container, "battery",
                   '"carCapturedTimestamp", "currentSOC_pct", "cruisingRangeElectric_km"')
    return _import_snapshot_rows(rows, session)


def import_trips(container: str, session: Session) -> int:
    battery_rows = pg_copy(container, "battery", '"carCapturedTimestamp", "currentSOC_pct"')
    trip_rows = pg_copy(
        container, "trips",
        '"startDate", "endDate", start_position_latitude, start_position_longitude, '
        "destination_position_latitude, destination_position_longitude, "
        "start_mileage_km, end_mileage_km",
    )
    return _import_trip_rows(trip_rows, battery_rows, session)


def import_charging(container: str, session: Session, battery_kwh: float = 77.0) -> int:
    rows = pg_copy(
        container, "charging_sessions",
        'started, ended, "startSOC_pct", "endSOC_pct", "realCharged_kWh", '
        '"maximumChargePower_kW", acdc, "realCost_ct", "pricePerKwh_ct"',
    )
    return _import_charging_rows(rows, session, battery_kwh)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Import VWsFriend data into VW-Dash SQLite")
    parser.add_argument("--docker", default="vwsfriend-tmp", help="Docker container name")
    parser.add_argument("--db", default="data/vwdash.db", help="Path to SQLite DB")
    parser.add_argument("--battery-kwh", type=float, default=77.0,
                        help="Usable battery capacity in kWh (default: 77)")
    parser.add_argument("--wipe", action="store_true", help="Wipe existing data before importing")
    args = parser.parse_args()

    check = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", args.docker],
        capture_output=True, text=True,
    )
    if check.returncode != 0 or check.stdout.strip() != "true":
        print(f"Error: Docker container '{args.docker}' is not running.")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if args.wipe:
            print("Wiping existing data...")
            for model in (VehicleSnapshot, Trip, ChargingSession):
                session.query(model).delete()
            session.flush()

        print("Importing snapshots...")
        n_snaps = import_snapshots(args.docker, session)
        print(f"  {n_snaps} snapshots")

        print("Importing trips...")
        n_trips = import_trips(args.docker, session)
        print(f"  {n_trips} trips")

        print(f"Importing charging sessions (battery={args.battery_kwh} kWh)...")
        n_charging = import_charging(args.docker, session, battery_kwh=args.battery_kwh)
        print(f"  {n_charging} charging sessions")

        session.commit()

    print(f"\nDone. {n_snaps} snapshots, {n_trips} trips, {n_charging} charging sessions.")
    print("Stop the container: docker stop vwsfriend-tmp && docker rm vwsfriend-tmp")


if __name__ == "__main__":
    main()
