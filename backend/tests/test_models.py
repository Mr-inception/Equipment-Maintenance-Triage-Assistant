import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


def make_report(db):
    eq = m.Equipment(equipment_type="pump", identifier="P-101")
    db.add(eq)
    db.flush()
    rep = m.IssueReport(
        equipment_id=eq.id,
        issue_description="Loud vibration at startup",
        operating_events=[{"time": "2026-10-06T08:00", "event": "Restart after power cut"}],
    )
    db.add(rep)
    db.commit()
    return eq, rep


def test_report_with_missing_sensor_value(db):
    _, rep = make_report(db)
    db.add(m.SensorReading(report_id=rep.id, name="bearing_temp", value=None, unit="C"))
    db.commit()
    assert rep.sensor_readings[0].value is None


def test_equipment_identity_is_unique(db):
    make_report(db)
    db.add(m.Equipment(equipment_type="pump", identifier="P-101"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_ai_cannot_create_confirmed_finding(db):
    _, rep = make_report(db)
    db.add(
        m.Finding(
            report_id=rep.id,
            kind=m.FindingKind.confirmed_finding,
            origin=m.FindingOrigin.ai,
            text="Bearing failure",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_technician_can_confirm_finding(db):
    _, rep = make_report(db)
    db.add(
        m.Finding(
            report_id=rep.id,
            kind=m.FindingKind.confirmed_finding,
            origin=m.FindingOrigin.technician,
            text="Worn bearing confirmed on inspection",
        )
    )
    db.commit()
    assert rep.findings[0].kind == m.FindingKind.confirmed_finding


def test_work_order_defaults_to_draft(db):
    _, rep = make_report(db)
    wo = m.WorkOrder(
        report_id=rep.id,
        title="Inspect pump P-101",
        description="Check bearings and alignment",
        priority=m.Priority.high,
    )
    db.add(wo)
    db.commit()
    assert wo.status == m.WorkOrderStatus.draft


def test_history_event_is_stored(db):
    eq, rep = make_report(db)
    db.add(m.HistoryEvent(equipment_id=eq.id, report_id=rep.id, event_type="report_created"))
    db.commit()
    assert db.query(m.HistoryEvent).count() == 1
