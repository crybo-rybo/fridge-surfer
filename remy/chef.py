import logging
from collections.abc import Callable

import requests

from remy import config, ollama_client
from remy.ollama_client import raise_for_ollama_status

logger = logging.getLogger(__name__)
StreamCallback = Callable[[str, str], None]
_TIMEOUT = 180


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
                timeout=_TIMEOUT,
            )
            raise_for_ollama_status(resp, model=payload["model"], endpoint="/api/chat")
            recipe = resp.json()["message"]["content"].strip()
        else:
            recipe = ollama_client.stream_request(
                "/api/chat", payload, stream_callback, timeout=_TIMEOUT
            ).strip()
    except Exception:
        logger.exception("Chef LLM call failed (model=%r)", config.CHEF_MODEL)
        raise

    logger.info("Generated recipe (%d chars)", len(recipe))
    return recipe
