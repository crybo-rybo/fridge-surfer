import json
import logging
from collections.abc import Callable

import requests

from remy import config

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str, str], None]


def raise_for_ollama_status(resp: requests.Response, *, model: str, endpoint: str) -> None:
    """Raise for HTTP errors and log Ollama's response body for easier diagnosis."""
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        body = resp.text.strip() if resp.text else "(empty body)"
        if len(body) > 500:
            body = body[:500] + "..."
        logger.error(
            "Ollama %s failed for model=%r: HTTP %s — %s",
            endpoint,
            model,
            resp.status_code,
            body,
        )
        raise


def format_stats(chunk: dict) -> str:
    """Render a final Ollama chunk's timing/token fields as a one-line summary."""
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


def stream_request(
    endpoint: str,
    payload: dict,
    callback: StreamCallback,
    timeout: float,
) -> str:
    """POST a streaming request to Ollama and return the accumulated text.

    Invokes ``callback(kind, text)`` for each ``thinking`` / ``response`` chunk
    and a final ``stats`` line. Handles both the /api/generate shape (top-level
    ``response``) and the /api/chat shape (``message.content``), so vision and
    chef can share one loop.
    """
    raw_parts: list[str] = []

    with requests.post(
        f"{config.OLLAMA_HOST}{endpoint}",
        json=payload,
        timeout=timeout,
        stream=True,
    ) as resp:
        raise_for_ollama_status(resp, model=payload["model"], endpoint=endpoint)

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
                stats = format_stats(chunk)
                if stats:
                    callback("stats", stats)

    return "".join(raw_parts)
