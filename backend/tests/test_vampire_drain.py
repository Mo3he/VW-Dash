"""
Tests for the vampire drain endpoint (routers/vehicle.py).

Tests the window-finding algorithm directly by calling the router function
with a seeded in-memory DB session — no full app startup required.
"""
from datetime import datetime, timezone, timedelta

import pytest

from models import VehicleSnapshot


T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _snap(hours_offset: float, soc: float, charge_kw: float = 0.0, odometer: float = 1000.0) -> VehicleSnapshot:
    return VehicleSnapshot(
        recorded_at=T0 + timedelta(hours=hours_offset),
        soc_pct=soc,
        charge_power_kw=charge_kw,
        odometer_km=odometer,
    )


def _call_drain(db, days: int = 9999, min_park_hours: float = 2.0) -> dict:
    """Call the vampire_drain router function directly with the test session."""
    from routers.vehicle import vampire_drain
    return vampire_drain(days=days, min_park_hours=min_park_hours, db=db)


def _seed(db, snaps):
    for s in snaps:
        db.add(s)
    db.commit()


# ---------------------------------------------------------------------------
# Core window detection
# ---------------------------------------------------------------------------

class TestVampireDrainWindows:

    def test_detects_pure_drain_window(self, db):
        """SoC drops over a 3-hour parked window with no charging or driving."""
        snaps = [
            _snap(0, soc=80.0, odometer=1000.0),
            _snap(1, soc=79.5, odometer=1000.0),
            _snap(2, soc=79.0, odometer=1000.0),
            _snap(3, soc=78.0, odometer=1000.0),
        ]
        _seed(db, snaps)
        result = _call_drain(db)

        assert len(result["events"]) == 1
        ev = result["events"][0]
        assert ev["soc_drop_pct"] == pytest.approx(2.0)
        assert ev["duration_h"] == pytest.approx(3.0)

    def test_no_event_when_soc_does_not_drop(self, db):
        """No drain event if SoC is flat or rising."""
        snaps = [
            _snap(0, soc=80.0, odometer=1000.0),
            _snap(2, soc=80.0, odometer=1000.0),
            _snap(4, soc=81.0, odometer=1000.0),
        ]
        _seed(db, snaps)
        result = _call_drain(db)

        assert result["events"] == []
        assert result["avg_drain_pct_per_h"] is None

    def test_charging_breaks_parked_window(self, db):
        """A charging snapshot mid-window terminates the parked period.
        The pre-charge window is too short (<2h); the post-charge window has no
        SoC drop. Neither should produce a drain event."""
        snaps = [
            _snap(0,  soc=80.0, odometer=1000.0),
            _snap(1,  soc=79.0, odometer=1000.0),  # 1h window — below min_park_hours
            _snap(2,  soc=79.0, charge_kw=7.4, odometer=1000.0),  # charging starts
            _snap(4,  soc=90.0, odometer=1000.0),   # post-charge parked
            _snap(6,  soc=90.0, odometer=1000.0),   # no drop
        ]
        _seed(db, snaps)
        result = _call_drain(db)

        # Pre-charge window: 1h < min_park_hours=2h → excluded
        # Post-charge window: soc flat → no drop → no event
        assert result["events"] == []

    def test_odometer_increase_breaks_parked_window(self, db):
        """
        If the odometer increases mid-sequence, that's driving not parking.
        The SoC drop from driving must NOT be counted as vampire drain.
        """
        snaps = [
            _snap(0,  soc=80.0, odometer=1000.0),  # parked start
            _snap(1,  soc=80.0, odometer=1000.0),
            _snap(2,  soc=79.0, odometer=1030.0),  # odometer jumped — drove!
            _snap(4,  soc=79.0, odometer=1030.0),  # parked again
            _snap(6,  soc=78.0, odometer=1030.0),
        ]
        _seed(db, snaps)
        result = _call_drain(db)

        # The first window (t=0..1, 1h) is below min_park_hours, no event.
        # The second window (t=2..6, 4h, 1% drop) should be detected.
        assert len(result["events"]) == 1
        ev = result["events"][0]
        assert ev["soc_drop_pct"] == pytest.approx(1.0)
        assert ev["duration_h"] == pytest.approx(4.0)

    def test_window_below_min_park_hours_excluded(self, db):
        """Windows shorter than min_park_hours must not produce events."""
        snaps = [
            _snap(0, soc=80.0, odometer=1000.0),
            _snap(1, soc=78.0, odometer=1000.0),  # 2% drop but only 1 hour
        ]
        _seed(db, snaps)
        result = _call_drain(db, min_park_hours=2.0)

        assert result["events"] == []

    def test_custom_min_park_hours(self, db):
        """A 1.5h window is included when min_park_hours=1.0."""
        snaps = [
            _snap(0.0, soc=80.0, odometer=1000.0),
            _snap(0.5, soc=79.5, odometer=1000.0),
            _snap(1.5, soc=79.0, odometer=1000.0),
        ]
        _seed(db, snaps)
        result = _call_drain(db, min_park_hours=1.0)

        assert len(result["events"]) == 1


# ---------------------------------------------------------------------------
# Average drain calculation
# ---------------------------------------------------------------------------

class TestVampireDrainAverage:

    def test_weighted_average(self, db):
        """
        avg_drain_pct_per_h should be weighted by window duration, not
        a simple mean of per-event rates.

        Window A: 2% drop over 2h → 1.0 %/h
        Window B: 3% drop over 6h → 0.5 %/h

        Unweighted mean = (1.0 + 0.5) / 2 = 0.75 %/h  (WRONG)
        Weighted mean   = (2 + 3) / (2 + 6) = 0.625 %/h (CORRECT)

        Use charging as the window break so the transition snapshot is excluded
        from the next window's SoC start.
        """
        snaps = [
            # Window A: t=0..2h, 2% drop
            _snap(0,  soc=80.0, odometer=1000.0),
            _snap(2,  soc=78.0, odometer=1000.0),
            # Charging break — cleanly terminates window A
            _snap(2.5, soc=78.0, charge_kw=7.4, odometer=1000.0),
            # Window B: t=3..9h, 3% drop
            _snap(3,  soc=90.0, odometer=1000.0),
            _snap(9,  soc=87.0, odometer=1000.0),
        ]
        _seed(db, snaps)
        result = _call_drain(db, min_park_hours=1.5)

        assert len(result["events"]) == 2
        # Window A: 2%/2h, Window B: 3%/6h → weighted = (2+3)/(2+6) = 0.625
        assert result["avg_drain_pct_per_h"] == pytest.approx(0.625, abs=0.01)

    def test_total_soc_lost(self, db):
        """total_soc_lost should sum SoC drops across all events."""
        snaps = [
            _snap(0, soc=80.0, odometer=1000.0),
            _snap(3, soc=77.0, odometer=1000.0),  # Window A: 3h, 3% drop
            # Charging break to cleanly separate windows
            _snap(3.5, soc=77.0, charge_kw=7.4, odometer=1000.0),
            _snap(4,   soc=80.0, odometer=1000.0),  # Window B start
            _snap(7,   soc=77.0, odometer=1000.0),  # Window B: 3h, 3% drop
        ]
        _seed(db, snaps)
        result = _call_drain(db, min_park_hours=2.0)

        assert len(result["events"]) == 2
        assert result["total_soc_lost"] == pytest.approx(6.0, abs=0.1)
