"""Russian Tk/ttk desktop interface for Оттиск Фото."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from .i18n import filedialog, messagebox, translate, localize_tree, load_preferences, save_preferences

from PIL import Image, ImageOps, ImageTk

from .core import (
    Correction, EdgeInsets, Layout, PAPERS, PRINT_SIZES, Photo, SUPPORTED,
    export_pdf, first_print_index, load_source, page_count, page_items,
    booklet_pages, spread_positions, page_labels, print_count, render_page, set_all_modes, effective_ppi, CARD_TEMPLATES, CardTemplate, photo_slot, validate_output, PDFReplaceError,
)
from .editing import EditingMixin
from .production_ui import ProductionMixin
from .production_geometry import page_cells,fold_guides
from .duplex_ui import FoldingMixin
from .round_scrollbar import RoundScrollbar
from .async_preview import AsyncPreviewMixin
from .preview import PreviewRenderer, load_preview_source
from .widgets import CapsuleButton, NumberSpin, TickScale, ToolTip, ellipsize, RoundedCombo, CheckMark, FoldSection, LockButton
from .metadata import APP_NAME, VERSION, set_icon, ASSETS


PINK = "#f53286"
BG = "#faf8fa"
INK = "#20232b"
MUTED = "#737782"


class IllusivePrintApp(ProductionMixin, AsyncPreviewMixin, FoldingMixin, EditingMixin):
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.preferences = load_preferences()
        root._translate = self.display_text
        root.title(APP_NAME)
        set_icon(root)
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(1260, screen_w - 40), min(860, screen_h - 90)
        root.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+20")
        root.minsize(1080, 640)
        root.configure(bg=BG)
        self.photos: list[Photo] = []
        self.selected = -1
        self.selected_rows = set()
        self.selection_anchor = None
        self._selected_instance = None
        self.page = 0
        self.layout: Layout | None = None
        self.correction = Correction()
        self.preview_before = False
        self.preview_image: ImageTk.PhotoImage | None = None
        self._preview_renderer = PreviewRenderer()
        self.init_async_preview()
        self._preview_display_structure = None
        self.preview_origin = (0.0, 0.0)
        self.preview_scale = 1.0
        self.sheet_zoom = 1.0
        self.sheet_pan = (0.0, 0.0)
        self._sheet_drag = None
        self.thumbnail_widgets: list[tuple[tk.Widget, ...]] = []
        self.thumbnail_images: list[ImageTk.PhotoImage] = []
        self.curve_badges: list[tk.Label] = []
        self.copy_vars: list[tk.StringVar] = []
        self.copy_entries: list[ttk.Entry] = []
        self.copy_traces: list[str] = []
        self.copy_buttons: list[tuple[CapsuleButton, CapsuleButton]] = []
        self.preview_driver_margins: EdgeInsets | None = None
        self._refresh_job: str | None = None
        self._export_results: queue.Queue[tuple[bool, str | PDFReplaceError]] = queue.Queue()
        self._exporting = False
        self._pending_pdf = None
        self._pdf_recovery_window = None
        self._viewer_pdf: Path | None = None
        self._print_dialog = None
        self._closing = False
        root.bind("<Destroy>", self._on_destroy, add=True)
        self._style()
        self._variables()
        self.init_editing()
        self._build()
        self.unit_fields = [*self.paper_entries, *self.print_entries, *self.card_custom_entries,
                            self.margin_entry, self.gap_entry, self.trim_entry,*self.production_fields]
        for field in self.unit_fields:
            field.bind_units(self)
        self.paper_combo.format_value = self.paper_caption
        self.paper_combo.format_popup_value = lambda key: self.format_preset(key, PAPERS)
        self.print_combo.format_value = lambda key: self.format_preset(key, PRINT_SIZES)
        self.units_combo.format_value = lambda key: ({"mm": "mm", "in": "in"} if self.language_var.get() == "English"
                                                    else {"mm": "мм", "in": "дюймы"})[key]
        self.units_combo._literal_text = True
        ToolTip(self.paper_combo, lambda: self.format_preset(self.paper_var.get(), PAPERS))
        ToolTip(self.print_combo, lambda: self.format_preset(self.print_var.get(), PRINT_SIZES))
        self._bind_settings()
        self.bind_editing()
        self.refresh()

        self.explorer_drop = None
        if sys.platform == 'win32':
            from .file_drop import ExplorerDrop
            self.explorer_drop = ExplorerDrop(root, self.drop_paths)
            self.explorer_drop.register(self.preview_canvas)
            self.explorer_drop.register(self.library_canvas)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.option_add("*Font", ("Segoe UI", 10))
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Heading.TLabel", font=("Segoe UI", 11, "bold"), foreground="#9b2454")
        style.configure("TButton", padding=(10, 6), background="#ffffff", bordercolor="#d6d2d8")
        style.map("TButton", background=[("active", "#f3edf1")])
        style.configure("Accent.TButton", background=PINK, foreground="white", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#dc2473"), ("disabled", "#edb5cc")],
                  foreground=[("disabled", "#ffffff")])
        style.configure("Chosen.TButton", background="#ffe0ed", foreground="#ba145d")
        style.map("Chosen.TButton", background=[("active", "#ffd0e3")])
        style.configure("TLabelframe", background=BG, bordercolor="#ded9df")
        style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 10, "bold"))
        style.configure("TCombobox", padding=3)
        style.configure("Slim.Vertical.TScrollbar", width=6, arrowsize=6)
        style.configure("TEntry", padding=3)
        style.configure("Horizontal.TScale", background=BG, troughcolor="#ddd5dd")

    def display_text(self, text):
        language = "en" if hasattr(self, "language_var") and self.language_var.get() == "English" else "ru"
        units = "in" if hasattr(self, "unit_var") and self.unit_var.get() == "in" else "mm"
        return translate(text, language, units)

    def format_preset(self, key, presets):
        if key not in presets:
            return self.display_text(key)
        w, h = presets[key]
        name = f"{key} · " if presets is PAPERS or key in ("A4", "A3", "US Letter", "4 × 6″", "5 × 7″", "8 × 10″") else ""
        return self.display_text(f"{name}{w:g} × {h:g} мм / {w/25.4:.2f} × {h/25.4:.2f} in")

    def paper_caption(self, key):
        if key not in PAPERS:
            return self.display_text(key)
        w, h = PAPERS[key]
        name = f"{key} · " if key in ("A4", "A3", "US Letter") else ""
        return self.display_text(f"{name}{w:g} × {h:g} мм")

    def presentation_changed(self, *_):
        # Changing presentation never writes a rounded display back to the model.
        for field in self.unit_fields:
            field.update_unit_display()
        self.language_flag.configure(image=self.language_icons['en' if self.language_var.get() == 'English' else 'ru'])
        if self.selected < 0:
            self.selected_var.set(self.display_text("Выберите снимок слева или на листе"))
        localize_tree(self.root)
        if self.layout:
            self.draw_preview(fast=True)
        try:
            save_preferences("en" if self.language_var.get() == "English" else "ru",
                             "in" if self.unit_var.get() == "in" else "mm")
        except OSError as error:
            self.status_var.set(str(error))

    def _on_destroy(self, event):
        if event.widget == self.root:
            self._closing = True
            self.close_async_preview()
            if self._library_scroll_job:self.root.after_cancel(self._library_scroll_job)
            if self._pending_pdf:
                self._pending_pdf.cleanup()
            if self._refresh_job:
                self.root.after_cancel(self._refresh_job)
                self._refresh_job = None
            # Trace callbacks retain the app after its window is destroyed.
            # Release owned Tcl variables here, on the Tk thread, rather than
            # letting cyclic GC finalize them on a preview worker later.
            def release_variables(value):
                if isinstance(value, tk.Variable):
                    if value._tk is not None:
                        value.__del__()
                        value._tk = None
                elif isinstance(value, dict):
                    for item in value.values(): release_variables(item)
                elif isinstance(value, (list, tuple)):
                    for item in value: release_variables(item)
            for value in tuple(vars(self).values()):
                release_variables(value)

    def _legacy_variables(self) -> None:
        self.language_var = tk.StringVar(value="English" if self.preferences["language"] == "en" else "Русский")
        self.unit_var = tk.StringVar(value=self.preferences["units"])
        self.print_sequence = ()
        self.panel_ids = [None]*4
        self.booklet_cover_ids = [None,None]
        self.booklet_interior_ids = []
        self._booklet_seen = set()
        self._booklet_initialized = False
        self.booklet_leaves = []
        self._booklet_cards = []
        self._booklet_card_key = None
        self._booklet_selected = None
        self._target_images = {}
        self._library_scroll_job = None
        self.center_line_var = tk.StringVar(value="Нет")
        self.fold_marks_var = tk.StringVar(value="Нет")
        self.fold_side_var = tk.StringVar(value="Обе")
        self.mode_var = tk.StringVar(value="Разделить лист")
        self.paper_var = tk.StringVar(value="A4")
        self.orientation_var = tk.StringVar(value="Книжная")
        self.paper_w_var = tk.StringVar(value="210")
        self.paper_h_var = tk.StringVar(value="297")
        self.count_var = tk.StringVar(value="1")
        self.margin_var = tk.StringVar(value="0")
        self.gap_var = tk.StringVar(value="0")
        self.print_var = tk.StringVar(value="Свой размер")
        self.print_w_var = tk.StringVar(value="100")
        self.print_h_var = tk.StringVar(value="150")
        self.size_lock_var = tk.BooleanVar(value=True)
        self.autorotate_var = tk.BooleanVar(value=True)
        self.ppi_var = tk.StringVar(value="Исходный размер при 300 ppi")
        self.saturation_var = tk.DoubleVar(value=0.0)
        self.temperature_var = tk.StringVar(value="0")
        self.tint_var = tk.StringVar(value="0")
        self.individual_color_var = tk.BooleanVar(value=False)
        self.color_scope_var = tk.StringVar(value="Для всех фото")
        self.gamma_var = tk.StringVar(value="1,00")
        self.gamma_label_var = tk.StringVar(value="1,00")
        self.output_ppi_var = tk.StringVar(value="300")
        self.quality_var = tk.StringVar()
        self.status_var = tk.StringVar(value="JPG, JPEG и PNG · исходники остаются без изменений")
        self.counter_var = tk.StringVar(value="0 отпечатков · 0 листов")
        self.page_var = tk.StringVar(value="Лист 0 из 0")
        self.size_hint_var = tk.StringVar()
        self.selected_var = tk.StringVar(value="Выбранное фото")
        self.selection_title_var = tk.StringVar(value='Выбранное фото')
        self.mixed_color_var = tk.StringVar()
        self.capacity_var = tk.StringVar()
        self.occupancy_var = tk.StringVar()
        self.zoom_var = tk.StringVar(value="100%")
        self.sheet_zoom_var = tk.StringVar(value="100%")
        self.align_x_var = tk.StringVar(value="center")
        self.align_y_var = tk.StringVar(value="center")
        self.keep_positions_var = tk.BooleanVar(value=False)
        self.placement_var = tk.StringVar(value="Авто")
        self.card_var = tk.StringVar(value="Instax Mini")
        self.card_w_var = tk.StringVar(value="54")
        self.card_h_var = tk.StringVar(value="86")
        self.window_w_var = tk.StringVar(value="46")
        self.window_h_var = tk.StringVar(value="62")
        self.window_top_var = tk.StringVar(value="4")
        self.window_left_var = tk.StringVar(value="4")
        self.card_hint_var = tk.StringVar()
        self.trim_var = tk.StringVar(value="Нет")
        self.trim_inset_var = tk.StringVar(value="0")
        self.mark_inset_var = tk.StringVar(value="2")
        self.line_inset_var = tk.StringVar(value="0")
        self.trim_hint_var = tk.StringVar()
        self._mode_vars = {
            "paper": self.paper_var, "orientation": self.orientation_var,
            "paper_w": self.paper_w_var, "paper_h": self.paper_h_var,
            "count": self.count_var, "margin": self.margin_var, "gap": self.gap_var,
            "print": self.print_var, "print_w": self.print_w_var, "print_h": self.print_h_var,
            "autorotate": self.autorotate_var, "size_lock": self.size_lock_var,
            "align_x": self.align_x_var, "align_y": self.align_y_var,
            "keep_positions": self.keep_positions_var, "placement": self.placement_var,
            "card": self.card_var, "card_w": self.card_w_var, "card_h": self.card_h_var,
            "window_w": self.window_w_var, "window_h": self.window_h_var,
            "window_top": self.window_top_var, "window_left": self.window_left_var,
            "trim": self.trim_var, "trim_inset": self.trim_inset_var,
            "mark_inset": self.mark_inset_var, "line_inset": self.line_inset_var,
        }
        defaults = {key: variable.get() for key, variable in self._mode_vars.items()}
        self._mode_settings = {name: dict(defaults) for name in ("Разделить лист", "Задать размер фото", "Фото с рамкой", "Открытка со сгибом", "Буклет")}
        self._mode_settings["Задать размер фото"]["margin"] = "3"
        self._mode_settings["Фото с рамкой"]["margin"] = "3"
        self._mode_settings["Фото с рамкой"]["trim"] = "Линии"
        for name in ("Открытка со сгибом", "Буклет"):
            self._mode_settings[name].update(orientation="Альбомная", margin="3")
        self._factory_settings = {name: {**values, 'count': '1'} for name, values in self._mode_settings.items()}
        self._fold_states = {}
        self._fold_mode = None
        self._active_mode = "Разделить лист"
        self._switching_mode = False

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(20, 12))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 20, "bold")).pack(side="left")
        ttk.Label(header, text=VERSION, style="Muted.TLabel").pack(side="left", padx=12)
        self.units_combo = RoundedCombo(header, self.unit_var, ("mm", "in"), width=8, height=28)
        self.units_combo.pack(side="right")
        language = ttk.Frame(header)
        language.pack(side="right", padx=8)
        self.language_icons = {key: ImageTk.PhotoImage(Image.open(ASSETS / filename), master=self.root)
                               for key, filename in (('globe', 'globe.png'), ('ru', 'flag_ru.png'), ('en', 'flag_en.png'))}
        ttk.Label(language, image=self.language_icons['globe']).pack(side='left', padx=3)
        self.language_flag = ttk.Label(language, image=self.language_icons['en' if self.language_var.get() == 'English' else 'ru'])
        self.language_flag.pack(side='left', padx=3)
        self.language_combo = RoundedCombo(language, self.language_var, ("Русский", "English"), width=9, height=28)
        self.language_combo.format_value = lambda key: 'EN' if key == 'English' else 'RU'
        self.language_combo._literal_text = True
        self.language_combo.pack(side="left")
        self.reset_settings_button = CapsuleButton(header, text='↺ Сбросить настройки…', height=28, command=self.reset_settings)
        self.reset_settings_button.pack(side='right', padx=8)
        main = ttk.Frame(self.root)
        main.grid(row=1, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        main.columnconfigure(0, minsize=260)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, minsize=382)
        main.rowconfigure(0, weight=1)
        self._build_library(main)
        self._build_preview(main)
        self._build_settings(main)
        footer = ttk.Frame(self.root, padding=(18, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.counter_var, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", wraplength=610).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.print_button = CapsuleButton(footer, text="Печать…", command=self.print_order)
        self.print_button.grid(row=0, column=1, rowspan=2, padx=(10, 0), ipadx=10, ipady=4)
        self.save_button = CapsuleButton(footer, text="Сохранить PDF", style="Accent.TButton", command=self.save_pdf)
        self.save_button.grid(row=0, column=2, rowspan=2, padx=(10, 0), ipadx=15, ipady=4)

    def _build_library(self, parent: ttk.Frame) -> None:
        library = ttk.Frame(parent, padding=(10, 0, 10, 0), width=max(260,round(235*self.root.winfo_fpixels('1i')/96)))
        library.grid(row=0, column=0, sticky="nsew")
        library.grid_propagate(False)
        library.columnconfigure(0, weight=1)
        library.rowconfigure(4, weight=1)
        self.cover_box=tk.Frame(library,bg=BG)
        self.cover_box.grid(row=3,column=0,columnspan=2,sticky="ew",pady=(0,5))
        self.cover_box.columnconfigure((0,1),weight=1)
        self.cover_targets=[]
        for i,title in enumerate(("0 · Лицевая","END · Задняя")):
            target=self.create_assignment_target(self.cover_box,i,title,"cover")
            target.grid(row=0,column=i,sticky="ew",padx=2)
            self.cover_targets.append(target)
        self.blank_page_button=CapsuleButton(self.cover_box,text='+ Пустая страница',command=self.insert_booklet_blank)
        self.blank_page_button.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(4,0))
        self.booklet_blank_var=tk.StringVar(value='Пустые страницы: —')
        ttk.Label(self.cover_box,textvariable=self.booklet_blank_var,wraplength=220).grid(row=2,column=0,columnspan=2,sticky='w',pady=(6,0))
        CapsuleButton(self.cover_box,text='Номера…',height=24,command=self.edit_booklet_blank_numbers).grid(row=3,column=0,sticky='ew',pady=(4,0))
        CapsuleButton(self.cover_box,text='Вставить…',height=24,command=self.insert_booklet_dialog).grid(row=3,column=1,sticky='ew',pady=(4,0))
        CapsuleButton(library, text="＋  Добавить фото", command=self.add_dialog).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        CapsuleButton(library, text="Открыть папку", command=self.folder_dialog).grid(row=1, column=0, sticky="ew")
        bar = ttk.Frame(library)
        bar.grid(row=2, column=0, sticky="ew", pady=(15, 8))
        ttk.Label(bar, text="Фотографии", style="Heading.TLabel").pack(side="left")
        CapsuleButton(bar, text="Удалить", command=self.remove_selected, padding=(4, 2)).pack(side="right")
        self.library_canvas = tk.Canvas(library, bg=BG, highlightthickness=0)
        self.library_canvas.configure(takefocus=True)
        self.library_canvas.bind("<Delete>", self.delete_from_list)
        self.library_canvas.grid(row=4, column=0, sticky="nsew")
        scroll = RoundScrollbar(library,command=self.library_canvas.yview)
        self.library_scrollbar=scroll
        scroll.grid(row=4,column=1,sticky="ns",padx=(3,0))
        self.library_canvas.configure(yscrollcommand=scroll.set)
        self.library_inner = tk.Frame(self.library_canvas, bg=BG)
        self.library_window = self.library_canvas.create_window((0, 0), window=self.library_inner, anchor="nw")
        self.library_inner.bind("<Configure>", lambda event: self.library_canvas.configure(scrollregion=self.library_canvas.bbox("all")))
        self.library_canvas.bind("<Configure>", self.resize_library)
        self.empty_label = tk.Label(self.library_inner, text="Перетащите фото или папку сюда", bg=BG, wraplength=230,
                                    fg=MUTED, justify="center", pady=36)
        self.empty_label.pack(fill="x")
        self._wheel(self.library_canvas, self.library_canvas)

    def resize_library(self,event):
        self.library_canvas.itemconfigure(self.library_window,width=event.width)
        self.sync_library_labels()

    def resize_preview_footer(self,event):
        self.page_label.configure(wraplength=max(35,event.width-self.previous_button.winfo_reqwidth()-self.next_button.winfo_reqwidth()-48))
        for label in (self.size_hint_label,self.quality_label):label.configure(wraplength=max(80,event.width-20))

    def _build_preview(self, parent: ttk.Frame) -> None:
        panel = tk.Frame(parent, bg="#e4e6eb")
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        tk.Label(panel, text="Предпросмотр печати", font=("Segoe UI", 13, "bold"), bg="#e4e6eb", fg=INK,
                 anchor="w", padx=18, pady=12).grid(row=0, column=0, sticky="ew")
        self.preview_canvas = tk.Canvas(panel, bg="#e4e6eb", highlightthickness=0)
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.schedule_refresh)
        self.preview_canvas.configure(cursor="hand2", takefocus=True)
        self.preview_canvas.bind("<Button-1>", self.begin_drag)
        self.preview_canvas.bind("<B1-Motion>", self.drag_motion)
        self.preview_canvas.bind("<ButtonRelease-1>", self.end_drag)
        self.preview_canvas.bind("<MouseWheel>", self.zoom_sheet)
        self.preview_canvas.bind("<Button-2>", self.begin_sheet_pan)
        self.preview_canvas.bind("<B2-Motion>", self.move_sheet_pan)
        self.preview_canvas.bind("<ButtonRelease-2>", self.end_sheet_pan)
        bottom = tk.Frame(panel, bg="#e4e6eb")
        bottom.grid(row=2, column=0, sticky="ew", pady=10)
        bottom.columnconfigure(0, weight=0)
        bottom.columnconfigure(4, weight=1)
        self.previous_button = CapsuleButton(bottom, text="Назад", width=6, command=lambda: self.turn_page(-1))
        self.previous_button.grid(row=0, column=0,sticky="w",padx=(8,8))
        self.page_label=tk.Label(bottom,textvariable=self.page_var,bg="#e4e6eb",font=("Segoe UI",10),width=1,wraplength=180,justify='center')
        self.page_label.grid(row=0,column=1,sticky="ew",padx=6)
        bottom.columnconfigure(1,weight=1)
        bottom.columnconfigure(4,weight=0)
        self.next_button = CapsuleButton(bottom, text="Далее", width=6, command=lambda: self.turn_page(1))
        self.next_button.grid(row=0,column=2,sticky="e",padx=(8,8))
        bottom.bind('<Configure>',self.resize_preview_footer)
        self.size_hint_label=tk.Label(bottom,textvariable=self.size_hint_var,bg="#e4e6eb",fg="#626776",font=("Segoe UI",9),wraplength=300)
        self.size_hint_label.grid(row=1,column=0,columnspan=3,pady=(7,0),sticky='ew')
        self.quality_label=tk.Label(bottom,textvariable=self.quality_var,bg="#e4e6eb",fg="#a34451",font=("Segoe UI",9),wraplength=300)
        self.quality_label.grid(row=2,column=0,columnspan=3,pady=(4,0),sticky='ew')
        tk.Label(bottom, textvariable=self.occupancy_var, bg="#e4e6eb", fg=MUTED,
                 font=("Segoe UI", 9)).grid(row=3, column=0, columnspan=5)
        view_bar = tk.Frame(bottom, bg="#e4e6eb")
        view_bar.grid(row=4, column=0, columnspan=5, pady=(3, 0))
        tk.Label(view_bar, textvariable=self.sheet_zoom_var, bg="#e4e6eb", width=6).pack(side="left")
        self.fit_sheet_button = CapsuleButton(view_bar, text="Вписать лист", height=26, command=self.fit_sheet)
        self.fit_sheet_button.pack(side="left")

    def _legacy_build_settings(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, width=382)
        outer.grid(row=0, column=2, sticky="nsew")
        outer.grid_propagate(False)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, takefocus=True)
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        self.settings_scrollbar = RoundScrollbar(outer,command=self.settings_canvas.yview,auto_hide=False)
        outer.columnconfigure(1,minsize=self.settings_scrollbar.winfo_reqwidth())
        self.settings_scrollbar.grid(row=0, column=1, sticky="ns")
        self.settings_scrollbar.grid_remove()
        self.settings_canvas.configure(yscrollcommand=self.settings_scrollbar.set)
        settings = self.settings_inner = ttk.Frame(self.settings_canvas, padding=(12, 0, 12, 4))
        self.settings_window = self.settings_canvas.create_window((0, 0), window=settings, anchor="nw")
        self.settings_canvas.bind("<Configure>", self._update_settings_scroll)
        settings.bind("<Configure>", self._update_settings_scroll)
        self.root.bind("<FocusIn>", self._settings_focus_in, add=True)
        for key, direction in (("Prior", -1), ("Next", 1)):
            self.settings_canvas.bind(f"<{key}>", lambda event, d=direction: self.settings_canvas.yview_scroll(d, "pages"))
        settings.columnconfigure(1, weight=1)

        self.mode_combo = self._combo_row(settings, 0, "Раскладка", self.mode_var, ("Разделить лист", "Задать размер фото", "Фото с рамкой", "Открытка со сгибом", "Буклет"))
        settings.grid_slaves(row=0,column=0)[0].configure(style="Heading.TLabel")
        paper_row = ttk.Frame(settings)
        paper_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        paper_row.columnconfigure(0, weight=1, uniform="paper")
        paper_row.columnconfigure(1, weight=1, uniform="paper")
        ttk.Label(paper_row, text="Бумага").grid(row=0, column=0, sticky="w")
        ttk.Label(paper_row, text="Ориентация").grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.paper_combo = RoundedCombo(paper_row, self.paper_var, (*PAPERS, "Свой размер"), width=14, height=28)
        self.paper_combo.grid(row=1, column=0, sticky="ew", padx=(0, 3))
        self.paper_orientation_combo = RoundedCombo(paper_row, self.orientation_var, ("Книжная", "Альбомная"), width=14, height=28)
        self.paper_orientation_combo.grid(row=1, column=1, sticky="ew", padx=(3, 0))
        self.card_page_button = CapsuleButton(paper_row, text="Лист по размеру карточки", height=26, command=self.use_card_page)
        self.card_page_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self.paper_custom = ttk.Frame(settings)
        self.paper_custom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Label(self.paper_custom, text="Бумага, мм").pack(side="left", padx=(0, 6))
        dims = ttk.Frame(self.paper_custom)
        dims.pack(side="right", fill="x", expand=True)
        self.paper_entries = self._dimensions(dims, self.paper_w_var, self.paper_h_var)

        self.cells_box = ttk.Frame(settings)
        self.cells_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        self.cells_box.columnconfigure(1, weight=1)
        self.count_combo = self._combo_row(self.cells_box, 0, "Фото на листе", self.count_var, ("1", "2", "4", "6", "9"))

        self.exact_box = ttk.Frame(settings)
        self.exact_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        self.exact_box.columnconfigure(1, weight=1)
        self.print_combo = self._combo_row(self.exact_box, 0, "Размер фото", self.print_var, (*PRINT_SIZES, "Свой размер"))
        self.print_caption = self.exact_box.grid_slaves(row=0, column=0)[0]
        self.card_box = ttk.Frame(self.exact_box)
        self.card_box.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.card_box.columnconfigure(0, weight=1)
        ttk.Label(self.card_box, text="Шаблон карточки").grid(row=0, column=0, sticky="w")
        self.card_combo = RoundedCombo(self.card_box, self.card_var, (*CARD_TEMPLATES, "Свой шаблон"), height=28)
        self.card_combo.grid(row=1, column=0, sticky="ew")
        ToolTip(self.card_combo, "\n".join(CARD_TEMPLATES))
        ttk.Label(self.card_box, textvariable=self.card_hint_var, style="Muted.TLabel", wraplength=330).grid(row=2, column=0, sticky="w")
        self.card_custom = ttk.Frame(self.card_box)
        self.card_custom.grid(row=3, column=0, sticky="ew")
        self.card_custom.columnconfigure(1, weight=1)
        self.card_custom_entries = []
        for row, (caption, a_var, b_var) in enumerate((("Карточка, Ш × В", self.card_w_var, self.card_h_var),
                ("Окно, Ш × В", self.window_w_var, self.window_h_var),
                ("Отступ сверху / слева", self.window_top_var, self.window_left_var))):
            ttk.Label(self.card_custom, text=caption).grid(row=row, column=0, sticky="w", padx=(0, 5))
            fields = ttk.Frame(self.card_custom)
            fields.grid(row=row, column=1, sticky="ew", pady=2)
            self.card_custom_entries.extend(self._dimensions(fields, a_var, b_var))
        for field in self.card_custom_entries[-2:]:
            field.minimum = 0
            field.configure(from_=0)
        self.print_custom = ttk.Frame(self.exact_box)
        self.print_custom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        self.print_custom.columnconfigure(0, weight=1)
        self.print_custom.columnconfigure(2, weight=1)
        a = NumberSpin(self.print_custom, self.print_w_var, minimum=1)
        a.grid(row=0, column=0, sticky="ew")
        self.lock_check = LockButton(self.print_custom,self.size_lock_var)
        self.lock_check.grid(row=0, column=1, padx=5)
        b = NumberSpin(self.print_custom, self.print_h_var, minimum=1)
        b.grid(row=0, column=2, sticky="ew")
        ttk.Label(self.print_custom, text="мм").grid(row=0, column=3, padx=(4, 0))
        self.print_entries = [a, b]
        ttk.Label(self.print_custom, textvariable=self.ppi_var, style="Muted.TLabel", wraplength=320).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(1, 0))
        self.original_button = CapsuleButton(self.exact_box, text="Исходный размер", command=self.original_size, height=26)
        self.original_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=1)
        self.capacity_row = ttk.Frame(self.exact_box)
        self.capacity_row.grid(row=4,column=0,columnspan=2,sticky="ew")
        self.capacity_row.columnconfigure(0,weight=1)
        self.capacity_label = ttk.Label(self.exact_box, textvariable=self.capacity_var, foreground=PINK,
                  font=("Segoe UI", 10, "bold"))
        self.capacity_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=1)
        self.placement_row = ttk.Frame(self.exact_box)
        self.placement_row.grid(row=4, column=0, columnspan=2, sticky="ew")
        
        self.placement_hint = ttk.Label(self.placement_row)
        self.placement_buttons = []
        for label in ("Авто", "Рядом", "Стопкой"):
            button = CapsuleButton(self.placement_row, text=label, height=24, width=6,
                                   command=lambda value=label: self.placement_var.set(value))
            button.pack(side="left", fill="x", expand=True, padx=1)
            self.placement_buttons.append(button)
        alignment = self.alignment_row = ttk.Frame(self.exact_box)
        alignment.grid(row=6, column=0, columnspan=2, sticky="ew", pady=2)
        self.alignment_buttons = []
        for axis, value, hint in (("x", "left", "Слева"), ("x", "center", "По центру горизонтали"),
                                  ("x", "right", "Справа"), ("y", "top", "Сверху"),
                                  ("y", "center", "По центру вертикали"), ("y", "bottom", "Снизу")):
            button = CapsuleButton(alignment, text="", width=4, height=24,
                                   command=lambda a=axis, v=value: self.set_group_alignment(a, v))
            button.pack(side="left", fill="x", expand=True, padx=(0, 2))
            # Small vector pictograms: guide plus two unequal bars.
            def draw_icon(event=None, widget=button, a=axis, v=value):
                widget.delete("alignment_icon")
                cx, cy = widget.winfo_width() / 2, widget.winfo_height() / 2
                guide = {"left": -8, "center": 0, "right": 8, "top": -8, "bottom": 8}[v]
                color = "#a1a1a1" if widget.cget("state") == "disabled" else INK
                if a == "x":
                    widget.create_line(cx + guide, cy - 8, cx + guide, cy + 8, fill=color, tags="alignment_icon")
                    for width, yy in ((11, -4), (7, 4)):
                        start = guide if v == "left" else guide - width if v == "right" else -width / 2
                        widget.create_line(cx + start, cy + yy, cx + start + width, cy + yy,
                                           fill=color, width=3, tags="alignment_icon")
                else:
                    widget.create_line(cx - 8, cy + guide, cx + 8, cy + guide, fill=color, tags="alignment_icon")
                    for height, xx in ((11, -4), (7, 4)):
                        start = guide if v == "top" else guide - height if v == "bottom" else -height / 2
                        widget.create_line(cx + xx, cy + start, cx + xx, cy + start + height,
                                           fill=color, width=3, tags="alignment_icon")
            button.bind("<Configure>", draw_icon, add=True)
            button.draw_alignment_icon = draw_icon
            ToolTip(button, hint)
            self.alignment_buttons.append((button, axis, value))
        self.layout_advanced = FoldSection(self.exact_box, 'Дополнительно…', opened=False)
        self.layout_advanced.grid(row=6, column=0, columnspan=2, sticky='ew')
        self.keep_positions_check = CheckMark(self.layout_advanced.body, text="Сохранять позиции на всех листах",
                                              variable=self.keep_positions_var)
        self.keep_positions_check.pack(fill='x')

        spacing = self.spacing = ttk.Frame(settings)
        spacing.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 5))
        spacing.columnconfigure(1, weight=1)
        spacing.columnconfigure(3, weight=1)
        ttk.Label(spacing, text="Поля листа").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.margin_entry = NumberSpin(spacing, self.margin_var, width=5)
        self.margin_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(spacing, text="Зазор").grid(row=0, column=2, padx=(10, 5))
        self.gap_entry = NumberSpin(spacing, self.gap_var, width=5)
        self.gap_entry.grid(row=0, column=3, sticky="ew")
        ToolTip(spacing, "Поля и зазор. Стрелки: 1 мм / 0,01 in, дробные значения можно вводить вручную.")

        self.trim_section = FoldSection(settings, 'Метки реза', opened=False)
        self.trim_section.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(0, 5))
        self.trim_box = self.trim_section.body
        self.trim_box.columnconfigure(1, weight=1)
        self.trim_combo = self._combo_row(self.trim_box, 0, "Рез", self.trim_var, ("Нет", "Линии", "Метки", "Метки и линии"))
        self.trim_caption = ttk.Label(self.trim_box, text="Отступ реза внутрь, мм")
        self.trim_caption.grid(row=1, column=0, sticky="w")
        self.trim_entry = NumberSpin(self.trim_box, self.trim_inset_var, width=6)
        self.trim_entry.grid(row=1, column=1, sticky="e")
        self.combined_trim_box=ttk.Frame(self.trim_box)
        self.combined_trim_box.grid(row=1,column=0,columnspan=2,sticky='ew')
        self.combined_trim_box.columnconfigure(0,weight=1)
        self.combined_trim_entries=[]
        for row,(label,var) in enumerate((('Отступ меток внутрь',self.mark_inset_var),('Отступ линий внутрь',self.line_inset_var))):
            caption=ttk.Label(self.combined_trim_box,text=label,wraplength=230)
            caption.grid(row=row,column=0,sticky='ew')
            caption.bind('<Configure>',lambda event,w=caption:w.configure(wraplength=max(80,event.width)))
            entry=NumberSpin(self.combined_trim_box,var,width=6)
            entry.grid(row=row,column=1,sticky='e');self.combined_trim_entries.append(entry)
        self.trim_hint_label = ttk.Label(self.trim_box, textvariable=self.trim_hint_var, style="Muted.TLabel", wraplength=330)
        self.trim_hint_label.grid(row=2, column=0, columnspan=2, sticky="w")
        self._combo_row(self.trim_box,3,"Линия по центру",self.center_line_var,("Нет","Вертикальная","Горизонтальная"))
        self.fold_controls=ttk.Frame(self.trim_box)
        self.fold_controls.grid(row=4,column=0,columnspan=2,sticky='ew')
        self._combo_row(self.fold_controls,0,"Метки сгиба",self.fold_marks_var,("Нет","Риски по краям","Сплошная линия"))
        self._combo_row(self.fold_controls,1,"Сторона",self.fold_side_var,("Лицевая","Оборот","Обе"))
        self.panel_box=ttk.Frame(settings)
        self.panel_box.grid(row=3,column=0,columnspan=2,sticky='ew')
        ttk.Label(self.panel_box,text='Выберите фото слева и назначьте панель',wraplength=320).grid(row=0,column=0,columnspan=2,sticky='w')
        self.panel_buttons=[]
        self.panel_box.columnconfigure((0,1),weight=1)
        for i,label in enumerate(("Лицевая","Задняя","Внутри слева","Внутри справа")):
            button=self.create_assignment_target(self.panel_box,i,label,'panel')
            button.grid(row=i//2+1,column=i%2,sticky='ew',padx=2,pady=2)
            self.panel_buttons.append(button)
        self.duplex_info=ttk.Label(settings,textvariable=self.capacity_var,wraplength=320)
        self.duplex_info.grid(row=3,column=0,columnspan=2,sticky='w')
        ToolTip(self.duplex_info,'Страницы в порядке чтения задаются списком слева. PDF: одна страница на сторону листа, короткий край; режим буклета в просмотрщике выключить.')
        for var in (self.center_line_var,self.fold_marks_var,self.fold_side_var):
            var.trace_add('write',self.schedule_refresh)

        selected_box = ttk.LabelFrame(settings, text="Выбранное фото", padding=5)
        self.selection_title_label = ttk.Label(selected_box,textvariable=self.selection_title_var,style="Heading.TLabel")
        selected_box.configure(labelwidget=self.selection_title_label)
        selected_box.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        selected_box.columnconfigure(0, weight=1)
        selected_box.columnconfigure(1, weight=1)
        self.selected_name_label = ttk.Label(selected_box, textvariable=self.selected_var, style="Muted.TLabel",wraplength=330)
        self.selected_name_label._l10n_skip = True
        self.selected_name_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        ToolTip(self.selected_name_label, lambda: self.photos[self.selected].name if 0 <= self.selected < len(self.photos) else '')
        self.fill_button = CapsuleButton(selected_box, text="Обрезать до краёв", command=lambda: self.selected_mode("fill"), height=28)
        self.fill_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.fit_button = CapsuleButton(selected_box, text="Фото целиком", command=lambda: self.selected_mode("fit"), height=28)
        self.fit_button.grid(row=1, column=1, sticky="ew")
        actions = ttk.Frame(selected_box)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=3)
        self.rotate_button = CapsuleButton(actions, text="↻ 90°", command=self.rotate_photo, height=28)
        self.rotate_button.pack(side="left")
        self.zoom_out_button = CapsuleButton(actions, text="−", width=2, command=lambda: self.zoom_photo(-10), height=28)
        self.zoom_out_button.pack(side="left", padx=(4, 0))
        ttk.Label(actions, textvariable=self.zoom_var, width=5, anchor="center").pack(side="left")
        self.zoom_button = CapsuleButton(actions, text="+", width=2, command=self.zoom_photo, height=28)
        self.zoom_button.pack(side="left", padx=(0, 4))
        ToolTip(self.zoom_button, "Увеличить фото")
        ToolTip(self.zoom_out_button, "Уменьшить фото до 100%")
        self.reset_frame_button = CapsuleButton(actions, text="Сбросить кадр", command=self.reset_frame, height=28)
        self.reset_frame_button.pack(side="left", fill="x", expand=True)
        self.apply_crop_button = CapsuleButton(selected_box, text="Применить кадрирование ко всем", command=self.apply_crop_to_all, height=26)
        self.apply_crop_button.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.pdf_size_button = CapsuleButton(selected_box, text='Взять размер страницы из PDF',
                                              command=self.take_pdf_size, height=26)
        self.pdf_size_button.grid(row=4,column=0,columnspan=2,sticky='ew')

        self.color_section = FoldSection(settings, 'Цвет')
        self.color_section.summary_provider = lambda opened: self.color_section.summary
        self.color_section.grid(row=7, column=0, columnspan=2, sticky='ew')
        correction = self.color_section.body
        correction.columnconfigure(0, weight=1)
        ttk.Label(correction,textvariable=self.color_scope_var,style="Muted.TLabel").grid(row=10,column=0,columnspan=2,sticky="w")
        self.individual_color_check = CheckMark(correction, text="Индивидуально для выбранного фото",
            variable=self.individual_color_var, command=lambda: self.set_individual_color(self.individual_color_var.get()))
        self.individual_color_check.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.mixed_color_label = ttk.Label(correction,textvariable=self.mixed_color_var,style='Muted.TLabel',wraplength=330)
        self.mixed_color_label.grid(row=9,column=0,columnspan=2,sticky='w')
        for row, (name, variable, hint, attribute) in enumerate((
                ("Температура", self.temperature_var, "холоднее ↔ теплее", "temperature"),
                ("Оттенок", self.tint_var, "зелёный ↔ пурпурный", "tint"),
                ("Сочность", self.saturation_var, "", "saturation"))):
            caption = ttk.Frame(correction)
            caption.grid(row=1 + row * 2, column=0, sticky="ew")
            ttk.Label(caption, text=name).pack(side="left")
            if hint:
                ttk.Label(caption, text=hint, style="Muted.TLabel").pack(side="right", padx=4)
            if attribute == "saturation":
                label = ttk.Label(correction, text="0", width=4, anchor="e")
            else:
                label = NumberSpin(correction, variable, minimum=-100, maximum=100, increment=.5, width=6)
                label.bind("<Return>", lambda event, var=variable: self.commit_color_number(var))
                label.bind("<FocusOut>", lambda event, var=variable: self.commit_color_number(var))
            label.grid(row=1 + row * 2, column=1, rowspan=2, sticky="e")
            command = self.saturation_changed if attribute == "saturation" else lambda value: None
            scale = TickScale(correction, variable, -100, 100, 1 if attribute == "saturation" else .5,
                              10, 0, command, decimals=0 if attribute == "saturation" else 1, compact=True,
                              gradient={"temperature":("#74b6dc","#e7e2e5","#edb45d"),
                                        "tint":("#76b490","#e7e2e5","#c76aac"),
                                        "saturation":("#d4bec8","#ed4787")}[attribute])
            scale.grid(row=2 + row * 2, column=0, sticky="ew")
            scale.scale.bind("<ButtonRelease-1>", self.finish_color_preview, add=True)
            setattr(self, attribute + "_label", label)
            setattr(self, attribute + "_scale", scale)
        curve_row = ttk.Frame(correction)
        curve_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=2)
        curve_row.columnconfigure(0, weight=1)
        self.curves_button = CapsuleButton(curve_row, text="Кривые RGB…", command=self.open_curves, height=28)
        self.curves_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.before_button = CapsuleButton(curve_row, text="До", command=lambda: self.set_before(True), height=28)
        self.before_button.grid(row=0, column=1, padx=(0, 3))
        self.after_button = CapsuleButton(curve_row, text="После", command=lambda: self.set_before(False), height=28)
        self.after_button.grid(row=0, column=2)
        color_actions = ttk.Frame(correction)
        color_actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        CapsuleButton(color_actions, text="Яркость", command=self.open_advanced, height=26).pack(side="left")
        self.color_reset_button = CapsuleButton(color_actions, text="Сбросить цвет", command=self.reset_color, height=26)
        self.color_reset_button.pack(side="right")
        to_row=ttk.Frame(correction)
        to_row.grid(row=11,column=0,columnspan=2,sticky='ew')
        self.to_buttons={}
        for mode,label,hint in (("a_to_b","TO a→b","Скопировать a* в b*, сохранив a* и L*"),("b_to_a","TO b→a","Скопировать b* в a*, сохранив b* и L*")):
            b=CapsuleButton(to_row,text=label,command=lambda m=mode:self.toggle_teal_orange(m),height=26)
            b.pack(side='left',fill='x',expand=True,padx=2)
            ToolTip(b,hint)
            self.to_buttons[mode]=b
        output = ttk.Frame(settings)
        output.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        output.columnconfigure(1, weight=1)
        self.output_combo = self._combo_row(output, 0, "Разрешение вывода", self.output_ppi_var, ("300", "600"))
        ToolTip(self.output_combo, "300 / 600 ppi: плотность растра PDF и прямой печати. Размеры в мм сохраняются.")
        self._wheel(self.settings_canvas, self.settings_canvas)
        for scale in (self.temperature_scale, self.tint_scale, self.saturation_scale):
            scale.scale.unbind("<MouseWheel>")

    def _update_settings_scroll(self, event=None):
        if self._closing:
            return
        canvas = self.settings_canvas
        width = max(1, canvas.winfo_width())
        if float(canvas.itemcget(self.settings_window, "width")) != width:
            canvas.itemconfigure(self.settings_window, width=width)
        canvas.configure(scrollregion=(0,0,width,self.settings_inner.winfo_reqheight()))
        if self.settings_inner.winfo_reqheight() > canvas.winfo_height() + 1:
            self.settings_scrollbar.grid()
        else:
            self.settings_scrollbar.grid_remove()
            canvas.yview_moveto(0)

    def _settings_focus_in(self, event):
        widget = event.widget
        if (not isinstance(widget, tk.Widget) or widget.winfo_toplevel() != self.root
                or not str(widget).startswith(str(self.settings_inner) + ".")):
            return
        canvas = self.settings_canvas
        top = widget.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        height = max(1, self.settings_inner.winfo_height())
        origin = canvas.yview()[0] * height
        if top < 0:
            canvas.yview_moveto(max(0, origin + top - 3) / height)
        elif bottom > canvas.winfo_height():
            canvas.yview_moveto((origin + bottom - canvas.winfo_height() + 3) / height)

    def open_advanced(self):
        if getattr(self, "_advanced", None) and self._advanced.winfo_exists():
            self._advanced.lift()
            return
        window = self._advanced = tk.Toplevel(self.root)
        window.title(self.display_text("Яркость"))
        set_icon(window)
        window.transient(self.root)
        window.configure(bg=BG)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.display_text("Гамма"), style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.gamma_label_var).grid(row=0, column=1, sticky="e")
        self.gamma_scale = TickScale(frame, self.gamma_var, .5, 2, .01, .1, 1, lambda value: None, decimals=2)
        self.gamma_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        self.gamma_scale.scale.configure(length=300)
        self.gamma_scale.scale.bind("<ButtonRelease-1>", self.finish_color_preview, add=True)
        ttk.Label(frame, text="Двойной щелчок: 1,00", style="Muted.TLabel").grid(row=2, column=0, columnspan=2)
        CapsuleButton(frame, text="Готово", command=window.destroy).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    @staticmethod
    def _combo_row(parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, values: tuple[str, ...]) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        combo = RoundedCombo(parent, textvariable=variable, values=values, state="readonly", width=20, height=28)
        combo.grid(row=row, column=1, sticky="ew", pady=2)
        return combo

    @staticmethod
    def _dimensions(parent: ttk.Frame, width: tk.StringVar, height: tk.StringVar) -> list[ttk.Entry]:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(2, weight=1)
        a = NumberSpin(parent, width, minimum=1)
        a.grid(row=0, column=0, sticky="ew")
        ttk.Label(parent, text="×").grid(row=0, column=1, padx=5)
        b = NumberSpin(parent, height, minimum=1)
        b.grid(row=0, column=2, sticky="ew")
        return [a, b]

    def _wheel(self, widget: tk.Widget, canvas_widget: tk.Canvas) -> None:
        def scroll(event: tk.Event) -> str:
            bounds = canvas_widget.bbox("all")
            if bounds and bounds[3] > canvas_widget.winfo_height():
                canvas_widget.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        widget.bind("<MouseWheel>", scroll)
        for child in widget.winfo_children():
            self._wheel(child, canvas_widget)

    def _bind_settings(self) -> None:
        self.language_var.trace_add("write", self.presentation_changed)
        self.unit_var.trace_add("write", self.presentation_changed)
        self.output_ppi_var.trace_add("write", self.schedule_refresh)
        self.output_ppi_var.trace_add("write", self.update_original_size_label)
        self.mode_var.trace_add("write", self._mode_changed)
        self.count_var.trace_add('write',self.save_cell_count)
        for key, variable in self._mode_vars.items():
            if not key.startswith('bleed_'):
                variable.trace_add("write", self.schedule_refresh)
        for variable in (self.paper_var, self.orientation_var, self.paper_w_var, self.paper_h_var):
            variable.trace_add("write", self._paper_changed)

    def _paper_changed(self, *_args: object) -> None:
        # Driver margins are meaningful only for the paper/orientation queried.
        self.preview_driver_margins = None

    def save_cell_count(self, *_):
        if not self._switching_mode and self.mode_var.get()=='Разделить лист':
            try:
                save_preferences('en' if self.language_var.get()=='English' else 'ru',
                                 'in' if self.unit_var.get()=='in' else 'mm',self.count_var.get())
            except OSError as error:
                self.status_var.set(str(error))

    def _mode_changed(self, *_args: object) -> None:
        mode = self.mode_var.get()
        if mode == self._active_mode or self._switching_mode:
            return
        self._mode_settings[self._active_mode] = {key: var.get() for key, var in self._mode_vars.items()}
        self._switching_mode = True
        try:
            for key, value in self._mode_settings[mode].items():
                self._mode_vars[key].set(value)
            self._active_mode = mode
        finally:
            self._switching_mode = False
        self.preview_driver_margins = None
        self.settings_canvas.yview_moveto(0)
        self.refresh()
        self.root.update_idletasks()
        self.settings_canvas.yview_moveto(0)
        self.custom_preset_changed()

    def schedule_refresh(self, *_args: object) -> None:
        if self._switching_mode or self._closing:
            return
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(100, self.refresh)

    @staticmethod
    def _number(variable: tk.StringVar) -> float:
        try:
            return float(str(variable.get()).strip().replace(",", ".").replace("−", "-"))
        except ValueError as error:
            raise ValueError("Введите числовые размеры, поля и промежуток.") from error

    def _legacy_read_layout(self) -> Layout:
        card_mode = self.mode_var.get() == "Фото с рамкой"
        duplex = self.mode_var.get() in ("Открытка со сгибом", "Буклет")
        if self.mode_var.get()=="Буклет":self.ensure_booklet_covers()
        exact = self.mode_var.get() in ("Задать размер фото", "Фото с рамкой")
        if self.paper_var.get() in PAPERS:
            pw, ph = PAPERS[self.paper_var.get()]
        else:
            pw, ph = self._number(self.paper_w_var), self._number(self.paper_h_var)
        pw, ph = sorted((pw, ph), reverse=self.orientation_var.get() == "Альбомная")
        if duplex: pw,ph=max(pw,ph),min(pw,ph)
        card = self.read_card() if card_mode else None
        if card:
            fw, fh = card.width, card.height
        elif exact and self.print_var.get() == "Свой размер":
            fw, fh = self._number(self.print_w_var), self._number(self.print_h_var)
        else:
            fw, fh = PRINT_SIZES.get(self.print_var.get(), (100.0, 150.0))
        try:
            count = int(self.count_var.get())
        except ValueError as error:
            raise ValueError("Выберите число фото на листе.") from error
        margin = self._number(self.margin_var)
        return Layout(mode=({"Открытка со сгибом":"postcard","Буклет":"booklet"}[self.mode_var.get()] if duplex else "exact" if exact else "cells"), paper_width=pw, paper_height=ph,
                      per_sheet=count, margin=margin,
                      gap=self._number(self.gap_var), print_width=fw, print_height=fh,
                      driver_margins=None, autorotate=not duplex,
                      order=self.print_sequence, panels=tuple(self.panel_ids),booklet_covers=tuple(self.booklet_cover_ids),booklet_interiors=tuple(self.booklet_interior_ids),
                      booklet_sequence=tuple(leaf['token'] for leaf in self.booklet_leaves) if self._booklet_initialized else None,
                      center_line={"Нет":"none","Вертикальная":"vertical","Горизонтальная":"horizontal"}[self.center_line_var.get()],
                      fold_marks={"Нет":"none","Риски по краям":"ticks","Сплошная линия":"line"}[self.fold_marks_var.get()],
                      fold_side={"Лицевая":"front","Оборот":"back","Обе":"both"}[self.fold_side_var.get()],
                      align_x=self.align_x_var.get(), align_y=self.align_y_var.get(),
                      keep_positions=self.keep_positions_var.get(),
                      placement={"Авто": "auto", "Рядом": "beside", "Стопкой": "stack"}[self.placement_var.get()],
                      card=card, trim_mode={"Нет": "none", "Линии": "lines", "Метки": "marks", "Метки и линии":"both"}[self.trim_var.get()] if exact else "none",
                      trim_inset=self._number(self.trim_inset_var) if exact and self.trim_var.get() != "Нет" else 0,
                      mark_inset=self._number(self.mark_inset_var),line_inset=self._number(self.line_inset_var))

    def read_card(self):
        if self.card_var.get() in CARD_TEMPLATES:
            return CARD_TEMPLATES[self.card_var.get()]
        return CardTemplate(*(self._number(v) for v in (self.card_w_var, self.card_h_var, self.window_w_var,
                                                         self.window_h_var, self.window_top_var, self.window_left_var)))

    def use_card_page(self):
        try:
            card = self.read_card()
            card.validate()
        except ValueError as error:
            messagebox.showerror("Проверьте шаблон карточки", str(error), parent=self.root)
            return
        self.paper_var.set("Свой размер")
        self.paper_w_var.set(repr(card.width))
        self.paper_h_var.set(repr(card.height))
        self.orientation_var.set("Альбомная" if card.width > card.height else "Книжная")
        self.margin_var.set("0")
        self.gap_var.set("0")
        self.placement_var.set("Авто")
        self.refresh()

    def set_group_alignment(self, axis, value):
        (self.align_x_var if axis == "x" else self.align_y_var).set(value)
        self.refresh()

    def sync_fold_sections(self):
        mode = self.mode_var.get()
        if mode != self._fold_mode:
            if self._fold_mode is not None:
                self._fold_states[self._fold_mode] = (self.color_section.opened, self.trim_section.opened)
            color, trim = self._fold_states.get(mode, (mode == 'Разделить лист', False))
            self.color_section.set_open(color)
            self.trim_section.set_open(trim)
            self._fold_mode = mode
        colors = [self.correction] + [p.correction for p in self.photos if p.correction is not None]
        corrected = any(c != Correction() for c in colors) or any(p.curve is not None and p.curve != Correction().curve for p in self.photos)
        self.color_section.update_header('есть коррекция' if corrected else 'без правок')
        summary='нет' if self.trim_var.get() == 'Нет' else self.trim_var.get().lower()+', '+self.trim_inset_var.get()+' мм внутрь'
        if self.trim_var.get()=='Метки и линии':summary='метки '+self.mark_inset_var.get()+' мм, линии '+self.line_inset_var.get()+' мм'
        if self.center_line_var.get()!='Нет': summary+=' · '+self.center_line_var.get()
        if self.mode_var.get() in ('Открытка со сгибом','Буклет') and self.fold_marks_var.get()!='Нет': summary+=' · '+self.fold_marks_var.get()
        self.trim_section.update_header(summary)

    def reset_settings(self):
        if not messagebox.askyesno('Сбросить настройки?',
                'Будут сброшены: раскладка, поля, зазор, выравнивание, подрезка, кадрирование и цвет. Фото, количество копий, язык и единицы сохранятся.', parent=self.root):
            return
        self._switching_mode = True
        self._size_updating = True
        try:
            self._mode_settings = {name: dict(values) for name, values in self._factory_settings.items()}
            self.mode_var.set('Разделить лист')
            self._active_mode = 'Разделить лист'
            for key, value in self._mode_settings[self._active_mode].items():
                self._mode_vars[key].set(value)
            self.trim_var.set('Нет')
            self.trim_inset_var.set('0')
            self.mark_inset_var.set('2');self.line_inset_var.set('0')
            for photo in self.photos:
                photo.mode = 'fill'
                photo.reset_frame()
                photo.correction = photo.curve = None
            self.center_line_var.set("Нет")
            self.fold_marks_var.set("Нет")
            self.fold_side_var.set("Обе")
            self.correction = Correction()
            self.global_curve = self.correction.curve
            self.preview_before = False
            self.preview_driver_margins = None
            self._custom_initialized = False
            self.reset_production_settings()
            self._undo_stack.clear()
            self._fold_states.clear()
            self._fold_mode = None
        finally:
            self._size_updating = False
            self._switching_mode = False
        self.sync_color_controls(force=True)
        self.update_curve_badges()
        self.save_cell_count()
        self.refresh()

    def set_printer_margins(self, margins: EdgeInsets | None) -> None:
        """Recompute BEFORE confirmation if a future driver adapter supplies margins."""
        self.preview_driver_margins = margins
        self.refresh()

    @staticmethod
    def _state(widget: ttk.Widget, enabled: bool, readonly: bool = False) -> None:
        widget.configure(state=("readonly" if readonly else "normal") if enabled else "disabled")

    def _legacy_sync_controls(self) -> None:
        exact = self.mode_var.get() == "Задать размер фото"
        cards = self.mode_var.get() == "Фото с рамкой"
        if cards:
            self.card_page_button.grid()
        else:
            self.card_page_button.grid_remove()
        if exact or cards:
            self.cells_box.grid_remove()
            self.exact_box.grid()
        else:
            self.exact_box.grid_remove()
            self.cells_box.grid()
        for widget, visible in ((self.card_box, cards), (self.print_combo, exact), (self.print_caption, exact),
                                (self.card_custom, cards and self.card_var.get() == "Свой шаблон"),
                                (self.trim_section, True)):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        self._state(self.trim_entry, self.trim_var.get() != "Нет")
        combined=self.trim_var.get()=='Метки и линии'
        for widget in (self.trim_caption, self.trim_entry):
            widget.grid() if self.trim_var.get() != 'Нет' and not combined else widget.grid_remove()
        self.trim_hint_label.grid() if self.trim_var.get()!='Нет' else self.trim_hint_label.grid_remove()
        self.combined_trim_box.grid() if combined else self.combined_trim_box.grid_remove()
        # Keep spacing beside size/capacity/alignment in the exact-size group.
        self.spacing.grid_forget()
        self.spacing.grid(in_=self.exact_box if exact or cards else self.settings_inner,
                          row=3 if exact or cards else 4, column=0, columnspan=2, sticky='ew', pady=2)
        # The capacity follows spacing; placement and alignment remain independent.
        self.capacity_label.grid(in_=self.capacity_row,row=0,column=0,columnspan=1,sticky="w")
        self.placement_row.grid(in_=self.capacity_row,row=0,column=1,columnspan=1,sticky="e")
        self.alignment_row.grid_configure(row=5)
        self.layout_advanced.grid_configure(row=6)
        duplex=self.mode_var.get() in ("Открытка со сгибом","Буклет")
        if duplex:
            self.cells_box.grid_remove()
            self.exact_box.grid_remove()
        self.fold_controls.grid() if duplex else self.fold_controls.grid_remove()
        self.panel_box.grid() if self.mode_var.get()=="Открытка со сгибом" else self.panel_box.grid_remove()
        self.duplex_info.grid() if self.mode_var.get()=="Буклет" else self.duplex_info.grid_remove()
        self._state(self.paper_orientation_combo,not duplex)
        self.cover_box.grid() if self.mode_var.get()=="Буклет" else self.cover_box.grid_remove()
        self.sync_panel_buttons()
        self.sync_fold_sections()
        self.margin_entry.minimum = 0
        for widget, visible in ((self.paper_custom, self.paper_var.get() == "Свой размер"),
                                (self.print_custom, exact and self.print_var.get() == "Свой размер"),
                                (self.original_button, exact and self.print_var.get() == "Свой размер")):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        selected = 0 <= self.selected < len(self.photos)
        if selected and self.photos[self.selected].pdf_page is not None:
            self.pdf_size_button.grid()
        else:
            self.pdf_size_button.grid_remove()
        for button in (self.fill_button, self.fit_button, self.rotate_button, self.reset_frame_button, self.zoom_button,
                       self.apply_crop_button, self.original_button):
            self._state(button, selected)
        zoom = self.photos[self.selected].zoom if selected else 1.0
        group = self.editing_photos()
        self.selection_title_var.set(f'Выбрано: {len(group)} фото' if len(group)>1 else 'Выбранное фото')
        self.zoom_var.set('—' if len({p.zoom for p in group})>1 else f"{round(zoom * 100)}%")
        self._state(self.zoom_out_button, any(p.zoom>1.000001 for p in group))
        for button, axis, value in self.alignment_buttons:
            active = (self.align_x_var if axis == "x" else self.align_y_var).get() == value
            button.configure(style="Chosen.TButton" if active else "TButton")
        for button in self.placement_buttons:
            button.configure(style="Chosen.TButton" if button.cget("text") == self.placement_var.get() else "TButton")
        self.fill_button.configure(style="Chosen.TButton" if group and all(p.mode=='fill' for p in group) else "TButton")
        self.fit_button.configure(style="Chosen.TButton" if group and all(p.mode=='fit' for p in group) else "TButton")
        self.before_button.configure(style="Chosen.TButton" if self.preview_before else "TButton")
        self.after_button.configure(style="TButton" if self.preview_before else "Chosen.TButton")
        name = self.photos[self.selected].name if selected else self.display_text("Выберите снимок слева или на листе")
        self.selected_var.set(name if len(name) <= 40 else name[:37] + "…")
        if len(group)>1:
            differences = [label for attribute,label in (('mode','Кадрирование'),('rotation','Поворот'),('zoom','Масштаб'))
                           if len({getattr(p,attribute) for p in group})>1]
            self.selected_var.set('Разные значения: '+', '.join(differences) if differences else f'Выбрано: {len(group)} фото')
        self.sync_color_controls()
        self.sync_fold_sections()

    def _legacy_refresh(self) -> None:
        if self._closing:
            return
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = None
        self._sync_controls()
        try:
            if any(not var.get().isascii() or not var.get().isdigit() or int(var.get()) < 1 for var in self.copy_vars):
                raise ValueError("Укажите число копий не меньше 1. Для исключения фото используйте «Удалить».")
            from .core import CutGeometryError
            self._cut_error=None
            layout = self.read_layout()
            try:layout.validate()
            except CutGeometryError as error:
                self._cut_error=error
                layout=replace(layout,trim_mode='none')
                layout.validate()
            fmt = lambda value: f"{value:g}".replace(".", ",")
            if layout.card:
                c = layout.card
                self.card_hint_var.set(f"Карточка {fmt(c.width)} × {fmt(c.height)} мм · "
                                       f"Окно {fmt(c.window_width)} × {fmt(c.window_height)} мм\n"
                                       f"Сверху {fmt(c.top)} мм · Слева {fmt(c.left)} мм")
            inset = layout.effective_trim_inset
            width,height=layout.print_width-2*inset,layout.print_height-2*inset
            if layout.trim_mode=='both':
                from .production_geometry import cut_geometry
                geometry=cut_geometry(layout,0,1)
                if geometry:width,height=geometry[0].trim.width,geometry[0].trim.height
            self.trim_hint_var.set(f"После реза: {fmt(width)} × {fmt(height)} мм")
            from .production_geometry import MarkConflict
            self._mark_issues=()
            try:
                validate_output(self.photos, layout)
            except MarkConflict as error:
                # A valid layout with impossible marks remains inspectable.
                # Export/printing still validate it and remain disabled here.
                self._mark_issues=error.issues
            cells = layout.cells(limit=1)
            if layout.mode == 'exact':
                self.placement_row.grid()
                choices = layout.placement_choices()
                for button in self.placement_buttons:
                    button.pack(side='left', fill='x', expand=True, padx=1) if choices else button.pack_forget()
                if choices:
                    self.placement_hint.pack_forget()
                else:
                    cols, rows, *_ = layout.exact_grid()
                    self.placement_hint.configure(text=self.display_text(f'Авто · {cols}×{rows}'))
                    self.placement_hint.pack(side='left')
            else:
                self.placement_row.grid_remove()
            self.read_color_controls()  # Validate the active editor without changing global settings.
            correction = self.correction
            if layout.mode!='repeat' and not layout.duplex and self.layout and self.layout != layout and self.selected >= 0:
                self.page = self.photo_print_index(self.selected,layout) // layout.count
            self.layout, self.correction = layout, correction
            self.sync_panel_buttons()
            total = page_count(self.photos, layout)
            self.page = max(0, min(self.page, total - 1))
            items = page_items(self.photos, layout, self.page)
            self.occupancy_var.set(f"Занято {len(items)} из {layout.count} мест" if layout.mode == "cells" else "")
            if items and not layout.duplex and not any(index == self.selected for index, _ in items):
                self.selected = items[0][0]
                self.update_selection()
                self._sync_controls()
            self.page_var.set(self.side_caption(layout,self.page,total))
            if layout.duplex:
                sheets=total//2
                self.counter_var.set(f"{sheets} {'лист' if sheets%10==1 and sheets%100!=11 else 'листа' if sheets%10 in (2,3,4) and sheets%100 not in (12,13,14) else 'листов'} · {total} {'стороны' if total%10 in (2,3,4) and total%100 not in (12,13,14) else 'сторон'}")
            else:self.counter_var.set(f"Отпечатков: {print_count(self.photos)}  ·  Листов: {total}")
            self.sync_library_labels()
            self._state(self.previous_button, self.page > 0)
            self._state(self.next_button, self.page < total - 1)
            for button in (self.previous_button, self.next_button):
                if total <= 1:
                    button.grid_remove()
                else:
                    button.grid()
            for button in (self.save_button, self.print_button):
                self._state(button, bool(self.photos) and not self._exporting and self._pending_pdf is None)
            self.capacity_var.set(f"До {layout.count} {'карточек' if layout.card else 'фото'} на листе")
            if layout.mode == "booklet":
                auto=[str(i+1) for i,p in enumerate(self.booklet_leaves) if p['auto']]
                self.capacity_var.set('Добавлено для сгиба: '+str(len(auto))+(' · № '+', '.join(auto) if auto else ''))
            w, h = cells[0].width, cells[0].height
            self.size_hint_var.set(f"Лист {fmt(layout.page_size[0])} × {fmt(layout.page_size[1])} мм · "
                                   f"{'Карточка' if layout.card else 'Размер фото'} {fmt(w)} × {fmt(h)} мм")
            self.quality_var.set("")
            if 0 <= self.selected < len(self.photos):
                selected_photo, area, auto = photo_slot(self.photos[self.selected], cells[0], layout)
                ppi = effective_ppi(selected_photo, area, auto)
                if ppi < int(self.output_ppi_var.get()):
                    self.quality_var.set(f"Выбранное фото: {ppi:.0f} ppi после кадрирования — ниже {self.output_ppi_var.get()} ppi. "
                                         "Увеличение растра не добавляет деталей.")
            from .production_geometry import cut_warning
            warning=cut_warning(layout)
            if warning:self.quality_var.set(warning)
            if self._mark_issues:
                self.quality_var.set(self._mark_issues[0].message)
                self._state(self.save_button,False)
                self._state(self.print_button,False)
            if self._cut_error:
                self.quality_var.set(str(self._cut_error));self.trim_hint_var.set(str(self._cut_error))
                self._state(self.save_button,False);self._state(self.print_button,False)
            self.draw_preview()
            if self._curves_editor:
                self._curves_editor.sync()
        except (ValueError, OSError, Image.DecompressionBombError) as error:
            self.cancel_async_preview()
            self.layout = None
            self.occupancy_var.set("")
            for button in (self.save_button, self.print_button, self.previous_button, self.next_button):
                self._state(button, False)
            self.counter_var.set(f"Отпечатков: {print_count(self.photos)}  ·  Листов: —")
            self.page_var.set("Лист —")
            self.capacity_var.set("Проверьте параметры карточки / реза" if self.mode_var.get() == "Фото с рамкой"
                                  else "Размер фото не помещается / проверьте размеры")
            if self.trim_var.get() != "Нет":
                self.trim_hint_var.set(str(error))
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(max(200, self.preview_canvas.winfo_width() / 2),
                                            max(100, self.preview_canvas.winfo_height() / 2),
                                            text=self.display_text(str(error)), width=350, fill="#ab245c", font=("Segoe UI", 11), justify="center")
            self.size_hint_var.set("Вывод заблокирован до исправления параметров")
        localize_tree(self.root)

    def draw_preview(self, fast: bool = False) -> None:
        if self.layout is None:
            return
        canvas_widget = self.preview_canvas
        cw, ch = max(100, canvas_widget.winfo_width()), max(100, canvas_widget.winfo_height())
        pw, ph = self.layout.page_size
        fit_scale = max(.05, min((cw - 48) / pw, (ch - 28) / ph))
        scale = fit_scale * self.sheet_zoom
        frame = self.preview_frame(scale)
        canvas_widget.delete('preview_busy')
        if frame is None:
            if self._preview_pending:
                canvas_widget.configure(cursor='watch')
                canvas_widget.create_text(16,24,anchor='nw',text=self.display_text('Подготовка предпросмотра…'),fill='#6d6570',tags='preview_busy')
            return
        canvas_widget.configure(cursor='hand2' if self._drag is None else 'fleur')
        canvas_widget.delete("preview_overlay")
        rendered = frame.image
        x = (cw - rendered.width) / 2 + self.sheet_pan[0]
        y = (ch - rendered.height) / 2 + self.sheet_pan[1]
        self.preview_origin, self.preview_scale = (x, y), scale
        if self._preview_display_structure != frame.structure or not canvas_widget.find_withtag('preview_base'):
            canvas_widget.delete('all')
            self.preview_image = ImageTk.PhotoImage(rendered)
            self._preview_shadow = canvas_widget.create_rectangle(x+4,y+5,x+rendered.width+4,y+rendered.height+5,
                fill='#cdd0d7',outline='',tags='preview_base')
            self._preview_canvas_item = canvas_widget.create_image(x,y,image=self.preview_image,anchor='nw',tags='preview_base')
            self._preview_border = canvas_widget.create_rectangle(x,y,x+rendered.width,y+rendered.height,outline='#c0c3cb',tags='preview_base')
            self._preview_display_structure = frame.structure
        else:
            for box,tile in frame.changed:
                patch = ImageTk.PhotoImage(tile)
                self.preview_image.tk.call(str(self.preview_image),'copy',str(patch),'-to',box[0],box[1])
            canvas_widget.coords(self._preview_shadow,x+4,y+5,x+rendered.width+4,y+rendered.height+5)
            canvas_widget.coords(self._preview_canvas_item,x,y)
            canvas_widget.coords(self._preview_border,x,y,x+rendered.width,y+rendered.height)
        items = page_items(self.photos, self.layout, self.page)
        for segment in self.layout.output_segments(self.page,len(items)):
            canvas_widget.create_line(*tuple((x if i%2==0 else y)+round(v*scale) for i,v in enumerate(segment)),
                fill='black',width=max(1,round(.1*scale)),tags='preview_overlay')
        from .production_geometry import crop_mark_plan
        for issue in crop_mark_plan(self.layout,self.page,len(items))[1]:
            r=issue.region
            canvas_widget.create_rectangle(x+r.x*scale,y+r.y*scale,x+(r.x+r.width)*scale,y+(r.y+r.height)*scale,
                fill='#ffdedf',stipple='gray50',outline='#dc1745',tags='preview_overlay')
            canvas_widget.create_line(*tuple((x if i%2==0 else y)+v*scale for i,v in enumerate(issue.mark.segment)),
                fill='#dc1745',width=3,tags='preview_overlay')
        for line in fold_guides(self.layout,self.page):
            canvas_widget.create_line(*tuple((x if i%2==0 else y)+v*scale for i,v in enumerate(line)),fill='#7893a2',dash=(4,4),tags=('fold_guide','preview_overlay'))
        self._print_handle=None
        instance = self._selected_instance
        if (instance is None or instance[0] != self.page or instance[1] >= len(items)
                or items[instance[1]][0] != self.selected):
            instance = next(((self.page, slot) for slot, (index, _) in enumerate(items) if index == self.selected), None)
        self._selected_instance = instance
        current_cells=page_cells(self.photos,self.layout,self.page)
        if getattr(self,'_cut_error',None):
            for cell in current_cells:
                canvas_widget.create_rectangle(x+cell.x*scale,y+cell.y*scale,x+(cell.x+cell.width)*scale,y+(cell.y+cell.height)*scale,
                    outline='#dc1745',width=3,tags=('invalid_cut','preview_overlay'))
        for slot, ((index, photo), cell) in enumerate(zip(items, current_cells)):
            coords = (x + cell.x * scale, y + cell.y * scale,
                      x + (cell.x + cell.width) * scale, y + (cell.y + cell.height) * scale)
            canvas_widget.create_rectangle(*coords, outline=PINK if index in self.selected_rows else "#d1d3da",
                                           width=3 if instance == (self.page, slot) else 1,
                                           tags=("selected_instance" if instance == (self.page, slot) else
                                                 "selected_copy" if index in self.selected_rows else "photo_border",'preview_overlay'))
            if instance == (self.page,slot) and self.layout.mode!='repeat' and (index >= 0 or self.layout.mode=='booklet') and (self.layout.mode!='booklet' or 0 < spread_positions(len(booklet_pages(self.photos,self.layout)),self.page)[slot%2] < len(booklet_pages(self.photos,self.layout))-1):
                self._print_handle=(coords[0]+5,coords[1]+5,coords[0]+29,coords[1]+29,slot)
                canvas_widget.create_rectangle(*self._print_handle[:4],fill='white',outline=PINK,tags='preview_overlay')
                canvas_widget.create_text(coords[0]+17,coords[1]+17,text='↔',fill=PINK,tags='preview_overlay')
            if self.layout.card:
                area = self.layout.photo_area(cell)
                canvas_widget.create_rectangle(x + area.x * scale, y + area.y * scale,
                    x + (area.x + area.width) * scale, y + (area.y + area.height) * scale,
                    outline=PINK if index in self.selected_rows else "#d1d3da", width=1, tags=('card_window','preview_overlay'))
        for slot,label in enumerate(page_labels(self.photos,self.layout,self.page)):
            cell=current_cells[slot]
            if self.layout.mode=='booklet':
                caption=label
                blank=items[slot][0]<0
                if blank:caption+='\nПустая страница'
                badge_font=10 if blank else 12
                text_id=canvas_widget.create_text(x+(cell.x+cell.width)*scale-9,y+cell.y*scale+9,anchor='ne',
                    text=self.display_text(caption),fill='#32182a',font=('Segoe UI',badge_font,'bold'),
                    width=max(60,cell.width*scale-24),justify='right',tags=('page_badge','preview_overlay'))
                box=canvas_widget.bbox(text_id)
                background=canvas_widget.create_rectangle(box[0]-6,box[1]-4,box[2]+6,box[3]+4,fill='white',outline='#ab245c',width=2,tags=('page_badge_background','preview_overlay'))
                canvas_widget.tag_raise(text_id,background)
            else:
                canvas_widget.create_text(x+(cell.x+cell.width/2)*scale,y+(cell.y+cell.height)*scale-12,anchor='s',text=self.display_text(label),fill='#885470',font=('Segoe UI',10,'bold'),tags=('page_badge','preview_overlay'))
        if self.layout.trim_mode == "marks":
            for rect in self.layout.cut_rects(len(items)):
                canvas_widget.create_rectangle(x + rect.x * scale, y + rect.y * scale,
                    x + (rect.x + rect.width) * scale, y + (rect.y + rect.height) * scale,
                    outline="#8c9099", dash=(2, 3), width=1, tags=('cut_hint','preview_overlay'))
        if self.layout.mode == "cells":
            for cell in self.layout.cells()[len(items):]:
                canvas_widget.create_rectangle(x + cell.x * scale, y + cell.y * scale,
                    x + (cell.x + cell.width) * scale, y + (cell.y + cell.height) * scale,
                    outline="#b8bdc7", width=1, dash=(3, 3), tags=('empty_cell','preview_overlay'))
        if self.layout.mode=='booklet' and self.layout.booklet_page_size:
            from .production_geometry import spread_rects
            for r in spread_rects(self.layout,self.page):
                canvas_widget.create_rectangle(x+r.x*scale,y+r.y*scale,x+(r.x+r.width)*scale,y+(r.y+r.height)*scale,outline='#73818b',dash=(2,3),tags=('spread_trim','preview_overlay'))
        canvas_widget.tag_raise('fold_guide')
        if self.preview_driver_margins:
            m=self.preview_driver_margins
            canvas_widget.create_rectangle(x+m.left*scale,y+m.top*scale,x+(pw-m.right)*scale,y+(ph-m.bottom)*scale,
                outline='#ad275b',dash=(6,3),tags=('driver_printable','preview_overlay'))
        if not self.photos:
            canvas_widget.create_text(x + rendered.width / 2, y + rendered.height / 2,
                                      text=self.display_text("Перетащите фото или папку сюда"), fill="#9b9da5", justify="center", width=max(100,rendered.width-25), font=("Segoe UI", 14),tags='preview_overlay')
        if self.preview_before:
            canvas_widget.create_text(16, 6, anchor="nw", text=self.display_text("ДО · без коррекции"), fill="#6d6570", font=("Segoe UI", 9, "bold"),tags='preview_overlay')

    def add_dialog(self) -> None:
        paths = filedialog.askopenfilenames(parent=self.root, title="Добавить фотографии",
                                             filetypes=[("Фото и документы", "*.jpg *.jpeg *.png *.webp *.heic *.heif *.pdf *.psd"),('Все файлы','*.*')])
        if paths:
            self.add_paths([Path(path) for path in paths])

    def folder_dialog(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, title="Открыть папку с фотографиями")
        if not folder:
            return
        try:
            from .file_drop import folder_images
            paths, _ = folder_images(folder)
        except OSError as error:
            messagebox.showerror("Не удалось открыть папку", str(error), parent=self.root)
            return
        if not paths:
            messagebox.showinfo("Фотографии не найдены", "В папке нет поддерживаемых фото или документов. Подпапки не просматриваются.", parent=self.root)
            return
        self.add_paths(paths,folder_batch=True)

    def take_pdf_size(self):
        if not 0 <= self.selected < len(self.photos) or self.photos[self.selected].pdf_page is None:
            return
        self.mode_var.set('Задать размер фото')
        self.original_size()

    def choose_pdf_import(self, path=None, count=None):
        """One policy for a folder, or explicit page range for a single document."""
        from .document_sources import parse_pages
        window = tk.Toplevel(self.root)
        window.title(self.display_text('Импорт PDF'))
        window.transient(self.root)
        set_icon(window)
        box = ttk.Frame(window,padding=14)
        box.pack(fill='both',expand=True)
        ttk.Label(box,text=path.name if path else 'PDF в этой папке',wraplength=380).pack(anchor='w')
        choices = ('Все страницы','Диапазон страниц') if path else ('Все страницы','Только первые страницы','Пропустить PDF')
        choice = tk.StringVar(value=choices[0])
        RoundedCombo(box,choice,choices,width=32).pack(fill='x',pady=6)
        pages = tk.StringVar(value='1')
        if path:
            ttk.Label(box,text=f'1–{count} · например 1–3, 7').pack(anchor='w')
            ttk.Entry(box,textvariable=pages).pack(fill='x',pady=4)
        result = [None]
        def accept():
            try:
                result[0] = (list(range(count)) if choice.get()=='Все страницы' else parse_pages(pages.get(),count)) if path else choice.get()
            except ValueError as error:
                messagebox.showerror('Импорт PDF',str(error),parent=window)
                return
            window.destroy()
        controls = ttk.Frame(box)
        controls.pack(fill='x',pady=(8,0))
        CapsuleButton(controls,text='Отмена',command=window.destroy).pack(side='left')
        CapsuleButton(controls,text='Добавить',command=accept).pack(side='right')
        window.bind('<Return>',lambda e:accept())
        window.bind('<Escape>',lambda e:window.destroy())
        localize_tree(window)
        window.grab_set()
        window.wait_window()
        return result[0]

    def drop_paths(self, paths):
        from .file_drop import folder_images
        expanded, skipped, folder_batch = [], 0, False
        for path in paths:
            try:
                if path.is_dir():
                    folder_batch = True
                    images, ignored = folder_images(path)
                    expanded.extend(images)
                    skipped += ignored
                else:
                    expanded.append(path)
            except OSError:
                skipped += 1
        added, ignored = self.add_paths(expanded, report_errors=False,folder_batch=folder_batch)
        self.status_var.set(f'Добавлено {added} фото, пропущено {skipped + ignored} файлов')
        if self.last_import_errors:
            self.status_var.set(self.status_var.get()+' · '+self.last_import_errors[0])

    def add_paths(self, paths: list[Path], report_errors=True, folder_batch=False) -> tuple[int, int]:
        from .document_sources import pdf_pages
        from .diagnostics import record
        existing = {(photo.path.resolve(),photo.pdf_page) for photo in self.photos}
        errors = []
        added = 0
        skipped = 0
        pdf_policy = None
        if folder_batch and any(Path(p).suffix.lower()=='.pdf' for p in paths):
            pdf_policy = self.choose_pdf_import()
        for path in paths:
            try:
                path = path.resolve()
                if path.suffix.lower() not in SUPPORTED:
                    raise ValueError('Неподдерживаемый формат файла')
                pages = [None]
                if path.suffix.lower()=='.pdf':
                    if folder_batch and pdf_policy in (None,'Пропустить PDF'):
                        skipped += 1
                        continue
                    count = pdf_pages(path)
                    pages = ([0] if pdf_policy=='Только первые страницы' or count==1 else
                             list(range(count)) if pdf_policy=='Все страницы' else self.choose_pdf_import(path,count))
                    if pages is None:
                        skipped += 1
                        continue
            except Exception as error:
                skipped += 1
                errors.append(f'{path.name}: {error}')
                record('import.file.error',file=str(path),error=repr(error))
                continue
            for page in pages:
                if (path,page) in existing:
                    skipped += 1
                    continue
                photo = Photo(path,pdf_page=page)
                try:
                    image = load_preview_source(photo)
                    thumbnail = ImageOps.contain(image,(90,72),Image.Resampling.LANCZOS)
                    thumbnail_image = ImageTk.PhotoImage(thumbnail)
                except Exception as error:
                    skipped += 1
                    errors.append(f'{photo.name}: {error}')
                    record('import.file.error',file=str(path),page=page,error=repr(error))
                    continue
                self.photos.append(photo)
                self.thumbnail_images.append(thumbnail_image)
                self._add_thumbnail(len(self.photos)-1,thumbnail_image)
                existing.add((path,page))
                added += 1
        self.last_import_errors = errors
        if added:
            self.empty_label.pack_forget()
            if self.selected < 0:
                self.selected = 0
                self.selected_rows = {0}
                self.selection_anchor = 0
            self.update_selection()
            self.status_var.set(f"Добавлено: {added}. Всего фотографий: {len(self.photos)}.")
            self.custom_preset_changed()
        self.refresh()
        if errors and report_errors:
            messagebox.showwarning("Некоторые фото не добавлены", "\n".join(errors[:8]) + ("\n…" if len(errors) > 8 else ""), parent=self.root)
        return added, skipped

    def _add_thumbnail(self, index: int, image: ImageTk.PhotoImage) -> None:
        frame = tk.Frame(self.library_inner, bg="white", highlightbackground="#e4dfe5", highlightthickness=1, padx=5, pady=8)
        frame.pack(fill="x", pady=(0, 6))
        display=tk.PhotoImage(master=self.root)
        self.root.tk.call(str(display),'copy',str(image),'-subsample',2,2)
        thumb = tk.Label(frame, image=display, bg="white")
        thumb._image=display
        thumb.grid(row=0, column=1, rowspan=3, sticky="w")
        frame.columnconfigure(2,weight=1)
        label = tk.Label(frame, bg="white", fg=INK,
                         anchor="w", justify="left", font=("Segoe UI", 10, "bold"))
        label.configure(text=ellipsize(label, self.display_text(self.photos[index].name), 110))
        label._l10n_skip = True
        ToolTip(label, self.display_text(self.photos[index].name))
        label.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        copy_label = tk.Label(frame, text="Копий", bg="white", fg=MUTED, font=("Segoe UI", 9))
        copy_label.grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(4, 0))
        controls = tk.Frame(frame, bg="white")
        controls.grid(row=2, column=2, sticky="w", padx=(6, 0), pady=(2, 0))
        variable = tk.StringVar(value=str(self.photos[index].copies))
        self.copy_vars.append(variable)
        minus = CapsuleButton(controls, text="−", width=2, height=26, command=lambda: self.change_copies(index, -1))
        minus.grid(row=0, column=0)
        validator = (self.root.register(lambda text: text == "" or (text.isascii() and text.isdigit() and int(text) >= 1)), "%P")
        entry = ttk.Entry(controls, textvariable=variable, width=4, justify="center",
                          validate="key", validatecommand=validator)
        entry.grid(row=0, column=1, padx=3)
        plus = CapsuleButton(controls, text="+", width=2, height=26, command=lambda: self.change_copies(index, 1))
        plus.grid(row=0, column=2)
        duplicate=CapsuleButton(controls,text='⧉',width=2,height=26,command=lambda:self.duplicate_photo(index))
        duplicate.grid(row=0,column=3,padx=(4,0));ToolTip(duplicate,self.display_text('Дублировать'))
        self.copy_entries.append(entry)
        self.copy_buttons.append((minus, plus))
        self.copy_traces.append(variable.trace_add("write", lambda *_args: self.copies_changed(index)))
        entry.bind("<Return>", lambda event: self.commit_copies(index))
        entry.bind("<FocusOut>", lambda event: self.commit_copies(index))
        entry.bind("<FocusIn>", lambda event: self.select_photo(index))
        badge = tk.Label(frame, text="Своя кривая" if self.photos[index].curve is not None else "",
                         fg="#c53770", bg="white", font=("Segoe UI", 8))
        badge.grid(row=3, column=2, sticky="w", padx=(6, 0))
        if self.photos[index].curve is None:
            badge.grid_remove()
        self.curve_badges.append(badge)
        self.thumbnail_widgets.append((frame, thumb, label, copy_label, controls, badge))
        handle=tk.Label(frame,text='⠿',cursor='fleur',bg='white',width=2,anchor='center')
        handle.grid(row=0,column=0,rowspan=4,sticky='ns',padx=(0,4))
        frame._handle=handle
        frame.bind('<Configure>',lambda e:self.sync_library_labels())
        handle.bind('<Button-1>',lambda e,i=index:self.begin_library_move(i,e))
        handle.bind('<B1-Motion>',self.library_move_motion)
        handle.bind('<ButtonRelease-1>',self.end_library_move)
        for widget in (frame, thumb, label, copy_label):
            widget.bind("<Button-1>", lambda event, i=index: self.select_photo(i))
        frame.configure(takefocus=True)
        for widget in (frame, thumb, label, copy_label, badge):
            widget.bind("<Button-1>", lambda event, i=index: self.library_click(i, event))
            widget.bind("<Delete>", self.delete_from_list)
        self._wheel(frame, self.library_canvas)

    def copies_changed(self, index: int) -> None:
        text = self.copy_vars[index].get()
        if text.isascii() and text.isdigit() and int(text) >= 1:
            self.photos[index].copies = int(text)
        self.schedule_refresh()

    def commit_copies(self, index: int) -> None:
        if index >= len(self.copy_vars):
            return
        text = self.copy_vars[index].get()
        if not text.isascii() or not text.isdigit() or int(text) < 1:
            self.copy_vars[index].set(str(self.photos[index].copies))
        self.refresh()

    def change_copies(self, index: int, delta: int) -> None:
        self.selected = index
        self.selected_rows = {index}
        self.copy_vars[index].set(str(max(1, self.photos[index].copies + delta)))
        self.update_selection()
        self.refresh()

    def update_selection(self) -> None:
        for index, widgets in enumerate(self.thumbnail_widgets):
            chosen = index in self.selected_rows
            active = index == self.selected
            if getattr(widgets[0],'_selection_state',None)==(chosen,active):
                continue
            widgets[0]._selection_state=(chosen,active)
            color = "#ffd8e9" if chosen else "#fff0f6" if active else "#ffffff"
            widgets[0].configure(highlightbackground=PINK if chosen or active else "#e4dfe5",
                                 highlightthickness=2 if chosen else 1)
            for widget in widgets:
                widget.configure(bg=color)
                for child in widget.winfo_children():
                    if isinstance(child, CapsuleButton):
                        child.redraw()

    def select_photo(self, index: int, keep_page: bool = False, preserve_selection=False) -> None:
        if not 0 <= index < len(self.photos):
            return
        self.selected = index
        if not preserve_selection:
            self.selected_rows = {index}
            self.selection_anchor = index
        if not keep_page:
            self._selected_instance = None
        if self.layout and not keep_page:
            self.navigate_photo(index)
        self.update_selection()
        if keep_page:self.reveal_library_photo(index)
        self.refresh()

    def preview_click(self, event: tk.Event) -> None:
        if self.layout is None:
            return
        x = (event.x - self.preview_origin[0]) / self.preview_scale
        y = (event.y - self.preview_origin[1]) / self.preview_scale
        items = page_items(self.photos, self.layout, self.page)
        for (index, _photo), cell in zip(items, page_cells(self.photos,self.layout,self.page)):
            if cell.contains(x, y):
                self.select_photo(index, keep_page=True)
                return

    def turn_page(self, direction: int) -> None:
        if self.layout is None:
            return
        new_page = self.page + direction
        if 0 <= new_page < page_count(self.photos, self.layout):
            self.page = new_page
            self.update_selection()
            self.refresh()

    def rotate_photo(self) -> None:
        group = self.editing_photos()
        if group:
            before = self.frame_snapshot(group)
            for photo in group:
                photo.rotate_clockwise()
            self.remember(before)
            self.refresh()

    def selected_mode(self, mode: str) -> None:
        group = self.editing_photos()
        if group:
            before = self.frame_snapshot(group)
            for photo in group:
                photo.set_mode(mode)
            self.remember(before)
            self.refresh()

    def all_mode(self, mode: str) -> None:
        set_all_modes(self.photos, mode)
        self.refresh()

    def move_photo(self, dx: float, dy: float) -> None:
        if 0 <= self.selected < len(self.photos):
            self.photos[self.selected].move(dx, dy)
            self.refresh()

    def center_photo(self) -> None:
        if 0 <= self.selected < len(self.photos):
            self.photos[self.selected].offset_x = self.photos[self.selected].offset_y = 0
            self.refresh()

    def remove_selected(self) -> None:
        indices = sorted(i for i in self.selected_rows if 0 <= i < len(self.photos))
        if not indices:
            return
        active_photo = self.photos[self.selected] if 0 <= self.selected < len(self.photos) else None
        for index in reversed(indices):
            del self.photos[index]
            del self.thumbnail_images[index]
        for variable, trace in zip(self.copy_vars, self.copy_traces):
            variable.trace_remove("write", trace)
        self.copy_vars.clear()
        self.copy_entries.clear()
        self.copy_traces.clear()
        self.copy_buttons.clear()
        self.curve_badges.clear()
        self._drag = None
        for widgets in self.thumbnail_widgets:
            widgets[0].destroy()
        self.thumbnail_widgets.clear()
        for index, image in enumerate(self.thumbnail_images):
            self._add_thumbnail(index, image)
        self.selected = next((i for i, photo in enumerate(self.photos) if photo is active_photo),
                             min(indices[0], len(self.photos) - 1))
        self.selected_rows = {self.selected} if self.selected >= 0 else set()
        self.selection_anchor = self.selected if self.selected >= 0 else None
        self._selected_instance = None
        if not self.photos:
            self.empty_label.pack(fill="x")
        self.update_selection()
        self.refresh()

    def library_click(self, index, event):
        rows, anchor = set(self.selected_rows), self.selection_anchor
        if event.state & 1 and anchor is not None:
            self.selected_rows = set(range(min(anchor, index), max(anchor, index) + 1))
            if event.state & 4:
                self.selected_rows |= rows
            self.selection_anchor = anchor
        elif event.state & 4:
            self.selected_rows = rows ^ {index}
            self.selection_anchor = index
        else:
            self.selected_rows = {index}
            self.selection_anchor = index
        self.selected = index if index in self.selected_rows else next(iter(sorted(self.selected_rows)),-1)
        if self.layout:
            self.navigate_photo(index)
        self._selected_instance = None
        self.thumbnail_widgets[index][0].focus_set()
        self.update_selection()
        self.refresh()
        return "break"

    def delete_from_list(self, event=None):
        # Entry widgets retain their native Delete binding for copy editing.
        if event is not None and isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        self.remove_selected()
        self.library_canvas.focus_set()
        return "break"

    def fit_sheet(self):
        self.sheet_zoom, self.sheet_pan = 1.0, (0.0, 0.0)
        self.sheet_zoom_var.set("100%")
        self.draw_preview()

    def zoom_sheet(self, event):
        if self.layout is None or self._drag:
            return "break"
        previous = self.sheet_zoom
        self.sheet_zoom = min(8.0, max(.25, previous * 1.2 ** (event.delta / 120)))
        ratio = self.sheet_zoom / previous
        # Transform the page centre around the cursor; millimetre coordinates
        # beneath the cursor remain invariant, including after previous panning.
        cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height()
        pw, ph = self.layout.page_size
        origin_x = event.x - (event.x - self.preview_origin[0]) * ratio
        origin_y = event.y - (event.y - self.preview_origin[1]) * ratio
        self.sheet_pan = (origin_x - (cw - round(pw * self.preview_scale * ratio)) / 2,
                          origin_y - (ch - round(ph * self.preview_scale * ratio)) / 2)
        self.sheet_zoom_var.set(f"{self.sheet_zoom * 100:.0f}%")
        self.draw_preview(fast=True)
        return "break"

    def begin_sheet_pan(self, event):
        self._sheet_drag = (event.x, event.y, *self.sheet_pan)
        self.preview_canvas.configure(cursor="fleur")
        return "break"

    def move_sheet_pan(self, event):
        if self._sheet_drag:
            x, y, pan_x, pan_y = self._sheet_drag
            self.sheet_pan = (pan_x + event.x - x, pan_y + event.y - y)
            self.draw_preview(fast=True)
        return "break"

    def end_sheet_pan(self, event=None):
        self._sheet_drag = None
        self.preview_canvas.configure(cursor="hand2")
        return "break"

    def saturation_changed(self, value: str) -> None:
        rounded = round(float(value))
        if self.saturation_var.get() != rounded:
            self.saturation_var.set(rounded)
        self.saturation_label.configure(text=f"{rounded:+d}" if rounded else "0")

    def set_before(self, before: bool) -> None:
        self.preview_before = before
        self.refresh()

    def save_pdf(self) -> None:
        if self._pending_pdf:
            if self._pdf_recovery_window:
                self._pdf_recovery_window.lift()
            return
        self.preview_driver_margins = None
        self.refresh()
        if self.layout is None or not self.photos or self._exporting or getattr(self,'_cut_error',None) or getattr(self,'_mark_issues',()):
            return
        from .vector_pdf import pdf_export_notices
        notices=pdf_export_notices(self.photos,self.correction)
        if notices and not messagebox.askyesno('Растровый вывод отдельных страниц PDF',
                '\n'.join(notices)+'\nПродолжить сохранение?',parent=self.root):return
        filename = filedialog.asksaveasfilename(parent=self.root, title="Сохранить PDF", defaultextension=".pdf",
                                                initialfile=f"{APP_NAME}.pdf", filetypes=[("Документ PDF", "*.pdf")])
        if filename:
            self._start_export(Path(filename))

    def print_order(self) -> None:
        if self._print_dialog and self._print_dialog.window.winfo_exists():
            self._print_dialog.window.lift()
            return
        self.refresh()
        if self.layout is None or not self.photos or self._exporting or getattr(self,'_cut_error',None) or getattr(self,'_mark_issues',()):
            return
        from .print_dialog import PrintDialog
        try:
            self._print_dialog = PrintDialog(self)
        except Exception as error:
            messagebox.showerror("Ошибка прямой печати", str(error), parent=self.root)

    def _start_export(self, destination: Path) -> None:
        if self.layout is None or self._exporting or getattr(self,'_cut_error',None) or getattr(self,'_mark_issues',()):
            return
        snapshot = [replace(photo) for photo in self.photos]
        layout, correction = replace(self.layout, driver_margins=None), self.correction
        ppi = int(self.output_ppi_var.get())
        app_name = self.display_text(APP_NAME)
        self._exporting = True
        for button in (self.save_button, self.print_button):
            self._state(button, False)
        self.status_var.set("Создание PDF из исходных фотографий…")

        def worker() -> None:
            try:
                count = export_pdf(destination, snapshot, layout, correction, ppi, app_name=app_name)
                self._export_results.put((True, f"Сохранено листов: {count}. {destination}"))
            except PDFReplaceError as error:
                if self._closing:
                    error.prepared.cleanup()
                else:
                    self._export_results.put((False, error))
            except Exception as error:
                self._export_results.put((False, str(error)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_export)

    def _poll_export(self) -> None:
        try:
            ok, text = self._export_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_export)
            return
        self._exporting = False
        if isinstance(text, PDFReplaceError):
            self._pending_pdf = text.prepared
            self._show_pdf_recovery(text)
            self.refresh()
            return
        if self._pending_pdf:
            self._pending_pdf.cleanup()
            self._pending_pdf = None
        self.status_var.set(text if ok else "Не удалось сохранить PDF.")
        self.refresh()
        if not ok:
            messagebox.showerror("Ошибка экспорта PDF", text, parent=self.root)

    def _show_pdf_recovery(self, error):
        window = self._pdf_recovery_window = tk.Toplevel(self.root)
        window.title('Сохранение PDF')
        set_icon(window)
        window.transient(self.root)
        box = ttk.Frame(window, padding=16)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=str(error), wraplength=460).pack(anchor='w', pady=(0, 12))
        controls = ttk.Frame(box)
        controls.pack(fill='x')
        CapsuleButton(controls, text='Повторить', command=lambda: self._retry_pdf(error.destination)).pack(side='left', padx=3)
        CapsuleButton(controls, text='Сохранить под другим именем', command=self._save_pdf_as).pack(side='left', padx=3)
        CapsuleButton(controls, text='Отмена', command=self._cancel_pdf_recovery).pack(side='left', padx=3)
        window.protocol('WM_DELETE_WINDOW', self._cancel_pdf_recovery)
        localize_tree(window)
        window.grab_set()

    def _cancel_pdf_recovery(self):
        if self._pdf_recovery_window:
            self._pdf_recovery_window.destroy()
            self._pdf_recovery_window = None
        if self._pending_pdf:
            self._pending_pdf.cleanup()
            self._pending_pdf = None
        self.refresh()

    def _save_pdf_as(self):
        name = filedialog.asksaveasfilename(parent=self._pdf_recovery_window, title='Сохранить PDF',
                                          defaultextension='.pdf', filetypes=[('Документ PDF', '*.pdf')])
        if name:
            self._retry_pdf(Path(name))

    def _retry_pdf(self, destination):
        if self._exporting or self._pending_pdf is None:
            return
        if any(Path(destination).resolve() == photo.path.resolve() for photo in self.photos):
            messagebox.showerror('Ошибка экспорта PDF', 'Нельзя перезаписать исходную фотографию.', parent=self._pdf_recovery_window)
            return
        if self._pdf_recovery_window:
            self._pdf_recovery_window.destroy()
            self._pdf_recovery_window = None
        prepared = self._pending_pdf
        self._exporting = True
        def worker():
            try:
                prepared.commit(destination)
                self._export_results.put((True, f'Сохранено листов: {prepared.pages}. {destination}'))
            except PDFReplaceError as error:
                if self._closing:
                    error.prepared.cleanup()
                else:
                    self._export_results.put((False, error))
            except Exception as error:
                self._export_results.put((False, str(error)))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_export)


def create_root() -> tk.Tk:
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OttiskPhoto.0.1")
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
    from .diagnostics import install
    install(root)
    return root


def main() -> None:
    if len(sys.argv)>=3 and sys.argv[1] in ('--production-self-check','--polish-self-check'):
        os.environ['OTTISK_PHOTO_PREFERENCES']=str(Path(sys.argv[2]).resolve()/'qa-preferences.json')
    root = create_root()
    if len(sys.argv)>=4 and sys.argv[1] in ('--duplex-self-check','--production-self-check','--polish-self-check'):
        root.tk.call('tk','scaling',float(sys.argv[3])/100*96/72)
    app = IllusivePrintApp(root)
    if len(sys.argv)>=3 and sys.argv[1]=='--polish-self-check':
        from .polish_check import run
        root.after(150,lambda:run(app,sys.argv[2],sys.argv[3] if len(sys.argv)>=4 else '100','--keep-open' in sys.argv))
    elif len(sys.argv)>=3 and sys.argv[1]=='--production-self-check':
        from .production_check import run
        root.after(150,lambda:run(app,sys.argv[2],sys.argv[3] if len(sys.argv)>=4 else '100','--keep-open' in sys.argv))
    elif len(sys.argv)>=3 and sys.argv[1]=='--booklet-self-check':
        from .booklet_check import run
        root.after(150,lambda:run(app,sys.argv[2],'--keep-open' in sys.argv))
    elif len(sys.argv)>=4 and sys.argv[1]=='--duplex-self-check':
        from .duplex_check import run
        root.after(150,lambda:run(app,sys.argv[2],sys.argv[3],'--keep-open' in sys.argv))
    elif len(sys.argv) >= 4 and sys.argv[1] == '--to-self-check':
        from .to_check import run
        root.after(150,lambda:run(app,sys.argv[2],sys.argv[3]))
    elif len(sys.argv) >= 3 and sys.argv[1] == '--fold-self-check':
        from .fold_check import run
        root.after(150,lambda:run(app,sys.argv[2],*(sys.argv[3:5])))
    elif len(sys.argv) >= 3 and sys.argv[1] == '--project-self-check':
        from .self_check import run_project
        root.after(150, lambda: run_project(app, sys.argv[2]))
    elif len(sys.argv) >= 4 and sys.argv[1] == '--document-self-check':
        from .self_check import run_documents
        root.after(150, lambda: run_documents(app, sys.argv[2], sys.argv[3]))
    elif len(sys.argv) >= 4 and sys.argv[1] == '--drop-self-check':
        from .self_check import run_drop
        root.after(150, lambda: run_drop(app, sys.argv[2], sys.argv[3]))
    elif len(sys.argv) >= 4 and sys.argv[1] == "--self-check":
        from .self_check import run
        root.after(150, lambda: run(app, sys.argv[2], sys.argv[3:]))
    elif len(sys.argv) > 1:
        root.after(100, lambda: app.add_paths([Path(arg) for arg in sys.argv[1:]]))
    root.mainloop()
