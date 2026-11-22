from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.color import IDENTITY, curve_lut
from illusive_print.core import (Correction, Layout, Photo, Rect, correct_image, image_rect, load_source,
                                 photo_image, render_page, rotation_turns, source_size, export_pdf)
from tests.support import COLOR_SAMPLES, make_color_samples, make_photos


class ColourAndMetadataTests(unittest.TestCase):
    def test_curve_identity_shape_preservation_and_extrema(self):
        self.assertEqual(curve_lut(IDENTITY), tuple(range(256)))
        self.assertEqual(curve_lut(((0, 0), (70, 70), (180, 180), (255, 255))), tuple(range(256)))
        for points in (((0, 0), (60, 150), (180, 190), (255, 255)),
                       ((0, 30), (60, 200), (140, 20), (200, 180), (255, 240))):
            lut = curve_lut(points)
            self.assertEqual(len(lut), 256)
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                self.assertEqual(lut[x0], y0)
                self.assertEqual(lut[x1], y1)
                values = lut[x0:x1 + 1]
                self.assertTrue(all(min(y0, y1) <= value <= max(y0, y1) for value in values))
                if y1 >= y0:
                    self.assertEqual(list(values), sorted(values))
                else:
                    self.assertEqual(list(values), sorted(values, reverse=True))
        with self.assertRaises(ValueError):
            curve_lut(((0, 0), (100, 120), (100, 130), (255, 255)))

    def test_vibrance_samples_neutral_muted_saturated_and_soft_skin_guard(self):
        image = make_color_samples()
        corrected = correct_image(image, Correction(vibrance=1))
        def sat(rgb):
            return (max(rgb) - min(rgb)) / (max(rgb) or 1)
        gains = {}
        for index, (name, before) in enumerate(COLOR_SAMPLES.items()):
            after = corrected.getpixel((index * 40 + 20, 20))
            gains[name] = sat(after) - sat(before)
            if name.startswith("neutral"):
                self.assertEqual(after, before)
        self.assertGreater(gains["muted_blue"], .2)
        self.assertLess(gains["saturated_blue"], .02)
        self.assertGreater(gains["skin_warm"], 0)
        self.assertLess(gains["skin_warm"], gains["muted_blue"] * .6)

    def test_one_rgb_lut_after_gamma_and_individual_override(self):
        points = ((0, 0), (128, 180), (255, 255))
        image = Image.new("RGB", (1, 1), (50, 100, 170))
        correction = Correction(gamma=1.23, curve=points)
        expected = tuple(curve_lut(points)[round(255 * (v / 255) ** (1 / 1.23))] for v in (50, 100, 170))
        self.assertEqual(correct_image(image, correction).getpixel((0, 0)), expected)
        grey = correct_image(Image.new("RGB", (1, 1), (128, 128, 128)), Correction(curve=points)).getpixel((0, 0))
        self.assertEqual(grey, (180, 180, 180))

    def test_physical_size_ppi_exif_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = Image.new("RGB", (1200, 800), (80, 100, 150))
            no_ppi, good_ppi, bad_ppi, oriented = [folder / name for name in ("no.png", "150.jpg", "bad.png", "rotated.jpg")]
            source.save(no_ppi)
            source.save(good_ppi, dpi=(150, 150))
            source.save(bad_ppi, dpi=(1, 1))
            exif = source.getexif()
            exif[274] = 6
            source.save(oriented, dpi=(300, 300), exif=exif)
            self.assertTrue(source_size(no_ppi).fallback)
            self.assertTrue(source_size(bad_ppi).fallback)
            self.assertEqual(source_size(no_ppi).ppi, 300)
            self.assertAlmostEqual(source_size(no_ppi).millimetres[0], 101.6)
            self.assertFalse(source_size(good_ppi).fallback)
            self.assertEqual(source_size(good_ppi).ppi, 150)
            self.assertAlmostEqual(source_size(good_ppi).millimetres[0], 203.2)
            self.assertEqual((source_size(oriented).width_px, source_size(oriented).height_px), (800, 1200))
            self.assertAlmostEqual(source_size(oriented).millimetres[1], 101.6)

    def test_disable_auto_rotation_retains_manual_rotation(self):
        photo = Photo(Path("unused.jpg"), rotation=1)
        cell = Rect(0, 0, 100, 150)
        self.assertEqual(rotation_turns((1200, 800), cell, photo), 2)
        self.assertEqual(rotation_turns((1200, 800), cell, photo, False), 1)
        photo.reset_frame()
        self.assertEqual(rotation_turns((1200, 800), cell, photo, False), 0)

    def test_nine_photo_live_preview_reuses_small_images(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            photos = []
            for index in range(9):
                path = folder / f"source-{index}.png"
                Image.new("RGB", (1200, 800), (50 + index * 10, 110, 180)).save(path)
                photos.append(Photo(path))
            layout = Layout(per_sheet=9)
            render_page(photos, layout, 0, Correction(), 1, fast=True)
            with patch("illusive_print.core._read_source", side_effect=AssertionError("Original read during live edit")):
                render_page(photos, layout, 0, Correction(curve=((0, 0), (128, 180), (255, 255))), 1, fast=True)


class EditingAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.paths = make_photos(cls.folder / "фото")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.unit_var.set('mm')
        self.app.count_var.set('2')
        self.root.update()
        self.app.add_paths(self.paths[:2])
        self.root.update()

    def tearDown(self):
        if self.app._refresh_job:
            self.root.after_cancel(self.app._refresh_job)
        self.root.update_idletasks()
        self.root.destroy()

    def test_drag_both_crop_modes_and_layouts_copies_single_step_undo(self):
        app = self.app
        app.copy_vars[0].set("3")
        for layout_mode in ("Разделить лист", "Задать размер фото"):
            app.mode_var.set(layout_mode)
            if layout_mode == "Разделить лист":
                app.count_var.set("1")
            else:
                app.print_var.set("Свой размер")
                app.size_lock_var.set(False)
                app.print_w_var.set("40")
                app.print_h_var.set("70")
            for crop_mode in ("fill", "fit"):
                with self.subTest(layout=layout_mode, crop=crop_mode):
                    app.select_photo(0)
                    photo = app.photos[0]
                    photo.reset_frame()
                    photo.mode = crop_mode
                    app.refresh()
                    from illusive_print.core import page_items
                    cell = app.layout.cells(limit=len(page_items(app.photos, app.layout, app.page)))[0]
                    x = app.preview_origin[0] + (cell.x + cell.width / 2) * app.preview_scale
                    y = app.preview_origin[1] + (cell.y + cell.height / 2) * app.preview_scale
                    history = len(app._undo_stack)
                    app.begin_drag(SimpleNamespace(x=x, y=y))
                    self.assertIsNotNone(app._drag)
                    app.drag_motion(SimpleNamespace(x=x + 200, y=y + 200))
                    app.drag_motion(SimpleNamespace(x=x + 400, y=y + 400))
                    app.end_drag()
                    self.assertEqual(len(app._undo_stack), history + 1)
                    changed = max(abs(photo.offset_x), abs(photo.offset_y))
                    self.assertGreater(changed, 0)
                    self.assertTrue(-1 <= photo.offset_x <= 1 and -1 <= photo.offset_y <= 1)
                    size = load_source(photo.path).size
                    if rotation_turns(size, cell, photo, app.layout.autorotate) % 2:
                        size = size[::-1]
                    placed = image_rect(size, cell, photo)
                    if crop_mode == "fill":
                        self.assertLessEqual(placed.x, cell.x + 1e-8)
                        self.assertGreaterEqual(placed.x + placed.width, cell.x + cell.width - 1e-8)
                    else:
                        self.assertGreaterEqual(placed.y, cell.y - 1e-8)
                        self.assertLessEqual(placed.y + placed.height, cell.y + cell.height + 1e-8)
                    self.assertEqual(app.photos[1].offset_x, 0)
                    # The same Photo object owns every copy's frame state.
                    from illusive_print.core import page_items
                    self.assertTrue(all(p is photo for i, p in page_items(app.photos, app.layout, 0) if i == 0))
                    app.preview_canvas.focus_force()
                    self.root.update()
                    app.preview_canvas.event_generate("<KeyPress>", keycode=90, state=4)
                    self.root.update()
                    self.assertEqual((photo.offset_x, photo.offset_y), (0, 0))
                    self.assertEqual(photo.mode, crop_mode)

    def test_zoom_first_photo_drag_keeps_second_unchanged_then_reset(self):
        app = self.app
        app.select_photo(0)
        first, second = app.photos
        layout = app.layout
        original_first, original_second = replace(first), replace(second)
        cell, other_cell = layout.cells()
        original = render_page(app.photos, layout, 0, app.correction, 2)
        other_box = (round(other_cell.x * 2), round(other_cell.y * 2),
                     round((other_cell.x + other_cell.width) * 2), round((other_cell.y + other_cell.height) * 2))
        size = load_source(first.path).size
        if rotation_turns(size, cell, first) % 2:
            size = size[::-1]
        before = image_rect(size, cell, first)
        app.zoom_button.invoke()
        self.assertAlmostEqual(first.zoom, 1.1)
        enlarged = image_rect(size, cell, first)
        self.assertAlmostEqual(enlarged.width, before.width * 1.1)
        self.assertAlmostEqual(enlarged.height, before.height * 1.1)
        self.assertAlmostEqual(enlarged.x + enlarged.width / 2, cell.x + cell.width / 2)
        self.assertAlmostEqual(enlarged.y + enlarged.height / 2, cell.y + cell.height / 2)
        x = app.preview_origin[0] + (cell.x + cell.width / 2) * app.preview_scale
        y = app.preview_origin[1] + (cell.y + cell.height / 2) * app.preview_scale
        app.begin_drag(SimpleNamespace(x=x, y=y))
        app.drag_motion(SimpleNamespace(x=x + 80, y=y + 60))
        app.end_drag()
        self.assertGreater(max(abs(first.offset_x), abs(first.offset_y)), 0)
        placed = image_rect(size, cell, first)
        self.assertLessEqual(placed.x, cell.x + 1e-8)
        self.assertLessEqual(placed.y, cell.y + 1e-8)
        self.assertGreaterEqual(placed.x + placed.width, cell.x + cell.width - 1e-8)
        self.assertGreaterEqual(placed.y + placed.height, cell.y + cell.height - 1e-8)
        self.assertEqual(app.layout, layout)
        self.assertEqual(second, original_second)
        changed = render_page(app.photos, layout, 0, app.correction, 2)
        self.assertEqual(changed.crop(other_box).tobytes(), original.crop(other_box).tobytes())
        self.assertNotEqual(changed.tobytes(), original.tobytes())
        from illusive_print.print_job import PrintSnapshot
        from illusive_print.core import page_items
        snapshot = PrintSnapshot.capture([replace(first, copies=2), second], layout, app.correction, 0)
        self.assertTrue(all(photo.zoom == 1.1 for _, photo in page_items(snapshot.photos, layout, 0)))
        app.reset_frame_button.invoke()
        self.assertEqual(first, original_first)
        self.assertEqual(second, original_second)
        self.assertEqual(render_page(app.photos, layout, 0, app.correction, 2).tobytes(), original.tobytes())

    def test_apply_crop_only_reset_frame_and_undo(self):
        app = self.app
        first, second = app.photos
        first.mode, first.offset_x, first.rotation = "fit", .7, 1
        second.mode, second.offset_y, second.rotation = "fill", -.6, 2
        app.select_photo(0)
        app.apply_crop_button.invoke()
        self.assertEqual([p.mode for p in app.photos], ["fit", "fit"])
        self.assertEqual((first.offset_x, first.rotation, second.offset_y, second.rotation), (.7, 1, -.6, 2))
        app.undo()
        self.assertEqual([p.mode for p in app.photos], ["fit", "fill"])
        app.reset_frame_button.invoke()
        self.assertEqual((first.offset_x, first.offset_y, first.rotation, first.mode), (0, 0, 0, "fit"))
        self.assertEqual((second.offset_y, second.rotation), (-.6, 2))

    def test_custom_initial_size_lock_selection_reset_and_mm_spins(self):
        app = self.app
        app.mode_var.set("Задать размер фото")
        app.print_var.set("Свой размер")
        app.refresh()
        self.assertTrue(app.size_lock_var.get())
        self.assertAlmostEqual(app._number(app.print_w_var), 101.6, places=4)
        self.assertIn("300 ppi", app.ppi_var.get())
        app.print_w_var.set("150,5")
        self.assertAlmostEqual(app._number(app.print_h_var), 150.5 * 2 / 3, places=4)
        original = (app.print_w_var.get(), app.print_h_var.get())
        app.select_photo(1)
        self.assertEqual((app.print_w_var.get(), app.print_h_var.get()), original)
        app.original_button.invoke()
        self.assertLess(app._number(app.print_w_var), app._number(app.print_h_var))
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.print_entries[0].step(1)
        self.assertEqual(app._number(app.print_w_var), 41)
        self.assertEqual(app._number(app.print_h_var), 40)
        app.original_button.invoke()
        self.assertTrue(app.size_lock_var.get())
        self.assertAlmostEqual(app._number(app.print_h_var), 101.6, places=4)
        app.size_lock_var.set(False)
        app.paper_var.set("10 × 15 см")
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.gap_var.set("5")
        app.refresh()
        self.assertEqual(app.layout.count, 6)
        app.margin_var.set("10,5")
        app.refresh()
        self.assertEqual(app.layout.count, 2)
        self.assertEqual((app.layout.cells()[0].width, app.layout.cells()[0].height), (40, 40))
        app.margin_entry.step(1)
        self.assertEqual(app._number(app.margin_var), 11.5)

    def test_curve_scope_editor_controls_and_separate_resets(self):
        app = self.app
        app.set_curve(((0, 0), (128, 170), (255, 255)), final=True)
        app.open_curves()
        editor = app._curves_editor
        self.root.update()
        self.assertIsNone(editor.window.grab_current())
        app.individual_color_var.set(True)
        app.set_individual_color(app.individual_color_var.get())
        own = app.photos[0].curve
        self.assertEqual(own, app.global_curve)
        self.assertEqual(app.curve_badges[0]["text"], "Своя кривая")
        cell = app.layout.cells()[0]
        before = photo_image(app.photos[0], app.correction, cell).tobytes()
        app.select_photo(1)
        app.set_curve(((0, 0), (128, 70), (255, 255)), final=True)
        self.assertEqual(photo_image(app.photos[0], app.correction, cell).tobytes(), before)
        app.select_photo(0)
        app.individual_color_var.set(False)
        app.set_individual_color(app.individual_color_var.get())
        self.assertIsNone(app.photos[0].curve)
        self.assertNotEqual(photo_image(app.photos[0], app.correction, cell).tobytes(), before)
        app.individual_color_var.set(True)
        app.set_individual_color(app.individual_color_var.get())
        app.reset_curve()
        self.assertEqual(app.photos[0].curve, IDENTITY)
        self.assertTrue(app.individual_color_var.get())
        self.assertNotEqual(app.global_curve, IDENTITY)
        # Actual graph events: add, drag and delete an intermediate point.
        x, y = editor.to_canvas(100, 150)
        editor.press(SimpleNamespace(x=x, y=y))
        x, y = editor.to_canvas(110, 160)
        editor.motion(SimpleNamespace(x=x, y=y))
        editor.release()
        self.assertIn((110, 160), app.photos[0].curve)
        editor.delete_point()
        self.assertEqual(app.photos[0].curve, IDENTITY)
        app.gamma_var.set("1,23")
        app.saturation_var.set(25)
        self.assertIn("1,23", editor.gamma_var.get())
        app.reset_color()
        self.assertEqual(app.correction.gamma, 1)
        self.assertEqual(app.correction.vibrance, 0)
        self.assertNotEqual(app.global_curve, IDENTITY)
        self.assertEqual(app.photos[0].curve, IDENTITY)
        self.assertEqual(editor.gamma_var.get(), "")
        app.saturation_var.set(70)
        app.saturation_scale.reset()
        self.assertEqual(app.saturation_var.get(), 0)
        app.open_advanced()
        self.root.update()
        app.gamma_var.set("1,27")
        app.gamma_scale.reset()
        self.assertEqual(app.gamma_var.get(), "1,00")
        editor.close()

    def test_fast_curve_preview_skips_full_resolution_colour_and_before_bypasses_all_curves(self):
        app = self.app
        app.set_individual_curve(True)
        app.set_curve(((0, 0), (128, 190), (255, 255)), final=True)
        with patch("illusive_print.core._corrected_source", side_effect=AssertionError("Full original recoloured during gesture")):
            app.set_curve(((0, 0), (128, 180), (255, 255)))
        neutral = render_page(app.photos, app.layout, 0, Correction(), 1, apply_correction=False)
        corrected = render_page(app.photos, app.layout, 0, app.correction, 1)
        self.assertGreater(sum(ImageStat.Stat(ImageChops.difference(neutral, corrected)).mean), 5)
        bare = [replace(photo, curve=None, correction=None) for photo in app.photos]
        self.assertEqual(neutral.tobytes(), render_page(bare, app.layout, 0, Correction(), 1).tobytes())

    def test_capsule_keyboard_disabled_and_single_sheet_navigation(self):
        app = self.app
        self.assertEqual(app.previous_button.winfo_manager(), "")
        self.assertEqual(app.next_button.winfo_manager(), "")
        button = app.rotate_button
        button.focus_force()
        self.root.update()
        button.event_generate("<KeyPress-space>")
        self.root.update()
        self.assertEqual(app.photos[0].rotation, 1)
        button.configure(state="disabled")
        button.invoke()
        self.assertEqual(app.photos[0].rotation, 1)
        button.configure(state="normal")
        app.undo()
        self.assertEqual(app.photos[0].rotation, 0)
        app.copy_vars[0].set("4")
        app.refresh()
        self.assertEqual(app.next_button.winfo_manager(), "grid")

    def test_final_pdf_includes_global_and_individual_curves_after_drag(self):
        app = self.app
        app.copy_vars[0].set("2")
        app.global_curve = ((0, 0), (128, 160), (255, 255))
        app.photos[0].curve = ((0, 0), (128, 85), (255, 255))
        app.photos[0].offset_x = .6
        app.photos[1].rotation = 1
        app.gamma_var.set("1,15")
        app.saturation_var.set(20)
        app.refresh()
        output = self.folder / "individual-and-global.pdf"
        export_pdf(output, app.photos, app.layout, app.correction)
        import pymupdf
        with pymupdf.open(output) as document:
            for index, page in enumerate(document):
                preview = render_page(app.photos, app.layout, index, app.correction, 2)
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2 * 25.4 / 72, 2 * 25.4 / 72), alpha=False)
                pdf = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).crop((0, 0, preview.width, preview.height))
                self.assertLess(max(ImageStat.Stat(ImageChops.difference(preview, pdf)).mean), 4.5)
        self.assertEqual(len(PdfReader(output).pages), 2)


if __name__ == "__main__":
    unittest.main()
