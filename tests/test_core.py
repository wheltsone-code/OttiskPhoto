from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

import pymupdf
from PIL import Image, ImageChops, ImageFilter, ImageStat
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.core import (
    Correction, EdgeInsets, Layout, Photo, Rect, correct_image, export_pdf,
    first_print_index, image_rect, load_source, page_count, page_items,
    page_photos, photo_image, print_count, render_page, rotation_turns, set_all_modes,
)
from tests.support import make_photos


class PrintCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.paths = make_photos(cls.folder / "originals")
        cls.hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.paths}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.photos = [Photo(path) for path in self.paths]

    def test_ten_copies_two_per_page_and_pdf_order(self):
        photos = [Photo(self.paths[0], copies=10), Photo(self.paths[1], copies=1)]
        layout = Layout(per_sheet=2)
        self.assertEqual(print_count(photos[:1]), 10)
        self.assertEqual(page_count(photos[:1], layout), 5)
        self.assertEqual([len(page_photos(photos[:1], layout, page)) for page in range(5)], [2] * 5)
        self.assertTrue(all(index == 0 for page in range(5) for index, _ in page_items(photos, layout, page)))
        self.assertEqual(page_items(photos, layout, 5)[0][0], 1)
        self.assertEqual(first_print_index(photos, 1), 10)
        output = self.folder / "ten-copies.pdf"
        export_pdf(output, photos[:1], layout, Correction())
        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 5)
        self.assertEqual([page.get_contents().get_data().count(b" Do") for page in reader.pages], [2] * 5)
        self.assertEqual(len(photos[:1]), 1)

    def test_40mm_frames_six_plus_four_on_100_by_150_paper(self):
        photos = [Photo(self.paths[0], copies=10)]
        layout = Layout(mode="exact", paper_width=100, paper_height=150,
                        print_width=40, print_height=40, gap=5)
        self.assertEqual(layout.count, 6)
        self.assertEqual(layout.capacity_grid(), (2, 3))
        self.assertEqual(layout.effective_margins, EdgeInsets(3, 3, 3, 3))
        self.assertEqual([len(page_photos(photos, layout, page)) for page in range(2)], [6, 4])
        for cell in layout.cells():
            self.assertEqual((cell.width, cell.height), (40, 40))
            self.assertGreaterEqual(cell.x, 3)
            self.assertGreaterEqual(cell.y, 3)
            self.assertLessEqual(cell.x + cell.width, 97)
            self.assertLessEqual(cell.y + cell.height, 147)
        output = self.folder / "40mm.pdf"
        export_pdf(output, photos, layout, Correction())
        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 2)
        for index, page in enumerate(reader.pages):
            self.assertAlmostEqual(float(page.mediabox.width) * 25.4 / 72, 100, places=4)
            self.assertAlmostEqual(float(page.mediabox.height) * 25.4 / 72, 150, places=4)
            clips = [operands for operands, operator in ContentStream(page.get_contents(), reader).operations if operator == b"re"]
            self.assertEqual(len(clips), [6, 4][index])
            for _, _, width, height in clips:
                self.assertAlmostEqual(float(width) * 25.4 / 72, 40, places=4)
                self.assertAlmostEqual(float(height) * 25.4 / 72, 40, places=4)
        preview = render_page(photos, layout, 1, Correction(), 2)
        fifth_cell = layout.cells()[4]
        self.assertEqual(preview.getpixel((round((fifth_cell.x + 20) * 2),
                                          round((fifth_cell.y + 20) * 2))), (255, 255, 255))

    def test_best_frame_rotation_and_driver_margins(self):
        layout = Layout(mode="exact", paper_width=100, paper_height=150,
                        print_width=60, print_height=40, gap=5)
        self.assertEqual(layout.exact_grid(), (2, 2, 40, 60))
        square = replace(layout, print_width=40, print_height=40)
        enlarged = replace(square, driver_margins=EdgeInsets(10, 1, 10, 1))
        self.assertEqual(square.count, 6)
        self.assertEqual(enlarged.count, 6)
        self.assertEqual(enlarged.effective_margins, EdgeInsets(3, 3, 3, 3))
        self.assertEqual(page_count([Photo(self.paths[0], copies=10)], enlarged), 2)
        self.assertTrue(all((cell.width, cell.height) == (40, 40) for cell in enlarged.cells()))

    def test_last_sheet_preserves_grid_and_equal_a4_halves(self):
        layout = Layout(per_sheet=2)
        self.assertEqual(page_count(self.photos, layout), 3)
        self.assertEqual([len(page_photos(self.photos, layout, p)) for p in range(3)], [2, 2, 1])
        self.assertEqual(layout.cells(), (Rect(0, 0, 210, 148.5), Rect(0, 148.5, 210, 148.5)))
        four = Layout(per_sheet=4)
        self.assertEqual(four.cells()[0], Rect(0, 0, 105, 148.5))
        preview = render_page(self.photos, four, 1, Correction(), 2)
        for point in ((315, 100), (100, 450), (315, 450)):
            self.assertEqual(preview.getpixel(point), (255, 255, 255))
        horizontal = Layout(paper_width=297, paper_height=210)
        self.assertEqual(horizontal.cells(), (Rect(0, 0, 148.5, 210), Rect(148.5, 0, 148.5, 210)))

    def test_grid_margins_gaps_and_no_resizing_exact_frames(self):
        for count, columns, rows in ((1, 1, 1), (4, 2, 2), (6, 2, 3), (9, 3, 3)):
            cells = Layout(per_sheet=count, margin=10, gap=4).cells()
            self.assertEqual(len(cells), count)
            self.assertAlmostEqual(cells[0].width, (190 - (columns - 1) * 4) / columns)
            self.assertAlmostEqual(cells[0].height, (277 - (rows - 1) * 4) / rows)
            self.assertEqual((cells[0].x, cells[0].y), (10, 10))
        layout = Layout(mode="exact", print_width=100, print_height=150)
        self.assertTrue(all(sorted((c.width, c.height)) == [100, 150] for c in layout.cells()))

    def test_autorotation_manual_rotation_and_all_copies(self):
        photo, other = self.photos[:2]
        photo.copies = 4
        upright = Layout().cells()[0]
        landscape = Layout(paper_width=297, paper_height=210).cells()[0]
        self.assertEqual(rotation_turns((1200, 800), upright, photo), 0)
        self.assertEqual(rotation_turns((1200, 800), landscape, photo), 1)
        self.assertEqual(rotation_turns((1200, 800), Rect(0, 0, 40, 40), photo), 0)
        photo.rotate_clockwise()
        self.assertEqual(rotation_turns((1200, 800), upright, photo), 1)
        self.assertEqual(rotation_turns((1200, 800), landscape, photo), 2)
        self.assertEqual(other.rotation, 0)
        self.assertTrue(all(copy.rotation == 1 for copy in page_photos([photo], Layout(per_sheet=4), 0)))
        self.assertEqual(photo_image(photo, Correction(), upright).size, (800, 1200))
        for _ in range(3):
            photo.rotate_clockwise()
        self.assertEqual(photo.rotation, 0)

    def test_individual_crop_after_batch_affects_only_its_copies(self):
        self.photos[1].copies = 3
        set_all_modes(self.photos, "fill")
        self.photos[1].set_mode("fit")
        items = page_items(self.photos, Layout(per_sheet=9), 0)
        self.assertEqual([photo.mode for _, photo in items],
                         ["fill", "fit", "fit", "fit", "fill", "fill", "fill"])

    def test_movement_bounds_never_expose_fill_or_clip_fit(self):
        cell = Rect(10, 20, 100, 150)
        for size in ((1200, 600), (600, 1200), (800, 800)):
            for mode in ("fill", "fit"):
                photo = Photo(self.paths[0], mode)
                for dx, dy in ((-100, -100), (200, 200), (-1, -1)):
                    photo.move(dx, dy)
                    self.assertTrue(-1 <= photo.offset_x <= 1 and -1 <= photo.offset_y <= 1)
                    placed = image_rect(size, cell, photo)
                    if mode == "fill":
                        self.assertLessEqual(placed.x, cell.x + 1e-8)
                        self.assertLessEqual(placed.y, cell.y + 1e-8)
                        self.assertGreaterEqual(placed.x + placed.width, cell.x + cell.width - 1e-8)
                        self.assertGreaterEqual(placed.y + placed.height, cell.y + cell.height - 1e-8)
                    else:
                        self.assertGreaterEqual(placed.x, cell.x - 1e-8)
                        self.assertGreaterEqual(placed.y, cell.y - 1e-8)
                        self.assertLessEqual(placed.x + placed.width, cell.x + cell.width + 1e-8)
                        self.assertLessEqual(placed.y + placed.height, cell.y + cell.height + 1e-8)

    def test_vibrance_muted_colours_and_neutral_greys(self):
        def pixel(rgb, amount):
            return correct_image(Image.new("RGB", (1, 1), rgb), Correction(vibrance=amount)).getpixel((0, 0))
        def saturation(rgb):
            return (max(rgb) - min(rgb)) / max(rgb)
        for value in (0, 25, 128, 225, 255):
            self.assertEqual(pixel((value, value, value), 1), (value, value, value))
        muted, saturated = (100, 130, 150), (0, 10, 150)
        self.assertEqual(pixel(muted, 0), muted)
        boost_muted = saturation(pixel(muted, 1)) - saturation(muted)
        boost_saturated = saturation(pixel(saturated, 1)) - saturation(saturated)
        self.assertGreater(boost_muted, .15)
        self.assertLess(boost_saturated, .02)
        self.assertLess(saturation(pixel(muted, -.5)), saturation(muted))

    def test_gamma_neutral_and_monotonic_brightening(self):
        image = Image.new("RGB", (1, 1), (80, 120, 160))
        self.assertEqual(correct_image(image, Correction()).getpixel((0, 0)), (80, 120, 160))
        previous = (80, 120, 160)
        for gamma in (1.1, 1.2, 1.3, 1.4):
            current = correct_image(image, Correction(gamma=gamma)).getpixel((0, 0))
            self.assertTrue(all(a > b for a, b in zip(current, previous)))
            previous = current

    def test_exif_transparency_and_source_integrity(self):
        oriented = self.folder / "oriented.jpg"
        image = Image.new("RGB", (80, 40), "red")
        exif = image.getexif()
        exif[274] = 6
        image.save(oriented, exif=exif)
        self.assertEqual(load_source(oriented).size, (40, 80))
        self.assertEqual(photo_image(Photo(oriented), Correction(), Rect(0, 0, 40, 60)).size, (40, 80))
        transparent = self.folder / "alpha.png"
        Image.new("RGBA", (20, 20), (255, 0, 0, 0)).save(transparent)
        self.assertEqual(load_source(transparent).getpixel((0, 0)), (255, 255, 255))
        self.photos[0].copies = 3
        self.photos[1].rotate_clockwise()
        export_pdf(self.folder / "unchanged.pdf", self.photos, Layout(), Correction(.5, 1.2))
        for path, original_hash in self.hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_hash)
        with self.assertRaises(ValueError):
            export_pdf(self.paths[0], self.photos, Layout(), Correction())

    def test_invalid_values_and_frame_that_cannot_fit(self):
        for copies in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                Photo(self.paths[0], copies=copies)
        for layout in (Layout(margin=120), Layout(gap=300, per_sheet=4), Layout(paper_width=float("nan")),
                       Layout(mode="exact", paper_width=100, paper_height=150),  # 3mm edges prevent 100x150 frame
                       Layout(mode="exact", print_width=500)):
            with self.assertRaises(ValueError):
                layout.cells()

    def test_rendered_pdf_matches_preview_for_copies_rotations_and_correction(self):
        self.photos[0].copies = 3
        self.photos[0].move(.8, -.6)
        self.photos[1].set_mode("fit")
        self.photos[1].rotate_clockwise()
        self.photos[1].move(-.7, .9)
        self.photos[2].set_mode("fit")
        self.photos[2].move(.8, -.8)
        correction = Correction(.5, 1.2)
        layouts = (Layout(), Layout(per_sheet=4, margin=8, gap=3),
                   Layout(paper_width=297, paper_height=210, per_sheet=6), Layout(per_sheet=9),
                   Layout(mode="exact", paper_width=100, paper_height=150, print_width=40, print_height=40, gap=5),
                   Layout(mode="exact", print_width=150, print_height=100, gap=5))
        for index, layout in enumerate(layouts):
            with self.subTest(layout=index):
                output = self.folder / f"parity-{index}.pdf"
                export_pdf(output, self.photos, layout, correction)
                with pymupdf.open(output) as document:
                    for page in range(len(document)):
                        preview = render_page(self.photos, layout, page, correction, 2)
                        pixmap = document[page].get_pixmap(matrix=pymupdf.Matrix(2 * 25.4 / 72, 2 * 25.4 / 72), alpha=False)
                        pdf_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                        pdf_image = pdf_image.crop((0, 0, preview.width, preview.height))
                        raw = ImageStat.Stat(ImageChops.difference(preview, pdf_image)).mean
                        smoothed = ImageStat.Stat(ImageChops.difference(
                            preview.filter(ImageFilter.GaussianBlur(1)), pdf_image.filter(ImageFilter.GaussianBlur(1)))).mean
                        # At 2 px/mm, fine lines are sampled differently by the
                        # two renderers; the smoothed colour/position bound is
                        # deliberately tighter than this raw edge bound.
                        self.assertLess(max(raw), 4.5, (index, page, raw))
                        self.assertLess(max(smoothed), 2.0, (index, page, smoothed))
                    objects = PdfReader(output).pages[0]["/Resources"]["/XObject"].values()
                    embedded_sizes = {(int(obj.get_object()["/Width"]), int(obj.get_object()["/Height"])) for obj in objects}
                    expected_sizes = {(round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4)) for cell in
                                      layout.cells(limit=len(page_photos(self.photos, layout, 0)))}
                    self.assertEqual(embedded_sizes, expected_sizes)

    def test_icon_contains_multiple_windows_sizes(self):
        path = Path(__file__).resolve().parent.parent / "assets" / "logo.ico"
        with Image.open(path) as icon:
            sizes = icon.ico.sizes()
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes)


if __name__ == "__main__":
    unittest.main()
