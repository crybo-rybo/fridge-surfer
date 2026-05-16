"""Debug CLI — interactive REPL that replaces the Telegram bot for local testing.

Usage:
    python -m fridgesurfer.debug_cli [--image PATH]

Commands inside the REPL:
    /recipe [PATH]            Full pipeline (VLM → chef → memory)
    /scan [PATH]              VLM only — returns ingredient list
    /ingredients "a, b, c"   Chef only — bypasses VLM (fastest for chef testing)
    /last                     Show last recipe from memory
    /feedback <id> <rating>   Rate a recipe (1-5)
    /help                     Show this help
    /quit                     Exit

PATH is an image file. Defaults to tests/fixtures/fridge_sample.jpg when omitted.
"""
import argparse
import logging
import sys
from pathlib import Path

from fridgesurfer import chef, config, memory, orchestrator, vision

DEFAULT_FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "fridge_sample.jpg"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)
# Quieten third-party noise but keep our DEBUG messages available via -v
logger = logging.getLogger("fridgesurfer")


def _load_image(path: str | Path | None) -> bytes:
    target = Path(path) if path else DEFAULT_FIXTURE
    if not target.exists():
        print(f"[error] Image not found: {target}")
        print("  Run `python setup_fixtures.py` to generate the default fixture,")
        print("  or supply a path: /recipe path/to/image.jpg")
        return b""
    return target.read_bytes()


def _cmd_recipe(args: list[str]) -> None:
    image_path = args[0] if args else None
    image_bytes = _load_image(image_path)
    if not image_bytes:
        return
    print("[*] Running full pipeline...")
    result = orchestrator.run(image_bytes=image_bytes)
    print("\n" + result + "\n")


def _cmd_scan(args: list[str]) -> None:
    image_path = args[0] if args else None
    image_bytes = _load_image(image_path)
    if not image_bytes:
        return
    print("[*] Running VLM scan...")
    ingredients = orchestrator.scan(image_bytes=image_bytes)
    if ingredients:
        print("Ingredients detected:")
        for item in ingredients:
            print(f"  • {item}")
    else:
        print("No ingredients detected.")
    print()


def _cmd_ingredients(args: list[str]) -> None:
    if not args:
        print("[error] Provide an ingredient list, e.g.: /ingredients \"milk, eggs, cheese\"")
        return
    raw = " ".join(args)
    # Support both comma-separated and space-separated
    items = [i.strip() for i in raw.split(",") if i.strip()]
    if not items:
        items = raw.split()

    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    print(f"[*] Calling chef with {len(items)} ingredient(s), {len(recent)} recent recipe(s)...")
    try:
        recipe = chef.generate_recipe(items, recent)
    except Exception as exc:
        print(f"[error] Chef failed: {exc}")
        return
    memory.save_recipe(items, recipe)
    print("\n" + recipe + "\n")


def _cmd_last(_args: list[str]) -> None:
    result = memory.get_last_recipe()
    if result is None:
        print("No recipes in history yet.\n")
    else:
        recipe_id, text = result
        print(f"[Recipe #{recipe_id}]\n\n{text}\n")


def _cmd_feedback(args: list[str]) -> None:
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        print("[error] Usage: /feedback <recipe_id> <rating 1-5>")
        return
    recipe_id, rating = int(args[0]), int(args[1])
    if rating not in range(1, 6):
        print("[error] Rating must be between 1 and 5.")
        return
    memory.rate_recipe(recipe_id, rating)
    print(f"Saved rating {rating} for recipe #{recipe_id}.\n")


def _print_help() -> None:
    print(__doc__)


_COMMANDS = {
    "/recipe": _cmd_recipe,
    "/scan": _cmd_scan,
    "/ingredients": _cmd_ingredients,
    "/last": _cmd_last,
    "/feedback": _cmd_feedback,
    "/help": lambda _: _print_help(),
}


def run(default_image: str | None = None) -> None:
    memory.init_db()

    print("Fridge Surfer debug CLI")
    print(f"  Vision model : {config.VISION_MODEL}")
    print(f"  Chef model   : {config.CHEF_MODEL}")
    print(f"  Ollama host  : {config.OLLAMA_HOST}")
    print(f"  Default image: {default_image or DEFAULT_FIXTURE}")
    print("Type /help for available commands.\n")

    while True:
        try:
            line = input("fridge> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not line:
            continue

        if line in ("/quit", "/exit", "quit", "exit"):
            print("Bye.")
            break

        parts = line.split()
        cmd, args = parts[0], parts[1:]

        if cmd not in _COMMANDS:
            print(f"Unknown command: {cmd!r}. Type /help for options.\n")
            continue

        # If a default image was passed at CLI startup, use it when no per-command path is given.
        if cmd in ("/recipe", "/scan") and not args and default_image:
            args = [default_image]

        _COMMANDS[cmd](args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fridge Surfer interactive debug CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--image",
        metavar="PATH",
        help="Default image to use when no path is supplied to /recipe or /scan",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging (shows raw VLM output and chef prompts)",
    )
    ns = parser.parse_args()

    if ns.debug:
        logging.getLogger("fridgesurfer").setLevel(logging.DEBUG)

    run(default_image=ns.image)


if __name__ == "__main__":
    main()
