from dataclasses import replace
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageChops, ImageStat
from reportlab.pdfgen import canvas
from pypdf import PdfReader
from illusive_print.core import Photo, Rect, Layout, Correction, render_photo, render_page, export_pdf, photo_slot, CardTemplate
from illusive_print.preview import PreviewRenderer
from illusive_print.app import create_root, IllusivePrintApp
from illusive_print.print_job import PrintSnapshot


class ReflectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.path=self.folder/'corners.png'
        image=Image.new('RGB',(300,200),'white')
        for box,color in [((0,0,150,100),'red'),((150,0,300,100),'green'),((0,100,150,200),'blue'),((150,100,300,200),'yellow')]:
            image.paste(color,box)
        image.save(self.path)
        self.pdf=self.folder/'corners.pdf';c=canvas.Canvas(str(self.pdf),pagesize=(300,200))
        for x,y,color in [(0,100,(1,0,0)),(150,100,(0,.5,0)),(0,0,(0,0,1)),(150,0,(1,1,0))]:
            c.setFillColorRGB(*color);c.rect(x,y,150,100,fill=1,stroke=0)
        c.drawString(20,20,'VECTOR');c.save()
    def tearDown(self):self.temp.cleanup()

    def test_screen_axes_crop_rotation_auto_and_cache_recovery(self):
        from illusive_print.image_cache import FULL_IMAGES,PREVIEW_IMAGES
        for path,page in [(self.path,None),(self.pdf,0)]:
            for turns in range(4):
                for auto in (True,False):
                    for mode in ('fill','fit'):
                        p=Photo(path,pdf_page=page,rotation=turns,mode=mode,zoom=1.3,offset_x=.4,offset_y=-.3)
                        cell=Rect(0,0,50,70)
                        original=render_photo(p,cell,Correction(),(150,210),auto)
                        for horizontal,transpose in [(True,Image.Transpose.FLIP_LEFT_RIGHT),(False,Image.Transpose.FLIP_TOP_BOTTOM)]:
                            q=replace(p);q.reflect(horizontal)
                            actual=render_photo(q,cell,Correction(),(150,210),auto)
                            self.assertLess(max(ImageStat.Stat(ImageChops.difference(actual,original.transpose(transpose))).mean),.3)
                            FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
                            self.assertEqual(actual.tobytes(),render_photo(q,cell,Correction(),(150,210),auto).tobytes())
                        q=replace(p);q.reflect();q.reflect();self.assertEqual(p,q)

    def test_vector_pdf_print_preview_agree_all_matrices(self):
        import pypdfium2 as pdfium
        for turns in range(4):
            for fx,fy in [(True,False),(False,True),(True,True)]:
                p=Photo(self.pdf,pdf_page=0,rotation=turns,flip_x=fx,flip_y=fy,zoom=1.2,offset_x=.25,offset_y=-.3)
                layout=Layout(paper_width=80,paper_height=100,margin=3,autorotate=False)
                output=self.folder/'export.pdf';export_pdf(output,[p],layout,Correction())
                self.assertIn('VECTOR',PdfReader(output).pages[0].extract_text())
                reference=render_page([p],layout,0,Correction(),3)
                screen=PreviewRenderer().prepare([p],layout,0,Correction(),3).image
                with pdfium.PdfDocument(output) as doc:
                    page=doc[0];bitmap=page.render(scale=3*25.4/72)
                    actual=bitmap.to_pil().convert('RGB').crop((0,0,reference.width,reference.height))
                    bitmap.close();page.close()
                self.assertLess(max(ImageStat.Stat(ImageChops.difference(actual,reference)).mean),3)
                self.assertLess(max(ImageStat.Stat(ImageChops.difference(screen,reference)).mean),3)

    def test_batch_undo_reset_and_background_snapshots(self):
        with patch.dict(os.environ,OTTISK_PHOTO_PREFERENCES=str(self.folder/'preferences.json')):
            root=create_root();a=IllusivePrintApp(root)
            try:
                a.add_paths([self.path,self.pdf]);a.selected_rows={0,1}
                a.photos[0].offset_x=.4
                original=[replace(p) for p in a.photos]
                a.reflect_photos(True)
                self.assertTrue(all(p.flip_x for p in a.photos))
                snapshot=PrintSnapshot.capture(a.photos,a.layout,a.correction,0).photos
                a.undo();self.assertEqual(a.photos,original)
                self.assertTrue(all(p.flip_x for p in snapshot))
                a.reflect_photos(False);a.reset_frame()
                self.assertTrue(all(not p.flip_x and not p.flip_y for p in a.photos))
                a.undo();self.assertTrue(all(p.flip_y for p in a.photos))
                a.rotate_photo();self.assertTrue(all(p.flip_x and not p.flip_y for p in a.photos))
                a.language_var.set('English')
                self.assertEqual(a.display_text('↔ Отразить'),'↔ Mirror')
            finally:root.destroy()
