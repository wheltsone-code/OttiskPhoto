import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from PIL import Image
from illusive_print.core import Photo,Layout,Correction,render_page
from illusive_print.preview import PreviewRenderer

class ProductionScreenTests(unittest.TestCase):
    def test_reuses_sheet_and_invalidates_crop_without_full_color_work(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.png';Image.new('RGB',(1000,700),(60,130,200)).save(path)
            photo=Photo(path);layout=Layout(mode='repeat',print_width=60,print_height=40,repeat_front=photo.uid,repeat_quantity=100)
            renderer=PreviewRenderer()
            with patch('illusive_print.core._corrected_source',side_effect=AssertionError('Full-resolution preview correction')):
                first=renderer.prepare([photo],layout,0,Correction(teal_orange='a_to_b'),2)
                same=renderer.prepare([photo],layout,0,Correction(teal_orange='a_to_b'),2)
                self.assertIs(first.image,same.image);self.assertEqual(same.changed,[])
                photo.offset_x=.4
                moved=renderer.prepare([photo],layout,0,Correction(teal_orange='a_to_b'),2)
                self.assertTrue(moved.changed)
            # Preview must never substitute its small tile for an output tile.
            output=render_page([photo],layout,0,Correction(),2)
            self.assertEqual(output.size,first.image.size)

    def test_screen_fit_bleed_preserves_white_outer_border(self):
        from illusive_print.core import EdgeInsets
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.png';Image.new('RGB',(100,100),'red').save(path)
            photo=Photo(path,mode='fit');layout=Layout(mode='repeat',print_width=60,print_height=40,margin=5,bleed=EdgeInsets(2,2,2,2),repeat_front=photo.uid)
            frame=PreviewRenderer().prepare([photo],layout,0,Correction(),3)
            cell=layout.cells()[0]
            self.assertEqual(frame.image.getpixel((round((cell.x-1)*3),round((cell.y+10)*3))),(255,255,255))
