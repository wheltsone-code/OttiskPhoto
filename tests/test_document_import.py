from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from pypdf import PdfReader, PdfWriter
from psd_tools import PSDImage
from psd_tools.constants import Resource
from psd_tools.psd.image_resources import ImageResource, VersionInfo

from illusive_print.app import create_root, IllusivePrintApp
from illusive_print.core import Photo, Layout, Rect, Correction, load_source, source_size, render_photo, export_pdf
from illusive_print.document_sources import pdf_size, parse_pages, psd_composite, pdf_pages
from illusive_print.color_management import srgb_bytes
from tests.test_file_drop import send_drop


def fixtures(folder):
    folder.mkdir(parents=True,exist_ok=True)
    page = folder/'Макет 70x45.pdf'
    c = canvas.Canvas(str(page),pagesize=(70*mm,45*mm))
    c.setFillColorRGB(.2,.5,.8)
    c.rect(0,0,70*mm,45*mm,fill=1,stroke=0)
    c.showPage()
    c.save()
    writer = PdfWriter()
    for _ in range(4): writer.add_page(PdfReader(page).pages[0])
    writer.pages[1].rotate(90)
    writer.pages[2].cropbox.lower_left = (10*mm,5*mm)
    writer.pages[2].cropbox.upper_right = (60*mm,40*mm)
    with (folder/'Несколько страниц.pdf').open('wb') as stream: writer.write(stream)
    locked = PdfWriter(clone_from=PdfReader(page))
    locked.encrypt('secret')
    with (folder/'Пароль.pdf').open('wb') as stream: locked.write(stream)
    rgba = Image.new('RGBA',(300,200),(255,0,0,0))
    rgba.paste((60,100,150,255),(50,50,150,150))
    psd = PSDImage.frompil(rgba)
    psd.image_resources[Resource.ICC_PROFILE] = ImageResource(key=Resource.ICC_PROFILE,data=srgb_bytes())
    psd.save(folder/'Прозрачность ICC.psd')
    psd.image_resources[Resource.VERSION_INFO] = ImageResource(key=Resource.VERSION_INFO,data=VersionInfo(has_composite=False))
    psd.save(folder/'Без совместимости.psd')
    Image.new('RGB',(400,200),'orange').save(folder/'Обычное фото.jpg')
    Image.new('RGB',(200,400),'green').save(folder/'Фото.webp')
    from pillow_heif import from_pillow
    from_pillow(Image.new('RGB',(200,300),'blue')).save(folder/'Фото.heic')
    (folder/'Повреждённый.jpg').write_bytes(b'broken')
    return page


class DocumentImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.page = fixtures(self.folder/'Папка с кириллицей')
        self.env = patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(self.folder/'preferences.json')})
        self.env.start()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
    def tearDown(self):
        self.root.destroy()
        self.env.stop()
        self.temp.cleanup()

    def test_single_range_rotation_cropbox_dedupe_physical_size_and_render_density(self):
        app = self.app
        self.assertEqual(app.add_paths([self.page]),(1,0))
        self.assertLess(max(load_source(app.photos[0]).size),300)  # import is a thumbnail render
        self.assertAlmostEqual(pdf_size(self.page,0)[0],70,places=4)
        self.assertAlmostEqual(pdf_size(self.page,0)[1],45,places=4)
        app.take_pdf_size()
        self.assertEqual(app.paper_var.get(),'A4')
        self.assertAlmostEqual(app._number(app.print_w_var),70,places=4)
        self.assertAlmostEqual(app._number(app.print_h_var),45,places=4)
        multi = self.page.parent/'Несколько страниц.pdf'
        with patch.object(app,'choose_pdf_import',return_value=parse_pages('2, 4',4)):
            self.assertEqual(app.add_paths([multi]),(2,0))
            self.assertEqual(app.add_paths([multi]),(0,2))
        self.assertEqual([p.pdf_page for p in app.photos],[0,1,3])
        self.assertAlmostEqual(pdf_size(multi,1)[0],45,places=4)
        self.assertAlmostEqual(pdf_size(multi,1)[1],70,places=4)
        self.assertAlmostEqual(pdf_size(multi,2)[0],50,places=4)
        self.assertAlmostEqual(pdf_size(multi,2)[1],35,places=4)
        from illusive_print import document_sources as documents
        original = documents.pdf_render
        for ppi in (300,600):
            with patch.object(documents,'pdf_render',wraps=original) as render:
                render_photo(app.photos[0],Rect(0,0,70,45),Correction(),(round(70*ppi/25.4),round(45*ppi/25.4)))
                self.assertAlmostEqual(render.call_args.args[2],ppi,delta=1)
        self.assertEqual(parse_pages('1–3, 3, 4',4),[0,1,2,3])
        with self.assertRaises(ValueError): parse_pages('0, 8',4)

    def test_psd_merged_alpha_icc_once_and_no_layer_fallback(self):
        from illusive_print import document_sources as documents
        from illusive_print.color_management import to_srgb
        path = self.page.parent/'Прозрачность ICC.psd'
        with patch.object(documents,'to_srgb',wraps=to_srgb) as convert, patch.object(PSDImage,'composite',side_effect=AssertionError('must not composite')):
            image = psd_composite(path)
            self.assertEqual(convert.call_count,1)
            self.assertEqual(image.getpixel((0,0)),(255,255,255))
            self.assertEqual(image.info['icc_profile'],srgb_bytes())
        with self.assertRaisesRegex(ValueError,'максимальной совместимостью'):
            psd_composite(self.page.parent/'Без совместимости.psd')

    def test_folder_one_policy_mixed_errors_and_tcl_drop_not_a_mouse_gesture(self):
        app = self.app
        with patch.object(app,'choose_pdf_import',return_value='Только первые страницы') as policy:
            send_drop(app.preview_canvas,[self.page.parent])
            self.root.update()
            policy.assert_called_once_with()
        self.assertEqual(len(app.photos),6) # two PDFs, PSD, JPG, HEIC, WebP
        self.assertEqual(sum(p.pdf_page is not None for p in app.photos),2)
        self.assertEqual(len(app.last_import_errors),3) # locked PDF, broken JPG, incompatible PSD
        self.assertIn('Добавлено 6 фото, пропущено 3',app.status_var.get())
        self.assertTrue(all(app.preview_canvas.bind(event) for event in ('<Button-1>','<B1-Motion>','<ButtonRelease-1>')))
        dest = self.folder/'контроль.pdf'
        export_pdf(dest,app.photos,app.layout,app.correction)
        self.assertTrue(dest.stat().st_size>1000)
        with self.assertRaisesRegex(ValueError,'пароль'): pdf_pages(self.page.parent/'Пароль.pdf')
        for choice in ('Все страницы','Пропустить PDF'):
            with patch.object(app,'choose_pdf_import',return_value=choice) as policy:
                app.add_paths([self.page.parent/'Несколько страниц.pdf'],report_errors=False,folder_batch=True)
                policy.assert_called_once_with()


if __name__ == '__main__': unittest.main()
