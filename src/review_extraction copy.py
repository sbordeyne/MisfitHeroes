"""Manually review/correct OCR results from extract_artwork.py and produce
final per-card assets.

Pick a raw scan, hit "Scan with OCR" (runs the exact same
classify/OCR pipeline as extract_artwork.py's analyze_card, on just that one
image), fix whatever the OCR got wrong, and "Save" to write:
  assets/processed/<slugified name>/artwork.png   -- artwork crop, background
                                                       keyed to transparent
  assets/processed/<slugified name>/results.json  -- card data + the
                                                       fractional {x,y,width,
                                                       height} box of every
                                                       field, for recomposing
                                                       cards later

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
    BACKGROUND_REGIONS,
    HERO_REGIONS,
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
VP_MAX = 20


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

        self.show_boxes = BooleanVar(value=True)
        self.layout_var = StringVar(value="background")
        self.faction_var = StringVar(value="none")
        self.effect_category_var = StringVar(value="")
        self.cost_var = DoubleVar(value=0)
        self.vp_var = DoubleVar(value=0)
        self.vp_is_x = BooleanVar(value=False)
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

        ttk.Label(parent, text="Victory points").grid(row=row, column=0, sticky="w")
        row += 1
        vp_row = ttk.Frame(parent)
        vp_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        vp_row.columnconfigure(0, weight=1)
        self.vp_scale = ttk.Scale(
            vp_row, from_=0, to=VP_MAX, variable=self.vp_var, command=self._on_vp_change
        )
        self.vp_scale.grid(row=0, column=0, sticky="ew")
        self.vp_label = ttk.Label(vp_row, text="0", width=3)
        self.vp_label.grid(row=0, column=1, padx=(6, 0))
        ttk.Checkbutton(
            vp_row, text="X (variable)", variable=self.vp_is_x, command=self._on_vp_x_toggle
        ).grid(row=0, column=2, padx=(6, 0))
        row += 1

        ttk.Label(parent, text="Layout").grid(row=row, column=0, sticky="w")
        row += 1
        layout_combo = ttk.Combobox(
            parent, textvariable=self.layout_var, values=["background", "hero"], state="readonly"
        )
        layout_combo.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        layout_combo.bind("<<ComboboxSelected>>", lambda e: self.draw_boxes())
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
        self.vp_var.set(0)
        self.vp_is_x.set(False)
        self.vp_scale.state(["!disabled"])
        self.cost_label.config(text="0")
        self.vp_label.config(text="0")
        self.faction_var.set("none")
        self.effect_category_var.set("")
        self.layout_var.set("background")

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
        vp = data.get("victory_points")
        if isinstance(vp, str) and vp.upper() == "X":
            self.vp_is_x.set(True)
            self.vp_scale.state(["disabled"])
        else:
            self.vp_is_x.set(False)
            self.vp_scale.state(["!disabled"])
            self.vp_var.set(vp or 0)
        self.vp_label.config(text=str(int(self.vp_var.get())))

    # -- preview / bounding boxes --------------------------------------------

    def current_regions(self) -> dict:
        return BACKGROUND_REGIONS if self.layout_var.get() == "background" else HERO_REGIONS

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
        for field, box in self.current_regions().items():
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

        vp_raw = analysis["victory_points"]
        if vp_raw and "x" in vp_raw.lower():
            self.vp_is_x.set(True)
            self.vp_scale.state(["disabled"])
        else:
            vp = parse_int(vp_raw)
            self.vp_is_x.set(False)
            self.vp_scale.state(["!disabled"])
            self.vp_var.set(min(vp, VP_MAX) if vp is not None else 0)
        self.vp_label.config(text=str(int(self.vp_var.get())))

        self.draw_boxes()
        self.status_var.set(
            f"OCR done: layout={analysis['layout']} faction={analysis['faction_tab']} "
            "-- review the fields before saving."
        )

    def _on_cost_change(self, value: str) -> None:
        self.cost_label.config(text=str(round(float(value))))

    def _on_vp_change(self, value: str) -> None:
        self.vp_label.config(text=str(round(float(value))))

    def _on_vp_x_toggle(self) -> None:
        self.vp_scale.state(["disabled" if self.vp_is_x.get() else "!disabled"])

    # -- save -------------------------------------------------------------

    def on_save(self) -> None:
        if self.current_path is None or self.current_image_bgr is None:
            messagebox.showinfo("No scan selected", "Select a raw scan from the list first.")
            return
        name = self.name_text.get("1.0", "end").strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a card name before saving.")
            return

        slug = slugify(name)
        out_dir = PROCESSED_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        regions = self.current_regions()
        artwork_rgba = build_artwork(self.current_image_bgr, regions)
        artwork_path = out_dir / "artwork.png"
        cv2.imwrite(str(artwork_path), artwork_rgba)

        victory_points = "X" if self.vp_is_x.get() else round(self.vp_var.get())
        results = {
            "source": rel_display(self.current_path),
            "layout": self.layout_var.get(),
            "faction": self.faction_var.get().strip() or "none",
            "effect_category": self.effect_category_var.get().strip() or None,
            "name": name,
            "effect_text": self.effect_text.get("1.0", "end").strip(),
            "cost": round(self.cost_var.get()),
            "victory_points": victory_points,
            "regions": {field: box_to_xywh(box) for field, box in regions.items()},
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
