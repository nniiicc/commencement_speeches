"""Anthropic LLM extraction for Step 1 (speaker identity).

Returns the structured schema from design doc Section 5, Step 1.4.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from commencement.config import CONFIG

log = logging.getLogger(__name__)


@dataclass
class SpeakerExtraction:
    speaker_name: str | None
    speaker_role: str | None
    ceremony_date: str | None
    ceremony_type: str
    source_url: str
    is_official_institution_source: bool
    confidence: float
    notes: str | None = None


def _extraction_system_prompt(year: int) -> str:
    return f"""You extract structured facts about a single university's {year}
universitywide commencement ceremony from a set of candidate web pages.

CRITICAL RULES
- The target ceremony is the universitywide / main / institution-wide ceremony.
  Per-college or departmental convocations (e.g., "School of Engineering convocation",
  "Graduate College ceremony") are NOT the target. If the only evidence you have is
  for a per-college event, return ceremony_type="per_college".
- Pull facts only from the supplied pages. Do not guess from prior knowledge.
- If multiple pages give conflicting names, trust the institution's own press
  release / news page over third-party coverage. Set
  is_official_institution_source accordingly.
- If you cannot determine a fact, set the field to null and lower confidence.
- confidence is a 0..1 calibrated estimate of "the universitywide {year} speaker for
  this institution is exactly the person I extracted". Bake in your uncertainty.

OUTPUT
Return ONLY a single JSON object matching this schema, no preamble:
{{
  "speaker_name": string | null,
  "speaker_role": string | null,
  "ceremony_date": "YYYY-MM-DD" | null,
  "ceremony_type": "universitywide" | "per_college" | "unknown",
  "source_url": string,
  "is_official_institution_source": bool,
  "confidence": number,
  "notes": string | null
}}
"""


def _format_pages(institution_name: str, pages: list[dict], year: int) -> str:
    body = [f"Institution: {institution_name}", f"Target year: {year}\n"]
    for i, p in enumerate(pages, 1):
        body.append(f"--- PAGE {i} ---")
        body.append(f"URL: {p.get('url', '')}")
        if p.get("title"):
            body.append(f"TITLE: {p['title']}")
        if p.get("snippet"):
            body.append(f"SNIPPET: {p['snippet']}")
        if p.get("text"):
            text = p["text"]
            if len(text) > 8000:
                text = text[:8000] + "\n...[truncated]"
            body.append(f"TEXT:\n{text}")
        body.append("")
    return "\n".join(body)


def extract_speaker(
    institution_name: str,
    pages: list[dict],
    model: Optional[str] = None,
    year: int = CONFIG.PILOT_YEAR,
) -> SpeakerExtraction | None:
    if not CONFIG.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError("anthropic SDK is not installed") from e

    client = Anthropic(api_key=CONFIG.ANTHROPIC_API_KEY)
    user_content = _format_pages(institution_name, pages, year)

    try:
        resp = client.messages.create(
            model=model or CONFIG.LLM_MODEL_EXTRACTION,
            max_tokens=800,
            system=_extraction_system_prompt(year),
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        log.warning("anthropic call failed for %s: %s", institution_name, e)
        return None

    text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM did not return valid JSON for %s: %.200r", institution_name, text)
        return None

    return SpeakerExtraction(
        speaker_name=data.get("speaker_name"),
        speaker_role=data.get("speaker_role"),
        ceremony_date=data.get("ceremony_date"),
        ceremony_type=data.get("ceremony_type", "unknown"),
        source_url=data.get("source_url", ""),
        is_official_institution_source=bool(data.get("is_official_institution_source", False)),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        notes=data.get("notes"),
    )
