"""Physical paper selection and normal printing of nearby formats; no spooler jobs."""
from dataclasses import replace
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import pywintypes

from illusive_print.app import create_root, IllusivePrintApp
from illusive_print.core import Layout
from illusive_print.print_dialog import PrintDialog
from illusive_print.windows_print import PaperFormat, DriverPaper, WindowsPrinter, close_paper, select_paper
from tests.support import make_photos
from tests.test_beta import FakePrinter


class PaperMatchingTests(unittest.TestCase):
    def test_limits_both_directions_orientation_and_exact_first(self):
        for a,b in (((100,150),(101.6,152.4)),((130,180),(127,177.8))):
            self.assertTrue(close_paper(a,b))
            self.assertTrue(close_paper(b,a))
        self.assertTrue(close_paper((103,153.2),(100,150)))
        self.assertFalse(close_paper((103.01,150),(100,150)))  # percentage limit
        self.assertFalse(close_paper((130,183.21),(130,180)))  # absolute limit
        self.assertFalse(close_paper((210,297),(130,180)))
        self.assertFalse(close_paper((180,130),(130,180)))
        self.assertFalse(close_paper((0,0),(130,180)))
        papers = [PaperFormat(91,'Completely different name',127,177.8),
                  PaperFormat(42,'Metric exact',130,180), PaperFormat(9,'A4',210,297)]
        self.assertEqual(select_paper(papers,(130,180)).identifier,42)
        self.assertEqual(select_paper(papers[:1],(180,130)).identifier,91)
        self.assertIsNone(select_paper(papers,(100,150)))

    def test_configure_driver_ids_not_names_and_custom_request_readback(self):
        backend = WindowsPrinter()
        source = pywintypes.DEVMODEType(8)
        source.DriverData = b'12345678'
        source.PaperSize,source.Orientation,source.Fields = 9,1,3
        formats = {2:(9,173,888),3:({'x':2100,'y':2970},{'x':1270,'y':1778},{'x':1300,'y':1800}),
                   16:('A4','Vendor mystery','Unrelated exact label')}
        accepted = []
        def properties(hwnd,handle,name,output,input_settings,mode):
            accepted.append(input_settings)
            output.PaperSize = input_settings.PaperSize
            output.Orientation = input_settings.Orientation
            output.DriverData = b'accepted'
            return 1
        with patch.object(backend.api,'OpenPrinter',return_value=1),patch.object(backend.api,'ClosePrinter'), \
             patch.object(backend.api,'GetPrinter',return_value={'pDevMode':source,'pPortName':'port'}), \
             patch.object(backend.api,'DeviceCapabilities',side_effect=lambda name,port,cap:formats[cap]), \
             patch.object(backend.api,'DocumentProperties',side_effect=properties) as native:
            result = backend.configure('Other driver',Layout(paper_width=130,paper_height=180))
            self.assertEqual(result.PaperSize,888)
            self.assertEqual(result.DriverData,b'accepted')
            formats[2],formats[3],formats[16] = (173,),({'x':1270,'y':1778},),('Mystery',)
            result = backend.configure('Other driver',Layout(paper_width=180,paper_height=130))
            self.assertEqual(result.PaperSize,173)
            self.assertEqual(result.Orientation,2)
            previous_count = native.call_count
            result = backend.configure('Other driver',Layout(paper_width=100,paper_height=150))
            self.assertEqual((result.PaperSize,result.Orientation,result.DriverData),(256,1,b'accepted'))
            self.assertEqual((accepted[-1].PaperWidth,accepted[-1].PaperLength),(1000,1500))
            self.assertEqual(native.call_count,previous_count+1)
            self.assertEqual((source.PaperSize,source.Orientation,source.DriverData),(9,1,b'12345678'))
            self.assertEqual(accepted[0].PaperSize,888)

    def test_shared_check_allows_close_but_not_a4_or_wrong_scale(self):
        layout = Layout(paper_width=130,paper_height=180)
        self.assertFalse(DriverPaper(127,177.8).mismatch(layout))
        self.assertTrue(DriverPaper(210,297).mismatch(layout))
        self.assertTrue(DriverPaper(127,177.8,scale=95).mismatch(layout))

    def test_manual_close_selection_survives_until_single_normal_submission(self):
        class Backend(FakePrinter):
            configures = 0
            def configure(inner,*args):
                inner.configures += 1
                return {'size':(210,297),'token':'initial'}
            def inspect(inner,name,settings): return DriverPaper(*settings['size'],name='Vendor 5x7')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(Path(folder)/'preferences.json')}):
            root = create_root()
            app = IllusivePrintApp(root)
            app.add_paths(make_photos(Path(folder)/'photos')[:1])
            app.paper_var.set('13 × 18 см')
            app.refresh()
            original_layout = app.layout
            original_photo = replace(app.photos[0])
            backend = Backend()
            dialog = PrintDialog(app,backend=backend)
            try:
                self.assertEqual(dialog.confirm_button.cget('state'),'disabled')
                selected = {'size':(127,177.8),'token':'manual private'}
                backend.returned = selected
                dialog.properties()
                self.assertEqual(dialog.confirm_button.cget('state'),'normal')
                self.assertIn('Края макета могут быть обрезаны',dialog.summary_var.get())
                self.assertIn('130 × 180',dialog.summary_var.get())
                self.assertIn('127 × 177.8',dialog.summary_var.get())
                self.assertIn('Vendor 5x7',dialog.summary_var.get())
                with patch('illusive_print.print_dialog.messagebox.askyesno') as prompt:
                    dialog.confirm()
                    dialog.confirm()
                    deadline = time.monotonic()+20
                    while dialog.job.state in ('preparing','sending') and time.monotonic()<deadline:
                        root.update()
                        time.sleep(.01)
                    prompt.assert_not_called()
                self.assertEqual(dialog.job.state,'sent')
                self.assertEqual(backend.configures,1)
                self.assertEqual(len(backend.calls),1)
                self.assertIs(backend.calls[0][1],selected)
                self.assertEqual(backend.calls[0][3],original_layout)
                self.assertEqual(app.layout,original_layout)
                self.assertEqual(app.photos[0],original_photo)
            finally:
                dialog.close()
                root.destroy()


if __name__ == '__main__':
    unittest.main()
