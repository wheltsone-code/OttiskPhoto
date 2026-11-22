"""Local diagnostics; driver-private bytes are represented only by a hash."""
from datetime import datetime, timezone
import hashlib
import json
from threading import Lock
from .i18n import preferences_path

_lock = Lock()
_crash_stream = None
_roots = set()


def install(root):
    """Exceptions remain visible in windowed EXE; fatal traces survive aborts."""
    import faulthandler
    import sys
    import threading
    import traceback
    global _crash_stream
    _roots.add(id(root))
    def closed(event):
        global _crash_stream
        if event.widget == root:
            _roots.discard(id(root))
            if not _roots and _crash_stream is not None:
                faulthandler.disable()
                _crash_stream.close()
                _crash_stream = None
    root.bind('<Destroy>',closed,add=True)
    def exception(kind,value,tb):
        record('application.exception',traceback=''.join(traceback.format_exception(kind,value,tb)))
    root.report_callback_exception = exception
    sys.excepthook = exception
    threading.excepthook = lambda args: exception(args.exc_type,args.exc_value,args.exc_traceback)
    if _crash_stream is None:
        try:
            path = preferences_path().parent/'crash.log'
            path.parent.mkdir(parents=True,exist_ok=True)
            _crash_stream = path.open('a',encoding='utf-8')
            faulthandler.enable(file=_crash_stream,all_threads=True)
        except OSError:
            pass
    record('application.start',executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)),drop_backend='TkDnD')

def record(event, **values):
    try:
        path = preferences_path().parent / 'diagnostics.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'event': event, **values},
                                    ensure_ascii=False, default=str) + '\n')
    except OSError:
        pass

def devmode(settings):
    result = {key: getattr(settings, key, None) for key in
              ('PaperSize', 'PaperWidth', 'PaperLength', 'FormName', 'Orientation', 'Scale', 'Copies', 'Fields')}
    data = getattr(settings, 'DriverData', b'')
    result.update(private_size=len(data), private_sha256=hashlib.sha256(data).hexdigest())
    return result
