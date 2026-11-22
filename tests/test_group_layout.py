"""Group alignment and crop zoom; output tests never use a physical printer."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

import pymupdf
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import (Correction, Layout, Photo, Rect, export_pdf, image_rect,
                                 load_source, page_items, render_page, rotation_turns)
from illusive_print.print_job import PrintJob, PrintSnapshot
from tests.support import make_photos
from tests.test_beta import FakePrinter


class GroupGeometryTests(unittest.TestCase):
    def test_beside_stack_auto_and_independent_axes(self):
        layout = Layout(mode="exact", gap=2)
        self.assertTrue(layout.placement_choices())
        self.assertEqual(layout.exact_grid(), (2, 1, 100, 150))
        self.assertEqual(layout.cells(), (Rect(4, 73.5, 100, 150), Rect(106, 73.5, 100, 150)))
        stack = replace(layout, placement="stack")
        self.assertEqual(stack.exact_grid(), (1, 2, 150, 100))
        self.assertEqual(stack.cells(), (Rect(30, 47.5, 150, 100), Rect(30, 149.5, 150, 100)))
        self.assertEqual(replace(layout, placement="beside").cells(), layout.cells())
        top = replace(stack, align_y="top")
        self.assertEqual(top.cells()[0], Rect(30, 3, 150, 100))
        right = replace(top, align_x="right")
        self.assertEqual(right.cells()[0], Rect(57, 3, 150, 100))
        bottom = replace(right, align_y="bottom")
        self.assertEqual(bottom.cells()[0], Rect(57, 92, 150, 100))
        # Capacity dominates height when the other orientation holds more prints.
        smaller = replace(layout, paper_width=100, paper_height=150, print_width=60, print_height=40, gap=5)
        self.assertEqual(smaller.exact_grid(), (2, 2, 40, 60))
        self.assertFalse(replace(smaller, print_width=40, print_height=40).placement_choices())

    def test_incomplete_occupied_block_and_stack_cutting_positions(self):
        layout = Layout(mode="exact", paper_width=100, paper_height=150,
                        print_width=40, print_height=40, gap=5)
        self.assertEqual(layout.cells(limit=4)[0], Rect(7.5, 32.5, 40, 40))
        self.assertEqual(layout.cells(limit=1), (Rect(30, 55, 40, 40),))
        stable = replace(layout, keep_positions=True)
        self.assertEqual(stable.cells(limit=4), stable.cells()[:4])
        self.assertEqual(stable.cells(limit=1), stable.cells()[:1])
        self.assertEqual(stable.cells(limit=0), ())
        for ax in ("left", "center", "right"):
            for ay in ("top", "center", "bottom"):
                aligned = replace(stable, align_x=ax, align_y=ay)
                self.assertEqual(aligned.cells(limit=1), aligned.cells()[:1])
        cells = Layout(per_sheet=6)
        self.assertEqual(replace(cells, align_x="right", align_y="bottom", keep_positions=True).cells(limit=1),
                         cells.cells(limit=1))

    def test_pdf_positions_match_preview_and_fake_print_for_partial_pages(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / "source.png"
            Image.new("RGB", (400, 600), (80, 120, 160)).save(path)
            photos = [Photo(path, copies=3, zoom=1.2, offset_x=.4)]
            for placement, stable in (("beside", False), ("stack", False), ("stack", True)):
                layout = Layout(mode="exact", gap=2, placement=placement, keep_positions=stable)
                pdf_path = folder / f"{placement}-{stable}.pdf"
                export_pdf(pdf_path, photos, layout, Correction())
                reader = PdfReader(pdf_path)
                with pymupdf.open(pdf_path) as document:
                    for page_index, page in enumerate(reader.pages):
                        items = page_items(photos, layout, page_index)
                        cells = layout.cells(limit=len(items))
                        clips = [v for v, op in ContentStream(page.get_contents(), reader).operations if op == b"re"]
                        self.assertEqual(len(clips), len(items))
                        for operands, cell in zip(clips, cells):
                            x, y, w, h = [float(v) * 25.4 / 72 for v in operands]
                            for actual, expected in zip((x, 297 - y - h, w, h),
                                                        (cell.x, cell.y, cell.width, cell.height)):
                                self.assertAlmostEqual(actual, expected, places=4)
                        preview = render_page(photos, layout, page_index, Correction(), 2)
                        pix = document[page_index].get_pixmap(matrix=pymupdf.Matrix(2 * 25.4 / 72, 2 * 25.4 / 72), alpha=False)
                        output = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        for cell in cells:
                            point = (round((cell.x + cell.width / 2) * 2), round((cell.y + cell.height / 2) * 2))
                            self.assertEqual(preview.getpixel(point), output.getpixel(point))
                        self.assertEqual(preview.getpixel((1, 1)), output.getpixel((1, 1)))
            snapshot = PrintSnapshot.capture(photos, layout, Correction(), 1)
            backend, job = FakePrinter(), PrintJob()
            job.start(snapshot, True, 300, backend, "Подмена", {}, None)
            deadline = time.monotonic() + 15
            while job.state in ("preparing", "sending") and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(job.state, "sent")
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(len(backend.calls[0][2]), 1)
            self.assertEqual(backend.calls[0][2][0].tobytes(), render_page(photos, layout, 1, Correction(), 300 / 25.4).tobytes())


class GroupControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.count_var.set('2')
        self.root.geometry("1270x840")
        self.app.add_paths(make_photos(Path(self.temp.name))[:2])
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.temp.cleanup()

    def test_zoom_percent_steps_drag_reset_and_copies(self):
        app = self.app
        first, second = app.photos
        original_second = replace(second)
        app.copy_vars[0].set("2")
        app.refresh()
        original_layout = app.layout
        self.assertEqual(app.zoom_var.get(), "100%")
        self.assertEqual(app.zoom_out_button.cget("state"), "disabled")
        for expected in (110, 120, 130):
            app.zoom_button.invoke()
            self.assertAlmostEqual(first.zoom, expected / 100)
            self.assertEqual(app.zoom_var.get(), f"{expected}%")
        app.zoom_out_button.invoke()
        self.assertEqual(first.zoom, 1.2)
        self.assertEqual(app.zoom_var.get(), "120%")
        cell = app.layout.cells()[1]
        x = app.preview_origin[0] + (cell.x + cell.width / 2) * app.preview_scale
        y = app.preview_origin[1] + (cell.y + cell.height / 2) * app.preview_scale
        app.begin_drag(SimpleNamespace(x=x, y=y))
        app.drag_motion(SimpleNamespace(x=x+1000, y=y+1000))
        app.end_drag()
        self.assertEqual(app._selected_instance, (0, 1))
        size = load_source(first.path).size
        if rotation_turns(size, cell, first) % 2:
            size = size[::-1]
        placed = image_rect(size, cell, first)
        self.assertLessEqual(placed.x, cell.x)
        self.assertLessEqual(placed.y, cell.y)
        self.assertGreaterEqual(placed.x + placed.width, cell.x + cell.width - 1e-8)
        self.assertGreaterEqual(placed.y + placed.height, cell.y + cell.height - 1e-8)
        self.assertEqual(second, original_second)
        self.assertTrue(all(p.zoom == 1.2 for i, p in page_items(app.photos, app.layout, 0) if i == 0))
        self.assertEqual(app.layout, original_layout)
        app.apply_crop_button.invoke()
        self.assertEqual(second.zoom, 1)
        app.rotate_button.invoke()
        app.reset_frame_button.invoke()
        self.assertEqual((first.zoom, first.rotation, first.offset_x, first.offset_y), (1, 0, 0, 0))
        self.assertEqual(app.zoom_out_button.cget("state"), "disabled")
        self.assertEqual(app.zoom_var.get(), "100%")

    def test_group_controls_modes_preview_decorations_and_restore(self):
        app = self.app
        self.assertEqual(app.mode_var.get(), "Разделить лист")
        self.assertEqual(app.fill_button.cget("text"), "Обрезать до краёв")
        self.assertEqual(app.fit_button.cget("text"), "Фото целиком")
        app.count_var.set("6")
        app.copy_vars[0].set("3")
        app.refresh()
        self.assertEqual(app.occupancy_var.get(), "Занято 4 из 6 мест")
        self.assertEqual(len(app.preview_canvas.find_withtag("empty_cell")), 2)
        self.assertEqual(len(app.preview_canvas.find_withtag("selected_instance")), 1)
        self.assertEqual(len(app.preview_canvas.find_withtag("selected_copy")), 2)
        self.assertEqual(app.preview_canvas.itemcget(app.preview_canvas.find_withtag("selected_instance")[0], "width"), "3.0")
        self.assertTrue(all(app.preview_canvas.itemcget(i, "dash") for i in app.preview_canvas.find_withtag("empty_cell")))
        app.mode_var.set("Задать размер фото")
        app.print_var.set('100 × 150 мм')
        app.gap_var.set("2")
        app.refresh()
        self.assertEqual(app.placement_row.winfo_manager(), "grid")
        app.placement_buttons[2].invoke()
        app.root.update()
        app.refresh()
        self.assertEqual(app.layout.exact_grid(), (1, 2, 150, 100))
        # The six icon buttons have full keyboard/focus semantics inherited from capsules.
        app.alignment_buttons[3][0].invoke()
        self.assertEqual((app.layout.align_x, app.layout.align_y), ("center", "top"))
        app.alignment_buttons[2][0].invoke()
        self.assertEqual((app.layout.align_x, app.layout.align_y), ("right", "top"))
        icon = app.alignment_buttons[2][0]
        icon.redraw()
        self.assertEqual(len(icon.find_withtag("alignment_icon")), 3)
        app.keep_positions_check.invoke()
        app.refresh()
        self.assertTrue(app.layout.keep_positions)
        self.assertEqual(app.occupancy_var.get(), "")
        self.assertFalse(app.preview_canvas.find_withtag("empty_cell"))
        app.mode_var.set("Разделить лист")
        app.mode_var.set("Задать размер фото")
        self.assertEqual((app.layout.placement, app.layout.align_x, app.layout.align_y, app.layout.keep_positions),
                         ("stack", "right", "top", True))
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.refresh()
        self.assertEqual(app.placement_hint.cget('text'), f'Авто · {app.layout.exact_grid()[0]}×{app.layout.exact_grid()[1]}')
        self.assertTrue(all(not button.winfo_manager() for button in app.placement_buttons))


if __name__ == "__main__":
    unittest.main()
