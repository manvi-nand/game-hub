from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx


DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass(frozen=True)
class TruthOrDareBatchRequest:
    scenario: str
    intensity: str
    mode: str
    prompt_type: str
    player_names: list[str]
    used_prompts: list[str]
    count: int = 50


def generate_truth_or_dare_batch(request: TruthOrDareBatchRequest) -> list[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": build_truth_or_dare_batch_prompt(request)}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 2200,
            "topP": 0.95,
            "responseMimeType": "application/json",
        },
    }

    try:
        with httpx.Client(timeout=12.0) as client:
            response = client.post(
                GEMINI_ENDPOINT.format(model=model),
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            text = extract_text(response.json())
            return clean_prompt_batch(text, request.count)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return []


def build_truth_or_dare_batch_prompt(request: TruthOrDareBatchRequest) -> str:
    used = "\n".join(f"- {prompt}" for prompt in request.used_prompts[-80:]) or "- None yet"
    players = ", ".join(request.player_names)
    scenario = request.scenario or "A same-room group playing a casual party game."
    return f"""
Generate {request.count} unique {request.prompt_type} prompts for a Truth or Dare game.

Return strict JSON only in this shape:
{{"prompts":["prompt 1","prompt 2"]}}

Game context:
- Scenario: {scenario}
- Intensity: {request.intensity}
- Room mode: {request.mode}
- Players physically present: {players}
- Previously used prompts to avoid:
{used}

Rules:
- Each prompt must be one or two short sentences.
- Make prompts feel tailored to the scenario and suitable for people physically present.
- Stay within the requested intensity:
  - mild: light, friendly, low-pressure.
  - medium: playful, revealing, mildly embarrassing, but still comfortable.
  - wild: bold and energetic, but never explicit, unsafe, coercive, damaging, or illegal.
- Do not involve anyone outside the room.
- Do not pressure disclosure of genuinely private, traumatic, medical, financial, sexual, or illegal information.
- Dares must be physically safe, non-destructive, and possible in the room.
- Keep all content non-explicit at every intensity.
- Do not include labels, numbering, markdown, or duplicate prompts.
""".strip()


def extract_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    parts = candidates[0]["content"].get("parts") or []
    return "".join(str(part.get("text") or "") for part in parts)


def clean_prompt_batch(text: str, limit: int) -> list[str]:
    raw_items = parse_prompt_items(text)
    prompts: list[str] = []
    seen = set()
    for item in raw_items:
        cleaned = clean_prompt(item)
        key = cleaned.casefold() if cleaned else ""
        if cleaned and key not in seen:
            prompts.append(cleaned)
            seen.add(key)
        if len(prompts) >= limit:
            break
    return prompts


def parse_prompt_items(text: str) -> list[str]:
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = parsed.get("prompts", [])
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def clean_prompt(text: str) -> str | None:
    prompt = re.sub(r"\s+", " ", text).strip().strip('"').strip("'")
    prompt = re.sub(r"^(truth|dare)\s*:\s*", "", prompt, flags=re.IGNORECASE).strip()
    prompt = re.sub(r"^\d+[\).\-\s]+", "", prompt).strip()
    if not prompt:
        return None
    return prompt[:280]
