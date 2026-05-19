import json
import logging
from collections.abc import Callable

import requests

from fridgesurfer import config

logger = logging.getLogger(__name__)
StreamCallback = Callable[[str, str], None]


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


def _stream_chat(payload: dict, callback: StreamCallback) -> str:
    raw_parts: list[str] = []

    with requests.post(
        f"{config.OLLAMA_HOST}/api/chat",
        json=payload,
        timeout=180,
        stream=True,
    ) as resp:
        resp.raise_for_status()

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

            message = chunk.get("message")
            if not isinstance(message, dict):
                message = {}

            thinking = chunk.get("thinking") or message.get("thinking")
            if thinking:
                callback("thinking", str(thinking))

            content = (
                chunk.get("response")
                or chunk.get("content")
                or message.get("content")
            )
            if content:
                text = str(content)
                raw_parts.append(text)
                callback("response", text)

            if chunk.get("done"):
                stats = _format_stats(chunk)
                if stats:
                    callback("stats", stats)

    return "".join(raw_parts)


def generate_recipe(
    ingredients: list[str],
    recent_recipes: list[str],
    constraints: str | None = None,
    stream_callback: StreamCallback | None = None,
) -> str:
    """Call the Ollama chat LLM and return a recipe as plain text."""
    parts = [
        f"Available ingredients: {', '.join(ingredients)}",
    ]

    if recent_recipes:
        recent_summary = "; ".join(
            r.splitlines()[0] if r.splitlines() else r[:60]
            for r in recent_recipes
        )
        parts.append(
            f"Please suggest something different from these recent recipes: {recent_summary}"
        )

    if constraints:
        parts.append(f"Dietary constraints / preferences: {constraints}")

    user_content = "\n".join(parts)

    payload = {
        "model": config.CHEF_MODEL,
        "messages": [
            {"role": "system", "content": config.CHEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": stream_callback is not None,
        "think": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {
            "num_ctx": config.CHEF_NUM_CTX,
        },
    }

    logger.debug("Chef prompt user content: %r", user_content)

    try:
        if stream_callback is None:
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            recipe = resp.json()["message"]["content"].strip()
        else:
            recipe = _stream_chat(payload, stream_callback).strip()
    except Exception:
        logger.exception("Chef LLM call failed (model=%r)", config.CHEF_MODEL)
        raise

    logger.info("Generated recipe (%d chars)", len(recipe))
    return recipe
