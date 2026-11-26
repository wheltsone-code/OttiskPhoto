from pathlib import Path
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pypdf import PdfReader
from illusive_print.vector_import import identify, prepare_document, module_root, ImportCancelled, run_process
from illusive_print.document_sources import pdf_pages, pdf_size
from illusive_print.core import Photo, Layout, Correction, source_size, export_pdf
from tools.vector_fixtures import make_vectors


class VectorImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=make_vectors(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_content_checks_and_ai_pdf_real_pages(self):
        self.assertEqual(identify(self.folder/'pdf-compatible.ai'),'ai-pdf')
        self.assertEqual(pdf_pages(self.folder/'pdf-compatible.ai'),2)
        self.assertEqual(identify(self.folder/'postscript.ai'),'ai-postscript')
        with self.assertRaisesRegex(ValueError,'AI:'):identify(self.folder/'false.ai')
        bad=self.folder/'fake.cdr';bad.write_bytes(b'RIFF'+b'\x00'*4+b'CDR3')
        with self.assertRaisesRegex(ValueError,'CDR 3'):identify(bad)
        bad.write_bytes(b'not CDR')
        with self.assertRaisesRegex(ValueError,'CDR:'):identify(bad)
        bad=self.folder/'external.svg';bad.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.org/a.png"/></svg>')
        with self.assertRaisesRegex(ValueError,'SVG:'):identify(bad)

    @unittest.skipUnless((module_root()/'inkscape/bin/inkscape.com').is_file(),'local Inkscape module required')
    def test_svg_features_sizes_pages_and_vector_export(self):
        from illusive_print import vector_import as vectors
        from illusive_print.disk_cache import DiskCache
        with patch('illusive_print.vector_import.document_cache',return_value=DiskCache(self.folder/'cache')):
            path=self.folder/'features.svg';original=path.read_bytes()
            prepared=prepare_document(path)
            self.assertFalse(prepared.cache_hit)
            self.assertAlmostEqual(pdf_size(prepared.path,0)[0],70,places=3)
            self.assertAlmostEqual(pdf_size(prepared.path,0)[1],45,places=3)
            page=PdfReader(prepared.path).pages[0]
            self.assertIn('VECTOR text',page.extract_text())
            self.assertIn('/ExtGState',page['/Resources'])
            vectors._ready.clear()
            with patch('illusive_print.vector_import.run_process',side_effect=AssertionError('must reuse disk result')):
                self.assertTrue(prepare_document(path).cache_hit)
            self.assertEqual(path.read_bytes(),original)
            multipage=prepare_document(self.folder/'multipage.svg')
            self.assertEqual(pdf_pages(multipage.path),2)
            for index in (0,1):
                w,h=pdf_size(multipage.path,index)
                self.assertAlmostEqual(w,70,places=4);self.assertAlmostEqual(h,45,places=4)
            photo=Photo(path,pdf_page=0,flip_x=True)
            self.assertAlmostEqual(source_size(photo).physical_mm[0],70,places=3)
            output=self.folder/'output.pdf';export_pdf(output,[photo],Layout(),Correction(),300,'vector-test')
            self.assertEqual(PdfReader(output).metadata.title,'vector-test')
            self.assertIn('VECTOR text',PdfReader(output).pages[0].extract_text())

    @unittest.skipUnless((module_root()/'ghostscript/bin/gswin64c.exe').is_file(),'local Ghostscript module required')
    def test_eps_and_postscript_ai_preserve_text_and_sizes(self):
        for name in ('features.eps','postscript.ai'):
            result=prepare_document(self.folder/name)
            self.assertIn('POSTSCRIPT text',PdfReader(result.path).pages[0].extract_text())
            if name.endswith('.eps'):
                w,h=pdf_size(result.path,0)
                self.assertAlmostEqual(w,200*25.4/72,places=3);self.assertAlmostEqual(h,100*25.4/72,places=3)

    def test_subprocess_cancellation(self):
        import sys
        event=threading.Event();timer=threading.Timer(.15,event.set);timer.start()
        started=time.monotonic()
        with self.assertRaises(ImportCancelled):run_process([sys.executable,'-c','import time; time.sleep(30)'],event)
        self.assertLess(time.monotonic()-started,3)
        timer.join()

    @unittest.skipUnless((module_root()/'inkscape/bin/inkscape.com').is_file(),'local import module required')
    def test_real_cdr15_and_eps_libreoffice_regressions(self):
        folder=Path(__file__).parent/'fixtures/vector'
        cdr=folder/'cdr15.cdr'
        self.assertEqual(identify(cdr),'cdr-15')
        result=prepare_document(cdr)
        self.assertEqual(pdf_pages(result.path),1)
        w,h=pdf_size(result.path,0)
        self.assertAlmostEqual(w,210,places=2);self.assertAlmostEqual(h,297,places=2)
        self.assertTrue(PdfReader(result.path).pages[0].get_contents().get_data())
        result=prepare_document(folder/'libreoffice.eps')
        self.assertGreaterEqual(pdf_pages(result.path),1)

    def test_background_import_ui_heartbeat_cancel_and_error_isolation(self):
        from illusive_print.app import create_root,IllusivePrintApp
        from PIL import Image
        with patch.dict(os.environ,OTTISK_PHOTO_PREFERENCES=str(self.folder/'prefs.json')):
            root=create_root();app=IllusivePrintApp(root)
            started=threading.Event();release=threading.Event();threads=[]
            real=__import__('illusive_print.import_tasks',fromlist=['load_preview_source']).load_preview_source
            path=self.folder/'photo.png';Image.new('RGB',(40,30),'red').save(path)
            def slow(photo):
                threads.append(threading.get_ident());started.set();release.wait(2)
                return real(photo)
            try:
                with patch('illusive_print.import_tasks.load_preview_source',side_effect=slow):
                    app.start_import([path]);self.assertTrue(started.wait(1))
                    tick=[];root.after(0,lambda:tick.append(True));root.update()
                    self.assertEqual(tick,[True]);app._import_job['cancel'].set();release.set()
                    until=time.monotonic()+4
                    while app._import_job and time.monotonic()<until:root.update();time.sleep(.01)
                self.assertFalse(app.photos)
                app.start_import([self.folder/'false.ai',path])
                until=time.monotonic()+4
                while app._import_job and time.monotonic()<until:root.update();time.sleep(.01)
                self.assertIsNone(app._import_job)
                self.assertEqual(len(app.photos),1);self.assertEqual(len(app.last_import_errors),1)
                self.assertTrue(all(t!=threading.get_ident() for t in threads))
            finally:release.set();root.destroy()
