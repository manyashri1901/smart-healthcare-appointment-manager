"""Provider-agnostic LLM adapter for pre-visit and post-visit summaries.

Env vars:
    LLM_PROVIDER   anthropic | openai | emergent | "" (unavailable)
    LLM_API_KEY    provider API key
    LLM_MODEL      e.g. claude-haiku-4-5, gpt-4o-mini, ...
    LLM_BASE_URL   optional custom endpoint (OpenAI-compatible)

If credentials are absent the adapter returns a FAILED/UNAVAILABLE status —
the caller must persist that status and keep the appointment usable.
"""
from __future__ import annotations
import json
import logging
from typing import Any
import httpx

from .. import config

log = logging.getLogger("llm")

PRE_VISIT_PROMPT = """You are assisting a doctor by organizing patient-provided symptoms.

Analyze the symptoms and return ONLY valid JSON with this shape:

{{
  "urgency_level": "Low | Medium | High",
  "chief_complaint": "...",
  "summary": "...",
  "suggested_questions": ["...", "...", "..."]
}}

Do not diagnose the patient. Do not prescribe medication. Do not invent symptoms.
Base the response only on the information provided.

Patient symptoms:
{symptoms}
"""

POST_VISIT_PROMPT = """You are converting a doctor's clinical notes into a clear patient-friendly visit summary.

Return ONLY valid JSON:

{{
  "summary": "...",
  "medications": [
    {{"name": "...", "dosage": "...", "frequency": "...", "duration": "...", "instructions": "..."}}
  ],
  "follow_up_steps": ["...", "..."]
}}

Use only information supplied by the doctor. Do not invent medical information.
Do not change medication dosage. Do not add diagnoses that are not present.

Doctor's notes:
{notes}

Prescription:
{prescription}

Follow-up:
{follow_up}
"""


def _configured() -> bool:
    return bool(config.LLM_PROVIDER and config.LLM_API_KEY)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object even if the model wrapped it in markdown/prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    # find first { and last }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in model response")
    return json.loads(text[start : end + 1])


async def _call_anthropic(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.LLM_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": config.LLM_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]


async def _call_openai(prompt: str) -> str:
    base = config.LLM_BASE_URL or "https://api.openai.com/v1"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _call_emergent(prompt: str) -> str:
    """Uses emergentintegrations package if configured with the Universal Key."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # lazy import

    chat = LlmChat(api_key=config.LLM_API_KEY, session_id="pulsecare", system_message="Return only JSON.")
    chat.with_model("anthropic", config.LLM_MODEL)
    response = await chat.send_message(UserMessage(text=prompt))
    return response


async def _generate(prompt: str) -> dict:
    if not _configured():
        return {"status": "UNAVAILABLE", "error": "LLM not configured", "model": config.LLM_MODEL}
    provider = (config.LLM_PROVIDER or "").lower()
    try:
        if provider == "anthropic":
            text = await _call_anthropic(prompt)
        elif provider == "openai":
            text = await _call_openai(prompt)
        elif provider == "emergent":
            text = await _call_emergent(prompt)
        else:
            return {"status": "UNAVAILABLE", "error": f"Unknown provider '{provider}'", "model": config.LLM_MODEL}
        payload = _extract_json(text)
        return {"status": "COMPLETED", "payload": payload, "model": config.LLM_MODEL}
    except Exception as e:  # pragma: no cover — graceful degradation
        log.warning("LLM call failed: %s", e)
        return {"status": "FAILED", "error": str(e)[:400], "model": config.LLM_MODEL}


async def generate_pre_visit_summary(symptoms: dict) -> dict:
    text = json.dumps(symptoms, ensure_ascii=False)
    return await _generate(PRE_VISIT_PROMPT.format(symptoms=text))


async def generate_post_visit_summary(clinical: dict) -> dict:
    return await _generate(
        POST_VISIT_PROMPT.format(
            notes=clinical.get("clinical_notes", ""),
            prescription=json.dumps(clinical.get("medications", []), ensure_ascii=False),
            follow_up=clinical.get("follow_up_instructions", ""),
        )
    )
