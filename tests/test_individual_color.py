from dataclasses import replace
import math
from pathlib import Path
import tempfile
import time
import unittest

from PIL import Image, ImageChops
from pypdf import PdfReader

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.color import IDENTITY, temperature_tint
from illusive_print.core import Correction, Layout, Photo, effective_correction, export_pdf, photo_image, render_page, render_photo
from illusive_print.print_job import PrintJob, PrintSnapshot
from tests.support import make_photos
from tests.test_beta import FakePrinter


class IndividualColorChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.paths = make_photos(self.folder / "photos")
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.add_paths(self.paths[:2])
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def pixels(self, index):
        return photo_image(self.app.photos[index], self.app.correction, self.app.layout.cells()[0]).tobytes()

    def test_two_photos_individual_all_five_global_changes_then_disable(self):
        app = self.app
        app.temperature_var.set("−12,5")
        app.tint_var.set("6,5")
        app.saturation_var.set(20)
        app.gamma_var.set("1,12")
        app.set_curve(((0, 0), (128, 155), (255, 255)), final=True)
        before = [self.pixels(i) for i in (0, 1)]
        app.individual_color_check.invoke()
        self.assertTrue(app.individual_color_var.get())
        self.assertEqual(app.color_scope_var.get(), "Для выбранного фото")
        self.assertEqual(app.photos[0].correction, app.correction)
        self.assertEqual([self.pixels(i) for i in (0, 1)], before)
        app.temperature_var.set("25,5")
        app.tint_var.set("-18,5")
        app.saturation_var.set(40)
        app.gamma_var.set("1,27")
        app.set_curve(((0, 0), (128, 85), (255, 255)), final=True)
        own = app.photos[0].correction
        own_pixels = self.pixels(0)
        self.assertNotEqual(own_pixels, before[0])
        self.assertEqual(self.pixels(1), before[1])
        app.open_curves()
        self.assertFalse(hasattr(app._curves_editor, "individual_check"))
        self.assertIn("1,27", app._curves_editor.gamma_var.get())
        app.select_photo(1)
        self.assertFalse(app.individual_color_var.get())
        self.assertEqual(app.color_scope_var.get(), "Для всех фото")
        self.assertEqual(app._number(app.temperature_var), -12.5)
        app.temperature_var.set("-40,5")
        app.tint_var.set("12,5")
        app.saturation_var.set(-10)
        app.gamma_var.set("1,05")
        app.set_curve(((0, 0), (128, 185), (255, 255)), final=True)
        self.assertEqual(app.photos[0].correction, own)
        self.assertEqual(self.pixels(0), own_pixels)
        self.assertNotEqual(self.pixels(1), before[1])
        app.select_photo(0)
        self.assertTrue(app.individual_color_var.get())
        self.assertEqual(app._number(app.temperature_var), 25.5)
        self.assertEqual(app._number(app.tint_var), -18.5)
        self.assertEqual(app.gamma_var.get(), "1,27")
        global_color = app.correction
        app.color_reset_button.invoke()
        self.assertEqual(app.correction, global_color)
        self.assertEqual(app.photos[0].correction, Correction(curve=own.curve))
        app.individual_color_check.invoke()
        self.assertIsNone(app.photos[0].correction)
        self.assertIsNone(app.photos[0].curve)
        self.assertEqual(effective_correction(app.photos[0], app.correction), global_color)
        self.assertEqual(app._number(app.temperature_var), -40.5)
        app.set_individual_color(True)
        saved = app.photos[0].correction
        app.select_photo(1)
        app.color_reset_button.invoke()
        self.assertEqual(app.correction, Correction(curve=global_color.curve))
        self.assertEqual(app.photos[0].correction, saved)

    def test_legacy_curve_preserved_precision_half_steps_and_no_selection(self):
        app = self.app
        app.temperature_label.delete(0, "end")
        for character in "-12,5":
            app.temperature_label.insert("end", character)
            self.root.update()
        self.assertEqual(app.correction.temperature, -.125)
        app.temperature_label.step(1)
        self.assertEqual(app._number(app.temperature_var), -12)
        app.temperature_label.step(-1)
        self.assertEqual(app._number(app.temperature_var), -12.5)
        app.tint_var.set("1,5")
        self.assertEqual(app.correction.tint, .015)
        app.temperature_scale.reset()
        self.assertEqual(app._number(app.temperature_var), 0)
        self.assertEqual(app._number(app.tint_var), 1.5)
        own_curve = ((0, 0), (128, 195), (255, 255))
        app.photos[0].curve = own_curve
        before = self.pixels(0)
        app.refresh()
        self.assertTrue(app.individual_color_var.get())
        self.assertEqual(app.photos[0].correction.curve, own_curve)
        self.assertEqual(self.pixels(0), before)
        app.set_individual_color(True)
        self.assertEqual(app.photos[0].correction.curve, own_curve)
        app.reset_curve()
        self.assertEqual(app.photos[0].correction.curve, IDENTITY)
        self.assertTrue(app.individual_color_var.get())
        app.remove_selected()
        app.remove_selected()
        self.assertEqual(app.individual_color_check.cget("state"), "disabled")
        self.assertFalse(app.individual_color_var.get())

    def test_final_controls_both_scopes_and_pdf_pixels(self):
        from illusive_print.color import curve_lut
        app = self.app
        # A white/grey/colour source; the same file exercises both scopes.
        source = Image.new('RGB', (600, 400), 'white')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(source)
        draw.rectangle((100, 100, 200, 300), fill=(125, 125, 125))
        draw.rectangle((250, 100, 350, 300), fill=(190, 80, 40))
        draw.rectangle((400, 100, 500, 300), fill=(40, 150, 220))
        path = self.folder / 'final-white-background.png'
        source.save(path)
        app.add_paths([path])
        app.select_photo(len(app.photos) - 1)
        photo = app.photos[app.selected]
        layout = Layout(paper_width=60, paper_height=40, per_sheet=1, autorotate=False)
        cell = layout.cells()[0]
        for individual in (False, True):
            app.set_individual_color(individual)
            for field in ('temperature', 'tint'):
                for value in (-100, 100):
                    app.temperature_var.set('0')
                    app.tint_var.set('0')
                    getattr(app, field + '_var').set(str(value))
                    chosen = effective_correction(photo, app.correction)
                    self.assertEqual(getattr(chosen, field), value / 100)
                    adjusted = photo_image(photo, app.correction, cell, False)
                    from illusive_print.preview import render_tile
                    from illusive_print.core import _source_key
                    preview = render_tile(photo, cell, source.size, chosen, False, _source_key(photo.path))
                    self.assertEqual(preview.tobytes(), adjusted.tobytes())
                    self.assertEqual(adjusted.getpixel((0, 0)), (255, 255, 255))
                    grey = adjusted.getpixel((150, 150))
                    self.assertEqual(min(grey), 125)
                    self.assertGreater(max(grey), 125)
                    output = self.folder / f'{individual}-{field}-{value}.pdf'
                    export_pdf(output, [photo], layout, app.correction)
                    embedded = next(iter(PdfReader(output).pages[0]['/Resources']['/XObject'].values())).get_object()
                    expected = render_photo(photo, cell, app.correction,
                                            (round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4)), False)
                    self.assertEqual(embedded.get_data(), expected.tobytes())
            app.set_curve(((20, 0), (235, 255)), final=True)
            self.assertEqual(curve_lut(app.active_curve())[:21], (0,) * 21)
            chosen = effective_correction(photo, app.correction)
            adjusted = photo_image(photo, app.correction, cell, False)
            preview = render_tile(photo, cell, source.size, chosen, False, _source_key(photo.path))
            self.assertEqual(preview.tobytes(), adjusted.tobytes())
            output = self.folder / f'{individual}-endpoints.pdf'
            export_pdf(output, [photo], layout, app.correction)
            embedded = next(iter(PdfReader(output).pages[0]['/Resources']['/XObject'].values())).get_object()
            expected = render_photo(photo, cell, app.correction,
                                    (round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4)), False)
            self.assertEqual(embedded.get_data(), expected.tobytes())
            app.reset_curve()
            self.assertEqual(app.active_curve(), IDENTITY)

    def test_individual_copies_pdf_and_fake_print_keep_full_correction_snapshot(self):
        app = self.app
        app.set_individual_color(True)
        app.temperature_var.set("30,5")
        app.tint_var.set("-15,5")
        app.gamma_var.set("1,2")
        app.set_curve(((0, 0), (128, 100), (255, 255)), final=True)
        app.photos[0].copies = 2
        photos = app.photos
        layout = Layout(paper_width=100, paper_height=150, per_sheet=2)
        snapshot = PrintSnapshot.capture(photos, layout, app.correction, 0)
        own = snapshot.photos[0].correction
        self.assertEqual(own.temperature, .305)
        app.temperature_var.set("60")
        self.assertEqual(snapshot.photos[0].correction, own)
        path = self.folder / "individual.pdf"
        export_pdf(path, snapshot.photos, layout, snapshot.correction)
        reader = PdfReader(path)
        embedded = next(iter(reader.pages[0]["/Resources"]["/XObject"].values())).get_object()
        cell = layout.cells()[0]
        expected = render_photo(snapshot.photos[0], cell, snapshot.correction,
                                (round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4)))
        self.assertEqual(embedded.get_data(), expected.tobytes())
        self.assertEqual(reader.pages[0].get_contents().get_data().count(b" Do"), 2)
        backend, job = FakePrinter(), PrintJob()
        job.start(snapshot, True, 300, backend, "Подмена", {}, None)
        deadline = time.monotonic() + 15
        while job.state in ("preparing", "sending") and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(job.state, "sent")
        self.assertEqual(backend.calls[0][2][0].tobytes(),
                         render_page(snapshot.photos, layout, 0, snapshot.correction, 300 / 25.4).tobytes())


if __name__ == "__main__":
    unittest.main()
