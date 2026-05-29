"""Debug CLI — interactive REPL that replaces the Telegram bot for local testing.

Usage:
    python -m remy.debug_cli

Commands inside the REPL:
    /recipe <PATH>            Full pipeline (VLM → chef → memory)
    /scan <PATH>              VLM only — returns ingredient list
    /ingredients "a, b, c"   Chef only — bypasses VLM (fastest for chef testing)
    /last                     Show last recipe from memory
    /feedback <id> <rating>   Rate a recipe (1-5)
    /help                     Show this help
    /quit                     Exit

/recipe and /scan require an image path. /ingredients, /last, and /feedback
work without one. Model calls stream raw Ollama output so you can inspect
thinking/content chunks and timing while testing.
"""
import logging
import argparse
from pathlib import Path

from remy import chef, config, memory, orchestrator, vision

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger("remy")


class _OllamaStreamPrinter:
    def __init__(self, label: str) -> None:
        self.label = label
        self.current_kind: str | None = None
        self.saw_any = False
        self.saw_response = False
        self.saw_thinking = False

    def begin(self) -> None:
        print(f"--- {self.label} Ollama stream ---", flush=True)

    def __call__(self, kind: str, text: str) -> None:
        if not text:
            return

        if kind == "stats":
            if self.current_kind is not None:
                print()
                self.current_kind = None
            print(f"[{self.label} stats] {text}", flush=True)
            return

        self.saw_any = True
        if kind == "response":
            self.saw_response = True
        elif kind == "thinking":
            self.saw_thinking = True
        else:
            kind = "raw"

        if self.current_kind != kind:
            if self.current_kind is not None:
                print()
            print(f"[{self.label} {kind}]", flush=True)
            self.current_kind = kind

        print(text, end="", flush=True)

    def finish(self) -> None:
        if self.current_kind is not None:
            print()

        if not self.saw_any:
            print(f"[{self.label}] no streamed response chunks received")
        if not self.saw_thinking:
            print(f"[{self.label}] no thinking chunks received")
        print(f"--- end {self.label} stream ---\n")


def _load_image(path: str) -> bytes:
    target = Path(path)
    if not target.exists():
        print(f"[error] Image not found: {target}")
        return b""
    return target.read_bytes()


def _cmd_recipe(args: list[str]) -> None:
    if not args:
        print("[error] /recipe requires an image path, e.g.: /recipe path/to/fridge.jpg")
        return
    image_bytes = _load_image(args[0])
    if not image_bytes:
        return
    print("[*] Running full pipeline...")
    vlm_stream = _OllamaStreamPrinter("VLM")
    vlm_stream.begin()
    ingredients = vision.extract_ingredients(
        image_bytes,
        stream_callback=vlm_stream,
    )
    vlm_stream.finish()

    if not ingredients:
        print("The fridge looks empty (or the VLM output could not be parsed).\n")
        return

    print("Ingredients detected:")
    for item in ingredients:
        print(f"  • {item}")
    print()

    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    print(f"[*] Calling chef with {len(ingredients)} ingredient(s), {len(recent)} recent recipe(s)...")
    chef_stream = _OllamaStreamPrinter("Chef")
    chef_stream.begin()
    try:
        recipe = chef.generate_recipe(
            ingredients,
            recent,
            stream_callback=chef_stream,
        )
    except Exception as exc:
        chef_stream.finish()
        print(f"[error] Chef failed: {exc}")
        return

    recipe_id = memory.save_recipe(ingredients, recipe)
    chef_stream.finish()
    if not chef_stream.saw_response:
        print("\n" + recipe + "\n")
    print(f"Saved recipe #{recipe_id}.\n")


def _cmd_scan(args: list[str]) -> None:
    if not args:
        print("[error] /scan requires an image path, e.g.: /scan path/to/fridge.jpg")
        return
    image_bytes = _load_image(args[0])
    if not image_bytes:
        return
    print("[*] Running VLM scan...")
    vlm_stream = _OllamaStreamPrinter("VLM")
    vlm_stream.begin()
    ingredients = orchestrator.scan(
        image_bytes=image_bytes,
        vision_stream_callback=vlm_stream,
    )
    vlm_stream.finish()
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
    items = [i.strip() for i in raw.split(",") if i.strip()]
    if not items:
        items = raw.split()

    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    print(f"[*] Calling chef with {len(items)} ingredient(s), {len(recent)} recent recipe(s)...")
    chef_stream = _OllamaStreamPrinter("Chef")
    chef_stream.begin()
    try:
        recipe = chef.generate_recipe(
            items,
            recent,
            stream_callback=chef_stream,
        )
    except Exception as exc:
        chef_stream.finish()
        print(f"[error] Chef failed: {exc}")
        return
    recipe_id = memory.save_recipe(items, recipe)
    chef_stream.finish()
    if not chef_stream.saw_response:
        print("\n" + recipe + "\n")
    print(f"Saved recipe #{recipe_id}.\n")


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


def _print_help(_args: list[str] | None = None) -> None:
    print(__doc__)


_COMMANDS = {
    "/recipe": _cmd_recipe,
    "/scan": _cmd_scan,
    "/ingredients": _cmd_ingredients,
    "/last": _cmd_last,
    "/feedback": _cmd_feedback,
    "/help": _print_help,
}


def run() -> None:
    memory.init_db()

    print("Remy debug CLI")
    print(f"  Vision model : {config.VISION_MODEL}")
    print(f"  Chef model   : {config.CHEF_MODEL}")
    print(f"  Ollama host  : {config.OLLAMA_HOST}")
    print(f"  Keep alive   : {config.OLLAMA_KEEP_ALIVE}")
    print(f"  VLM context  : {config.VISION_NUM_CTX}")
    print(f"  Chef context : {config.CHEF_NUM_CTX}")
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

        _COMMANDS[cmd](args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remy interactive debug CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging (shows raw VLM output and chef prompts)",
    )
    ns = parser.parse_args()

    if ns.debug:
        logging.getLogger("remy").setLevel(logging.DEBUG)

    run()


if __name__ == "__main__":
    main()
