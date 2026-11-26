"""Frozen-app integration check. Uses a fake print backend; never submits a job."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback
from pypdf import PdfReader
from .core import Correction, Layout, export_pdf, render_page, source_size
from .print_job import PrintSnapshot, PrintJob
from .metadata import VERSION


def run(app, output, source, keep_open=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'warnings':[]}
    checks=report['checks'];warnings=[]
    original_choose=app.choose_pdf_import
    from . import import_tasks
    original_warning=import_tasks.messagebox.showwarning
    import_tasks.messagebox.showwarning=lambda *a,**kw:warnings.append(str(a))
    app.choose_pdf_import=lambda path=None,count=None:list(range(count)) if count else 'Все страницы'
    ticks=[]
    active=[True]
    def heartbeat():
        ticks.append(time.monotonic())
        if active[0]:app.root.after(20,heartbeat)
    app.root.after(20,heartbeat)
    try:
        paths=[p for p in Path(source).iterdir() if p.suffix.lower() in ('.svg','.ai','.eps','.cdr') and p.name!='false.ai']
        app.start_import(paths,folder_batch=True)
        deadline=time.monotonic()+180
        while app._import_job and time.monotonic()<deadline:
            app.root.update();time.sleep(.005)
        assert app._import_job is None,'import timeout'
        checks['import']=not app.last_import_errors and len(app.photos)>=len(paths)
        assert checks['import'],repr(app.last_import_errors)
        app.selected_rows=set(range(len(app.photos)))
        before=[replace(p) for p in app.photos]
        app.reflect_photos(True);app.reflect_photos(False)
        assert all(p.flip_x and p.flip_y for p in app.photos)
        app.undo();assert all(p.flip_x and not p.flip_y for p in app.photos)
        app.undo();assert app.photos==before
        checks['batch_reflection_undo']=True
        app.reflect_photos(True);app.rotate_photo()
        snapshot=PrintSnapshot.capture(app.photos,app.layout,app.correction,app.page)
        assert all(p.flip_y for p in snapshot.photos)
        app.reset_frame();assert all(p.flip_y for p in snapshot.photos)
        checks['immutable_print_snapshot']=True
        report['sources']=[{'file':p.name,'page':p.pdf_page,'mm':source_size(p).millimetres} for p in app.photos]
        layout=Layout(paper_width=100,paper_height=150,per_sheet=4)
        photos=list(snapshot.photos[:4])
        for ppi in (300,600):
            path=output/f'vector-{ppi}.pdf';export_pdf(path,photos,layout,Correction(),ppi)
            page=PdfReader(path).pages[0]
            assert any(ref.get_object().get('/Subtype')=='/Form' for ref in page['/Resources']['/XObject'].values())
            checks[f'pdf_{ppi}_has_vector_forms']=True
        class Backend:
            def submit(self,printer,settings,paths,layout,managed,title,before_start=None,**kwargs):
                assert paths and all(p.stat().st_size>100 for p in paths)
                assert before_start()
                checks['print_preparation_fake_backend']=True
                return 1
        job=PrintJob()
        job._run(PrintSnapshot.capture(photos,layout,Correction(),0),False,300,Backend(),'test',None,None)
        assert job.state=='sent'
        app.count_var.set('4');app.refresh();app.root.update()
        deadline=time.monotonic()+20
        while app._preview_pending and time.monotonic()<deadline:
            app.root.update();time.sleep(.01)
        app._preview_renderer.frame.image.save(output/'preview.png')
        app.language_var.set('English');app.root.update()
        assert app.display_text('↔ Отразить')=='↔ Mirror'
        checks['ru_en']=True
        gaps=[b-a for a,b in zip(ticks,ticks[1:])]
        report['ui_heartbeat_max_gap_seconds']=max(gaps,default=0)
        report['warnings']=warnings+getattr(app,'last_import_warnings',[])
        report['passed']=all(checks.values())
    except Exception:
        report['passed']=False;report['error']=traceback.format_exc()
    finally:
        active[0]=False
        app.choose_pdf_import=original_choose
        import_tasks.messagebox.showwarning=original_warning
        (output/'self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        if not keep_open:app.root.destroy()
