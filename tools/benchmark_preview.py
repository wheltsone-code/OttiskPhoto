"""Repeatable A3/9x12MP preview benchmark. Never prints or overwrites sources."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from illusive_print.core import Photo, Layout, Correction, render_page


def run(baseline=False,ui=False,profile_ui=False):
    folder=Path('tmp/preview-benchmark')
    folder.mkdir(parents=True,exist_ok=True)
    photos=[]
    for i in range(9):
        path=folder/f'photo-{i}.jpg'
        if not path.exists():
            g=Image.linear_gradient('L').resize((4000,3000))
            Image.merge('RGB',(g,g.point(lambda v:(v+i*17)%256),g.transpose(Image.Transpose.FLIP_LEFT_RIGHT))).save(path,quality=92)
        photos.append(Photo(path))
    layout=Layout(paper_width=297,paper_height=420,per_sheet=9)
    color=Correction(.2,1.1,temperature=.1,tint=-.05)
    if ui:
        import os
        import statistics
        os.environ['OTTISK_PHOTO_PREFERENCES']=str((folder/'ui-preferences.json').resolve())
        from illusive_print.app import create_root,IllusivePrintApp
        root=create_root()
        app=IllusivePrintApp(root)
        root.geometry('1270x840')
        app.paper_var.set('A3');app.count_var.set('9')
        started=perf_counter()
        try:
            app.add_paths([p.path for p in photos]);root.update()
            results={'import_and_first_view':round((perf_counter()-started)*1000,2)}
            app.temperature_var.set('10');app.tint_var.set('-5');app.saturation_var.set(20);app.gamma_var.set('1,10')
            root.update()
            samples=[]
            for _ in range(20):
                started=perf_counter();app.draw_preview();root.update_idletasks()
                samples.append((perf_counter()-started)*1000)
            results['repeat_median']=round(statistics.median(samples),2)
            results['repeat_p95']=round(sorted(samples)[18],2)
            for name,operation in (
                ('select_photo',lambda:app.select_photo(1)),
                ('crop_one',lambda:(setattr(app.photos[0],'offset_x',.5),app.draw_preview(True))),
                ('global_temperature',lambda:app.temperature_var.set('15'))):
                started=perf_counter()
                if profile_ui and name=='select_photo':
                    import cProfile,pstats
                    profile=cProfile.Profile()
                    profile.runcall(operation)
                    pstats.Stats(profile).sort_stats('cumulative').print_stats(20)
                else:operation()
                root.update_idletasks()
                results[name]=round((perf_counter()-started)*1000,2)
            report={'input':'A3, nine 4000x3000 JPEGs, actual Tk UI 1270x840','milliseconds':results}
            (folder/('ui-profile.json' if profile_ui else 'ui-after.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2))
        finally:root.destroy()
        return
    report={'input':'9 distinct JPEGs, 4000x3000 each; A3; 1.5 preview pixels/mm','seconds':{}}
    if baseline:
        render=lambda:render_page(photos,layout,0,color,1.5)
    else:
        from illusive_print.preview import PreviewRenderer
        renderer=PreviewRenderer()
        render=lambda:renderer.prepare(photos,layout,0,color,1.5)
    for name,change in (('cold',lambda:None),('repeat',lambda:None),
                        ('crop_one',lambda:setattr(photos[0],'offset_x',.5)),
                        ('individual_color',lambda:setattr(photos[0],'correction',Correction(.1,1.2,temperature=.2))),
                        ('repeat_after_edits',lambda:None)):
        change()
        started=perf_counter()
        result=render()
        report['seconds'][name]=round(perf_counter()-started,6)
        if not baseline:
            report.setdefault('updated_slots',{})[name]=len(result.changed)
    if not baseline:
        from illusive_print.image_cache import FULL_IMAGES, PREVIEW_IMAGES
        report['cache']={'full':FULL_IMAGES.info(),'preview':PREVIEW_IMAGES.info()}
    dest=folder/('before.json' if baseline else 'after.json')
    dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--ui',action='store_true')
    parser.add_argument('--profile',action='store_true')
    args=parser.parse_args()
    run(args.baseline,args.ui,args.profile)
