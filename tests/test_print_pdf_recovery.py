from dataclasses import replace
from pathlib import Path
import os
import gc
import tempfile
import time
from unittest.mock import Mock, patch
import unittest

import win32file
import win32con
from pypdf import PdfReader
from PIL import Image

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import Correction, Layout, Photo, PDFReplaceError, PDF_REPLACE_MESSAGE, export_pdf
from illusive_print.print_dialog import PrintDialog
from illusive_print.windows_print import DriverPaper, WindowsPrinter, clone_devmode
from tests.support import make_photos
from tests.test_beta import FakePrinter


class DriverAndUnitsTests(unittest.TestCase):
    def setUp(self):
        # Dispose prior test roots on Tk's main thread before an export worker
        # allocates enough PIL/PDF objects to trigger cyclic collection.
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'OTTISK_PHOTO_PREFERENCES':str(self.folder/'preferences.json')})
        self.env.start()
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.add_paths(make_photos(self.folder/'photos')[:1])
        self.app.paper_var.set('5 × 7″')
        self.app.refresh()
        self.root.update()
        self.dialog = None

    def tearDown(self):
        if self.dialog and self.dialog.window.winfo_exists():
            self.dialog.close()
        self.root.destroy()
        self.env.stop()
        self.temp.cleanup()

    def pump(self, predicate, seconds=20):
        end = time.monotonic()+seconds
        while predicate() and time.monotonic()<end:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(predicate())

    def test_driver_returned_job_context_summary_and_cancel_no_defaults(self):
        class Backend(FakePrinter):
            def __init__(self):
                super().__init__()
                self.inspected = []
                self.returned = {'size':(210,297), 'private':b'current A4'}
            def configure(inner,*args): return {'size':(210,297), 'private':b'initial A4', 'token':'A4'}
            def inspect(inner,name,settings):
                inner.inspected.append(settings)
                return DriverPaper(*settings['size'])
        backend = Backend()
        d = self.dialog = PrintDialog(self.app, backend=backend)
        for size in ((210,297), (127,177.8), (210,297)):
            returned = {'size':size, 'private':repr(size).encode(), 'token':repr(size)}
            backend.returned = returned
            d.properties()
            self.assertIs(d.settings, returned)
            self.assertIs(backend.inspected[-1], returned)
            self.assertIn(f'{size[0]:g} × {size[1]:g}', d.summary_var.get())
            self.assertEqual(d.paper, DriverPaper(*size))
            self.assertEqual(d.job.state,'idle')
        previous, count = d.settings, len(backend.inspected)
        backend.returned = None
        d.properties()
        self.assertIs(d.settings, previous)
        self.assertEqual(len(backend.inspected), count)
        d.close()
        self.dialog = None
        self.assertEqual(backend.calls, [])
        self.assertFalse(DriverPaper(126.98,177.79).mismatch(Layout(paper_width=127,paper_height=177.8)))
        self.assertFalse(DriverPaper(127,177.8).mismatch(Layout(paper_width=130,paper_height=180)))

    def test_manual_mismatch_unknown_cancel_and_double_submission(self):
        for unknown in (False, True):
            class Backend(FakePrinter):
                def __init__(inner):
                    super().__init__()
                    inner.manual = []
                def inspect(inner,*args):
                    if unknown: raise ValueError('unknown paper')
                    return DriverPaper(100,150)
                def submit(inner,*args,allow_driver_settings=False,**kwargs):
                    inner.manual.append(allow_driver_settings)
                    return super().submit(*args,**kwargs)
            backend = Backend()
            d = self.dialog = PrintDialog(self.app, backend=backend)
            self.assertIsNotNone(d.settings)
            self.assertEqual(d.confirm_button.cget('state'), 'disabled')
            self.assertEqual(d.override_button.cget('state'), 'normal')
            d.confirm()
            self.assertEqual(backend.calls, [])
            with patch('illusive_print.print_dialog.messagebox.askyesno', return_value=False):
                d.confirm_override()
            self.assertEqual(backend.calls, [])
            with patch('illusive_print.print_dialog.messagebox.askyesno', return_value=True) as confirm:
                d.confirm_override()
                d.confirm_override()
                d.confirm()
            self.pump(lambda:d.job.state in ('preparing','sending'))
            self.assertEqual(d.job.state,'sent')
            self.assertEqual(backend.manual,[True])
            self.assertEqual(len(backend.calls),1)
            self.assertIs(backend.calls[0][1],d.settings)
            self.assertEqual(confirm.call_count,1)
            self.assertIn('обрез',confirm.call_args.args[1])
            d.close()
            self.dialog = None

    def test_units_both_languages_popup_labels_and_invariant_geometry(self):
        app = self.app
        geometry = app.layout
        for lang, expected in (('English',('mm','in')),('Русский',('мм','дюймы'))):
            for unit in ('mm','in'):
                app.unit_var.set(unit)
                app.language_var.set(lang)
                app.units_combo.open()
                self.assertEqual(app.units_combo.listbox.get(0,'end'),expected)
                app.units_combo.close()
                self.assertEqual(app.unit_var.get(),unit)
                self.assertEqual(app.layout,geometry)
        self.assertIn('130 × 180',app.format_preset('13 × 18 см',__import__('illusive_print.core',fromlist=['PAPERS']).PAPERS))
        self.assertIn('127 × 177.8',app.format_preset('5 × 7″',__import__('illusive_print.core',fromlist=['PAPERS']).PAPERS))

    def test_pdf_recovery_window_retry_save_as_and_cancel_without_rerender(self):
        app = self.app
        app.paper_var.set('10 × 15 см')
        app.refresh()
        dest = self.folder/'locked.pdf'
        export_pdf(dest,app.photos,app.layout,Correction())
        original = dest.read_bytes()
        handle = win32file.CreateFile(str(dest), win32con.GENERIC_READ, win32con.FILE_SHARE_READ,
                                     None,win32con.OPEN_EXISTING,0,None)
        from illusive_print import core
        try:
            with patch('illusive_print.app.export_pdf',wraps=core.export_pdf) as render:
                app._start_export(dest)
                self.pump(lambda:app._exporting)
                self.assertIsNotNone(app._pending_pdf)
                self.assertTrue(app._pdf_recovery_window.winfo_exists())
                self.assertEqual(dest.read_bytes(),original)
                prepared = app._pending_pdf.path
                count = render.call_count
                # Retry still locked; no second image processing pass.
                app._retry_pdf(dest)
                self.pump(lambda:app._exporting)
                self.assertEqual(render.call_count,count)
                new = self.folder/'new.pdf'
                with patch('illusive_print.app.filedialog.asksaveasfilename',return_value=str(new)):
                    app._save_pdf_as()
                self.pump(lambda:app._exporting)
                self.assertEqual(render.call_count,count)
                self.assertTrue(new.exists())
                self.assertFalse(prepared.exists())
                app._start_export(dest)
                self.pump(lambda:app._exporting)
                prepared = app._pending_pdf.path
                app._cancel_pdf_recovery()
                self.assertFalse(prepared.exists())
                self.assertEqual(dest.read_bytes(),original)
        finally:
            handle.Close()
        # Closing the viewer-style Windows handle makes the same prepared PDF retryable.
        handle = win32file.CreateFile(str(dest),win32con.GENERIC_READ,win32con.FILE_SHARE_READ,None,win32con.OPEN_EXISTING,0,None)
        app._start_export(dest)
        self.pump(lambda:app._exporting)
        stage = app._pending_pdf.path
        handle.Close()
        app._retry_pdf(dest)
        self.pump(lambda:app._exporting)
        self.assertFalse(stage.exists())
        self.assertIsNone(app._pending_pdf)
        self.assertEqual(len(PdfReader(dest).pages),1)


class PDFAndNativeContracts(unittest.TestCase):
    def test_manual_gdi_keeps_job_data_and_layout_scale_for_mismatch_or_unknown(self):
        import pywintypes
        from illusive_print.windows_print import PrinterOpenError, PrintSubmissionError
        backend = WindowsPrinter()
        dm = pywintypes.DEVMODEType(8)
        dm.DriverData = b'12345678'
        dm.Scale, dm.Copies, dm.Fields = 75, 2, 16 | 256
        layout = Layout(paper_width=130, paper_height=180)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'page.bmp'
            Image.new('RGB',(20,30),'red').save(path)
            for physical in ((2100,2970),(0,0)):
                dc, gdi = Mock(), Mock()
                caps = {110:physical[0],111:physical[1],88:254,90:254,112:3,113:4}
                dc.GetDeviceCaps.side_effect = caps.__getitem__
                dc.GetHandleOutput.return_value = 123
                dc.StartDoc.return_value = 42
                gdi.SetICMMode.return_value = 1
                with patch.object(backend,'_dc',return_value=dc) as create, \
                     patch('illusive_print.windows_print.ctypes.WinDLL',return_value=gdi), \
                     patch('PIL.ImageWin.Dib') as dib:
                    self.assertEqual(backend.submit('Any printer',dm,[path],layout,False,'Test',allow_driver_settings=True),42)
                    used = create.call_args.args[1]
                    self.assertEqual(used.DriverData,dm.DriverData)
                    self.assertEqual((used.Scale,used.Copies),(100,1))
                    self.assertEqual((dm.Scale,dm.Copies),(75,2))
                    dib.return_value.draw.assert_called_once_with(123,(-3,-4,1297,1796))
                    dc.StartDoc.assert_called_once()
                    dc.StartDoc.side_effect = OSError('spooler rejected')
                    with self.assertRaises(PrintSubmissionError):
                        backend.submit('Any printer',dm,[],layout,False,'Test',allow_driver_settings=True)
        with patch.object(backend.api,'OpenPrinter',side_effect=OSError('offline')):
            with self.assertRaises(PrinterOpenError):
                backend.properties(0,'Missing',dm)

    def test_media_crop_boxes_direct_mm_at_300_and_600(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = folder/'photo.png'
            Image.new('RGB',(400,600),'red').save(image)
            for width,height in ((130,180),(127,177.8)):
                boxes = []
                for ppi in (300,600):
                    path = folder/f'{width}-{ppi}.pdf'
                    layout = Layout(paper_width=width,paper_height=height,per_sheet=1)
                    export_pdf(path,[Photo(image)],layout,Correction(),ppi)
                    page = PdfReader(path).pages[0]
                    for box in (page.mediabox,page.cropbox):
                        self.assertAlmostEqual(float(box.width)*25.4/72,width,places=6)
                        self.assertAlmostEqual(float(box.height)*25.4/72,height,places=6)
                    self.assertEqual(page.mediabox,page.cropbox)
                    boxes.append(tuple(page.mediabox))
                self.assertEqual(boxes[0],boxes[1])

    def test_native_cancel_preserves_even_mutated_input_and_full_private_data(self):
        import pywintypes
        dm = pywintypes.DEVMODEType(8)
        dm.DriverData = b'12345678'
        dm.PaperSize, dm.Fields = 9, 2
        b = WindowsPrinter()
        def cancelled(hwnd,handle,name,output,input_settings,mode):
            input_settings.PaperSize = 173
            input_settings.DriverData = b'abcdefgh'
            return 2
        with patch.object(b.api,'OpenPrinter',return_value=1),patch.object(b.api,'ClosePrinter'), \
             patch.object(b.api,'DocumentProperties',side_effect=cancelled):
            self.assertIsNone(b.properties(0,'Fake',dm))
        self.assertEqual(dm.PaperSize,9)
        self.assertEqual(dm.DriverData,b'12345678')
        cloned = clone_devmode(dm)
        self.assertEqual(cloned.DriverData,dm.DriverData)


if __name__ == '__main__':
    unittest.main()
