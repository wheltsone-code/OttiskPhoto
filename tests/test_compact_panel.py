"""Compact presentation must not alter order data or output geometry."""
import gc
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import Correction, PAPERS, export_pdf, render_page
from tests.support import make_photos


class CompactPanelTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.preferences = patch.dict(os.environ, OTTISK_PHOTO_PREFERENCES=str(Path(self.temp.name)/'preferences.json'))
        self.preferences.start()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.root.geometry('1270x840')
        self.app.add_paths(make_photos(Path(self.temp.name))[:2])
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.preferences.stop()
        self.temp.cleanup()

    def test_placement_and_square_summary(self):
        a = self.app
        a.mode_var.set('Задать размер фото')
        a.print_var.set('100 × 150 мм')
        a.gap_var.set('2')
        a.align_y_var.set('top')
        for button, expected in ((1, (2, 1, 100, 150)), (2, (1, 2, 150, 100))):
            a.placement_buttons[button].invoke()
            a.refresh()
            self.assertEqual(a.layout.exact_grid(), expected)
            self.assertEqual((a.layout.print_width, a.layout.print_height), (100, 150))
            self.assertEqual(a.layout.align_y, 'top')
            path=Path(self.temp.name)/f'placement-{button}.pdf'
            export_pdf(path,a.photos,a.layout,a.correction)
            reader=PdfReader(path)
            clips=[values for values,op in ContentStream(reader.pages[0].get_contents(),reader).operations if op==b're']
            self.assertEqual(len(clips),2)
            for clip,cell in zip(clips,a.layout.cells(limit=2)):
                for actual,wanted in zip(clip,(cell.x,297-cell.y-cell.height,cell.width,cell.height)):
                    self.assertAlmostEqual(float(actual)*25.4/72,wanted,places=4)
        a.print_var.set('Свой размер')
        a.size_lock_var.set(False)
        a.print_w_var.set('100'); a.print_h_var.set('100')
        a.refresh(); self.root.update()
        self.assertEqual(a.placement_hint.cget('text'), 'Авто · 2×2')
        self.assertTrue(all(not b.winfo_manager() for b in a.placement_buttons))

    def test_collapsing_keeps_color_trim_and_pdf(self):
        a = self.app
        self.assertTrue(a.color_section.opened)
        a.mode_var.set('Задать размер фото')
        self.assertFalse(a.color_section.opened)
        self.assertFalse(a.trim_section.opened)
        a.temperature_var.set('25')
        a.trim_var.set('Линии'); a.trim_inset_var.set('2')
        a.refresh()
        before = render_page(a.photos, a.layout, 0, a.correction, 1).tobytes()
        paths = [Path(self.temp.name)/f'fold-{n}.pdf' for n in range(2)]
        export_pdf(paths[0], a.photos, a.layout, a.correction, ppi=300)
        a.color_section.header.invoke(); a.trim_section.header.invoke()
        self.root.update(); a.refresh()
        export_pdf(paths[1], a.photos, a.layout, a.correction, ppi=300)
        self.assertEqual(before, render_page(a.photos, a.layout, 0, a.correction, 1).tobytes())
        readers = [PdfReader(p) for p in paths]
        streams = [ContentStream(r.pages[0].get_contents(), r).operations for r in readers]
        self.assertEqual(streams[0], streams[1])
        self.assertTrue(any(op == b'S' for _, op in streams[0]))
        for r in readers:
            image = next(iter(r.pages[0].images))
            self.assertEqual(image.image.getpixel((50, 50)), next(iter(readers[0].pages[0].images)).image.getpixel((50, 50)))
        a.trim_var.set('Нет'); a.refresh(); self.root.update()
        self.assertFalse(a.trim_entry.winfo_ismapped())
        self.assertFalse(a.trim_hint_label.winfo_ismapped())
        a.mode_var.set('Фото с рамкой')
        self.assertFalse(a.color_section.opened)
        self.assertFalse(a.trim_section.opened)
        self.root.update()
        self.assertLessEqual(a.settings_inner.winfo_reqheight(), a.settings_canvas.winfo_height())
        self.assertTrue(a.save_button.winfo_ismapped())

    def test_units_icons_and_confirmed_reset_preserve_order(self):
        a = self.app
        a.copy_vars[0].set('3'); a.refresh()
        a.language_var.set('English'); a.unit_var.set('in')
        self.assertNotIn('mm', a.paper_combo.display_value('A4'))
        self.assertIn('in', a.paper_combo.display_value('A4'))
        self.assertIn('in', a.paper_combo.popup_value('A4'))
        self.assertNotIn('mm', a.paper_combo.popup_value('A4'))
        a.language_var.set('Русский')
        self.assertEqual(a.unit_var.get(), 'in')
        self.assertEqual(a.language_combo.display_value('Русский'), 'RU')
        for icon in a.language_icons.values(): self.assertGreater(icon.width(), 0)
        a.photos[0].zoom=1.4; a.photos[0].rotation=1
        a.photos[0].correction=Correction(temperature=.3)
        a.correction=Correction(tint=.2)
        a.mode_var.set('Фото с рамкой'); a.trim_var.set('Линии')
        order=[(p.path,p.copies) for p in a.photos]
        with patch('illusive_print.app.messagebox.askyesno', return_value=False): a.reset_settings()
        self.assertEqual(a.mode_var.get(), 'Фото с рамкой')
        with patch('illusive_print.app.messagebox.askyesno', return_value=True): a.reset_settings()
        self.assertEqual([(p.path,p.copies) for p in a.photos], order)
        self.assertEqual((a.mode_var.get(),a.count_var.get(),a.margin_var.get(),a.gap_var.get()),('Разделить лист','1','0','0'))
        self.assertEqual((a.language_var.get(),a.unit_var.get()), ('Русский','in'))
        self.assertEqual(a.correction,Correction())
        self.assertTrue(all(p.zoom==1 and p.rotation==0 and p.offset_x==0 and p.mode=='fill' and p.correction is None and p.curve is None for p in a.photos))
        a.mode_var.set('Задать размер фото')
        self.assertEqual((a.margin_var.get(),a.placement_var.get(),a.align_x_var.get(),a.align_y_var.get()), ('3','Авто','center','center'))

    def test_gradient_track_zero_step_focus_and_header_state(self):
        a=self.app
        a.color_section.set_open(True)
        self.root.update()
        for control in (a.temperature_scale,a.tint_scale,a.saturation_scale):
            self.assertTrue(control.scale.find_withtag('gradient'))
            self.assertTrue(control.scale.find_withtag('neutral_mark'))
            self.assertIn('0',[control.ticks.itemcget(i,'text') for i in control.ticks.find_all() if control.ticks.type(i)=='text'])
            self.assertEqual(control.scale.cget('highlightcolor'),'#a82258')
        image=a.temperature_scale.scale._image
        left=self.root.tk.call(str(image),'get',0,3)
        right=self.root.tk.call(str(image),'get',image.width()-1,3)
        self.assertLess(left[0],left[2]); self.assertGreater(right[0],right[2])
        a.temperature_scale.scale.set(12.5)
        self.assertEqual(a.correction.temperature,.125)
        a.tint_scale.scale.set(-8.5)
        self.assertEqual(a.correction.tint,-.085)
        a.temperature_scale.reset()
        self.assertEqual(a.correction.temperature,0)
        self.assertEqual(a.correction.tint,-.085)
        self.assertIn('есть коррекция',a.color_section.header.cget('text'))
        with patch('illusive_print.app.messagebox.askyesno',return_value=False) as prompt:
            a.reset_settings()
        for field in ('раскладка','поля','зазор','выравнивание','подрезка','кадрирование','цвет'):
            self.assertIn(field,prompt.call_args.args[1])
