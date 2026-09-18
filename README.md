# GridWise — BUP CSE Fest 2026 (Preliminary)

LLM-assisted smart-campus energy scheduling service for the BUP CSE Fest 2026
online preliminary. Interprets natural-language operator notes with an LLM,
validates them with deterministic guardrails, then produces a valid,
minimum-cost 24-hour energy schedule via linear programming.

## Architecture

```
POST /optimize-energy
   │
   ├─ 1. LLM (Groq, gpt-oss-120b / fallback gpt-oss-20b)
   │       converts each operator note into a structured directive
   │
   ├─ 2. Deterministic guardrails (app/guardrails.py)
   │       directive whitelist, note mapping/order, hours 0-23 unique
   │       ascending, applies semantics, numeric ranges, shape normalization
   │       rejected LLM output triggers a self-correction retry with feedback
   │
   ├─ 3. LP optimizer (app/optimizer.py, PuLP + CBC)
   │       minimizes Σ grid[h] × tariff[h] subject to energy balance,
   │       battery bounds/rates, end-of-day neutrality, effective solar
   │       (after solar_reduction), reserve/no-charge/no-discharge/grid-cap
   │
   └─ 4. Self-replay validator (app/validator.py)
           replays the plan; the response is only sent if every rule holds
```

The LLM is in the directive-interpretation path (mandatory requirement);
deterministic code owns validation and optimization.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | yes | — | Groq API key (never commit; provide at runtime) |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | Primary interpretation model |
| `GROQ_FALLBACK_MODEL` | no | `openai/gpt-oss-20b` | Fallback model |
| `GROQ_BASE_URL` | no | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint |
| `PORT` | no | `8000` | HTTP port (Docker) |

Copy `.env.example` to `.env` and fill in `GROQ_API_KEY`. The `.env` file is
gitignored and must never be committed or baked into the Docker image.

## Local quickstart

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # then edit .env: GROQ_API_KEY=...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Optimize request

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @samples/case_01.json
```

Sample response (abridged):

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {"note_index": 0, "applies": true, "directive_type": "solar_reduction",
     "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
     "explanation": "Solar availability reduced to 25% during panel cleaning."},
    {"note_index": 1, "applies": false, "directive_type": "no_op",
     "structured_adjustment": null, "explanation": "..."}
  ],
  "hourly_plan": [
    {"hour": 0, "grid_kwh": 90, "solar_used_kwh": 0, "battery_action": "idle",
     "battery_kwh": 0, "battery_energy_after_kwh": 110}
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "..."
}
```

## Run the public sample pack

```bash
python scripts/test_samples.py --url http://localhost:8000
# health: 200 {"status":"ok"}
# SAMPLE-01 ... VALID cost=38365.0 ref=38365.0 ratio=1.000
# ...
# 10/10 cases valid
```

The script replays each returned plan independently (energy balance, battery
rules, directives, end-of-day neutrality) and compares the recalculated cost
against the organizer reference.

## Docker

```bash
docker build -t gridwise:latest .
docker run --rm -p 8000:8000 -e GROQ_API_KEY=your_key gridwise:latest
curl http://localhost:8000/health
```

The image binds `0.0.0.0`, exposes port `8000`, and contains no secrets.

## API behavior

- `GET /health` → `200 {"status":"ok"}`
- `POST /optimize-energy` → `200` with interpretation + plan
- Malformed JSON / structurally invalid request → `400`
- Infeasible under interpreted directives → `422`
- Controlled internal error → `500` (no stack traces, no secrets)

## Known limitations

- Cost optimality depends on the CBC solver; equivalent alternative optimal
  schedules may differ from the judge reference while scoring identically.
- Reserve/percentage conversions use only the battery capacity supplied in
  the request; no other request values are modified.
- LLM interpretation depends on Groq availability; retries, a fallback model,
  and deterministic guardrails bound the failure modes.
