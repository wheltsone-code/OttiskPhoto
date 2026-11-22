from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from illusive_print.color import (_rgb_lab,_lab_linear,copy_lab_channels,teal_orange)
from illusive_print.preview_tasks import LatestPreview,check_preview_cancelled
from illusive_print.core import Correction,Photo
from illusive_print.preview import PreviewRenderer
from illusive_print.app import create_root,IllusivePrintApp


def original_to(image,mode):
    """Independent pre-patch gamut-search oracle, retained for regression checks."""
    output=Image.new('RGB',image.size)
    for top in range(0,image.height,128):
        source=np.asarray(image.crop((0,top,image.width,min(top+128,image.height))))
        lab=copy_lab_channels(_rgb_lab(source.astype(np.float64)/255),mode)
        raw=_lab_linear(lab)
        outside=np.any((raw < -1e-7)|(raw > 1+1e-7),axis=-1)
        if outside.any():
            lo=np.zeros(outside.shape); hi=np.ones(outside.shape)
            for _ in range(16):
                mid=(lo+hi)/2
                candidate=lab.copy(); candidate[...,1:]*=mid[...,None]
                linear=_lab_linear(candidate)
                valid=np.all((linear>=-1e-7)&(linear<=1+1e-7),axis=-1)
                lo=np.where(valid,mid,lo); hi=np.where(valid,hi,mid)
            lab[...,1:]*=np.where(outside,lo,1)[...,None]
            raw=_lab_linear(lab)
        raw=np.clip(raw,0,1)
        encoded=np.where(raw<=.0031308,12.92*raw,1.055*raw**(1/2.4)-.055)
        pixels=np.rint(encoded*255).astype(np.uint8)
        neutral=(source[...,0]==source[...,1])&(source[...,1]==source[...,2])
        pixels[neutral]=source[neutral]
        output.paste(Image.fromarray(pixels),(0,top))
    return output


class OptimizationTests(unittest.TestCase):
    def test_exact_random_ramps_neutrals_and_strip_boundary(self):
        rng=np.random.default_rng(29571)
        random=rng.integers(0,256,size=(259,257,3),dtype=np.uint8)
        random[:256,0,:]=np.arange(256,dtype=np.uint8)[:,None]
        image=Image.fromarray(random)
        for mode in ('a_to_b','b_to_a'):
            self.assertEqual(teal_orange(image,mode).tobytes(),original_to(image,mode).tobytes())

    def test_cancel_active_and_replace_queued_requests(self):
        worker=LatestPreview(); started=threading.Event(); release=threading.Event()
        def slow():
            started.set(); release.wait(2); check_preview_cancelled()
            return 'old'
        try:
            worker.submit(1,slow); self.assertTrue(started.wait(1))
            worker.submit(2,lambda:'middle'); worker.submit(3,lambda:'last'); release.set()
            generation,value,error=worker.results.get(timeout=3)
            self.assertEqual((generation,value,error),(3,'last',None))
            self.assertTrue(worker.results.empty())
        finally: release.set(); worker.close(); worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())


class AsyncUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.env=patch.dict('os.environ',OTTISK_PHOTO_PREFERENCES=str(self.folder/'preferences.json')); self.env.start()
        self.root=create_root(); self.app=IllusivePrintApp(self.root)
        image=Image.fromarray(np.random.default_rng(90).integers(0,256,(160,200,3),dtype=np.uint8))
        path=self.folder/'photo.jpg'; image.save(path)
        self.app.add_paths([path]); self.root.update()

    def tearDown(self):
        self.root.destroy(); self.env.stop(); self.temp.cleanup()

    def settle(self):
        until=time.monotonic()+5
        while self.app._preview_pending and time.monotonic()<until:
            self.root.update(); time.sleep(.002)
        self.assertFalse(self.app._preview_pending)

    def test_mainloop_live_switch_off_and_final_pixels(self):
        a=self.app
        started=threading.Event(); release=threading.Event(); main=threading.get_ident(); threads=[]
        from illusive_print import preview
        original=preview.correct_image
        def blocked(image,c):
            threads.append(threading.get_ident()); started.set()
            release.wait(3); check_preview_cancelled()
            return original(image,c)
        with patch('illusive_print.preview.correct_image',side_effect=blocked):
            a.toggle_teal_orange('a_to_b'); self.assertTrue(started.wait(1))
            tick=[]; self.root.after(0,lambda:tick.append(True)); self.root.update()
            self.assertEqual(tick,[True])
            a.toggle_teal_orange('b_to_a'); a.toggle_teal_orange('b_to_a')
            self.assertFalse(a._preview_pending)
            self.assertEqual(a.correction.teal_orange,'none')
            off=a._preview_renderer.frame.image.tobytes()
            release.set()
        a.toggle_teal_orange('a_to_b'); self.settle()
        reference=PreviewRenderer().prepare(tuple(replace(p) for p in a.photos),a.layout,a.page,a.correction,a.preview_scale).image
        self.assertEqual(a._preview_renderer.frame.image.tobytes(),reference.tobytes())
        self.assertTrue(all(t!=main for t in threads))
        self.assertNotEqual(off,reference.tobytes())

    def test_pending_layout_change_uses_latest_snapshot_and_close_cancels(self):
        a=self.app
        a.toggle_teal_orange('a_to_b'); a.count_var.set('4'); a.paper_var.set('A3'); a.refresh()
        a.toggle_teal_orange('b_to_a'); self.settle()
        expected=PreviewRenderer().prepare(a.photos,a.layout,a.page,a.correction,a.preview_scale).image
        self.assertEqual(a._preview_renderer.frame.image.tobytes(),expected.tobytes())
        a.toggle_teal_orange('a_to_b')
        worker=a._preview_worker
        self.root.destroy(); worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())
        # tearDown may safely destroy an already destroyed root only once.
        self.root=create_root(); self.root.withdraw()
