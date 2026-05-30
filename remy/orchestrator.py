import logging
from collections.abc import Callable

from remy import chef, config, memory, vision
from remy.camera import CameraUnavailableError

logger = logging.getLogger(__name__)
StreamCallback = Callable[[str, str], None]
# How many liked/disliked past recipes to feed the chef as taste guidance.
_FEEDBACK_RECIPES_N = 3
# Settings key for the household's standing dietary preference.
_DIET_KEY = "diet"
IngredientsCallback = Callable[[list[str]], None]
SavedCallback = Callable[[int], None]

_MSG_CAMERA_FAIL = (
    "Sorry, I couldn't access the camera right now. Please try again later."
)
_MSG_EMPTY_FRIDGE = (
    "The fridge looks empty (or I couldn't make out any food items). "
    "Time to go grocery shopping!"
)
_MSG_OLLAMA_DOWN = (
    "The AI models appear to be unavailable right now. "
    "Please check that Ollama is running and try again."
)


def format_ingredients(ingredients: list[str]) -> str:
    if ingredients:
        return "Ingredients found:\n" + "\n".join(f"• {i}" for i in ingredients)
    return "No ingredients detected."


def merge_pantry(detected: list[str], pantry: list[str]) -> list[str]:
    """Union detected ingredients with pantry staples, case-insensitively.

    Detected items come first (and win on casing); duplicates are dropped.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for item in [*detected, *pantry]:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def pantry_command(args: list[str]) -> str:
    """Handle '/pantry [list | add <item> | remove <item>]' for any front-end."""
    if not args or args[0].lower() == "list":
        items = memory.list_pantry_items()
        if not items:
            return "Your pantry is empty. Add a staple with: /pantry add <item>"
        return "Pantry staples:\n" + "\n".join(f"• {i}" for i in items)

    action = args[0].lower()
    item = " ".join(args[1:]).strip()
    if action == "add":
        if not item:
            return "Usage: /pantry add <item>"
        added = memory.add_pantry_item(item)
        verb = "Added" if added else "Already have"
        return f"{verb} '{item.lower()}' in the pantry."
    if action == "remove":
        if not item:
            return "Usage: /pantry remove <item>"
        removed = memory.remove_pantry_item(item)
        return (
            f"Removed '{item.lower()}' from the pantry."
            if removed
            else f"'{item.lower()}' isn't in the pantry."
        )
    return "Usage: /pantry [list | add <item> | remove <item>]"


def diet_command(args: list[str]) -> str:
    """Handle '/diet [<preference> | clear]' — the standing dietary constraint."""
    if not args:
        current = memory.get_setting(_DIET_KEY)
        if current:
            return f"Current dietary preference: {current}"
        return "No dietary preference set. Set one with: /diet <e.g. vegetarian, no nuts>"

    if len(args) == 1 and args[0].lower() == "clear":
        memory.delete_setting(_DIET_KEY)
        return "Dietary preference cleared."

    value = " ".join(args).strip()
    memory.set_setting(_DIET_KEY, value)
    return f"Dietary preference set to: {value}"


def format_ingredient_stats(top_n: int = 10) -> str:
    """Rank the most frequently detected ingredients across recipe history."""
    freq = memory.query_ingredients_frequency()
    if not freq:
        return "No recipes recorded yet — nothing to summarize."
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    lines = [f"• {item} ×{count}" for item, count in ranked]
    return "Most-used ingredients:\n" + "\n".join(lines)


def get_last_recipe_text() -> str:
    result = memory.get_last_recipe()
    if result is None:
        return "No recipes in history yet."
    recipe_id, text = result
    return f"[Recipe #{recipe_id}]\n\n{text}"


def _recipe_title(text: str) -> str:
    lines = text.splitlines()
    return lines[0] if lines else text[:60]


def format_history(n: int = 5) -> str:
    rows = memory.get_recipe_history(n)
    if not rows:
        return "No recipes in history yet."
    lines = []
    for recipe_id, text, rating in rows:
        stars = f" — {rating}⭐" if rating else ""
        lines.append(f"#{recipe_id}: {_recipe_title(text)}{stars}")
    return "Recent recipes:\n" + "\n".join(lines)


def format_recipe(recipe_id: int) -> str:
    row = memory.get_recipe_by_id(recipe_id)
    if row is None:
        return f"No recipe found with id #{recipe_id}."
    rid, text, rating = row
    header = f"[Recipe #{rid}]"
    if rating:
        header += f" — rated {rating}⭐"
    return f"{header}\n\n{text}"


def format_feedback_saved(recipe_id: int, rating: int) -> str:
    return f"Saved rating {rating} for recipe #{recipe_id}."


def run(
    image_bytes: bytes | None = None,
    vision_stream_callback: StreamCallback | None = None,
    chef_stream_callback: StreamCallback | None = None,
    on_ingredients: IngredientsCallback | None = None,
    on_saved: SavedCallback | None = None,
) -> str:
    """Run the full pipeline and return a recipe string.

    If image_bytes is None, attempts to capture from the hardware camera.
    Pass pre-loaded bytes (e.g., from a fixture file) to bypass the camera —
    this is how the debug CLI and tests exercise the pipeline on a Mac.
    """
    # ── Step 1: acquire image ─────────────────────────────────────────────────
    if image_bytes is None:
        from remy import camera  # noqa: PLC0415
        try:
            image_bytes = camera.capture()
        except CameraUnavailableError:
            logger.exception("Camera unavailable")
            return _MSG_CAMERA_FAIL

    # ── Step 2: extract ingredients via VLM ───────────────────────────────────
    try:
        ingredients = vision.extract_ingredients(
            image_bytes,
            stream_callback=vision_stream_callback,
        )
    except Exception:
        logger.exception("Vision module failed unexpectedly")
        return _MSG_OLLAMA_DOWN

    if not ingredients:
        return _MSG_EMPTY_FRIDGE

    if on_ingredients is not None:
        on_ingredients(ingredients)

    # ── Step 3: fetch recent + rated recipes and pantry staples for context ───
    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    favorites = memory.get_top_rated_recipes(_FEEDBACK_RECIPES_N)
    dislikes = memory.get_disliked_recipes(_FEEDBACK_RECIPES_N)
    # The camera only sees the fridge; fold in always-on-hand pantry staples.
    available = merge_pantry(ingredients, memory.list_pantry_items())
    constraints = memory.get_setting(_DIET_KEY)

    # ── Step 4: generate recipe ───────────────────────────────────────────────
    try:
        recipe = chef.generate_recipe(
            available,
            recent,
            favorites=favorites,
            dislikes=dislikes,
            constraints=constraints,
            stream_callback=chef_stream_callback,
        )
    except Exception:
        logger.exception("Chef module failed unexpectedly")
        return _MSG_OLLAMA_DOWN

    # ── Step 5: persist (record what the fridge actually held, not staples) ────
    recipe_id = memory.save_recipe(ingredients, recipe, constraints=constraints)
    if on_saved is not None:
        on_saved(recipe_id)

    return recipe


def run_chef_only(
    ingredients: list[str],
    chef_stream_callback: StreamCallback | None = None,
    on_saved: SavedCallback | None = None,
) -> str:
    """Generate and persist a recipe from a known ingredient list (no VLM)."""
    if not ingredients:
        return _MSG_EMPTY_FRIDGE

    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    favorites = memory.get_top_rated_recipes(_FEEDBACK_RECIPES_N)
    dislikes = memory.get_disliked_recipes(_FEEDBACK_RECIPES_N)
    constraints = memory.get_setting(_DIET_KEY)
    try:
        recipe = chef.generate_recipe(
            ingredients,
            recent,
            favorites=favorites,
            dislikes=dislikes,
            constraints=constraints,
            stream_callback=chef_stream_callback,
        )
    except Exception:
        logger.exception("Chef module failed unexpectedly")
        return _MSG_OLLAMA_DOWN

    recipe_id = memory.save_recipe(ingredients, recipe, constraints=constraints)
    if on_saved is not None:
        on_saved(recipe_id)

    return recipe


def scan(
    image_bytes: bytes | None = None,
    vision_stream_callback: StreamCallback | None = None,
) -> list[str]:
    """Run only the VLM step and return the ingredient list.

    Used by /scan command (debug or Telegram) to inspect VLM output without
    generating a recipe.
    """
    if image_bytes is None:
        from remy import camera  # noqa: PLC0415
        try:
            image_bytes = camera.capture()
        except CameraUnavailableError:
            logger.exception("Camera unavailable during scan")
            return []

    try:
        return vision.extract_ingredients(
            image_bytes,
            stream_callback=vision_stream_callback,
        )
    except Exception:
        logger.exception("Vision module failed during scan")
        return []
