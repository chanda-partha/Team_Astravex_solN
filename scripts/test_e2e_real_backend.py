"""End-to-End Test for GridWise Frontend & Real Production Backend (Render)."""

import json
import urllib.request
import sys

LIVE_BACKEND = "https://gridpilot-bup.onrender.com"

def run_e2e_test():
    print(f"1. Checking Live Backend Health at {LIVE_BACKEND}/health...")
    health_url = f"{LIVE_BACKEND}/health"
    req = urllib.request.urlopen(health_url)
    health_res = json.loads(req.read().decode())
    assert health_res == {"status": "ok"}, f"Unexpected health response: {health_res}"
    print("   [SUCCESS] Backend is connected and returning status ok.")

    print(f"\n2. Testing Real Demo Scenario POST {LIVE_BACKEND}/optimize-energy...")
    
    # 24 hour load profile (solar 10-15, peak tariff 17-21)
    hours = []
    for h in range(24):
        tariff = 15.0 if (17 <= h <= 21) else 5.0
        solar = 20.0 if (10 <= h <= 15) else 0.0
        hours.append({
            "hour": h,
            "demand_kwh": 80.0,
            "solar_kwh": solar,
            "tariff_bdt_per_kwh": tariff
        })

    payload = {
        "scenario_id": "DEMO-SCENARIO-E2E",
        "operator_notes": [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "Keep at least 120 kWh in reserve from 6 PM until 9 PM.",
            "The cafeteria menu changes tomorrow."
        ],
        "hours": hours,
        "battery": {
            "capacity_kwh": 220.0,
            "initial_energy_kwh": 110.0,
            "minimum_energy_kwh": 40.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0
        }
    }

    req_data = json.dumps(payload).encode('utf-8')
    opt_req = urllib.request.Request(
        f"{LIVE_BACKEND}/optimize-energy",
        data=req_data,
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(opt_req) as response:
        assert response.status == 200, f"Expected 200, got {response.status}"
        data = json.loads(response.read().decode('utf-8'))

    print("   [SUCCESS] Received 200 OK from real production backend.")
    print(f"   Scenario ID: {data['scenario_id']}")
    print(f"   Total Grid kWh: {data['total_grid_kwh']}")
    print(f"   Total Cost BDT: {data['total_cost_bdt']}")
    print(f"   Peak Grid kWh: {data['peak_grid_kwh']}")
    print(f"   Plan Summary: {data['plan_summary']}")

    # Validate Directive Interpretations
    directives = data["directive_interpretation"]
    assert len(directives) == 4, f"Expected 4 directives, got {len(directives)}"
    
    d1 = directives[0]
    assert d1["directive_type"] == "solar_reduction"
    assert d1["applies"] is True
    assert d1["structured_adjustment"]["hours"] == [13, 14]
    assert d1["structured_adjustment"]["factor"] == 0.2

    d2 = directives[1]
    assert d2["directive_type"] == "no_charge_window"
    assert d2["applies"] is True
    assert d2["structured_adjustment"]["hours"] == [14, 15]

    d3 = directives[2]
    assert d3["directive_type"] == "minimum_battery_reserve"
    assert d3["applies"] is True
    assert d3["structured_adjustment"]["hours"] == [18, 19, 20]
    assert d3["structured_adjustment"]["minimum_energy_kwh"] == 120.0

    d4 = directives[3]
    assert d4["directive_type"] == "no_op"
    assert d4["applies"] is False
    assert d4["structured_adjustment"] is None

    print("\n3. Verifying Hourly Dispatch Plan...")
    plan = data["hourly_plan"]
    assert len(plan) == 24, f"Expected 24 hourly steps, got {len(plan)}"
    
    # Check battery charging zero in hours 14, 15
    for step in plan:
        h = step["hour"]
        if h in [14, 15]:
            assert step["battery_action"] != "charge", f"Battery charged at prohibited hour {h}"
            assert step["battery_kwh"] == 0.0, f"Non-zero battery_kwh at hour {h}"
        if h in [18, 19, 20]:
            assert step["battery_energy_after_kwh"] >= 120.0 - 1e-4, f"Reserve violated at hour {h}: {step['battery_energy_after_kwh']} < 120"

    print("   [SUCCESS] All mathematical constraints (charging ban, battery reserve, solar reduction) verified!")
    print("\nALL END-TO-END CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    try:
        run_e2e_test()
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
