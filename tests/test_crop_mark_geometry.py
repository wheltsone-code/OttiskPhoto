"""Crop-mark regressions use physical sheet coordinates, including stroke."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,RectangleObject
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm

from illusive_print.core import Layout,Photo,EdgeInsets,Correction,export_pdf,page_items,render_page,validate_output
from illusive_print.production_geometry import crop_mark_plan,mark_rects,placements,MarkConflict,side_cells,STROKE_MM
from illusive_print.vector_pdf import vector_matrix,bleed_shortfalls


class CropMarkGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.source=self.folder/'94x54.pdf'
        c=Canvas(str(self.source),pagesize=(94*mm,54*mm))
        c.setFillColorRGB(.8,.9,1);c.rect(0,0,94*mm,54*mm,fill=1,stroke=0)
        c.setFillColorRGB(0,0,0);c.drawString(5*mm,25*mm,'VECTOR 90 x 50')
        c.line(2*mm,2*mm,92*mm,52*mm);c.save()
        w=PdfWriter(clone_from=self.source);p=w.pages[0]
        p[NameObject('/TrimBox')]=RectangleObject((2*mm,2*mm,92*mm,52*mm))
        p[NameObject('/BleedBox')]=RectangleObject((0,0,94*mm,54*mm))
        self.boxed=self.folder/'trim-and-bleed.pdf';w.write(self.boxed)
        self.photo=Photo(self.source,pdf_page=0,mode='fit')
        self.layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=94,print_height=54,
                           margin=7,gap=2,trim_mode='marks',trim_inset=2,repeat_front=self.photo.uid)

    def tearDown(self):self.temp.cleanup()

    def assert_safe(self,layout,page=0,limit=None):
        marks,issues=crop_mark_plan(layout,page,limit);self.assertTrue(marks);self.assertFalse(issues)
        cuts,paints=mark_rects(layout,page,limit);half=STROKE_MM/2
        for m in marks:
            x0,y0,x1,y1=m.segment
            self.assertGreaterEqual(min(x0,x1)-half,-1e-6)
            self.assertGreaterEqual(min(y0,y1)-half,-1e-6)
            self.assertLessEqual(max(x0,x1)+half,layout.paper_width+1e-6)
            self.assertLessEqual(max(y0,y1)+half,layout.paper_height+1e-6)
            for r in paints:
                overlaps=(min(x0,x1)-half<r.x+r.width-1e-6 and max(x0,x1)+half>r.x+1e-6
                          and min(y0,y1)-half<r.y+r.height-1e-6 and max(y0,y1)+half>r.y+1e-6)
                self.assertFalse(overlaps,(m,r))
        # Each distinct cut coordinate has both perimeter marks. Gutter
        # boundaries are not collapsed into one centre cut.
        self.assertEqual({round(m.segment[0],6) for m in marks if m.segment[0]==m.segment[2]},
                         {round(x,6) for r in cuts for x in (r.x,r.x+r.width)})
        self.assertEqual({round(m.segment[1],6) for m in marks if m.segment[1]==m.segment[3]},
                         {round(y,6) for r in cuts for y in (r.y,r.y+r.height)})

    def test_known_inset_bug_both_gaps_preserves_physical_grid(self):
        for gap,grid in ((2,(2,5)),(10,(3,2))):
            l=replace(self.layout,gap=gap);self.assertEqual(l.capacity_grid(),grid)
            self.assertEqual(l.bleed,EdgeInsets());self.assert_safe(l)
            validate_output([self.photo],l)
            for r in mark_rects(l,0)[0]:self.assertEqual(sorted((r.width,r.height)),[50,90])
            dest=self.folder/f'gap-{gap}.pdf';export_pdf(dest,[self.photo],l,Correction())
            self.assertIn('VECTOR 90 x 50',PdfReader(dest).pages[0].extract_text())
        # 2 x 4 at gap 10 requires width <= 93, not 94, with A4 / 7mm margins.
        self.assertEqual(replace(self.layout,gap=10,print_width=93).capacity_grid(),(2,4))

    def test_screenshot_margin_three_has_the_requested_grids(self):
        # Screenshots show 3mm, and slightly rounded PDF dimensions. Keep
        # those physical inputs instead of silently substituting a new gap.
        for gap,grid in ((2,(2,5)),(10,(2,4))):
            l=replace(self.layout,margin=3,gap=gap,print_width=94.000108333333,print_height=54.000004722222)
            self.assertEqual(l.capacity_grid(),grid);self.assert_safe(l)
            validate_output([self.photo],l)

    def test_both_size_methods_have_identical_cut_and_artwork_at_100_percent(self):
        for source in (self.source,self.boxed):
            for mode in ('fit','fill'):
                p=Photo(source,pdf_page=0,mode=mode)
                a=replace(self.layout,repeat_front=p.uid)
                b=replace(a,print_width=90,print_height=50,bleed=EdgeInsets(2,2,2,2),trim_inset=0)
                self.assertEqual(mark_rects(a,0),mark_rects(b,0))
                matrices=[]
                for l in (a,b):
                    item=placements([p],l,0)[0]
                    matrix=vector_matrix(item.photo,item.reference,item.autorotate,l.paper_height,item.source_box)
                    self.assertAlmostEqual(matrix[0]*matrix[3]-matrix[1]*matrix[2],1,places=6)
                    matrices.append(matrix)
                    self.assertLess(max(bleed_shortfalls(p,item.reference,item.paint,item.autorotate,l.paper_height,item.source_box)),.001)
                    dest=self.folder/f'{source.stem}-{mode}-{l.trim_inset}.pdf'
                    export_pdf(dest,[p],l,Correction())
                    page=PdfReader(dest).pages[0];self.assertIn('VECTOR 90 x 50',page.extract_text())
                    forms=[o.get_object() for o in page['/Resources']['/XObject'].values()]
                    self.assertEqual(len(forms),1);self.assertEqual(forms[0]['/Subtype'],'/Form')
                    self.assertIn(b' l',forms[0].get_data())
                for x,y in zip(*matrices):self.assertAlmostEqual(x,y,places=6)

    def test_pdf_orientation_with_asymmetric_bleed_matches_export(self):
        import pypdfium2 as pdfium
        from PIL import ImageChops,ImageStat
        l=replace(self.layout,paper_width=100,paper_height=100,print_width=30,print_height=20,
                  bleed=EdgeInsets(0,20,0,20),trim_inset=0,repeat_quantity=1)
        dest=self.folder/'asymmetric.pdf';export_pdf(dest,[self.photo],l,Correction())
        preview=render_page([self.photo],l,0,Correction(),4)
        with pdfium.PdfDocument(dest) as doc:
            page=doc[0];bitmap=page.render(scale=4/mm)
            output=bitmap.to_pil().convert('RGB').copy();bitmap.close();page.close()
        error=max(ImageStat.Stat(ImageChops.difference(preview,output.crop((0,0,preview.width,preview.height)))).mean)
        self.assertLess(error,3)

    def test_inset_does_not_change_pdf_artwork_or_clip(self):
        from illusive_print.production_geometry import render_planned_page
        from pypdf.generic import ContentStream
        writer=PdfWriter(clone_from=self.source)
        writer.pages[0][NameObject('/TrimBox')]=RectangleObject(writer.pages[0].mediabox)
        full=self.folder/'trim-equals-page.pdf';writer.write(full)
        for path in (self.source,full,self.boxed):
            for mode in ('repeat','exact'):
                for cut_mode in ('none','lines','marks'):
                    for fitting in ('fit','fill'):
                        p=Photo(path,pdf_page=0,mode=fitting)
                        base=replace(self.layout,mode=mode,trim_mode=cut_mode,repeat_front=p.uid)
                        pixels=[];matrices=[];clips=[]
                        for inset in (0,2):
                            l=replace(base,trim_inset=inset)
                            item=placements([p],l,0)[0];clips.append(item.paint)
                            pixels.append(render_planned_page([p],l,0,Correction(),2,marks=False).tobytes())
                            dest=self.folder/'inset.pdf';export_pdf(dest,[p],l,Correction())
                            page=PdfReader(dest).pages[0]
                            ops=ContentStream(page.get_contents(),page.pdf).operations
                            matrices.append([tuple(float(v) for v in values) for values,op in ops if op==b'cm'])
                        with self.subTest(path=path.name,mode=mode,cut_mode=cut_mode,fitting=fitting):
                            self.assertEqual(clips[0],clips[1])
                            self.assertEqual(pixels[0],pixels[1])
                            self.assertEqual(matrices[0],matrices[1])

    def test_rotated_nonuniform_bleeds_partial_sheet_and_reverse_marks(self):
        p=self.photo
        l=replace(self.layout,print_width=54,print_height=94,bleed=EdgeInsets(1,2,3,4),repeat_quantity=13,
                  repeat_duplex=True,repeat_back=p.uid,align_x='left',align_y='top',placement='stack')
        self.assertNotEqual(l.exact_grid()[2:],(l.print_width,l.print_height))
        for page in (0,1,2,3):
            limit=len(page_items([p],l,page));self.assert_safe(l,page,limit)
            self.assertEqual(len(mark_rects(l,page,limit)[0]),limit)
        validate_output([p],l)
        # Symmetric bleeds allow direct reflection of every physical mark;
        # asymmetric bleeds were separately checked for safe placement above.
        l=replace(l,bleed=EdgeInsets(2,2,2,2),repeat_quantity=l.count+3)
        def normal(lines):return {tuple(round(v,5) for point in sorted(((s[0],s[1]),(s[2],s[3]))) for v in point) for s in lines}
        front=[m.segment for m in crop_mark_plan(l,2,3)[0]]
        back=[m.segment for m in crop_mark_plan(l,3,3)[0]]
        self.assertEqual(normal([(l.paper_width-x0,y0,l.paper_width-x1,y1) for x0,y0,x1,y1 in front]),normal(back))
        self.assertLess(len(crop_mark_plan(l,2,1)[0]),len(crop_mark_plan(l,2,l.count)[0]))

    def test_shortened_marks_and_impossible_edge_report_without_layout_mutation(self):
        l=replace(self.layout,paper_width=98,paper_height=58,margin=2,repeat_quantity=1)
        self.assert_safe(l,limit=1)
        self.assertTrue(all(abs(m.segment[2]-m.segment[0])+abs(m.segment[3]-m.segment[1])<2 for m in crop_mark_plan(l,0,1)[0]))
        bad=replace(l,paper_width=94,paper_height=54,margin=0)
        with self.assertRaises(MarkConflict) as caught:validate_output([self.photo],bad)
        self.assertIn('0.65',str(caught.exception));self.assertTrue(caught.exception.issues)
        self.assertEqual(bad.print_width,94);self.assertEqual(bad.trim_inset,2)
        # The render adapter itself still paints an inspectable preview.
        self.assertEqual(render_page([self.photo],bad,0,Correction(),2).size,(188,108))

    def test_internal_waste_is_used_if_perimeter_is_unavailable(self):
        l=replace(self.layout,paper_width=102,paper_height=118,margin=0,gap=10,repeat_quantity=2)
        self.assert_safe(l,limit=2)
        marks=crop_mark_plan(l,0,2)[0]
        self.assertTrue(any(54<m.segment[1]<64 for m in marks if m.segment[0]==m.segment[2]))

    def test_stroke_boundary_tolerance_does_not_use_an_infinite_axis(self):
        l=replace(self.layout,paper_width=95.3,paper_height=55.3,margin=.65,repeat_quantity=1)
        self.assert_safe(l,limit=1)
        # At the exact minimum, the full 0.1mm stroke fits on the sheet.
        # A genuinely smaller sheet cannot accommodate even a 0.5mm mark.
        bad=replace(l,paper_width=95.298,paper_height=55.298,margin=.649)
        self.assertTrue(crop_mark_plan(bad,0,1)[1])

    def test_shared_exact_and_booklet_geometry(self):
        l=replace(self.layout,mode='exact',repeat_front=None)
        validate_output([self.photo],l);self.assert_safe(l,limit=1)
        booklet=Layout(mode='booklet',paper_width=320,paper_height=450,margin=7,gap=5,
                       booklet_page_size=(148,210),booklet_copies=2,bleed=EdgeInsets(2,2,2,2),trim_mode='marks')
        self.assert_safe(booklet,0);self.assert_safe(booklet,1)

