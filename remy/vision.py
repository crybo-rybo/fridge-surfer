import base64
import json
import logging
import re
from collections.abc import Callable

import requests

from remy import config, ollama_client
from remy.ollama_client import raise_for_ollama_status

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = "List all food items visible as a JSON array of strings."
_TIMEOUT = 120
StreamCallback = Callable[[str, str], None]


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


def _union(passes: list[list[str]]) -> list[str]:
    """Merge per-pass ingredient lists, case-insensitively, first-seen order."""
    seen: set[str] = set()
    merged: list[str] = []
    for items in passes:
        for item in items:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def _extract_once(
    image_b64: str,
    model: str,
    prompt: str,
    stream_callback: StreamCallback | None,
) -> list[str]:
    """Run a single VLM pass and return its parsed ingredients ([] on failure)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": stream_callback is not None,
        "think": False,
        # Unload immediately so the chef model can load on memory-constrained devices.
        "keep_alive": 0,
        "options": {
            "num_ctx": config.VISION_NUM_CTX,
        },
    }

    try:
        if stream_callback is None:
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/generate",
                json=payload,
                timeout=_TIMEOUT,
            )
            raise_for_ollama_status(resp, model=payload["model"], endpoint="/api/generate")
            raw = resp.json().get("response", "")
        else:
            raw = ollama_client.stream_request(
                "/api/generate", payload, stream_callback, timeout=_TIMEOUT
            )
    except Exception:
        logger.exception("VLM call failed (model=%r)", model)
        return []

    logger.debug("VLM raw output: %r", raw)
    return _parse(raw)


def extract_ingredients(
    image_bytes: bytes,
    model: str | None = None,
    stream_callback: StreamCallback | None = None,
    passes: int | None = None,
) -> list[str]:
    """Call the Ollama VLM and return a clean list of ingredient strings.

    Runs ``passes`` independent VLM passes (default: config.VISION_PASSES) and
    unions the results to catch items a single pass misses. Streaming inspects a
    single pass, so a stream_callback forces one pass. Returns [] if every pass
    fails or yields nothing.
    """
    model = model or config.VISION_MODEL
    prompt = _prompt_for(model)
    image_b64 = base64.standard_b64encode(image_bytes).decode()

    n = passes if passes is not None else config.VISION_PASSES
    if stream_callback is not None:
        n = 1  # streaming inspects a single pass
    n = max(1, n)

    results = [
        _extract_once(image_b64, model, prompt, stream_callback) for _ in range(n)
    ]
    ingredients = _union(results)
    logger.info(
        "Extracted %d ingredients via %r over %d pass(es)", len(ingredients), model, n
    )
    return ingredients
