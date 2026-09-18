"""Independent replay validator: verifies the final plan against every rule."""

from __future__ import annotations

import math

from .optimizer import compute_effective_solar
from .schemas import DirectiveInterpretation

TOL = 0.01


def validate_plan(
    plan: list[dict],
    hours_data: list[dict],
    battery: dict,
    directives: list[DirectiveInterpretation],
    metrics: dict | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if len(plan) != 24:
        errors.append(f"plan must contain exactly 24 entries, got {len(plan)}")
        return False, errors

    cap = float(battery["capacity_kwh"])
    e0 = float(battery["initial_energy_kwh"])
    base_min = float(battery["minimum_energy_kwh"])
    max_ch = float(battery["max_charge_kwh_per_hour"])
    max_dis = float(battery["max_discharge_kwh_per_hour"])

    reserve = [base_min] * 24
    no_charge: set[int] = set()
    no_discharge: set[int] = set()
    grid_cap: dict[int, float] = {}
    for d in directives:
        if not d.applies or d.structured_adjustment is None:
            continue
        t = d.directive_type
        if t == "minimum_battery_reserve":
            for h in d.structured_adjustment.hours:
                reserve[h] = max(reserve[h], d.structured_adjustment.minimum_energy_kwh)
        elif t == "no_charge_window":
            no_charge.update(d.structured_adjustment.hours)
        elif t == "no_discharge_window":
            no_discharge.update(d.structured_adjustment.hours)
        elif t == "max_grid_window":
            for h in d.structured_adjustment.hours:
                grid_cap[h] = min(grid_cap.get(h, float("inf")), d.structured_adjustment.max_grid_kwh)

    effective_solar = compute_effective_solar(hours_data, directives)

    prev_e = e0
    seen_hours = set()
    calc_total_grid = 0.0
    calc_total_cost = 0.0
    calc_peak_grid = 0.0

    for idx, entry in enumerate(plan):
        h = entry["hour"]
        if not (0 <= h <= 23):
            errors.append(f"hour {h}: out of range")
            continue
        if h in seen_hours:
            errors.append(f"hour {h}: duplicate hour entry")
        seen_hours.add(h)

        if h != idx:
            errors.append(f"hour entry at index {idx} has hour {h} (must be strictly 0..23 in order)")

        demand = float(hours_data[h]["demand_kwh"])
        tariff = float(hours_data[h]["tariff_bdt_per_kwh"])
        g = entry["grid_kwh"]
        s = entry["solar_used_kwh"]
        action = entry["battery_action"]
        mag = entry["battery_kwh"]
        e_after = entry["battery_energy_after_kwh"]

        if any(isinstance(v, float) and not math.isfinite(v) for v in (g, s, mag, e_after)):
            errors.append(f"hour {h}: non-finite value")
            continue
        if g < -TOL or s < -TOL or mag < -TOL:
            errors.append(f"hour {h}: negative value")
        if action == "idle" and mag > 1e-6:
            errors.append(f"hour {h}: idle with nonzero battery_kwh ({mag})")

        # Solar limit
        if s > effective_solar[h] + TOL:
            errors.append(f"hour {h}: solar_used {s} exceeds effective {effective_solar[h]}")

        # Battery transition
        expected = prev_e + (mag if action == "charge" else -mag if action == "discharge" else 0)
        if abs(e_after - expected) > TOL:
            errors.append(f"hour {h}: battery transition mismatch (got {e_after}, expected {expected})")
        if e_after < reserve[h] - TOL:
            errors.append(f"hour {h}: battery {e_after} below reserve {reserve[h]}")
        if e_after > cap + TOL:
            errors.append(f"hour {h}: battery {e_after} above capacity {cap}")
        if action == "charge" and mag > max_ch + TOL:
            errors.append(f"hour {h}: charge rate {mag} exceeds {max_ch}")
        if action == "discharge" and mag > max_dis + TOL:
            errors.append(f"hour {h}: discharge rate {mag} exceeds {max_dis}")
        if h in no_charge and action == "charge" and mag > TOL:
            errors.append(f"hour {h}: charging in no_charge_window")
        if h in no_discharge and action == "discharge" and mag > TOL:
            errors.append(f"hour {h}: discharging in no_discharge_window")
        if h in grid_cap and g > grid_cap[h] + TOL:
            errors.append(f"hour {h}: grid {g} exceeds cap {grid_cap[h]}")

        # Energy balance
        supplied = g + s + (mag if action == "discharge" else 0)
        required = demand + (mag if action == "charge" else 0)
        if abs(supplied - required) > TOL:
            errors.append(f"hour {h}: energy balance off by {supplied - required}")

        calc_total_grid += g
        calc_total_cost += g * tariff
        if g > calc_peak_grid:
            calc_peak_grid = g

        prev_e = e_after

    if len(seen_hours) != 24:
        errors.append("plan does not contain all 24 hours 0..23")

    # Final neutrality
    if abs(prev_e - e0) > TOL:
        errors.append(f"end-of-day battery {prev_e} != initial {e0}")

    if metrics is not None:
        if abs(calc_total_grid - metrics.get("total_grid_kwh", calc_total_grid)) > TOL:
            errors.append(
                f"total_grid_kwh mismatch: calculated {calc_total_grid:.4f} != response {metrics.get('total_grid_kwh')}"
            )
        if abs(calc_total_cost - metrics.get("total_cost_bdt", calc_total_cost)) > TOL:
            errors.append(
                f"total_cost_bdt mismatch: calculated {calc_total_cost:.4f} != response {metrics.get('total_cost_bdt')}"
            )
        if abs(calc_peak_grid - metrics.get("peak_grid_kwh", calc_peak_grid)) > TOL:
            errors.append(
                f"peak_grid_kwh mismatch: calculated {calc_peak_grid:.4f} != response {metrics.get('peak_grid_kwh')}"
            )

    return (len(errors) == 0), errors
