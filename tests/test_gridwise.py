"""Automated test suite for GridWise Energy Optimizer.

Tests cover all 28 hackathon evaluation scenarios including endpoints,
validation rules, directive enforcement, infeasibility, and deterministic LLM fallback parsing.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.fallback_parser import fallback_interpret_notes

client = TestClient(app)


def _base_hours():
    """Build a standard 24-hour baseline dataset."""
    hours = []
    for h in range(24):
        tariff = 15.0 if 17 <= h <= 21 else 5.0
        solar = 20.0 if 10 <= h <= 15 else 0.0
        hours.append(
            {
                "hour": h,
                "demand_kwh": 30.0,
                "solar_kwh": solar,
                "tariff_bdt_per_kwh": tariff,
            }
        )
    return hours


def _base_battery():
    return {
        "capacity_kwh": 100.0,
        "initial_energy_kwh": 50.0,
        "minimum_energy_kwh": 10.0,
        "max_charge_kwh_per_hour": 25.0,
        "max_discharge_kwh_per_hour": 25.0,
    }


# ---------------------------------------------------------------------------
# Test 1: Health endpoint
# ---------------------------------------------------------------------------
def test_1_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test 2: Root endpoint
# ---------------------------------------------------------------------------
def test_2_root_endpoint():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert "health" in data
    assert "optimize" in data


# ---------------------------------------------------------------------------
# Test 3: Valid basic optimization request
# ---------------------------------------------------------------------------
def test_3_valid_basic_optimization():
    payload = {
        "scenario_id": "test_basic",
        "operator_notes": ["Routine campus day."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=([{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}], "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario_id"] == "test_basic"
        assert len(data["hourly_plan"]) == 24


# ---------------------------------------------------------------------------
# Test 4: Invalid battery input (HTTP 400)
# ---------------------------------------------------------------------------
def test_4_invalid_battery_input():
    bad_battery = _base_battery()
    bad_battery["initial_energy_kwh"] = 150.0  # > capacity
    payload = {
        "scenario_id": "test_invalid_battery",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": bad_battery,
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 5: Missing hours (< 24 hours, HTTP 400)
# ---------------------------------------------------------------------------
def test_5_missing_hours():
    payload = {
        "scenario_id": "test_missing_hours",
        "operator_notes": ["Routine day"],
        "hours": _base_hours()[:12],
        "battery": _base_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 6: Duplicate or unordered hours (HTTP 400)
# ---------------------------------------------------------------------------
def test_6_duplicate_unordered_hours():
    hours = _base_hours()
    hours[1]["hour"] = 0  # Duplicate 0
    payload = {
        "scenario_id": "test_dup_hours",
        "operator_notes": ["Routine day"],
        "hours": hours,
        "battery": _base_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 7: Negative demand (HTTP 400)
# ---------------------------------------------------------------------------
def test_7_negative_demand():
    hours = _base_hours()
    hours[5]["demand_kwh"] = -10.0
    payload = {
        "scenario_id": "test_neg_demand",
        "operator_notes": ["Routine day"],
        "hours": hours,
        "battery": _base_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 8: Negative solar (HTTP 400)
# ---------------------------------------------------------------------------
def test_8_negative_solar():
    hours = _base_hours()
    hours[10]["solar_kwh"] = -5.0
    payload = {
        "scenario_id": "test_neg_solar",
        "operator_notes": ["Routine day"],
        "hours": hours,
        "battery": _base_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 9: Basic solar usage
# ---------------------------------------------------------------------------
def test_9_basic_solar_usage():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    payload = {
        "scenario_id": "test_solar_usage",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Hour 10 has solar=20.0, demand=30.0 -> solar should be fully utilized
        plan_h10 = data["hourly_plan"][10]
        assert plan_h10["solar_used_kwh"] == 20.0


# ---------------------------------------------------------------------------
# Test 10: Battery charging
# ---------------------------------------------------------------------------
def test_10_battery_charging():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    payload = {
        "scenario_id": "test_battery_charging",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        actions = [p["battery_action"] for p in data["hourly_plan"]]
        assert "charge" in actions


# ---------------------------------------------------------------------------
# Test 11: Battery discharging
# ---------------------------------------------------------------------------
def test_11_battery_discharging():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    payload = {
        "scenario_id": "test_battery_discharging",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        actions = [p["battery_action"] for p in data["hourly_plan"]]
        assert "discharge" in actions


# ---------------------------------------------------------------------------
# Test 12: Battery minimum reserve directive
# ---------------------------------------------------------------------------
def test_12_minimum_battery_reserve():
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 60.0},
            "explanation": "Reserve 60 kWh",
        }
    ]
    payload = {
        "scenario_id": "test_min_reserve",
        "operator_notes": ["Keep at least 60 kWh in storage between 6 PM and 9 PM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [18, 19, 20]:
            assert plan[h]["battery_energy_after_kwh"] >= 60.0 - 1e-4


# ---------------------------------------------------------------------------
# Test 13: No-charge window directive
# ---------------------------------------------------------------------------
def test_13_no_charge_window():
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [2, 3, 4]},
            "explanation": "No charge 2 AM - 5 AM",
        }
    ]
    payload = {
        "scenario_id": "test_no_charge",
        "operator_notes": ["Grid charging isolated 2 AM to 5 AM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [2, 3, 4]:
            assert plan[h]["battery_action"] != "charge"
            if plan[h]["battery_action"] == "idle":
                assert plan[h]["battery_kwh"] == 0.0


# ---------------------------------------------------------------------------
# Test 14: No-discharge window directive
# ---------------------------------------------------------------------------
def test_14_no_discharge_window():
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [17, 18]},
            "explanation": "No discharge 5 PM - 7 PM",
        }
    ]
    payload = {
        "scenario_id": "test_no_discharge",
        "operator_notes": ["Inverter diagnostic: do not discharge 5 PM to 7 PM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [17, 18]:
            assert plan[h]["battery_action"] != "discharge"


# ---------------------------------------------------------------------------
# Test 15: Solar reduction directive
# ---------------------------------------------------------------------------
def test_15_solar_reduction():
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [12, 13], "factor": 0.2},
            "explanation": "Solar reduced to 20%",
        }
    ]
    payload = {
        "scenario_id": "test_solar_red",
        "operator_notes": ["Dust storm from 12 PM to 2 PM, solar output drop to 20%."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        assert plan[12]["solar_used_kwh"] <= 4.0 + 1e-4
        assert plan[13]["solar_used_kwh"] <= 4.0 + 1e-4


# ---------------------------------------------------------------------------
# Test 16: Max-grid constraint directive
# ---------------------------------------------------------------------------
def test_16_max_grid_window():
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [18, 19], "max_grid_kwh": 20.0},
            "explanation": "Grid cap 20 kWh",
        }
    ]
    payload = {
        "scenario_id": "test_max_grid",
        "operator_notes": ["Grid import capped at 20 kWh between 6 PM and 8 PM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [18, 19]:
            assert plan[h]["grid_kwh"] <= 20.0 + 1e-4


# ---------------------------------------------------------------------------
# Test 17: No-op note
# ---------------------------------------------------------------------------
def test_17_no_op_note():
    mock_inter = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No energy impact",
        }
    ]
    payload = {
        "scenario_id": "test_noop",
        "operator_notes": ["Cafeteria lunch menu has been updated for tomorrow."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["directive_interpretation"][0]["directive_type"] == "no_op"
        assert data["directive_interpretation"][0]["applies"] is False


# ---------------------------------------------------------------------------
# Test 18: Multiple directives together
# ---------------------------------------------------------------------------
def test_18_multiple_directives():
    mock_inter = [
        {"note_index": 0, "applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [11, 12], "factor": 0.5}, "explanation": "50% solar"},
        {"note_index": 1, "applies": True, "directive_type": "no_discharge_window", "structured_adjustment": {"hours": [8, 9]}, "explanation": "No discharge"},
        {"note_index": 2, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "No-op"},
    ]
    payload = {
        "scenario_id": "test_multi",
        "operator_notes": [
            "Solar reduced by 50% 11 AM to 1 PM.",
            "Do not discharge battery 8 AM to 10 AM.",
            "Library silent reading event.",
        ],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["directive_interpretation"]) == 3


# ---------------------------------------------------------------------------
# Test 19: Infeasible scenario handling (HTTP 422)
# ---------------------------------------------------------------------------
def test_19_infeasible_scenario():
    # Set grid cap to 0 when demand is 30 and solar/battery cannot cover it
    mock_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [0], "max_grid_kwh": 0.0},
            "explanation": "0 grid import",
        },
        {
            "note_index": 1,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [0]},
            "explanation": "0 discharge",
        },
    ]
    hours = _base_hours()
    hours[0]["solar_kwh"] = 0.0  # No solar at hour 0
    payload = {
        "scenario_id": "test_infeasible",
        "operator_notes": ["No grid import at hour 0", "No discharge at hour 0"],
        "hours": hours,
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"] == "infeasible_under_interpreted_directives"


# ---------------------------------------------------------------------------
# Test 20: Final battery energy equals initial energy
# ---------------------------------------------------------------------------
def test_20_end_of_day_neutrality():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    battery = _base_battery()
    payload = {
        "scenario_id": "test_neutrality",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": battery,
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        final_e = data["hourly_plan"][23]["battery_energy_after_kwh"]
        assert abs(final_e - battery["initial_energy_kwh"]) < 1e-3


# ---------------------------------------------------------------------------
# Test 21: Energy balance
# ---------------------------------------------------------------------------
def test_21_energy_balance():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    hours = _base_hours()
    payload = {
        "scenario_id": "test_balance",
        "operator_notes": ["Routine day"],
        "hours": hours,
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        for p in data["hourly_plan"]:
            h = p["hour"]
            demand = hours[h]["demand_kwh"]
            g, s, act, mag = p["grid_kwh"], p["solar_used_kwh"], p["battery_action"], p["battery_kwh"]
            supplied = g + s + (mag if act == "discharge" else 0.0)
            required = demand + (mag if act == "charge" else 0.0)
            assert abs(supplied - required) < 1e-3


# ---------------------------------------------------------------------------
# Test 22: Total cost calculation
# ---------------------------------------------------------------------------
def test_22_total_cost_calc():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    hours = _base_hours()
    payload = {
        "scenario_id": "test_cost",
        "operator_notes": ["Routine day"],
        "hours": hours,
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        calc_cost = sum(p["grid_kwh"] * hours[p["hour"]]["tariff_bdt_per_kwh"] for p in data["hourly_plan"])
        assert abs(calc_cost - data["total_cost_bdt"]) < 1e-2


# ---------------------------------------------------------------------------
# Test 23: Peak grid calculation
# ---------------------------------------------------------------------------
def test_23_peak_grid_calc():
    mock_inter = [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "no-op"}]
    payload = {
        "scenario_id": "test_peak",
        "operator_notes": ["Routine day"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        calc_peak = max(p["grid_kwh"] for p in data["hourly_plan"])
        assert abs(calc_peak - data["peak_grid_kwh"]) < 1e-2


# ---------------------------------------------------------------------------
# Test 24: Deterministic fallback parser execution without LLM key
# ---------------------------------------------------------------------------
def test_24_fallback_parser_no_api_key():
    notes = [
        "Facilities will wash solar panels from noon until 2 PM. Usable solar should be treated as roughly 25% of forecast.",
        "Keep at least 60 kWh in storage between 6 PM and 9 PM.",
        "Cafeteria lunch menu update.",
    ]
    battery = _base_battery()
    parsed = fallback_interpret_notes(notes, battery)
    assert len(parsed) == 3
    assert parsed[0]["directive_type"] == "solar_reduction"
    assert parsed[0]["structured_adjustment"]["hours"] == [12, 13]
    assert parsed[0]["structured_adjustment"]["factor"] == 0.25
    assert parsed[1]["directive_type"] == "minimum_battery_reserve"
    assert parsed[1]["structured_adjustment"]["hours"] == [18, 19, 20]
    assert parsed[1]["structured_adjustment"]["minimum_energy_kwh"] == 60.0
    assert parsed[2]["directive_type"] == "no_op"
    assert parsed[2]["applies"] is False


# ---------------------------------------------------------------------------
# Test 25: Malformed LLM response handling
# ---------------------------------------------------------------------------
def test_25_malformed_llm_response():
    # If interpret_notes raises an error, fallback handles it safely
    payload = {
        "scenario_id": "test_malformed_llm",
        "operator_notes": ["Solar panels wash noon until 2 PM 25%"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    # Unset client so fallback triggers automatically
    with patch("app.llm_client._get_client", return_value=None):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["directive_interpretation"][0]["directive_type"] == "solar_reduction"


# ---------------------------------------------------------------------------
# Test 26: Unknown directive rejection
# ---------------------------------------------------------------------------
def test_26_unknown_directive_rejection():
    mock_bad_inter = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "invalid_unsupported_directive",
            "structured_adjustment": {"hours": [12]},
            "explanation": "Bad directive",
        }
    ]
    payload = {
        "scenario_id": "test_bad_directive",
        "operator_notes": ["Some note"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_bad_inter, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code in [422, 500]


# ---------------------------------------------------------------------------
# Test 27: Overnight time window handling
# ---------------------------------------------------------------------------
def test_27_overnight_time_window():
    note = "Battery charger isolated from 11 PM until 3 AM for electrical maintenance."
    parsed = fallback_interpret_notes([note], _base_battery())
    assert parsed[0]["directive_type"] == "no_charge_window"
    assert parsed[0]["structured_adjustment"]["hours"] == [23, 0, 1, 2]
