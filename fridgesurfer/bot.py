"""Telegram bot layer.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_ID to be set.
Not needed for local testing — use debug_cli.py instead.
"""
import logging
from datetime import time
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    JobQueue,
)

from fridgesurfer import config, memory, orchestrator, vision

logger = logging.getLogger(__name__)
_TEST_IMAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "ingredients_chicken_caprese.png"
)
_HELP_TEXT = """Fridge Surfer commands:

/help - Show this command list.
/recipe - Scan the fridge camera and generate a recipe.
/test - Run the full pipeline with a bundled fixture image.
/scan - Scan the fridge camera and list detected ingredients.
/last - Show the most recent saved recipe.
/feedback <recipe_id> <rating 1-5> - Rate a saved recipe."""


def _is_allowed(update: Update) -> bool:
    tg = config.get_telegram_config()
    return update.effective_chat is not None and update.effective_chat.id == tg["allowed_chat_id"]


async def _send(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    await context.bot.send_message(chat_id=chat_id, text=text)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text("Scanning the fridge and generating a recipe, please wait...")
    recipe = orchestrator.run()
    await update.message.reply_text(recipe)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(_HELP_TEXT)


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    if not _TEST_IMAGE_PATH.exists():
        await update.message.reply_text(f"Test fixture not found: {_TEST_IMAGE_PATH}")
        return
    await update.message.reply_text(
        f"Running full pipeline with test fixture: {_TEST_IMAGE_PATH.name}"
    )
    try:
        image_bytes = _TEST_IMAGE_PATH.read_bytes()
    except OSError:
        logger.exception("Failed to read test fixture: %s", _TEST_IMAGE_PATH)
        await update.message.reply_text("Sorry, I couldn't read the test fixture.")
        return
    recipe = orchestrator.run(image_bytes=image_bytes)
    await update.message.reply_text(recipe)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text("Running vision scan only...")
    ingredients = orchestrator.scan()
    if ingredients:
        await update.message.reply_text("Ingredients found:\n" + "\n".join(f"• {i}" for i in ingredients))
    else:
        await update.message.reply_text("No ingredients detected.")


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    result = memory.get_last_recipe()
    if result is None:
        await update.message.reply_text("No recipes in history yet.")
    else:
        recipe_id, text = result
        await update.message.reply_text(f"[Recipe #{recipe_id}]\n\n{text}")


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
    await update.message.reply_text(f"Saved rating {rating} for recipe #{recipe_id}.")


# ── Scheduled job ─────────────────────────────────────────────────────────────

async def _scheduled_recipe(context: ContextTypes.DEFAULT_TYPE) -> None:
    tg = config.get_telegram_config()
    chat_id = tg["allowed_chat_id"]
    logger.info("Running scheduled recipe pipeline")
    recipe = orchestrator.run()
    await _send(context, chat_id, recipe)


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
    app.add_handler(CommandHandler("feedback", cmd_feedback))

    # Schedule daily recipe
    hour, minute = (int(x) for x in tg["scheduled_scan_time"].split(":"))
    app.job_queue.run_daily(
        _scheduled_recipe,
        time=time(hour=hour, minute=minute),
    )

    async def on_startup(app: Application) -> None:
        await app.bot.send_message(
            chat_id=tg["allowed_chat_id"],
            text="Fridge Surfer is online. Send /help for available commands.",
        )

    app.post_init = on_startup

    logger.info("Starting bot (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
