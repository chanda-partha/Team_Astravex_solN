"""Final Acceptance Test Suite for BUP CSE Fest 2026 GridWise Application.

Tests the exact 4-note scenario and 15 acceptance criteria specified by the user prompt.
"""

from fastapi.testclient import TestClient
from app.main import app
import pytest

client = TestClient(app)


def test_final_acceptance_4_notes():
    hours = []
    for h in range(24):
        tariff = 15.0 if 17 <= h <= 21 else 5.0
        solar = 20.0 if 10 <= h <= 15 else 0.0
        hours.append({
            "hour": h,
            "demand_kwh": 80.0,
            "solar_kwh": solar,
            "tariff_bdt_per_kwh": tariff
        })

    battery = {
        "capacity_kwh": 220,
        "initial_energy_kwh": 110,
        "minimum_energy_kwh": 40,
        "max_charge_kwh_per_hour": 50,
        "max_discharge_kwh_per_hour": 50
    }

    payload = {
        "scenario_id": "FINAL-ACCEPTANCE-001",
        "operator_notes": [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "Keep at least 120 kWh in reserve from 6 PM until 9 PM.",
            "The cafeteria menu changes tomorrow."
        ],
        "hours": hours,
        "battery": battery
    }

    resp = client.post("/optimize-energy", json=payload)
    assert resp.status_code == 200, f"Failed with {resp.status_code}: {resp.text}"
    data = resp.json()

    # 1. Exactly 4 interpretation entries returned
    directives = data["directive_interpretation"]
    assert len(directives) == 4, f"Expected 4 directives, got {len(directives)}"

    # 2. Entries ordered by note_index (0, 1, 2, 3)
    for idx, d in enumerate(directives):
        assert d["note_index"] == idx

    # 3. First directive is solar_reduction (hours [13, 14], factor 0.2)
    assert directives[0]["directive_type"] == "solar_reduction"
    assert directives[0]["applies"] is True
    assert directives[0]["structured_adjustment"]["hours"] == [13, 14]
    assert abs(directives[0]["structured_adjustment"]["factor"] - 0.2) < 1e-4

    # 4. Second directive is no_charge_window (hours [14, 15])
    assert directives[1]["directive_type"] == "no_charge_window"
    assert directives[1]["applies"] is True
    assert directives[1]["structured_adjustment"]["hours"] == [14, 15]

    # 5. Third directive is minimum_battery_reserve (hours [18, 19, 20], reserve 120.0)
    assert directives[2]["directive_type"] == "minimum_battery_reserve"
    assert directives[2]["applies"] is True
    assert directives[2]["structured_adjustment"]["hours"] == [18, 19, 20]
    assert directives[2]["structured_adjustment"]["minimum_energy_kwh"] == 120.0

    # 6. Fourth directive is no_op (applies=False, structured_adjustment=None)
    assert directives[3]["directive_type"] == "no_op"
    assert directives[3]["applies"] is False
    assert directives[3]["structured_adjustment"] is None

    # 7. Final plan actually respects all applicable directives
    plan = {p["hour"]: p for p in data["hourly_plan"]}
    assert len(plan) == 24

    # Hour 14 and 15 charge is 0
    assert plan[14]["battery_action"] != "charge" or plan[14]["battery_kwh"] == 0.0
    assert plan[15]["battery_action"] != "charge" or plan[15]["battery_kwh"] == 0.0

    # Hours 18, 19, 20 battery level >= 120.0
    for h in [18, 19, 20]:
        assert plan[h]["battery_energy_after_kwh"] >= 120.0 - 1e-4

    # 8. Total cost and peak grid usage match recalculated hourly plan values
    calc_grid = sum(p["grid_kwh"] for p in data["hourly_plan"])
    calc_cost = sum(p["grid_kwh"] * hours[p["hour"]]["tariff_bdt_per_kwh"] for p in data["hourly_plan"])
    calc_peak = max(p["grid_kwh"] for p in data["hourly_plan"])

    assert abs(calc_grid - data["total_grid_kwh"]) < 1e-2
    assert abs(calc_cost - data["total_cost_bdt"]) < 1e-2
    assert abs(calc_peak - data["peak_grid_kwh"]) < 1e-2
