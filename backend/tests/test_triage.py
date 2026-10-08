import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import llm
from app import models as m
from app import triage as triage_mod
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.retrieval import RetrievalError


@pytest.fixture()
def triage_env():
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
        "equipment_type": "pump",
        "identifier": "P-101",
        "issue_description": "Loud vibration and hot bearing housing since restart",
        "operating_events": [{"time": "2026-10-06T08:00", "event": "Restart after power cut"}],
        "sensor_readings": [
            {"name": "bearing_temp", "value": 97, "unit": "C"},
            {"name": "vibration", "value": 8.0, "unit": "mm/s"},
        ],
    }
    base.update(over)
    return base


def fake_ai(**over):
    base = {
        "possible_causes": [
            {
                "cause": "Bearing lubrication problem",
                "likelihood": "medium",
                "reasoning": "Bearing temperature is above the critical limit.",
                "evidence": ["PUMP-1.1", "SENSOR:bearing_temp"],
            },
            {
                "cause": "Misalignment after the restart",
                "likelihood": "low",
                "reasoning": "Vibration began after a restart event.",
                "evidence": ["PUMP-1.2", "EVENT-1"],
            },
        ],
        "follow_up_questions": [
            {"question": "When was the bearing last lubricated?", "why": "Lubrication is a common cause."}
        ],
        "inspection_steps": [
            {"step": "Isolate and lock out the motor before inspection.", "evidence": ["PUMP-2.1"]},
            {"step": "Check oil level and coupling alignment.", "evidence": ["PUMP-1.1"]},
        ],
        "suggested_priority": {"level": "high", "rationale": "Critical bearing temperature.", "evidence": ["PUMP-1.1"]},
        "work_order": {
            "title": "Inspect pump P-101 bearing",
            "description": "Investigate high bearing temperature and vibration.",
            "evidence": ["PUMP-1.1", "EVENT-1"],
        },
    }
    base.update(over)
    return json.dumps(base)


def make_report(client, **over):
    return client.post("/api/reports", json=payload(**over)).json()["id"]


def test_success_flow_creates_cited_causes_and_draft_work_order(triage_env, monkeypatch):
    client, Session = triage_env
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: fake_ai())
    rid = make_report(client)
    r = client.post(f"/api/reports/{rid}/triage")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    res = data["result"]
    assert len(res["possible_causes"]) == 2
    assert all(c["evidence"] for c in res["possible_causes"])
    assert res["work_order"]["status"] == "draft"
    assert "not confirmed findings" in res["disclaimer"]
    with Session() as db:
        kinds = [(f.kind, f.origin) for f in db.query(m.Finding).all()]
        assert kinds.count((m.FindingKind.possible_cause, m.FindingOrigin.ai)) == 2
        assert not any(k == m.FindingKind.confirmed_finding for k, _ in kinds)
        wo = db.query(m.WorkOrder).one()
        assert wo.status == m.WorkOrderStatus.draft
        assert wo.ai_draft["title"] == wo.title
        assert db.get(m.IssueReport, rid).status == m.ReportStatus.triaged


def test_uncited_and_invalid_citations_are_dropped_with_warning(triage_env, monkeypatch):
    client, Session = triage_env
    ai = fake_ai(
        possible_causes=[
            {"cause": "Made-up cause", "likelihood": "high", "reasoning": "x", "evidence": ["PUMP-9.9"]},
            {"cause": "Real cause", "likelihood": "medium", "reasoning": "y", "evidence": ["PUMP-1.1"]},
        ],
        inspection_steps=[{"step": "Do something uncited", "evidence": []}],
    )
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: ai)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "success"
    causes = data["result"]["possible_causes"]
    assert [c["cause"] for c in causes] == ["Real cause"]
    assert data["result"]["inspection_steps"] == []
    assert len(data["result"]["warnings"]) >= 2
    with Session() as db:
        assert db.query(m.Finding).filter(m.Finding.kind == m.FindingKind.possible_cause).count() == 1


def test_priority_never_below_rule_floor(triage_env, monkeypatch):
    client, Session = triage_env
    ai = fake_ai(suggested_priority={"level": "low", "rationale": "Seems minor.", "evidence": ["PUMP-1.1"]})
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: ai)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    pr = data["result"]["suggested_priority"]
    assert pr["level"] == "high" and pr["ai_level"] == "low" and pr["adjusted"] is True
    with Session() as db:
        assert db.query(m.WorkOrder).one().priority == m.Priority.high


def test_llm_failure_is_recorded_and_visible(triage_env, monkeypatch):
    client, Session = triage_env

    def boom(system, user, max_tokens=2500):
        raise llm.LLMError("boom")

    monkeypatch.setattr(llm, "complete", boom)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "ai_failed"
    assert "boom" in data["error_message"]
    assert data["result"]["retrieved"]
    with Session() as db:
        assert db.query(m.WorkOrder).count() == 0
        assert db.get(m.IssueReport, rid).status == m.ReportStatus.open
    runs = client.get(f"/api/reports/{rid}/triage-runs").json()
    assert runs[0]["status"] == "ai_failed"


def test_missing_api_key_message(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("sys", "user")
    assert exc.value.code == "no_api_key"
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_retrieval_failure_skips_ai(triage_env, monkeypatch):
    client, _ = triage_env

    def no_kb():
        raise RetrievalError("Knowledge base folder not found")

    def must_not_call(system, user, max_tokens=2500):
        raise AssertionError("LLM must not be called when retrieval fails")

    monkeypatch.setattr(triage_mod, "get_knowledge_base", no_kb)
    monkeypatch.setattr(llm, "complete", must_not_call)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "retrieval_failed"
    assert "Knowledge base" in data["error_message"]


def test_invalid_json_after_retry_fails_cleanly(triage_env, monkeypatch):
    client, Session = triage_env
    calls = []

    def junk(system, user, max_tokens=2500):
        calls.append(1)
        return "this is not json"

    monkeypatch.setattr(llm, "complete", junk)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "ai_failed"
    assert len(calls) == 2
    with Session() as db:
        assert db.query(m.WorkOrder).count() == 0


def test_equipment_type_without_manual_is_retrieval_failure(triage_env, monkeypatch):
    client, _ = triage_env

    def must_not_call(system, user, max_tokens=2500):
        raise AssertionError("LLM must not be called without manual coverage")

    monkeypatch.setattr(llm, "complete", must_not_call)
    rid = make_report(client, equipment_type="crane", identifier="C-1", sensor_readings=[])
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "retrieval_failed"
    assert "crane" in data["error_message"]


def test_triage_unknown_report_is_404(triage_env):
    client, _ = triage_env
    assert client.post("/api/reports/9999/triage").status_code == 404


def test_issue_description_is_a_valid_citation(triage_env, monkeypatch):
    client, _ = triage_env
    ai = fake_ai(
        possible_causes=[
            {
                "cause": "Misalignment after restart",
                "likelihood": "medium",
                "reasoning": "r",
                "evidence": ["ISSUE", "issue description"],
            }
        ]
    )
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: ai)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["result"]["possible_causes"][0]["evidence"] == ["ISSUE"]
    assert not any("unknown citation" in w for w in data["result"]["warnings"])


def test_citation_matching_is_tolerant():
    allowed = {
        "pump-1.1": "PUMP-1.1",
        "event-1": "EVENT-1",
        "sensor:bearing_temp": "SENSOR:bearing_temp",
        "issue": "ISSUE",
    }
    cases = [
        ("  PUMP-1.1  ", "PUMP-1.1"),
        ("[PUMP-1.1]", "PUMP-1.1"),
        ('"PUMP-1.1"', "PUMP-1.1"),
        ("(PUMP-1.1)", "PUMP-1.1"),
        ("PUMP-1.1.", "PUMP-1.1"),
        ("pump-1.1", "PUMP-1.1"),
        ("SENSOR: bearing_temp", "SENSOR:bearing_temp"),
        ("event 1", "EVENT-1"),
        ("event-1", "EVENT-1"),
        ("EVENT_1", "EVENT-1"),
        ("issue", "ISSUE"),
        ("issue description", "ISSUE"),
        ("issue_description", "ISSUE"),
        ("issue-description", "ISSUE"),
    ]
    for raw, expected in cases:
        valid, invalid = triage_mod._clean([raw], allowed)
        assert invalid == [], raw
        assert valid == [expected], raw
    valid, invalid = triage_mod._clean(["PUMP-9.9"], allowed)
    assert valid == [] and invalid == ["PUMP-9.9"]


def test_tolerant_citations_are_kept_and_unknown_ids_still_warned(triage_env, monkeypatch):
    client, _ = triage_env
    ai = fake_ai(
        possible_causes=[
            {
                "cause": "Lubrication",
                "likelihood": "medium",
                "reasoning": "r",
                "evidence": [
                    "  PUMP-1.1  ",
                    "[PUMP-1.1]",
                    '"SENSOR: bearing_temp"',
                    "(event 1)",
                    "EVENT_1.",
                    "issue-description",
                    "PUMP-9.9",
                ],
            }
        ]
    )
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: ai)
    rid = make_report(client)
    data = client.post(f"/api/reports/{rid}/triage").json()
    assert data["status"] == "success"
    evidence = data["result"]["possible_causes"][0]["evidence"]
    assert evidence == ["PUMP-1.1", "SENSOR:bearing_temp", "EVENT-1", "ISSUE"]
    assert any("PUMP-9.9" in w for w in data["result"]["warnings"])


def test_second_successful_run_does_not_create_second_draft(triage_env, monkeypatch):
    client, Session = triage_env
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: fake_ai())
    rid = make_report(client)
    first = client.post(f"/api/reports/{rid}/triage").json()
    wo_id = first["result"]["work_order"]["id"]
    edited = client.patch(
        f"/api/work-orders/{wo_id}",
        json={"edited_by": "Asha", "title": "Technician edited title"},
    )
    assert edited.status_code == 200
    second = client.post(f"/api/reports/{rid}/triage").json()
    assert second["status"] == "success"
    assert second["result"]["work_order"] == {"id": wo_id, "reused": True}
    prop = second["result"]["proposed_work_order"]
    assert prop["title"] and prop["description"] and prop["priority"] and prop["evidence"]
    with Session() as db:
        orders = db.query(m.WorkOrder).filter(m.WorkOrder.report_id == rid).all()
        assert len(orders) == 1
        assert orders[0].id == wo_id
        assert orders[0].title == "Technician edited title"


def test_confirmed_causes_stay_current_after_rerun(triage_env, monkeypatch):
    client, _ = triage_env
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: fake_ai())
    rid = make_report(client)
    client.post(f"/api/reports/{rid}/triage")
    report = client.get(f"/api/reports/{rid}").json()
    causes = [f for f in report["findings"] if f["kind"] == "possible_cause"]
    assert len(causes) == 2
    first_id, other_id = causes[0]["id"], causes[1]["id"]
    conf = client.post(f"/api/findings/{first_id}/confirm", json={"confirmed_by": "Asha"})
    assert conf.status_code == 201
    client.post(f"/api/reports/{rid}/triage")
    after = client.get(f"/api/reports/{rid}").json()
    by_id = {f["id"]: f for f in after["findings"]}
    assert by_id[first_id]["superseded"] is False
    assert by_id[other_id]["superseded"] is True
    new_causes = [
        f for f in after["findings"]
        if f["kind"] == "possible_cause" and f["id"] not in {first_id, other_id}
    ]
    assert new_causes
    assert all(f["superseded"] is False for f in new_causes)
    detail = client.get(f"/api/reports/{rid}").json()
    confirmed = [f for f in detail["findings"] if f["kind"] == "confirmed_finding"]
    assert confirmed and confirmed[0]["superseded"] is False


def test_rerun_after_approved_draft_creates_new_draft(triage_env, monkeypatch):
    client, Session = triage_env
    monkeypatch.setattr(llm, "complete", lambda system, user, max_tokens=2500: fake_ai())
    rid = make_report(client)
    first = client.post(f"/api/reports/{rid}/triage").json()
    wo_id = first["result"]["work_order"]["id"]
    assert client.post(f"/api/work-orders/{wo_id}/approve", json={"decided_by": "Asha"}).status_code == 200
    second = client.post(f"/api/reports/{rid}/triage").json()
    assert second["status"] == "success"
    assert second["result"]["work_order"]["id"] != wo_id
    assert second["result"]["work_order"].get("reused") is not True
    assert "proposed_work_order" not in second["result"]
    with Session() as db:
        orders = db.query(m.WorkOrder).filter(m.WorkOrder.report_id == rid).all()
        assert len(orders) == 2
        statuses = {o.status for o in orders}
        assert statuses == {m.WorkOrderStatus.approved, m.WorkOrderStatus.draft}