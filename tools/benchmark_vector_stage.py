"""Same local workloads for the recorded HEAD and updated application. No printing."""
import argparse
import cProfile
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time

parser=argparse.ArgumentParser()
parser.add_argument('--code-root',default='.')
parser.add_argument('--output',required=True)
parser.add_argument('--vectors',action='store_true')
args=parser.parse_args()
root=Path.cwd();output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(args.code_root).resolve()))
os.environ['OTTISK_PHOTO_CACHE']=str((output.parent/'disk-cache').resolve())
from PIL import Image
from illusive_print.core import Photo,Layout,Correction,render_page,export_pdf
from illusive_print.preview import PreviewRenderer,load_preview_source
from illusive_print.image_cache import FULL_IMAGES,PREVIEW_IMAGES
from process_memory import MemorySampler
sampler=MemorySampler();sampler.start()

report={'code_root':str(Path(args.code_root).resolve()),'workload':'nine distinct 4000x3000 JPEGs; A3 four slots; single A4 output 300ppi',
        'seconds':{},'memory':{},'cache':{},'vectors':{}}
profile=cProfile.Profile();profile.enable()
def measure(name,operation,repeats=1):
    samples=[];value=None
    for _ in range(repeats):
        start=time.perf_counter();value=operation();samples.append(time.perf_counter()-start)
    report['seconds'][name]={'median':statistics.median(samples),'samples':samples}
    return value

photos=[]
for i in range(9):
    path=root/'tmp/preview-benchmark'/f'photo-{i}.jpg'
    if not path.exists():raise RuntimeError('Run benchmark_preview.py to create identical input JPEGs first')
    photos.append(Photo(path))
FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
measure('photo_cold_open',lambda:[load_preview_source(p) for p in photos])
FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
measure('photo_reopen_after_ram_clear',lambda:[load_preview_source(p) for p in photos])
layout=Layout(paper_width=297,paper_height=420,per_sheet=4)
r=PreviewRenderer();color=Correction(.2,1.1,temperature=.1,tint=-.05)
measure('preview_first',lambda:r.prepare(photos,layout,0,Correction(),1.5))
measure('preview_repeat',lambda:r.prepare(photos,layout,0,Correction(),1.5),5)
measure('switch_page_cold',lambda:r.prepare(photos,layout,1,Correction(),1.5))
measure('switch_page_warm',lambda:r.prepare(photos,layout,0,Correction(),1.5),5)
photos[0].offset_x=.4
measure('crop_one',lambda:r.prepare(photos,layout,0,Correction(),1.5))
photos[0].rotate_clockwise()
measure('rotate_one',lambda:r.prepare(photos,layout,0,Correction(),1.5))
if hasattr(photos[0],'reflect'):
    photos[0].reflect()
    measure('reflect_one',lambda:r.prepare(photos,layout,0,Correction(),1.5))
photos[0].correction=color
measure('individual_color',lambda:r.prepare(photos,layout,0,Correction(),1.5))
measure('global_color',lambda:r.prepare(photos,layout,0,color,1.5))
output_layout=Layout(paper_width=210,paper_height=297,per_sheet=4)
measure('pdf_export_300',lambda:export_pdf(output.parent/'photos.pdf',photos[:4],output_layout,Correction(),300))
prepared=measure('print_prepare_300',lambda:render_page(photos[:4],output_layout,0,Correction(),300/25.4))
prepared.close()
report['cache']={'full':FULL_IMAGES.info(),'preview':PREVIEW_IMAGES.info()}
photo_tree_peak=sampler.peak

if args.vectors:
    from vector_fixtures import make_vectors
    from illusive_print.vector_import import prepare_document,identify,_ready
    from illusive_print.document_sources import pdf_pages,pdf_size
    from illusive_print.disk_cache import document_cache
    sources=make_vectors(output.parent/'vectors')
    paths=[sources/n for n in ('features.svg','multipage.svg','features.eps','postscript.ai','pdf-compatible.ai')]
    paths += [root/'tests/fixtures/vector/cdr15.cdr',root/'tests/fixtures/vector/libreoffice.eps']
    for path in paths:
        record={'kind':identify(path)};report['vectors'][path.name]=record
        try:
            start=time.perf_counter();document=prepare_document(path);record['cold_seconds']=time.perf_counter()-start
            _ready.clear()
            start=time.perf_counter();warm=prepare_document(path);record['disk_seconds']=time.perf_counter()-start
            record.update(pages=pdf_pages(warm.path),mm=pdf_size(warm.path,0),cache_hit=warm.cache_hit,warnings=warm.warnings)
            photo=Photo(path,pdf_page=0,flip_x=True,rotation=1)
            measure(path.name+'_export',lambda:export_pdf(output.parent/(path.stem+'-vector.pdf'),[photo],output_layout,Correction(),300))
        except Exception as error:record['error']=repr(error)
    cache=document_cache()
    report['disk_cache']={k:getattr(cache,k) for k in ('hits','misses','writes','evictions')}
try:
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
            ('peak','working','pool_peak','pool','nonpool_peak','nonpool','page','page_peak')]
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    c=Counters();c.cb=ctypes.sizeof(c);psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb)
    report['memory']={'peak_working_bytes':c.peak,'final_working_bytes':c.working}
except Exception as error:report['memory']={'error':repr(error)}
sampler.stop()
report['memory']['photo_tree_peak_sampled_bytes']=photo_tree_peak
report['memory']['whole_tree_peak_sampled_bytes']=sampler.peak
report['memory']['tree_sampling_interval_seconds']=.025
report['memory']['tree_samples']=sampler.samples
profile.disable();profile.dump_stats(str(output.with_suffix('.prof')))
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
