"""
Tests for poller.py:
  - _close_trip energy calculation (SoC primary path, range-delta fallback)
  - _update_trip stale-parking trip-start trigger
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from models import Trip, TripPoint, VehicleSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Use a recent timestamp so the 24h force-close doesn't fire during tests.
T0 = datetime.now(timezone.utc) - timedelta(hours=2)


def _snap(**kwargs) -> VehicleSnapshot:
    defaults = dict(
        recorded_at=T0,
        soc_pct=70.0,
        range_km=287.0,
        odometer_km=10000.0,
        plug_connected=False,
        charging_state="notReadyForCharging",
        charge_power_kw=0.0,
        parking_time=None,
        latitude=55.72,
        longitude=13.22,
        outdoor_temp_c=15.0,
    )
    defaults.update(kwargs)
    return VehicleSnapshot(**defaults)


def _open_trip(**kwargs) -> Trip:
    defaults = dict(
        started_at=T0 - timedelta(hours=1),
        soc_start_pct=75.0,
        range_km_start=310.0,
        start_lat=55.72,
        start_lon=13.22,
    )
    defaults.update(kwargs)
    return Trip(**defaults)


# ---------------------------------------------------------------------------
# _close_trip — energy calculation
# ---------------------------------------------------------------------------

class TestCloseTripEnergy:
    """_close_trip should compute kwh_used correctly for all three cases."""

    def _call(self, db, trip, snap, odo_start=None):
        import poller
        poller._trip_start_odometer = odo_start
        with patch("webhook.fire"):
            poller._close_trip(db, trip, snap)

    def test_soc_primary_path(self, db):
        """SoC dropped 5% on a 77 kWh battery → 3.85 kWh."""
        trip = _open_trip(soc_start_pct=75.0, range_km_start=310.0)
        snap = _snap(
            recorded_at=T0,
            soc_pct=70.0,
            range_km=290.0,
            odometer_km=10050.0,
        )
        db.add(trip)
        db.flush()

        with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
            with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                self._call(db, trip, snap, odo_start=10000.0)

        assert trip.kwh_used == pytest.approx(3.85, abs=0.01)
        assert trip.efficiency_kwh_100km is not None

    def test_range_fallback_when_soc_unchanged(self, db):
        """SoC flat (short trip), but range dropped 20 km → use range-delta fallback."""
        trip = _open_trip(soc_start_pct=70.0, range_km_start=300.0)
        snap = _snap(
            recorded_at=T0,
            soc_pct=70.0,   # unchanged — SoC quantization
            range_km=280.0,  # dropped 20 km
            odometer_km=10020.0,
        )
        db.add(trip)
        db.flush()

        # 20 km / 410 km_rated * 77 kWh ≈ 3.75 kWh
        expected_kwh = 20.0 / 410.0 * 77.0

        with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
            with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                self._call(db, trip, snap, odo_start=10000.0)

        assert trip.kwh_used == pytest.approx(expected_kwh, rel=0.01)
        assert trip.efficiency_kwh_100km is not None

    def test_no_energy_when_both_flat(self, db):
        """SoC and range both unchanged → kwh_used stays None."""
        trip = _open_trip(soc_start_pct=70.0, range_km_start=280.0)
        snap = _snap(
            recorded_at=T0,
            soc_pct=70.0,
            range_km=280.0,
            odometer_km=10020.0,
        )
        db.add(trip)
        db.flush()

        with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
            with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                self._call(db, trip, snap, odo_start=10000.0)

        assert trip.kwh_used is None
        assert trip.efficiency_kwh_100km is None

    def test_distance_and_speed_computed(self, db):
        """Odometer delta and avg speed should be populated."""
        trip = _open_trip(started_at=T0 - timedelta(hours=1))
        snap = _snap(recorded_at=T0, soc_pct=65.0, odometer_km=10100.0)
        db.add(trip)
        db.flush()

        with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
            with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                self._call(db, trip, snap, odo_start=10000.0)

        assert trip.distance_km == pytest.approx(100.0)
        assert trip.distance_miles == pytest.approx(62.14, abs=0.1)
        assert trip.avg_speed_kmh == pytest.approx(100.0)  # 100 km in 1 h


# ---------------------------------------------------------------------------
# _update_trip — stale parking_time fallback
# ---------------------------------------------------------------------------

class TestUpdateTripStaleParkingFallback:
    """
    When WeConnect returns a frozen (unchanged) parkingPosition timestamp
    while the odometer is moving, the 'stale_parking' fallback should open
    a new trip after 2 consecutive polls with the same timestamp.
    """

    PARKING_TS = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

    def _make_snap(self, recorded_at, odometer_km, parking_time=PARKING_TS):
        return _snap(
            recorded_at=recorded_at,
            soc_pct=80.0,
            range_km=330.0,
            odometer_km=odometer_km,
            parking_time=parking_time,
            plug_connected=False,
            charging_state="notReadyForCharging",
            charge_power_kw=0.0,
        )

    def test_stale_parking_triggers_trip_after_two_unchanged_polls(self, db):
        import poller

        poller._prev_odometer = 10000.0  # seed so first poll can compute a delta later

        # Poll 1: parking_time first seen — counter resets to 0 (prev was None)
        s1 = self._make_snap(T0, odometer_km=10000.0)
        db.add(s1)
        db.flush()
        with patch("webhook.fire"):
            poller._update_trip(db, s1)
        assert poller._active_trip_id is None
        assert poller._parking_time_unchanged_polls == 0

        # Poll 2: same parking_time, same odometer — counter → 1, no trip yet
        s2 = self._make_snap(T0 + timedelta(minutes=5), odometer_km=10000.0)
        db.add(s2)
        db.flush()
        with patch("webhook.fire"):
            poller._update_trip(db, s2)
        assert poller._active_trip_id is None
        assert poller._parking_time_unchanged_polls == 1

        # Poll 3: same parking_time, odometer moved — counter → 2, trip STARTS
        s3 = self._make_snap(T0 + timedelta(minutes=10), odometer_km=10010.0)
        db.add(s3)
        db.flush()
        with patch("webhook.fire"):
            poller._update_trip(db, s3)
        assert poller._active_trip_id is not None, "Trip should have started via stale_parking fallback"

    def test_no_false_trigger_without_odometer_movement(self, db):
        """Frozen parking_time with no odometer change should never start a trip."""
        import poller

        poller._prev_odometer = 10000.0

        for i in range(5):
            s = self._make_snap(T0 + timedelta(minutes=i * 5), odometer_km=10000.0)
            db.add(s)
            db.flush()
            with patch("webhook.fire"):
                poller._update_trip(db, s)

        assert poller._active_trip_id is None

    def test_counter_resets_when_trip_ends(self, db):
        """After a trip closes, _parking_time_unchanged_polls should reset to 0."""
        import poller

        poller._prev_odometer = 10000.0

        # Start a trip via stale parking (poll 1, 2, 3)
        for i in range(3):
            odo = 10000.0 if i < 2 else 10010.0
            s = self._make_snap(T0 + timedelta(minutes=i * 5), odometer_km=odo)
            db.add(s)
            db.flush()
            with patch("webhook.fire"):
                poller._update_trip(db, s)

        assert poller._active_trip_id is not None

        # Close trip: plug in
        end_snap = _snap(
            recorded_at=T0 + timedelta(minutes=30),
            soc_pct=75.0,
            odometer_km=10020.0,
            plug_connected=True,
            parking_time=self.PARKING_TS,
        )
        db.add(end_snap)
        db.flush()
        with patch("webhook.fire"):
            with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
                with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                    poller._update_trip(db, end_snap)

        assert poller._active_trip_id is None
        assert poller._parking_time_unchanged_polls == 0


# ---------------------------------------------------------------------------
# _update_trip — odometer-idle end (website-portal mode, no parking_time)
# ---------------------------------------------------------------------------

class TestUpdateTripOdometerIdleEnd:
    """
    The website portal exposes no GPS/parking_time, so trips start via the odometer
    fallback. Without a parking signal, the trip must end once the odometer stalls
    for long enough instead of waiting for the 24h force-close.
    """

    def _portal_snap(self, recorded_at, odometer_km):
        # No parking_time, no GPS — mirrors a website-portal snapshot.
        return _snap(
            recorded_at=recorded_at,
            soc_pct=70.0,
            range_km=287.0,
            odometer_km=odometer_km,
            parking_time=None,
            latitude=None,
            longitude=None,
            plug_connected=False,
            charging_state="notReadyForCharging",
            charge_power_kw=0.0,
        )

    def test_trip_starts_then_ends_on_idle_odometer(self, db):
        import poller

        poller._prev_odometer = 10000.0

        with patch.object(__import__("config").settings, "poll_interval_seconds", 300):
            with patch.object(__import__("config").settings, "battery_capacity_kwh", 77.0):
                with patch.object(__import__("config").settings, "epa_rated_range_km", 410.0):
                    # Poll 1: odometer moves → trip starts via odometer fallback
                    s1 = self._portal_snap(T0, odometer_km=10005.0)
                    db.add(s1); db.flush()
                    with patch("webhook.fire"):
                        poller._update_trip(db, s1)
                    assert poller._active_trip_id is not None

                    # Poll 2 (5 min later): odometer still moving → trip stays open
                    s2 = self._portal_snap(T0 + timedelta(minutes=5), odometer_km=10010.0)
                    db.add(s2); db.flush()
                    with patch("webhook.fire"):
                        poller._update_trip(db, s2)
                    assert poller._active_trip_id is not None

                    # Simulate the car having parked: push last-move into the past so the
                    # idle threshold (max(600, 2*300)=600s) is exceeded.
                    poller._last_odometer_move_at = datetime.now(timezone.utc) - timedelta(seconds=601)

                    # Poll 3: odometer unchanged and idle long enough → trip ENDS
                    s3 = self._portal_snap(T0 + timedelta(minutes=10), odometer_km=10010.0)
                    db.add(s3); db.flush()
                    with patch("webhook.fire"):
                        poller._update_trip(db, s3)

        assert poller._active_trip_id is None, "Trip should end once odometer stalls"

    def test_trip_stays_open_while_odometer_moves(self, db):
        """A long drive (odometer keeps increasing) must not be ended by idle logic."""
        import poller

        poller._prev_odometer = 10000.0

        with patch.object(__import__("config").settings, "poll_interval_seconds", 300):
            odo = 10000.0
            for i in range(6):
                odo += 5.0
                s = self._portal_snap(T0 + timedelta(minutes=i * 5), odometer_km=odo)
                db.add(s); db.flush()
                with patch("webhook.fire"):
                    poller._update_trip(db, s)

        assert poller._active_trip_id is not None

    def test_idle_end_does_not_fire_before_threshold(self, db):
        """An odometer that just stalled (within threshold) keeps the trip open."""
        import poller

        poller._prev_odometer = 10000.0

        with patch.object(__import__("config").settings, "poll_interval_seconds", 300):
            with patch("webhook.fire"):
                s1 = self._portal_snap(T0, odometer_km=10005.0)
                db.add(s1); db.flush()
                poller._update_trip(db, s1)
                assert poller._active_trip_id is not None

                # Only a short time has passed since the last move (< 600s threshold).
                poller._last_odometer_move_at = datetime.now(timezone.utc) - timedelta(seconds=120)
                s2 = self._portal_snap(T0 + timedelta(minutes=2), odometer_km=10005.0)
                db.add(s2); db.flush()
                poller._update_trip(db, s2)

        assert poller._active_trip_id is not None
