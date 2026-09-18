"""GridWise API service: LLM interpretation -> guardrails -> LP optimization."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .guardrails import validate_interpretation
from .llm_client import interpret_notes
from .optimizer import solve
from .schemas import OptimizeRequest
from .validator import validate_plan


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("gridwise.main")


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="GridWise Energy Optimizer",
    version="1.0.0",
)


# --------------------------------------------------
# Root endpoint
# --------------------------------------------------

@app.get("/")
def root() -> dict:
    return {
        "name": "GridWise Energy Optimizer",
        "status": "running",
        "health": "/health",
        "docs": "/docs",
        "optimize": "/optimize-energy",
    }


# --------------------------------------------------
# Health endpoint
# --------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------
# Plan summary
# --------------------------------------------------

def _build_plan_summary(plan: list[dict], directives) -> str:
    """Create a deterministic human-readable summary."""

    applied = [
        d.directive_type
        for d in directives
        if d.applies
    ]

    charges = [
        p["battery_kwh"]
        for p in plan
        if p["battery_action"] == "charge"
    ]

    discharge_hours = [
        p["hour"]
        for p in plan
        if p["battery_action"] == "discharge"
    ]

    total_grid = sum(
        p["grid_kwh"]
        for p in plan
    )

    parts = [
        "Schedule applies "
        + (", ".join(applied) if applied else "no directives")
        + ".",
        f"Total grid purchase {total_grid:.1f} kWh.",
    ]

    if charges:
        parts.append(
            f"Charging peaks at {max(charges):.1f} kWh/h."
        )

    if discharge_hours:
        parts.append(
            f"Discharges during hours "
            f"{min(discharge_hours)}-{max(discharge_hours)} "
            "toward peak tariffs, ending at the initial battery level."
        )

    return " ".join(parts)


# --------------------------------------------------
# Main optimization endpoint
# --------------------------------------------------

@app.post("/optimize-energy")
async def optimize_energy(request: OptimizeRequest) -> JSONResponse:
    try:
        hours_data = [
            hour.model_dump()
            for hour in request.hours
        ]

        battery = request.battery.model_dump()
        notes = request.operator_notes

        # 1. LLM interpretation with deterministic guardrails.
        raw, model_used = interpret_notes(
            notes,
            battery,
            validate_fn=lambda interpretation: (
                validate_interpretation(
                    interpretation,
                    len(notes),
                )
            ),
        )

        logger.info("LLM model used: %s", model_used)

        # 2. Validate the final interpreted directives.
        directives = validate_interpretation(
            raw,
            len(notes),
        )

        # 3. Optimize under interpreted directives.
        plan = solve(
            hours_data,
            battery,
            directives,
        )

        if plan is None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "infeasible_under_interpreted_directives",
                    "detail": (
                        "No valid 24h schedule exists for "
                        "the interpreted directives."
                    ),
                    "directive_interpretation": [
                        directive.model_dump(mode="json")
                        for directive in directives
                    ],
                },
            )

        # 4. Self-replay validation before responding.
        is_valid, errors = validate_plan(
            plan,
            hours_data,
            battery,
            directives,
        )

        if not is_valid:
            logger.error(
                "Self-validation failed: %s",
                errors,
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_validation_failed",
                    "detail": errors[:10],
                },
            )

        # 5. Calculate final metrics.
        total_grid = sum(
            item["grid_kwh"]
            for item in plan
        )

        total_cost = sum(
            item["grid_kwh"]
            * hours_data[index]["tariff_bdt_per_kwh"]
            for index, item in enumerate(plan)
        )

        peak_grid = max(
            item["grid_kwh"]
            for item in plan
        )

        # 6. Return the final response.
        return JSONResponse(
            status_code=200,
            content={
                "scenario_id": request.scenario_id,
                "directive_interpretation": [
                    directive.model_dump(mode="json")
                    for directive in directives
                ],
                "hourly_plan": plan,
                "total_grid_kwh": round(total_grid, 4),
                "total_cost_bdt": round(total_cost, 4),
                "peak_grid_kwh": round(peak_grid, 4),
                "plan_summary": _build_plan_summary(
                    plan,
                    directives,
                ),
            },
        )

    except Exception as exc:
        logger.exception(
            "Optimization request failed: %s",
            exc,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "Controlled internal failure.",
            },
        )


# --------------------------------------------------
# Request validation error handler
# --------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    """Return 400 for malformed or structurally invalid requests."""

    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_request",
            "detail": (
                "Malformed JSON or structurally invalid request."
            ),
        },
    )
