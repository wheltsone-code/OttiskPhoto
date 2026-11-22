from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm
from pypdf import PdfReader,PdfWriter
from pypdf.generic import RectangleObject,NameObject,ContentStream
from illusive_print.core import Layout,Photo,Correction,EdgeInsets,CutGeometryError,export_pdf,validate_output,page_items,render_page
from illusive_print.production_geometry import cut_geometry,crop_mark_plan,cut_output_segments,cut_warning,placements,segment_intersects_rect,MarkConflict,render_planned_page
from illusive_print.core import Rect


class CombinedCutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.path=self.folder/'white-94x54.pdf';c=Canvas(str(self.path),pagesize=(94*mm,54*mm))
        c.drawString(6*mm,25*mm,'WHITE CARD / TL / 94 x 54');c.save()
        self.photo=Photo(self.path,pdf_page=0,mode='fit')
        self.layout=Layout(mode='repeat',paper_width=210,paper_height=297,margin=7,gap=2,
                           print_width=94,print_height=54,trim_mode='both',repeat_front=self.photo.uid)

    def tearDown(self):self.temp.cleanup()

    def test_default_finished_and_contour_are_independent(self):
        l=self.layout;g=cut_geometry(l,0)[0]
        self.assertEqual((g.source.width,g.source.height),(94,54))
        self.assertEqual((g.trim.width,g.trim.height),(90,50))
        self.assertEqual(g.contour,g.source);self.assertFalse(cut_warning(l))
        self.assertEqual(l.effective_trim_inset,2)
        self.assertEqual(cut_geometry(replace(l,line_inset=1),0)[0].trim,g.trim)
        self.assertTrue(cut_warning(replace(l,line_inset=1.96)))
        self.assertTrue(cut_warning(replace(l,line_inset=3)))
        legacy=replace(l,trim_mode='lines',trim_inset=1,mark_inset=99,line_inset=99)
        legacy.validate();self.assertEqual(cut_geometry(legacy,0)[0].contour.width,92)

    def test_all_insets_preserve_source_transform_and_cropping(self):
        images=[];refs=[]
        for mark,line in ((2,0),(3,1),(1,0),(0,0)):
            l=replace(self.layout,mark_inset=mark,line_inset=line)
            refs.append([(p.trim,p.paint,p.reference,p.source_box) for p in placements([self.photo],l,0)])
            images.append(render_planned_page([self.photo],l,0,Correction(),2,marks=False).tobytes())
        self.assertTrue(all(ref==refs[0] for ref in refs));self.assertTrue(all(im==images[0] for im in images))

    def test_double_gutter_cut_and_two_ways_of_specifying_bleed(self):
        a=self.layout;b=replace(a,print_width=90,print_height=50,bleed=EdgeInsets(2,2,2,2),mark_inset=0)
        ga,gb=cut_geometry(a,0),cut_geometry(b,0)
        self.assertEqual([g.trim for g in ga],[g.trim for g in gb])
        self.assertEqual([g.contour for g in ga],[g.contour for g in gb])
        self.assertFalse(cut_warning(b))
        self.assertAlmostEqual(ga[1].trim.x-ga[0].trim.x-ga[0].trim.width,6)
        for l in (a,b):
            marks,issues=crop_mark_plan(l,0);self.assertFalse(issues)
            xs={round(m.segment[0],6) for m in marks if m.segment[0]==m.segment[2]}
            self.assertIn(round(ga[0].trim.x+ga[0].trim.width,6),xs)
            self.assertIn(round(ga[1].trim.x,6),xs)
        writer=PdfWriter(clone_from=self.path);page=writer.pages[0]
        page[NameObject('/TrimBox')]=RectangleObject((2*mm,2*mm,92*mm,52*mm))
        page[NameObject('/BleedBox')]=RectangleObject(page.mediabox)
        boxed=self.folder/'boxed.pdf';writer.write(boxed)
        photo=Photo(boxed,pdf_page=0,mode='fit')
        for l in (a,b):
            l=replace(l,repeat_front=photo.uid);dest=self.folder/f'boxed-{l.mark_inset}.pdf'
            export_pdf(dest,[photo],l,Correction())
            self.assertIn('WHITE CARD',PdfReader(dest).pages[0].extract_text())

    def test_single_exterior_end_is_sufficient_and_preferred_to_internal_marks(self):
        l=replace(self.layout,paper_width=100,paper_height=120,margin=0,gap=0,align_y='top')
        validate_output([self.photo],l);marks,issues=crop_mark_plan(l,0)
        self.assertFalse(issues)
        vertical=[m for m in marks if m.segment[0]==m.segment[2]]
        self.assertEqual(len(vertical),2)
        self.assertTrue(all(min(m.segment[1],m.segment[3])>108 for m in vertical))

    def test_stroke_tangency_and_finite_segments_detect_real_neighbour_overlap(self):
        r=Rect(9,9,5,5)
        self.assertFalse(segment_intersects_rect((10,0,10,1),r))
        self.assertFalse(segment_intersects_rect((10,0,10,8.95),r))
        self.assertTrue(segment_intersects_rect((10,0,10,8.951),r))
        self.assertTrue(segment_intersects_rect((10,9.5,10,10.5),r))

    def test_collapsed_active_geometry_is_rejected_and_tight_marks_report_a_field(self):
        for changes in ({'mark_inset':27},{'line_inset':27},{'mark_inset':float('inf')},{'line_inset':-1}):
            with self.assertRaises(CutGeometryError):replace(self.layout,**changes).validate()
        # Inactive combined insets do not affect old single-mode settings.
        replace(self.layout,trim_mode='marks',trim_inset=2,mark_inset=99,line_inset=99).validate()
        bad=replace(self.layout,paper_width=94,paper_height=54,margin=0)
        with self.assertRaises(MarkConflict) as conflict:validate_output([self.photo],bad)
        self.assertIn('поле',str(conflict.exception));self.assertNotIn('Увеличьте зазор',str(conflict.exception))

    def test_counts_rotation_partial_duplex_and_adjacent_modes(self):
        for margin,gap,grid in ((7,2,(2,5)),(7,10,(3,2)),(3,10,(2,4))):
            l=replace(self.layout,margin=margin,gap=gap)
            self.assertEqual(l.capacity_grid(),grid)
            self.assertEqual(l.count,replace(l,trim_mode='none').count)
            validate_output([self.photo],l)
        l=replace(self.layout,repeat_duplex=True,repeat_back=self.photo.uid,repeat_quantity=13,keep_positions=True)
        from illusive_print.production_geometry import mirror_rect
        front=cut_geometry(l,2,3);back=cut_geometry(l,3,3)
        self.assertEqual([mirror_rect(g.trim,l) for g in front],[g.trim for g in back])
        self.assertEqual([mirror_rect(g.contour,l) for g in front],[g.contour for g in back])
        for edge in ('short','long'):
            paired=replace(l,flip_edge=edge)
            def normalized(s):return tuple(round(v,5) for point in sorted(((s[0],s[1]),(s[2],s[3]))) for v in point)
            reflected=[]
            for mark in crop_mark_plan(paired,2,3)[0]:
                x,y,u,v=mark.segment
                a=mirror_rect(Rect(x,y,0,0),paired);b=mirror_rect(Rect(u,v,0,0),paired)
                reflected.append((a.x,a.y,b.x,b.y))
            self.assertEqual({normalized(s) for s in reflected},{normalized(m.segment) for m in crop_mark_plan(paired,3,3)[0]})
        self.assertEqual(len(front),len(page_items([self.photo],l,2)))
        validate_output([self.photo],replace(l,mode='exact'))
        booklet=Layout(mode='booklet',paper_width=320,paper_height=450,margin=7,gap=5,booklet_page_size=(148,210),booklet_copies=2,trim_mode='both')
        self.assertEqual(len(cut_geometry(booklet,0)),2);self.assertFalse(crop_mark_plan(booklet,0)[1])

    def test_pdf_has_one_copy_of_each_shared_mark_and_contour(self):
        from PIL import Image
        path=self.folder/'photo.png';Image.new('RGB',(94,54),'white').save(path)
        raster=Photo(path,copies=self.layout.count)
        cases=(([self.photo],self.layout),([raster,self.photo],replace(self.layout,mode='exact')))
        def normalized(s):return tuple(round(v,4) for point in sorted(((s[0],s[1]),(s[2],s[3]))) for v in point)
        for photos,layout in cases:
            dest=self.folder/'combined.pdf';export_pdf(dest,photos,layout,Correction())
            reader=PdfReader(dest);self.assertIn('WHITE CARD',reader.pages[-1].extract_text())
            for i,page in enumerate(reader.pages):
                lines=[];start=None
                for values,op in ContentStream(page.get_contents(),page.pdf).operations:
                    if op==b'm':start=tuple(float(v) for v in values)
                    elif op==b'l' and start is not None:
                        x,y=start;u,v=(float(a) for a in values)
                        lines.append((x/mm,layout.paper_height-y/mm,u/mm,layout.paper_height-v/mm));start=None
                expected=layout.output_segments(i,len(page_items(photos,layout,i)))
                self.assertEqual({normalized(s) for s in lines},{normalized(s) for s in expected})
                self.assertEqual(len(lines),len(expected))

    def test_direct_print_uses_the_combined_geometry_without_a_real_queue(self):
        import time
        from tests.test_beta import FakePrinter
        from illusive_print.print_job import PrintSnapshot,PrintJob
        backend=FakePrinter();job=PrintJob()
        l=replace(self.layout,repeat_quantity=1)
        snapshot=PrintSnapshot.capture([self.photo],l,Correction(),0)
        self.assertTrue(job.start(snapshot,False,300,backend,'Test',{},None))
        until=time.monotonic()+15
        while job.state in ('preparing','sending') and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(job.state,'sent')
        self.assertEqual(backend.calls[0][2][0].tobytes(),render_page(snapshot.photos,l,0,Correction(),300/25.4).tobytes())
