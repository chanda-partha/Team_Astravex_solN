# GridWise Energy Optimizer

**BUP CSE Fest 2026 Smart Campus Energy Optimization Challenge**  
*LLM-Assisted Operator Directive Interpretation & 24-Hour Schedule Optimization*

---

## Overview

GridWise Energy Optimizer is an intelligent energy management service designed for smart campus grids. It combines natural-language processing (via LLMs with strict deterministic guardrails) and Linear Programming (PuLP) to interpret operator directives and compute mathematically optimal 24-hour electricity dispatch schedules.

### Key Capabilities
1. **LLM-Assisted Directive Interpretation**: Parses natural-language operator notes into structured machine directives.
2. **Deterministic Guardrails**: Validates and normalizes LLM outputs against strict physical and logical constraints.
3. **Linear Programming Optimization**: Minimizes total grid electricity cost over 24 hours while prioritizing grid constraints and feasibility.
4. **Independent Replay Validator**: Runs an 18-rule verification pass on every schedule before responding to guarantee correctness.

---

## Supported Directives

The service interprets up to 3 natural-language operator notes into exactly one of six supported directive types per note:

| Directive Type | Description | Constraint Applied |
| :--- | :--- | :--- |
| `solar_reduction` | Usable solar generation reduced for specific hours | `effective_solar[h] = original_solar[h] * factor` |
| `minimum_battery_reserve` | Required minimum energy reserve for specific hours | `battery_energy_after_kwh[h] >= max(base, directive)` |
| `no_charge_window` | Battery charging disabled for specific hours | `battery_charge[h] == 0` |
| `no_discharge_window` | Battery discharging disabled for specific hours | `battery_discharge[h] == 0` |
| `max_grid_window` | Maximum grid import cap for specific hours | `grid_kwh[h] <= max_grid_kwh` |
| `no_op` | Irrelevant note (cafeteria, library, registration, etc.) | No change to optimization model |

---

## Local Setup & Environment Variables

### 1. Prerequisites
- Python 3.10+ (or Python 3.12/3.14 via `uv`)

### 2. Environment Variables
Copy `.env.example` to `.env`:

```bash
GROQ_API_KEY=your_groq_or_openai_api_key_here
GROQ_MODEL=llama-3.1-8b-instant
GROQ_FALLBACK_MODEL=llama-3.3-70b-versatile
GROQ_BASE_URL=https://api.groq.com/openai/v1
```

*Note: The LLM client automatically falls back to `OPENAI_API_KEY` or `LLM_API_KEY` if `GROQ_API_KEY` is not set.*

### 3. Installation

```bash
uv venv .venv
uv pip install -r requirements.txt pytest httpx
```

---

## Running the Service Locally

Start the server using Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Service info and endpoint links |
| `GET` | `/health` | Health check endpoint (`{"status": "ok"}`) |
| `GET` | `/docs` | OpenAPI / Swagger interactive documentation |
| `POST` | `/optimize-energy` | Main optimization endpoint |

---

## Example Request & Response

### Request (`POST /optimize-energy`)

```json
{
  "scenario_id": "SAMPLE-01",
  "operator_notes": [
    "Facilities will wash the rooftop solar panels from noon until 2 PM. Usable solar should be treated as roughly 25% of forecast.",
    "The sports office moved registration deadline."
  ],
  "hours": [
    { "hour": 0, "demand_kwh": 25.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 5.0 },
    "... (24 hours total for hours 0..23)"
  ],
  "battery": {
    "capacity_kwh": 100.0,
    "initial_energy_kwh": 50.0,
    "minimum_energy_kwh": 10.0,
    "max_charge_kwh_per_hour": 25.0,
    "max_discharge_kwh_per_hour": 25.0
  }
}
```

### Response (`HTTP 200`)

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar availability is reduced to 25% during the panel-cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 25.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 50.0
    }
  ],
  "total_grid_kwh": 580.0,
  "total_cost_bdt": 4200.0,
  "peak_grid_kwh": 35.0,
  "plan_summary": "Schedule applies solar_reduction. Total grid purchase 580.0 kWh."
}
```

---

## Automated Testing

Run the full automated test suite:

```bash
pytest -v
```

This executes:
- `tests/test_gridwise.py`: Tests all 14 required core scenarios and edge cases.
- `tests/test_public_samples.py`: Tests all 10 official public sample cases.

---

## Render Deployment Instructions

To deploy on [Render](https://render.com/):

1. **New Web Service**: Connect your repository on Render.
2. **Environment**: Python 3.12+ / Docker.
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
5. **Environment Variables**: Add `GROQ_API_KEY` (or `OPENAI_API_KEY`) in Render dashboard settings.
