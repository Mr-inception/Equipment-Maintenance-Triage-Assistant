import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportStatus(str, enum.Enum):
    open = "open"
    triaged = "triaged"
    closed = "closed"


class TriageStatus(str, enum.Enum):
    success = "success"
    retrieval_failed = "retrieval_failed"
    ai_failed = "ai_failed"


class FindingKind(str, enum.Enum):
    observation = "observation"
    possible_cause = "possible_cause"
    confirmed_finding = "confirmed_finding"


class FindingOrigin(str, enum.Enum):
    rule = "rule"  # deterministic threshold check
    ai = "ai"
    technician = "technician"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class WorkOrderStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"


def _enum(e):
    return Enum(e, native_enum=False, length=32)


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("equipment_type", "identifier", name="uq_equipment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_type: Mapped[str] = mapped_column(String(64))
    identifier: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reports: Mapped[list["IssueReport"]] = relationship(back_populates="equipment")


class IssueReport(Base):
    __tablename__ = "issue_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    issue_description: Mapped[str] = mapped_column(Text)
    operating_events: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[ReportStatus] = mapped_column(_enum(ReportStatus), default=ReportStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    equipment: Mapped[Equipment] = relationship(back_populates="reports")
    sensor_readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    triage_runs: Mapped[list["TriageRun"]] = relationship(back_populates="report")
    findings: Mapped[list["Finding"]] = relationship(back_populates="report")
    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="report")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("issue_reports.id"))
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # null = missing
    unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[IssueReport] = relationship(back_populates="sensor_readings")


class TriageRun(Base):
    __tablename__ = "triage_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("issue_reports.id"))
    status: Mapped[TriageStatus] = mapped_column(_enum(TriageStatus))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[IssueReport] = relationship(back_populates="triage_runs")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(
            "kind != 'confirmed_finding' OR origin = 'technician'",
            name="ck_confirmed_only_by_technician",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("issue_reports.id"))
    triage_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("triage_runs.id"), nullable=True)
    kind: Mapped[FindingKind] = mapped_column(_enum(FindingKind))
    origin: Mapped[FindingOrigin] = mapped_column(_enum(FindingOrigin))
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # citations: manual sections / events
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[IssueReport] = relationship(back_populates="findings")


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("issue_reports.id"))
    triage_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("triage_runs.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(_enum(Priority))
    status: Mapped[WorkOrderStatus] = mapped_column(
        _enum(WorkOrderStatus), default=WorkOrderStatus.draft
    )
    ai_draft: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # original, unedited
    decided_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    report: Mapped[IssueReport] = relationship(back_populates="work_orders")


class HistoryEvent(Base):
    __tablename__ = "history_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    report_id: Mapped[Optional[int]] = mapped_column(ForeignKey("issue_reports.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64), default="system")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
