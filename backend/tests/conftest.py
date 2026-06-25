"""
Shared pytest fixtures for the VW-Dash backend test suite.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db():
    """In-memory SQLite session with all tables created."""
    from database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def reset_poller_state():
    """Reset all poller module-level globals before every test."""
    import poller

    poller._active_trip_id = None
    poller._prev_parking_time = None
    poller._prev_odometer = None
    poller._trip_start_odometer = None
    poller._prev_lat = None
    poller._prev_lon = None
    poller._parking_time_unchanged_polls = 0
    poller._trip_point_count = 0
    poller._last_odometer_move_at = None
    poller._active_charging_session_id = None
    poller._prev_charging_state = None
    poller._prev_soc = None
    poller._charging_power_samples = []
    poller._prev_climatisation_state = None
    poller._prev_locked = None
    poller._prev_plug_connected = None
    yield
