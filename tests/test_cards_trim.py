"""Physical card/window sizes and shared cut geometry; no real print queue."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

import pymupdf
from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import (CARD_TEMPLATES, CardTemplate, Correction, Layout, Photo, Rect,
    export_pdf, photo_slot, render_page, validate_output)
from illusive_print.print_job import PrintJob, PrintSnapshot
from tests.support import make_photos
from tests.test_beta import FakePrinter


def pdf_rectangles(path):
    reader = PdfReader(path)
    return [[tuple(float(v) * 25.4 / 72 for v in args) for args, op in
             ContentStream(page.get_contents(), reader).operations if op == b"re"] for page in reader.pages]


class CardGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.paths = make_photos(self.folder / "photos")

    def tearDown(self):
        self.temp.cleanup()

    def test_all_preset_card_and_window_dimensions_measured_in_pdf(self):
        expected = ((88.47, 107.52, 78.94, 76.81, 4.8), (54, 86, 46, 62, 4),
                    (72, 86, 62, 62, 5), (108, 86, 99, 62, 5))
        solid = self.folder / "solid.png"
        Image.new("RGB", (800, 600), (75, 125, 180)).save(solid)
        for (name, card), dimensions in zip(CARD_TEMPLATES.items(), expected):
            with self.subTest(template=name):
                self.assertEqual((card.width, card.height, card.window_width, card.window_height, card.top), dimensions)
                self.assertAlmostEqual(card.left, (card.width-card.window_width)/2)
                layout = Layout(mode="exact", paper_width=card.width+12, paper_height=card.height+12,
                                print_width=card.width, print_height=card.height, card=card, margin=6,
                                trim_mode="lines")
                self.assertEqual(layout.count, 1)
                self.assertFalse(layout.card_turned)
                photo = Photo(solid)
                correction = Correction(temperature=.7, gamma=1.1)
                path = self.folder / f"{name.split()[0]}-{card.width}.pdf"
                export_pdf(path, [photo], layout, correction)
                outer, window = pdf_rectangles(path)[0]
                for actual, target in zip(outer[2:], (card.width, card.height)):
                    self.assertAlmostEqual(actual, target, places=4)
                for actual, target in zip(window[2:], (card.window_width, card.window_height)):
                    self.assertAlmostEqual(actual, target, places=4)
                self.assertAlmostEqual(window[0] - outer[0], card.left, places=4)
                self.assertAlmostEqual(outer[1] + outer[3] - window[1] - window[3], card.top, places=4)
                preview = render_page([photo], layout, 0, correction, 4)
                with pymupdf.open(path) as doc:
                    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(4 * 25.4 / 72, 4 * 25.4 / 72), alpha=False)
                    output = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                # White frame is never included in the photo colour correction.
                white_point = (round((6 + card.width/2)*4), round((6 + card.height-3)*4))
                image_point = (round((6+card.width/2)*4), round((6+card.top+card.window_height/2)*4))
                self.assertEqual(preview.getpixel(white_point), (255, 255, 255))
                self.assertEqual(output.getpixel(white_point), (255, 255, 255))
                self.assertEqual(preview.getpixel(image_point), output.getpixel(image_point))
                box = (0, 0, min(preview.width, output.width), min(preview.height, output.height))
                # PDF antialiases a 0.1 mm vector stroke; the low-res preview
                # uses one screen pixel. Exact path coordinates are checked above.
                self.assertLess(max(ImageStat.Stat(ImageChops.difference(preview.crop(box), output.crop(box))).mean), 4)

    def test_mini_zero_edge_cut_and_whole_card_rotation_including_square_window(self):
        for name in ("Instax Mini", "Instax Square"):
            card = CARD_TEMPLATES[name]
            native = Layout(mode="exact", paper_width=card.width+12, paper_height=card.height+12,
                            print_width=card.width, print_height=card.height, card=card, margin=6, trim_mode="lines")
            rotated = replace(native, paper_width=native.paper_height, paper_height=native.paper_width)
            self.assertTrue(rotated.card_turned)
            photo = Photo(self.paths[0], zoom=1.2, offset_x=.35, offset_y=-.2, rotation=1)
            a = render_page([photo], replace(native, trim_mode="none"), 0, Correction(), 5).transpose(Image.Transpose.ROTATE_270)
            b = render_page([photo], replace(rotated, trim_mode="none"), 0, Correction(), 5)
            self.assertLess(max(ImageStat.Stat(ImageChops.difference(a, b)).mean), .1)
            cell = rotated.cells(limit=1)[0]
            self.assertEqual(rotated.cut_rects(1), (cell,))
            window = rotated.photo_area(cell)
            self.assertAlmostEqual(window.x, cell.x+card.height-card.top-card.window_height)
            self.assertAlmostEqual(window.y, cell.y+card.left)
            path = self.folder / f"turned-{name}.pdf"
            export_pdf(path, [photo], rotated, Correction())
            outer, inside = pdf_rectangles(path)[0]
            self.assertAlmostEqual(outer[2], card.height, places=4)
            self.assertAlmostEqual(outer[3], card.width, places=4)
            self.assertAlmostEqual(inside[2], card.window_height, places=4)
            self.assertAlmostEqual(inside[3], card.window_width, places=4)

    def test_trim_140_to_136_preserves_layout_photo_size_and_shared_edges(self):
        layout = Layout(mode="exact", print_width=140, print_height=140)
        trimmed = replace(layout, trim_mode="lines", trim_inset=2)
        self.assertEqual(layout.cells(), trimmed.cells())
        self.assertTrue(all((r.width, r.height) == (136, 136) for r in trimmed.cut_rects()))
        path = self.folder / "136.pdf"
        export_pdf(path, [Photo(self.paths[0], copies=2)], trimmed, Correction())
        self.assertTrue(all(abs(r[2]-140)<.0001 and abs(r[3]-140)<.0001 for r in pdf_rectangles(path)[0]))
        # The cut rectangle is vector linework; the original photo clip stays 140.
        with pymupdf.open(path) as doc:
            cuts = [d for d in doc[0].get_drawings() if d["type"] == "s"]
            self.assertEqual(len(cuts), len(trimmed.cut_segments(2)))
        touching = Layout(mode="exact", paper_width=100, paper_height=50, margin=0,
                          print_width=50, print_height=50, trim_mode="lines")
        segments = touching.cut_segments(2)
        self.assertEqual(len(segments), 5)
        self.assertEqual(segments.count((50, 0, 50, 50)), 1)
        for invalid in (70, 71, -1, float("nan")):
            with self.assertRaises(ValueError):
                replace(trimmed, trim_inset=invalid).validate()
        self.assertEqual(replace(trimmed, trim_mode="none", trim_inset=999).cut_segments(), ())

    def test_marks_outside_all_finished_cards_vector_only_and_insufficient_space(self):
        card = CARD_TEMPLATES["Instax Mini"]
        layout = Layout(mode="exact", print_width=card.width, print_height=card.height, card=card,
                        gap=5, trim_mode="marks")
        photos = [Photo(self.paths[0], copies=layout.count+1)]
        validate_output(photos, layout)
        for count in (1, layout.count):
            segments = layout.cut_segments(count)
            self.assertGreater(len(segments), 0)
            for x0, y0, x1, y1 in segments:
                self.assertTrue(.049 <= min(x0, x1) <= max(x0, x1) <= layout.paper_width-.049)
                self.assertTrue(.049 <= min(y0, y1) <= max(y0, y1) <= layout.paper_height-.049)
                for rect in layout.cut_rects(count):
                    overlap_x = max(x0, x1)+.049 > rect.x and min(x0, x1)-.049 < rect.x+rect.width
                    overlap_y = max(y0, y1)+.049 > rect.y and min(y0, y1)-.049 < rect.y+rect.height
                    if overlap_x and overlap_y:
                        # Marks now deliberately enter the finished edge by 1 mm.
                        vertical = x0 == x1
                        overlap = (min(max(y0, y1), rect.y+rect.height)-max(min(y0, y1), rect.y) if vertical else
                                   min(max(x0, x1), rect.x+rect.width)-max(min(x0, x1), rect.x))
                        self.assertLessEqual(overlap, 1.00001)
        path = self.folder / "marks.pdf"
        export_pdf(path, photos, layout, Correction())
        with pymupdf.open(path) as doc:
            self.assertEqual(len([d for d in doc[0].get_drawings() if d["type"] == "s"]), len(layout.cut_segments(layout.count)))
        tight = replace(layout, card=None, paper_width=54, paper_height=86, margin=0, gap=0)
        with self.assertRaisesRegex(ValueError, "увеличьте поле минимум") as conflict:
            validate_output(photos[:1], tight)
        self.assertNotIn('или зазор',str(conflict.exception))
        blocked = self.folder / "blocked.pdf"
        with self.assertRaises(ValueError):
            export_pdf(blocked, photos[:1], tight, Correction())
        self.assertFalse(blocked.exists())
        with self.assertRaises(ValueError):
            PrintSnapshot.capture(photos[:1], tight, Correction(), 0)
        # The same marks/card rendering is used for direct print, with a fake queue.
        backend, job = FakePrinter(), PrintJob()
        snapshot = PrintSnapshot.capture([Photo(self.paths[0])], layout, Correction(), 0)
        job.start(snapshot, False, 300, backend, "Подмена", {}, None)
        deadline = time.monotonic()+15
        while job.state in ("preparing", "sending") and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(job.state, "sent")
        self.assertEqual(backend.calls[0][2][0].tobytes(), render_page(snapshot.photos, layout, 0, Correction(), 300/25.4).tobytes())

    def test_custom_invalid_window(self):
        for card in (CardTemplate(54, 86, 60, 62, 4, 4), CardTemplate(54, 86, 46, 82, 5, 4),
                     CardTemplate(54, 86, 46, 62, -1, 4)):
            with self.assertRaises(ValueError):
                card.validate()


class CardControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.root.geometry("1270x840")
        self.app.add_paths(make_photos(Path(self.temp.name))[:2])
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def test_presets_custom_error_trim_status_restore_and_white_border_no_drag(self):
        app = self.app
        app.mode_var.set("Фото с рамкой")
        self.assertEqual(app.card_combo.winfo_manager(), "grid")
        self.assertEqual(app.print_combo.winfo_manager(), "")
        self.assertEqual(app.trim_section.winfo_manager(), "grid")
        self.assertFalse(app.trim_section.opened)
        self.assertEqual(str(app.trim_entry.cget("state")), "normal")
        self.assertEqual(app.trim_var.get(), "Линии")
        self.assertIn("54 × 86", app.card_hint_var.get())
        self.assertIn("46 × 62", app.card_hint_var.get())
        app.copy_vars[0].set("3")
        app.trim_var.set("Линии")
        app.trim_inset_var.set("0,5")
        app.refresh()
        self.assertEqual(app.trim_hint_var.get(), "После реза: 53 × 85 мм")
        self.assertEqual(app.photos[0].copies, 3)
        app.set_group_alignment("x", "right")
        app.mode_var.set("Разделить лист")
        self.assertEqual(app.trim_section.winfo_manager(), "grid")  # Center line is independent of cut marks.
        app.mode_var.set("Фото с рамкой")
        self.assertEqual(app.layout.align_x, "right")
        self.assertEqual(app.trim_var.get(), "Линии")
        app.card_var.set("Свой шаблон")
        app.window_left_var.set("20")
        app.refresh()
        self.assertIsNone(app.layout)
        self.assertEqual(app.save_button.cget("state"), "disabled")
        self.assertIn("Окно выходит", app.trim_hint_var.get())
        app.window_left_var.set("4")
        app.trim_var.set("Нет")
        app.refresh()
        self.assertIsNotNone(app.layout)
        items = page_items_for(app)
        cell = app.layout.cells(len(items))[0]
        x = app.preview_origin[0]+(cell.x+1)*app.preview_scale
        y = app.preview_origin[1]+(cell.y+1)*app.preview_scale
        app.begin_drag(SimpleNamespace(x=x, y=y))
        self.assertIsNone(app._drag)
        self.assertTrue(app.preview_canvas.find_withtag("card_window"))
        app.card_var.set("Instax Mini")
        app.paper_var.set("Свой размер")
        app.paper_w_var.set("54")
        app.paper_h_var.set("87")
        app.margin_var.set("0")
        app.trim_var.set("Метки")
        app.refresh()
        self.assertIsNone(app.layout)
        self.assertIn("Увеличьте поля", app.trim_hint_var.get())
        self.assertEqual(app.print_button.cget("state"), "disabled")

    def test_rotated_card_window_drag_zoom_reset_only_photo_and_copies(self):
        app = self.app
        app.mode_var.set("Фото с рамкой")
        app.paper_var.set("Свой размер")
        app.paper_w_var.set("98")
        app.paper_h_var.set("66")
        app.orientation_var.set("Альбомная")
        app.margin_var.set("6")
        app.copy_vars[0].set("2")
        app.refresh()
        layout = app.layout
        self.assertTrue(layout.card_turned)
        cell = layout.cells(1)[0]
        area = layout.photo_area(cell)
        other = replace(app.photos[1])
        app.zoom_button.invoke()
        self.assertEqual(app.photos[0].zoom, 1.1)
        x = app.preview_origin[0]+(area.x+area.width/2)*app.preview_scale
        y = app.preview_origin[1]+(area.y+area.height/2)*app.preview_scale
        app.begin_drag(SimpleNamespace(x=x, y=y))
        self.assertIsNotNone(app._drag)
        app.drag_motion(SimpleNamespace(x=x+100, y=y+100))
        app.end_drag()
        self.assertNotEqual((app.photos[0].offset_x, app.photos[0].offset_y), (0, 0))
        self.assertEqual(app.layout, layout)
        self.assertEqual(app.layout.photo_area(cell), area)
        self.assertEqual(app.photos[1], other)
        chosen, _, _ = photo_slot(app.photos[0], cell, layout)
        self.assertEqual((chosen.offset_x, chosen.offset_y), (-app.photos[0].offset_y, app.photos[0].offset_x))
        app.reset_frame_button.invoke()
        self.assertEqual((app.photos[0].zoom, app.photos[0].rotation, app.photos[0].offset_x, app.photos[0].offset_y), (1, 0, 0, 0))


def page_items_for(app):
    from illusive_print.core import page_items
    return page_items(app.photos, app.layout, app.page)


if __name__ == "__main__":
    unittest.main()
