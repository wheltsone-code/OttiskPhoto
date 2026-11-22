from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium

from illusive_print.core import Photo,Layout,Correction,ordered_tokens,page_items,page_count,render_page,export_pdf,correct_image
from illusive_print.color import _rgb_lab,copy_lab_channels,teal_orange
from illusive_print.preview import PreviewRenderer
from illusive_print.print_job import PrintSnapshot
from illusive_print.app import IllusivePrintApp,create_root


class FoldingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.photos=[]
        for i in range(8):
            p=self.folder/f'{i+1}.png'
            Image.new('RGB',(50,70),(20+i*25,40+i*20,220-i*20)).save(p)
            self.photos.append(Photo(p))
        self.layout=Layout(mode='booklet',paper_width=100,paper_height=70,margin=3,autorotate=False)

    def tearDown(self): self.temp.cleanup()

    def test_booklet_reading_sequence_and_padding(self):
        for n,expected in ((4,[[3,0],[1,2]]),(5,[[4,0],[1,-1],[-1,2],[3,-1]]),(8,[[7,0],[1,6],[5,2],[3,4]])):
            photos=self.photos[:n]
            self.assertEqual(page_count(photos,self.layout),len(expected))
            self.assertEqual([[i for i,p in page_items(photos,self.layout,page)] for page in range(len(expected))],expected)
            snap=PrintSnapshot.capture(photos,self.layout,Correction(),1)
            self.assertEqual(snap.pages(True),(0,1))
            self.assertFalse(snap.layout.autorotate)

    def test_postcard_assignments_empty_inside_and_shared_output(self):
        layout=replace(self.layout,mode='postcard',panels=tuple(p.uid for p in self.photos[:4]))
        self.assertEqual([[i for i,p in page_items(self.photos,layout,page)] for page in (0,1)],[[1,0],[2,3]])
        layout=replace(layout,panels=(self.photos[0].uid,self.photos[1].uid,None,None))
        self.assertEqual([i for i,p in page_items(self.photos,layout,1)],[-1,-1])
        self.assertEqual(render_page(self.photos,layout,1,Correction(),2).getextrema(),((255,255),)*3)
        self.assertEqual(render_page(self.photos,layout,1,Correction(curve=((0,50),(255,200))),2).getextrema(),((255,255),)*3)
        dest=self.folder/'empty-inside.pdf'
        export_pdf(dest,self.photos,layout,Correction())
        self.assertEqual(len(PdfReader(dest).pages),2)

    def test_order_copies_reflow_and_snapshot(self):
        photos=self.photos[:3]; photos[0].copies=3
        photos[0].offset_x=.7; photos[0].correction=Correction(teal_orange='a_to_b')
        tokens=ordered_tokens(photos); tokens[1],tokens[4]=tokens[4],tokens[1]
        for count in (1,2,4):
            layout=Layout(per_sheet=count,order=tuple(tokens))
            actual=[p.uid for page in range(page_count(photos,layout)) for i,p in page_items(photos,layout,page)]
            self.assertEqual(actual,[t[0] for t in tokens])
        self.assertEqual(photos[0].offset_x,.7)
        self.assertEqual(photos[0].correction.teal_orange,'a_to_b')
        snap=PrintSnapshot.capture(photos,layout,Correction(),0)
        photos[0].offset_x=0
        self.assertEqual(snap.photos[0].offset_x,.7)

    def test_center_fold_marks_and_pdf_preview_parity(self):
        for axis,segment in (('vertical',(50,3,50,67)),('horizontal',(3,35,97,35))):
            l=replace(self.layout,center_line=axis,fold_marks='ticks',fold_side='back')
            self.assertIn(segment,l.output_segments(0))
            if axis=='horizontal': self.assertIn((50,3,50,7),l.output_segments(1))
        for n in (4,5,8):
            l=replace(self.layout,center_line='horizontal',fold_marks='ticks')
            dest=self.folder/f'{n}.pdf'; photos=self.photos[:n]
            export_pdf(dest,photos,l,Correction())
            doc=pdfium.PdfDocument(dest)
            for page in range(page_count(photos,l)):
                screen=PreviewRenderer().prepare(photos,l,page,Correction(),2).image
                raster=render_page(photos,l,page,Correction(),2)
                pdf=doc[page].render(scale=2*25.4/72).to_pil().convert('RGB')
                for x,y in ((25,20),(75,20)):
                    a=screen.getpixel((x*2,y*2))
                    self.assertEqual(a,raster.getpixel((x*2,y*2)))
                    self.assertLessEqual(max(abs(c-d) for c,d in zip(a,pdf.getpixel((x*2,y*2)))),1)
            doc.close()

    def test_direct_print_one_job_keeps_duplex_sequence(self):
        import time
        from tests.test_beta import FakePrinter
        from illusive_print.print_job import PrintJob
        backend=FakePrinter()
        layout=replace(self.layout,fold_marks='ticks',fold_side='back')
        snap=PrintSnapshot.capture(self.photos,layout,Correction(),1)
        job=PrintJob()
        job.start(snap,False,300,backend,'fake',{},None)
        deadline=time.monotonic()+20
        while job.state not in ('sent','failed','cancelled') and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(job.state,'sent')
        self.assertEqual(len(backend.calls),1)
        images=backend.calls[0][2]
        self.assertEqual(len(images),4)
        for page,image in enumerate(images):
            expected=render_page(self.photos,layout,page,Correction(),300/25.4)
            self.assertEqual(image.tobytes(),expected.tobytes())


class LabTests(unittest.TestCase):
    def test_copy_direction_L_and_neutrality(self):
        rgb=np.array([[[.2,.4,.7],[.8,.3,.1],[.5,.6,.2]]])
        lab=_rgb_lab(rgb)
        for mode in ('a_to_b','b_to_a'):
            result=copy_lab_channels(lab,mode)
            np.testing.assert_array_equal(result[...,0],lab[...,0])
            source,target=(1,2) if mode=='a_to_b' else (2,1)
            np.testing.assert_array_equal(result[...,target],lab[...,source])
            np.testing.assert_array_equal(result[...,source],lab[...,source])
            gray=Image.fromarray(np.repeat(np.arange(256,dtype=np.uint8)[None,:,None],3,axis=2))
            self.assertEqual(teal_orange(gray,mode).tobytes(),gray.tobytes())
            result=_rgb_lab(np.asarray(teal_orange(Image.fromarray((rgb*255).astype('uint8')),mode))/255)
            self.assertLess(np.max(np.abs(result[...,0]-_rgb_lab((rgb*255).astype('uint8')/255)[...,0])),.4)

    def test_stage_zero_and_switch_are_non_accumulating(self):
        image=Image.new('RGB',(2,2),(68,135,189))
        self.assertIs(teal_orange(image),image)
        a=correct_image(image,Correction(teal_orange='a_to_b'))
        b=correct_image(image,Correction(teal_orange='b_to_a'))
        self.assertNotEqual(a.tobytes(),b.tobytes())
        self.assertEqual(correct_image(image,Correction()).tobytes(),image.tobytes())


class FoldingUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.root=create_root(); self.app=IllusivePrintApp(self.root)
        self.paths=[]
        for i in range(5):
            p=self.folder/f'{i}.png'; Image.new('RGB',(60,80),(i*40,60,150)).save(p); self.paths.append(p)
        self.app.add_paths(self.paths); self.root.update(); self.app.refresh()
    def tearDown(self): self.root.destroy(); self.temp.cleanup()
    def test_controls_duplex_and_color_scope(self):
        a=self.app
        a.mode_var.set('Открытка со сгибом')
        for n in range(4): a.selected=n; a.assign_panel(n)
        self.assertEqual([i for i,p in page_items(a.photos,a.layout,0)],[1,0])
        a.turn_page(1); self.assertEqual(a.page_var.get(),'Лист 1 из 1 · Внутри')
        a.mode_var.set('Буклет'); a.refresh()
        self.assertIn('3',a.capacity_var.get())
        a.selected=0; a.selected_rows={0}; a.set_individual_color(True)
        a.toggle_teal_orange('a_to_b'); self.assertEqual(a.photos[0].correction.teal_orange,'a_to_b')
        a.toggle_teal_orange('b_to_a'); self.assertEqual(a.photos[0].correction.teal_orange,'b_to_a')
        a.toggle_teal_orange('b_to_a'); self.assertEqual(a.photos[0].correction.teal_orange,'none')
        a.toggle_teal_orange('a_to_b'); a.reset_color(); self.assertEqual(a.photos[0].correction.teal_orange,'none')
    def test_real_handlers_swap_and_library_group(self):
        a=self.app; a.count_var.set('4'); a.copy_vars[0].set('2'); a.refresh(); self.root.update()
        a.photos[0].offset_x=.3; a.photos[0].correction=Correction(teal_orange='a_to_b')
        a.selected=0; a.selected_rows={0}; a.draw_preview()
        import time
        deadline=time.monotonic()+10
        while a._preview_pending and time.monotonic()<deadline:
            self.root.update(); time.sleep(.002)
        h=a._print_handle
        a.begin_drag(SimpleNamespace(x=h[0]+8,y=h[1]+8))
        cell=a.layout.cells()[2]
        a.end_drag(SimpleNamespace(x=a.preview_origin[0]+(cell.x+cell.width/2)*a.preview_scale,y=a.preview_origin[1]+(cell.y+cell.height/2)*a.preview_scale))
        self.assertEqual([i for i,p in page_items(a.photos,a.layout,0)],[1,0,0,2])
        self.assertEqual(a.photos[0].offset_x,.3)
        a.begin_library_move(0,SimpleNamespace(y_root=0))
        a._library_target=3; a.end_library_move(None)
        self.assertEqual(a.photos[2].path,self.paths[0])
        self.assertEqual(a.photos[2].copies,2)
        self.assertEqual(a.photos[2].correction.teal_orange,'a_to_b')
        with patch('illusive_print.app.messagebox.askyesno',return_value=True): a.reset_settings()
        self.assertEqual(a.center_line_var.get(),'Нет')
