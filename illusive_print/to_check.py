"""Opt-in frozen-app checks for asynchronous TO; no PDF/printer submission."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

from .core import Correction
from .metadata import VERSION
from .preview import PreviewRenderer


def run(app,output,inputs):
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    inputs=Path(inputs).resolve()
    report={'version':VERSION,'executable':sys.executable,'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'timings':[],'passed':False}
    checks=report['checks']
    def settle():
        until=time.monotonic()+30
        while app._preview_pending and time.monotonic()<until:
            app.root.update(); time.sleep(.002)
        assert not app._preview_pending,'Preview timeout'
    def exact():
        expected=PreviewRenderer().prepare(tuple(replace(p) for p in app.photos),app.layout,app.page,app.correction,app.preview_scale,not app.preview_before)
        return expected.image.tobytes()==app._preview_renderer.frame.image.tobytes()
    try:
        for name,paths,count in (('large',[inputs/'large-24MP.jpg'],'1'),('six-photos',[inputs/f'sheet-{n}.jpg' for n in range(6)],'6')):
            if app.photos:
                app.selected_rows=set(range(len(app.photos))); app.remove_selected()
            app.correction=Correction(); app.global_curve=app.correction.curve
            app.count_var.set(count); app.add_paths(paths); app.root.update(); settle()
            for mode in ('a_to_b','b_to_a'):
                if app.correction.teal_orange!='none':
                    app.toggle_teal_orange(app.correction.teal_orange); app.root.update()
                start=time.perf_counter(); app.to_buttons[mode].invoke(); returned=time.perf_counter()
                heartbeat=[]; app.root.after(0,lambda:heartbeat.append(True)); app.root.update()
                checks[name+'_'+mode+'_mainloop']=bool(heartbeat)
                settle(); visible=time.perf_counter()
                checks[name+'_'+mode+'_exact']=exact()
                image=app._preview_renderer.frame.image
                report['timings'].append({'scenario':name,'mode':mode,'callback_ms':(returned-start)*1000,'ready_ms':(visible-start)*1000,'sha256_pixels':hashlib.sha256(image.tobytes()).hexdigest()})
            # Finish with no effect; a cancelled result must not overwrite it.
            app.toggle_teal_orange('a_to_b'); app.toggle_teal_orange('b_to_a'); app.toggle_teal_orange('b_to_a')
            settle(); checks[name+'_quick_off']=app.correction.teal_orange=='none' and exact()
            app.toggle_teal_orange('a_to_b'); app.toggle_teal_orange('b_to_a')
            settle(); checks[name+'_quick_last']=app.correction.teal_orange=='b_to_a' and exact()
        report['passed']=all(checks.values())
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        (output/'to-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.root.destroy()
