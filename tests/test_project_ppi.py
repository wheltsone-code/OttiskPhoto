import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import export_pdf, source_size


class ProjectPpiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        preferences = self.folder / 'preferences.json'
        preferences.write_text(json.dumps({'photos_per_sheet': '9'}))
        self.env = patch.dict(os.environ, OTTISK_PHOTO_PREFERENCES=str(preferences))
        self.env.start()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)

    def tearDown(self):
        self.root.destroy()
        self.env.stop()
        self.temp.cleanup()

    def photo(self, dpi=None, orientation=None):
        path = self.folder / f'{dpi}-{orientation}.jpg'
        kwargs = {'dpi': (dpi, dpi)} if dpi else {}
        if orientation:
            exif = Image.Exif()
            exif[274] = orientation
            kwargs['exif'] = exif
        Image.new('RGB', (828, 1104), 'white').save(path, **kwargs)
        self.app.add_paths([path])
        self.app.select_photo(len(self.app.photos) - 1)
        return path

    def test_start_session_modes_and_reset(self):
        a = self.app
        self.assertEqual((a.mode_var.get(), a.count_var.get()), ('Разделить лист', '1'))
        a.count_var.set('4')
        a.mode_var.set('Задать размер фото')
        self.assertEqual(a.print_var.get(), 'Свой размер')
        a.print_var.set('100 × 150 мм')
        a.mode_var.set('Фото с рамкой')
        self.assertEqual(a.trim_var.get(), 'Линии')
        a.trim_var.set('Метки')
        a.mode_var.set('Разделить лист')
        self.assertEqual(a.count_var.get(), '4')
        a.mode_var.set('Задать размер фото')
        self.assertEqual(a.print_var.get(), '100 × 150 мм')
        a.mode_var.set('Фото с рамкой')
        self.assertEqual(a.trim_var.get(), 'Метки')
        with patch('illusive_print.app.messagebox.askyesno', return_value=True):
            a.reset_settings()
        self.assertEqual((a.mode_var.get(), a.count_var.get()), ('Разделить лист', '1'))
        a.mode_var.set('Задать размер фото')
        self.assertEqual(a.print_var.get(), 'Свой размер')
        a.mode_var.set('Фото с рамкой')
        self.assertEqual(a.trim_var.get(), 'Линии')

    def test_pixels_ignore_metadata_and_exif_transposes(self):
        a = self.app
        a.mode_var.set('Задать размер фото')
        for dpi, orientation in ((72, None), (96, None), (300, None), (None, None), (72, 6)):
            path = self.photo(dpi, orientation)
            px = (1104, 828) if orientation == 6 else (828, 1104)
            self.assertEqual((source_size(path).width_px, source_size(path).height_px), px)
            for ppi in (300, 600):
                a.output_ppi_var.set(str(ppi))
                a.original_button.invoke()
                self.assertAlmostEqual(a._number(a.print_w_var), px[0] * 25.4 / ppi, places=2)
                self.assertAlmostEqual(a._number(a.print_h_var), px[1] * 25.4 / ppi, places=2)
                self.assertEqual(a.ppi_var.get(), f'Исходный размер при {ppi} ppi')

    def test_resolution_preserves_manual_mm_and_pdf_raster(self):
        a = self.app
        self.photo(72)
        a.mode_var.set('Задать размер фото')
        a.size_lock_var.set(False)
        a.print_w_var.set('70,104')
        a.print_h_var.set('93,472')
        for ppi in (300, 600):
            a.output_ppi_var.set(str(ppi))
            a.refresh()
            self.assertEqual((a._number(a.print_w_var), a._number(a.print_h_var)), (70.104, 93.472))
            path = self.folder / f'output-{ppi}.pdf'
            export_pdf(path, a.photos, a.layout, a.correction, ppi=ppi)
            page = PdfReader(path).pages[0]
            image = next(iter(page['/Resources']['/XObject'].values())).get_object()
            self.assertEqual(sorted((image['/Width'], image['/Height'])), sorted((round(70.104 * ppi / 25.4), round(93.472 * ppi / 25.4))))
            clips = [v for v, op in ContentStream(page.get_contents(), page.pdf).operations if op == b're']
            for actual, expected in zip(sorted(float(v) * 25.4 / 72 for v in clips[0][2:]), (70.104, 93.472)):
                self.assertAlmostEqual(actual, expected, places=4)
        self.assertIn('ниже 600', a.quality_var.get())
        a.print_var.set('100 × 150 мм')
        a.output_ppi_var.set('300'); a.refresh()
        self.assertEqual((a.layout.print_width, a.layout.print_height), (100, 150))
        a.output_ppi_var.set('600'); a.refresh()
        self.assertEqual((a.layout.print_width, a.layout.print_height), (100, 150))

    def test_card_lines_visible_with_closed_cut_marks(self):
        a = self.app
        self.photo(72)
        a.mode_var.set('Фото с рамкой')
        a.card_var.set('Polaroid 600 / SX-70 / i-Type')
        a.refresh(); self.root.update()
        self.assertFalse(a.trim_section.opened)
        self.assertEqual(a.layout.trim_mode, 'lines')
        self.assertIn('Метки реза', a.trim_section.header.cget('text'))
        self.assertTrue(a.layout.cut_segments(1))
        self.assertTrue(any(a.preview_canvas.type(item) == 'line' for item in a.preview_canvas.find_withtag('preview_overlay')))
        path = self.folder / 'lines.pdf'
        export_pdf(path, a.photos, a.layout, a.correction)
        page = PdfReader(path).pages[0]
        self.assertTrue(any(op == b'S' for _, op in ContentStream(page.get_contents(), page.pdf).operations))
        a.language_var.set('English')
        self.root.update()
        self.assertTrue(any('Cut marks' in a.trim_section.header.itemcget(i, 'text')
                            for i in a.trim_section.header.find_all() if a.trim_section.header.type(i) == 'text'))

    def test_manual_size_before_import_survives_import_and_mode_switch(self):
        a = self.app
        a.mode_var.set('Задать размер фото')
        a.size_lock_var.set(False)
        a.print_w_var.set('44')
        a.print_h_var.set('55')
        self.photo(72)
        self.assertEqual((a._number(a.print_w_var), a._number(a.print_h_var)), (44, 55))
        a.mode_var.set('Фото с рамкой')
        a.mode_var.set('Задать размер фото')
        a.output_ppi_var.set('600')
        self.assertEqual((a._number(a.print_w_var), a._number(a.print_h_var)), (44, 55))
