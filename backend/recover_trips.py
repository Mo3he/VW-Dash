#!/usr/bin/env python3
"""
Reconstruct Trip records from raw VehicleSnapshot data.

Run inside the backend container or locally (with data/vwdash.db accessible):
    python recover_trips.py [--date 2026-05-10] [--dry-run]

It walks snapshots in chronological order, detects trip boundaries by looking
for transitions between "parked/plugged/charging" and "driving" states, then
inserts Trip rows for any period that has no existing overlapping trip.
"""
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap path so we can reuse models/database from the backend package
# ---------------------------------------------------------------------------
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from database import SessionLocal
from models import Trip, TripPoint, VehicleSnapshot
from geocoder import reverse_geocode


def _is_driving(snap: VehicleSnapshot) -> bool:
    charging = (snap.charging_state or "").upper() == "CHARGING"
    plugged = snap.plug_connected is True
    return not charging and not plugged


def _build_segments(snaps: list[VehicleSnapshot]) -> list[tuple[VehicleSnapshot, VehicleSnapshot]]:
    """
    Return list of (start_snap, end_snap) pairs representing contiguous
    "driving" windows.  A driving window is a maximal run of snapshots where
    _is_driving() is True AND there is meaningful activity (SoC dropped or
    odometer increased between first and last snap in the window).
    """
    segments = []
    seg_start: Optional[VehicleSnapshot] = None
    prev: Optional[VehicleSnapshot] = None

    for snap in snaps:
        driving = _is_driving(snap)
        if driving and seg_start is None:
            seg_start = snap
        elif not driving and seg_start is not None:
            # segment just ended — prev is last driving snap
            if prev is not None and prev is not seg_start:
                segments.append((seg_start, prev))
            seg_start = None
        prev = snap

    # Handle still-open segment at end of window
    if seg_start is not None and prev is not None and prev is not seg_start:
        segments.append((seg_start, prev))

    return segments


def _has_activity(start: VehicleSnapshot, end: VehicleSnapshot) -> bool:
    """Return True if there is evidence of actual movement in this segment."""
    # Odometer increased
    if start.odometer_km and end.odometer_km and end.odometer_km > start.odometer_km:
        return True
    # SoC dropped (consumption without charging)
    if start.soc_pct and end.soc_pct and start.soc_pct > end.soc_pct + 0.5:
        return True
    # Location changed measurably (> ~200 m apart)
    if (start.latitude and start.longitude and end.latitude and end.longitude):
        dlat = abs(start.latitude - end.latitude)
        dlon = abs(start.longitude - end.longitude)
        if dlat > 0.002 or dlon > 0.002:
            return True
    return False


def recover(since: datetime, dry_run: bool) -> None:
    db = SessionLocal()
    try:
        snaps: list[VehicleSnapshot] = (
            db.query(VehicleSnapshot)
            .filter(VehicleSnapshot.recorded_at >= since)
            .order_by(VehicleSnapshot.recorded_at)
            .all()
        )
        print(f"Found {len(snaps)} snapshots since {since.date()}")

        if not snaps:
            print("No snapshot data found — nothing to recover.")
            return

        segments = _build_segments(snaps)
        print(f"Identified {len(segments)} driving segment(s)")

        inserted = 0
        for seg_start, seg_end in segments:
            if not _has_activity(seg_start, seg_end):
                print(f"  SKIP  {seg_start.recorded_at:%H:%M} – {seg_end.recorded_at:%H:%M}  (no measurable activity)")
                continue

            # Check for existing trip that already covers this window
            existing = db.execute(text(
                "SELECT id FROM trips WHERE started_at <= :end AND (ended_at >= :start OR ended_at IS NULL)"
            ), {"start": seg_start.recorded_at, "end": seg_end.recorded_at}).fetchone()

            if existing:
                print(f"  SKIP  {seg_start.recorded_at:%H:%M} – {seg_end.recorded_at:%H:%M}  (trip {existing[0]} already exists)")
                continue

            # Calculate distance and efficiency
            distance_km = None
            distance_miles = None
            avg_speed_kmh = None
            kwh_used = None
            efficiency = None

            if seg_start.odometer_km and seg_end.odometer_km:
                dist = seg_end.odometer_km - seg_start.odometer_km
                if dist > 0:
                    distance_km = round(dist, 2)
                    distance_miles = round(dist * 0.621371, 2)
                    duration_h = (seg_end.recorded_at - seg_start.recorded_at).total_seconds() / 3600
                    if duration_h > 0:
                        avg_speed_kmh = round(dist / duration_h, 1)

            if seg_start.soc_pct and seg_end.soc_pct and seg_start.soc_pct > seg_end.soc_pct:
                delta_soc = seg_start.soc_pct - seg_end.soc_pct
                kwh_used = round(delta_soc / 100 * 77.0, 2)
                if distance_km and distance_km > 0:
                    efficiency = round(kwh_used / distance_km * 100, 1)

            start_address = None
            end_address = None
            if not dry_run:
                if seg_start.latitude and seg_start.longitude:
                    start_address = reverse_geocode(seg_start.latitude, seg_start.longitude)
                if seg_end.latitude and seg_end.longitude:
                    end_address = reverse_geocode(seg_end.latitude, seg_end.longitude)

            duration_min = int((seg_end.recorded_at - seg_start.recorded_at).total_seconds() / 60)
            print(
                f"  {'DRY ' if dry_run else ''}INSERT  "
                f"{seg_start.recorded_at:%H:%M} – {seg_end.recorded_at:%H:%M}  "
                f"({duration_min} min"
                + (f", {distance_km:.1f} km" if distance_km else "")
                + (f", {kwh_used:.1f} kWh" if kwh_used else "")
                + ")"
            )

            if not dry_run:
                trip = Trip(
                    started_at=seg_start.recorded_at,
                    ended_at=seg_end.recorded_at,
                    soc_start_pct=seg_start.soc_pct,
                    soc_end_pct=seg_end.soc_pct,
                    distance_km=distance_km,
                    distance_miles=distance_miles,
                    avg_speed_kmh=avg_speed_kmh,
                    kwh_used=kwh_used,
                    efficiency_kwh_100km=efficiency,
                    start_lat=seg_start.latitude,
                    start_lon=seg_start.longitude,
                    end_lat=seg_end.latitude,
                    end_lon=seg_end.longitude,
                    outdoor_temp_c=seg_start.outdoor_temp_c,
                    start_address=start_address,
                    end_address=end_address,
                )
                db.add(trip)
                db.flush()

                # Add GPS breadcrumbs from all snapshots in this window
                window_snaps = [
                    s for s in snaps
                    if seg_start.recorded_at <= s.recorded_at <= seg_end.recorded_at
                    and s.latitude and s.longitude
                ]
                for ws in window_snaps:
                    db.add(TripPoint(
                        trip_id=trip.id,
                        recorded_at=ws.recorded_at,
                        latitude=ws.latitude,
                        longitude=ws.longitude,
                    ))

                inserted += 1

        if not dry_run:
            db.commit()
            print(f"\nDone — inserted {inserted} trip(s).")
        else:
            print(f"\nDry run complete — would insert {inserted} trip(s). Re-run without --dry-run to apply.")
    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover trips from snapshot history")
    parser.add_argument("--date", default=None, help="Recover from this date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--days", type=int, default=1, help="Number of days back to scan (default 1)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be inserted without writing")
    args = parser.parse_args()

    if args.date:
        since = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    recover(since, args.dry_run)
