"""Prepare raw card-scan photos for downstream use.

For every entry in assets/raw/batch.json: load its "source" scan, resize it
to exactly PREPARED_WIDTH px wide (aspect ratio preserved), crop the result
to a PREPARED_WIDTH x PREPARED_WIDTH square anchored at the top-left corner,
and write it out under the path given in that entry's "artwork_path" -- the
standardized filename the rest of the pipeline expects. The batch entry
itself is also written out as results.json alongside the image, so each
output directory carries its own source-of-truth metadata.

Usage:
    python src/prepare_images.py
    python src/prepare_images.py --batch-json assets/raw/batch1.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BATCH_JSON = PROJECT_ROOT / "assets" / "raw" / "batch.json"

PREPARED_WIDTH = 1000


def resize_and_crop_square(image, size: int):
    """Resize `image` to `size` px wide (aspect preserved), then crop the
    height down to `size` px anchored at the top-left corner. Assumes the
    source is at least as tall as it is wide (true for these portrait card
    scans) -- a shorter source is top-left anchored on a padded canvas
    instead of cropped so the output is still exactly size x size."""
    h, w = image.shape[:2]
    new_h = round(h * size / w)
    interpolation = cv2.INTER_AREA if size < w else cv2.INTER_CUBIC
    resized = cv2.resize(image, (size, new_h), interpolation=interpolation)

    if new_h >= size:
        return resized[0:size, :]

    canvas = resized[0:0].copy()
    canvas.resize((size, size, image.shape[2]), refcheck=False)
    canvas[0:new_h, :] = resized
    return canvas


def prepare_images(batch_json: Path) -> None:
    entries = json.loads(batch_json.read_text(encoding="utf-8"))

    for entry in entries:
        source = PROJECT_ROOT / entry["source"]
        dest = PROJECT_ROOT / entry["artwork_path"]

        image = cv2.imread(str(source))
        if image is None:
            print(f"SKIP {source}: could not read image")
            continue

        result = resize_and_crop_square(image, PREPARED_WIDTH)

        dest.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dest), result)

        results_json = dest.parent / "results.json"
        results_json.write_text(json.dumps(entry, indent=4, ensure_ascii=False), encoding="utf-8")

        print(f"{source.name} -> {entry['artwork_path']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-json", type=Path, default=DEFAULT_BATCH_JSON)
    args = parser.parse_args()

    prepare_images(args.batch_json)


if __name__ == "__main__":
    main()
