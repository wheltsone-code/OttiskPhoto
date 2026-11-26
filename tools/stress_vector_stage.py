"""Bounded long-session exercise, recording settled RSS instead of a leak claim."""
import gc
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from illusive_print.core import Photo,Layout,Correction
from illusive_print.preview import PreviewRenderer
from illusive_print.image_cache import FULL_IMAGES,PREVIEW_IMAGES
from illusive_print.resources import memory_snapshot

folder=Path('tmp/vector-stress');folder.mkdir(parents=True,exist_ok=True)
photos=[Photo(Path('tmp/preview-benchmark')/f'photo-{i}.jpg') for i in range(9)]
layout=Layout(paper_width=297,paper_height=420,per_sheet=4)
renderer=PreviewRenderer();samples=[];start=time.monotonic()
for cycle in range(200):
    p=photos[cycle%9];p.rotate_clockwise();p.reflect(cycle%2==0);p.offset_x=(cycle%5-2)/3
    p.correction=Correction(gamma=1+(cycle%4)/10,temperature=(cycle%3)/10)
    renderer.prepare(photos,layout,(cycle//7)%3,Correction(),1.5)
    if cycle%20==19:
        gc.collect();samples.append({'cycle':cycle+1,'rss':memory_snapshot().process,
            'full':FULL_IMAGES.info(),'preview':PREVIEW_IMAGES.info()})
    if cycle%50==49:FULL_IMAGES.clear();PREVIEW_IMAGES.clear()
report={'cycles':200,'seconds':time.monotonic()-start,'settled_samples':samples,
        'rss_change_after_warmup':samples[-1]['rss']-samples[1]['rss'],
        'scope':'200 edits/page switches with cache eviction; not an hours-long or clean-machine test'}
(folder/'report.json').write_text(json.dumps(report,indent=2),'utf-8');print(json.dumps(report,indent=2))
