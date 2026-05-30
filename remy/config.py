import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        sys.exit(f"[config] Missing required environment variable: {name}")
    return val


def _optional_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        sys.exit(f"[config] {name} must be an integer, got: {val!r}")


def _require_for_telegram(name: str) -> str:
    """Returns the value or raises — only called from bot.py, not debug_cli.py."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing Telegram environment variable: {name}")
    return val


OLLAMA_HOST = _require("OLLAMA_HOST")
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
VISION_NUM_CTX = _optional_int("VISION_NUM_CTX", 2048)
CHEF_NUM_CTX = _optional_int("CHEF_NUM_CTX", 2048)
# Number of VLM passes per scan; results are unioned to catch items a single
# pass misses (occluded items, model sampling variance). 1 = original behavior.
VISION_PASSES = _optional_int("VISION_PASSES", 1)
VISION_MODEL = _require("VISION_MODEL")
CHEF_MODEL = _require("CHEF_MODEL")
DB_PATH = _require("DB_PATH")
RECENT_RECIPES_N = int(_require("RECENT_RECIPES_N"))

# Resolved lazily by bot.py so the debug CLI never trips on these.
def get_telegram_config() -> dict:
    return {
        "bot_token": _require_for_telegram("TELEGRAM_BOT_TOKEN"),
        "allowed_chat_id": int(_require_for_telegram("TELEGRAM_ALLOWED_CHAT_ID")),
        "scheduled_scan_time": _require_for_telegram("SCHEDULED_SCAN_TIME"),
    }


CAMERA_INDEX: str | int = os.getenv("CAMERA_INDEX", "0")
try:
    CAMERA_INDEX = int(CAMERA_INDEX)
except ValueError:
    pass  # GStreamer pipeline string — keep as-is


# ── Prompt registry ───────────────────────────────────────────────────────────
# Each VLM has its own preferred framing. The rest of the codebase only reads
# VISION_PROMPTS[model_name]; add a new entry here to support a new model.
VISION_PROMPTS: dict[str, str] = {
    "moondream": "List all the food items you can see as a JSON array of strings. Only output the JSON array, nothing else.",
    "llava-phi3": "What food items do you see? Respond ONLY with a JSON array of strings, no other text.",
    "qwen2-vl": "Return a JSON array of all visible food items. Output only the JSON array.",
    "qwen3-vl:2b": "Return a JSON array of all visible food items. Output only the JSON array.",
}

CHEF_SYSTEM_PROMPT = (
    "You are a helpful home chef. When given a list of available ingredients, "
    "suggest one complete dinner recipe that uses primarily those ingredients. "
    "Format your response with a recipe title, a brief ingredient list, and "
    "numbered steps. Keep it practical and concise. Assume you always have "
    "access to a standard selection of herbs and spices."
)
