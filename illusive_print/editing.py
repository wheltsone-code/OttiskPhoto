"""Frame gestures, size linking, history, and global/individual curve editing."""

import math
import tkinter as tk
from dataclasses import replace

from .color import IDENTITY, curve_lut
from .core import Correction, Rect, effective_correction, image_rect, load_source, page_items, rotation_turns, source_size, photo_slot
from .production_geometry import page_cells,spread_grid


class EditingMixin:
    def init_editing(self):
        self.global_curve = IDENTITY
        self._curves_editor = None
        self._undo_stack = []
        self._drag = None
        self._size_updating = False
        self._custom_initialized = False
        self._custom_ratio = 1.0
        self._color_syncing = False
        self._color_selection = None
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Control-Z>", self.undo)
        self.root.bind("<Control-KeyPress>", self.control_key)
        self.root.bind("<Escape>", self.cancel_drag)

    def control_key(self, event):
        # Windows reports a different keysym under a Cyrillic keyboard layout.
        # VK_Z=90 remains the same physical shortcut in either layout.
        if (str(event.keysym).lower() in ("z", "cyrillic_ya")
                or (self.root.tk.call("tk", "windowingsystem") == "win32" and event.keycode == 90)):
            return self.undo(event)

    def bind_editing(self):
        self.print_var.trace_add("write", self.custom_preset_changed)
        self.print_w_var.trace_add("write", lambda *_: self.dimension_changed("width"))
        self.print_h_var.trace_add("write", lambda *_: self.dimension_changed("height"))
        for variable,parameter in ((self.gamma_var,'gamma'),(self.saturation_var,'vibrance'),
                                   (self.temperature_var,'temperature'),(self.tint_var,'tint')):
            variable.trace_add('write',lambda *_, parameter=parameter:self.live_color_preview(parameter=parameter))

    def editing_photos(self):
        return [self.photos[i] for i in sorted(self.selected_rows) if 0<=i<len(self.photos)]

    def individual_editing(self):
        return any(p.correction is not None or p.curve is not None for p in self.editing_photos())

    def frame_snapshot(self, photos=None):
        return [(photo, photo.mode, photo.offset_x, photo.offset_y, photo.rotation, photo.zoom)
                for photo in (self.photos if photos is None else photos)]

    def remember(self, before):
        changed = any((p.mode, p.offset_x, p.offset_y, p.rotation, p.zoom) != (mode, x, y, rotation, zoom)
                      for p, mode, x, y, rotation, zoom in before)
        if changed:
            self._undo_stack.append(before)
            self._undo_stack = self._undo_stack[-100:]

    def undo(self, event=None):
        if self._drag:
            self.end_drag()
        if self._undo_stack:
            for photo, mode, x, y, rotation, zoom in self._undo_stack.pop():
                if any(photo is current for current in self.photos):
                    photo.mode, photo.offset_x, photo.offset_y, photo.rotation, photo.zoom = mode, x, y, rotation, zoom
            self.refresh()
        return "break"

    def begin_drag(self, event):
        self._drag = None
        if self._preview_pending:
            return
        if self.begin_print_swap(event): return
        if self.layout is None:
            return
        self.preview_canvas.focus_set()
        x = (event.x - self.preview_origin[0]) / self.preview_scale
        y = (event.y - self.preview_origin[1]) / self.preview_scale
        items = page_items(self.photos, self.layout, self.page)
        for slot, ((index, photo), cell) in enumerate(zip(items, page_cells(self.photos,self.layout,self.page))):
            if index < 0 and self.layout.mode=='booklet' and cell.contains(x,y):
                from .core import booklet_pages, spread_positions
                self.select_booklet_page(self.booklet_position_at(slot))
                return
            if index < 0 or not cell.contains(x, y):
                continue
            self._selected_instance = (self.page, slot)
            self.select_photo(index, keep_page=True,preserve_selection=index in self.selected_rows)
            original = photo
            photo, cell, autorotate = photo_slot(photo, cell, self.layout)
            info = source_size(photo)
            size = (info.width_px,info.height_px)
            if rotation_turns(size, cell, photo, autorotate) % 2:
                size = size[::-1]
            placed = image_rect(size, cell, photo)
            if cell.contains(x, y) and placed.contains(x, y):
                self._drag = {
                    "photo": original, "before": self.frame_snapshot([original]),
                    "start": (event.x, event.y), "offset": (photo.offset_x, photo.offset_y),
                    "travel": (abs(cell.width - placed.width) / 2, abs(cell.height - placed.height) / 2),
                    "scale": self.preview_scale,
                    "card_turned": self.layout.card_turned or bool(self.layout.mode=='booklet' and self.layout.booklet_page_size and spread_grid(self.layout)[4]),
                    'moved':False,
                }
                self.preview_canvas.configure(cursor="fleur")
            elif len(self.selected_rows)>1:
                self.select_photo(index,keep_page=True)
            return

    def drag_motion(self, event):
        if getattr(self,"_swap_from",None) is not None:
            self.print_swap_motion(event); return
        if not self._drag:
            return
        gesture = self._drag
        gesture['moved'] |= (event.x,event.y)!=gesture['start']
        photo = gesture["photo"]
        values = []
        for delta, initial, travel in zip((event.x - gesture["start"][0], event.y - gesture["start"][1]),
                                          gesture["offset"], gesture["travel"]):
            values.append(max(-1, min(1, initial + delta / (travel * gesture["scale"]))) if travel > 1e-8 else 0.0)
        photo.offset_x, photo.offset_y = (values[1], -values[0]) if gesture["card_turned"] else values
        self.draw_preview(fast=True)

    def end_drag(self, event=None):
        if self.end_print_swap(event): return
        if self._drag:
            clicked = self._drag['photo'] if not self._drag['moved'] else None
            self.remember(self._drag["before"])
            self._drag = None
            self.preview_canvas.configure(cursor="hand2")
            if clicked is not None and len(self.selected_rows)>1:
                index = next(i for i,p in enumerate(self.photos) if p is clicked)
                self.select_photo(index,keep_page=True)
            self.refresh()

    def cancel_drag(self, event=None):
        if getattr(self,'_swap_from',None) is not None:
            self._swap_from=None
            self.preview_canvas.grab_release()
            self.highlight_target(None)
            self.preview_canvas.configure(cursor='hand2')
        if self._drag:
            photo, mode, x, y, rotation, zoom = self._drag["before"][0]
            photo.mode, photo.offset_x, photo.offset_y, photo.rotation, photo.zoom = mode, x, y, rotation, zoom
            self._drag = None
            self.preview_canvas.configure(cursor="hand2")
            self.refresh()
        return "break"

    def reset_frame(self):
        group = self.editing_photos()
        if group:
            before = self.frame_snapshot(group)
            for photo in group:
                photo.reset_frame()
            self.remember(before)
            self.refresh()

    def zoom_photo(self, delta=10):
        if self.layout is None or not 0 <= self.selected < len(self.photos):
            return
        group = self.editing_photos()
        before = self.frame_snapshot(group)
        for photo in group:
            self._zoom_one(photo,delta)
        self.remember(before)
        self.refresh()

    def _zoom_one(self,photo,delta):
        cell = self.layout.cells()[0]
        if self.layout.card:
            cell = Rect(0, 0, self.layout.card.window_width, self.layout.card.window_height)
        info = source_size(photo)
        size = (info.width_px, info.height_px)
        if rotation_turns(size, cell, photo, self.layout.autorotate) % 2:
            size = size[::-1]
        old = image_rect(size, cell, photo)
        previous_zoom = photo.zoom
        photo.zoom = max(1.0, round(photo.zoom * 100 + delta) / 100)
        factor = photo.zoom / previous_zoom
        enlarged = image_rect(size, cell, photo)
        # Keep the source point under the viewport centre fixed while zooming.
        # Normalised offsets retain the existing drag limits in both modes.
        for attribute, previous, current, extent in (
                ("offset_x", old.width, enlarged.width, cell.width),
                ("offset_y", old.height, enlarged.height, cell.height)):
            travel = abs(extent - current)
            offset = getattr(photo, attribute) * abs(extent - previous) * factor / travel if travel > 1e-8 else 0.0
            setattr(photo, attribute, max(-1.0, min(1.0, offset)))

    def apply_crop_to_all(self):
        if 0 <= self.selected < len(self.photos):
            before = self.frame_snapshot()
            mode = self.photos[self.selected].mode
            for photo in self.photos:
                photo.mode = mode
            self.remember(before)
            self.refresh()

    def custom_preset_changed(self, *_args):
        if (self.mode_var.get() == "Задать размер фото" and not self._switching_mode
                and not self._size_updating and self.print_var.get() == "Свой размер"
                and not self._custom_initialized and self.selected >= 0):
            self.original_size()

    @staticmethod
    def size_text(value):
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")

    def original_size(self):
        if not 0 <= self.selected < len(self.photos):
            self.update_original_size_label()
            return
        info = source_size(self.photos[self.selected])
        ppi = int(self.output_ppi_var.get())
        width, height = info.physical_mm or (info.width_px * 25.4 / ppi, info.height_px * 25.4 / ppi)
        self._size_updating = True
        try:
            self.print_var.set("Свой размер")
            self.print_w_var.set(self.size_text(width))
            self.print_h_var.set(self.size_text(height))
            self.size_lock_var.set(True)
            self._custom_ratio = width / height
            self._custom_initialized = True
            self.update_original_size_label()
        finally:
            self._size_updating = False
        self.schedule_refresh()

    def update_original_size_label(self, *_):
        # Output density never resizes a manual value or preset. Recalculate
        # from upright source pixels only when Original size is invoked.
        self.ppi_var.set(f"Исходный размер при {self.output_ppi_var.get()} ppi")

    def dimension_changed(self, side):
        if (self._size_updating or self._switching_mode or self.mode_var.get() != "Задать размер фото"
                or self.print_var.get() != "Свой размер"):
            return
        self._custom_initialized = True
        if not self.size_lock_var.get():
            return
        variable = self.print_w_var if side == "width" else self.print_h_var
        try:
            value = self._number(variable)
            if not math.isfinite(value) or value <= 0:
                return
            ratio = self._custom_ratio
            self._size_updating = True
            other = self.print_h_var if side == "width" else self.print_w_var
            other.set(self.size_text(value / ratio if side == "width" else value * ratio))
        except (ValueError, OSError):
            pass
        finally:
            self._size_updating = False

    def active_color(self):
        global_color = replace(self.correction, curve=self.global_curve)
        if 0 <= self.selected < len(self.photos):
            return effective_correction(self.photos[self.selected], global_color)
        return global_color

    def active_curve(self):
        return self.active_color().curve

    def _migrate_legacy_colors(self):
        for photo in self.photos:
            if photo.correction is None and photo.curve is not None:
                photo.correction = replace(self.correction, curve=photo.curve)

    def sync_color_controls(self, force=False):
        self.correction = replace(self.correction, curve=self.global_curve)
        self._migrate_legacy_colors()
        photo = self.photos[self.selected] if 0 <= self.selected < len(self.photos) else None
        individual = self.individual_editing()
        self.individual_color_var.set(individual)
        self.individual_color_check.configure(state="normal" if photo else "disabled")
        self.color_scope_var.set(('Для выбранных фото' if len(self.editing_photos())>1 else 'Для выбранного фото') if individual else 'Для всех фото')
        key = (id(photo) if photo else None, individual,tuple(id(p) for p in self.editing_photos()))
        if force or key != self._color_selection:
            chosen = self.active_color()
            self._color_syncing = True
            try:
                self.temperature_var.set(self.size_text(chosen.temperature * 100))
                self.tint_var.set(self.size_text(chosen.tint * 100))
                self.saturation_var.set(chosen.vibrance * 100)
                self.gamma_var.set(f"{chosen.gamma:.2f}".replace(".", ","))
            finally:
                self._color_syncing = False
            self._color_selection = key
        for mode,button in self.to_buttons.items():
            button.configure(style="Chosen.TButton" if self.active_color().teal_orange==mode else "TButton")
        self._update_color_labels()
        self.update_mixed_color()

    def update_mixed_color(self):
        group = self.editing_photos()
        colors = [effective_correction(p,replace(self.correction,curve=self.global_curve)) for p in group]
        names = [label for attribute,label in (('temperature','Температура'),('tint','Оттенок'),('vibrance','Сочность'),
                                               ('gamma','Gamma'),('curve','Кривая RGB'))
                 if len({getattr(c,attribute) for c in colors})>1]
        self.mixed_color_var.set('Разные значения: '+', '.join(names) if names else '')
        if names:
            self.mixed_color_label.grid()
        else:
            self.mixed_color_label.grid_remove()

    def apply_color_changes(self,changes):
        if self.individual_editing():
            for photo in self.editing_photos():
                photo.correction = replace(effective_correction(photo,self.correction),**changes)
                photo.curve = photo.correction.curve
        else:
            self.correction = replace(self.correction,**changes)
            self.global_curve = self.correction.curve

    def set_individual_color(self, enabled):
        if not 0 <= self.selected < len(self.photos):
            self.individual_color_var.set(False)
            return
        for photo in self.editing_photos():
            if enabled and photo.correction is None:
                photo.correction = replace(self.correction, curve=photo.curve if photo.curve is not None else self.global_curve)
                photo.curve = photo.correction.curve
            elif not enabled:
                photo.correction = None
                photo.curve = None
        self.sync_color_controls(force=True)
        self.update_curve_badges()
        self.refresh()

    def set_individual_curve(self, enabled):
        # Compatibility with existing callers; there is only one UI switch.
        self.set_individual_color(enabled)

    def set_curve(self, points, final=False):
        points = tuple((int(x), int(y)) for x, y in points)
        curve_lut(points)
        self._migrate_legacy_colors()
        self.apply_color_changes({'curve':points})
        self.update_mixed_color()
        self.update_curve_badges()
        if final:
            self.refresh()
        else:
            self.live_color_preview()

    def reset_curve(self):
        self.set_curve(IDENTITY, final=True)

    def update_curve_badges(self):
        for index, badge in enumerate(self.curve_badges):
            own = self.photos[index].correction is not None or self.photos[index].curve is not None
            badge.configure(text="Своя кривая" if own else "")
            if own:
                badge.grid()
            else:
                badge.grid_remove()

    def read_color_controls(self):
        return Correction(round(float(self.saturation_var.get())) / 100,
                          self._number(self.gamma_var), self.active_curve(),
                          self._number(self.temperature_var) / 100, self._number(self.tint_var) / 100, self.active_color().teal_orange)

    def _update_color_labels(self):
        number = round(float(self.saturation_var.get()))
        self.saturation_label.configure(text=f"{number:+d}" if number else "0")
        self.gamma_label_var.set(f"{self.active_color().gamma:.2f}".replace(".", ","))

    def live_color_preview(self, *_args, parameter=None):
        if not hasattr(self, "preview_canvas") or self._closing or self._color_syncing:
            return
        try:
            self._migrate_legacy_colors()
            if parameter:
                variable = {'temperature':self.temperature_var,'tint':self.tint_var,
                            'gamma':self.gamma_var,'vibrance':self.saturation_var}[parameter]
                value = self._number(variable) / (1 if parameter=='gamma' else 100)
                self.apply_color_changes({parameter:value})
            self._update_color_labels()
            self.update_mixed_color()
            self.sync_fold_sections()
            if self.layout:
                self.draw_preview(fast=True)
            if self._curves_editor:
                self._curves_editor.sync()
        except (ValueError, tk.TclError, OSError):
            pass

    def commit_color_number(self, variable):
        try:
            self.read_color_controls()
        except (ValueError, tk.TclError):
            chosen = self.active_color()
            value = chosen.temperature if variable is self.temperature_var else chosen.tint
            self._color_syncing = True
            try:
                variable.set(self.size_text(value * 100))
            finally:
                self._color_syncing = False
        self.live_color_preview()
        self.refresh()

    def finish_color_preview(self, event=None):
        self.refresh()

    def reset_color(self):
        self.apply_color_changes({'temperature':0,'tint':0,'vibrance':0,'gamma':1,'teal_orange':'none'})
        self._color_syncing = True
        try:
            self.temperature_var.set("0")
            self.tint_var.set("0")
            self.saturation_var.set(0)
            self.gamma_var.set("1,00")
        finally:
            self._color_syncing = False
        self.live_color_preview()
        self.refresh()

    def open_curves(self):
        from .curves_editor import CurvesEditor
        if self._curves_editor and self._curves_editor.window.winfo_exists():
            self._curves_editor.window.lift()
        else:
            self._curves_editor = CurvesEditor(self)

