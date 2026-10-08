import pytest

from app.rules import run_rules


def one(summary, sensor):
    return next(r for r in summary.results if r.sensor == sensor)


def test_within_limits_is_ok():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 60, "unit": "C"}])
    r = one(s, "bearing_temp")
    assert r.status == "ok" and r.severity == "none"
    assert s.overall_severity == "none" and s.priority_floor is None


def test_warning_above_limit():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 90, "unit": "C"}])
    r = one(s, "bearing_temp")
    assert r.status == "warning" and r.citation == "PUMP-1.1" and r.limit == 85


def test_critical_above_limit():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 96, "unit": "C"}])
    r = one(s, "bearing_temp")
    assert r.status == "critical" and r.limit == 95
    assert s.overall_severity == "critical"


def test_below_direction_uses_lower_limit():
    low = run_rules("pump", [{"name": "suction_pressure", "value": 0.3, "unit": "bar"}])
    ok = run_rules("pump", [{"name": "suction_pressure", "value": 0.8, "unit": "bar"}])
    assert one(low, "suction_pressure").status == "warning"
    assert one(ok, "suction_pressure").status == "ok"


def test_fahrenheit_is_converted():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 200, "unit": "F"}])
    r = one(s, "bearing_temp")
    assert r.value == pytest.approx(93.33, abs=0.05)
    assert r.status == "warning"


def test_missing_value_is_unknown_not_ok():
    s = run_rules("pump", [{"name": "bearing_temp", "value": None, "unit": "C"}])
    r = one(s, "bearing_temp")
    assert r.status == "missing" and r.severity == "unknown"
    assert s.overall_severity == "none" and s.data_issue_count == 1


def test_conflicting_readings_flagged_with_worst_severity():
    s = run_rules(
        "pump",
        [
            {"name": "bearing_temp", "value": 70, "unit": "C"},
            {"name": "bearing_temp", "value": 92, "unit": "C"},
        ],
    )
    r = one(s, "bearing_temp")
    assert r.status == "conflict" and r.severity == "warning" and len(r.values) == 2
    assert s.overall_severity == "warning"


def test_agreeing_duplicate_readings_are_not_a_conflict():
    s = run_rules(
        "pump",
        [
            {"name": "bearing_temp", "value": 80, "unit": "C"},
            {"name": "bearing_temp", "value": 82, "unit": "C"},
        ],
    )
    r = one(s, "bearing_temp")
    assert r.status == "ok" and r.value == 82


def test_implausible_value_is_rejected():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 900, "unit": "C"}])
    r = one(s, "bearing_temp")
    assert r.status == "implausible" and r.severity == "unknown"


def test_unsupported_unit_is_flagged():
    s = run_rules("pump", [{"name": "bearing_temp", "value": 80, "unit": "rpm"}])
    assert one(s, "bearing_temp").status == "unit_error"


def test_unknown_sensor_has_no_rule():
    s = run_rules("pump", [{"name": "oil_color", "value": 3, "unit": None}])
    r = one(s, "oil_color")
    assert r.status == "unknown_sensor" and r.severity == "unknown"


def test_sensor_name_is_normalised():
    s = run_rules("pump", [{"name": " Bearing Temp ", "value": 60, "unit": "C"}])
    assert s.results[0].sensor == "bearing_temp"


def test_not_provided_sensors_are_listed():
    s = run_rules("pump", [{"name": "vibration", "value": 3, "unit": "mm/s"}])
    assert s.not_provided == ["bearing_temp", "suction_pressure"]


def test_clean_limits_with_data_issues_is_not_a_clean_bill():
    s = run_rules(
        "pump",
        [
            {"name": "bearing_temp", "value": None, "unit": "C"},
            {"name": "vibration", "value": 3, "unit": "mm/s"},
        ],
    )
    assert s.overall_severity == "none" and s.data_issue_count == 1
    assert "not a clean bill" in s.note


def test_priority_floor_levels():
    warn = run_rules("pump", [{"name": "bearing_temp", "value": 90, "unit": "C"}])
    crit = run_rules("pump", [{"name": "bearing_temp", "value": 99, "unit": "C"}])
    none = run_rules("pump", [{"name": "bearing_temp", "value": 50, "unit": "C"}])
    assert (warn.priority_floor, crit.priority_floor, none.priority_floor) == ("medium", "high", None)


def test_compressor_discharge_temperature():
    warn = run_rules("compressor", [{"name": "discharge_temp", "value": 118, "unit": "C"}])
    crit = run_rules("compressor", [{"name": "discharge_temp", "value": 121, "unit": "C"}])
    assert one(warn, "discharge_temp").status == "warning"
    assert one(warn, "discharge_temp").citation == "COMP-1.1"
    assert one(crit, "discharge_temp").status == "critical"
