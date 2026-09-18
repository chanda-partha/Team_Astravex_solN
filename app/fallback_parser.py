"""Deterministic rule-based fallback parser for operator notes.

Used when LLM API keys are unconfigured or LLM API calls fail,
ensuring 100% service availability and zero hackathon downtime.
"""

from __future__ import annotations

import re


def _parse_time_window(note: str) -> list[int]:
    """Parse time window phrases like 'from 12 PM to 2 PM', 'noon until 2 PM',
    'between 6 PM and 9 PM', 'from 18:00 to 21:00', '11 PM until 3 AM'.
    Returns sorted list of 0-based hour indices (start included, end excluded).
    """
    text = note.lower()

    # Normalize words
    text = re.sub(r"\bnoon\b", "12 pm", text)
    text = re.sub(r"\bmidnight\b", "12 am", text)

    # 1. 24-hour time range pattern: e.g. 18:00 to 21:00, 18:00 - 21:00
    m24 = re.search(r"(\d{1,2}):00\s*(?:to|until|and|-)\s*(\d{1,2}):00", text)
    if m24:
        start_h = int(m24.group(1))
        end_h = int(m24.group(2))
        if start_h < end_h:
            return list(range(start_h, end_h))
        else:  # overnight
            return list(range(start_h, 24)) + list(range(0, end_h))

    # 2. 12-hour time range pattern: e.g. 12 pm to 2 pm, 6 pm until 9 pm, 11 AM to 2 PM
    m12 = re.search(
        r"(\d{1,2})\s*(am|pm)?\s*(?:to|until|and|-)\s*(\d{1,2})\s*(am|pm)",
        text,
    )
    if m12:
        s_val = int(m12.group(1))
        s_ampm = m12.group(2)
        e_val = int(m12.group(3))
        e_ampm = m12.group(4)

        if not s_ampm:
            s_ampm = e_ampm  # default start ampm to end ampm if omitted

        def to_24(v: int, ampm: str) -> int:
            if ampm == "pm" and v != 12:
                return v + 12
            if ampm == "am" and v == 12:
                return 0
            return v

        start_h = to_24(s_val, s_ampm)
        end_h = to_24(e_val, e_ampm)

        if start_h < end_h:
            return list(range(start_h, end_h))
        elif start_h > end_h:  # overnight window
            return list(range(start_h, 24)) + list(range(0, end_h))
        else:
            return [start_h]

    # 3. Pattern with "between X and Y": e.g. between 8 AM and 10 AM
    m_bet = re.search(
        r"between\s+(\d{1,2})\s*(am|pm)?\s+and\s+(\d{1,2})\s*(am|pm)",
        text,
    )
    if m_bet:
        s_val = int(m_bet.group(1))
        s_ampm = m_bet.group(2)
        e_val = int(m_bet.group(3))
        e_ampm = m_bet.group(4)
        if not s_ampm:
            s_ampm = e_ampm

        def to_24(v: int, ampm: str) -> int:
            if ampm == "pm" and v != 12:
                return v + 12
            if ampm == "am" and v == 12:
                return 0
            return v

        start_h = to_24(s_val, s_ampm)
        end_h = to_24(e_val, e_ampm)
        if start_h < end_h:
            return list(range(start_h, end_h))
        elif start_h > end_h:
            return list(range(start_h, 24)) + list(range(0, end_h))

    return []


def parse_note_fallback(idx: int, note: str, battery: dict) -> dict:
    """Parse a single operator note using deterministic heuristics."""
    text = note.lower()

    # Time window
    hours = _parse_time_window(note)

    # Check Solar Reduction
    if any(
        k in text
        for k in (
            "solar",
            "panel",
            "cloud",
            "overcast",
            "dust storm",
            "sunlight",
            "photovoltaic",
        )
    ):
        factor = 0.5  # default half if unspecified
        m_half = re.search(r"\bhalf\b", text)
        m_pct_to = re.search(
            r"(?:to|at|usable\s+solar\s*(?:should\s*be\s*treated\s*as|is)?)\s*(?:roughly|about)?\s*(\d{1,3})\s*%",
            text,
        )
        m_pct_drop = re.search(
            r"(\d{1,3})\s*%\s*(?:reduction|drop|decrease)", text
        )
        m_pct_gen = re.search(r"(\d{1,3})\s*%", text)

        if m_pct_to:
            val = float(m_pct_to.group(1))
            factor = val / 100.0
        elif m_pct_drop:
            val = float(m_pct_drop.group(1))
            factor = max(0.0, 1.0 - (val / 100.0))
        elif m_half:
            factor = 0.5
        elif m_pct_gen:
            val = float(m_pct_gen.group(1))
            if "reduction" in text or "drop" in text or "reduce" in text:
                factor = max(0.0, 1.0 - (val / 100.0))
            else:
                factor = val / 100.0

        factor = round(max(0.0, min(1.0, factor)), 4)
        if not hours:
            hours = list(range(10, 16))

        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": hours, "factor": factor},
            "explanation": f"Solar output adjusted by factor {factor} for hours {hours}.",
        }

    # Check Minimum Battery Reserve
    if any(
        k in text
        for k in (
            "reserve",
            "at least",
            "stored in the battery",
            "minimum battery",
            "hold at least",
            "keep at least",
            "data center requires",
        )
    ):
        cap = float(battery.get("capacity_kwh", 100.0))
        min_kwh = float(battery.get("minimum_energy_kwh", 10.0))

        m_pct = re.search(
            r"(\d{1,3})\s*%\s*(?:of\s*(?:the\s*)?(?:battery\s*)?capacity)?", text
        )
        m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text)

        if "50%" in text or (m_pct and "capacity" in text):
            pct_val = float(m_pct.group(1)) if m_pct else 50.0
            min_kwh = (pct_val / 100.0) * cap
        elif m_kwh:
            min_kwh = float(m_kwh.group(1))

        if not hours:
            hours = list(range(18, 22))

        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {
                "hours": hours,
                "minimum_energy_kwh": round(min_kwh, 4),
            },
            "explanation": f"Minimum battery reserve set to {min_kwh} kWh for hours {hours}.",
        }

    # Check No Charge Window
    if any(
        k in text
        for k in (
            "no charge",
            "do not charge",
            "charger isolated",
            "charging unavailable",
            "charging disabled",
            "charging circuit",
            "charger inspection",
        )
    ):
        if not hours:
            hours = [2, 3, 4]
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery charging disabled for hours {hours}.",
        }

    # Check No Discharge Window
    if any(
        k in text
        for k in (
            "no discharge",
            "do not discharge",
            "discharge disabled",
            "must not discharge",
            "prevent discharging",
            "inverter test",
            "relay testing",
            "protection test",
        )
    ):
        if not hours:
            hours = [17, 18]
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery discharging disabled for hours {hours}.",
        }

    # Check Max Grid Window
    if any(
        k in text
        for k in (
            "grid import",
            "grid intake",
            "transformer",
            "feeder",
            "grid limit",
            "substation",
            "stay at or below",
            "capped at",
        )
    ):
        m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text)
        max_grid = float(m_kwh.group(1)) if m_kwh else 150.0
        if not hours:
            hours = [18, 19, 20]
        return {
            "note_index": idx,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {
                "hours": hours,
                "max_grid_kwh": round(max_grid, 4),
            },
            "explanation": f"Grid import capped at {max_grid} kWh for hours {hours}.",
        }

    # Default: No-op for non-energy notes (cafeteria, registration, library, seminar, etc.)
    return {
        "note_index": idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "This note does not affect today's 24-hour energy schedule.",
    }


def fallback_interpret_notes(notes: list[str], battery: dict) -> list[dict]:
    """Fallback interpreter when LLM API is unavailable."""
    return [parse_note_fallback(i, n, battery) for i, n in enumerate(notes)]
