"""Resize assets/ui/*.png to the pixel size they occupy on a 1000px-wide card.

The UI decal images (cost badge, victory badge, name banner, faction ribbons,
effect boxes) were exported at inconsistent, ad-hoc resolutions with no
shared "native card width" -- src/Card.lua stretches each one at render time
to exactly fill its LAYOUT box, regardless of the source image's own
resolution. This script uses that same LAYOUT table (the authoritative
on-card size for every element) to compute each element's target pixel
footprint at a given card width, then produces a resized copy: the source
image is scaled uniformly (aspect ratio preserved, no distortion) to fit
within the target box and centered on a transparent canvas of exactly that
box size.

Usage:
    python src/rescale_ui_assets.py
    python src/rescale_ui_assets.py --card-width 1000 --output-dir assets/ui_1000
    python src/rescale_ui_assets.py --in-place
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = PROJECT_ROOT / "assets" / "ui"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "assets" / "ui_1000"

# A card is 5:7 (width:height) -- mirrors CARD_ASPECT_W/H in extract_artwork.py
# and Card.lua's own artwork box (5/7). Duplicated here rather than shared,
# matching the project's existing convention (see Card.lua's module docstring
# on why FACTION/BG_EFFECT are duplicated instead of imported).
CARD_ASPECT_W, CARD_ASPECT_H = 5, 7

# Fractional (left, top, right, bottom) layout boxes, copied from the
# relevant subset of src/Card.lua's LAYOUT table -- the ground truth for how
# big each UI element actually is on a rendered card.
LAYOUT = {
    "cost": (0.0, 0.0, 0.22, 0.18),
    "victory": (0.78, 0.0, 1.0, 0.18),
    "faction": (0.0, 0.05, 0.22, 0.65),
    "banner": (0.08, 0.53, 0.92, 0.78),
    "effectBackground": (0.03, 0.76, 1.0, 0.94),
    "effectHero": (0.03, 0.65, 1.0, 0.86),
}

# Which LAYOUT box each assets/ui/ file is placed into.
ASSET_LAYOUT_KEY = {
    "ui_cost.png": "cost",
    "ui_victory.png": "victory",
    "ui_banner.png": "banner",
    "ui_faction_blue.png": "faction",
    "ui_faction_red.png": "faction",
    "ui_faction_purple.png": "faction",
    "ui_effect_hero.png": "effectHero",
    "ui_effect_condition.png": "effectBackground",
    "ui_effect_additional_cost.png": "effectBackground",
    "ui_effect_on_play.png": "effectBackground",
    "ui_effect_victory.png": "effectBackground",
}


def target_size(layout_key: str, card_width: int) -> tuple[int, int]:
    """(width, height) in pixels of `layout_key`'s box on a card of
    `card_width` pixels wide (card height follows the 5:7 aspect ratio)."""
    left, top, right, bottom = LAYOUT[layout_key]
    card_height = card_width * CARD_ASPECT_H / CARD_ASPECT_W
    width = round((right - left) * card_width)
    height = round((bottom - top) * card_height)
    return width, height


def resize_into_box(image: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Uniformly scale `image` (aspect ratio preserved) to fit within
    target_w x target_h, then center it on a transparent canvas of exactly
    that size."""
    src_h, src_w = image.shape[:2]
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))

    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(image, (new_w, new_h), interpolation=interpolation)

    if resized.shape[2] == 3:
        alpha = np.full((new_h, new_w, 1), 255, dtype=resized.dtype)
        resized = np.concatenate([resized, alpha], axis=2)

    canvas = np.zeros((target_h, target_w, 4), dtype=resized.dtype)
    x_off = (target_w - new_w) // 2
    y_off = (target_h - new_h) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=UI_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--card-width", type=int, default=1000)
    parser.add_argument(
        "--in-place", action="store_true",
        help="Overwrite files in --input-dir instead of writing to --output-dir",
    )
    args = parser.parse_args()

    output_dir = args.input_dir if args.in_place else args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(args.input_dir.glob("*.png")):
        layout_key = ASSET_LAYOUT_KEY.get(path.name)
        if layout_key is None:
            print(f"SKIP {path.name}: no LAYOUT mapping known for this file")
            continue

        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            print(f"FAILED {path.name}: could not read image")
            continue

        src_h, src_w = image.shape[:2]
        target_w, target_h = target_size(layout_key, args.card_width)
        result = resize_into_box(image, target_w, target_h)

        out_path = output_dir / path.name
        cv2.imwrite(str(out_path), result)
        scale = min(target_w / src_w, target_h / src_h)
        print(f"{path.name}: {src_w}x{src_h} -> {target_w}x{target_h} (scale={scale:.3f})")

    print(f"\nWrote resized assets to {output_dir}")


if __name__ == "__main__":
    main()
