from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from illusive_print.app import create_root, IllusivePrintApp, PINK
from illusive_print.core import Correction
from illusive_print.i18n import save_preferences
from tests.support import make_photos


class BatchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(self.folder/'preferences.json')})
        self.env.start()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.add_paths(make_photos(self.folder/'photos')[:3])
        self.root.update()
    def tearDown(self):
        self.root.destroy()
        self.env.stop()
        self.temp.cleanup()
    def select_pair(self):
        self.app.library_click(0,SimpleNamespace(state=0))
        self.app.library_click(2,SimpleNamespace(state=4))

    def test_ctrl_shift_copies_highlight_all_pages_and_title(self):
        a = self.app
        a.count_var.set('2')
        a.copy_vars[0].set('3')
        a.copy_vars[2].set('2')
        self.select_pair()
        self.assertEqual(a.selected_rows,{0,2})
        self.assertEqual(a.selection_title_var.get(),'Выбрано: 2 фото')
        a.page = 0
        a.refresh()
        for expected in (2,1,2):
            a.root.update()
            selected = a.preview_canvas.find_withtag('selected_instance')+a.preview_canvas.find_withtag('selected_copy')
            self.assertEqual(len(selected),expected)
            self.assertTrue(all(a.preview_canvas.itemcget(i,'outline')==PINK for i in selected))
            self.assertEqual(a.selected_rows,{0,2})
            a.turn_page(1)
        a.library_click(1,SimpleNamespace(state=1))
        self.assertEqual(a.selected_rows,{1,2})
        a.library_click(0,SimpleNamespace(state=1))
        self.assertEqual(a.selected_rows,{0,1,2})
        a.library_click(1,SimpleNamespace(state=4))
        self.assertEqual(a.selected_rows,{0,2})

    def test_batch_crop_rotation_zoom_reset_and_drag_one_only(self):
        a = self.app
        a.count_var.set('2')
        self.select_pair()
        other = replace(a.photos[1])
        a.photos[0].rotation,a.photos[2].rotation = 0,2
        a.photos[0].zoom,a.photos[2].zoom = 1,1.3
        a.refresh()
        self.assertIn('Разные значения',a.selected_var.get())
        a.selected_mode('fit')
        self.assertEqual([p.mode for p in a.photos],['fit','fill','fit'])
        a.rotate_photo()
        self.assertEqual([p.rotation for p in a.photos],[1,0,3])
        a.zoom_photo()
        self.assertEqual([p.zoom for p in a.photos],[1.1,1,1.4])
        a.zoom_photo(-10)
        self.assertEqual([p.zoom for p in a.photos],[1,1,1.3])
        self.assertEqual(a.photos[1],other)
        a.page = 0
        a.refresh()
        cell = a.layout.cells()[0]
        event = SimpleNamespace(x=a.preview_origin[0]+(cell.x+cell.width/2)*a.preview_scale,
                                y=a.preview_origin[1]+(cell.y+cell.height/2)*a.preview_scale)
        untouched = replace(a.photos[2])
        a.begin_drag(event)
        a.drag_motion(SimpleNamespace(x=event.x+40,y=event.y+35))
        a.end_drag()
        self.assertEqual(a.selected_rows,{0,2})
        self.assertEqual(a.photos[2],untouched)
        self.assertEqual(a.photos[1],other)
        a.reset_frame()
        self.assertTrue(all((p.rotation,p.zoom,p.offset_x,p.offset_y)==(0,1,0,0) for p in (a.photos[0],a.photos[2])))
        self.assertEqual(a.photos[1],other)

    def test_individual_parameter_only_preserves_gamma_curves_other_photo_and_global(self):
        a = self.app
        c1 = ((0,0),(128,150),(255,255))
        c2 = ((0,0),(128,80),(255,255))
        a.photos[0].correction = Correction(.1,1.1,c1,.2,.1)
        a.photos[2].correction = Correction(.3,1.4,c2,-.2,-.1)
        a.photos[0].curve,a.photos[2].curve = c1,c2
        self.select_pair()
        untouched,global_color = replace(a.photos[1]),a.correction
        self.assertTrue(a.individual_color_var.get())
        self.assertIn('Разные значения',a.mixed_color_var.get())
        a.temperature_var.set('12,5')
        self.assertEqual([a.photos[i].correction.temperature for i in (0,2)],[.125,.125])
        self.assertEqual([a.photos[i].correction.gamma for i in (0,2)],[1.1,1.4])
        self.assertEqual([a.photos[i].correction.curve for i in (0,2)],[c1,c2])
        self.assertNotIn('Температура',a.mixed_color_var.get())
        a.tint_var.set('8')
        self.assertEqual([a.photos[i].correction.tint for i in (0,2)],[.08,.08])
        self.assertEqual(a.photos[1],untouched)
        self.assertEqual(a.correction,global_color)
        a.reset_color()
        self.assertEqual([a.photos[i].correction.curve for i in (0,2)],[c1,c2])
        a.set_individual_color(False)
        a.temperature_var.set('20')
        self.assertEqual(a.correction.temperature,.2)

    def test_fresh_default_one_and_session_choice_preserved_by_language(self):
        self.assertEqual(self.app.count_var.get(),'1')
        self.app.count_var.set('4')
        self.app.language_var.set('English')
        data = json.loads((self.folder/'preferences.json').read_text())
        self.assertEqual(data['photos_per_sheet'],'4')
        self.root.destroy()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.assertEqual(self.app.count_var.get(),'1')


if __name__ == '__main__': unittest.main()
