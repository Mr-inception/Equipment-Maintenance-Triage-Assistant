from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models as m
from .rules import run_rules
from .triage import PRIORITY_ORDER


class ConflictError(Exception):
    """The requested action is not allowed in the current state."""


def _iso(dt):
    return dt.isoformat() if dt else None


def _rule_floor(wo: m.WorkOrder):
    report = wo.report
    readings = [{"name": r.name, "value": r.value, "unit": r.unit} for r in report.sensor_readings]
    return run_rules(report.equipment.equipment_type, readings).priority_floor


def work_order_detail(wo: m.WorkOrder) -> dict:
    floor = _rule_floor(wo)
    warnings = []
    if floor and PRIORITY_ORDER.index(wo.priority.value) < PRIORITY_ORDER.index(floor):
        warnings.append(
            f"Priority '{wo.priority.value}' is below the minimum '{floor}' required by the "
            "deterministic threshold checks. Confirm this is intentional before approving."
        )
    return {
        "id": wo.id,
        "report_id": wo.report_id,
        "triage_run_id": wo.triage_run_id,
        "title": wo.title,
        "description": wo.description,
        "priority": wo.priority.value,
        "status": wo.status.value,
        "rule_priority_floor": floor,
        "ai_draft": wo.ai_draft,
        "decided_by": wo.decided_by,
        "decided_at": _iso(wo.decided_at),
        "rejection_reason": wo.rejection_reason,
        "created_at": _iso(wo.created_at),
        "updated_at": _iso(wo.updated_at),
        "warnings": warnings,
    }


def _history(db: Session, wo: m.WorkOrder, event_type: str, actor: str, detail: dict) -> None:
    db.add(
        m.HistoryEvent(
            equipment_id=wo.report.equipment_id, report_id=wo.report_id,
            event_type=event_type, actor=actor, detail={"work_order_id": wo.id, **detail},
        )
    )


def _require_draft(wo: m.WorkOrder) -> None:
    if wo.status != m.WorkOrderStatus.draft:
        raise ConflictError(
            f"Work order is already {wo.status.value} and can no longer be changed."
        )


def edit_work_order(db: Session, wo: m.WorkOrder, changes: dict, edited_by: str) -> m.WorkOrder:
    _require_draft(wo)
    diff = {}
    for field in ("title", "description", "priority"):
        new = changes.get(field)
        if new is None:
            continue
        old = getattr(wo, field)
        old_cmp = old.value if field == "priority" else old
        if new == old_cmp:
            continue
        diff[field] = {"from": old_cmp, "to": new}
        setattr(wo, field, m.Priority(new) if field == "priority" else new)
    if diff:
        _history(db, wo, "work_order_edited", edited_by, {"changes": diff})
    db.commit()
    return wo


def approve_work_order(db: Session, wo: m.WorkOrder, decided_by: str) -> m.WorkOrder:
    _require_draft(wo)
    wo.status = m.WorkOrderStatus.approved
    wo.decided_by = decided_by
    wo.decided_at = datetime.now(timezone.utc)
    _history(db, wo, "work_order_approved", decided_by, {"priority": wo.priority.value})
    db.commit()
    return wo


def reject_work_order(db: Session, wo: m.WorkOrder, decided_by: str, reason: str) -> m.WorkOrder:
    _require_draft(wo)
    wo.status = m.WorkOrderStatus.rejected
    wo.decided_by = decided_by
    wo.decided_at = datetime.now(timezone.utc)
    wo.rejection_reason = reason
    _history(db, wo, "work_order_rejected", decided_by, {"reason": reason})
    db.commit()
    return wo
