"""Repeatable cold-effect GUI timing and exact before/after raster comparison."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from PIL import Image,ImageChops,ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from illusive_print.app import IllusivePrintApp,create_root
from illusive_print.core import load_source,Photo
from illusive_print.color import teal_orange
from illusive_print.image_cache import PREVIEW_IMAGES,FULL_IMAGES


def digest(image): return hashlib.sha256(image.tobytes()).hexdigest()


def make_inputs(folder):
    folder.mkdir(parents=True,exist_ok=True)
    large=folder/'large-24MP.jpg'
    if not large.exists():
        with Image.open(ROOT/'tmp/landscape.jpg') as source:
            source.convert('RGB').resize((6000,4000),Image.Resampling.LANCZOS).save(large,quality=96)
        with Image.open(ROOT/'tmp/channel-gain/portrait.jpg') as source:
            portrait=source.convert('RGB')
        for i in range(6):
            with Image.open(large) as source:
                image=source.resize((3000,2000))
            if i%2: image=ImageOps.mirror(image)
            if i>=2:
                tile=portrait.resize((1200,1600)); image.paste(tile,(300*(i-2),200))
            image.save(folder/f'sheet-{i}.jpg',quality=94)
    return large,[folder/f'sheet-{i}.jpg' for i in range(6)]


def wait_preview(app,root):
    deadline=time.perf_counter()+60
    while time.perf_counter()<deadline:
        root.update()
        pending=getattr(app,'_preview_pending',False)
        if not pending: return
        time.sleep(.002)
    raise TimeoutError('Preview did not settle')


def benchmark(stage,output,full=True,reference=False,synchronous=False):
    if reference:
        import importlib.util
        from illusive_print import core
        spec=importlib.util.spec_from_file_location('to_reference',ROOT/'tmp/to-optimization/reference_color.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        core.teal_orange=module.teal_orange
    output.mkdir(parents=True,exist_ok=True)
    baseline=output.parent/'before'
    large,sheet=make_inputs(output.parent/'inputs')
    result={'stage':stage,'input':{'path':str(large),'size':[6000,4000],'bytes':large.stat().st_size,'sha256':hashlib.sha256(large.read_bytes()).hexdigest()},'gui':[],'full':[]}
    for scenario,paths,count in (('large',[large],'1'),('six-photos',sheet,'6')):
        for mode in ('a_to_b','b_to_a'):
            gc.collect(); PREVIEW_IMAGES.clear(); FULL_IMAGES.clear()
            os.environ['OTTISK_PHOTO_PREFERENCES']=str(output/'preferences.json')
            root=create_root(); app=IllusivePrintApp(root)
            if synchronous:
                app.preview_frame=lambda scale:app._preview_renderer.prepare(app.photos,app.layout,app.page,app.correction,scale,not app.preview_before)
            try:
                app.count_var.set(count); app.add_paths(paths); root.update(); wait_preview(app,root)
                ticks=[]; tick_job=None
                def tick():
                    nonlocal tick_job
                    ticks.append(time.perf_counter()); tick_job=root.after(10,tick)
                tick()
                until=time.perf_counter()+.1
                while time.perf_counter()<until: root.update(); time.sleep(.002)
                start=time.perf_counter(); app.to_buttons[mode].invoke(); returned=time.perf_counter()
                wait_preview(app,root); visible=time.perf_counter()
                until=time.perf_counter()+.05
                while time.perf_counter()<until: root.update(); time.sleep(.002)
                image=app._preview_renderer.frame.image.copy()
                path=output/f'{scenario}-{mode}.png'; image.save(path)
                case={'scenario':scenario,'mode':mode,'callback_ms':(returned-start)*1000,'first_visible_ms':(visible-start)*1000,'max_heartbeat_gap_ms':max(b-a for a,b in zip(ticks,ticks[1:]))*1000,'sha256_pixels':digest(image),'size':list(image.size)}
                if stage!='before':
                    with Image.open(baseline/path.name) as ref:
                        diff=ImageChops.difference(image,ref.convert('RGB'))
                        case['pixel_identical']=not diff.getbbox()
                        case['max_channel_difference']=max(v[1] for v in diff.getextrema())
                result['gui'].append(case)
            finally:
                if tick_job: root.after_cancel(tick_job)
                root.destroy()
    (output/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if full:
        source=load_source(Photo(large))
        for mode in ('a_to_b','b_to_a'):
            start=time.perf_counter(); image=teal_orange(source,mode); elapsed=time.perf_counter()-start
            path=output/f'full-{mode}.png'; image.save(path)
            case={'mode':mode,'ms':elapsed*1000,'sha256_pixels':digest(image)}
            if stage!='before':
                with Image.open(baseline/path.name) as ref:
                    diff=ImageChops.difference(image,ref.convert('RGB'))
                    case['pixel_identical']=not diff.getbbox()
                    case['max_channel_difference']=max(v[1] for v in diff.getextrema())
            result['full'].append(case)
    (output/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('stage'); parser.add_argument('--skip-full',action='store_true')
    parser.add_argument('--reference',action='store_true'); parser.add_argument('--synchronous',action='store_true')
    args=parser.parse_args()
    benchmark(args.stage,ROOT/'tmp/to-optimization'/args.stage,not args.skip_full,args.reference,args.synchronous)
