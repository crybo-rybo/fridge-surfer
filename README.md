# Fridge Surfer 🧲

A tiny AI that lives near a fridge, stares at its contents, and figures out what to make for dinner.

---

## The Idea

The refrigerator stare is a universal human experience. Door opens, eyes glaze over, door closes. Nothing was accomplished.

Fridge Surfer is a local AI appliance running on a **Jetson Orin Nano Super** tucked somewhere near the refrigerator. It takes a photo of the fridge interior, identifies what's in there, and generates a dinner recipe using only what it sees — delivered via Telegram like a tiny chef that lives in the kitchen wall.

No cloud APIs. No subscriptions. No uploading photos of sad leftovers to a server farm. Everything runs locally.

## How It Works

The pipeline is pretty straightforward:

```
📸 Camera → 🔍 VLM (vision model) → 🍳 Chef LLM → 💬 Telegram
```

1. A camera captures a still of the fridge interior.
2. A vision-language model (VLM) looks at the image and produces a list of ingredients it can identify.
3. A chat LLM plays the role of a practical home chef and generates a dinner recipe using those ingredients, deliberately avoiding whatever it suggested recently.
4. The recipe lands in Telegram.

There's also a SQLite memory layer that keeps track of past recipes so it doesn't suggest the same broccoli stir-fry three nights in a row.

Both models run locally via **Ollama** — which means the whole thing works offline, and the fridge contents stay private.

## The Stack

| Piece | What it does |
|---|---|
| Jetson Orin Nano Super | Runs everything — compute, camera, models |
| Ollama | Local model server (wraps llama.cpp) |
| Moondream2 | The VLM — looks at the fridge photo, names what it sees |
| Phi-3 mini / qwen3 | The chef — turns ingredient lists into recipes |
| python-telegram-bot | Two-way Telegram interaction |
| SQLite | Keeps recipe history |

## Project Structure

```
fridgesurfer/
├── config.py       # env vars + per-model prompt registry
├── vision.py       # VLM wrapper → ingredient list
├── chef.py         # chat LLM wrapper → recipe
├── memory.py       # SQLite (recipes, ratings, history)
├── camera.py       # image capture (Jetson) or fixture loader (dev)
├── orchestrator.py # linear pipeline tying it all together
├── bot.py          # Telegram bot + scheduled daily scan
└── debug_cli.py    # local REPL for testing without Telegram or a camera
```

## Development on a Mac

The intended target is a Jetson, but the whole pipeline (minus the camera and Telegram) can be exercised locally:

```bash
# 1. Install deps
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. Generate a synthetic fridge image for testing
python setup_fixtures.py

# 3. Pull the vision model
ollama pull moondream

# 4. Copy config and fill in model names
cp .env.example .env

# 5. Launch the debug CLI
python -m fridgesurfer.debug_cli
```

Inside the CLI:

```
/scan path/to/fridge.jpg      → run only the VLM, see what it finds
/recipe path/to/fridge.jpg    → full pipeline end-to-end
/ingredients "milk, eggs"     → test the chef directly, no image needed
/last                         → see the most recent recipe from memory
/feedback 1 5                 → rate recipe #1 with 5 stars
```

## Status

Hobby project in active development. Currently standing up the core pipeline and testing model interactions before putting anything inside an actual fridge.

v1 goal: camera fires → recipe lands in Telegram. That's it.
