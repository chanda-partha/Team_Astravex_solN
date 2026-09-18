"""GridWise API service: LLM interpretation -> guardrails -> LP optimization."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .guardrails import validate_interpretation
from .llm_client import interpret_notes
from .optimizer import solve
from .schemas import OptimizeRequest, OptimizeResponse
from .validator import validate_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gridwise.main")

app = FastAPI(title="GridWise Energy Optimizer", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _build_plan_summary(plan: list[dict], directives) -> str:
    """Deterministic human-readable summary (LLM not needed here)."""
    applied = [d.directive_type for d in directives if d.applies]
    charges = [p["battery_kwh"] for p in plan if p["battery_action"] == "charge"]
    discharge_hours = [p["hour"] for p in plan if p["battery_action"] == "discharge"]
    total_grid = sum(p["grid_kwh"] for p in plan)

    parts = [
        "Schedule applies " + (", ".join(applied) if applied else "no directives") + ".",
        f"Total grid purchase {total_grid:.1f} kWh.",
    ]
    if charges:
        parts.append(f"Charging peaks at {max(charges):.1f} kWh/h.")
    if discharge_hours:
        parts.append(
            f"Discharges during hours {min(discharge_hours)}-{max(discharge_hours)} "
            "toward peak tariffs, ending at the initial battery level."
        )
    return " ".join(parts)


@app.post("/optimize-energy")
async def optimize_energy(request: OptimizeRequest) -> JSONResponse:
    hours_data = [h.model_dump() for h in request.hours]
    battery = request.battery.model_dump()
    notes = request.operator_notes

    # 1) LLM interpretation with deterministic guardrails in the loop
    raw, model_used = interpret_notes(
        notes, battery, validate_fn=lambda e: validate_interpretation(e, len(notes))
    )

    # 2) Deterministic guardrails (already validated inside the loop; re-validate
    #    for a typed object we own)
    directives = validate_interpretation(raw, len(notes))

    # 3) Optimize under interpreted directives
    plan = solve(hours_data, battery, directives)
    if plan is None:
        return JSONResponse(
            status_code=422,
            content={
                "error": "infeasible_under_interpreted_directives",
                "detail": "No valid 24h schedule exists for the interpreted directives.",
                "directive_interpretation": [d.model_dump(mode="json") for d in directives],
            },
        )

    # 4) Self-replay validation before responding
    ok, errors = validate_plan(plan, hours_data, battery, directives)
    if not ok:
        logger.error("Self-validation failed: %s", errors)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_validation_failed", "detail": errors[:10]},
        )

    total_grid = sum(p["grid_kwh"] for p in plan)
    total_cost = sum(
        p["grid_kwh"] * hours_data[i]["tariff_bdt_per_kwh"] for i, p in enumerate(plan)
    )
    peak = max(p["grid_kwh"] for p in plan)

    return JSONResponse(
        status_code=200,
        content={
            "scenario_id": request.scenario_id,
            "directive_interpretation": [d.model_dump(mode="json") for d in directives],
            "hourly_plan": plan,
            "total_grid_kwh": round(total_grid, 4),
            "total_cost_bdt": round(total_cost, 4),
            "peak_grid_kwh": round(peak, 4),
            "plan_summary": _build_plan_summary(plan, directives),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Malformed JSON or structurally invalid request -> 400 (spec section 6.1)."""
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": "Malformed JSON or structurally invalid request."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "Controlled internal failure."},
    )
