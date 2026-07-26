"""Manually review/correct OCR results from extract_artwork.py and produce
final per-card assets.

Pick a raw scan, hit "Scan with OCR" (runs the exact same detect+OCR pipeline
as extract_artwork.py's analyze_card, on just that one image -- badges/tab/
text boxes are detected per-card, not looked up from a fixed template; see
that module's docstring), fix whatever it got wrong -- including dragging a
box's corners/edges to fit, if the detected one is off -- and "Save" to write:
  assets/processed/<slug>/<slug>.png       -- standardized artwork crop,
                                               backdrop removed via GrabCut,
                                               badges/tab erased
  assets/processed/<slug>/results.json     -- card data + the fractional
                                               {x,y,width,height} box of every
                                               detected field, for recomposing
                                               cards later

Saving runs on a background thread (GrabCut is slow enough to otherwise
freeze the window for a few seconds) with a progress bar tracking each step;
the UI stays responsive but the Save button is disabled until it finishes.

Re-selecting a raw scan that's already been saved reloads its saved values
(rather than blanking the form), so a review pass can be stopped and resumed.

Run with: python src/review_extraction.py
"""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import unicodedata
from pathlib import Path
from tkinter import BooleanVar, DoubleVar, StringVar, Tk, Canvas, Text, messagebox
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_artwork import (  # noqa: E402
    EFFECT_CATEGORY_HUES,
    PROJECT_ROOT,
    RAW_DIR,
    analyze_card,
    build_artwork,
    check_tesseract_available,
    find_raw_scans,
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

# "artwork" is derived from the card's aspect ratio (see ARTWORK_HEIGHT_FRACTION
# in extract_artwork.py), not something to hand-tune per card, so it's the one
# box excluded from dragging.
EDITABLE_BOX_FIELDS = {"cost", "victory_points", "faction_tab", "effect_category", "name", "effect"}
HANDLE_RADIUS = 6  # canvas px; corner-hit tolerance for starting a resize drag

PREVIEW_MAX_W = 680
PREVIEW_MAX_H = 900


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


def rebuild_erase_mask(image_shape: tuple, boxes: dict) -> np.ndarray:
    """Full-resolution erase mask built fresh from whatever boxes are
    CURRENTLY shown (auto-detected, manually dragged, or reloaded from a
    saved review) -- so a manual correction actually changes what gets
    erased from the artwork, not just what the JSON reports. This trades the
    precise faction-tab contour (its pointed tip corners) for a plain
    rectangle at save time; the tradeoff is intentional, since a rectangle is
    the only shape a drag-to-resize UI can express, and it's still a tight
    fit around the same contour's bounding box, not the old oversized guess."""
    h, w = image_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for field in ("cost", "victory_points", "faction_tab"):
        box = boxes.get(field)
        if box is None:
            continue
        left, top, right, bottom = box
        x1, y1 = max(int(left * w), 0), max(int(top * h), 0)
        x2, y2 = min(int(right * w), w), min(int(bottom * h), h)
        mask[y1:y2, x1:x2] = 255
    return mask


class ReviewApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("Misfit Heroes -- card extraction review")
        root.geometry("1650x950")
        root.minsize(1200, 720)

        self.raw_files: list[Path] = find_raw_scans(RAW_DIR)
        self.item_to_path: dict[str, Path] = {}
        self.processed_by_source: dict[str, Path] = {}

        self.current_path: Path | None = None
        self.current_image_bgr = None
        self.photo_image = None
        self.display_size = (0, 0)

        # Boxes are detected per-card now (not a fixed layout template), so
        # they're only known once analyze_card has actually run on this image
        # -- either via "Scan with OCR", or reconstructed from a
        # previously-saved review's regions. Manual corrections made by
        # dragging a box on the canvas (see _on_canvas_*) land here directly,
        # and Save rebuilds the erase mask from whatever's currently here
        # (see rebuild_erase_mask), so edits always take effect.
        self.last_boxes: dict = {}
        self.drag_state: dict | None = None

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
        self.progress_step_var = StringVar(value="")
        self.save_queue: queue.Queue | None = None

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

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", side="bottom")
        self.progress_bar = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x", side="top", padx=4, pady=(4, 0))
        progress_label = ttk.Label(bottom, textvariable=self.progress_step_var, anchor="w")
        progress_label.pack(fill="x", side="top", padx=4)
        status_bar = ttk.Label(bottom, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="top")

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
        ttk.Label(controls, text="(drag a box's corners to resize, its middle to move)").pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(controls, text="Scan with OCR", command=self.on_scan_ocr)
        self.scan_button.pack(side="right")

        canvas_container = ttk.Frame(parent)
        canvas_container.pack(fill="both", expand=True, pady=6)
        self.canvas = Canvas(canvas_container, background="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

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

        self.save_button = ttk.Button(parent, text="Save", command=self.on_save)
        self.save_button.grid(row=row, column=0, sticky="ew", pady=(12, 0))

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

    def render_preview(self) -> None:
        if self.current_image_bgr is None:
            return
        rgb = cv2.cvtColor(self.current_image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = min(PREVIEW_MAX_W / w, PREVIEW_MAX_H / h, 1.0)
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
            x1, y1, x2, y2 = left * disp_w, top * disp_h, right * disp_w, bottom * disp_h
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, tags="box")
            self.canvas.create_text(
                x1 + 4, y1 + 4, text=field, anchor="nw",
                fill=color, font=("Segoe UI", 8, "bold"), tags="box",
            )
            if field in EDITABLE_BOX_FIELDS:
                r = HANDLE_RADIUS
                for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                    self.canvas.create_rectangle(
                        cx - r, cy - r, cx + r, cy + r,
                        fill=color, outline="white", width=1, tags="box",
                    )

    # -- manual box editing ---------------------------------------------------

    def _on_canvas_press(self, event) -> None:
        if not self.show_boxes.get() or not self.last_boxes:
            return
        disp_w, disp_h = self.display_size
        x, y = event.x, event.y

        for field in EDITABLE_BOX_FIELDS:
            box = self.last_boxes.get(field)
            if box is None:
                continue
            left, top, right, bottom = box
            x1, y1, x2, y2 = left * disp_w, top * disp_h, right * disp_w, bottom * disp_h
            for corner, (cx, cy) in (
                ("nw", (x1, y1)), ("ne", (x2, y1)), ("sw", (x1, y2)), ("se", (x2, y2))
            ):
                if abs(x - cx) <= HANDLE_RADIUS and abs(y - cy) <= HANDLE_RADIUS:
                    self.drag_state = {"field": field, "mode": "resize", "corner": corner}
                    return

        for field in EDITABLE_BOX_FIELDS:
            box = self.last_boxes.get(field)
            if box is None:
                continue
            left, top, right, bottom = box
            x1, y1, x2, y2 = left * disp_w, top * disp_h, right * disp_w, bottom * disp_h
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.drag_state = {"field": field, "mode": "move", "start_mouse": (x, y), "start_box": box}
                return

        self.drag_state = None

    def _on_canvas_drag(self, event) -> None:
        if self.drag_state is None:
            return
        disp_w, disp_h = self.display_size
        field = self.drag_state["field"]

        if self.drag_state["mode"] == "resize":
            left, top, right, bottom = self.last_boxes[field]
            nx = min(max(event.x / disp_w, 0.0), 1.0)
            ny = min(max(event.y / disp_h, 0.0), 1.0)
            corner = self.drag_state["corner"]
            if corner == "nw":
                left, top = nx, ny
            elif corner == "ne":
                right, top = nx, ny
            elif corner == "sw":
                left, bottom = nx, ny
            else:
                right, bottom = nx, ny
            left, right = min(left, right), max(left, right)
            top, bottom = min(top, bottom), max(top, bottom)
        else:
            start_x, start_y = self.drag_state["start_mouse"]
            sl, st, sr, sb = self.drag_state["start_box"]
            box_w, box_h = sr - sl, sb - st
            dx = (event.x - start_x) / disp_w
            dy = (event.y - start_y) / disp_h
            left = min(max(sl + dx, 0.0), 1.0 - box_w)
            top = min(max(st + dy, 0.0), 1.0 - box_h)
            right, bottom = left + box_w, top + box_h

        self.last_boxes[field] = (left, top, right, bottom)
        self.draw_boxes()

    def _on_canvas_release(self, _event) -> None:
        self.drag_state = None

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
        if "artwork" not in self.last_boxes:
            messagebox.showwarning("Not scanned yet", "Click 'Scan with OCR' before saving.")
            return
        if self.save_queue is not None:
            return  # a save is already in flight

        victory_points = None
        if self.layout_var.get() == "background":
            victory_points = "X" if self.effect_category_var.get() == "victory_calc" else 1

        # Everything the worker thread needs, read from Tk state here on the
        # main thread -- Tk variables/widgets aren't safe to touch off-thread.
        slug = slugify(name)
        worker_kwargs = dict(
            image_bgr=self.current_image_bgr,
            boxes=dict(self.last_boxes),
            name=name,
            slug=slug,
            out_dir=PROCESSED_DIR / slug,
            source=rel_display(self.current_path),
            layout=self.layout_var.get(),
            faction=self.faction_var.get().strip() or "none",
            effect_category=self.effect_category_var.get().strip() or None,
            effect_text=self.effect_text.get("1.0", "end").strip(),
            cost=round(self.cost_var.get()),
            victory_points=victory_points,
        )

        self.save_queue = queue.Queue()
        self.save_button.state(["disabled"])
        self.scan_button.state(["disabled"])
        self.progress_bar["value"] = 0
        self.progress_step_var.set("Starting...")
        self.status_var.set(f"Saving {name!r}...")

        threading.Thread(
            target=self._save_worker, kwargs={**worker_kwargs, "progress_q": self.save_queue}, daemon=True
        ).start()
        self.root.after(80, self._poll_save_queue)

    @staticmethod
    def _save_worker(
        *, image_bgr, boxes, name, slug, out_dir, source, layout, faction, effect_category,
        effect_text, cost, victory_points, progress_q: queue.Queue,
    ) -> None:
        """Runs off the main thread -- must not touch any Tk widget/variable,
        only the plain values it was handed and the queue to report back on."""
        try:
            progress_q.put(("step", "Preparing regions", 5))
            analysis = {"boxes": boxes, "erase_mask": rebuild_erase_mask(image_bgr.shape, boxes)}

            def on_step(label: str) -> None:
                progress_q.put(("step", label, None))

            artwork_rgba = build_artwork(image_bgr, analysis, on_step=on_step)

            progress_q.put(("step", "Writing artwork file", 88))
            out_dir.mkdir(parents=True, exist_ok=True)
            artwork_path = out_dir / f"{slug}.png"
            cv2.imwrite(str(artwork_path), artwork_rgba)

            progress_q.put(("step", "Writing results.json", 95))
            results = {
                "source": source,
                "layout": layout,
                "faction": faction,
                "effect_category": effect_category,
                "name": name,
                "effect_text": effect_text,
                "cost": cost,
                "victory_points": victory_points,
                "regions": {field: box_to_xywh(box) for field, box in boxes.items()},
                "artwork_path": rel_display(artwork_path),
            }
            (out_dir / "results.json").write_text(
                json.dumps(results, indent=4, ensure_ascii=False), encoding="utf-8"
            )

            progress_q.put(("done", rel_display(out_dir), name))
        except Exception as exc:
            progress_q.put(("error", str(exc)))

    def _poll_save_queue(self) -> None:
        q = self.save_queue
        if q is None:
            return
        try:
            while True:
                msg = q.get_nowait()
                kind = msg[0]
                if kind == "step":
                    _, label, pct = msg
                    self.progress_step_var.set(label)
                    if pct is not None:
                        self.progress_bar["value"] = pct
                    else:
                        self.progress_bar["value"] = min(self.progress_bar["value"] + 12, 88)
                elif kind == "done":
                    _, out_dir_str, saved_name = msg
                    self.progress_bar["value"] = 100
                    self.progress_step_var.set("Done.")
                    self.save_queue = None
                    self.save_button.state(["!disabled"])
                    self.scan_button.state(["!disabled"])
                    self.refresh_processed_index()
                    self.refresh_list()
                    self.status_var.set(f"Saved {saved_name!r} to {out_dir_str}")
                    return
                else:  # "error"
                    _, err = msg
                    self.progress_step_var.set("Failed.")
                    self.save_queue = None
                    self.save_button.state(["!disabled"])
                    self.scan_button.state(["!disabled"])
                    self.status_var.set("Save failed.")
                    messagebox.showerror("Save failed", err)
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll_save_queue)


def main() -> None:
    check_tesseract_available()
    root = Tk()
    ReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
