"""Persist expensive screen sources, never high-churn colour/crop variants."""
from functools import wraps
from pathlib import Path
import tempfile
import time
from PIL import Image, __version__ as pillow_version
from .disk_cache import document_cache


def persistent_screen(function):
    @wraps(function)
    def render(*args):
        from .vector_import import source_digest
        path,modified,length,page,bucket=args
        cache=document_cache()
        digest=source_digest(path,modified,length)
        key=cache.key(('screen-v1',pillow_version,digest,page,bucket,'sRGB-white'))
        found=cache.get(key,'.png')
        if found:
            try:
                with Image.open(found[0]) as image: return image.copy()
            except (OSError,ValueError): pass
            finally: cache.pinned.discard(found[0].name)
        started=time.perf_counter()
        image=function(*args)
        if time.perf_counter()-started > .025:
            try:
                with tempfile.TemporaryDirectory(prefix='ottisk-screen-') as temp:
                    output=Path(temp)/'screen.png';image.save(output,compress_level=1)
                    saved=cache.publish(key,'.png',output)
                    cache.pinned.discard(saved.name)
            except OSError: pass  # A disposable cache must never break an import.
        return image
    return render
