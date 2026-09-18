import json
import logging
import time

from openai import OpenAI

from .config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_FALLBACK_MODEL,
    GROQ_MODEL,
)
from .fallback_parser import fallback_interpret_notes

logger = logging.getLogger("gridwise.llm")

_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    global _client
    if _client is None:
        key = GROQ_API_KEY
        if not key:
            return None
        _client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
    return _client


def _parse(raw: str) -> list[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    data = json.loads(cleaned)
    if isinstance(data, dict):
        for key in ("directives", "results", "interpretations", "notes", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("LLM JSON is not an array")
    return data


def interpret_notes(
    notes: list[str],
    battery: dict,
    validate_fn=None,
) -> tuple[list[dict], str]:
    """Interpret notes via LLM. If LLM is unconfigured or fails,
    fallback deterministically using rules.

    Returns (raw_entries, model_used).
    """
    client = _get_client()
    if client is None:
        logger.info("No LLM API key configured; using deterministic fallback parser.")
        entries = fallback_interpret_notes(notes, battery)
        if validate_fn is not None:
            validate_fn(entries)
        return entries, "deterministic-fallback"

    from .llm_prompt import SYSTEM_PROMPT

    user_content = "\n\n".join(f"[note {i}] {n}" for i, n in enumerate(notes))
    user_content += (
        f"\n\nBattery capacity_kwh = {battery.get('capacity_kwh')}"
        " (use only for percentage-to-kWh conversion)."
        "\nRespond with a JSON object {\"directives\": [ ... one object per note ... ]}"
    )

    attempts = [
        (GROQ_MODEL, 2),
        (GROQ_FALLBACK_MODEL, 1),
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    last_err: Exception | None = None
    for model, tries in attempts:
        for attempt in range(tries):
            try:
                start = time.perf_counter()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    max_tokens=4000,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content
                if not raw or not raw.strip():
                    raise ValueError("empty content from model")
                entries = _parse(raw)

                if validate_fn is not None:
                    validate_fn(entries)

                elapsed = time.perf_counter() - start
                logger.info(
                    "LLM ok model=%s attempt=%d took=%.2fs notes=%d",
                    model,
                    attempt + 1,
                    elapsed,
                    len(notes),
                )
                return entries, model
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning(
                    "LLM attempt failed model=%s try=%d: %s", model, attempt + 1, exc
                )
                if attempt + 1 < tries or model == attempts[-1][0]:
                    messages = messages[:2] + [
                        {"role": "assistant", "content": raw if 'raw' in locals() and raw else ""},
                        {
                            "role": "user",
                            "content": (
                                "Your previous answer was rejected by the deterministic "
                                f"validator with error: {exc}\n"
                                "Return the corrected JSON object {\"directives\": [...]} "
                                "following ALL conventions."
                            ),
                        },
                    ]
                time.sleep(0.4)

    logger.warning("All LLM attempts failed (%s); switching to deterministic fallback parser.", last_err)
    entries = fallback_interpret_notes(notes, battery)
    if validate_fn is not None:
        validate_fn(entries)
    return entries, "deterministic-fallback"
