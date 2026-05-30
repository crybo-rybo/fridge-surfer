import logging
from collections.abc import Callable

import requests

from remy import config, ollama_client
from remy.ollama_client import raise_for_ollama_status

logger = logging.getLogger(__name__)
StreamCallback = Callable[[str, str], None]
_TIMEOUT = 180


def _summarize_titles(recipes: list[str]) -> str:
    """Collapse recipe texts to their title lines for compact prompt context."""
    return "; ".join(
        r.splitlines()[0] if r.splitlines() else r[:60]
        for r in recipes
    )


def build_user_content(
    ingredients: list[str],
    recent_recipes: list[str],
    favorites: list[str] | None = None,
    dislikes: list[str] | None = None,
    constraints: str | None = None,
) -> str:
    """Assemble the chef's user message from ingredients and feedback history.

    Pure function (no I/O) so the prompt-shaping logic can be unit tested.
    """
    parts = [f"Available ingredients: {', '.join(ingredients)}"]

    if recent_recipes:
        parts.append(
            "Please suggest something different from these recent recipes: "
            f"{_summarize_titles(recent_recipes)}"
        )
    if favorites:
        parts.append(
            "The cook rated these recipes highly — lean toward this style: "
            f"{_summarize_titles(favorites)}"
        )
    if dislikes:
        parts.append(
            "The cook disliked these recipes — avoid anything similar: "
            f"{_summarize_titles(dislikes)}"
        )
    if constraints:
        parts.append(f"Dietary constraints / preferences: {constraints}")

    return "\n".join(parts)


def generate_recipe(
    ingredients: list[str],
    recent_recipes: list[str],
    favorites: list[str] | None = None,
    dislikes: list[str] | None = None,
    constraints: str | None = None,
    stream_callback: StreamCallback | None = None,
) -> str:
    """Call the Ollama chat LLM and return a recipe as plain text."""
    user_content = build_user_content(
        ingredients, recent_recipes, favorites, dislikes, constraints
    )

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
