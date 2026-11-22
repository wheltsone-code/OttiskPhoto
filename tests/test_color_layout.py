"""Focused checks for relative colour, compact settings and top-left exact grids."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

import pymupdf
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import Correction, Layout, Photo, Rect, correct_image, export_pdf, render_page
from illusive_print.print_job import PrintJob, PrintSnapshot
from tests.test_beta import FakePrinter


class ColorLayoutChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.paths = [self.folder / "first.jpg", self.folder / "second.png"]
        Image.new("RGB", (600, 900), (140, 95, 70)).save(self.paths[0])
        Image.new("RGB", (600, 900), (55, 85, 145)).save(self.paths[1])
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.root.geometry("1270x840+0+0")
        self.app.add_paths(self.paths)
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def test_two_100x150_at_a4_top_left_preview_pdf_and_incomplete_page(self):
        layout = Layout(mode="exact", print_width=100, print_height=150, margin=3, gap=0,
                        align_x="left", align_y="top")
        self.assertEqual(layout.exact_grid(), (2, 1, 100, 150))
        self.assertEqual(layout.cells(), (Rect(3, 3, 100, 150), Rect(103, 3, 100, 150)))
        photos = [Photo(path) for path in self.paths]
        path = self.folder / "top-left.pdf"
        export_pdf(path, photos, layout, Correction())
        reader = PdfReader(path)
        page = reader.pages[0]
        clips = [v for v, op in ContentStream(page.get_contents(), reader).operations if op == b"re"]
        for operands, cell in zip(clips, layout.cells()):
            x, y, w, h = [float(v) * 25.4 / 72 for v in operands]
            self.assertAlmostEqual(x, cell.x, places=4)
            self.assertAlmostEqual(297 - y - h, cell.y, places=4)
            self.assertAlmostEqual(w, 100, places=4)
            self.assertAlmostEqual(h, 150, places=4)
        preview = render_page(photos, layout, 0, Correction(), 2)
        with pymupdf.open(path) as document:
            pix = document[0].get_pixmap(matrix=pymupdf.Matrix(2 * 25.4 / 72, 2 * 25.4 / 72), alpha=False)
            rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for point in ((5, 10), (10, 10), (210, 10), (10, 310)):
                self.assertEqual(preview.getpixel(point), rendered.getpixel(point))
        photos[0].copies = 2
        last = render_page(photos, layout, 1, Correction(), 2)
        self.assertNotEqual(last.getpixel((10, 10)), (255, 255, 255))
        self.assertEqual(last.getpixel((210, 10)), (255, 255, 255))
        self.assertEqual(layout.cells(limit=1), (Rect(3, 3, 100, 150),))

    def test_zero_and_fractional_margins_no_photo_resizing(self):
        app = self.app
        app.mode_var.set("Задать размер фото")
        self.assertEqual(app.margin_var.get(), "3")
        app.paper_var.set("10 × 15 см")
        app.print_var.set("100 × 150 мм")
        app.refresh()
        self.assertIsNone(app.layout)
        self.assertIn("не помещается", app.capacity_var.get())
        app.margin_var.set("0")
        app.refresh()
        self.assertEqual(app.layout.cells(), (Rect(0, 0, 100, 150),))
        self.assertEqual(app.layout.count, 1)
        self.assertEqual(app.margin_entry.minimum, 0)
        app.margin_var.set("0,5")
        app.refresh()
        self.assertIsNone(app.layout)
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.refresh()
        self.assertEqual(app.layout.cells(limit=1)[0], Rect(30, 55, 40, 40))
        self.assertEqual(Layout(mode="exact").margin, 3)

    def test_neutral_colour_independent_slider_resets_keep_curves_and_before(self):
        app = self.app
        sample = Image.new("RGB", (1, 1), (125, 125, 125))
        self.assertEqual(correct_image(sample, Correction(temperature=0, tint=0)).tobytes(), sample.tobytes())
        warm = correct_image(sample, Correction(temperature=1)).getpixel((0, 0))
        cold = correct_image(sample, Correction(temperature=-1)).getpixel((0, 0))
        magenta = correct_image(sample, Correction(tint=1)).getpixel((0, 0))
        green = correct_image(sample, Correction(tint=-1)).getpixel((0, 0))
        self.assertGreater(warm[0], warm[1])
        self.assertGreater(warm[1], warm[2])
        self.assertEqual(warm[2], 125)
        self.assertEqual(cold[:2], (125, 125))
        self.assertGreater(cold[2], 125)
        self.assertGreater(magenta[0], 125)
        self.assertGreater(magenta[2], magenta[0])
        self.assertEqual(magenta[1], 125)
        self.assertEqual((green[0], green[2]), (125, 125))
        self.assertGreater(green[1], 125)
        app.global_curve = ((0, 0), (128, 170), (255, 255))
        own = app.photos[0].curve = ((0, 0), (128, 80), (255, 255))
        app.temperature_var.set(35)
        app.tint_var.set(-22)
        self.assertEqual(app.temperature_label.get(), "35")
        self.assertEqual(app.tint_label.get(), "-22")
        app.temperature_scale.reset()
        self.assertEqual((app._number(app.temperature_var), app._number(app.tint_var)), (0, -22))
        app.temperature_var.set(28)
        app.tint_scale.reset()
        self.assertEqual((app._number(app.temperature_var), app._number(app.tint_var)), (28, 0))
        app.saturation_var.set(30)
        app.gamma_var.set("1,13")
        app.set_before(True)
        bare = [replace(p, curve=None, correction=None) for p in app.photos]
        self.assertEqual(render_page(app.photos, app.layout, 0, app.correction, 1, apply_correction=False).tobytes(),
                         render_page(bare, app.layout, 0, Correction(), 1).tobytes())
        global_curve = app.global_curve
        app.color_reset_button.invoke()
        self.assertEqual((app._number(app.temperature_var), app._number(app.tint_var), app.saturation_var.get(), app.gamma_var.get()),
                         (0, 0, 0, "1,00"))
        self.assertEqual(app.global_curve, global_curve)
        self.assertEqual(app.photos[0].curve, own)
        self.assertTrue(app.preview_before)

    def test_compact_panel_and_smaller_window_wheel_keyboard_footer_access(self):
        app = self.app
        for mode in ("Разделить лист", "Задать размер фото"):
            app.mode_var.set(mode)
            if mode == "Задать размер фото":
                app.paper_var.set("Свой размер")
                app.print_var.set("Свой размер")
            app.refresh()
            self.root.update()
            overflow = app.settings_inner.winfo_reqheight() > app.settings_canvas.winfo_height() + 1
            self.assertEqual(app.settings_scrollbar.winfo_manager(), "grid" if overflow else "")
        self.assertTrue(app.original_button.winfo_ismapped())
        app.print_var.set("100 × 150 мм")
        app.refresh()
        self.root.update()
        self.assertFalse(app.original_button.winfo_ismapped())
        app.print_var.set("Свой размер")
        app.refresh()
        app.color_section.set_open(True)
        self.root.geometry("1100x640")
        self.root.update()
        self.assertEqual(app.settings_scrollbar.winfo_manager(), "grid")
        self.assertLessEqual(app.settings_scrollbar.winfo_width(), round(12 * app.settings_scrollbar.factor))
        app.settings_canvas.yview_moveto(0)
        app.settings_canvas.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(app.settings_canvas.yview()[0], 0)
        app.settings_canvas.yview_moveto(0)
        app.output_combo.focus_force()
        self.root.update()
        bottom = app.output_combo.winfo_rooty() + app.output_combo.winfo_height() - app.settings_canvas.winfo_rooty()
        self.assertLessEqual(bottom, app.settings_canvas.winfo_height())
        for button in (app.print_button, app.save_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())

    def test_shared_colour_pdf_print_and_missing_job_number_with_fake_queue(self):
        photos = [Photo(self.paths[0])]
        layout = Layout(mode="exact", paper_width=100, paper_height=150, print_width=100, print_height=150, margin=0)
        correction = Correction(.25, 1.12, temperature=.4, tint=-.2)
        path = self.folder / "colour.pdf"
        export_pdf(path, photos, layout, correction)
        embedded = next(iter(PdfReader(path).pages[0]["/Resources"]["/XObject"].values())).get_object()

        class NoJobNumber(FakePrinter):
            def submit(inner, *args, **kwargs):
                super().submit(*args, **kwargs)
                return None

        backend, job = NoJobNumber(), PrintJob()
        snapshot = PrintSnapshot.capture(photos, layout, correction, 0)
        job.start(snapshot, False, 300, backend, "Подмена принтера", {}, None)
        deadline = time.monotonic() + 15
        while job.state in ("preparing", "sending") and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(job.state, "sent")
        self.assertEqual(backend.calls[0][2][0].tobytes(), embedded.get_data())
        self.assertIn(("sent", "Отправлено в очередь печати"), list(job.events.queue))


if __name__ == "__main__":
    unittest.main()
