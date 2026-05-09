from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Float, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class VehicleSnapshot(Base):
    """Periodic snapshot of all vehicle telemetry."""
    __tablename__ = "vehicle_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Battery / range
    soc_pct: Mapped[Optional[float]] = mapped_column(Float)
    range_km: Mapped[Optional[float]] = mapped_column(Float)
    range_miles: Mapped[Optional[float]] = mapped_column(Float)

    # Charging
    charging_state: Mapped[Optional[str]] = mapped_column(String(32))
    charge_power_kw: Mapped[Optional[float]] = mapped_column(Float)
    charge_rate_km_h: Mapped[Optional[float]] = mapped_column(Float)
    charge_type: Mapped[Optional[str]] = mapped_column(String(16))
    remaining_charge_time_min: Mapped[Optional[int]] = mapped_column(Integer)
    target_soc_pct: Mapped[Optional[float]] = mapped_column(Float)

    # Location
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    parking_time: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Climate / cabin
    outdoor_temp_c: Mapped[Optional[float]] = mapped_column(Float)
    cabin_temp_c: Mapped[Optional[float]] = mapped_column(Float)
    battery_temp_c: Mapped[Optional[float]] = mapped_column(Float)
    climatisation_state: Mapped[Optional[str]] = mapped_column(String(32))

    # Vehicle status
    locked: Mapped[Optional[bool]] = mapped_column(Boolean)
    odometer_km: Mapped[Optional[float]] = mapped_column(Float)
    plug_connected: Mapped[Optional[bool]] = mapped_column(Boolean)


class ChargingSession(Base):
    """One completed or in-progress charging session."""
    __tablename__ = "charging_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    soc_start_pct: Mapped[Optional[float]] = mapped_column(Float)
    soc_end_pct: Mapped[Optional[float]] = mapped_column(Float)
    kwh_added: Mapped[Optional[float]] = mapped_column(Float)
    kwh_added_real: Mapped[Optional[float]] = mapped_column(Float)
    range_added_km: Mapped[Optional[float]] = mapped_column(Float)
    peak_power_kw: Mapped[Optional[float]] = mapped_column(Float)
    avg_power_kw: Mapped[Optional[float]] = mapped_column(Float)
    charge_type: Mapped[Optional[str]] = mapped_column(String(16))
    cost: Mapped[Optional[float]] = mapped_column(Float)
    cost_per_kwh: Mapped[Optional[float]] = mapped_column(Float)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    location_name: Mapped[Optional[str]] = mapped_column(String(256))


class Trip(Base):
    """One drive from point A to B."""
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    distance_km: Mapped[Optional[float]] = mapped_column(Float)
    distance_miles: Mapped[Optional[float]] = mapped_column(Float)
    soc_start_pct: Mapped[Optional[float]] = mapped_column(Float)
    soc_end_pct: Mapped[Optional[float]] = mapped_column(Float)
    kwh_used: Mapped[Optional[float]] = mapped_column(Float)
    efficiency_kwh_100km: Mapped[Optional[float]] = mapped_column(Float)
    avg_speed_kmh: Mapped[Optional[float]] = mapped_column(Float)
    start_lat: Mapped[Optional[float]] = mapped_column(Float)
    start_lon: Mapped[Optional[float]] = mapped_column(Float)
    end_lat: Mapped[Optional[float]] = mapped_column(Float)
    end_lon: Mapped[Optional[float]] = mapped_column(Float)
    outdoor_temp_c: Mapped[Optional[float]] = mapped_column(Float)
    start_address: Mapped[Optional[str]] = mapped_column(String(256))
    end_address: Mapped[Optional[str]] = mapped_column(String(256))


class TripPoint(Base):
    """GPS breadcrumb recorded during an active trip."""
    __tablename__ = "trip_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(Integer, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)


class Event(Base):
    """State-change events emitted by the poller (trip started, charging ended, etc.)."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    detail: Mapped[Optional[str]] = mapped_column(Text)  # JSON string for extra context
