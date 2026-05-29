import logging
from collections.abc import Callable

from remy import config, memory, vision, chef
from remy.camera import CameraUnavailableError

logger = logging.getLogger(__name__)
StreamCallback = Callable[[str, str], None]

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


def run(
    image_bytes: bytes | None = None,
    vision_stream_callback: StreamCallback | None = None,
    chef_stream_callback: StreamCallback | None = None,
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

    # ── Step 3: fetch recent recipes for context ──────────────────────────────
    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)

    # ── Step 4: generate recipe ───────────────────────────────────────────────
    try:
        recipe = chef.generate_recipe(
            ingredients,
            recent,
            stream_callback=chef_stream_callback,
        )
    except Exception:
        logger.exception("Chef module failed unexpectedly")
        return _MSG_OLLAMA_DOWN

    # ── Step 5: persist ───────────────────────────────────────────────────────
    memory.save_recipe(ingredients, recipe)

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
