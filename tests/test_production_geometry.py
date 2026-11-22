import unittest
from dataclasses import replace
from pathlib import Path
from illusive_print.core import Layout,Photo,EdgeInsets,page_count,page_items,page_labels
from illusive_print.production_geometry import side_cells,spread_grid,spread_rects,mirror_rect,placements


class ProductionGeometryTests(unittest.TestCase):
    def test_exact_quantity_and_large_last_sheet(self):
        photo=Photo(Path('front.png'))
        layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=60,print_height=40,margin=0,repeat_front=photo.uid,repeat_quantity=100)
        self.assertEqual(layout.count,21)
        self.assertEqual(page_count([photo],layout),5)
        self.assertEqual(len(page_items([photo],layout,4)),16)
        huge=replace(layout,repeat_quantity=10**9)
        last=page_count([photo],huge)-1
        self.assertLessEqual(len(page_items([photo],huge,last)),21)

    def test_asymmetric_partial_reverse_positions(self):
        f,b=Photo(Path('f.png')),Photo(Path('b.png'))
        for edge in ('short','long'):
            layout=Layout(mode='repeat',paper_width=320,paper_height=450,print_width=90,print_height=60,margin=10,align_x='left',align_y='top',repeat_front=f.uid,repeat_back=b.uid,repeat_duplex=True,repeat_quantity=layout_capacity_remainder(),flip_edge=edge)
            front=side_cells(layout,2,2);back=side_cells(layout,3,2)
            self.assertEqual(back,tuple(mirror_rect(r,layout) for r in front))
            self.assertEqual(tuple(mirror_rect(r,layout) for r in back),front)
            self.assertEqual(page_count([f,b],layout)%2,0)

    def test_two_a5_spreads_on_sra3(self):
        layout=Layout(mode='booklet',paper_width=320,paper_height=450,margin=5,gap=5,booklet_page_size=(148,210),booklet_copies=2,bleed=EdgeInsets(2,2,2,2))
        layout.validate()
        self.assertEqual(spread_grid(layout)[:2],(1,2))
        self.assertEqual(len(side_cells(layout)),4)
        self.assertEqual(layout.binding_edge,'long')
        photos=[Photo(Path(str(i)+'.png')) for i in range(8)]
        layout=replace(layout,booklet_covers=(photos[0].uid,photos[-1].uid),booklet_sequence=tuple((p.uid,0) for p in photos[1:-1]))
        self.assertEqual(page_count(photos,layout),4)
        self.assertEqual(page_labels(photos,layout,0),('END','0','END','0'))
        self.assertEqual(page_labels(photos,layout,1),('1','6','1','6'))
        self.assertEqual(spread_rects(layout,1),tuple(mirror_rect(r,layout) for r in spread_rects(layout,0)))

    def test_a4_spread_fits_rotated_once(self):
        layout=Layout(mode='booklet',paper_width=320,paper_height=450,margin=5,booklet_page_size=(210,297))
        layout.validate()
        self.assertEqual(spread_grid(layout),(1,1,297,420,True))
        self.assertEqual(layout.binding_edge,'short')
        with self.assertRaises(ValueError):replace(layout,booklet_copies=2).validate()

    def test_zero_bleed_preserves_exact_grid(self):
        layout=Layout(mode='exact',print_width=50,print_height=70,margin=5,gap=2)
        cells=layout.cells()
        self.assertEqual(cells,side_cells(layout,0))
        bleeds=replace(layout,bleed=EdgeInsets(3,3,3,3))
        self.assertLessEqual(bleeds.count,layout.count)
        rect=bleeds.cells()[0]
        self.assertGreaterEqual(rect.x-3,5-1e-8)

    def test_driver_duplex_capability_and_printable_area_are_explicit(self):
        from illusive_print.windows_print import DriverPaper
        from illusive_print.production_geometry import clipping_warning
        layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=60,print_height=40,margin=0,repeat_duplex=True)
        paper=DriverPaper(210,297,duplex_supported=False,margins=EdgeInsets(8,8,8,8))
        self.assertIn('автоматическую',paper.mismatch(layout))
        photo=Photo(Path('front.png'));layout=replace(layout,repeat_front=photo.uid)
        self.assertEqual(clipping_warning([photo],layout,paper),'')
        self.assertIn('непечатаемую',clipping_warning([photo],replace(layout,align_x='left',align_y='top'),paper))


def layout_capacity_remainder():return 23
