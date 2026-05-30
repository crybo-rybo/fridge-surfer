"""Telegram bot layer.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID to be set.
Not needed for local testing — use debug_cli.py instead.
"""
import asyncio
import logging
from datetime import time
from pathlib import Path
from typing import Literal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from remy import config, memory, orchestrator

logger = logging.getLogger(__name__)
_THIRD_PARTY_LOGGERS = (
    "apscheduler",
    "httpx",
    "telegram",
)
_TEST_IMAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "images"
    / "ingredients_chicken_caprese.png"
)
_HELP_TEXT = """Remy commands:

/help - Show this command list.
/recipe - Scan the fridge camera and generate a recipe.
/test - Run the full pipeline with a bundled test image.
/scan - Scan the fridge camera and list detected ingredients.
/last - Show the most recent saved recipe.
/history - List recent recipes with their ids.
/show <recipe_id> - Show a specific saved recipe.
/feedback <recipe_id> <rating 1-5> - Rate a saved recipe.
/pantry - List staples. /pantry add <item> or /pantry remove <item> to edit.
/diet - Show the dietary preference. /diet <text> to set, /diet clear to unset.
/stats - Show the most frequently detected ingredients.

Tip: tap the ⭐ buttons under a recipe to rate it, or 🔁 for another idea.

Send a photo captioned /recipe to generate a recipe from that image.
Send a photo captioned /scan to list detected ingredients only.
/recipe and /scan (without a photo) still use the fridge camera."""

_RATING_PREFIX = "rate"
_REGEN_PREFIX = "regen"


def _recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """1–5 star rating buttons plus a 'regenerate from the same ingredients' button."""
    stars = [
        InlineKeyboardButton(
            f"{n}⭐", callback_data=f"{_RATING_PREFIX}:{recipe_id}:{n}"
        )
        for n in range(1, 6)
    ]
    another = [
        InlineKeyboardButton(
            "🔁 Another", callback_data=f"{_REGEN_PREFIX}:{recipe_id}"
        )
    ]
    return InlineKeyboardMarkup([stars, another])


def _parse_rating_callback(data: str) -> tuple[int, int] | None:
    """Parse 'rate:<id>:<rating>' callback data into (recipe_id, rating).

    Returns None for anything that isn't a well-formed rating in 1–5.
    """
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != _RATING_PREFIX:
        return None
    if not parts[1].isdigit() or not parts[2].isdigit():
        return None
    rating = int(parts[2])
    if rating not in range(1, 6):
        return None
    return int(parts[1]), rating


def _parse_regen_callback(data: str) -> int | None:
    """Parse 'regen:<id>' callback data into a recipe id, or None."""
    parts = (data or "").split(":")
    if len(parts) != 2 or parts[0] != _REGEN_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1])


def _is_allowed(update: Update) -> bool:
    tg = config.get_telegram_config()
    return update.effective_chat is not None and update.effective_chat.id == tg["allowed_chat_id"]


PhotoMode = Literal["recipe", "scan"]


def _photo_mode_from_caption(caption: str) -> PhotoMode | None:
    normalized = caption.strip().lower()
    if normalized in ("/recipe", "recipe"):
        return "recipe"
    if normalized in ("/scan", "scan"):
        return "scan"
    return None


async def _download_image_bytes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bytes | None:
    message = update.message
    if message is None:
        return None

    file_id: str | None = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif (
        message.document is not None
        and message.document.mime_type is not None
        and message.document.mime_type.startswith("image/")
    ):
        file_id = message.document.file_id

    if file_id is None:
        return None

    try:
        tg_file = await context.bot.get_file(file_id)
        return bytes(await tg_file.download_as_bytearray())
    except Exception:
        logger.exception("Failed to download Telegram image")
        return None


# ── Command handlers ──────────────────────────────────────────────────────────

async def _run_recipe_and_reply(update: Update, image_bytes: bytes | None = None) -> None:
    """Run the full pipeline and reply with the recipe + rating buttons.

    The orchestrator persists the recipe and reports its id through on_saved;
    we capture that to attach a star keyboard. If nothing was saved (a camera
    or model failure returned a fallback string), reply without buttons.
    """
    saved_id: list[int] = []
    recipe = await asyncio.to_thread(
        orchestrator.run, image_bytes=image_bytes, on_saved=saved_id.append
    )
    reply_markup = _recipe_keyboard(saved_id[0]) if saved_id else None
    await update.message.reply_text(recipe, reply_markup=reply_markup)


async def cmd_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text("Scanning the fridge and generating a recipe, please wait...")
    await _run_recipe_and_reply(update)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(_HELP_TEXT)


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    if not _TEST_IMAGE_PATH.exists():
        await update.message.reply_text(f"Test image not found: {_TEST_IMAGE_PATH}")
        return
    await update.message.reply_text(
        f"Running full pipeline with test image: {_TEST_IMAGE_PATH.name}"
    )
    try:
        image_bytes = _TEST_IMAGE_PATH.read_bytes()
    except OSError:
        logger.exception("Failed to read test image: %s", _TEST_IMAGE_PATH)
        await update.message.reply_text("Sorry, I couldn't read the test image.")
        return
    await _run_recipe_and_reply(update, image_bytes=image_bytes)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text("Running vision scan only...")
    ingredients = await asyncio.to_thread(orchestrator.scan)
    await update.message.reply_text(orchestrator.format_ingredients(ingredients))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    caption = update.message.caption or ""
    if not caption.strip():
        return

    mode = _photo_mode_from_caption(caption)
    if mode is None:
        await update.message.reply_text("Caption your photo with /recipe or /scan.")
        return

    image_bytes = await _download_image_bytes(update, context)
    if image_bytes is None:
        await update.message.reply_text("Sorry, I couldn't download that image.")
        return

    await update.message.reply_text("Processing your photo...")
    if mode == "recipe":
        await _run_recipe_and_reply(update, image_bytes=image_bytes)
    else:
        ingredients = await asyncio.to_thread(orchestrator.scan, image_bytes=image_bytes)
        await update.message.reply_text(orchestrator.format_ingredients(ingredients))


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(orchestrator.get_last_recipe_text())


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(orchestrator.format_history())


async def cmd_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /show <recipe_id>")
        return
    await update.message.reply_text(orchestrator.format_recipe(int(args[0])))


async def cmd_pantry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(orchestrator.pantry_command(context.args or []))


async def cmd_diet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(orchestrator.diet_command(context.args or []))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(orchestrator.format_ingredient_stats())


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    args = context.args or []
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("Usage: /feedback <recipe_id> <rating 1-5>")
        return
    recipe_id, rating = int(args[0]), int(args[1])
    if rating not in range(1, 6):
        await update.message.reply_text("Rating must be between 1 and 5.")
        return
    memory.rate_recipe(recipe_id, rating)
    await update.message.reply_text(orchestrator.format_feedback_saved(recipe_id, rating))


async def on_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the inline ⭐ buttons attached to a recipe."""
    query = update.callback_query
    if query is None:
        return
    if not _is_allowed(update):
        await query.answer()
        return

    parsed = _parse_rating_callback(query.data or "")
    if parsed is None:
        await query.answer("Sorry, I couldn't read that rating.")
        return

    recipe_id, rating = parsed
    memory.rate_recipe(recipe_id, rating)
    await query.answer(f"Rated recipe #{recipe_id}: {rating}⭐")
    # Clear the buttons so the same recipe can't be re-rated; keep its text.
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Could not clear recipe keyboard", exc_info=True)


async def on_regen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the '🔁 Another' button: re-cook from the same ingredients."""
    query = update.callback_query
    if query is None:
        return
    if not _is_allowed(update):
        await query.answer()
        return

    recipe_id = _parse_regen_callback(query.data or "")
    if recipe_id is None:
        await query.answer("Sorry, I couldn't read that.")
        return

    ingredients = memory.get_recipe_ingredients(recipe_id)
    if not ingredients:
        await query.answer("I don't have the ingredients for that recipe anymore.")
        return

    await query.answer("Cooking up another idea...")
    saved_id: list[int] = []
    recipe = await asyncio.to_thread(
        orchestrator.run_chef_only, ingredients, on_saved=saved_id.append
    )
    reply_markup = _recipe_keyboard(saved_id[0]) if saved_id else None
    if query.message is not None:
        await context.bot.send_message(
            chat_id=query.message.chat_id, text=recipe, reply_markup=reply_markup
        )


# ── Scheduled job ─────────────────────────────────────────────────────────────

async def _scheduled_recipe(context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = config.get_telegram_config()
    chat_id = tg["allowed_chat_id"]
    logger.info("Running scheduled recipe pipeline")
    saved_id: list[int] = []
    recipe = await asyncio.to_thread(orchestrator.run, on_saved=saved_id.append)
    reply_markup = _recipe_keyboard(saved_id[0]) if saved_id else None
    await context.bot.send_message(chat_id=chat_id, text=recipe, reply_markup=reply_markup)


# ── Bot startup ───────────────────────────────────────────────────────────────

def main() -> None:
    tg = config.get_telegram_config()
    memory.init_db()

    app = Application.builder().token(tg["bot_token"]).build()

    app.add_handler(CommandHandler("recipe", cmd_recipe))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("show", cmd_show))
    app.add_handler(CommandHandler("pantry", cmd_pantry))
    app.add_handler(CommandHandler("diet", cmd_diet))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CallbackQueryHandler(on_rating_callback, pattern=f"^{_RATING_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(on_regen_callback, pattern=f"^{_REGEN_PREFIX}:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    # Schedule daily recipe
    hour, minute = (int(x) for x in tg["scheduled_scan_time"].split(":"))
    app.job_queue.run_daily(
        _scheduled_recipe,
        time=time(hour=hour, minute=minute),
    )

    async def on_startup(app: Application) -> None:
        await app.bot.send_message(
            chat_id=tg["allowed_chat_id"],
            text="Remy is online. Send /help for available commands.",
        )

    app.post_init = on_startup

    logger.info("Starting bot (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for logger_name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    main()
