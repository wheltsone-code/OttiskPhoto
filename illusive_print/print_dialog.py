"""Per-job printer settings and confirmation; workers never touch Tk."""
import queue
import tkinter as tk
from tkinter import ttk
from .i18n import filedialog, messagebox, localize_tree
from pathlib import Path

from .color_management import OutputProfile, ProfileStore, installed_profiles
from .core import page_count, page_items, effective_ppi
from .metadata import APP_NAME, set_icon
from .print_job import PrintJob, PrintSnapshot
from .widgets import CapsuleButton, RoundedCombo
from .windows_print import WindowsPrinter
from .diagnostics import record

PRINTER_COLOR = "Цветом управляет принтер"
APP_COLOR = f"Цветом управляет {APP_NAME}"


class PrintDialog:
    def __init__(self, app, backend=None, store=None):
        self.app = app
        self.snapshot = PrintSnapshot.capture(app.photos, app.layout, app.correction, app.page)
        self.backend, self.store = backend or WindowsPrinter(), store or ProfileStore()
        self.job, self.settings, self.paper = PrintJob(), None, None
        self.inspection_error = ''
        self._confirming = False
        self._poll_job = None
        self.profile = None
        self.window = tk.Toplevel(app.root)
        self.window.title(f"Печать — {APP_NAME}")
        set_icon(self.window)
        self.window.transient(app.root)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self.destroyed, add=True)
        self.window.bind("<Return>", lambda e: self.confirm())
        self.window.bind("<Escape>", lambda e: self.close())
        box = ttk.Frame(self.window, padding=18)
        box.pack(fill="both", expand=True)
        box.columnconfigure(1, weight=1)
        self.printer_var = tk.StringVar()
        self.color_var = tk.StringVar(value=PRINTER_COLOR)
        self.scope_var = tk.StringVar(value="Все листы")
        self.ppi_var = tk.StringVar(value=app.output_ppi_var.get())
        self.icc_var = tk.StringVar()
        self.summary_var = tk.StringVar()
        self.problem_var = tk.StringVar()
        self.progress_var = tk.StringVar()
        try:
            printers = self.backend.printers()
            printer_error = ""
        except Exception as error:
            printers, printer_error = [], str(error)
        for row, label in enumerate(("Принтер", "Разрешение вывода", "Объём печати", "Управление цветом")):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.printer_combo = RoundedCombo(box, self.printer_var, printers, width=34)
        self.printer_combo.grid(row=0, column=1, sticky="ew")
        self.ppi_combo = RoundedCombo(box, self.ppi_var, ("300", "600"), width=34)
        self.ppi_combo.grid(row=1, column=1, sticky="ew")
        self.scope_combo = RoundedCombo(box, self.scope_var, ("Все листы", "Текущий лист"), width=34)
        self.scope_combo.grid(row=2, column=1, sticky="ew")
        self.color_combo = RoundedCombo(box, self.color_var, (PRINTER_COLOR, APP_COLOR), width=34)
        self.color_combo.grid(row=3, column=1, sticky="ew")
        self.properties_button = CapsuleButton(box, text="Свойства принтера…", command=self.properties)
        self.properties_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(7, 5))
        self.icc_box = ttk.Frame(box)
        self.icc_box.grid(row=5, column=0, columnspan=2, sticky="ew")
        profiles = installed_profiles()
        self.profile_paths = {f"{p.name} · {p.parent}": p for p in profiles}
        self.profile_combo = RoundedCombo(self.icc_box, self.icc_var, tuple(self.profile_paths), width=42)
        self.profile_combo.pack(fill="x", pady=3)
        CapsuleButton(self.icc_box, text="Выбрать ICC из файла…", command=self.choose_profile).pack(fill="x")
        self.profile_hint = tk.StringVar()
        ttk.Label(self.icc_box, textvariable=self.profile_hint, wraplength=490, style="Muted.TLabel").pack(anchor="w", pady=4)
        edge_hint = ("Поля 0 мм: драйвер может обрезать край, а «Без полей» может увеличить изображение. "
                     if self.snapshot.layout.mode == "exact" and self.snapshot.layout.margin == 0
                     else "Для точных размеров отключите «Без полей». ")
        warning = (edge_hint +
                   "Приложение печатает в масштабе 100%; драйвер может обрезать края листа.\n"
                   "«Без полей», внутреннее увеличение и цветокоррекцию драйвера проверить нельзя — задайте их вручную в свойствах.")
        if self.snapshot.layout.duplex:
            edge='короткому' if self.snapshot.layout.binding_edge=='short' else 'длинному'
            warning = f"В свойствах принтера включите двустороннюю печать с переворотом по {edge} краю. " + warning
        ttk.Label(box, text=warning, wraplength=505, style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(box, textvariable=self.problem_var, foreground="#ad275b", wraplength=505).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Separator(box).grid(row=8, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(box, textvariable=self.summary_var, wraplength=505, font=("Segoe UI", 10, "bold")).grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Label(box, textvariable=self.progress_var, wraplength=505).grid(row=10, column=0, columnspan=2, sticky="w", pady=8)
        controls = ttk.Frame(box)
        controls.grid(row=11, column=0, columnspan=2, sticky="ew")
        self.override_box = ttk.Frame(box)
        self.override_box.grid(row=12, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        self.return_properties_button = CapsuleButton(self.override_box, text='Вернуться в свойства', command=self.properties)
        self.return_properties_button.pack(side='left', padx=(0, 5))
        self.override_button = CapsuleButton(self.override_box, text='Печатать с настройками драйвера', command=self.confirm_override)
        self.override_button.pack(side='right')
        self.cancel_button = CapsuleButton(controls, text="Отмена", command=self.close)
        self.cancel_button.pack(side="left")
        self.confirm_button = CapsuleButton(controls, text="Печатать", style="Accent.TButton", command=self.confirm)
        self.confirm_button.pack(side="right")
        self.inputs = (self.printer_combo, self.ppi_combo, self.scope_combo, self.color_combo, self.properties_button, self.profile_combo)
        self.printer_var.trace_add("write", self.printer_changed)
        self.color_var.trace_add("write", self.color_changed)
        self.icc_var.trace_add("write", self.profile_changed)
        self.ppi_var.trace_add("write", self.update_summary)
        self.scope_var.trace_add("write", self.update_summary)
        if printers:
            default = self.backend.default()
            self.printer_var.set(default if default in printers else printers[0])
        else:
            self.problem_var.set("В Windows нет доступных принтеров. Установите драйвер и откройте диалог заново. " + printer_error)
        self.color_changed()
        self.window.grab_set()
        self._poll_job = self.window.after(70, self.poll)
        localize_tree(self.window)

    def destroyed(self, event):
        if event.widget == self.window:
            self.job.cancel()
            if self._poll_job:
                self.window.after_cancel(self._poll_job)
                self._poll_job = None

    @property
    def current(self):
        return self.scope_var.get() == "Текущий лист"

    def profile_key(self):
        layout = self.snapshot.layout
        mode = self.backend.profile_mode(self.settings) if self.settings is not None else ""
        return f"{self.printer_var.get()}|{layout.paper_width:g}x{layout.paper_height:g}|{layout.mode}|{mode}"

    def printer_changed(self, *_):
        self.problem_var.set("")
        self.settings, self.paper, self.inspection_error = None, None, ''
        try:
            self.settings = self.backend.configure(self.printer_var.get(), self.snapshot.layout)
            self.inspect_current()
        except Exception as error:
            self.inspection_error = str(error)
        self.restore_profile()
        self.update_summary()

    def inspect_current(self):
        self.paper, self.inspection_error = None, ''
        try:
            self.paper = self.backend.inspect(self.printer_var.get(), self.settings)
            self.app.preview_driver_margins=getattr(self.paper,'margins',None)
            if self.app.preview_driver_margins:self.app.draw_preview(fast=True)
        except Exception as error:
            self.inspection_error = str(error)

    def format_problem(self):
        if self.paper is not None:
            return self.paper.mismatch(self.snapshot.layout)
        w, h = self.snapshot.layout.page_size
        return f'Макет: {w:g} × {h:g} мм.\nФормат бумаги драйвера не подтверждён. {self.inspection_error}'

    def restore_profile(self):
        path = self.store.get(self.profile_key())
        self.icc_var.set(str(path) if path else "")

    def properties(self):
        if self.job.state in ("preparing", "sending", "sent") or self.settings is None:
            return
        try:
            returned = self.backend.properties(self.window.winfo_id(), self.printer_var.get(), self.settings)
            if returned is not None:
                self.settings = returned
                self.inspect_current()
                self.restore_profile()
        except Exception as error:
            self.inspection_error = str(error)
            self.paper = None
        self.update_summary()

    def choose_profile(self):
        if self.job.state in ("preparing", "sending", "sent"):
            return
        path = filedialog.askopenfilename(parent=self.window, title="Выбрать выходной ICC",
                                          filetypes=[("Цветовые профили", "*.icc *.icm")])
        if path:
            self.icc_var.set(path)

    def color_changed(self, *_):
        if self.color_var.get() == APP_COLOR:
            self.icc_box.grid()
        else:
            self.icc_box.grid_remove()
        self.profile_changed()

    def profile_changed(self, *_):
        self.profile = None
        self.profile_hint.set("")
        if self.color_var.get() == APP_COLOR:
            path = self.profile_paths.get(self.icc_var.get(), Path(self.icc_var.get()))
            try:
                self.profile = OutputProfile.read(path)
                self.profile_hint.set(self.profile.name + " · вручную отключите цветокоррекцию в свойствах драйвера.")
            except ValueError as error:
                self.profile_hint.set("Выберите пригодный RGB ICC заново. " + str(error))
        self.update_summary()

    def update_summary(self, *_):
        if not hasattr(self, "confirm_button"):
            return
        layout = self.snapshot.layout
        count = page_count(self.snapshot.photos, layout)
        scope = f"текущий лист {self.snapshot.current_page + 1} из {count}" if self.current else f"все листы: {count}"
        if layout.duplex:
            scope=(f"текущий лист {self.snapshot.current_page//2+1} из {count//2} · 2 стороны" if self.current else f"все листы: {count//2} · {count} сторон")
        dimensions = (self.paper.width, self.paper.height) if self.paper else layout.page_size
        orientation = "альбомная" if dimensions[0] > dimensions[1] else "книжная"
        icc = f" · ICC: {self.profile.name}" if self.profile else " · sRGB"
        driver_size = (f'{self.paper.name + " " if self.paper.name else ""}({self.paper.width:g} × {self.paper.height:g} мм)'
                       if self.paper else 'Формат бумаги драйвера не подтверждён')
        self.summary_var.set(f"{self.printer_var.get() or 'Принтер не выбран'} · Бумага: {driver_size} · "
                             f"{orientation} · {self.ppi_var.get()} ppi · {scope} · "
                             f"{self.snapshot.prints(self.current)} отпечатков\nМакет: {layout.paper_width:g} × {layout.paper_height:g} мм\n{self.color_var.get()}{icc}")
        if self.paper and (self.paper.width < layout.paper_width - .1 or self.paper.height < layout.paper_height - .1):
            self.summary_var.set(self.summary_var.get() + '\nКрая макета могут быть обрезаны')
        if self.paper:
            from .production_geometry import clipping_warning
            warning=clipping_warning(self.snapshot.photos,layout,self.paper,self.snapshot.current_page if self.current else None)
            if warning:self.summary_var.set(self.summary_var.get()+'\n'+warning)
        mismatch = self.format_problem()
        self.problem_var.set(mismatch)
        if mismatch:
            self.override_box.grid()
        else:
            self.override_box.grid_remove()
        valid = self.settings is not None and self.paper is not None and not mismatch
        valid &= self.color_var.get() != APP_COLOR or self.profile is not None
        valid &= self.job.state not in ("preparing", "sending", "sent")
        self.confirm_button.configure(state="normal" if valid else "disabled")
        manual_valid = (self.settings is not None and self.job.state not in ('preparing', 'sending', 'sent')
                        and (self.color_var.get() != APP_COLOR or self.profile is not None))
        self.override_button.configure(state='normal' if manual_valid else 'disabled')
        self.return_properties_button.configure(state='normal' if self.settings is not None and manual_valid else 'disabled')
        record('printer.summary', printer=self.printer_var.get(), summary=self.summary_var.get(), problem=mismatch)

    def confirm_override(self):
        return self.confirm(manual=True)

    def confirm(self, manual=False):
        if self._confirming or self.job.state in ("preparing", "sending", "sent"):
            return "break"
        self.update_summary()
        if (self.override_button if manual else self.confirm_button).cget("state") == "disabled":
            return "break"
        # Recheck at the last boundary; changing global driver defaults cannot
        # silently alter this captured per-job DEVMODE.
        try:
            self.inspect_current()
            mismatch = self.format_problem()
            if mismatch and not manual:
                self.problem_var.set(mismatch)
                self.update_summary()
                return "break"
            if manual:
                self._confirming = True
                warning = mismatch + '\nПечать с настройками текущего задания драйвера: масштаб 100%, без подгонки.'
                if self.paper and (self.paper.width < self.snapshot.layout.paper_width - .5
                                   or self.paper.height < self.snapshot.layout.paper_height - .5):
                    warning += '\nБумага меньше макета: края изображения могут быть обрезаны.'
                elif not self.paper:
                    warning += '\nРазмер бумаги неизвестен: возможна обрезка краёв.'
                try:
                    accepted = messagebox.askyesno('Печатать с настройками драйвера', warning, parent=self.window, default='no')
                finally:
                    self._confirming = False
                if not accepted:
                    return 'break'
            profile = OutputProfile.read(self.profile.path) if self.color_var.get() == APP_COLOR else None
            if profile:
                self.store.put(self.profile_key(), profile.path)
        except Exception as error:
            self.problem_var.set(str(error))
            return "break"
        self.app.output_ppi_var.set(self.ppi_var.get())
        options = {'allow_driver_settings': True} if manual else {}
        if self.job.start(self.snapshot, self.current, int(self.ppi_var.get()), self.backend,
                          self.printer_var.get(), self.settings, profile, **options):
            self.confirm_button.configure(state="disabled")
            self.override_button.configure(state='disabled')
            self.return_properties_button.configure(state='disabled')
            for widget in self.inputs:
                widget.configure(state="disabled")
            self.progress_var.set("Подготовка листов…")
        return "break"

    def poll(self):
        self._poll_job = None
        if not self.window.winfo_exists():
            return
        while True:
            try:
                kind, text = self.job.events.get_nowait()
            except queue.Empty:
                break
            self.progress_var.set(text)
            if kind == "sending":
                self.cancel_button.configure(state="disabled")
            elif kind in ("sent", "error", "cancelled"):
                self.app.status_var.set(text)
                self.cancel_button.configure(text="Закрыть", state="normal")
                if kind != "sent":
                    for widget in self.inputs:
                        widget.configure(state="normal")
                    self.update_summary()
                if kind == "error":
                    messagebox.showerror("Ошибка прямой печати", text + "\nАвтоматическая повторная отправка не выполняется.", parent=self.window)
        self._poll_job = self.window.after(70, self.poll)

    def close(self):
        if self.job.state == "preparing":
            if self.job.cancel():
                self.progress_var.set("Отмена подготовки… Задание не будет создано.")
            return "break"
        if self.job.state == "sending":
            self.progress_var.set("Передача задания Windows уже началась. Дождитесь результата.")
            return "break"
        self.window.grab_release()
        self.window.destroy()
        self.app._print_dialog = None
        self.app.refresh()
        return "break"
