"""Deterministic guardrails: LLM output is untrusted until validated here."""

from __future__ import annotations

import logging

from .schemas import (
    DirectiveInterpretation,
    HoursOnly,
    MaxGridWindow,
    MinimumBatteryReserve,
    SolarReduction,
)

logger = logging.getLogger("gridwise.guardrails")

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

ADJUSTMENT_MODELS = {
    "solar_reduction": SolarReduction,
    "minimum_battery_reserve": MinimumBatteryReserve,
    "no_charge_window": HoursOnly,
    "no_discharge_window": HoursOnly,
    "max_grid_window": MaxGridWindow,
}


def _normalize_hours(raw) -> list[int] | None:
    if not isinstance(raw, list) or not raw:
        return None
    hours: list[int] = []
    for h in raw:
        if isinstance(h, bool) or not isinstance(h, (int, float)):
            return None
        if isinstance(h, float) and not h.is_integer():
            return None
        hours.append(int(h))
    if any(not (0 <= h <= 23) for h in hours):
        return None
    hours = sorted(set(hours))
    return hours


def validate_interpretation(
    raw_list: list[dict], n_notes: int, battery: dict | None = None
) -> list[DirectiveInterpretation]:
    """Turn untrusted LLM JSON into valid DirectiveInterpretation entries.

    Raises ValueError if any entry is unusable (caller may retry / fail safely).
    """
    if not isinstance(raw_list, list):
        raise ValueError("interpretation is not a list")
    if len(raw_list) != n_notes:
        raise ValueError(f"expected {n_notes} entries, got {len(raw_list)}")

    validated: list[DirectiveInterpretation] = []
    for i, raw in enumerate(raw_list):
        if not isinstance(raw, dict):
            raise ValueError(f"entry {i} is not an object")

        idx = raw.get("note_index", i)
        if isinstance(idx, bool) or not isinstance(idx, (int, float)) or not float(idx).is_integer():
            raise ValueError(f"entry {i}: bad note_index")
        idx = int(idx)
        if idx != i:
            raise ValueError(f"entry {i}: note_index {idx} out of order/duplicate (expected {i})")

        dtype = raw.get("directive_type")
        if dtype not in ALLOWED_TYPES:
            raise ValueError(f"entry {i}: unsupported directive_type {dtype!r}")

        applies = raw.get("applies")
        if dtype == "no_op":
            if applies is True:
                raise ValueError(f"entry {i}: no_op directive must have applies=false")
            validated.append(
                DirectiveInterpretation(
                    note_index=idx,
                    applies=False,
                    directive_type="no_op",
                    structured_adjustment=None,
                    explanation=str(raw.get("explanation", ""))[:300]
                    or "This note does not affect today's 24-hour energy schedule.",
                )
            )
            continue

        if applies is not True:
            raise ValueError(f"entry {i}: non-no_op directive must have applies=true")

        adj_raw = raw.get("structured_adjustment")
        if not isinstance(adj_raw, dict):
            raise ValueError(f"entry {i}: structured_adjustment missing")
        adj_raw = dict(adj_raw)
        adj_raw.pop("note_index", None)

        # Normalize common LLM shape slip: {"<directive_type>": {<real fields>}}
        if dtype not in adj_raw or "hours" not in adj_raw:
            inner = adj_raw.get(dtype)
            if isinstance(inner, dict):
                logger.info("normalized nested adjustment shape for entry %d", i)
                adj_raw = {**inner, **{k: v for k, v in adj_raw.items() if k != dtype}}

        if "hours" not in adj_raw:
            raise ValueError(f"entry {i}: hours missing")
        hours = _normalize_hours(adj_raw.get("hours"))
        if hours is None:
            raise ValueError(f"entry {i}: invalid hours")
        adj_raw["hours"] = hours

        model = ADJUSTMENT_MODELS[dtype]
        try:
            adjustment = model.model_validate(adj_raw)
        except Exception as exc:
            raise ValueError(f"entry {i}: adjustment validation failed: {exc}") from exc

        if dtype == "minimum_battery_reserve" and battery is not None:
            cap = float(battery.get("capacity_kwh", float("inf")))
            if adjustment.minimum_energy_kwh > cap + 1e-6:
                raise ValueError(
                    f"entry {i}: minimum_energy_kwh ({adjustment.minimum_energy_kwh}) "
                    f"exceeds battery capacity ({cap})"
                )

        validated.append(
            DirectiveInterpretation(
                note_index=idx,
                applies=True,
                directive_type=dtype,
                structured_adjustment=adjustment,
                explanation=str(raw.get("explanation", ""))[:300]
                or f"Operator note interpreted as {dtype} for hours {hours}.",
            )
        )

    if len(validated) != n_notes:
        raise ValueError("mapping incomplete")
    return validated
