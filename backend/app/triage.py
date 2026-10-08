import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from . import llm
from . import models as m
from .retrieval import RetrievalError, get_knowledge_base
from .rules import run_rules

logger = logging.getLogger("triage.workflow")

PRIORITY_ORDER = ["low", "medium", "high", "critical"]
DISCLAIMER = (
    "AI suggestions are possible causes only, not confirmed findings. "
    "A technician must verify, edit and approve any work order."
)

SYSTEM_PROMPT = """You are a maintenance triage assistant that supports human technicians. You never control equipment and you never approve work.

Rules:
- Use ONLY the information in the report, the sensor results and the manual excerpts provided. Do not invent readings, events or manual content.
- Possible causes are hypotheses, not confirmed findings. Phrase them cautiously and never state a cause as certain.
- Every possible cause, inspection step, priority and work order draft must cite evidence using only the IDs provided: manual section IDs (for example PUMP-1.1), event IDs (EVENT-1), sensor IDs (SENSOR:bearing_temp), or ISSUE for the reported issue description.
- Where sensor data is missing, conflicting or invalid, say so in your reasoning and ask a follow-up question about it.
- Ask 2 to 5 targeted follow-up questions that would help narrow down the cause.
- Inspection steps must be safe: when hands-on work is needed, the first step must be to isolate and lock out the equipment, citing the safety section if provided.
- The priority must be one of low, medium, high, critical. The system enforces a minimum priority based on deterministic threshold checks.
- Reply with a single JSON object and nothing else. No markdown fences."""

SCHEMA_TEXT = """Return JSON with exactly this shape:
{
  "possible_causes": [{"cause": "...", "likelihood": "low|medium|high", "reasoning": "...", "evidence": ["PUMP-1.1", "EVENT-1", "SENSOR:bearing_temp"]}],
  "follow_up_questions": [{"question": "...", "why": "..."}],
  "inspection_steps": [{"step": "...", "evidence": ["..."]}],
  "suggested_priority": {"level": "low|medium|high|critical", "rationale": "...", "evidence": ["..."]},
  "work_order": {"title": "...", "description": "...", "evidence": ["..."]}
}"""


def _lower(v):
    return v.strip().lower() if isinstance(v, str) else v


class Cause(BaseModel):
    cause: str = Field(min_length=3)
    likelihood: Literal["low", "medium", "high"] = "medium"
    reasoning: str = ""
    evidence: list[str] = Field(default_factory=list)

    @field_validator("likelihood", mode="before")
    @classmethod
    def _norm(cls, v):
        return _lower(v)


class Question(BaseModel):
    question: str = Field(min_length=3)
    why: str = ""


class Step(BaseModel):
    step: str = Field(min_length=3)
    evidence: list[str] = Field(default_factory=list)


class PriorityOut(BaseModel):
    level: Literal["low", "medium", "high", "critical"]
    rationale: str = ""
    evidence: list[str] = Field(default_factory=list)

    @field_validator("level", mode="before")
    @classmethod
    def _norm(cls, v):
        return _lower(v)


class WorkOrderOut(BaseModel):
    title: str = Field(min_length=3)
    description: str = Field(min_length=3)
    evidence: list[str] = Field(default_factory=list)


class AIResult(BaseModel):
    possible_causes: list[Cause] = Field(default_factory=list)
    follow_up_questions: list[Question] = Field(default_factory=list)
    inspection_steps: list[Step] = Field(default_factory=list)
    suggested_priority: PriorityOut
    work_order: WorkOrderOut


def _extract_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in reply")
    return json.loads(t[start : end + 1])


def _retrieve(kb, report, etype, summary, events) -> list[dict]:
    if etype not in kb.equipment_types():
        raise RetrievalError(
            f"No manual is available for equipment type '{etype}'. "
            f"Available types: {', '.join(kb.equipment_types())}."
        )
    parts = [report.issue_description] + [str(e.get("event", "")) for e in events]
    parts += [r.label for r in summary.results if r.severity in ("warning", "critical")]

    selected: list[dict] = []
    seen: set[str] = set()

    def add(chunk, reason, score=None):
        if chunk.id not in seen:
            seen.add(chunk.id)
            selected.append({"chunk": chunk, "reason": reason, "score": score})

    for h in kb.search(" ".join(parts), equipment_type=etype, top_k=6):
        add(h.chunk, "search match", h.score)
    by_id = {c.id: c for c in kb.chunks}
    for r in summary.results:
        if r.severity in ("warning", "critical") and r.citation in by_id:
            add(by_id[r.citation], "threshold exceeded")
    if not selected:
        raise RetrievalError("No relevant manual sections were found for this report.")
    for c in kb.chunks:
        if c.equipment_type == etype and c.id.endswith("-2.1"):
            add(c, "safety procedure")
    return selected


def _build_prompt(report, eq, summary, selected, events) -> str:
    lines = [
        f"Equipment: {eq.equipment_type} {eq.identifier}",
        "",
        "Issue description (cite as ISSUE):",
        report.issue_description,
        "",
        "Recent operating events:",
    ]
    if events:
        for i, e in enumerate(events, 1):
            lines.append(f"EVENT-{i} [{e.get('time') or 'time unknown'}]: {e.get('event', '')}")
    else:
        lines.append("(none reported)")
    lines += ["", "Sensor results (deterministic checks already applied):"]
    if summary.results:
        for r in summary.results:
            lines.append(
                f"SENSOR:{r.sensor} | status={r.status} | readings={r.values} {r.unit or ''} | {r.message}"
            )
    else:
        lines.append("(no sensor readings provided)")
    if summary.not_provided:
        lines.append("No reading provided for: " + ", ".join(summary.not_provided))
    lines.append(
        f"Deterministic overall severity: {summary.overall_severity}; "
        f"minimum priority: {summary.priority_floor or 'none'}"
    )
    lines += ["", "Manual sections (cite by ID):"]
    for s in selected:
        c = s["chunk"]
        lines.append(f"[{c.id}] {c.title}: {c.text}")
    lines += ["", SCHEMA_TEXT]
    return "\n".join(lines)


_WRAPPERS = {"[": "]", "(": ")", "{": "}", '"': '"', "'": "'"}


def _normalize_citation(raw) -> str:
    s = str(raw).strip()
    changed = True
    while s and changed:
        changed = False
        s = s.strip()
        if len(s) >= 2 and s[0] in _WRAPPERS and s[-1] == _WRAPPERS[s[0]]:
            s = s[1:-1]
            changed = True
            continue
        stripped = s.rstrip(".,;:!?")
        if stripped != s:
            s = stripped
            changed = True
    s = s.lower().strip()
    s = re.sub(r"\s*:\s*", ":", s)
    s = re.sub(r"\s+", " ", s).strip()
    compact = re.sub(r"[\s_-]+", "", s)
    if compact in {"issue", "issuedescription"}:
        return "issue"
    m = re.fullmatch(r"event[\s_-]*(\d+)", s)
    if m:
        return f"event-{m.group(1)}"
    return re.sub(r"\s+", "", s)


def _clean(ids, allowed: dict) -> tuple[list, list]:
    valid, invalid = [], []
    for raw in ids or []:
        canon = allowed.get(_normalize_citation(raw))
        if canon is None:
            invalid.append(str(raw))
        elif canon not in valid:
            valid.append(canon)
    return valid, invalid


def _evidence_objs(ids, event_texts: dict) -> list:
    out = []
    for i in ids:
        if i == "ISSUE":
            out.append({"type": "report", "id": "ISSUE"})
        elif i.startswith("EVENT-"):
            out.append({"type": "event", "id": i, "text": event_texts.get(i, "")})
        elif i.startswith("SENSOR:"):
            out.append({"type": "sensor", "name": i.split(":", 1)[1]})
        else:
            out.append({"type": "manual", "id": i})
    return out


def run_detail(run: m.TriageRun) -> dict:
    return {
        "id": run.id,
        "report_id": run.report_id,
        "status": run.status.value,
        "error_message": run.error_message,
        "model": run.model,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "result": run.result,
    }


def _fail(db: Session, report, status: str, message: str, retrieved: list, model) -> dict:
    run = m.TriageRun(
        report_id=report.id,
        status=m.TriageStatus(status),
        error_message=message,
        model=model,
        result={"retrieved": retrieved, "disclaimer": DISCLAIMER} if retrieved else None,
    )
    db.add(run)
    db.add(
        m.HistoryEvent(
            equipment_id=report.equipment_id, report_id=report.id, event_type="triage_failed",
            actor="system", detail={"status": status, "error": message},
        )
    )
    db.commit()
    logger.error("Triage failed for report %s (%s): %s", report.id, status, message)
    return run_detail(run)


def run_triage(db: Session, report_id: int) -> dict:
    report = db.get(m.IssueReport, report_id)
    if report is None:
        raise LookupError(f"Report {report_id} not found")
    eq = report.equipment
    etype = eq.equipment_type
    events = report.operating_events or []
    readings = sorted(report.sensor_readings, key=lambda r: r.id)
    summary = run_rules(etype, [{"name": r.name, "value": r.value, "unit": r.unit} for r in readings])

    # 1. Retrieval
    try:
        selected = _retrieve(get_knowledge_base(), report, etype, summary, events)
    except RetrievalError as exc:
        return _fail(db, report, "retrieval_failed", str(exc), [], None)
    retrieved = [
        {"id": s["chunk"].id, "title": s["chunk"].title, "reason": s["reason"], "score": s["score"]}
        for s in selected
    ]

    # 2. AI call (one retry if the reply is not valid JSON)
    prompt = _build_prompt(report, eq, summary, selected, events)
    ai, last_err = None, ""
    for attempt in range(2):
        text = prompt
        if attempt:
            text += (
                f"\n\nYour previous reply was not valid JSON for this schema ({last_err}). "
                "Reply again with ONLY the JSON object."
            )
        try:
            raw = llm.complete(SYSTEM_PROMPT, text)
        except llm.LLMError as exc:
            return _fail(db, report, "ai_failed", str(exc), retrieved, llm.model_name())
        try:
            ai = AIResult.model_validate(_extract_json(raw))
            break
        except (ValueError, ValidationError) as exc:
            last_err = str(exc)[:200]
            logger.warning("AI reply invalid (attempt %d): %s", attempt + 1, last_err)
    if ai is None:
        return _fail(
            db, report, "ai_failed",
            "The AI reply could not be understood (invalid format). Try again.",
            retrieved, llm.model_name(),
        )

    # 3. Citation validation
    allowed = {s["chunk"].id.lower(): s["chunk"].id for s in selected}
    event_texts = {}
    allowed["issue"] = "ISSUE"
    for i, e in enumerate(events, 1):
        allowed[f"event-{i}"] = f"EVENT-{i}"
        event_texts[f"EVENT-{i}"] = str(e.get("event", ""))
    for r in summary.results:
        allowed[f"sensor:{r.sensor}".lower()] = f"SENSOR:{r.sensor}"

    warnings: list[str] = []
    causes, steps = [], []
    for c in ai.possible_causes:
        valid, invalid = _clean(c.evidence, allowed)
        if invalid:
            warnings.append(f"Removed unknown citation(s) {invalid} from cause '{c.cause[:60]}'.")
        if not valid:
            warnings.append(f"Dropped cause '{c.cause[:60]}' because it had no valid citation.")
            continue
        causes.append(
            {"cause": c.cause.strip(), "likelihood": c.likelihood,
             "reasoning": c.reasoning.strip(), "evidence": valid}
        )
    for s in ai.inspection_steps:
        valid, invalid = _clean(s.evidence, allowed)
        if invalid:
            warnings.append(f"Removed unknown citation(s) {invalid} from step '{s.step[:60]}'.")
        if not valid:
            warnings.append(f"Dropped inspection step '{s.step[:60]}' because it had no valid citation.")
            continue
        steps.append({"step": s.step.strip(), "evidence": valid})
    if not causes and not steps:
        return _fail(
            db, report, "ai_failed",
            "The AI reply contained no suggestions with valid citations, so it was discarded.",
            retrieved, llm.model_name(),
        )
    questions = [{"question": q.question.strip(), "why": q.why.strip()} for q in ai.follow_up_questions]

    # 4. Priority: AI may raise, never lower, the rule-based minimum
    p_valid, _ = _clean(ai.suggested_priority.evidence, allowed)
    if not p_valid:
        warnings.append("The priority rationale had no valid citation.")
    ai_level = ai.suggested_priority.level
    floor = summary.priority_floor
    final, adjusted = ai_level, False
    if floor and PRIORITY_ORDER.index(floor) > PRIORITY_ORDER.index(ai_level):
        final, adjusted = floor, True
        warnings.append(
            f"Priority raised from {ai_level} to {floor} because deterministic threshold checks require at least {floor}."
        )
    wo_valid, _ = _clean(ai.work_order.evidence, allowed)
    if not wo_valid:
        warnings.append("The work order draft had no valid citation.")

    # 5. Persist
    run = m.TriageRun(
        report_id=report.id, status=m.TriageStatus.success, model=llm.model_name(), result={}
    )
    db.add(run)
    db.flush()

    for c in causes:
        text = f"{c['cause']} (likelihood: {c['likelihood']})"
        if c["reasoning"]:
            text += f". {c['reasoning']}"
        db.add(
            m.Finding(
                report_id=report.id, triage_run_id=run.id,
                kind=m.FindingKind.possible_cause, origin=m.FindingOrigin.ai,
                text=text, evidence=_evidence_objs(c["evidence"], event_texts),
            )
        )

    description = ai.work_order.description.strip()
    if steps:
        description += "\n\nSuggested inspection steps:\n" + "\n".join(
            f"{i}. {s['step']}" for i, s in enumerate(steps, 1)
        )
    proposed = {
        "title": ai.work_order.title.strip()[:200],
        "description": description,
        "priority": final,
        "evidence": wo_valid,
    }
    existing_draft = (
        db.query(m.WorkOrder)
        .filter(
            m.WorkOrder.report_id == report.id,
            m.WorkOrder.status == m.WorkOrderStatus.draft,
        )
        .order_by(m.WorkOrder.id.desc())
        .first()
    )
    if existing_draft is not None:
        wo = existing_draft
        wo_result = {"id": wo.id, "reused": True}
    else:
        wo = m.WorkOrder(
            report_id=report.id, triage_run_id=run.id,
            title=proposed["title"], description=proposed["description"],
            priority=m.Priority(final), status=m.WorkOrderStatus.draft,
            ai_draft={
                "title": proposed["title"], "description": proposed["description"],
                "priority": final, "ai_suggested_priority": ai_level,
                "evidence": _evidence_objs(wo_valid, event_texts),
            },
        )
        db.add(wo)
        db.flush()
        wo_result = {
            "id": wo.id, "title": wo.title, "status": wo.status.value,
            "priority": final, "evidence": wo_valid,
        }

    run.result = {
        "retrieved": retrieved,
        "possible_causes": causes,
        "follow_up_questions": questions,
        "inspection_steps": steps,
        "suggested_priority": {
            "level": final, "ai_level": ai_level, "floor": floor, "adjusted": adjusted,
            "rationale": ai.suggested_priority.rationale.strip(), "evidence": p_valid,
        },
        "work_order": wo_result,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
    if existing_draft is not None:
        run.result["proposed_work_order"] = proposed
    report.status = m.ReportStatus.triaged
    db.add(
        m.HistoryEvent(
            equipment_id=report.equipment_id, report_id=report.id, event_type="triage_completed",
            actor="system", detail={"run_id": run.id, "priority": final, "work_order_id": wo.id},
        )
    )
    db.commit()
    logger.info("Triage %s completed for report %s (priority %s)", run.id, report.id, final)
    return run_detail(run)
