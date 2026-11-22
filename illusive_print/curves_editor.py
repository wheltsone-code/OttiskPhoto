"""Non-modal composite RGB editor with shape-preserving 256-entry LUT."""

import math
import tkinter as tk
from tkinter import ttk

from PIL import ImageOps

from .color import curve_lut
from .core import Correction, correct_image, load_source
from .widgets import CapsuleButton
from .metadata import set_icon
from .i18n import localize_tree


class CurvesEditor:
    LEFT, TOP, SIZE = 33, 12, 256

    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("Кривые RGB")
        set_icon(self.window)
        self.window.transient(app.root)  # Deliberately no grab/wait_window.
        self.window.resizable(False, False)
        self.window.configure(bg="#faf8fa")
        self.window.geometry(f"334x454+{app.root.winfo_rootx() + max(260, app.root.winfo_width() // 2 - 70)}+{app.root.winfo_rooty() + 120}")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(self.window, text="Кривые RGB", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=14, pady=(10, 5))
        ttk.Label(self.window, textvariable=app.color_scope_var, style="Muted.TLabel").pack(anchor="w", padx=14)
        self.gamma_var = tk.StringVar()
        ttk.Label(self.window, textvariable=self.gamma_var, style="Muted.TLabel").pack(anchor="w", padx=14)
        self.canvas = tk.Canvas(self.window, width=320, height=294, bg="#faf8fa", highlightthickness=0, takefocus=True)
        self.canvas.pack(padx=6)
        ttk.Label(self.window, text="ЛКМ: добавить/двигать · ПКМ или Delete: удалить",
                  font=("Segoe UI", 8), foreground="#827887").pack()
        buttons = ttk.Frame(self.window, padding=(12, 8))
        buttons.pack(fill="x")
        CapsuleButton(buttons, text="Сбросить кривую", command=app.reset_curve).pack(side="left", fill="x", expand=True, padx=(0, 8))
        CapsuleButton(buttons, text="Готово", style="Accent.TButton", command=self.close).pack(side="right")
        self.canvas.bind("<Button-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Button-3>", self.delete_point)
        self.canvas.bind("<Delete>", self.delete_point)
        self.canvas.bind("<BackSpace>", self.delete_point)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, 1), ("Down", 0, -1)):
            self.canvas.bind(f"<{key}>", lambda event, x=dx, y=dy: self.nudge(x, y))
        self.points = app.active_curve()
        self.selected = None
        self.dragging = False
        self.histogram = [0] * 256
        self.photo_key = None
        self.sync()
        localize_tree(self.window)

    def close(self):
        self.app._curves_editor = None
        self.window.destroy()

    def sync(self):
        selected = 0 <= self.app.selected < len(self.app.photos)
        photo = self.app.photos[self.app.selected] if selected else None
        active = self.app.active_color()
        key = (photo.path, photo.pdf_page, active.vibrance, active.gamma, active.temperature, active.tint) if photo else None
        if key != self.photo_key:
            self.dragging, self.selected = False, None
            self.photo_key = key
            try:
                if key:
                    from .preview import load_preview_source
                    small = ImageOps.contain(load_preview_source(photo), (512, 512))
                    before_curve = correct_image(small, Correction(active.vibrance, active.gamma,
                                                 temperature=active.temperature, tint=active.tint))
                    self.histogram = before_curve.convert("L").histogram()
                else:
                    self.histogram = [0] * 256
            except OSError:
                self.histogram = [0] * 256
        if not self.dragging:
            self.points = self.app.active_curve()
        gamma = active.gamma
        self.gamma_var.set(f"Gamma: {gamma:.2f}".replace(".", ",") if abs(gamma - 1) > .0001 else "")
        self.draw()

    def to_canvas(self, x, y):
        return self.LEFT + x * self.SIZE / 255, self.TOP + (255 - y) * self.SIZE / 255

    def from_canvas(self, x, y):
        return (round(max(0, min(255, (x - self.LEFT) * 255 / self.SIZE))),
                round(max(0, min(255, 255 - (y - self.TOP) * 255 / self.SIZE))))

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        left, top, size = self.LEFT, self.TOP, self.SIZE
        canvas.create_rectangle(left, top, left + size, top + size, fill="white", outline="#a8a1ad")
        maximum = max(self.histogram) or 1
        polygon = [left, top + size]
        for x in range(256):
            height = math.sqrt(self.histogram[x] / maximum) * size * .38
            polygon.extend((left + x * size / 255, top + size - height))
        polygon.extend((left + size, top + size))
        canvas.create_polygon(*polygon, fill="#d9d7dc", outline="")
        for value in (0, 64, 128, 192, 255):
            x, y = self.to_canvas(value, value)
            canvas.create_line(x, top, x, top + size, fill="#dedbe1")
            canvas.create_line(left, y, left + size, y, fill="#dedbe1")
            canvas.create_text(x, top + size + 12, text=str(value), font=("Segoe UI", 8), fill="#766c7d")
            canvas.create_text(left - 7, y, text=str(value), anchor="e", font=("Segoe UI", 8), fill="#766c7d")
        canvas.create_line(left, top + size, left + size, top, fill="#b8b0bf", dash=(4, 4))
        line = []
        for x, y in enumerate(curve_lut(self.points)):
            line.extend(self.to_canvas(x, y))
        canvas.create_line(*line, fill="#db3d78", width=2)
        for index, (x, y) in enumerate(self.points):
            cx, cy = self.to_canvas(x, y)
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="white" if index == self.selected else "#db3d78",
                               outline="#db3d78", width=2)

    def nearest(self, event):
        distances = [(math.dist(self.to_canvas(x, y), (event.x, event.y)), i) for i, (x, y) in enumerate(self.points)]
        distance, index = min(distances)
        return index if distance <= 10 else None

    def press(self, event):
        if not self.LEFT - 3 <= event.x <= self.LEFT + self.SIZE + 3 or not self.TOP - 3 <= event.y <= self.TOP + self.SIZE + 3:
            return
        self.canvas.focus_set()
        self.selected = self.nearest(event)
        if self.selected is None:
            x, y = self.from_canvas(event.x, event.y)
            points = list(self.points)
            existing = next((i for i, point in enumerate(points) if point[0] == x), None)
            if existing is None:
                points.append((x, y))
                points.sort()
                self.selected = points.index((x, y))
                self.points = tuple(points)
            else:
                self.selected = existing
        self.dragging = True
        self.motion(event)

    def motion(self, event):
        if not self.dragging or self.selected is None:
            return
        x, y = self.from_canvas(event.x, event.y)
        points = list(self.points)
        index = self.selected
        minimum = points[index - 1][0] + 1 if index else 0
        maximum = points[index + 1][0] - 1 if index < len(points) - 1 else 255
        x = max(minimum, min(maximum, x))
        points[index] = (x, y)
        self.points = tuple(points)
        self.app.set_curve(self.points)
        self.draw()

    def release(self, event=None):
        if self.dragging:
            self.dragging = False
            self.app.set_curve(self.points, final=True)

    def delete_point(self, event=None):
        index = self.nearest(event) if event and getattr(event, "num", None) == 3 else self.selected
        if index is not None and 0 < index < len(self.points) - 1:
            self.points = tuple(point for i, point in enumerate(self.points) if i != index)
            self.selected = None
            self.app.set_curve(self.points, final=True)
            self.draw()
        return "break"

    def nudge(self, dx, dy):
        if self.selected is not None:
            x, y = self.points[self.selected]
            cx, cy = self.to_canvas(x + dx, y + dy)
            self.dragging = True
            self.motion(type("Point", (), {"x": cx, "y": cy})())
            self.release()
        return "break"
