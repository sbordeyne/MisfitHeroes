"""Sort processed card art into assets/cards/ by layout.

Each assets/processed/<name>/ directory (written by prepare_images.py)
holds one <name>.png plus a results.json carrying that card's batch entry,
including its "layout" ("foreground" or "background"). This moves the PNG
into assets/cards/foregrounds/ or assets/cards/backgrounds/ accordingly,
keeping the same filename. results.json is left in place.

Usage:
    python src/sort_processed_cards.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "assets" / "processed"
CARDS_DIR = PROJECT_ROOT / "assets" / "cards"

LAYOUT_DEST = {
    "foreground": CARDS_DIR / "foregrounds",
    "hero": CARDS_DIR / "foregrounds",  # older extraction runs called this layout "hero"
    "background": CARDS_DIR / "backgrounds",
}


def sort_processed_cards() -> None:
    for card_dir in sorted(p for p in PROCESSED_DIR.iterdir() if p.is_dir()):
        results_json = card_dir / "results.json"
        if not results_json.exists():
            print(f"SKIP {card_dir.name}: no results.json")
            continue

        entry = json.loads(results_json.read_text(encoding="utf-8"))
        layout = entry.get("layout")
        dest_dir = LAYOUT_DEST.get(layout)
        if dest_dir is None:
            print(f"SKIP {card_dir.name}: unknown layout {layout!r}")
            continue

        png_path = PROJECT_ROOT / entry["artwork_path"]
        if not png_path.exists():
            print(f"SKIP {card_dir.name}: {png_path} not found")
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / png_path.name
        shutil.move(str(png_path), str(dest_path))
        print(f"{png_path.relative_to(PROJECT_ROOT)} -> {dest_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    sort_processed_cards()
