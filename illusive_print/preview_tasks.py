"""Latest-request-only preview worker. No Tk objects or callbacks on this thread."""
from contextlib import contextmanager
from contextvars import ContextVar
import queue
import threading


_cancel = ContextVar('preview_cancel', default=None)


class PreviewCancelled(Exception):
    pass


def check_preview_cancelled():
    event = _cancel.get()
    if event is not None and event.is_set():
        raise PreviewCancelled()


@contextmanager
def preview_cancellation(event):
    token = _cancel.set(event)
    try:
        check_preview_cancelled()
        yield
    finally:
        _cancel.reset(token)


class LatestPreview:
    def __init__(self):
        self.results = queue.Queue()
        self.condition = threading.Condition()
        self.pending = None
        self.cancel = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='OttiskPreview', daemon=True)
        self.thread.start()

    def submit(self, generation, render):
        with self.condition:
            if self.closed:
                return
            if self.cancel is not None:
                self.cancel.set()
            self.cancel = threading.Event()
            self.pending = (generation, render, self.cancel)
            self.condition.notify()

    def invalidate(self):
        with self.condition:
            if self.cancel is not None:
                self.cancel.set()
            self.pending = None

    def close(self):
        with self.condition:
            self.closed = True
            if self.cancel is not None:
                self.cancel.set()
            self.pending = None
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, render, cancel = self.pending
                self.pending = None
            try:
                with preview_cancellation(cancel):
                    result = render()
                    check_preview_cancelled()
                self.results.put((generation, result, None))
            except PreviewCancelled:
                pass
            except Exception as error:
                if not cancel.is_set():
                    self.results.put((generation, None, error))
