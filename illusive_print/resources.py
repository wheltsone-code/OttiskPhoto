"""Automatic process-wide budgets, including working memory outside the LRUs."""
from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import shutil
import threading
import time
from functools import wraps

MiB = 1024**2
GiB = 1024**3


@dataclass(frozen=True)
class Memory:
    total: int
    available: int
    process: int


def memory_snapshot():
    if os.name == 'nt':
        from ctypes import wintypes
        class Status(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [(n, ctypes.c_ulonglong) for n in
                ('total', 'available', 'page_total', 'page_available', 'virtual', 'virtual_available', 'extended')]
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                ('peak', 'working', 'pool_peak', 'pool', 'nonpool_peak', 'nonpool', 'page', 'page_peak')]
        status = Status(); status.length = ctypes.sizeof(status)
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
            return Memory(status.total, status.available, counters.working)
    # Conservative fallback if telemetry is unavailable; no user settings.
    return Memory(4*GiB, GiB, 512*MiB)


class ResourceManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.reserved = 0
        self.last = 0
        self.caches = ()
        self.peak_reserved = 0

    def refresh(self, force=False):
        with self.lock:
            now = time.monotonic()
            if not force and now-self.last < 1:
                return
            self.last = now
            m = memory_snapshot()
            cached = sum(c.bytes for c in self.caches)
            # RSS includes UI textures, PDF parsers and active rasters. Keep
            # headroom for the OS and allocations not represented by reservations.
            reserve = max(768*MiB, m.total//8)
            headroom = max(0, m.available-reserve-self.reserved)
            ceiling = max(0, m.total//2-max(0, m.process-cached)-self.reserved)
            budget = min(m.total//4, ceiling, cached+headroom//2)
            pressure = m.available < reserve or m.process+self.reserved > m.total*0.65
            if pressure:
                budget = min(budget, cached//2)
            # Retain a small hot screen working set under moderate pressure.
            # Repeatedly halving it on every sample causes decode/eviction loops.
            floor = min(64*MiB, m.available//8)
            budget = max(floor, budget)
            for cache, share in zip(self.caches, (0.45, 0.55)):
                target = int(budget*share)
                if pressure or abs(target-cache.budget) > max(64*MiB, cache.budget//4):
                    cache.resize(target)

    @contextmanager
    def working(self, estimate):
        with self.lock:
            self.reserved += max(0, estimate)
            self.peak_reserved = max(self.peak_reserved, self.reserved)
        self.refresh(True)
        try:
            yield
        finally:
            with self.lock:
                self.reserved -= max(0, estimate)


RESOURCES = ResourceManager()


def working_budget(estimate):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with RESOURCES.working(estimate(*args, **kwargs)):
                return function(*args, **kwargs)
        return run
    return decorate


def disk_budget(root):
    usage = shutil.disk_usage(Path(root))
    # Never consume the last 5 GiB (or 10% on a small volume).
    reserve = min(5*GiB, usage.total//10)
    return min(32*GiB, usage.total//20, max(0, usage.free-reserve)//2)
