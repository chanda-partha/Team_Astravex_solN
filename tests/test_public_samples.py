"""Test all 10 public sample cases end-to-end using the FastAPI TestClient and replay check."""

import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.validator import validate_plan

client = TestClient(app)


def load_sample_cases():
    with open("samples/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


@pytest.mark.parametrize("case", load_sample_cases(), ids=lambda c: c["id"])
def test_public_sample_case(case):
    cid = case["id"]
    payload = case["input"]
    expected_directives = case.get("expected_output", {}).get("directive_interpretation", [])

    # Test with expected directive interpretation mock
    with patch("app.main.interpret_notes", return_value=(expected_directives, "mock-model")):
        resp = client.post("/optimize-energy", json=payload)
        assert resp.status_code == 200, f"Case {cid} failed with {resp.status_code}: {resp.text}"

        data = resp.json()

        # 1. Check response structure
        assert data["scenario_id"] == payload["scenario_id"]
        assert len(data["directive_interpretation"]) == len(payload["operator_notes"])
        assert len(data["hourly_plan"]) == 24
        assert "total_grid_kwh" in data
        assert "total_cost_bdt" in data
        assert "peak_grid_kwh" in data
        assert "plan_summary" in data

        # 2. Check directive interpretation
        for idx, inter in enumerate(data["directive_interpretation"]):
            assert inter["note_index"] == idx
            assert inter["directive_type"] == expected_directives[idx]["directive_type"]
            assert inter["applies"] == expected_directives[idx]["applies"]

        # 3. Independent Replay Validation using validator.py
        directives_models = [
            # Re-parse into DirectiveInterpretation models
            inter for inter in data["directive_interpretation"]
        ]

        from app.guardrails import validate_interpretation
        validated_directives = validate_interpretation(directives_models, len(payload["operator_notes"]), payload["battery"])

        metrics = {
            "total_grid_kwh": data["total_grid_kwh"],
            "total_cost_bdt": data["total_cost_bdt"],
            "peak_grid_kwh": data["peak_grid_kwh"],
        }

        is_valid, errors = validate_plan(
            data["hourly_plan"],
            payload["hours"],
            payload["battery"],
            validated_directives,
            metrics=metrics,
        )

        assert is_valid, f"Case {cid} replay validation errors: {errors}"
