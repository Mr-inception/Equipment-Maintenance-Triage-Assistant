import re
from dataclasses import asdict, dataclass, field
from typing import Optional

SEVERITY_ORDER = {"none": 0, "warning": 1, "critical": 2}
DATA_ISSUE_STATUSES = {"missing", "conflict", "unit_error", "implausible"}


@dataclass(frozen=True)
class Threshold:
    sensor: str
    label: str
    unit: str
    direction: str  # "above" or "below"
    warning: float
    critical: Optional[float]
    citation: str
    conflict_tol: float
    min_plausible: float
    max_plausible: float


_T = Threshold

# Limits taken from the manuals in knowledge_base/.
THRESHOLDS: dict[str, list[Threshold]] = {
    "pump": [
        _T("bearing_temp", "Bearing temperature", "C", "above", 85, 95, "PUMP-1.1", 5, -40, 300),
        _T("vibration", "Vibration velocity", "mm/s", "above", 7.1, 11.2, "PUMP-1.2", 1.0, 0, 100),
        _T("suction_pressure", "Suction pressure", "bar", "below", 0.5, None, "PUMP-1.3", 0.3, -1, 50),
    ],
    "compressor": [
        _T("discharge_temp", "Discharge temperature", "C", "above", 110, 120, "COMP-1.1", 5, -40, 300),
        _T("discharge_pressure", "Discharge pressure", "bar", "below", 6, None, "COMP-1.2", 0.5, 0, 50),
        _T("vibration", "Vibration velocity", "mm/s", "above", 7.1, None, "COMP-1.4", 1.0, 0, 100),
    ],
    "motor": [
        _T("winding_temp", "Winding temperature", "C", "above", 130, 150, "MOT-1.1", 5, -40, 300),
        _T("bearing_temp", "Bearing temperature", "C", "above", 85, 95, "MOT-1.5", 5, -40, 300),
        _T("vibration", "Vibration velocity", "mm/s", "above", 7.1, None, "MOT-1.3", 1.0, 0, 100),
        _T("current_imbalance_pct", "Phase current imbalance", "%", "above", 5, None, "MOT-1.4", 2, 0, 100),
    ],
}

_UNIT_ALIASES = {
    "c": "C", "degc": "C", "celsius": "C",
    "f": "F", "degf": "F", "fahrenheit": "F",
    "k": "K", "kelvin": "K",
    "bar": "bar", "psi": "psi", "kpa": "kPa",
    "mm/s": "mm/s", "in/s": "in/s", "ips": "in/s",
    "%": "%", "pct": "%", "percent": "%",
}

_CONVERT = {
    ("F", "C"): lambda v: (v - 32) * 5 / 9,
    ("K", "C"): lambda v: v - 273.15,
    ("psi", "bar"): lambda v: v * 0.0689476,
    ("kPa", "bar"): lambda v: v / 100,
    ("in/s", "mm/s"): lambda v: v * 25.4,
}


def normalize_sensor_name(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _canon_unit(unit: str) -> Optional[str]:
    key = unit.strip().lower().replace("\u00b0", "").replace(" ", "")
    return _UNIT_ALIASES.get(key)


def _disp(unit: str) -> str:
    return "degC" if unit == "C" else unit


@dataclass
class RuleResult:
    sensor: str
    label: str
    status: str    # ok | warning | critical | missing | conflict | unit_error | implausible | unknown_sensor
    severity: str  # none | warning | critical | unknown
    message: str
    value: Optional[float] = None
    values: list = field(default_factory=list)
    unit: Optional[str] = None
    limit: Optional[float] = None
    citation: Optional[str] = None
    notes: list = field(default_factory=list)


@dataclass
class RuleSummary:
    results: list
    overall_severity: str
    priority_floor: Optional[str]
    data_issue_count: int
    not_provided: list
    note: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _level(th: Threshold, v: float) -> str:
    if th.direction == "above":
        if th.critical is not None and v > th.critical:
            return "critical"
        if v > th.warning:
            return "warning"
    else:
        if th.critical is not None and v < th.critical:
            return "critical"
        if v < th.warning:
            return "warning"
    return "none"


def _prepare(th: Threshold, raw: dict):
    """Return (value_in_expected_unit | None, issue | None, note | None)."""
    v = raw.get("value")
    if v is None:
        return None, "missing", None
    unit = raw.get("unit")
    note = None
    if unit is None or str(unit).strip() == "":
        note = f"unit not given, assumed {_disp(th.unit)}"
    else:
        canon = _canon_unit(str(unit))
        if canon == th.unit:
            pass
        elif canon and (canon, th.unit) in _CONVERT:
            v = _CONVERT[(canon, th.unit)](v)
        else:
            return None, "unit_error", f"unsupported unit '{unit}' (expected {_disp(th.unit)})"
    if not (th.min_plausible <= v <= th.max_plausible):
        return None, "implausible", f"value {v:.1f} is outside the plausible range"
    return v, None, note


def _evaluate(th: Threshold, raws: list) -> RuleResult:
    vals, issues, notes = [], [], []
    for raw in raws:
        v, issue, note = _prepare(th, raw)
        if v is not None:
            vals.append(round(v, 2))
        if issue:
            issues.append((issue, note))
        if note and not issue:
            notes.append(note)

    unit = _disp(th.unit)
    base = dict(sensor=th.sensor, label=th.label, unit=unit, citation=th.citation)

    if not vals:
        kinds = [i for i, _ in issues]
        if "unit_error" in kinds:
            status = "unit_error"
        elif "implausible" in kinds:
            status = "implausible"
        else:
            status = "missing"
        detail = "; ".join(n for _, n in issues if n)
        msg = {
            "missing": f"{th.label} reading is missing, so this limit could not be checked.",
            "unit_error": f"{th.label} reading has an unusable unit ({detail}), so this limit could not be checked.",
            "implausible": f"{th.label} reading looks invalid ({detail}), so this limit could not be checked.",
        }[status]
        return RuleResult(status=status, severity="unknown", message=msg, notes=notes, **base)

    rep = max(vals) if th.direction == "above" else min(vals)
    levels = [_level(th, v) for v in vals]
    worst = max(levels, key=lambda lv: SEVERITY_ORDER[lv])
    if issues:
        notes.append(f"{len(issues)} other reading(s) ignored (missing or invalid)")
    limit = th.critical if worst == "critical" else th.warning
    word = "above" if th.direction == "above" else "below"

    if len(vals) > 1 and (max(vals) - min(vals)) > th.conflict_tol:
        listed = ", ".join(f"{v:.1f}" for v in vals)
        worst_txt = "no limit exceeded" if worst == "none" else f"worst reading is at {worst} level"
        return RuleResult(
            status="conflict",
            severity=worst,
            message=(
                f"{th.label} readings conflict ({listed} {unit}); {worst_txt}. "
                "Verify the sensors before relying on this value."
            ),
            value=rep, values=vals, limit=limit if worst != "none" else None, notes=notes, **base,
        )

    if worst == "none":
        msg = f"{th.label} {rep:.1f} {unit} is within limits."
        return RuleResult(status="ok", severity="none", message=msg, value=rep, values=vals, notes=notes, **base)

    msg = f"{th.label} {rep:.1f} {unit} is {word} the {worst} limit of {limit:g} {unit}."
    return RuleResult(status=worst, severity=worst, message=msg, value=rep, values=vals, limit=limit, notes=notes, **base)


def run_rules(equipment_type: str, readings: list) -> RuleSummary:
    thresholds = THRESHOLDS.get(equipment_type.strip().lower(), [])
    by_sensor = {t.sensor: t for t in thresholds}

    grouped: dict[str, list] = {}
    for r in readings:
        grouped.setdefault(normalize_sensor_name(r["name"]), []).append(r)

    results = []
    for name, raws in grouped.items():
        th = by_sensor.get(name)
        if th is None:
            results.append(
                RuleResult(
                    sensor=name, label=name, status="unknown_sensor", severity="unknown",
                    message=f"No threshold rule is defined for '{name}'; recorded as an observation only.",
                    values=[r.get("value") for r in raws],
                )
            )
        else:
            results.append(_evaluate(th, raws))

    not_provided = [t.sensor for t in thresholds if t.sensor not in grouped]
    overall = "none"
    for r in results:
        if r.severity in SEVERITY_ORDER and SEVERITY_ORDER[r.severity] > SEVERITY_ORDER[overall]:
            overall = r.severity
    issues = sum(1 for r in results if r.status in DATA_ISSUE_STATUSES)
    floor = {"critical": "high", "warning": "medium"}.get(overall)
    note = None
    if overall == "none" and issues:
        note = (
            f"No limit was exceeded, but {issues} sensor check(s) have missing, conflicting or invalid data, "
            "so this is not a clean bill of health."
        )
    return RuleSummary(results, overall, floor, issues, not_provided, note)
