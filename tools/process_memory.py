"""Windows benchmark-only process-tree working-set sampler (no dependency)."""
import ctypes
from ctypes import wintypes
import os
import threading


class MemorySampler:
    def __init__(self):
        self.stop_event=threading.Event();self.peak=0;self.samples=0
        self.thread=threading.Thread(target=self.run,daemon=True)
    def start(self):self.thread.start()
    def stop(self):self.stop_event.set();self.thread.join(2)
    def run(self):
        if os.name!='nt':return
        class Entry(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
                ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
                ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('exe',wintypes.WCHAR*260)]
        class Memory(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                ('peak','working','pool_peak','pool','nonpool_peak','nonpool','page','page_peak')]
        kernel=ctypes.WinDLL('kernel32');psapi=ctypes.WinDLL('psapi')
        kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
        kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        while not self.stop_event.is_set():
            parents={};snapshot=kernel.CreateToolhelp32Snapshot(2,0)
            if snapshot and snapshot!=wintypes.HANDLE(-1).value:
                entry=Entry();entry.size=ctypes.sizeof(entry)
                ok=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
                while ok:
                    parents[entry.pid]=entry.parent;ok=kernel.Process32NextW(snapshot,ctypes.byref(entry))
                kernel.CloseHandle(snapshot)
            descendants={os.getpid()}
            while True:
                found={pid for pid,parent in parents.items() if parent in descendants}
                if found<=descendants:break
                descendants.update(found)
            total=0
            for pid in descendants:
                handle=kernel.OpenProcess(0x410,False,pid)
                if handle:
                    m=Memory();m.cb=ctypes.sizeof(m)
                    if psapi.GetProcessMemoryInfo(handle,ctypes.byref(m),m.cb):total+=m.working
                    kernel.CloseHandle(handle)
            self.peak=max(self.peak,total);self.samples+=1
            self.stop_event.wait(.025)
