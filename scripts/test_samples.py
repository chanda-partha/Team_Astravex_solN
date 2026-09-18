"""Run every public sample case against the local service and score it.

Usage:  python scripts/test_samples.py --url http://localhost:8000
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


def post(url: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def replay_check(case: dict, resp: dict) -> tuple[bool, list[str]]:
    """Independent replay of the response against the case input."""
    errors: list[str] = []
    hours = {h["hour"]: h for h in case["input"]["hours"]}
    battery = case["input"]["battery"]
    e = battery["initial_energy_kwh"]
    total_grid = 0.0
    total_cost = 0.0

    # Build effective solar and directive constraints from the RETURNED interpretation
    effective = {h["hour"]: h["solar_kwh"] for h in case["input"]["hours"]}
    reserve = {h: battery["minimum_energy_kwh"] for h in range(24)}
    no_charge, no_discharge, grid_cap = set(), set(), {}
    for d in resp.get("directive_interpretation", []):
        if not d.get("applies"):
            continue
        t, adj = d["directive_type"], d.get("structured_adjustment") or {}
        for h in adj.get("hours", []):
            if t == "solar_reduction":
                effective[h] = effective.get(h, 0) * adj["factor"]
            elif t == "minimum_battery_reserve":
                reserve[h] = max(reserve.get(h, 0), adj["minimum_energy_kwh"])
            elif t == "no_charge_window":
                no_charge.add(h)
            elif t == "no_discharge_window":
                no_discharge.add(h)
            elif t == "max_grid_window":
                grid_cap[h] = min(grid_cap.get(h, float("inf")), adj["max_grid_kwh"])

    for p in resp.get("hourly_plan", []):
        h = p["hour"]
        base = hours[h]
        g, s, act, mag, after = (
            p["grid_kwh"], p["solar_used_kwh"], p["battery_action"],
            p["battery_kwh"], p["battery_energy_after_kwh"],
        )
        demand, tariff = base["demand_kwh"], base["tariff_bdt_per_kwh"]

        if s > effective.get(h, 0) + 0.011:
            errors.append(f"h{h}: solar_used {s} > effective {effective.get(h, 0):.2f}")
        if h in no_charge and act == "charge" and mag > 0.011:
            errors.append(f"h{h}: charge in no-charge window")
        if h in no_discharge and act == "discharge" and mag > 0.011:
            errors.append(f"h{h}: discharge in no-discharge window")
        if h in grid_cap and g > grid_cap[h] + 0.011:
            errors.append(f"h{h}: grid {g} > cap {grid_cap[h]}")
        if after < reserve[h] - 0.011:
            errors.append(f"h{h}: battery {after} < reserve {reserve[h]}")
        if after > battery["capacity_kwh"] + 0.011:
            errors.append(f"h{h}: battery above capacity")
        if act == "charge" and mag > battery["max_charge_kwh_per_hour"] + 0.011:
            errors.append(f"h{h}: charge rate too high")
        if act == "discharge" and mag > battery["max_discharge_kwh_per_hour"] + 0.011:
            errors.append(f"h{h}: discharge rate too high")

        expected = e + (mag if act == "charge" else -mag if act == "discharge" else 0)
        if abs(after - expected) > 0.011:
            errors.append(f"h{h}: battery transition {e}->{after} (expected {expected:.3f})")

        supplied = g + s + (mag if act == "discharge" else 0)
        needed = demand + (mag if act == "charge" else 0)
        if abs(supplied - needed) > 0.011:
            errors.append(f"h{h}: balance off by {supplied - needed:.3f}")

        total_grid += g
        total_cost += g * tariff
        e = after

    if abs(e - battery["initial_energy_kwh"]) > 0.011:
        errors.append(f"end battery {e} != initial {battery['initial_energy_kwh']}")
    if abs(total_grid - resp.get("total_grid_kwh", 0)) > 0.011:
        errors.append("total_grid_kwh mismatch")
    if abs(total_cost - resp.get("total_cost_bdt", 0)) > 0.011:
        errors.append("total_cost_bdt mismatch")

    # Compare with organizer reference cost if available
    return len(errors) == 0, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--samples", default="samples/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
    args = ap.parse_args()

    base = args.url.rstrip("/")

    with urllib.request.urlopen(f"{base}/health", timeout=10) as r:
        print("health:", r.status, r.read().decode())

    with open(args.samples, "r", encoding="utf-8") as f:
        pack = json.load(f)

    passed = 0
    for case in pack["cases"]:
        cid, label = case["id"], case.get("label", "")
        try:
            status, resp = post(f"{base}/optimize-energy", case["input"])
        except urllib.error.HTTPError as exc:
            print(f"{cid} {label}: HTTP {exc.code} FAIL")
            print("   ", exc.read().decode()[:300])
            continue
        except Exception as exc:
            print(f"{cid} {label}: FAIL ({exc})")
            continue

        ok, errors = replay_check(case, resp)
        expected = case.get("expected_output", {})
        ref_cost = expected.get("total_cost_bdt")
        cost_note = ""
        if ref_cost is not None and resp.get("total_cost_bdt") is not None:
            ratio = min(1.0, ref_cost / max(resp["total_cost_bdt"], 1e-9))
            cost_note = f" cost={resp['total_cost_bdt']:.1f} ref={ref_cost:.1f} ratio={ratio:.3f}"

        if ok:
            passed += 1
            print(f"{cid} {label}: VALID{cost_note}")
        else:
            print(f"{cid} {label}: INVALID")
            for err in errors[:6]:
                print("    -", err)

    print(f"\n{passed}/{len(pack['cases'])} cases valid")
    return 0 if passed == len(pack["cases"]) else 1


if __name__ == "__main__":
    sys.exit(main())
