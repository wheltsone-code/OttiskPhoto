"""Thread-safe raster LRU bounded by bytes, not by an arbitrary photo count.

Eviction drops references, never closes an image still used by UI/output code.
Budgets cover cached pixel buffers; active working images and Tk textures are extra.
"""
from collections import OrderedDict
from functools import wraps
from threading import RLock


class ImageCache:
    def __init__(self,budget):
        self.budget=budget
        self.entries=OrderedDict()
        self.bytes=0
        self.hits=self.misses=0
        self.evictions=0
        self.lock=RLock()

    @staticmethod
    def cost(image):
        # Pillow stores RGB cores in four-byte pixels. Include a small allowance
        # for keys/profile metadata rather than counting compressed file bytes.
        pixel_bytes=1 if image.mode in ('1','L','P') else 2 if image.mode.startswith('I;16') else max(4,len(image.getbands()))
        return image.width*image.height*pixel_bytes+1024

    def get(self,key):
        if self in RESOURCES.caches: RESOURCES.refresh()
        with self.lock:
            entry=self.entries.get(key)
            if entry is None:
                self.misses+=1
                return None
            self.entries.move_to_end(key)
            self.hits+=1
            return entry[0]

    def put(self,key,image):
        size=self.cost(image)
        return self.put_sized(key,image,size)

    def put_sized(self,key,image,size):
        with self.lock:
            old=self.entries.pop(key,None)
            if old:self.bytes-=old[1]
            if size>self.budget:return image
            while self.entries and self.bytes+size>self.budget:
                _,(_,removed)=self.entries.popitem(last=False)
                self.bytes-=removed
                self.evictions+=1
            self.entries[key]=(image,size)
            self.bytes+=size
        return image

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.bytes=self.hits=self.misses=self.evictions=0

    def resize(self,budget):
        with self.lock:
            self.budget=max(0,budget)
            while self.entries and self.bytes>self.budget:
                _,(_,removed)=self.entries.popitem(last=False)
                self.bytes-=removed
                self.evictions+=1

    def info(self):
        with self.lock:
            return dict(bytes=self.bytes,budget=self.budget,entries=len(self.entries),hits=self.hits,misses=self.misses,evictions=self.evictions)


from .resources import RESOURCES
FULL_IMAGES=ImageCache(128*1024*1024)
PREVIEW_IMAGES=ImageCache(192*1024*1024)
RESOURCES.caches=(FULL_IMAGES,PREVIEW_IMAGES)
RESOURCES.refresh(True)


def image_memo(cache,namespace):
    def decorate(function):
        @wraps(function)
        def read(*args):
            key=(namespace,*args)
            image=cache.get(key)
            return cache.put(key,function(*args)) if image is None else image
        read.cache_clear=cache.clear
        read.cache_info=cache.info
        return read
    return decorate


def object_memo(cache,namespace,cost):
    def decorate(function):
        @wraps(function)
        def read(*args):
            key=(namespace,*args)
            value=cache.get(key)
            if value is None:
                value=function(*args)
                cache.put_sized(key,value,cost(args,value))
            return value
        read.cache_clear=cache.clear
        return read
    return decorate
