import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), Session
    app.dependency_overrides.clear()


def payload(**over):
    base = {
        "equipment_type": "Pump",
        "identifier": "p-101",
        "issue_description": "Loud vibration and hot bearing housing since restart",
        "operating_events": [{"time": "2026-10-06T08:00", "event": "Restart after power cut"}],
        "sensor_readings": [
            {"name": "bearing_temp", "value": 97, "unit": "C"},
            {"name": "vibration", "value": 3.2, "unit": "mm/s"},
        ],
    }
    base.update(over)
    return base


def test_create_report_runs_rules_and_stores_observations(env):
    client, _ = env
    r = client.post("/api/reports", json=payload())
    assert r.status_code == 201
    data = r.json()
    assert data["equipment"]["identifier"] == "P-101"
    assert data["equipment"]["equipment_type"] == "pump"
    assert data["rules"]["overall_severity"] == "critical"
    assert data["rules"]["priority_floor"] == "high"
    assert len(data["findings"]) == 2
    assert all(f["origin"] == "rule" and f["kind"] == "observation" for f in data["findings"])


def test_same_equipment_is_reused(env):
    client, Session = env
    client.post("/api/reports", json=payload(identifier="p-101"))
    client.post("/api/reports", json=payload(identifier="P-101"))
    with Session() as db:
        assert db.query(m.Equipment).count() == 1
        assert db.query(m.IssueReport).count() == 2


def test_get_report_recomputes_same_rules(env):
    client, _ = env
    created = client.post("/api/reports", json=payload()).json()
    fetched = client.get(f"/api/reports/{created['id']}").json()
    assert fetched["rules"] == created["rules"]


def test_unknown_report_is_404(env):
    client, _ = env
    assert client.get("/api/reports/9999").status_code == 404


def test_validation_rejects_short_description(env):
    client, _ = env
    r = client.post("/api/reports", json=payload(issue_description="x"))
    assert r.status_code == 422


def test_missing_sensor_value_is_flagged_in_response(env):
    client, _ = env
    body = payload(
        sensor_readings=[
            {"name": "bearing_temp", "value": None, "unit": "C"},
            {"name": "vibration", "value": 3.2, "unit": "mm/s"},
        ]
    )
    data = client.post("/api/reports", json=body).json()
    bt = next(x for x in data["rules"]["results"] if x["sensor"] == "bearing_temp")
    assert bt["status"] == "missing" and bt["severity"] == "unknown"
    assert data["rules"]["overall_severity"] == "none"
    assert data["rules"]["data_issue_count"] == 1
    assert "not a clean bill" in data["rules"]["note"]


def test_history_events_are_written(env):
    client, Session = env
    client.post("/api/reports", json=payload())
    with Session() as db:
        types = sorted(e.event_type for e in db.query(m.HistoryEvent).all())
    assert types == ["report_created", "rules_evaluated"]
