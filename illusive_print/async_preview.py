"""Tk-side coordination of immutable preview requests and latest-only results."""
from dataclasses import replace
import queue

from .core import effective_correction, page_items
from .preview import PreviewRenderer
from .preview_tasks import LatestPreview


class AsyncPreviewMixin:
    def init_async_preview(self):
        self._preview_worker = None
        self._preview_generation = 0
        self._preview_request_key = None
        self._preview_ready_key = None
        self._preview_failed_key = None
        self._preview_pending = False
        self._preview_poll_job = None

    def cancel_async_preview(self):
        self._preview_generation += 1
        self._preview_pending = False
        self._preview_request_key = None
        self._preview_ready_key = None
        if self._preview_worker is not None:
            self._preview_worker.invalidate()
        if self._preview_poll_job is not None:
            self.root.after_cancel(self._preview_poll_job)
            self._preview_poll_job = None

    def close_async_preview(self):
        self.cancel_async_preview()
        if self._preview_worker is not None:
            self._preview_worker.close()

    def preview_frame(self, scale):
        apply = not self.preview_before
        heavy = apply and any(effective_correction(p,self.correction).teal_orange != 'none'
                              for _,p in page_items(self.photos,self.layout,self.page))
        if not heavy:
            if self._preview_pending:
                self.cancel_async_preview()
            self._preview_ready_key = None
            self._preview_failed_key = None
            return self._preview_renderer.prepare(self.photos,self.layout,self.page,self.correction,scale,apply)
        photos = tuple(replace(p) for p in self.photos)
        layout,page,correction = self.layout,self.page,self.correction
        key = (tuple(tuple(vars(p).items()) for p in photos),layout,page,correction,scale,apply)
        if key == self._preview_ready_key:
            return self._preview_renderer.frame
        if key == self._preview_failed_key or (self._preview_pending and key == self._preview_request_key):
            return None
        self._preview_generation += 1
        self._preview_request_key = key
        self._preview_pending = True
        self._preview_failed_key = None
        if self._preview_worker is None:
            self._preview_worker = LatestPreview()
        def render():
            renderer = PreviewRenderer()
            renderer.prepare(photos,layout,page,correction,scale,apply)
            return renderer
        self._preview_worker.submit(self._preview_generation,render)
        if self._preview_poll_job is None:
            self._preview_poll_job = self.root.after(16,self.poll_preview)
        return None

    def poll_preview(self):
        self._preview_poll_job = None
        if self._closing:
            return
        try:
            while True:
                generation,renderer,error = self._preview_worker.results.get_nowait()
                if generation != self._preview_generation:
                    continue
                self._preview_pending = False
                if error is not None:
                    self._preview_failed_key = self._preview_request_key
                    self.preview_canvas.delete('preview_busy')
                    self.status_var.set('Не удалось подготовить предпросмотр: '+str(error))
                    self.preview_canvas.configure(cursor='hand2')
                else:
                    self._preview_renderer = renderer
                    self._preview_ready_key = self._preview_request_key
                    self.draw_preview()
        except queue.Empty:
            pass
        if self._preview_pending:
            self._preview_poll_job = self.root.after(16,self.poll_preview)
