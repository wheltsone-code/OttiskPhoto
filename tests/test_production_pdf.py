from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,NumberObject,RectangleObject
from reportlab.pdfgen import canvas

from illusive_print.core import Photo,Layout,Correction,EdgeInsets,export_pdf,render_page
from illusive_print.document_sources import pdf_size


class ProductionPDFTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        raw=self.folder/'raw.pdf';c=canvas.Canvas(str(raw),pagesize=(200,300))
        c.setFillColorCMYK(1,0,0,0);c.rect(10,20,180,260,fill=1,stroke=0)
        c.setFillColorCMYK(0,0,0,1);c.drawString(30,150,'VECTOR FRONT');c.line(25,35,170,260);c.save()
        writer=PdfWriter(clone_from=raw);p=writer.pages[0]
        p[NameObject('/TrimBox')]=RectangleObject((20,30,180,270))
        p[NameObject('/BleedBox')]=RectangleObject((10,20,190,280))
        self.source=self.folder/'source.pdf';writer.write(self.source)
        self.photo=Photo(self.source,pdf_page=0,mode='fit')
        self.layout=Layout(mode='exact',paper_width=210,paper_height=297,print_width=60,print_height=90,margin=8)

    def tearDown(self):self.temp.cleanup()

    def test_trim_box_physical_size_rotation_and_user_unit(self):
        self.assertEqual(tuple(round(v,6) for v in pdf_size(self.source,0)),tuple(round(v*25.4/72,6) for v in (160,240)))
        writer=PdfWriter(clone_from=self.source);writer.pages[0].rotate(90)
        writer.pages[0][NameObject('/UserUnit')]=NumberObject(2)
        rotated=self.folder/'rotated.pdf';writer.write(rotated)
        self.assertEqual(tuple(round(v,6) for v in pdf_size(rotated,0)),tuple(round(v*25.4/72,6) for v in (480,320)))

    def test_vector_text_cmyk_and_shared_form_are_preserved(self):
        self.photo.copies=4;dest=self.folder/'vector.pdf'
        export_pdf(dest,[self.photo],self.layout,Correction())
        reader=PdfReader(dest);self.assertIn('VECTOR FRONT',reader.pages[0].extract_text())
        forms=[ref.get_object() for ref in reader.pages[0]['/Resources']['/XObject'].values()]
        self.assertEqual(len(forms),1);self.assertEqual(forms[0]['/Subtype'],'/Form')
        self.assertIn(b' k',forms[0].get_data())
        self.assertIn(b'BT',forms[0].get_data())

    def test_mixed_pdf_and_photo_keeps_vector(self):
        path=self.folder/'photo.png';Image.new('RGB',(200,300),'red').save(path)
        dest=self.folder/'mixed.pdf';export_pdf(dest,[self.photo,Photo(path)],self.layout,Correction())
        page=PdfReader(dest).pages[0];self.assertIn('VECTOR FRONT',page.extract_text())
        types={ref.get_object()['/Subtype'] for ref in page['/Resources']['/XObject'].values()}
        self.assertEqual(types,{'/Form','/Image'})

    def test_raster_color_operation_has_an_explicit_notice(self):
        from illusive_print.vector_pdf import pdf_export_notices
        self.assertEqual(pdf_export_notices([self.photo],Correction()),[])
        self.assertTrue(pdf_export_notices([self.photo],Correction(gamma=1.2)))

    def test_bleed_from_original_pdf_and_identical_preview_transform(self):
        import pypdfium2 as pdfium
        from PIL import ImageChops,ImageStat
        w,h=pdf_size(self.source,0)
        layout=Layout(mode='repeat',paper_width=80,paper_height=110,print_width=w,print_height=h,margin=8,repeat_front=self.photo.uid,repeat_quantity=1,bleed=EdgeInsets(2,2,2,2))
        dest=self.folder/'bleed.pdf';export_pdf(dest,[self.photo],layout,Correction())
        preview=render_page([self.photo],layout,0,Correction(),3)
        cell=layout.cells(1)[0]
        self.assertNotEqual(preview.getpixel((round((cell.x-1)*3),round((cell.y+10)*3))),(255,255,255))
        with pdfium.PdfDocument(dest) as document:
            page=document[0]
            try:
                bitmap=page.render(scale=3*25.4/72)
                try:output=bitmap.to_pil().convert('RGB').crop((0,0,preview.width,preview.height))
                finally:bitmap.close()
            finally:page.close()
        self.assertLess(max(ImageStat.Stat(ImageChops.difference(preview,output)).mean),3)

    def test_nearly_square_pdf_uses_physical_dimensions_for_rotation(self):
        from reportlab.lib.units import mm
        path=self.folder/'nearly-square.pdf';c=canvas.Canvas(str(path),pagesize=(100*mm,100.01*mm))
        c.setFillColorRGB(1,0,0);c.rect(0,0,50*mm,100.01*mm,fill=1,stroke=0)
        c.setFillColorRGB(0,0,1);c.rect(50*mm,0,50*mm,100.01*mm,fill=1,stroke=0);c.save()
        photo=Photo(path,pdf_page=0,mode='fit')
        layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=60,print_height=40,margin=0,repeat_front=photo.uid,repeat_quantity=1)
        cell=layout.cells(1)[0];preview=render_page([photo],layout,0,Correction(),3)
        # Upright pixels at 300 ppi round both source edges to 1181; that must
        # not erase the portrait aspect or change the vector export's rotation.
        from illusive_print.core import source_size
        info=source_size(photo);self.assertEqual(info.width_px,info.height_px)
        pixel=preview.getpixel((round((cell.x+cell.width*.75)*3),round((cell.y+cell.height*.25)*3)))
        self.assertGreater(pixel[0],240);self.assertLess(pixel[2],20)

    def test_raster_fit_preserves_border_inside_trim_when_bleed_is_added(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(300,200),'red');draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,299,199),outline=(0,255,0),width=6)
        path=self.folder/'fitted-border.png';image.save(path);photo=Photo(path,mode='fit')
        layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=60,print_height=40,margin=5,bleed=EdgeInsets(2,2,2,2),repeat_front=photo.uid,repeat_quantity=1)
        cell=layout.cells(1)[0];preview=render_page([photo],layout,0,Correction(),3)
        inside=preview.getpixel((round((cell.x+cell.width/2)*3),round((cell.y+.3)*3)))
        outside=preview.getpixel((round((cell.x+cell.width/2)*3),round((cell.y-1)*3)))
        self.assertGreater(inside[1],240);self.assertLess(inside[0],20)
        self.assertEqual(outside,(255,255,255))
