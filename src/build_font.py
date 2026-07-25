"""Bake assets/font/*.png icons into ComickBook_CAPS.ttf as glyphs.

ComickBook_CAPS only has capital letters, digits, and standard punctuation in
active use by card text (see Card.lua's tokenize/ICON_MARKERS split, which is
the alternative -- separate Image UI elements interleaved with Text). This
script instead produces a single derived font where a handful of punctuation
codepoints that card text will never need (see CHAR_TO_ICON below) render as
icons, so a whole line can be a single Text element.

Each icon PNG is vectorized in two passes:
  1. its alpha channel gives the outer silhouette contour(s);
  2. any near-black pixels well inside that silhouette (border strokes and
     internal line art -- e.g. the leaf's vein, the globe's continent
     divisions) are extracted as hole contours and carved out of the glyph.
This keeps icons that share a rough outer shape (e.g. the human/monster/
mutant shields) visually distinct once reduced to a single-color glyph,
since the outer silhouette alone would look nearly identical.

Only the mapped glyphs' outlines/advance widths are touched -- cmap,
GlyphOrder, and every other glyph are untouched, so the output is safe to
swap in wherever ComickBook_CAPS.ttf is used today.

Usage:
    python src/build_font.py
    python src/build_font.py --src-font assets/ComickBook_CAPS.ttf --output assets/ComickBook_CAPS_Icons.ttf
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from PIL import Image

# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC_FONT = PROJECT_ROOT / "assets" / "ComickBook_CAPS.ttf"
DEFAULT_ICON_DIR = PROJECT_ROOT / "assets" / "font"
DEFAULT_OUTPUT_FONT = PROJECT_ROOT / "assets" / "ComickBook_CAPS_Icons.ttf"

# Which unused punctuation codepoint becomes which assets/font/<stem>.png icon.
# Picked to be characters card text (uppercase letters, digits, and standard
# punctuation) will never need -- see Card.lua's tokenize().
CHAR_TO_ICON = {
    "_": "coin",
    "{": "human",
    "}": "monster",
    "[": "mutant",
    "]": "plant",
    "|": "resource",
    "~": "rock",
    "^": "water",
    "\\": "condition",
    "`": "extra_cost",
    "@": "on_play",
}

# Icon glyphs are scaled to this height (font units, baseline at y=0) --
# matches the source font's capital-letter height (see 'A' glyph's yMax), so
# an icon sits flush with a line of capital text.
CAP_HEIGHT = 1662

# Left/right side bearing applied to every icon glyph, in font units --
# matches the source font's typical letter side bearing (see 'A' glyph's
# advance width minus its xMax).
SIDE_BEARING = 61

# --- Vectorization tuning (all fractions are relative to min(icon width, icon height) in px) ---

# Gaussian blur radius applied to the alpha channel before thresholding, to
# smooth painterly/antialiased edges before tracing the outer silhouette.
BLUR_FRAC = 0.012

# cv2.approxPolyDP epsilon (as a fraction of contour perimeter) used to
# simplify both outer and hole contours into clean, low-point polygons.
SIMPLIFY_FRAC = 0.004

# Outer contours smaller than this fraction of the image area are dropped as
# noise.
MIN_AREA_FRAC = 0.003

# A pixel counts as "line art" if opaque and max(R, G, B) is below this.
DARK_THRESHOLD = 70

# How far to erode the outer silhouette (as a fraction of min(w, h)) before
# looking for internal line art, so the icon's own outer border stroke isn't
# mistaken for an internal hole.
ERODE_FRAC = 0.15

# Hole contours smaller than this fraction of the image area are dropped as
# noise.
HOLE_MIN_AREA_FRAC = 0.004


# --------------------------------------------------------------------------
# Vectorization
# --------------------------------------------------------------------------


def _simplify(contour: np.ndarray) -> np.ndarray:
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, SIMPLIFY_FRAC * peri, True)
    return approx.reshape(-1, 2).astype(np.float64)


def trace_icon(path: Path) -> tuple[list[np.ndarray], list[np.ndarray], tuple[float, float, float, float]]:
    """Returns (outer_contours, hole_contours, pixel_bbox) for the icon at `path`."""
    image = Image.open(path).convert("RGBA")
    arr = np.array(image)
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]

    k = max(1, int(round(min(w, h) * BLUR_FRAC)) | 1)  # odd kernel size
    blurred = cv2.GaussianBlur(alpha, (k, k), 0)
    _, silhouette = cv2.threshold(blurred, 127, 255, cv2.THRESH_BINARY)

    img_area = w * h
    outer_raw, _ = cv2.findContours(silhouette, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outers = [_simplify(c) for c in outer_raw if cv2.contourArea(c) >= img_area * MIN_AREA_FRAC]

    rgb_max = arr[:, :, :3].max(axis=2)
    dark_raw = ((rgb_max < DARK_THRESHOLD) & (alpha > 127)).astype(np.uint8) * 255
    dark = cv2.medianBlur(dark_raw, 5)

    erode_px = max(2, int(round(min(w, h) * ERODE_FRAC)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))
    interior = cv2.erode(silhouette, kernel)

    internal_dark = cv2.bitwise_and(dark, interior)
    hole_raw, _ = cv2.findContours(internal_dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    holes = [_simplify(c) for c in hole_raw if cv2.contourArea(c) >= img_area * HOLE_MIN_AREA_FRAC]

    all_pts = np.vstack(outers)
    xmin, ymin = all_pts.min(axis=0)
    xmax, ymax = all_pts.max(axis=0)
    return outers, holes, (xmin, ymin, xmax, ymax)


def _signed_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _to_font_space(pts: np.ndarray, bbox_px: tuple[float, float, float, float], scale: float) -> np.ndarray:
    xmin, _ymin, _xmax, ymax = bbox_px
    out = np.empty_like(pts)
    out[:, 0] = (pts[:, 0] - xmin) * scale + SIDE_BEARING
    out[:, 1] = (ymax - pts[:, 1]) * scale  # flip: image y-down -> font y-up, baseline at 0
    return out


def _draw_contour(pen: TTGlyphPen, pts: np.ndarray) -> None:
    pts_int = [(int(round(x)), int(round(y))) for x, y in pts]
    pen.moveTo(pts_int[0])
    for p in pts_int[1:]:
        pen.lineTo(p)
    pen.closePath()


def build_glyph(outers: list[np.ndarray], holes: list[np.ndarray], bbox_px: tuple[float, float, float, float]):
    """Returns (glyph, advance_width). Outer contours are forced clockwise and
    hole contours counter-clockwise (font-space, y-up) so hole geometry
    actually carves a gap under the nonzero fill rule."""
    xmin, _ymin, xmax, _ymax = bbox_px
    height_px = bbox_px[3] - bbox_px[1]
    scale = CAP_HEIGHT / height_px
    advance_width = int(round((xmax - xmin) * scale)) + 2 * SIDE_BEARING

    pen = TTGlyphPen(None)
    for poly in outers:
        pts = _to_font_space(poly, bbox_px, scale)
        if np.sign(_signed_area(pts)) != -1:
            pts = pts[::-1]
        _draw_contour(pen, pts)
    for poly in holes:
        pts = _to_font_space(poly, bbox_px, scale)
        if np.sign(_signed_area(pts)) != 1:
            pts = pts[::-1]
        _draw_contour(pen, pts)

    return pen.glyph(), advance_width


# --------------------------------------------------------------------------
# Font patching
# --------------------------------------------------------------------------


def rename_font(font: TTFont, suffix: str) -> None:
    """Appends `suffix` to family/full/unique-ID name records so the derived
    font doesn't collide with the original in OS/font-manager caches."""
    name_table = font["name"]
    for rec in name_table.names:
        if rec.nameID not in (1, 4, 6, 16):
            continue
        try:
            value = rec.toUnicode()
        except Exception:
            continue
        if "Comic" not in value:
            continue
        new_value = value + suffix if rec.nameID != 6 else value + suffix.replace(" ", "-")
        name_table.setName(new_value, rec.nameID, rec.platformID, rec.platEncID, rec.langID)


def build_font(src_font: Path, icon_dir: Path, output: Path, mapping: dict[str, str]) -> None:
    # The source TTF has a malformed OS/2 table (predates this project);
    # ignoreDecompileErrors passes it through unchanged rather than choking --
    # it already renders fine wherever ComickBook_CAPS.ttf is used today.
    font = TTFont(str(src_font), ignoreDecompileErrors=True)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    hmtx = font["hmtx"]

    for char, icon_stem in mapping.items():
        glyph_name = cmap[ord(char)]
        outers, holes, bbox_px = trace_icon(icon_dir / f"{icon_stem}.png")
        glyph, advance_width = build_glyph(outers, holes, bbox_px)
        glyph.recalcBounds(glyf)
        glyf[glyph_name] = glyph
        hmtx[glyph_name] = (advance_width, glyph.xMin)
        print(
            f"{char!r} ({glyph_name}) <- {icon_stem}.png : advance={advance_width}, "
            f"bbox=({glyph.xMin},{glyph.yMin},{glyph.xMax},{glyph.yMax}), "
            f"outers={len(outers)} holes={len(holes)}"
        )

    rename_font(font, " Icons")
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(output))
    print(f"\nSaved {output}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src-font", type=Path, default=DEFAULT_SRC_FONT)
    parser.add_argument("--icon-dir", type=Path, default=DEFAULT_ICON_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FONT)
    args = parser.parse_args()

    build_font(args.src_font, args.icon_dir, args.output, CHAR_TO_ICON)


if __name__ == "__main__":
    main()
