import logging

import requests

logger = logging.getLogger(__name__)


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
