from dataclasses import replace
import gc
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image,ImageChops,ImageStat

from illusive_print.app import IllusivePrintApp,create_root
from illusive_print.core import Photo,Layout,Correction,render_page,Rect,render_photo
from illusive_print.preview import PreviewRenderer,load_preview_source
from illusive_print.image_cache import ImageCache,FULL_IMAGES,PREVIEW_IMAGES
from tests.support import make_photos


class PreviewPerformanceTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.paths=make_photos(self.folder)
        FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
    def tearDown(self):
        FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
        self.temp.cleanup()

    def test_byte_budget_eviction_oversized_and_live_reference(self):
        one=Image.new('RGB',(10,10),'red')
        cache=ImageCache(ImageCache.cost(one)*2)
        cache.put('a',one);cache.put('b',Image.new('RGB',(10,10),'blue'))
        self.assertIs(cache.get('a'),one)
        cache.put('c',Image.new('RGB',(10,10),'green'))
        self.assertIsNone(cache.get('b'))
        self.assertEqual(one.getpixel((0,0)),(255,0,0))
        cache.put('huge',Image.new('RGB',(100,100)))
        self.assertIsNone(cache.get('huge'))
        self.assertLessEqual(cache.bytes,cache.budget)

    def test_dirty_tiles_copies_individual_global_and_before(self):
        photos=[Photo(p) for p in self.paths[:3]]
        photos[0].copies=2
        photos[1].correction=Correction(gamma=1.2)
        layout=Layout(paper_width=297,paper_height=420,per_sheet=9)
        r=PreviewRenderer()
        self.assertEqual(len(r.prepare(photos,layout,0,Correction(),2).changed),4)
        with patch('illusive_print.preview.render_tile',side_effect=AssertionError('unchanged tile rendered')):
            self.assertFalse(r.prepare(photos,layout,0,Correction(),2).changed)
        photos[0].offset_x=.5
        with patch('illusive_print.preview.render_tile',wraps=__import__('illusive_print.preview',fromlist=['render_tile']).render_tile) as render:
            self.assertEqual(len(r.prepare(photos,layout,0,Correction(),2).changed),2)
            self.assertEqual(render.call_count,1)  # both copies share exactly the same cached tile
        self.assertEqual(len(r.prepare(photos,layout,0,Correction(temperature=.2),2).changed),3)
        self.assertEqual(len(r.prepare(photos,layout,0,Correction(temperature=.2),2,False).changed),4)
        photos[0].correction=Correction(gamma=1.4)
        self.assertFalse(r.prepare(photos,layout,0,Correction(temperature=.9),2,False).changed)

    def test_screen_resize_then_correction_original_output_unchanged_and_pixel_alignment(self):
        path=self.folder/'large.jpg'
        Image.merge('RGB',tuple(Image.linear_gradient('L').resize((2400,1600)) for _ in range(3))).save(path,quality=95)
        photo=Photo(path,mode='fit',offset_x=.6,zoom=1.2,rotation=1)
        layout=Layout(paper_width=297,paper_height=420,per_sheet=9)
        correction=Correction(.2,1.1,temperature=.2,tint=-.1)
        before=render_photo(photo,Rect(0,0,100,150),correction,(300,450)).tobytes()
        renderer=PreviewRenderer()
        frame=renderer.prepare([photo],layout,0,correction,2)
        reference=render_page([photo],layout,0,correction,2)
        self.assertLess(max(ImageStat.Stat(ImageChops.difference(frame.image,reference)).mean),1.5)
        self.assertLessEqual(max(load_preview_source(photo).size),1024)
        with patch('illusive_print.preview.correct_image',wraps=__import__('illusive_print.preview',fromlist=['correct_image']).correct_image) as correct:
            renderer.prepare([photo],layout,0,Correction(.1,1.2),2)
            self.assertLess(correct.call_args.args[0].width*correct.call_args.args[0].height,2400*1600)
        self.assertEqual(before,render_photo(photo,Rect(0,0,100,150),correction,(300,450)).tobytes())
        self.assertLessEqual(FULL_IMAGES.bytes,FULL_IMAGES.budget)
        self.assertLessEqual(PREVIEW_IMAGES.bytes,PREVIEW_IMAGES.budget)

    def test_nine_screen_sources_survive_full_size_cache_eviction(self):
        photos=[]
        for index in range(9):
            path=self.folder/f'photo-{index}.jpg'
            Image.new('RGB',(1200,800),(index*20,80,120)).save(path)
            photos.append(Photo(path))
        renderer=PreviewRenderer()
        layout=Layout(paper_width=297,paper_height=420,per_sheet=9)
        renderer.prepare(photos,layout,0,Correction(),1.5)
        FULL_IMAGES.clear()
        with patch('illusive_print.preview.load_source',side_effect=AssertionError('screen edit decoded original')):
            self.assertEqual(len(renderer.prepare(photos,layout,0,Correction(temperature=.2),1.5).changed),9)
            photos[0].offset_x=.3
            self.assertEqual(len(renderer.prepare(photos,layout,0,Correction(temperature=.2),1.5).changed),1)

    def test_actual_canvas_selection_reuses_photo_and_crop_uploads_one_cell(self):
        with patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(self.folder/'preferences.json')}):
            root=create_root()
            app=IllusivePrintApp(root)
            try:
                app.count_var.set('9');app.paper_var.set('A3')
                app.add_paths(self.paths)
                root.update()
                image=app.preview_image
                base=app.preview_canvas.find_withtag('preview_base')
                with patch('illusive_print.preview.render_tile',side_effect=AssertionError('selection rendered pixels')):
                    app.select_photo(1)
                self.assertIs(app.preview_image,image)
                self.assertEqual(app.preview_canvas.find_withtag('preview_base'),base)
                app.photos[1].offset_y=.4
                app.draw_preview(fast=True)
                self.assertEqual(len(app._preview_renderer.frame.changed),1)
                self.assertIs(app.preview_image,image)
                box,tile=app._preview_renderer.frame.changed[0]
                self.assertEqual(tuple(root.tk.call(str(image),'get',box[0]+3,box[1]+3)),tile.getpixel((3,3)))
                app.begin_sheet_pan(SimpleNamespace(x=100,y=100))
                with patch('illusive_print.preview.render_tile',side_effect=AssertionError('pan rendered pixels')):
                    app.move_sheet_pan(SimpleNamespace(x=140,y=125))
                app.end_sheet_pan()
            finally:root.destroy()


if __name__=='__main__':unittest.main()
