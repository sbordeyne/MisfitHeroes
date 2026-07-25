"""Manually review/correct OCR results from extract_artwork.py and produce
final per-card assets.

Pick a raw scan, hit "Scan with OCR" (runs the exact same detect+OCR pipeline
as extract_artwork.py's analyze_card, on just that one image -- badges/tab/
text boxes are detected per-card, not looked up from a fixed template; see
that module's docstring), fix whatever it got wrong, and "Save" to write:
  assets/processed/<slugified name>/artwork.png   -- standardized artwork
                                                       crop, backdrop removed
                                                       via GrabCut, badges/tab
                                                       erased
  assets/processed/<slugified name>/results.json  -- card data + the
                                                       fractional {x,y,width,
                                                       height} box of every
                                                       detected field, for
                                                       recomposing cards later

Re-selecting a raw scan that's already been saved reloads its saved values
(rather than blanking the form), so a review pass can be stopped and resumed.

Run with: python src/review_extraction.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from tkinter import BooleanVar, DoubleVar, StringVar, Tk, Canvas, Text, messagebox
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_artwork import (  # noqa: E402
    EFFECT_CATEGORY_HUES,
    PROJECT_ROOT,
    RAW_DIR,
    analyze_card,
    build_artwork,
    check_tesseract_available,
    rel_display,
)

PROCESSED_DIR = PROJECT_ROOT / "assets" / "processed"

BOX_COLORS = {
    "artwork": "#00BFFF",
    "name": "#FFD700",
    "effect": "#FF8C00",
    "cost": "#32CD32",
    "victory_points": "#FF69B4",
    "faction_tab": "#9370DB",
    "effect_category": "#00FA9A",
}

FACTIONS = ["human", "monster", "none"]
EFFECT_CATEGORIES = ["additional_cost", *EFFECT_CATEGORY_HUES]  # additional_cost is gray, not hue-based

COST_MAX = 30


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "untitled"


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def box_to_xywh(box: tuple[float, float, float, float]) -> dict:
    left, top, right, bottom = box
    return {
        "x": round(left, 4),
        "y": round(top, 4),
        "width": round(right - left, 4),
        "height": round(bottom - top, 4),
    }


def xywh_to_box(d: dict) -> tuple[float, float, float, float]:
    return (d["x"], d["y"], d["x"] + d["width"], d["y"] + d["height"])


class ReviewApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("Misfit Heroes -- card extraction review")
        root.geometry("1280x800")

        self.raw_files: list[Path] = sorted(RAW_DIR.glob("*.jpg"))
        self.item_to_path: dict[str, Path] = {}
        self.processed_by_source: dict[str, Path] = {}

        self.current_path: Path | None = None
        self.current_image_bgr = None
        self.photo_image = None
        self.display_size = (0, 0)

        # Boxes are detected per-card now (not a fixed layout template), so
        # they're only known once analyze_card has actually run on this
        # image -- either via "Scan with OCR", or reconstructed from a
        # previously-saved review's regions. last_analysis (which carries the
        # full-resolution erase_mask build_artwork needs) is cheaper to just
        # keep IF it's still for the current image, and cheap to recompute
        # otherwise -- see _ensure_analysis.
        self.last_boxes: dict = {}
        self.last_analysis: dict | None = None
        self.last_analysis_path: Path | None = None

        self.show_boxes = BooleanVar(value=True)
        self.layout_var = StringVar(value="background")
        self.faction_var = StringVar(value="none")
        self.effect_category_var = StringVar(value="")
        self.cost_var = DoubleVar(value=0)
        # Victory points isn't independently editable: it's 1 for every
        # background except victory_calc, which is "X" -- a straight lookup
        # from effect_category, not a value someone reads off the card.
        self.vp_display_var = StringVar(value="")
        self.status_var = StringVar(value="Select a raw scan to begin.")

        self._build_ui()
        self.refresh_processed_index()
        self.refresh_list()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        list_frame = ttk.Frame(paned, padding=6)
        paned.add(list_frame, weight=1)
        self._build_list_panel(list_frame)

        preview_frame = ttk.Frame(paned, padding=6)
        paned.add(preview_frame, weight=3)
        self._build_preview_panel(preview_frame)

        form_frame = ttk.Frame(paned, padding=6)
        paned.add(form_frame, weight=2)
        self._build_form_panel(form_frame)

        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom")

    def _build_list_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Raw scans").pack(anchor="w")
        self.tree = ttk.Treeview(parent, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        scrollbar.pack(fill="y", side="right")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill="x")
        ttk.Checkbutton(
            controls, text="Show bounding boxes", variable=self.show_boxes, command=self.draw_boxes
        ).pack(side="left")
        ttk.Button(controls, text="Scan with OCR", command=self.on_scan_ocr).pack(side="right")

        canvas_container = ttk.Frame(parent)
        canvas_container.pack(fill="both", expand=True, pady=6)
        self.canvas = Canvas(canvas_container, background="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

    def _build_form_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        row = 0

        ttk.Label(parent, text="Name").grid(row=row, column=0, sticky="w")
        row += 1
        self.name_text = Text(parent, height=2, wrap="word")
        self.name_text.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        row += 1

        ttk.Label(parent, text="Effect text").grid(row=row, column=0, sticky="w")
        row += 1
        self.effect_text = Text(parent, height=8, wrap="word")
        self.effect_text.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        row += 1

        ttk.Label(parent, text="Cost").grid(row=row, column=0, sticky="w")
        row += 1
        cost_row = ttk.Frame(parent)
        cost_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        cost_row.columnconfigure(0, weight=1)
        self.cost_scale = ttk.Scale(
            cost_row, from_=0, to=COST_MAX, variable=self.cost_var, command=self._on_cost_change
        )
        self.cost_scale.grid(row=0, column=0, sticky="ew")
        self.cost_label = ttk.Label(cost_row, text="0", width=3)
        self.cost_label.grid(row=0, column=1, padx=(6, 0))
        row += 1

        ttk.Label(parent, text="Layout").grid(row=row, column=0, sticky="w")
        row += 1
        layout_combo = ttk.Combobox(
            parent, textvariable=self.layout_var, values=["background", "hero"], state="readonly"
        )
        layout_combo.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        layout_combo.bind("<<ComboboxSelected>>", lambda e: (self.draw_boxes(), self._update_vp_display()))
        row += 1

        ttk.Label(parent, text="Faction").grid(row=row, column=0, sticky="w")
        row += 1
        faction_combo = ttk.Combobox(
            parent, textvariable=self.faction_var, values=FACTIONS, state="readonly"
        )
        faction_combo.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        row += 1

        ttk.Label(parent, text="Effect category (backgrounds only)").grid(row=row, column=0, sticky="w")
        row += 1
        effect_category_combo = ttk.Combobox(
            parent, textvariable=self.effect_category_var, values=["", *EFFECT_CATEGORIES], state="readonly"
        )
        effect_category_combo.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        effect_category_combo.bind("<<ComboboxSelected>>", lambda e: self._update_vp_display())
        row += 1

        # Not editable -- 1 VP for every background except victory_calc,
        # which is "X". Fix effect_category above if this looks wrong.
        vp_row = ttk.Frame(parent)
        vp_row.grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Label(vp_row, text="Victory points: ").pack(side="left")
        ttk.Label(vp_row, textvariable=self.vp_display_var, font=("Segoe UI", 9, "bold")).pack(side="left")
        row += 1

        ttk.Button(parent, text="Save", command=self.on_save).grid(row=row, column=0, sticky="ew", pady=(12, 0))

    # -- list / selection ----------------------------------------------------

    def refresh_processed_index(self) -> None:
        self.processed_by_source = {}
        if not PROCESSED_DIR.exists():
            return
        for results_path in PROCESSED_DIR.glob("*/results.json"):
            try:
                data = json.loads(results_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            source = data.get("source")
            if source:
                self.processed_by_source[source] = results_path.parent

    def refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.item_to_path = {}
        for path in self.raw_files:
            done = rel_display(path) in self.processed_by_source
            label = f"[done] {path.name}" if done else path.name
            iid = str(path)
            self.tree.insert("", "end", iid=iid, text=label)
            self.item_to_path[iid] = path

    def _on_select(self, _event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        path = self.item_to_path[selection[0]]
        self.load_scan(path)

    def load_scan(self, path: Path) -> None:
        image = cv2.imread(str(path))
        if image is None:
            messagebox.showerror("Could not read image", str(path))
            return
        self.current_path = path
        self.current_image_bgr = image

        # last_analysis (with its erase_mask) is only valid for the image it
        # was computed from -- selecting a different scan invalidates it.
        self.last_analysis = None
        self.last_analysis_path = None

        saved_dir = self.processed_by_source.get(rel_display(path))
        if saved_dir is not None:
            self._load_saved(saved_dir / "results.json")
            self.status_var.set(f"Loaded previously saved review from {rel_display(saved_dir)}")
        else:
            self._clear_form()
            self.status_var.set(f"Loaded {path.name}. Click 'Scan with OCR' to run extraction.")

        self.render_preview()

    def _clear_form(self) -> None:
        self.name_text.delete("1.0", "end")
        self.effect_text.delete("1.0", "end")
        self.cost_var.set(0)
        self.cost_label.config(text="0")
        self.faction_var.set("none")
        self.effect_category_var.set("")
        self.layout_var.set("background")
        self.last_boxes = {}
        self._update_vp_display()

    def _load_saved(self, results_path: Path) -> None:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        self.name_text.delete("1.0", "end")
        self.name_text.insert("1.0", data.get("name") or "")
        self.effect_text.delete("1.0", "end")
        self.effect_text.insert("1.0", data.get("effect_text") or "")
        self.layout_var.set(data.get("layout") or "background")
        self.faction_var.set(data.get("faction") or "none")
        self.effect_category_var.set(data.get("effect_category") or "")
        self.cost_var.set(data.get("cost") or 0)
        self.cost_label.config(text=str(int(self.cost_var.get())))
        self.last_boxes = {field: xywh_to_box(box) for field, box in (data.get("regions") or {}).items()}
        self._update_vp_display()

    def _update_vp_display(self) -> None:
        """1 VP for every background except victory_calc, which is "X" --
        see the module docstring in extract_artwork.py for the game rule."""
        if self.layout_var.get() != "background":
            self.vp_display_var.set("n/a (hero)")
        elif self.effect_category_var.get() == "victory_calc":
            self.vp_display_var.set("X")
        else:
            self.vp_display_var.set("1")

    # -- preview / bounding boxes --------------------------------------------

    def _ensure_analysis(self) -> dict:
        """analyze_card()'s result for the currently-loaded image, computing
        it fresh only if we don't already have one for this exact path (e.g.
        a previously-saved review was loaded without re-running OCR)."""
        if self.last_analysis is None or self.last_analysis_path != self.current_path:
            self.last_analysis = analyze_card(self.current_image_bgr)
            self.last_analysis_path = self.current_path
            self.last_boxes = self.last_analysis["boxes"]
        return self.last_analysis

    def render_preview(self) -> None:
        if self.current_image_bgr is None:
            return
        rgb = cv2.cvtColor(self.current_image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        max_w, max_h = 520, 760
        scale = min(max_w / w, max_h / h, 1.0)
        disp_w, disp_h = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(rgb, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        self.photo_image = ImageTk.PhotoImage(Image.fromarray(resized))
        self.display_size = (disp_w, disp_h)
        self.canvas.config(width=disp_w, height=disp_h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image, tags="preview")
        self.draw_boxes()

    def draw_boxes(self) -> None:
        self.canvas.delete("box")
        if not self.show_boxes.get() or self.current_image_bgr is None:
            return
        disp_w, disp_h = self.display_size
        for field, box in self.last_boxes.items():
            left, top, right, bottom = box
            color = BOX_COLORS.get(field, "red")
            self.canvas.create_rectangle(
                left * disp_w, top * disp_h, right * disp_w, bottom * disp_h,
                outline=color, width=2, tags="box",
            )
            self.canvas.create_text(
                left * disp_w + 4, top * disp_h + 4, text=field, anchor="nw",
                fill=color, font=("Segoe UI", 8, "bold"), tags="box",
            )

    # -- OCR ------------------------------------------------------------------

    def on_scan_ocr(self) -> None:
        if self.current_image_bgr is None:
            messagebox.showinfo("No scan selected", "Select a raw scan from the list first.")
            return
        self.status_var.set("Running OCR...")
        self.root.update_idletasks()
        try:
            analysis = analyze_card(self.current_image_bgr)
        except Exception as exc:
            messagebox.showerror("OCR failed", str(exc))
            self.status_var.set("OCR failed.")
            return

        self.last_analysis = analysis
        self.last_analysis_path = self.current_path
        self.last_boxes = analysis["boxes"]

        self.layout_var.set(analysis["layout"])
        self.faction_var.set(analysis["faction_tab"] or "none")
        self.effect_category_var.set(analysis["effect_category"] or "")

        self.name_text.delete("1.0", "end")
        self.name_text.insert("1.0", analysis["name"] or "")
        self.effect_text.delete("1.0", "end")
        self.effect_text.insert("1.0", analysis["effect_text"] or "")

        cost = parse_int(analysis["cost"])
        self.cost_var.set(min(cost, COST_MAX) if cost is not None else 0)
        self.cost_label.config(text=str(int(self.cost_var.get())))
        self._update_vp_display()

        self.draw_boxes()
        self.status_var.set(
            f"OCR done: layout={analysis['layout']} faction={analysis['faction_tab']} "
            "-- review the fields before saving."
        )

    def _on_cost_change(self, value: str) -> None:
        self.cost_label.config(text=str(round(float(value))))

    # -- save -------------------------------------------------------------

    def on_save(self) -> None:
        if self.current_path is None or self.current_image_bgr is None:
            messagebox.showinfo("No scan selected", "Select a raw scan from the list first.")
            return
        name = self.name_text.get("1.0", "end").strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a card name before saving.")
            return

        self.status_var.set("Building artwork...")
        self.root.update_idletasks()

        slug = slugify(name)
        out_dir = PROCESSED_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        # build_artwork needs the erase_mask, which is specific to this exact
        # image -- _ensure_analysis recomputes it if we don't already have
        # one (e.g. this scan was loaded from a saved review, never re-OCR'd).
        analysis = self._ensure_analysis()
        artwork_rgba = build_artwork(self.current_image_bgr, analysis)
        artwork_path = out_dir / "artwork.png"
        cv2.imwrite(str(artwork_path), artwork_rgba)

        victory_points = None
        if self.layout_var.get() == "background":
            victory_points = "X" if self.effect_category_var.get() == "victory_calc" else 1
        results = {
            "source": rel_display(self.current_path),
            "layout": self.layout_var.get(),
            "faction": self.faction_var.get().strip() or "none",
            "effect_category": self.effect_category_var.get().strip() or None,
            "name": name,
            "effect_text": self.effect_text.get("1.0", "end").strip(),
            "cost": round(self.cost_var.get()),
            "victory_points": victory_points,
            "regions": {field: box_to_xywh(box) for field, box in analysis["boxes"].items()},
            "artwork_path": rel_display(artwork_path),
        }
        (out_dir / "results.json").write_text(
            json.dumps(results, indent=4, ensure_ascii=False), encoding="utf-8"
        )

        self.refresh_processed_index()
        self.refresh_list()
        self.status_var.set(f"Saved {name!r} to {rel_display(out_dir)}")


def main() -> None:
    check_tesseract_available()
    root = Tk()
    ReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
