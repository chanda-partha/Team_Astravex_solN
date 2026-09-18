"""Automated test suite for GridWise Energy Optimizer.

Tests cover all 14 mandatory test requirements using mocked LLM responses
and FastAPI TestClient for deterministic local execution.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _base_hours():
    """Build a standard 24-hour baseline dataset."""
    hours = []
    for h in range(24):
        # Peak hours 17-21 have higher tariff
        tariff = 15.0 if 17 <= h <= 21 else 5.0
        # Peak solar 10-15
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
# Test 1: Basic scenario with no meaningful directive (no_op)
# ---------------------------------------------------------------------------
def test_1_no_op_directive():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Routine cafeteria note, no energy schedule impact.",
        }
    ]
    payload = {
        "scenario_id": "test_01",
        "operator_notes": ["Cafeteria lunch menu has been updated for tomorrow."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["scenario_id"] == "test_01"
        assert len(data["hourly_plan"]) == 24
        assert len(data["directive_interpretation"]) == 1
        assert data["directive_interpretation"][0]["directive_type"] == "no_op"
        assert data["directive_interpretation"][0]["applies"] is False


# ---------------------------------------------------------------------------
# Test 2: solar_reduction directive
# ---------------------------------------------------------------------------
def test_2_solar_reduction():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [12, 13], "factor": 0.2},
            "explanation": "Clouds reduce solar output by 80% (factor 0.2) from 12:00 to 14:00.",
        }
    ]
    payload = {
        "scenario_id": "test_02",
        "operator_notes": ["Heavy dust storm from 12 PM to 2 PM, solar output expected to drop to 20%."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        # Base solar for h=12,13 was 20.0, with factor 0.2 effective solar is 4.0
        assert plan[12]["solar_used_kwh"] <= 4.0 + 1e-4
        assert plan[13]["solar_used_kwh"] <= 4.0 + 1e-4


# ---------------------------------------------------------------------------
# Test 3: minimum_battery_reserve directive
# ---------------------------------------------------------------------------
def test_3_minimum_battery_reserve():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 60.0},
            "explanation": "Maintain at least 60 kWh battery reserve during peak evening hours.",
        }
    ]
    payload = {
        "scenario_id": "test_03",
        "operator_notes": ["Keep at least 60 kWh in storage between 6 PM and 9 PM for grid emergency."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [18, 19, 20]:
            assert plan[h]["battery_energy_after_kwh"] >= 60.0 - 1e-4


# ---------------------------------------------------------------------------
# Test 4: no_charge_window directive
# ---------------------------------------------------------------------------
def test_4_no_charge_window():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [2, 3, 4]},
            "explanation": "Charger maintenance scheduled from 2 AM to 5 AM.",
        }
    ]
    payload = {
        "scenario_id": "test_04",
        "operator_notes": ["Grid charging isolated for maintenance between 2 AM and 5 AM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [2, 3, 4]:
            assert plan[h]["battery_action"] != "charge"
            if plan[h]["battery_action"] == "idle":
                assert plan[h]["battery_kwh"] == 0.0


# ---------------------------------------------------------------------------
# Test 5: no_discharge_window directive
# ---------------------------------------------------------------------------
def test_5_no_discharge_window():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [17, 18]},
            "explanation": "Inverter test prevents discharging from 5 PM to 7 PM.",
        }
    ]
    payload = {
        "scenario_id": "test_05",
        "operator_notes": ["Inverter diagnostic test: do not discharge battery from 5 PM to 7 PM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [17, 18]:
            assert plan[h]["battery_action"] != "discharge"


# ---------------------------------------------------------------------------
# Test 6: max_grid_window directive
# ---------------------------------------------------------------------------
def test_6_max_grid_window():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": [18, 19], "max_grid_kwh": 20.0},
            "explanation": "Grid import capped at 20 kWh from 6 PM to 8 PM.",
        }
    ]
    payload = {
        "scenario_id": "test_06",
        "operator_notes": ["Transformer bottleneck: grid intake must not exceed 20 kWh/h between 6 PM and 8 PM."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [18, 19]:
            assert plan[h]["grid_kwh"] <= 20.0 + 1e-4


# ---------------------------------------------------------------------------
# Test 7: Multiple directives in one request
# ---------------------------------------------------------------------------
def test_7_multiple_directives():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": [11, 12], "factor": 0.5},
            "explanation": "Cloud cover reduces solar to 50% from 11 AM to 1 PM.",
        },
        {
            "note_index": 1,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": [8, 9]},
            "explanation": "Battery diagnostic prevents discharging from 8 AM to 10 AM.",
        },
        {
            "note_index": 2,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Library quiet hours note has no energy impact.",
        },
    ]
    payload = {
        "scenario_id": "test_07",
        "operator_notes": [
            "Partial overcast expected 11 AM to 1 PM, solar generation reduced by 50%.",
            "Do not discharge battery between 8 AM and 10 AM due to cell testing.",
            "Library silent reading event from 2 PM to 4 PM.",
        ],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["directive_interpretation"]) == 3
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        assert plan[11]["solar_used_kwh"] <= 10.0 + 1e-4
        assert plan[8]["battery_action"] != "discharge"
        assert plan[9]["battery_action"] != "discharge"


# ---------------------------------------------------------------------------
# Test 8: Paraphrased natural-language notes
# ---------------------------------------------------------------------------
def test_8_paraphrased_notes():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": [20, 21, 22], "minimum_energy_kwh": 40.0},
            "explanation": "Ensure battery remains at or above 40 kWh from 8 PM to 11 PM.",
        }
    ]
    payload = {
        "scenario_id": "test_08",
        "operator_notes": ["Kindly ensure battery storage does not drop below 40 kWh between 20:00 and 23:00."],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        plan = {p["hour"]: p for p in data["hourly_plan"]}
        for h in [20, 21, 22]:
            assert plan[h]["battery_energy_after_kwh"] >= 40.0 - 1e-4


# ---------------------------------------------------------------------------
# Test 9: Invalid request with fewer than 24 hours (returns 400)
# ---------------------------------------------------------------------------
def test_9_invalid_hours_count():
    payload = {
        "scenario_id": "test_09",
        "operator_notes": ["Normal day"],
        "hours": _base_hours()[:12],  # Only 12 hours
        "battery": _base_battery(),
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 10: Invalid battery values (returns 400)
# ---------------------------------------------------------------------------
def test_10_invalid_battery_values():
    bad_battery = _base_battery()
    bad_battery["initial_energy_kwh"] = 150.0  # Exceeds capacity 100
    payload = {
        "scenario_id": "test_10",
        "operator_notes": ["Normal day"],
        "hours": _base_hours(),
        "battery": bad_battery,
    }
    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["error"] == "invalid_request"


# ---------------------------------------------------------------------------
# Test 11: Malformed or unsupported LLM output (fails safely)
# ---------------------------------------------------------------------------
def test_11_malformed_llm_output():
    # LLM raises RuntimeError (e.g. invalid response format after retries)
    payload = {
        "scenario_id": "test_11",
        "operator_notes": ["Confusing directive"],
        "hours": _base_hours(),
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", side_effect=RuntimeError("LLM output unparseable")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code in [422, 500], resp.text
        data = resp.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# Test 12: Final battery energy equals initial energy
# ---------------------------------------------------------------------------
def test_12_end_of_day_neutrality():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No directive.",
        }
    ]
    battery = _base_battery()
    payload = {
        "scenario_id": "test_12",
        "operator_notes": ["Standard operation"],
        "hours": _base_hours(),
        "battery": battery,
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        final_energy = data["hourly_plan"][23]["battery_energy_after_kwh"]
        assert abs(final_energy - battery["initial_energy_kwh"]) < 1e-3


# ---------------------------------------------------------------------------
# Test 13: Energy balance for all 24 hours
# ---------------------------------------------------------------------------
def test_13_hourly_energy_balance():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No directive.",
        }
    ]
    hours = _base_hours()
    payload = {
        "scenario_id": "test_13",
        "operator_notes": ["Standard operation"],
        "hours": hours,
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for entry in data["hourly_plan"]:
            h = entry["hour"]
            demand = hours[h]["demand_kwh"]
            g = entry["grid_kwh"]
            s = entry["solar_used_kwh"]
            act = entry["battery_action"]
            mag = entry["battery_kwh"]

            discharge = mag if act == "discharge" else 0.0
            charge = mag if act == "charge" else 0.0

            supplied = g + s + discharge
            required = demand + charge
            assert abs(supplied - required) < 1e-3, f"Hour {h} balance mismatch"


# ---------------------------------------------------------------------------
# Test 14: Recalculated cost and peak match the response metrics
# ---------------------------------------------------------------------------
def test_14_recalculated_metrics_match():
    mock_interpretation = [
        {
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No directive.",
        }
    ]
    hours = _base_hours()
    payload = {
        "scenario_id": "test_14",
        "operator_notes": ["Standard operation"],
        "hours": hours,
        "battery": _base_battery(),
    }
    with patch("app.main.interpret_notes", return_value=(mock_interpretation, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        calc_grid = sum(p["grid_kwh"] for p in data["hourly_plan"])
        calc_cost = sum(p["grid_kwh"] * hours[p["hour"]]["tariff_bdt_per_kwh"] for p in data["hourly_plan"])
        calc_peak = max(p["grid_kwh"] for p in data["hourly_plan"])

        assert abs(calc_grid - data["total_grid_kwh"]) < 1e-2
        assert abs(calc_cost - data["total_cost_bdt"]) < 1e-2
        assert abs(calc_peak - data["peak_grid_kwh"]) < 1e-2
