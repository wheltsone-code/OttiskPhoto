"""TkDnD owns native OLE lifetime; paths are parsed by Tcl, never by spaces."""
from pathlib import Path
import traceback
from tkinterdnd2 import DND_FILES, COPY, REFUSE_DROP
from .diagnostics import record


class ExplorerDrop:
    def __init__(self, root, receive):
        self.root, self.receive = root, receive
        self.targets = []
        self.register(root)

    def register(self, widget):
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind('<<Drop>>', self.drop)
        widget.dnd_bind('<<DropEnter>>', self.enter)
        widget.dnd_bind('<<DropLeave>>', self.leave)
        self.targets.append(widget)

    def enter(self, event):
        if event.widget.winfo_class() == 'Canvas':
            event.widget.configure(highlightthickness=2, highlightbackground='#FD3977')
        return COPY

    def leave(self, event):
        if event.widget.winfo_class() == 'Canvas':
            event.widget.configure(highlightthickness=0)
        return COPY

    def drop(self, event):
        try:
            self.leave(event)
            paths = [Path(p) for p in self.root.tk.splitlist(event.data)]
            record('import.drop.received', count=len(paths))
            self.root.after_idle(lambda: self._receive(paths))
            return COPY
        except Exception:
            record('import.drop.error', traceback=traceback.format_exc())
            return REFUSE_DROP

    def _receive(self, paths):
        try:
            self.receive(paths)
        except Exception:
            record('import.drop.error', traceback=traceback.format_exc())
            self.root.report_callback_exception(*__import__('sys').exc_info())


def folder_images(folder):
    from .core import SUPPORTED
    files = sorted((p for p in Path(folder).iterdir() if p.is_file()), key=lambda p:p.name.casefold())
    images = [p for p in files if p.suffix.lower() in SUPPORTED]
    return images, len(files) - len(images)
