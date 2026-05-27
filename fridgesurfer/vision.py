import base64
import json
import logging
import re
from collections.abc import Callable

import requests

from fridgesurfer import config
from fridgesurfer.ollama_client import raise_for_ollama_status

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = "List all food items visible as a JSON array of strings."
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


def _format_stats(chunk: dict) -> str:
    parts = []
    for key, label in (
        ("load_duration", "load"),
        ("prompt_eval_duration", "prompt_eval"),
        ("eval_duration", "eval"),
        ("total_duration", "total"),
    ):
        value = chunk.get(key)
        if isinstance(value, int):
            parts.append(f"{label}={value / 1_000_000_000:.2f}s")

    for key, label in (
        ("prompt_eval_count", "prompt_tokens"),
        ("eval_count", "output_tokens"),
    ):
        value = chunk.get(key)
        if isinstance(value, int):
            parts.append(f"{label}={value}")

    return ", ".join(parts)


def _stream_generate(payload: dict, callback: StreamCallback) -> str:
    raw_parts: list[str] = []

    with requests.post(
        f"{config.OLLAMA_HOST}/api/generate",
        json=payload,
        timeout=120,
        stream=True,
    ) as resp:
        raise_for_ollama_status(resp, model=payload["model"], endpoint="/api/generate")

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue

            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Ignoring unparseable Ollama stream line: %r", line)
                continue

            if error := chunk.get("error"):
                raise RuntimeError(str(error))

            thinking = chunk.get("thinking")
            if thinking:
                callback("thinking", str(thinking))

            response = chunk.get("response")
            if response:
                text = str(response)
                raw_parts.append(text)
                callback("response", text)

            if chunk.get("done"):
                stats = _format_stats(chunk)
                if stats:
                    callback("stats", stats)

    return "".join(raw_parts)


def extract_ingredients(
    image_bytes: bytes,
    model: str | None = None,
    stream_callback: StreamCallback | None = None,
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
                timeout=120,
            )
            raise_for_ollama_status(resp, model=payload["model"], endpoint="/api/generate")
            raw = resp.json().get("response", "")
        else:
            raw = _stream_generate(payload, stream_callback)
    except Exception:
        logger.exception("VLM call failed (model=%r)", model)
        return []

    logger.debug("VLM raw output: %r", raw)

    ingredients = _parse(raw)
    logger.info("Extracted %d ingredients via %r", len(ingredients), model)
    return ingredients
