"""Debug CLI — interactive REPL that replaces the Telegram bot for local testing.

Usage:
    python -m remy.debug_cli

Commands inside the REPL:
    /recipe <PATH>            Full pipeline (VLM → chef → memory)
    /scan <PATH>              VLM only — returns ingredient list
    /ingredients "a, b, c"   Chef only — bypasses VLM (fastest for chef testing)
    /pantry [add|remove] X    List/edit always-on-hand staples merged into recipes
    /diet [<text>|clear]      Show/set/clear the standing dietary preference
    /stats                    Most frequently detected ingredients
    /last                     Show last recipe from memory
    /history                  List recent recipes with ids
    /show <id>                Show a specific saved recipe
    /feedback <id> <rating>   Rate a recipe (1-5)
    /help                     Show this help
    /quit                     Exit

/recipe and /scan require an image path. /ingredients, /last, and /feedback
work without one. Model calls stream raw Ollama output so you can inspect
thinking/content chunks and timing while testing.
"""
import argparse
import logging
from pathlib import Path

from remy import config, memory, orchestrator

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


def _print_ingredients(ingredients: list[str]) -> None:
    print("Ingredients detected:")
    for item in ingredients:
        print(f"  • {item}")
    print()


def _cmd_recipe(args: list[str]) -> None:
    if not args:
        print("[error] /recipe requires an image path, e.g.: /recipe path/to/fridge.jpg")
        return
    image_bytes = _load_image(args[0])
    if not image_bytes:
        return
    print("[*] Running full pipeline...")
    vlm_stream = _OllamaStreamPrinter("VLM")
    chef_stream = _OllamaStreamPrinter("Chef")
    saved_id: list[int] = []
    vlm_finished = False

    def _on_ingredients(ingredients: list[str]) -> None:
        nonlocal vlm_finished
        vlm_stream.finish()
        vlm_finished = True
        _print_ingredients(ingredients)
        recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
        print(
            f"[*] Calling chef with {len(ingredients)} ingredient(s), "
            f"{len(recent)} recent recipe(s)..."
        )
        chef_stream.begin()

    def _on_saved(recipe_id: int) -> None:
        saved_id.append(recipe_id)

    vlm_stream.begin()
    recipe = orchestrator.run(
        image_bytes=image_bytes,
        vision_stream_callback=vlm_stream,
        chef_stream_callback=chef_stream,
        on_ingredients=_on_ingredients,
        on_saved=_on_saved,
    )
    if not vlm_finished:
        vlm_stream.finish()
    if chef_stream.saw_any or saved_id:
        chef_stream.finish()

    if not saved_id:
        print(recipe + "\n")
        return

    if not chef_stream.saw_response:
        print("\n" + recipe + "\n")
    print(f"Saved recipe #{saved_id[0]}.\n")


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


def _parse_ingredient_args(args: list[str]) -> list[str]:
    """Parse a free-form ingredient list, tolerating the quotes the help shows.

    e.g. ['"milk,', 'eggs"'] (from `/ingredients "milk, eggs"`) -> ['milk', 'eggs'].
    """
    raw = " ".join(args).strip().strip("\"'")
    items = [piece for piece in (p.strip().strip("\"'") for p in raw.split(",")) if piece]
    if not items:
        items = raw.split()
    return items


def _cmd_ingredients(args: list[str]) -> None:
    if not args:
        print("[error] Provide an ingredient list, e.g.: /ingredients \"milk, eggs, cheese\"")
        return
    items = _parse_ingredient_args(args)

    recent = memory.get_recent_recipes(config.RECENT_RECIPES_N)
    print(f"[*] Calling chef with {len(items)} ingredient(s), {len(recent)} recent recipe(s)...")
    chef_stream = _OllamaStreamPrinter("Chef")
    saved_id: list[int] = []
    chef_stream.begin()
    recipe = orchestrator.run_chef_only(
        items,
        chef_stream_callback=chef_stream,
        on_saved=saved_id.append,
    )
    chef_stream.finish()

    if not saved_id:
        print(recipe + "\n")
        return

    if not chef_stream.saw_response:
        print("\n" + recipe + "\n")
    print(f"Saved recipe #{saved_id[0]}.\n")


def _cmd_pantry(args: list[str]) -> None:
    print(orchestrator.pantry_command(args) + "\n")


def _cmd_diet(args: list[str]) -> None:
    print(orchestrator.diet_command(args) + "\n")


def _cmd_stats(_args: list[str]) -> None:
    print(orchestrator.format_ingredient_stats() + "\n")


def _cmd_last(_args: list[str]) -> None:
    print(orchestrator.get_last_recipe_text() + "\n")


def _cmd_history(_args: list[str]) -> None:
    print(orchestrator.format_history() + "\n")


def _cmd_show(args: list[str]) -> None:
    if len(args) != 1 or not args[0].isdigit():
        print("[error] Usage: /show <recipe_id>")
        return
    print(orchestrator.format_recipe(int(args[0])) + "\n")


def _cmd_feedback(args: list[str]) -> None:
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        print("[error] Usage: /feedback <recipe_id> <rating 1-5>")
        return
    recipe_id, rating = int(args[0]), int(args[1])
    if rating not in range(1, 6):
        print("[error] Rating must be between 1 and 5.")
        return
    memory.rate_recipe(recipe_id, rating)
    print(orchestrator.format_feedback_saved(recipe_id, rating) + "\n")


def _print_help(_args: list[str] | None = None) -> None:
    print(__doc__)


_COMMANDS = {
    "/recipe": _cmd_recipe,
    "/scan": _cmd_scan,
    "/ingredients": _cmd_ingredients,
    "/pantry": _cmd_pantry,
    "/diet": _cmd_diet,
    "/stats": _cmd_stats,
    "/last": _cmd_last,
    "/history": _cmd_history,
    "/show": _cmd_show,
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
