"""Generate a synthetic fridge fixture image for local testing.

Run once:
    python setup_fixtures.py

Produces tests/fixtures/fridge_sample.jpg — a 640x480 JPEG with colored
rectangles and text labels for common fridge items. Moondream and similar VLMs
can read text embedded in images, so this gives the vision module something
real to work with.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_PATH = Path("tests/fixtures/fridge_sample.jpg")

ITEMS = [
    ("Milk", (220, 240, 255)),
    ("Eggs", (255, 240, 200)),
    ("Broccoli", (100, 200, 100)),
    ("Cheddar Cheese", (255, 210, 80)),
    ("Leftover Rice", (245, 245, 230)),
    ("Greek Yogurt", (240, 240, 245)),
]

COLS, ROWS = 3, 2
W, H = 640, 480
CELL_W, CELL_H = W // COLS, H // ROWS
PAD = 10


def make_fixture() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (W, H), color=(180, 200, 210))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except (IOError, OSError):
        font = ImageFont.load_default()

    for idx, (label, color) in enumerate(ITEMS):
        col = idx % COLS
        row = idx // COLS
        x0 = col * CELL_W + PAD
        y0 = row * CELL_H + PAD
        x1 = x0 + CELL_W - PAD * 2
        y1 = y0 + CELL_H - PAD * 2

        draw.rectangle([x0, y0, x1, y1], fill=color, outline=(80, 80, 80), width=2)
        # Center the label
        bbox = draw.textbbox((0, 0), label, font=font)
        tx = x0 + (CELL_W - PAD * 2 - (bbox[2] - bbox[0])) // 2
        ty = y0 + (CELL_H - PAD * 2 - (bbox[3] - bbox[1])) // 2
        draw.text((tx, ty), label, fill=(20, 20, 20), font=font)

    img.save(OUT_PATH, "JPEG", quality=90)
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    make_fixture()
