"""Extract card data out of raw physical-card scans.

The photos in assets/raw/ show a finished physical card: a cost coin
(top-left), art, a name banner, and an effect banner. Background cards
additionally carry a victory-point trophy (top-right) and, unique to them, a
small near-black effect-category icon box on the left edge of the effect
banner (a heart/star/trophy glyph depending on category). Character/wing
artwork on hero cards can be gold-colored too, so a "is there a gold blob in
the corner" check turns out to false-positive constantly; the near-black
icon box does not appear anywhere in hero art and is a far cleaner signal.
Verified against 5 known scans (3 background, 2 hero, one of them a rotated
phone photo): the near-black-pixel fraction in that band was 0.088-0.249 for
every background and 0.035-0.046 for every hero -- a clean gap.

For each scan this:
  1. classifies it as "hero" or "background" via that icon-box signal,
  2. detects the faction tab color (blue=human, red/pink/magenta=monster,
     no tab="none" -- there are only two real factions in the game) and,
     on backgrounds only, the effect-category icon's color (condition/
     additional_cost/on_play/victory_calc -- see EFFECT_CATEGORY_HUES),
  3. builds a standardized ARTWORK_OUTPUT_SIZE-square artwork crop with the
     badges/tab erased to transparent (see build_artwork),
  4. OCRs the cost / victory points / name / effect text out of their
     known regions (French, via Tesseract),
  5. writes everything to a review JSON -- NOT directly into data.json,
     since OCR will misread accented French text and shouldn't silently
     clobber curated data. Check extracted_data.json by hand and merge
     what's correct.

Known limitation: there's no deskew/rotation-correction step. An earlier
attempt at contour-based card detection was tried and scrapped -- on these
photos the largest contour was reliably a piece of interior artwork, not the
card's own edge, which made crops worse, not better. This works well on the
"Scan_*" flatbed batch (already near-full-frame, right-side-up) but a
photo shot at an angle or with clutter in frame (like the handful of plain
-timestamp phone photos) needs to be manually rotated/cropped to the card
first. Fold in a real deskew step here if that becomes worth solving.

Requires the Tesseract OCR binary on PATH with the French (fra) language
pack installed, in addition to `pip install pytesseract opencv-python`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "extracted"
REVIEW_JSON = PROJECT_ROOT / "src" / "extracted_data.json"

OCR_LANG = "fra"

# A card is 5:7 (width:height). Artwork is standardized to a 1000x1000
# square: at 1000px card-width, full card height would be 1400px, so a
# 1000px-tall crop captures the top CARD_ASPECT_W/CARD_ASPECT_H = 5/7 of the
# card -- everything above the effect-text band, landing partway through the
# name banner (roughly half of it ends up in frame; a fixed crop height
# can't land exactly on the banner's edge without per-card tuning).
CARD_ASPECT_W, CARD_ASPECT_H = 5, 7
ARTWORK_OUTPUT_SIZE = 1000
ARTWORK_HEIGHT_FRACTION = CARD_ASPECT_W / CARD_ASPECT_H

# Fractional (left, top, right, bottom) regions, tuned by eye against a
# handful of scans. Both capture batches (flatbed "Scan_*" vs handheld
# phone photos) frame the card slightly differently, so treat these as a
# starting point to refine, not ground truth.
BACKGROUND_REGIONS = {
    "cost": (0.0, 0.0, 0.17, 0.12),
    "victory_points": (0.83, 0.0, 1.0, 0.12),
    "faction_tab": (0.0, 0.15, 0.19, 0.6),
    "effect_category": (0.07, 0.76, 0.20, 0.86),
    "artwork": (0.0, 0.0, 1.0, ARTWORK_HEIGHT_FRACTION),
    "name": (0.12, 0.63, 0.88, 0.76),
    "effect": (0.03, 0.76, 1.0, 0.94),
}

HERO_REGIONS = {
    "cost": (0.0, 0.0, 0.2, 0.16),
    "faction_tab": (0.0, 0.15, 0.19, 0.6),
    "artwork": (0.0, 0.0, 1.0, ARTWORK_HEIGHT_FRACTION),
    "name": (0.1, 0.55, 0.9, 0.63),
    "effect": (0.03, 0.65, 1.0, 0.86),
}

# Fractional band covering the effect-category icon box (the dark square
# itself, wider than EFFECT_GLYPH region below), used for background/hero
# classification. See module docstring for how this was picked and validated.
EFFECT_ICON_BAND = (0.0, 0.76, 0.20, 0.94)
DARK_PIXEL_THRESHOLD = 70  # grayscale value below which a pixel counts as "icon-box dark"
LAYOUT_DARK_FRACTION_CUTOFF = 0.07  # backgrounds measured 0.088-0.249, heroes 0.035-0.046

# Faction is just blue (human) vs red (monster) vs no tab (none). "Red"
# covers the pink/magenta end too -- lighting/print variance made hero tabs
# read more magenta than the flatter red seen on backgrounds in testing,
# but there were only ever two real colors.
FACTION_HSV = {
    "human": [(np.array([85, 60, 60]), np.array([135, 255, 255]))],
    "monster": [
        (np.array([0, 60, 60]), np.array([10, 255, 255])),
        (np.array([140, 60, 60]), np.array([179, 255, 255])),
    ],
}

# Effect-category icon glyph colors, sampled from 3 known cards (heart=red,
# star=gray, trophy=yellow all measured directly; triangle=green is an
# unverified best guess -- no "condition" example was available to check
# against). Hue ranges apply only to the two hue-based categories;
# "additional_cost" (the gray star) is detected by low saturation instead,
# since gray isn't a hue.
EFFECT_CATEGORY_HUES = {
    "on_play": [(0, 10), (170, 179)],  # red heart
    "victory_calc": [(10, 30)],  # yellow/gold trophy
    "condition": [(35, 85)],  # green triangle -- UNVERIFIED, no test image
}
EFFECT_CATEGORY_GRAY_SATURATION = 60  # below this, a bright pixel counts as the gray star


@dataclass
class CardExtraction:
    source: str
    layout: str
    faction_tab: str | None
    effect_category: str | None
    cost: str | None
    victory_points: str | None
    name: str | None
    effect_text: str | None
    artwork_path: str | None


def region_coverage(region_bgr: np.ndarray, hsv_ranges: list[tuple[np.ndarray, np.ndarray]]) -> float:
    if region_bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for low, high in hsv_ranges:
        mask |= cv2.inRange(hsv, low, high)
    return float(np.count_nonzero(mask)) / mask.size


def classify_layout(card_bgr: np.ndarray) -> str:
    """'background' if the effect-category icon box (near-black, left edge
    of the effect banner) is present, 'hero' otherwise. See module
    docstring for why this signal was picked over corner-badge color."""
    h, w = card_bgr.shape[:2]
    left, top, right, bottom = EFFECT_ICON_BAND
    band = card_bgr[int(top * h) : int(bottom * h), int(left * w) : int(right * w)]
    if band.size == 0:
        return "hero"
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    dark_fraction = float((gray < DARK_PIXEL_THRESHOLD).sum()) / gray.size
    return "background" if dark_fraction > LAYOUT_DARK_FRACTION_CUTOFF else "hero"


def detect_faction_tab(card_bgr: np.ndarray, faction_tab_box: tuple[float, float, float, float]) -> str:
    strip = crop_fraction(card_bgr, faction_tab_box)
    best_faction, best_coverage = "none", 0.1  # minimum coverage to count as "present"
    for faction, hsv_ranges in FACTION_HSV.items():
        coverage = region_coverage(strip, hsv_ranges)
        if coverage > best_coverage:
            best_faction, best_coverage = faction, coverage
    return best_faction


def detect_effect_category(card_bgr: np.ndarray, glyph_box: tuple[float, float, float, float]) -> str | None:
    """Only meaningful on background cards. See EFFECT_CATEGORY_HUES for how
    this was calibrated -- glyph pixels are just those bright enough to be
    the icon rather than its near-black square backing; among those, the
    gray star is "not saturated", the other three are matched by hue."""
    glyph = crop_fraction(card_bgr, glyph_box)
    if glyph.size == 0:
        return None
    hsv = cv2.cvtColor(glyph, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    bright = val > 90
    total = int(bright.sum())
    if total < 20:
        return None

    scores = {
        "additional_cost": float(((sat < EFFECT_CATEGORY_GRAY_SATURATION) & bright).sum()) / total
    }
    for category, hue_ranges in EFFECT_CATEGORY_HUES.items():
        mask = np.zeros(hue.shape, dtype=bool)
        for low, high in hue_ranges:
            mask |= (hue >= low) & (hue <= high)
        mask &= bright & (sat >= 100)
        scores[category] = float(mask.sum()) / total

    best_category = max(scores, key=scores.get)
    return best_category if scores[best_category] > 0.15 else None


def crop_fraction(card_bgr: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = card_bgr.shape[:2]
    left, top, right, bottom = box
    return card_bgr[int(top * h) : int(bottom * h), int(left * w) : int(right * w)]


def ocr_region(
    region_bgr: np.ndarray,
    *,
    psm: int,
    whitelist: str | None = None,
    inset: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    upscale: float = 1.0,
) -> str | None:
    """OCR one region. `inset` (left, top, right, bottom fractions) trims
    decorative borders -- e.g. a badge's ring outline, or a banner's folded
    ribbon ends -- that otherwise get misread as extra characters/noise;
    `upscale` helps Tesseract on small crops. Both mattered a lot in
    practice: cost/VP badges only OCR'd correctly once the ring was cropped
    out and the digit enlarged (see module docstring test notes)."""
    if region_bgr.size == 0:
        return None
    left, top, right, bottom = inset
    h, w = region_bgr.shape[:2]
    region_bgr = region_bgr[int(top * h) : int(h * (1 - bottom)), int(left * w) : int(w * (1 - right))]
    if region_bgr.size == 0:
        return None
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    if upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    text = pytesseract.image_to_string(thresh, lang=OCR_LANG, config=config)
    text = " ".join(text.split())
    return text or None


def rel_display(path: Path) -> str:
    """Path relative to the project root, forward-slashed for portability
    (and so it round-trips reliably as a JSON dict key/lookup value on
    Windows), or the plain path if it lives outside the project (e.g. a
    custom --output-dir)."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# HSV thresholds used to key the near-white photo backdrop out to
# transparency. Simple chroma key, not true matting: faint shadows/paper
# texture right at the art's edge can survive as semi-opaque haze.
BACKGROUND_WHITE_VALUE = 235
BACKGROUND_MAX_SATURATION = 25
BACKGROUND_ALPHA_FEATHER = 2  # gaussian blur radius (px) so the cutout edge isn't jagged


def remove_background(image_bgr: np.ndarray) -> np.ndarray:
    """Return a BGRA copy with the near-white backdrop keyed to transparent,
    so the crop can be layered on top of other art later."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    is_background = (hsv[:, :, 2] > BACKGROUND_WHITE_VALUE) & (hsv[:, :, 1] < BACKGROUND_MAX_SATURATION)
    alpha = np.where(is_background, 0, 255).astype(np.uint8)
    if BACKGROUND_ALPHA_FEATHER:
        k = BACKGROUND_ALPHA_FEATHER * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (k, k), 0)
    bgra = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha
    return bgra


# Raw photos aren't deskewed (see module docstring), so a badge/tab's fixed
# fractional box doesn't line up identically on every scan -- on some it's a
# precise fit, on others (framed with more margin around the physical card)
# it's noticeably off. There's no inset value that's correct for both; this
# is a light trim mostly to soften hard corners, not a fix for that
# underlying misalignment. Expect erasure to sometimes leave a sliver of
# badge, or eat a sliver of real art, until scans get a real deskew pass.
ERASE_INSET = 0.05
ERASE_ALPHA_FEATHER = 4


def build_artwork(image_bgr: np.ndarray, regions: dict) -> np.ndarray:
    """Standardized ARTWORK_OUTPUT_SIZE x ARTWORK_OUTPUT_SIZE artwork: crop
    regions["artwork"] (the top ARTWORK_HEIGHT_FRACTION of the card -- see
    that constant's comment), key the white backdrop to transparent, then
    also erase the cost/VP badges and the faction tab to transparent so only
    the scene (plus whatever banner sliver falls inside the crop) remains.
    Resized to exactly ARTWORK_OUTPUT_SIZE regardless of the source photo's
    resolution, so every card's exported artwork is pixel-identical in size.
    """
    crop = crop_fraction(image_bgr, regions["artwork"])
    bgra = remove_background(crop)

    erase_fields = ["cost", "faction_tab"]
    if "victory_points" in regions:
        erase_fields.append("victory_points")

    h, w = bgra.shape[:2]
    alpha = bgra[:, :, 3]
    for field in erase_fields:
        left, top, right, bottom = regions[field]
        box_w, box_h = right - left, bottom - top
        left, right = left + box_w * ERASE_INSET, right - box_w * ERASE_INSET
        top, bottom = top + box_h * ERASE_INSET, bottom - box_h * ERASE_INSET
        # regions["artwork"] only covers the card's top ARTWORK_HEIGHT_FRACTION,
        # so badge/tab y-coordinates (defined in full-card fractions) need
        # rescaling into this crop's own 0-1 coordinate space.
        y1 = int(top / ARTWORK_HEIGHT_FRACTION * h)
        y2 = int(bottom / ARTWORK_HEIGHT_FRACTION * h)
        x1, x2 = int(left * w), int(right * w)
        alpha[y1:y2, x1:x2] = 0
    k = ERASE_ALPHA_FEATHER * 2 + 1
    bgra[:, :, 3] = cv2.GaussianBlur(alpha, (k, k), 0)

    interpolation = cv2.INTER_AREA if w > ARTWORK_OUTPUT_SIZE else cv2.INTER_CUBIC
    return cv2.resize(bgra, (ARTWORK_OUTPUT_SIZE, ARTWORK_OUTPUT_SIZE), interpolation=interpolation)


# Inset/upscale tuned in module docstring's test notes -- ring outlines and
# ribbon-fold decorations otherwise get misread as extra characters.
BADGE_OCR_KWARGS = dict(inset=(0.3, 0.3, 0.3, 0.3), upscale=5.0)
NAME_OCR_KWARGS = dict(inset=(0.2, 0.18, 0.2, 0.08), upscale=2.0)
EFFECT_OCR_KWARGS = dict(inset=(0.05, 0.1, 0.05, 0.1), upscale=2.0)


def analyze_card(image_bgr: np.ndarray) -> dict:
    """Run classification + OCR on an already-loaded card photo. Pure
    function, no file I/O -- shared by the batch CLI below and the manual
    review tool (review_extraction.py)."""
    layout = classify_layout(image_bgr)
    regions = BACKGROUND_REGIONS if layout == "background" else HERO_REGIONS
    faction = detect_faction_tab(image_bgr, regions["faction_tab"])
    effect_category = None
    if "effect_category" in regions:
        effect_category = detect_effect_category(image_bgr, regions["effect_category"])

    cost = ocr_region(
        crop_fraction(image_bgr, regions["cost"]), psm=7, whitelist="0123456789", **BADGE_OCR_KWARGS
    )
    victory_points = None
    if "victory_points" in regions:
        victory_points = ocr_region(
            crop_fraction(image_bgr, regions["victory_points"]), psm=7, whitelist="0123456789X",
            **BADGE_OCR_KWARGS,
        )
    name = ocr_region(crop_fraction(image_bgr, regions["name"]), psm=11, **NAME_OCR_KWARGS)
    effect_text = ocr_region(crop_fraction(image_bgr, regions["effect"]), psm=6, **EFFECT_OCR_KWARGS)

    return {
        "layout": layout,
        "faction_tab": faction,
        "effect_category": effect_category,
        "cost": cost,
        "victory_points": victory_points,
        "name": name,
        "effect_text": effect_text,
        "regions": regions,
    }


def extract_card(path: Path, output_dir: Path) -> CardExtraction:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"could not read image: {path}")

    analysis = analyze_card(image)

    output_dir.mkdir(parents=True, exist_ok=True)
    artwork_path = output_dir / f"{path.stem}.png"
    cv2.imwrite(str(artwork_path), build_artwork(image, analysis["regions"]))

    return CardExtraction(
        source=rel_display(path),
        layout=analysis["layout"],
        faction_tab=analysis["faction_tab"],
        effect_category=analysis["effect_category"],
        cost=analysis["cost"],
        victory_points=analysis["victory_points"],
        name=analysis["name"],
        effect_text=analysis["effect_text"],
        artwork_path=rel_display(artwork_path),
    )


# Default install location of the UB-Mannheim Windows build, used as a
# fallback when the binary is installed but not on PATH.
FALLBACK_TESSERACT_CMD = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def check_tesseract_available() -> None:
    try:
        pytesseract.get_tesseract_version()
        return
    except EnvironmentError:
        pass

    if FALLBACK_TESSERACT_CMD.exists():
        pytesseract.pytesseract.tesseract_cmd = str(FALLBACK_TESSERACT_CMD)
        try:
            pytesseract.get_tesseract_version()
            return
        except EnvironmentError:
            pass

    sys.exit(
        "Tesseract OCR binary not found.\n"
        "Install it (e.g. `winget install UB-Mannheim.TesseractOCR`), make sure the "
        "French language data (fra.traineddata) is included, and re-run this script.\n"
        "If it's installed somewhere else, point to it with:\n"
        "  pytesseract.pytesseract.tesseract_cmd = r'C:\\path\\to\\tesseract.exe'"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*", type=Path,
        help="Specific raw scans to process (default: every .jpg in --input-dir)",
    )
    parser.add_argument("--input-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--review-json", type=Path, default=REVIEW_JSON)
    args = parser.parse_args()

    check_tesseract_available()

    targets = args.files if args.files else sorted(args.input_dir.glob("*.jpg"))
    results = []
    for path in targets:
        try:
            result = extract_card(path, args.output_dir)
        except Exception as exc:  # keep going; one bad scan shouldn't kill the batch
            print(f"FAILED {path.name}: {exc}")
            continue
        results.append(asdict(result))
        print(
            f"{path.name}: layout={result.layout} faction={result.faction_tab} "
            f"cost={result.cost} vp={result.victory_points} name={result.name!r}"
        )

    args.review_json.write_text(json.dumps(results, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(results)} entries to {rel_display(args.review_json)} for review.")


if __name__ == "__main__":
    main()
