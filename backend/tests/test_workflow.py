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


def payload():
    return {
        "equipment_type": "pump",
        "identifier": "P-101",
        "issue_description": "Loud vibration and hot bearing housing since restart",
        "operating_events": [{"time": "2026-10-06T08:00", "event": "Restart after power cut"}],
        "sensor_readings": [{"name": "bearing_temp", "value": 97, "unit": "C"}],
    }


def seed(client, Session, priority="high"):
    created = client.post("/api/reports", json=payload()).json()
    rid = created["id"]
    with Session() as db:
        wo = m.WorkOrder(
            report_id=rid, title="Inspect pump P-101", description="Check bearing",
            priority=m.Priority(priority), ai_draft={"title": "Inspect pump P-101"},
        )
        cause = m.Finding(
            report_id=rid, kind=m.FindingKind.possible_cause, origin=m.FindingOrigin.ai,
            text="Bearing lubrication problem", evidence=[{"type": "manual", "id": "PUMP-1.1"}],
        )
        db.add_all([wo, cause])
        db.commit()
        return rid, wo.id, cause.id, created["equipment"]["id"]


def test_edit_draft_records_diff_in_history(env):
    client, Session = env
    rid, wid, _, eid = seed(client, Session)
    r = client.patch(
        f"/api/work-orders/{wid}",
        json={"edited_by": "Asha", "title": "Inspect P-101 bearing and coupling", "priority": "critical"},
    )
    assert r.status_code == 200
    assert r.json()["priority"] == "critical" and r.json()["status"] == "draft"
    events = client.get(f"/api/equipment/{eid}/history").json()["events"]
    edit = next(e for e in events if e["event_type"] == "work_order_edited")
    assert edit["actor"] == "Asha"
    assert edit["detail"]["changes"]["priority"] == {"from": "high", "to": "critical"}
    with Session() as db:
        assert db.get(m.WorkOrder, wid).ai_draft == {"title": "Inspect pump P-101"}


def test_edit_requires_a_change(env):
    client, Session = env
    _, wid, _, _ = seed(client, Session)
    r = client.patch(f"/api/work-orders/{wid}", json={"edited_by": "Asha"})
    assert r.status_code == 422


def test_approve_flow_and_locks_editing(env):
    client, Session = env
    _, wid, _, _ = seed(client, Session)
    r = client.post(f"/api/work-orders/{wid}/approve", json={"decided_by": "Asha"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved" and r.json()["decided_by"] == "Asha"
    assert r.json()["decided_at"]
    assert client.post(f"/api/work-orders/{wid}/approve", json={"decided_by": "Ravi"}).status_code == 409
    edit = client.patch(f"/api/work-orders/{wid}", json={"edited_by": "Asha", "title": "Changed title"})
    assert edit.status_code == 409


def test_reject_requires_reason(env):
    client, Session = env
    _, wid, _, _ = seed(client, Session)
    assert client.post(f"/api/work-orders/{wid}/reject", json={"decided_by": "Asha"}).status_code == 422
    r = client.post(
        f"/api/work-orders/{wid}/reject",
        json={"decided_by": "Asha", "reason": "Duplicate of an open order"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["rejection_reason"] == "Duplicate of an open order"


def test_cannot_approve_after_reject(env):
    client, Session = env
    _, wid, _, _ = seed(client, Session)
    client.post(f"/api/work-orders/{wid}/reject", json={"decided_by": "Asha", "reason": "Not needed"})
    assert client.post(f"/api/work-orders/{wid}/approve", json={"decided_by": "Asha"}).status_code == 409


def test_priority_below_rule_floor_warns(env):
    client, Session = env
    _, low_id, _, _ = seed(client, Session, priority="low")
    low = client.get(f"/api/work-orders/{low_id}").json()
    assert low["rule_priority_floor"] == "high" and len(low["warnings"]) == 1
    _, ok_id, _, _ = seed(client, Session, priority="high")
    assert client.get(f"/api/work-orders/{ok_id}").json()["warnings"] == []


def test_confirm_possible_cause_creates_technician_finding(env):
    client, Session = env
    rid, _, cid, _ = seed(client, Session)
    r = client.post(f"/api/findings/{cid}/confirm", json={"confirmed_by": "Asha", "notes": "Bearing worn"})
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "confirmed_finding" and data["origin"] == "technician"
    assert {"type": "finding", "id": cid} in data["evidence"]
    with Session() as db:
        assert db.get(m.Finding, cid).kind == m.FindingKind.possible_cause  # original preserved


def test_cannot_confirm_twice(env):
    client, Session = env
    _, _, cid, _ = seed(client, Session)
    client.post(f"/api/findings/{cid}/confirm", json={"confirmed_by": "Asha"})
    assert client.post(f"/api/findings/{cid}/confirm", json={"confirmed_by": "Asha"}).status_code == 409


def test_cannot_confirm_an_observation(env):
    client, Session = env
    rid, _, _, _ = seed(client, Session)
    with Session() as db:
        obs = db.query(m.Finding).filter(
            m.Finding.report_id == rid, m.Finding.kind == m.FindingKind.observation
        ).first()
        obs_id = obs.id
    assert client.post(f"/api/findings/{obs_id}/confirm", json={"confirmed_by": "Asha"}).status_code == 409


def test_technician_adds_confirmed_finding(env):
    client, Session = env
    rid, _, _, _ = seed(client, Session)
    r = client.post(
        f"/api/reports/{rid}/findings",
        json={"kind": "confirmed_finding", "text": "Coupling bolts loose", "recorded_by": "Asha",
              "evidence_note": "Found during walk-down"},
    )
    assert r.status_code == 201
    assert r.json()["origin"] == "technician" and r.json()["kind"] == "confirmed_finding"


def test_technician_cannot_add_possible_cause(env):
    client, Session = env
    rid, _, _, _ = seed(client, Session)
    r = client.post(
        f"/api/reports/{rid}/findings",
        json={"kind": "possible_cause", "text": "Maybe something", "recorded_by": "Asha"},
    )
    assert r.status_code == 422


def test_equipment_history_aggregates(env):
    client, Session = env
    rid, wid, cid, eid = seed(client, Session)
    client.post(f"/api/findings/{cid}/confirm", json={"confirmed_by": "Asha"})
    client.post(f"/api/work-orders/{wid}/approve", json={"decided_by": "Asha"})
    h = client.get(f"/api/equipment/{eid}/history").json()
    assert h["equipment"]["identifier"] == "P-101"
    assert len(h["reports"]) == 1 and len(h["work_orders"]) == 1
    assert len(h["confirmed_findings"]) == 1
    types = {e["event_type"] for e in h["events"]}
    assert {"report_created", "rules_evaluated", "finding_confirmed", "work_order_approved"} <= types


def test_equipment_list_has_report_counts(env):
    client, Session = env
    seed(client, Session)
    rows = client.get("/api/equipment").json()
    assert rows[0]["identifier"] == "P-101" and rows[0]["report_count"] == 1


def test_unknown_work_order_is_404(env):
    client, _ = env
    assert client.get("/api/work-orders/9999").status_code == 404
    assert client.post("/api/work-orders/9999/approve", json={"decided_by": "A"}).status_code == 404
