"""Opt-in frozen-app smoke test. Never calls confirm(), submit() or StartDoc.

Usage: OttiskPhoto.exe --self-check OUTPUT_FOLDER PHOTO [PHOTO ...]
Tests the real bundled app/widgets/export and reads native printer settings.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback

from pypdf import PdfReader

from .core import Layout, page_items
from .metadata import APP_NAME, ASSETS, VERSION
from .print_dialog import PrintDialog
from .print_job import PrintSnapshot


def run_project(app, output):
    """Opt-in project-density/defaults check in the actual frozen executable."""
    from PIL import Image
    from .core import source_size
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'executable': sys.executable, 'version': VERSION,
              'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}, 'sizes': []}
    checks = report['checks']

    def exported(name):
        app._start_export(output / name)
        deadline = time.monotonic() + 60
        while app._exporting and time.monotonic() < deadline:
            app.root.update()
            time.sleep(.01)
        assert not app._exporting and (output / name).is_file()
        return PdfReader(output / name)

    try:
        checks['ordinary_start_one'] = (app.mode_var.get(), app.count_var.get()) == ('Разделить лист', '1')
        app.count_var.set('4')
        app.mode_var.set('Задать размер фото')
        checks['initial_custom'] = app.print_var.get() == 'Свой размер'
        for dpi, orientation in ((72, 1), (96, 1), (300, 1), (None, 1), (72, 6)):
            path = output / f'828x1104-{dpi}-exif-{orientation}.jpg'
            exif = Image.Exif()
            exif[274] = orientation
            options = {'exif': exif}
            if dpi:
                options['dpi'] = (dpi, dpi)
            Image.new('RGB', (828, 1104), 'white').save(path, **options)
            app.add_paths([path])
            app.select_photo(len(app.photos) - 1)
            pixels = (1104, 828) if orientation == 6 else (828, 1104)
            info = source_size(app.photos[app.selected])
            assert (info.width_px, info.height_px) == pixels
            for ppi in (300, 600):
                app.output_ppi_var.set(str(ppi))
                app.original_button.invoke()
                actual = (app._number(app.print_w_var), app._number(app.print_h_var))
                expected = tuple(round(v * 25.4 / ppi, 2) for v in pixels)
                assert actual == expected, (actual, expected)
                assert app.ppi_var.get() == f'Исходный размер при {ppi} ppi'
                report['sizes'].append({'dpi': dpi, 'orientation': orientation, 'ppi': ppi, 'mm': actual})
        checks['pixel_sizes_metadata_independent_exif'] = True
        app.size_lock_var.set(False)
        app.print_w_var.set('70,10')
        app.print_h_var.set('93,47')
        from pypdf.generic import ContentStream
        for ppi in (300, 600):
            app.output_ppi_var.set(str(ppi))
            app.refresh()
            assert (app._number(app.print_w_var), app._number(app.print_h_var)) == (70.1, 93.47)
            pdf = exported(f'project-{ppi}.pdf')
            image = next(iter(pdf.pages[0]['/Resources']['/XObject'].values())).get_object()
            assert sorted((image['/Width'], image['/Height'])) == sorted((round(70.1 * ppi / 25.4), round(93.47 * ppi / 25.4)))
            clips = [v for v, op in ContentStream(pdf.pages[0].get_contents(), pdf).operations if op == b're']
            assert all(abs(x - y) < .001 for x, y in zip(sorted(float(v) * 25.4 / 72 for v in clips[0][2:]), (70.1, 93.47)))
            checks[f'manual_mm_pdf_raster_{ppi}'] = True
        checks['effective_resolution_warning'] = 'ниже 600' in app.quality_var.get()
        app.print_var.set('100 × 150 мм')
        for ppi in ('300', '600'):
            app.output_ppi_var.set(ppi)
            app.refresh()
            assert (app.layout.print_width, app.layout.print_height) == (100, 150)
        checks['preset_mm_preserved'] = True
        app.mode_var.set('Фото с рамкой')
        app.card_var.set('Polaroid 600 / SX-70 / i-Type')
        app.refresh(); app.root.update()
        checks['card_default_lines_closed_preview'] = (app.trim_var.get() == 'Линии' and not app.trim_section.opened
            and any(app.preview_canvas.type(i) == 'line' for i in app.preview_canvas.find_withtag('preview_overlay')))
        pdf = exported('polaroid-lines.pdf')
        checks['card_lines_in_pdf'] = any(op == b'S' for _, op in ContentStream(pdf.pages[0].get_contents(), pdf).operations)
        app.trim_var.set('Метки')
        app.mode_var.set('Разделить лист')
        checks['session_count'] = app.count_var.get() == '4'
        app.mode_var.set('Задать размер фото')
        checks['session_preset'] = app.print_var.get() == '100 × 150 мм'
        app.mode_var.set('Фото с рамкой')
        checks['session_cut_marks'] = app.trim_var.get() == 'Метки'
        app.language_var.set('English')
        app.root.update()
        checks['english_cut_marks'] = any('Cut marks' in app.trim_section.header.itemcget(i, 'text')
            for i in app.trim_section.header.find_all() if app.trim_section.header.type(i) == 'text')
        app.language_var.set('Русский')
        from . import app as app_module
        confirmation = app_module.messagebox.askyesno
        try:
            app_module.messagebox.askyesno = lambda *a, **kw: True
            app.reset_settings()
        finally:
            app_module.messagebox.askyesno = confirmation
        checks['reset_one'] = (app.mode_var.get(), app.count_var.get()) == ('Разделить лист', '1')
        app.mode_var.set('Задать размер фото')
        checks['reset_custom'] = app.print_var.get() == 'Свой размер'
        app.mode_var.set('Фото с рамкой')
        checks['reset_lines'] = app.trim_var.get() == 'Линии'
        report['passed'] = all(checks.values())
    except Exception:
        report['passed'] = False
        report['error'] = traceback.format_exc()
    finally:
        (output / 'project-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.root.destroy()


def tcl_drop(widget, paths):
    """Registered TkDnD binding test; explicitly not a real Explorer gesture."""
    payload = widget.tk.call('format','%s',widget.tk.call('list',*map(str,paths)))
    command = widget.tk.splitlist(widget.dnd_bind('<<Drop>>'))[0]
    widget.tk.call(command,'copy','copy',1,'','','','',payload,'Drop','','','','DND_Files','','',str(widget),0,0)
    widget.update()


def run_drop(app, output, source):
    """Packaged Tcl binding check, not a physical mouse gesture."""
    from .file_drop import folder_images
    output, source = Path(output), Path(source)
    output.mkdir(parents=True, exist_ok=True)
    report = {'frozen':bool(getattr(sys,'frozen',False)), 'executable':sys.executable,
              'cwd':str(Path.cwd()), 'checks':{}, 'method':'TkDnD registered Tcl callback, not a mouse gesture'}
    def drop(paths, hwnd):
        tcl_drop(hwnd,paths)
    try:
        checks = report['checks']
        files,_ = folder_images(source)
        album = next(p for p in source.iterdir() if p.is_dir())
        folder_files,_ = folder_images(album)
        checks['accept_main_window'] = len(app.explorer_drop.targets)==3
        checks['empty_hint'] = app.empty_label.cget('text') == 'Перетащите фото или папку сюда'
        drop(files,app.root)
        checks['multiple_images'] = [p.path for p in app.photos] == files
        before = [replace(p) for p in app.photos]
        drop([album],app.preview_canvas)
        checks['cyrillic_folder_append'] = [p.path for p in app.photos] == files+folder_files
        checks['existing_order_preserved'] = app.photos[:len(before)] == before
        checks['list_counts_preview'] = len(app.thumbnail_widgets)==len(files)+len(folder_files) and app.preview_image is not None
        report['status'] = app.status_var.get()
        report['photos'] = [str(p.path) for p in app.photos]
        drop(files,app.library_canvas)
        checks['duplicates_skipped'] = len(app.photos)==len(files)+len(folder_files)
        checks['crop_gesture_bound'] = all(app.preview_canvas.bind(event) for event in ('<Button-1>','<B1-Motion>','<ButtonRelease-1>'))
        report['ok'] = all(checks.values())
    except Exception:
        report['ok'] = False
        report['error'] = traceback.format_exc()
    finally:
        (output/'drop-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.root.destroy()


def run_documents(app, output, source):
    """Bundled readers and output check; no real drag gesture or spool submission."""
    output, source = Path(output), Path(source)
    output.mkdir(parents=True,exist_ok=True)
    report = {'frozen':bool(getattr(sys,'frozen',False)), 'executable':sys.executable,
              'cwd':str(Path.cwd()), 'method':'TkDnD Tcl callback and app UI handlers; not a real Explorer gesture', 'checks':{}}
    try:
        from .document_sources import pdf_size
        checks = report['checks']
        app.choose_pdf_import = lambda *args: 'Только первые страницы'
        tcl_drop(app.preview_canvas,[source])
        checks['mixed_import'] = len(app.photos)==6 and len(app.last_import_errors)==3
        checks['pdf_pages'] = sum(p.pdf_page is not None for p in app.photos)==2
        checks['psd'] = any(p.path.suffix=='.psd' for p in app.photos)
        checks['heic_webp'] = all(any(p.path.suffix==suffix for p in app.photos) for suffix in ('.heic','.webp'))
        index = next(i for i,p in enumerate(app.photos) if p.path.name=='Макет 70x45.pdf')
        app.select_photo(index)
        app.take_pdf_size()
        app.refresh()
        checks['page_size_70_45_paper_A4'] = (app.paper_var.get()=='A4' and abs(app._number(app.print_w_var)-70)<.001 and abs(app._number(app.print_h_var)-45)<.001)
        # Exercise the same background export used by the PDF button.
        app._start_export(output/'control.pdf')
        deadline = time.monotonic()+60
        while app._exporting and time.monotonic()<deadline:
            app.root.update()
            time.sleep(.01)
        pdf = PdfReader(output/'control.pdf')
        checks['control_pdf_A4'] = abs(float(pdf.pages[0].mediabox.width)*25.4/72-210)<.001
        report['photos'] = [p.name for p in app.photos]
        report['import_errors'] = app.last_import_errors
        checks['crop_mouse_bindings'] = all(app.preview_canvas.bind(e) for e in ('<Button-1>','<B1-Motion>','<ButtonRelease-1>'))
        app.open_curves()
        checks['curves'] = bool(app._curves_editor.window.winfo_exists())
        app._curves_editor.close()
        report['passed'] = all(checks.values())
    except Exception:
        report['passed'] = False
        report['error'] = traceback.format_exc()
    finally:
        (output/'document-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.root.destroy()


def run(app, output, paths):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"app": APP_NAME, "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "executable": sys.executable, "cwd": str(Path.cwd()), "checks": {}}
    try:
        app.root.attributes("-topmost", True)
        app.add_paths([Path(p) for p in paths])
        app.root.update()
        checks = report["checks"]
        checks["import"] = len(app.photos) == len(paths) > 0
        checks["title_icon"] = app.root.title() == APP_NAME and (ASSETS / "logo.ico").is_file()
        final_color_checks(app, output, checks)
        report['initial_photos_per_sheet'] = app.count_var.get()
        if len(app.photos)>=2:
            saved_count=app.count_var.get()
            app.count_var.set('9')
            app.refresh()
            app.root.update()
            # Configure events resize the canvas before its scheduled redraw.
            # Establish the final viewport before testing selection-only work.
            app.draw_preview()
            preview=app.preview_image
            before_structure=app._preview_renderer.frame.structure
            app.select_photo(1)
            checks['preview_selection_no_raster'] = (app.preview_image is preview and not app._preview_renderer.frame.changed)
            report['preview_cache_probe'] = dict(before=repr(before_structure),after=repr(app._preview_renderer.frame.structure),
                same_tk_image=app.preview_image is preview,dirty=len(app._preview_renderer.frame.changed))
            previous=app.photos[1].offset_x
            app.photos[1].offset_x=.37
            app.draw_preview(True)
            checks['preview_one_dirty_cell'] = (app.preview_image is preview and len(app._preview_renderer.frame.changed)==1)
            app.photos[1].offset_x=previous
            app.select_photo(0)
            app.count_var.set(saved_count)
            app.refresh()
            from .image_cache import FULL_IMAGES,PREVIEW_IMAGES
            checks['raster_cache_byte_limits'] = FULL_IMAGES.bytes<=FULL_IMAGES.budget and PREVIEW_IMAGES.bytes<=PREVIEW_IMAGES.budget
        if len(app.photos)>=3:
            from types import SimpleNamespace
            app.library_click(0,SimpleNamespace(state=0))
            app.library_click(2,SimpleNamespace(state=4))
            checks['batch_selection'] = app.selected_rows=={0,2} and app.selection_title_var.get()=='Выбрано: 2 фото'
            app.selected_mode('fit')
            checks['batch_crop'] = [p.mode for p in app.photos[:3]]==['fit','fill','fit']
            app.set_individual_color(True)
            app.temperature_var.set('12,5')
            checks['batch_temperature'] = (app.photos[0].correction.temperature==.125 and
                                           app.photos[2].correction.temperature==.125 and app.photos[1].correction is None)
            app.reset_color()
            app.set_individual_color(False)
            app.selected_mode('fill')
            app.select_photo(0)
        app.open_curves()
        app.root.update()
        editor = app._curves_editor
        app.individual_color_check.invoke()
        app.root.update()
        checks["curves_individual_tick"] = app.photos[app.selected].curve is not None and any(
            app.individual_color_check.itemcget(i, "text") == "✓" for i in app.individual_color_check.find_all()
            if app.individual_color_check.type(i) == "text")
        app.set_curve(((0, 0), (128, 160), (255, 255)), final=True)
        import win32gui
        handle = win32gui.GetParent(editor.window.winfo_id())
        checks["curves_window"] = bool(editor.window.winfo_exists() and win32gui.SendMessage(handle, 0x7F, 1, 0))
        editor.close()
        app.mode_var.set("Задать размер фото")
        app.paper_var.set("10 × 15 см")
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.gap_var.set("5")
        app.copy_vars[0].set("4")
        app.refresh()
        # Test the actual action handler and background export in the frozen app,
        # substituting only the filename picker which the desktop helper cannot target.
        from . import app as app_module
        original_picker = app_module.filedialog.asksaveasfilename
        pdfs = []
        try:
            for ppi in (300, 600):
                path = output / f"frozen-{ppi}.pdf"
                app.output_ppi_var.set(str(ppi))
                app_module.filedialog.asksaveasfilename = lambda **kwargs: str(path)
                app.save_button.invoke()
                deadline = time.monotonic() + 40
                while app._exporting and time.monotonic() < deadline:
                    app.root.update()
                    time.sleep(.01)
                reader = PdfReader(path)
                image = next(iter(reader.pages[0]["/Resources"]["/XObject"].values())).get_object()
                checks[f"pdf_{ppi}"] = (not app._exporting and image["/Width"] == round(40 * ppi / 25.4)
                                             and image["/ColorSpace"][0] == "/ICCBased")
                pdfs.append(str(path))
            app.mode_var.set("Фото с рамкой")
            app.card_var.set("Instax Mini")
            app.gap_var.set("5")
            app.trim_var.set("Метки")
            app.refresh()
            checks["card_mode"] = app.layout is not None and app.layout.card is not None
            checks["card_preview_window"] = bool(app.preview_canvas.find_withtag("card_window"))
            path = output / "frozen-cards.pdf"
            app_module.filedialog.asksaveasfilename = lambda **kwargs: str(path)
            app.save_button.invoke()
            deadline = time.monotonic() + 40
            while app._exporting and time.monotonic() < deadline:
                app.root.update()
                time.sleep(.01)
            from pypdf.generic import ContentStream
            reader = PdfReader(path)
            operations = ContentStream(reader.pages[0].get_contents(), reader).operations
            checks["card_pdf_vector_marks"] = any(op == b"S" for _, op in operations)
            rectangles = [args for args, op in operations if op == b"re"]
            checks["card_pdf_size"] = sorted(round(float(v)*25.4/72, 4) for v in rectangles[0][2:]) == [54, 86]
            pdfs.append(str(path))
            # Exercise the new full-card page through the actual button/export.
            app.card_var.set("Polaroid 600 / SX-70 / i-Type")
            app.card_page_button.invoke()
            if len(app.photos) > 1:
                app.selected_rows = set(range(1, len(app.photos)))
                app.remove_selected()
            app.copy_vars[0].set("2")
            app.refresh()
            path = output / "frozen-polaroid-two.pdf"
            app_module.filedialog.asksaveasfilename = lambda **kwargs: str(path)
            app.save_button.invoke()
            deadline = time.monotonic() + 40
            while app._exporting and time.monotonic() < deadline:
                app.root.update()
                time.sleep(.01)
            reader = PdfReader(path)
            checks["polaroid_two_exact_pages"] = len(reader.pages) == 2 and all(
                abs(float(p.mediabox.width)*25.4/72-88.47) < .0001 and
                abs(float(p.mediabox.height)*25.4/72-107.52) < .0001 for p in reader.pages)
            pdfs.append(str(path))
            layout, page = app.layout, app.page
            app.language_var.set("English")
            app.unit_var.set("in")
            checks["english_inches_preserve_order"] = app.root.title() == "Ottisk Photo" and app.layout == layout and app.page == page
            app.language_var.set("Русский")
            app.unit_var.set("mm")
            app.copy_vars[0].set("6")
        finally:
            app_module.filedialog.asksaveasfilename = original_picker
        report["pdfs"] = pdfs
        app.mode_var.set("Разделить лист")
        app.paper_var.set("A4")
        app.count_var.set("2")
        app.refresh()
        app.turn_page(1)
        app.print_button.invoke()
        app.root.update()
        dialog = app._print_dialog
        checks["print_dialog"] = bool(dialog and dialog.window.winfo_exists())
        dialog.scope_var.set("Текущий лист")
        snapshot = dialog.snapshot
        checks["current_sheet"] = snapshot.current_page == 1 and snapshot.pages(True) == (1,)
        checks["summary_actual_prints"] = f"{len(page_items(snapshot.photos, snapshot.layout, 1))} отпечатков" in dialog.summary_var.get()
        report["print_summary"] = dialog.summary_var.get()
        report["driver_problem"] = dialog.problem_var.get()
        checks["native_driver_read"] = dialog.settings is not None and dialog.paper is not None
        report["driver_paper"] = vars(dialog.paper) if dialog.paper else None
        checks["no_spool_created"] = dialog.job.state == "idle"
        dialog.close()
        app.mode_var.set('Задать размер фото')
        app.paper_var.set('A4')
        app.print_var.set('100 × 150 мм')
        app.trim_var.set('Нет')
        app.gap_var.set('2')
        app.refresh()
        checks['compact_sections_default_closed'] = not app.color_section.opened and not app.trim_section.opened
        app.placement_buttons[1].invoke(); app.refresh()
        checks['compact_beside'] = app.layout.exact_grid() == (2, 1, 100, 150)
        app.placement_buttons[2].invoke(); app.refresh()
        checks['compact_stack'] = app.layout.exact_grid() == (1, 2, 150, 100)
        checks['language_image_resources'] = all(image.width() > 0 for image in app.language_icons.values())
        app.unit_var.set('in')
        app.language_var.set('English')
        checks['compact_units_preserved'] = app.unit_var.get() == 'in' and 'mm' not in app.paper_combo.display_value('A4')
        checks['paper_popup_both_units'] = 'mm /' in app.paper_combo.popup_value('A4')
        app.root.geometry('1270x840')
        app.root.update()
        checks['compact_panel_fits'] = app.settings_inner.winfo_reqheight() <= app.settings_canvas.winfo_height()
        order = [(p.path, p.copies) for p in app.photos]
        original_confirm = app_module.messagebox.askyesno
        try:
            app_module.messagebox.askyesno = lambda *args, **kwargs: True
            app.reset_settings_button.invoke()
        finally:
            app_module.messagebox.askyesno = original_confirm
        checks['reset_keeps_order_language_units'] = ([(p.path,p.copies) for p in app.photos] == order
            and app.language_var.get() == 'English' and app.unit_var.get() == 'in')
        checks['reset_defaults_one_photo'] = app.count_var.get() == '1' and app.mode_var.get() == 'Разделить лист'
        app.language_var.set('Русский')
        app.unit_var.set('mm')
        report["passed"] = all(checks.values())
    except Exception:
        report["passed"] = False
        report["error"] = traceback.format_exc()
    finally:
        (output / "self-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.root.destroy()


def final_color_checks(app, output, checks):
    """Opt-in verification through packaged UI handlers; never submits printing."""
    from types import SimpleNamespace
    from PIL import Image, ImageDraw
    from .color import IDENTITY, curve_lut, temperature_tint
    from .core import (Correction, effective_correction, photo_image, render_photo,
                       export_pdf, _source_key)
    from .preview import render_tile

    ramp = Image.new('RGB', (256, 1))
    ramp.putdata([(v, v, v) for v in range(256)])
    for temperature, tint, selected in ((1, 0, (0, 1)), (-1, 0, (2,)), (0, 1, (0, 2)), (0, -1, (1,))):
        for amount in (.1, .2, 1):
            transformed = temperature_tint(ramp, temperature * amount, tint * amount)
            assert transformed.getpixel((0, 0)) == (0, 0, 0)
            assert transformed.getpixel((255, 0)) == (255, 255, 255)
            for channel in range(3):
                values = list(transformed.getchannel(channel).getdata())
                assert values == sorted(values)
                assert all(after >= before for before, after in enumerate(values))
                if channel in selected:
                    assert values[128] > 128 and values[248] < 255
                else:
                    assert values == list(range(256))
    checks['final_channel_gain_ramps_white_black_shoulder'] = True
    assert temperature_tint(ramp, 0, 0) is ramp
    checks['final_zero_bypass'] = True
    sample = Image.new('RGB', (2, 1))
    sample.putdata([(190, 80, 40), (40, 150, 220)])
    outputs = [temperature_tint(sample, *args).tobytes()
               for args in ((-1, 0), (1, 0), (0, -1), (0, 1))]
    checks['final_distinct_axes'] = len(set(outputs)) == 4
    layout = Layout(paper_width=60, paper_height=40, per_sheet=1, autorotate=False)
    cell = layout.cells()[0]
    source = Image.new('RGB', (900, 600), 'white')
    draw = ImageDraw.Draw(source)
    for i, rgb in enumerate(((0, 0, 0), (125, 125, 125), (190, 80, 40),
                             (40, 150, 220), (90, 180, 70), (180, 70, 180), (250, 249, 248))):
        draw.rectangle((30 + i * 120, 150, 120 + i * 120, 450), fill=rgb)
    source_path = output / 'final-white-colours.png'
    source.save(source_path)
    app.add_paths([source_path])
    app.select_photo(len(app.photos) - 1)
    photo = app.photos[app.selected]
    for individual in (False, True):
        app.set_individual_color(individual)
        scope = 'individual' if individual else 'global'
        for field in ('temperature', 'tint'):
            for value in (-100, 100):
                app.temperature_var.set('0')
                app.tint_var.set('0')
                getattr(app, field + '_var').set(str(value))
                chosen = effective_correction(photo, app.correction)
                assert getattr(chosen, field) == value / 100
                adjusted = photo_image(photo, app.correction, cell, False)
                preview = render_tile(photo, cell, adjusted.size, chosen, False, _source_key(photo.path))
                assert preview.tobytes() == adjusted.tobytes()
                assert adjusted.getpixel((0, 0)) == (255, 255, 255)
                destination = output / f'final-{scope}-{field}-{value}.pdf'
                export_pdf(destination, [photo], layout, app.correction)
                embedded = next(iter(PdfReader(destination).pages[0]['/Resources']['/XObject'].values())).get_object()
                expected = render_photo(photo, cell, app.correction,
                                        (round(60 * 300 / 25.4), round(40 * 300 / 25.4)), False)
                assert embedded.get_data() == expected.tobytes()
                checks[f'final_{scope}_{field}_{value}_preview_pdf'] = True
        app.temperature_scale.reset()
        app.tint_scale.reset()
        assert effective_correction(photo, app.correction).temperature == 0
        assert effective_correction(photo, app.correction).tint == 0
        app.reset_curve()
        app.open_curves()
        editor = app._curves_editor
        for index, point in ((0, (20, 0)), (1, (235, 255))):
            editor.selected, editor.dragging = index, True
            x, y = editor.to_canvas(*point)
            editor.motion(SimpleNamespace(x=x, y=y))
            editor.release()
            editor.delete_point()
        assert app.active_curve() == ((20, 0), (235, 255))
        lut = curve_lut(app.active_curve())
        assert lut[:21] == (0,) * 21 and lut[235:] == (255,) * 21
        chosen = effective_correction(photo, app.correction)
        adjusted = photo_image(photo, app.correction, cell, False)
        preview = render_tile(photo, cell, adjusted.size, chosen, False, _source_key(photo.path))
        assert adjusted.tobytes() == preview.tobytes()
        checks[f'final_{scope}_endpoint_drag_plateaus_preview'] = True
        app.reset_curve()
        assert app.active_curve() == IDENTITY
        editor.close()
    app.set_individual_color(False)
    app.reset_color()
    app.reset_curve()
    app.remove_selected()
    app.select_photo(0)
