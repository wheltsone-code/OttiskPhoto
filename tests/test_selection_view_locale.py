from dataclasses import replace
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
from pypdf.generic import ContentStream
import pymupdf

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import (CARD_TEMPLATES, PRINT_SIZES, PAPERS, Correction, Layout, Photo,
                                 export_pdf, page_items, render_page)
from illusive_print.i18n import localize_tree, translate
from illusive_print.print_dialog import PrintDialog
from tests.support import make_photos
from tests.test_beta import FakePrinter


class SelectionViewLocaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"OTTISK_PHOTO_PREFERENCES": str(self.folder / 'preferences.json')})
        self.environment.start()
        self.paths = make_photos(self.folder / 'photos')
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.count_var.set('2')
        self.root.geometry('1270x840')
        self.app.add_paths(self.paths)
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.environment.stop()
        self.temp.cleanup()

    def test_nonadjacent_ctrl_shift_delete_and_entry_delete_preserves_originals(self):
        app = self.app
        app.thumbnail_widgets[0][2].event_generate('<Button-1>')
        app.thumbnail_widgets[2][2].event_generate('<Button-1>', state=4)
        app.thumbnail_widgets[4][2].event_generate('<Button-1>', state=4)
        self.assertEqual(app.selected_rows, {0, 2, 4})
        self.assertEqual(app.selected, 4)
        self.assertEqual(app.photos[0].zoom, 1)
        # Frame actions address all selected photos, preserving the others.
        app.zoom_button.invoke()
        self.assertEqual([p.zoom for p in app.photos], [1.1, 1, 1.1, 1, 1.1])
        app.thumbnail_widgets[4][0].focus_force()
        app.root.update()
        app.thumbnail_widgets[4][0].event_generate('<Delete>')
        app.root.update()
        self.assertEqual([p.path for p in app.photos], [self.paths[1], self.paths[3]])
        self.assertTrue(all(path.exists() for path in self.paths))
        self.assertIn('Отпечатков: 2', app.counter_var.get())
        self.assertEqual(app.page, 0)
        # Delete inside Copies edits text rather than removing the photo row.
        app.copy_vars[0].set('12')
        entry = app.copy_entries[0]
        entry.focus_force()
        entry.icursor(0)
        app.root.update()
        entry.event_generate('<Delete>')
        app.root.update()
        self.assertEqual(entry.get(), '2')
        self.assertEqual(len(app.photos), 2)
        app.library_click(0, SimpleNamespace(state=0))
        app.library_click(1, SimpleNamespace(state=1))
        self.assertEqual(app.selected_rows, {0, 1})
        app.library_click(0, SimpleNamespace(state=4))
        self.assertEqual(app.selected_rows, {1})
        app.remove_selected()
        self.assertEqual(len(app.photos), 1)

    def test_zoom_cursor_anchor_middle_pan_and_crop_match_pdf(self):
        app = self.app
        app.select_photo(0)
        before_layout = app.layout
        before_photos = [replace(p) for p in app.photos]
        x, y = 200, 190
        original_point = ((x-app.preview_origin[0])/app.preview_scale, (y-app.preview_origin[1])/app.preview_scale)
        app.zoom_sheet(SimpleNamespace(x=x, y=y, delta=120))
        after_point = ((x-app.preview_origin[0])/app.preview_scale, (y-app.preview_origin[1])/app.preview_scale)
        self.assertAlmostEqual(original_point[0], after_point[0], places=6)
        self.assertAlmostEqual(original_point[1], after_point[1], places=6)
        self.assertEqual(app.layout, before_layout)
        self.assertEqual(app.photos, before_photos)
        self.assertEqual(app.sheet_zoom_var.get(), '120%')
        origin = app.preview_origin
        app.begin_sheet_pan(SimpleNamespace(x=100, y=100))
        app.move_sheet_pan(SimpleNamespace(x=150, y=130))
        app.end_sheet_pan()
        self.assertAlmostEqual(app.preview_origin[0]-origin[0], 50)
        self.assertAlmostEqual(app.preview_origin[1]-origin[1], 30)
        cell = app.layout.cells()[0]
        x = app.preview_origin[0]+(cell.x+cell.width/2)*app.preview_scale
        y = app.preview_origin[1]+(cell.y+cell.height/2)*app.preview_scale
        app.begin_drag(SimpleNamespace(x=x, y=y))
        self.assertIsNotNone(app._drag)
        app.drag_motion(SimpleNamespace(x=x+20*app.preview_scale, y=y+10*app.preview_scale))
        app.end_drag()
        frame = replace(app.photos[0])
        self.assertNotEqual((frame.offset_x, frame.offset_y), (0, 0))
        app.fit_sheet_button.invoke()
        self.assertEqual(app.sheet_zoom, 1)
        self.assertEqual(app.sheet_pan, (0, 0))
        self.assertEqual(app.photos[0], frame)
        path = self.folder/'view-crop.pdf'
        export_pdf(path, app.photos, app.layout, app.correction)
        preview = render_page(app.photos, app.layout, 0, app.correction, 2)
        with pymupdf.open(path) as doc:
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(2*25.4/72, 2*25.4/72), alpha=False)
            pdf_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        box = (2, 2, min(preview.width, pdf_image.width)-2, round(cell.height*2)-2)
        difference = ImageStat.Stat(ImageChops.difference(preview.crop(box), pdf_image.crop(box))).mean
        self.assertLess(max(difference), 4)

    def test_language_units_round_trip_order_page_settings_and_precision(self):
        app = self.app
        app.mode_var.set('Задать размер фото')
        app.print_var.set('Свой размер')
        app.size_lock_var.set(False)
        app.print_w_var.set('88.47123456789')
        app.print_h_var.set('107.52123456789')
        app.margin_var.set('3.123456789')
        app.gap_var.set('2.987654321')
        app.copy_vars[0].set('8')
        app.refresh()
        app.turn_page(1)
        layout, page = app.layout, app.page
        photos = [replace(p) for p in app.photos]
        settings = {k: v.get() for k, v in app._mode_vars.items()}
        for _ in range(3):
            app.language_var.set('English')
            app.unit_var.set('in')
            self.assertEqual(app.root.title(), 'Ottisk Photo')
            self.assertEqual(app.layout, layout)
            self.assertEqual(app.page, page)
            self.assertEqual(app.photos, photos)
            self.assertIn('in', app.display_text(app.size_hint_var.get()))
            self.assertEqual({k: v.get() for k, v in app._mode_vars.items()}, settings)
            app.language_var.set('Русский')
            app.unit_var.set('mm')
        self.assertEqual(app.root.title(), 'Оттиск Фото')
        self.assertEqual(app.layout, layout)
        self.assertEqual(app.page, page)
        self.assertEqual({k: v.get() for k, v in app._mode_vars.items()}, settings)
        app.unit_var.set('in')
        app.print_entries[0].delete(0, 'end')
        app.print_entries[0].insert(0, '4')
        app.print_entries[1].delete(0, 'end')
        app.print_entries[1].insert(0, '6')
        app.refresh()
        self.assertEqual((app.layout.print_width, app.layout.print_height), (101.6, 152.4))
        app.language_var.set('English')
        # Persisted presentation preferences are loaded by another app instance.
        self.root.destroy()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.assertEqual(self.root.title(), 'Ottisk Photo')
        self.assertEqual(self.app.unit_var.get(), 'in')

    def test_english_widgets_curves_print_dialog_and_errors(self):
        app = self.app
        app.language_var.set('English')
        app.mode_var.set('Фото с рамкой')
        app.card_var.set('Свой шаблон')
        app.refresh()
        app.open_curves()
        class EnglishPrinter(FakePrinter):
            def printers(self): return ['Test printer']
            def default(self): return 'Test printer'
        dialog = PrintDialog(app, backend=EnglishPrinter())
        app._print_dialog = dialog
        localize_tree(app.root)
        remaining = []
        def inspect(widget):
            if hasattr(widget, 'text') and not getattr(widget,'_literal_text',False):
                value = app.display_text(widget.text)
                if re.search('[а-яА-Я]', value) and value != 'Русский':
                    remaining.append(value)
            elif widget.winfo_class() in ('TLabel', 'Label', 'TLabelframe') and not getattr(widget, '_l10n_skip', False):
                variable = str(widget.cget('textvariable')) if 'textvariable' in widget.keys() else ''
                value = str(widget.getvar(variable)) if variable else str(widget.cget('text'))
                if re.search('[а-яА-Я]', value):
                    remaining.append(value)
            for child in widget.winfo_children():
                inspect(child)
        inspect(app.root)
        self.assertEqual(remaining, [])
        self.assertEqual(app._curves_editor.window.title(), 'RGB curves')
        self.assertIn('Print', dialog.window.title())
        self.assertIn('all sheets', app.display_text(dialog.summary_var.get()))
        for text in ('Окно выходит за пределы карточки. Уменьшите окно или отступы сверху и слева.',
                     'Встроенный ICC не читается или несовместим: invalid. Фото не импортировано.',
                     'Отправлено в очередь печати · задание 42'):
            self.assertFalse(re.search('[а-яА-Я]', translate(text, 'en')))
        self.assertEqual(dialog.job.state, 'idle')
        dialog.close()

    def test_inch_presets_and_full_card_page_two_copies_marks_pdf(self):
        self.assertEqual(PRINT_SIZES['4 × 6″'], (101.6, 152.4))
        self.assertEqual(PRINT_SIZES['5 × 7″'], (127, 177.8))
        self.assertEqual(PRINT_SIZES['8 × 10″'], (203.2, 254))
        self.assertEqual(PAPERS['US Letter'], (215.9, 279.4))
        app = self.app
        app.mode_var.set('Задать размер фото')
        app.print_var.set('4 × 6″')
        app.refresh()
        self.assertEqual((app.layout.print_width, app.layout.print_height), (101.6, 152.4))
        inch_pdf = self.folder / 'four-by-six.pdf'
        export_pdf(inch_pdf, app.photos[:1], app.layout, app.correction)
        inch_reader = PdfReader(inch_pdf)
        clips = [args for args, op in ContentStream(inch_reader.pages[0].get_contents(), inch_reader).operations if op == b're']
        self.assertEqual(sorted(round(float(v)*25.4/72, 4) for v in clips[0][2:]), [101.6, 152.4])
        app.mode_var.set('Фото с рамкой')
        app.card_var.set('Polaroid 600 / SX-70 / i-Type')
        app.trim_var.set('Метки')
        app.use_card_page()
        app.selected_rows = set(range(1, len(app.photos)))
        app.remove_selected()
        app.copy_vars[0].set('2')
        app.refresh()
        self.assertEqual(app.layout.count, 1)
        self.assertEqual(app.layout.page_size, (88.47, 107.52))
        self.assertEqual(app.layout.margin, 0)
        self.assertEqual(app.layout.gap, 0)
        path = self.folder/'polaroid-two.pdf'
        export_pdf(path, app.photos, app.layout, app.correction)
        reader = PdfReader(path)
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width)*25.4/72, 88.47, places=4)
            self.assertAlmostEqual(float(page.mediabox.height)*25.4/72, 107.52, places=4)
            operations = ContentStream(page.get_contents(), reader).operations
            self.assertTrue(any(op == b'S' for _, op in operations))
        before = app.layout.cut_rects(1)
        after = replace(app.layout, trim_inset=2).cut_rects(1)
        self.assertAlmostEqual(before[0].width-after[0].width, 4)
        self.assertAlmostEqual(before[0].height-after[0].height, 4)
        self.assertTrue(all(0 <= x0 <= 88.47 and 0 <= x1 <= 88.47 and 0 <= y0 <= 107.52 and 0 <= y1 <= 107.52
                            for x0, y0, x1, y1 in app.layout.cut_segments(1)))
        ordinary = Layout(mode='exact', print_width=140, print_height=140, trim_mode='marks', trim_inset=2)
        self.assertEqual(ordinary.cut_rects(1)[0].width, 136)
        self.assertTrue(all(abs(abs(x1-x0)+abs(y1-y0)-3.8) < 1e-6 for x0,y0,x1,y1 in ordinary.cut_segments(1)))


if __name__ == '__main__':
    unittest.main()
