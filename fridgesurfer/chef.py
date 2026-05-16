import logging

import requests

from fridgesurfer import config

logger = logging.getLogger(__name__)


def generate_recipe(
    ingredients: list[str],
    recent_recipes: list[str],
    constraints: str | None = None,
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
        "stream": False,
    }

    logger.debug("Chef prompt user content: %r", user_content)

    try:
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/chat",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        recipe = resp.json()["message"]["content"].strip()
    except Exception:
        logger.exception("Chef LLM call failed (model=%r)", config.CHEF_MODEL)
        raise

    logger.info("Generated recipe (%d chars)", len(recipe))
    return recipe
