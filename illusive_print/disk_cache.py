"""Disposable local cache. Atomic publication, verified hits and crash recovery."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from .resources import disk_budget


class DiskCache:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('OTTISK_PHOTO_CACHE',
            Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir()))/'OttiskPhoto'/'Cache'/'v1'))
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pinned = set()
        self.hits = self.misses = self.writes = self.evictions = 0
        self.last_cleanup = 0

    @staticmethod
    def key(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, key, suffix):
        path = self.root/(key+suffix)
        with self.lock:
            try:
                meta = json.loads(path.with_suffix(path.suffix+'.json').read_text('utf-8'))
                if path.stat().st_size != meta['bytes']:
                    raise ValueError('incomplete cache entry')
                # Hash is verified on every read: a damaged PDF must be rebuilt.
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != meta['sha256']:
                        raise ValueError('damaged cache entry')
                os.utime(path, None)
                self.pinned.add(path.name)
                self.hits += 1
                return path, meta.get('warnings', [])
            except (OSError, ValueError, KeyError):
                self.misses += 1
                return None

    def publish(self, key, suffix, source, warnings=()):
        import shutil
        with self.lock:
            self.prune(force=True)
            occupied=sum(p.stat().st_size for p in self.root.iterdir() if p.is_file() and p.suffix not in ('.json','.part') and p.name!=key+suffix)
            if occupied+source.stat().st_size > disk_budget(self.root):
                raise OSError('Недостаточно места для локального кэша / Not enough space for local cache')
            path = self.root/(key+suffix)
            fd, temporary = tempfile.mkstemp(dir=self.root, suffix='.part')
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
                    shutil.copyfileobj(stream, output)
                    output.flush(); os.fsync(output.fileno())
                with open(temporary, 'rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                meta = {'bytes': Path(temporary).stat().st_size, 'sha256': digest, 'warnings': list(warnings)}
                os.replace(temporary, path)
                # Metadata is the commit marker; missing marker means a miss.
                marker = Path(temporary+'.json')
                marker.write_text(json.dumps(meta, ensure_ascii=False), 'utf-8')
                os.replace(marker, path.with_suffix(path.suffix+'.json'))
                self.pinned.add(path.name)
                self.writes += 1
                return path
            finally:
                Path(temporary).unlink(missing_ok=True)
                Path(temporary+'.json').unlink(missing_ok=True)

    def prune(self, force=False):
        with self.lock:
            now = time.time()
            if not force and now-self.last_cleanup < 60:
                return
            self.last_cleanup = now
            entries = []
            for path in self.root.iterdir():
                if not path.is_file(): continue
                stat = path.stat()
                if '.part' in path.name or (path.suffix == '.json' and not Path(str(path)[:-5]).exists()):
                    if now-stat.st_mtime > 86400: path.unlink(missing_ok=True)
                elif path.suffix != '.json':
                    entries.append((stat.st_mtime, path, stat.st_size))
            total = sum(e[2] for e in entries)
            limit = disk_budget(self.root)
            # Screen rasters are cheaper to rebuild than converted documents.
            for touched, path, size in sorted(entries,key=lambda e:(e[1].suffix!='.png',e[0])):
                if path.name in self.pinned: continue
                if total <= limit and now-touched < 30*86400: continue
                try:
                    path.unlink(missing_ok=True)
                    path.with_suffix(path.suffix+'.json').unlink(missing_ok=True)
                    total -= size; self.evictions += 1
                except OSError: pass


_cache = None
def document_cache():
    global _cache
    if _cache is None:
        _cache = DiskCache()
        _cache.prune(True)
    return _cache
