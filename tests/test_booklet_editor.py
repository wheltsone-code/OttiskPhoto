import unittest
from pathlib import Path

from illusive_print.booklet_editor import blank_page_plan
from illusive_print.core import Photo
from illusive_print.duplex_ui import FoldingMixin


class BlankPagePlanTests(unittest.TestCase):
    def test_increasing_copies_places_new_instance_after_the_photo(self):
        editor=FoldingMixin()
        editor.photos=[Photo(Path(name+'.png')) for name in ('front','one','two','back')]
        editor.booklet_leaves=[];editor.booklet_cover_ids=[None,None]
        editor.booklet_interior_ids=[];editor._booklet_initialized=False
        editor._booklet_seen=set();editor.print_sequence=()
        editor.ensure_booklet_covers()
        editor.photos[1].copies=2;editor.ensure_booklet_covers()
        self.assertEqual([p['token'] for p in editor.booklet_leaves[:3]],
                         [(editor.photos[1].uid,0),(editor.photos[1].uid,1),(editor.photos[2].uid,0)])

    def leaves(self):
        return [{'token':(str(i),0),'auto':False} for i in range(7)]+[{'token':None,'auto':True} for _ in range(3)]

    def test_explicit_final_numbers_preserve_photos_and_pad_only_suffix(self):
        original=self.leaves()
        leaves,covers=blank_page_plan(original,['front','back'],'1, 4')
        self.assertEqual(covers,['front','back'])
        self.assertEqual(len(leaves)+2,12)
        self.assertEqual([i+1 for i,p in enumerate(leaves) if p['token'] is None],[1,4,10])
        self.assertEqual([p['token'] for p in leaves if p['token']],[(str(i),0) for i in range(7)])
        self.assertEqual([i+1 for i,p in enumerate(leaves) if p['auto']],[10])
        self.assertEqual(original,self.leaves())

    def test_both_covers_can_be_blank_without_losing_their_photos(self):
        leaves,covers=blank_page_plan(self.leaves(),['front','back'],'0, 1, END')
        self.assertEqual(covers,[None,None])
        self.assertIsNone(leaves[0]['token'])
        self.assertEqual([p['token'] for p in leaves if p['token']],[('front',0)]+[(str(i),0) for i in range(7)]+[('back',0)])
        self.assertEqual((len(leaves)+2)%4,0)

    def test_ranges_and_duplicate_numbers_are_not_duplicate_pages(self):
        leaves,covers=blank_page_plan(self.leaves(),['front','back'],'1 – 3, 2, 6..7')
        self.assertEqual([i+1 for i,p in enumerate(leaves) if not p['auto'] and p['token'] is None],[1,2,3,6,7])

    def test_invalid_input_does_not_mutate_document(self):
        leaves=self.leaves();covers=['front','back']
        for text in ('abc','4-2','10001','-1','1..a'):
            with self.subTest(text=text),self.assertRaises(ValueError):blank_page_plan(leaves,covers,text)
        self.assertEqual(leaves,self.leaves());self.assertEqual(covers,['front','back'])

    def test_empty_covers_are_never_automatically_filled(self):
        leaves,covers=blank_page_plan(self.leaves(),[None,None],'0, END')
        self.assertEqual(covers,[None,None])
        with self.assertRaises(ValueError):blank_page_plan(leaves,covers,'1')
