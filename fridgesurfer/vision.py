import base64
import json
import logging
import re

import requests

from fridgesurfer import config

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = "List all food items visible as a JSON array of strings."


def _prompt_for(model: str) -> str:
    for key in config.VISION_PROMPTS:
        if model.startswith(key):
            return config.VISION_PROMPTS[key]
    logger.warning("No prompt registered for model=%r; using fallback", model)
    return _FALLBACK_PROMPT


def _parse(raw: str) -> list[str]:
    """JSON-first, regex fallback. Never raises."""
    raw = raw.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw)

    # Try to find a JSON array anywhere in the response
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            items = json.loads(match.group())
            if isinstance(items, list):
                return [str(i).strip() for i in items if str(i).strip()]
        except json.JSONDecodeError:
            pass

    # Comma-separated fallback (try before multi-line bullet so a single-line CSV
    # like "milk, eggs, broccoli" isn't returned as one big string)
    if "," in raw and "\n" not in raw.strip():
        items = [i.strip() for i in raw.split(",") if i.strip() and len(i.strip()) < 60]
        if len(items) > 1:
            return items

    # Bullet / numbered list fallback
    lines = [re.sub(r"^[\s\-\*\d\.\)]+", "", ln).strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln and len(ln) < 80]
    if lines:
        return lines

    # Last-resort comma split (multi-line or no commas)
    items = [i.strip() for i in raw.split(",") if i.strip() and len(i.strip()) < 60]
    return items


def extract_ingredients(
    image_bytes: bytes,
    model: str | None = None,
) -> list[str]:
    """Call the Ollama VLM and return a clean list of ingredient strings.

    Returns [] if the model output is unparseable or the request fails.
    """
    model = model or config.VISION_MODEL
    prompt = _prompt_for(model)

    image_b64 = base64.standard_b64encode(image_bytes).decode()

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception:
        logger.exception("VLM call failed (model=%r)", model)
        return []

    logger.debug("VLM raw output: %r", raw)

    ingredients = _parse(raw)
    logger.info("Extracted %d ingredients via %r", len(ingredients), model)
    return ingredients
