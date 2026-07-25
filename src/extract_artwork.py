"""Extract card data out of raw physical-card scans.

The photos in assets/raw/ show a finished physical card: a cost coin
(top-left), art, a name banner, and an effect banner. Background cards
additionally carry a victory-point trophy (top-right) and, unique to them, a
small near-black effect-category icon box on the left edge of the effect
banner (a heart/star/trophy glyph depending on category).

Earlier versions of this script used one fixed fractional bounding box per
element, shared across every scan. That doesn't hold up: raw photos aren't
deskewed (see the limitation note below), so the same box lands slightly
differently on every card, and heroes/backgrounds aren't even laid out
identically to begin with. This version detects each element PER CARD instead:
  - cost/VP badges: largest sufficiently-round, sufficiently-saturated gold
    blob within a generous corner search window (contour + extent filter,
    not a fixed box). Validated against 4 known scans, 4/4 cost + 3/3 VP.
  - faction tab: largest blue/red blob within a left-edge search window that
    also passes a shape check (tall/narrow, hugs the left edge -- see
    FACTION_MIN_ASPECT), using the raw CONTOUR (not its bounding box) for
    masking -- the tab has pointed tips a rectangle either clips or way
    overshoots. The shape check exists because color alone isn't enough:
    without it, same-colored artwork (blue water on a maritime-themed card)
    got misdetected as the tab and erased from the final artwork. Most cards
    have no tab at all, so "nothing matched" correctly means faction "none",
    not a guess.
  - name/effect text: Tesseract's word-level boxes (image_to_data) within a
    generous search window, unioned into a bounding box. Falls back to a
    fixed default box if OCR finds nothing confident in the window, so a bad
    scan degrades to the old behavior rather than losing the field.

Background/foreground separation also changed: naively keying near-white
pixels to transparent kills legitimate white art (e.g. white paper inside a
framed image, in the "AVEC DIPLOME" test card) along with the real photo
backdrop. Swapped to OpenCV's GrabCut, seeded with an inset rectangle --
it segments by color+spatial coherence instead of a flat threshold, so a
white region connected to the rest of the illustration survives. Confirmed
on the same test card: framed certificate's paper interior stayed opaque,
true background around it still keyed out.

For each scan this:
  1. classifies it as "hero" or "background" via the effect-icon-box signal,
  2. detects the faction tab (blue=human, red/pink/magenta=monster, no
     tab="none") and, on backgrounds only, the effect-category icon color
     (condition/additional_cost/on_play/victory_calc -- see
     EFFECT_CATEGORY_HUES),
  3. builds a standardized ARTWORK_OUTPUT_SIZE-square artwork crop: GrabCut
     for the backdrop, the detected badge/tab shapes erased on top, edges
     trimmed and cleaned up (see build_artwork),
  4. OCRs the cost and the name/effect text out of their detected (not
     fixed) regions. Victory points is NOT OCR'd -- it's a game-rule lookup,
     not a printed digit that varies: 1 VP for every background, except "X"
     when the effect category is victory_calc (the VP trophy badge is still
     detected and erased from the artwork like any other badge, its printed
     value just isn't read),
  5. writes everything to a review JSON -- NOT directly into data.json,
     since OCR will misread accented French text and shouldn't silently
     clobber curated data. Check extracted_data.json by hand and merge
     what's correct.

Known limitation: there's no deskew/rotation-correction step. An earlier
attempt at contour-based card detection was tried and scrapped -- on these
photos the largest contour was reliably a piece of interior artwork, not the
card's own edge, which made crops worse, not better. Per-element detection
(this version) absorbs most of the resulting misalignment, but a photo shot
at a real angle or with clutter in frame (the handful of plain-timestamp
phone photos) still needs to be manually rotated/cropped first -- the search
windows assume "roughly upright, roughly full-frame".

Requires the Tesseract OCR binary on PATH with the French (fra) language
pack installed, in addition to `pip install pytesseract opencv-python`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pytesseract

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "assets" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "extracted"
REVIEW_JSON = PROJECT_ROOT / "src" / "extracted_data.json"

OCR_LANG = "fra"

RAW_SCAN_EXTENSIONS = ("*.jpg", "*.jpeg", "*.png")


def find_raw_scans(directory: Path) -> list[Path]:
    """Every raw scan directly in `directory` (non-recursive -- e.g. a
    'done' subfolder some review sessions use to set aside finished scans is
    deliberately not descended into), across the extensions actual scans
    show up in. Used by both this CLI and review_extraction.py so the two
    tools always agree on what counts as a scan."""
    paths = [p for ext in RAW_SCAN_EXTENSIONS for p in directory.glob(ext)]
    return sorted(set(paths))

# A card is 5:7 (width:height). Artwork is standardized to a 1000x1000
# square: at 1000px card-width, full card height would be 1400px, so a
# 1000px-tall crop captures the top CARD_ASPECT_W/CARD_ASPECT_H = 5/7 of the
# card -- everything above the effect-text band, landing partway through the
# name banner (roughly half of it ends up in frame; a fixed crop height
# can't land exactly on the banner's edge without per-card tuning).
CARD_ASPECT_W, CARD_ASPECT_H = 5, 7
ARTWORK_OUTPUT_SIZE = 1000
ARTWORK_HEIGHT_FRACTION = CARD_ASPECT_W / CARD_ASPECT_H

# Generous SEARCH windows (fractional left, top, right, bottom) -- priors for
# where to look, not the final answer. The final box comes from detecting the
# actual badge/tab/text within the window on each card.
COST_SEARCH = (0.0, 0.0, 0.22, 0.18)
VP_SEARCH = (0.78, 0.0, 1.0, 0.18)
FACTION_SEARCH = (0.0, 0.05, 0.22, 0.65)
NAME_SEARCH = {
    "background": (0.05, 0.58, 0.95, 0.80),
    "hero": (0.03, 0.48, 0.97, 0.68),
}
EFFECT_SEARCH = {
    "background": (0.0, 0.72, 1.0, 0.97),
    "hero": (0.0, 0.58, 1.0, 0.92),
}

# Static fallback boxes, used only when adaptive text-region detection finds
# nothing confident in the search window above (bad lighting, OCR chokes,
# etc.) -- degrades to "old fixed-box behavior" rather than losing the field.
NAME_FALLBACK = {
    "background": (0.12, 0.63, 0.88, 0.76),
    "hero": (0.1, 0.55, 0.9, 0.63),
}
EFFECT_FALLBACK = {
    "background": (0.03, 0.76, 1.0, 0.94),
    "hero": (0.03, 0.65, 1.0, 0.86),
}
EFFECT_CATEGORY_BOX = (0.07, 0.76, 0.20, 0.86)

# Fractional band covering the effect-category icon box (the dark square
# itself, wider than EFFECT_CATEGORY_BOX above), used for background/hero
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
FACTION_MIN_AREA_FRAC = 0.01  # of the search window
FACTION_MAX_AREA_FRAC = 0.35
# The tab is a tall narrow blade/pennant, not a blob -- height/width measured
# ~7.0-7.2 across all 3 known background cards with a tab. A same-colored
# patch of artwork (e.g. blue water on a maritime-themed card) is much more
# likely to be wide/irregular than this, so a low aspect ratio is the
# cheapest signal that a color match ISN'T the actual tab. Bug report: an
# earlier version had no shape check at all and picked up exactly this kind
# of false positive on a maritime card, then erased a chunk of real artwork.
FACTION_MIN_ASPECT = 3.0
FACTION_MAX_LEFT_FRAC = 0.4  # the tab hugs the search window's left edge; reject blobs that don't

# Gold badge detection: hue range for coin/trophy gold, plus shape filters.
# Saturation floor is high (170) on purpose -- some scans have a warm color
# cast that pushes the plain white paper background to hue~18-20, same as
# real gold, but only the actual badge reaches S>200; the cast background
# sits around S~100-140. Extent (contour area / bounding-box area) is used
# instead of circularity because the VP badge is a trophy, not a circle --
# true circularity rejected it in testing even at generous thresholds.
GOLD_HSV = (np.array([10, 170, 100]), np.array([40, 255, 255]))
BADGE_MIN_AREA_FRAC = 0.01
BADGE_MAX_AREA_FRAC = 0.35
BADGE_MIN_EXTENT = 0.45
BADGE_PAD_FRAC = 0.15  # grow the detected blob box this much to include its dark ring outline

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

TEXT_LOCATE_MIN_CONF = 30
TEXT_LOCATE_UPSCALE = 2.0


@dataclass
class CardExtraction:
    source: str
    layout: str
    faction_tab: str | None
    effect_category: str | None
    cost: str | None
    victory_points: int | str | None
    name: str | None
    effect_text: str | None
    boxes: dict
    artwork_path: str | None


def crop_fraction(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = image.shape[:2]
    left, top, right, bottom = box
    return image[int(top * h) : int(bottom * h), int(left * w) : int(right * w)]


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
    band = crop_fraction(card_bgr, EFFECT_ICON_BAND)
    if band.size == 0:
        return "hero"
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    dark_fraction = float((gray < DARK_PIXEL_THRESHOLD).sum()) / gray.size
    return "background" if dark_fraction > LAYOUT_DARK_FRACTION_CUTOFF else "hero"


def detect_badge(image_bgr: np.ndarray, search_box: tuple[float, float, float, float]) -> tuple[int, int, int, int] | None:
    """Largest sufficiently-round/compact gold blob in `search_box`. Returns
    a padded (x, y, w, h) in GLOBAL pixel coordinates, or None."""
    h, w = image_bgr.shape[:2]
    x0, y0 = int(search_box[0] * w), int(search_box[1] * h)
    roi = crop_fraction(image_bgr, search_box)
    if roi.size == 0:
        return None
    win_area = roi.shape[0] * roi.shape[1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, *GOLD_HSV)
    k = max(3, int(min(roi.shape[:2]) * 0.06))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_contour, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        area_frac = area / win_area
        if area_frac < BADGE_MIN_AREA_FRAC or area_frac > BADGE_MAX_AREA_FRAC:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        extent = area / (bw * bh) if bw * bh else 0.0
        if extent < BADGE_MIN_EXTENT:
            continue
        if area > best_area:
            best_contour, best_area = c, area
    if best_contour is None:
        return None

    bx, by, bw, bh = cv2.boundingRect(best_contour)
    pad_x, pad_y = int(bw * BADGE_PAD_FRAC), int(bh * BADGE_PAD_FRAC)
    gx1 = max(x0 + bx - pad_x, 0)
    gy1 = max(y0 + by - pad_y, 0)
    gx2 = min(x0 + bx + bw + pad_x, w)
    gy2 = min(y0 + by + bh + pad_y, h)
    return (gx1, gy1, gx2 - gx1, gy2 - gy1)


def detect_faction_tab(
    image_bgr: np.ndarray, search_box: tuple[float, float, float, float]
) -> tuple[str, np.ndarray | None]:
    """Largest blue/red blob in `search_box` that actually looks like the
    tab (tall, narrow, hugging the left edge -- see FACTION_MIN_ASPECT).
    Returns (faction, contour) with the contour in GLOBAL pixel coordinates
    (or None if nothing found) -- callers that need a precise erase mask
    should use the contour itself, not its bounding box, since the tab has
    pointed tips a rectangle can't follow without either clipping them or
    grabbing way more than needed.

    Without the shape check, any same-colored patch of artwork in the search
    window (blue water on a maritime-themed card, say) reads as "the tab" --
    confirmed bug, and a damaging one, since whatever this returns gets
    erased from the final artwork. Most cards don't have a tab at all
    (faction "none" is common), so defaulting to "none" whenever nothing
    matches the real shape is the safe failure mode, not a fallback guess.
    """
    h, w = image_bgr.shape[:2]
    x0, y0 = int(search_box[0] * w), int(search_box[1] * h)
    roi = crop_fraction(image_bgr, search_box)
    if roi.size == 0:
        return "none", None
    roi_h, roi_w = roi.shape[:2]
    win_area = roi_h * roi_w
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    best_faction, best_contour, best_area = "none", None, 0.0
    for faction, hsv_ranges in FACTION_HSV.items():
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in hsv_ranges:
            mask |= cv2.inRange(hsv, low, high)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            area_frac = area / win_area
            if area_frac < FACTION_MIN_AREA_FRAC or area_frac > FACTION_MAX_AREA_FRAC:
                continue
            bx, by, bw, bh = cv2.boundingRect(c)
            if bw == 0 or bh / bw < FACTION_MIN_ASPECT:
                continue
            if bx / roi_w > FACTION_MAX_LEFT_FRAC:
                continue
            if area > best_area:
                best_faction, best_contour, best_area = faction, c, area

    if best_contour is None:
        return "none", None
    return best_faction, best_contour + np.array([x0, y0])


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


def locate_text_box(
    image_bgr: np.ndarray, search_box: tuple[float, float, float, float], psm: int
) -> tuple[float, float, float, float] | None:
    """Union bounding box of confident OCR words found in `search_box`,
    returned in fractional card coordinates. None if nothing confident was
    found -- caller should fall back to a fixed default box in that case."""
    roi = crop_fraction(image_bgr, search_box)
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    upscaled = cv2.resize(gray, None, fx=TEXT_LOCATE_UPSCALE, fy=TEXT_LOCATE_UPSCALE, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    data = pytesseract.image_to_data(
        thresh, lang=OCR_LANG, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )

    xs, ys, xe, ye = [], [], [], []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        try:
            conf = int(data["conf"][i])
        except ValueError:
            conf = -1
        if text and conf >= TEXT_LOCATE_MIN_CONF:
            xs.append(data["left"][i])
            ys.append(data["top"][i])
            xe.append(data["left"][i] + data["width"][i])
            ye.append(data["top"][i] + data["height"][i])
    if not xs:
        return None

    roi_h, roi_w = roi.shape[:2]
    sl, st, sr, sb = search_box
    sw, sh = sr - sl, sb - st
    left = sl + (min(xs) / TEXT_LOCATE_UPSCALE) / roi_w * sw
    right = sl + (max(xe) / TEXT_LOCATE_UPSCALE) / roi_w * sw
    top = st + (min(ys) / TEXT_LOCATE_UPSCALE) / roi_h * sh
    bottom = st + (max(ye) / TEXT_LOCATE_UPSCALE) / roi_h * sh
    # pad a bit so the follow-up OCR pass (which applies its own inset) isn't
    # cropped flush against the detected glyph edges
    pad_x, pad_y = (right - left) * 0.08, (bottom - top) * 0.15
    return (
        max(left - pad_x, sl),
        max(top - pad_y, st),
        min(right + pad_x, sr),
        min(bottom + pad_y, sb),
    )


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
    `upscale` helps Tesseract on small crops."""
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


# GrabCut init rect is inset this much from the crop's own edges (assumes the
# photographed backdrop forms a border around the art, which held on every
# test card). More iterations converge better but cost more time per card.
GRABCUT_MARGIN_FRAC = 0.04
GRABCUT_ITERATIONS = 5


def remove_background_grabcut(image_bgr: np.ndarray) -> np.ndarray:
    """BGRA copy with the backdrop segmented out via GrabCut instead of a
    flat color key -- color+spatial-coherence based, so a white region
    connected to the rest of the illustration (e.g. paper inside a framed
    picture) survives as opaque instead of being punched transparent along
    with the real backdrop. See module docstring for the validation case."""
    h, w = image_bgr.shape[:2]
    if h < 20 or w < 20:
        bgra = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2BGRA)
        bgra[:, :, 3] = 255
        return bgra

    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    mx, my = int(w * GRABCUT_MARGIN_FRAC), int(h * GRABCUT_MARGIN_FRAC)
    rect = (mx, my, max(w - 2 * mx, 1), max(h - 2 * my, 1))
    try:
        cv2.grabCut(image_bgr, mask, rect, bgd_model, fgd_model, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_RECT)
        alpha = np.where((mask == 2) | (mask == 0), 0, 255).astype(np.uint8)
    except cv2.error:
        alpha = np.full((h, w), 255, dtype=np.uint8)  # degenerate image (e.g. flat color) -- keep it all

    bgra = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha
    return bgra


EDGE_TRIM_FRAC = 0.015  # force-transparent border strip -- cleans up residual photo-edge/shadow fringe
# OPEN removes small stray opaque specks -- kept tiny on purpose. A kernel
# anywhere close to CLOSE's size started eating legitimate art (e.g. the
# white paper inside a framed picture, on the "AVEC DIPLOME" test card,
# vanished at 0.01) instead of just noise. CLOSE (hole-filling) doesn't have
# that failure mode, so it can afford to be more generous.
ALPHA_OPEN_KERNEL_FRAC = 0.002
ALPHA_CLOSE_KERNEL_FRAC = 0.008
ALPHA_FEATHER = 4  # gaussian blur radius (px) on the final alpha so edges aren't hard/jagged


def clean_alpha(alpha: np.ndarray) -> np.ndarray:
    open_k = max(3, int(min(alpha.shape) * ALPHA_OPEN_KERNEL_FRAC))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k)))
    close_k = max(3, int(min(alpha.shape) * ALPHA_CLOSE_KERNEL_FRAC))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)))

    t = max(1, int(min(alpha.shape) * EDGE_TRIM_FRAC))
    alpha[:t, :] = 0
    alpha[-t:, :] = 0
    alpha[:, :t] = 0
    alpha[:, -t:] = 0

    k = ALPHA_FEATHER * 2 + 1
    return cv2.GaussianBlur(alpha, (k, k), 0)


def build_artwork(
    image_bgr: np.ndarray, analysis: dict, on_step: Callable[[str], None] | None = None
) -> np.ndarray:
    """Standardized ARTWORK_OUTPUT_SIZE x ARTWORK_OUTPUT_SIZE artwork: crop
    boxes["artwork"] (the top ARTWORK_HEIGHT_FRACTION of the card -- see that
    constant's comment), segment the backdrop out with GrabCut, erase the
    detected badge/tab shapes on top, clean up the alpha mask, then resize to
    exactly ARTWORK_OUTPUT_SIZE regardless of the source photo's resolution.
    `analysis` is analyze_card()'s return value for this same image. `on_step`,
    if given, is called with a short human-readable label before each phase
    (GrabCut is the slow one) -- e.g. to drive a progress bar.
    """
    def step(label: str) -> None:
        if on_step:
            on_step(label)

    step("Cropping artwork region")
    art_box = analysis["boxes"]["artwork"]
    crop = crop_fraction(image_bgr, art_box)
    erase_crop = crop_fraction(analysis["erase_mask"], art_box)

    step("Removing background (GrabCut)")
    bgra = remove_background_grabcut(crop)

    step("Erasing badges/tab")
    alpha = bgra[:, :, 3]
    alpha[erase_crop > 0] = 0
    bgra[:, :, 3] = clean_alpha(alpha)

    step("Resizing to standard size")
    h, w = bgra.shape[:2]
    interpolation = cv2.INTER_AREA if w > ARTWORK_OUTPUT_SIZE else cv2.INTER_CUBIC
    result = cv2.resize(bgra, (ARTWORK_OUTPUT_SIZE, ARTWORK_OUTPUT_SIZE), interpolation=interpolation)
    step("Artwork built")
    return result


# Insets/upscale tuned in module docstring's test notes -- ring outlines and
# ribbon-fold decorations otherwise get misread as extra characters. Now that
# the badge box is adaptively detected (tight fit + BADGE_PAD_FRAC padding)
# rather than a generous fixed guess, no single inset reads every coin
# correctly -- trying a few and taking the first hit got 4/4 in testing.
COST_OCR_INSETS = [(0.1, 0.1, 0.1, 0.1), (0.15, 0.15, 0.15, 0.15), (0.2, 0.2, 0.2, 0.2), (0.25, 0.25, 0.25, 0.25)]
NAME_OCR_KWARGS = dict(inset=(0.2, 0.18, 0.2, 0.08), upscale=2.0)
EFFECT_OCR_KWARGS = dict(inset=(0.05, 0.1, 0.05, 0.1), upscale=2.0)


def ocr_first_match(region_bgr: np.ndarray, *, psm: int, whitelist: str, insets: list, upscale: float) -> str | None:
    for inset in insets:
        result = ocr_region(region_bgr, psm=psm, whitelist=whitelist, inset=inset, upscale=upscale)
        if result:
            return result
    return None


def analyze_card(image_bgr: np.ndarray) -> dict:
    """Detect + OCR everything on an already-loaded card photo. Pure
    function, no file I/O -- shared by the batch CLI below and the manual
    review tool (review_extraction.py). Returns per-card detected boxes
    (fractional card coordinates) plus a full-resolution erase_mask
    (badge/tab pixels to punch transparent) that build_artwork consumes."""
    h, w = image_bgr.shape[:2]
    layout = classify_layout(image_bgr)
    erase_mask = np.zeros((h, w), dtype=np.uint8)
    boxes: dict = {"artwork": (0.0, 0.0, 1.0, ARTWORK_HEIGHT_FRACTION)}

    cost = None
    cost_px = detect_badge(image_bgr, COST_SEARCH)
    if cost_px is not None:
        cx, cy, cw, ch = cost_px
        erase_mask[cy : cy + ch, cx : cx + cw] = 255
        boxes["cost"] = (cx / w, cy / h, (cx + cw) / w, (cy + ch) / h)
        cost = ocr_first_match(
            crop_fraction(image_bgr, boxes["cost"]), psm=7, whitelist="0123456789",
            insets=COST_OCR_INSETS, upscale=5.0,
        )

    # Victory points aren't a free-form number: a background is worth 1 VP,
    # unless its effect category is victory_calc, in which case it's however
    # many the effect computes at scoring time -- printed on the card as
    # "X", not a digit. So this is a straight lookup from effect_category,
    # not something to OCR off the trophy badge. (The badge itself still
    # needs detecting/erasing below -- it's real printed content, just not
    # a value we read.)
    effect_category = None
    victory_points = None
    if layout == "background":
        effect_category = detect_effect_category(image_bgr, EFFECT_CATEGORY_BOX)
        boxes["effect_category"] = EFFECT_CATEGORY_BOX
        victory_points = "X" if effect_category == "victory_calc" else 1

        vp_px = detect_badge(image_bgr, VP_SEARCH)
        if vp_px is not None:
            vx, vy, vw, vh = vp_px
            erase_mask[vy : vy + vh, vx : vx + vw] = 255
            boxes["victory_points"] = (vx / w, vy / h, (vx + vw) / w, (vy + vh) / h)

    faction, faction_contour = detect_faction_tab(image_bgr, FACTION_SEARCH)
    if faction_contour is not None:
        cv2.fillPoly(erase_mask, [faction_contour], 255)
        fx, fy, fw, fh = cv2.boundingRect(faction_contour)
        boxes["faction_tab"] = (fx / w, fy / h, (fx + fw) / w, (fy + fh) / h)

    # grow the whole erase mask a little so badges'/tab's own dark outline
    # (not part of the colored blob detected above) gets punched out too
    dilate_px = max(1, int(w * 0.006))
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px * 2 + 1, dilate_px * 2 + 1))
    erase_mask = cv2.dilate(erase_mask, dilate_kernel)

    name_box = locate_text_box(image_bgr, NAME_SEARCH[layout], psm=11) or NAME_FALLBACK[layout]
    boxes["name"] = name_box
    name = ocr_region(crop_fraction(image_bgr, name_box), psm=11, **NAME_OCR_KWARGS)

    effect_box = locate_text_box(image_bgr, EFFECT_SEARCH[layout], psm=11) or EFFECT_FALLBACK[layout]
    boxes["effect"] = effect_box
    effect_text = ocr_region(crop_fraction(image_bgr, effect_box), psm=6, **EFFECT_OCR_KWARGS)

    return {
        "layout": layout,
        "faction_tab": faction,
        "effect_category": effect_category,
        "cost": cost,
        "victory_points": victory_points,
        "name": name,
        "effect_text": effect_text,
        "boxes": boxes,
        "erase_mask": erase_mask,
    }


def extract_card(path: Path, output_dir: Path) -> CardExtraction:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"could not read image: {path}")

    analysis = analyze_card(image)

    output_dir.mkdir(parents=True, exist_ok=True)
    artwork_path = output_dir / f"{path.stem}.png"
    cv2.imwrite(str(artwork_path), build_artwork(image, analysis))

    return CardExtraction(
        source=rel_display(path),
        layout=analysis["layout"],
        faction_tab=analysis["faction_tab"],
        effect_category=analysis["effect_category"],
        cost=analysis["cost"],
        victory_points=analysis["victory_points"],
        name=analysis["name"],
        effect_text=analysis["effect_text"],
        boxes=analysis["boxes"],
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
        help="Specific raw scans to process (default: every scan in --input-dir)",
    )
    parser.add_argument("--input-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--review-json", type=Path, default=REVIEW_JSON)
    args = parser.parse_args()

    check_tesseract_available()

    targets = args.files if args.files else find_raw_scans(args.input_dir)
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
