import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.database import Base
from app.demo import seed_demo_data


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_seeds_three_reports(factory):
    created = seed_demo_data(factory)
    assert len(created) == 3
    with factory() as db:
        assert db.query(m.IssueReport).count() == 3


def test_seeding_is_idempotent(factory):
    seed_demo_data(factory)
    assert seed_demo_data(factory) == []
    with factory() as db:
        assert db.query(m.IssueReport).count() == 3


def test_demo_findings_are_rule_observations_only(factory):
    seed_demo_data(factory)
    with factory() as db:
        findings = db.query(m.Finding).all()
        assert findings
        assert all(
            f.kind == m.FindingKind.observation and f.origin == m.FindingOrigin.rule for f in findings
        )