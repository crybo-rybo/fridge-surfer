# Fridge Surfer 🧲

A tiny AI that lives near my fridge, stares at its contents, and tells me what to make for dinner.

---

## The Idea

I keep opening the fridge, staring blankly, and closing it again. Classic.

Fridge Surfer is my attempt to outsource that problem to a local AI setup running on a **Jetson Orin Nano Super** tucked somewhere near the refrigerator. The idea is simple: it takes a photo of the fridge interior, figures out what's in there, and generates a dinner recipe using only what it sees. Then it texts me the recipe via Telegram like a little chef living in my kitchen wall.

No cloud APIs. No subscriptions. No sending photos of my sad leftovers to some server farm. Everything runs locally.

## How It Works

The pipeline is pretty straightforward:

```
📸 Camera → 🔍 VLM (vision model) → 🍳 Chef LLM → 💬 Telegram
```

1. A camera captures a still of the fridge interior.
2. A vision-language model (VLM) looks at the image and produces a list of ingredients it can identify.
3. A chat LLM plays the role of a practical home chef and generates a dinner recipe using those ingredients, deliberately avoiding whatever it suggested recently.
4. The recipe lands in my Telegram DMs.

There's also a SQLite memory layer that keeps track of past recipes so it doesn't suggest the same broccoli stir-fry three nights in a row.

Both models run locally via **Ollama** — which means the whole thing works even if my internet goes out, and my fridge contents stay private.

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
/scan                         → run only the VLM, see what it finds
/ingredients "milk, eggs"     → test the chef directly, no VLM needed
/recipe                       → full pipeline end-to-end
/last                         → see the most recent recipe from memory
/feedback 1 5                 → rate recipe #1 with 5 stars
```

## Status

This is a hobby project in active development. Currently standing up the core pipeline and testing model interactions before putting anything inside an actual fridge.

v1 goal: camera fires → recipe lands in Telegram → I make dinner. That's it.
