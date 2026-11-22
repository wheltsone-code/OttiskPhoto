"""Targeted desktop acceptance check; never sends a printer job."""
import json,sys,traceback
from pathlib import Path
from PIL import Image,ImageDraw
from .widgets import CheckMark
from .core import export_pdf,page_count

def run(app,output,dpi='100',keep_open=False):
    folder=Path(output).resolve();folder.mkdir(parents=True,exist_ok=True)
    report={'dpi':dpi,'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'errors':[]}
    app.root.report_callback_exception=lambda *args:report['errors'].append(''.join(traceback.format_exception(*args)))
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def settle():app.root.update()
    try:
        paths=[]
        for name,color in (('front','lightblue'),('back','lightyellow')):
            path=folder/(name+'_asymmetric_control_with_a_long_filename_0123456789.jpg')
            im=Image.new('RGB',(1600,1200),color);draw=ImageDraw.Draw(im)
            draw.rectangle((10,10,300,250),fill='red');draw.text((350,500),name.upper(),fill='black',font_size=100)
            draw.ellipse((1300,900,1580,1180),fill='blue');im.save(path,quality=95);paths.append(path)
        app.add_paths(paths);app.root.geometry('1080x740+20+20');settle()
        for language in ('Русский','English'):
            app.language_var.set(language)
            for mode in app.mode_combo.values:
                app.mode_var.set(mode);settle()
                for section in (app.color_section,app.bleed_section,app.trim_section):section.set_open(True)
                settle();app.settings_canvas.yview_moveto(1);settle()
                for section in (app.color_section,app.bleed_section,app.trim_section):section.set_open(False)
                settle();first,last=app.settings_canvas.yview()
                check(language+' '+mode+' scroll',0<=first<=last<=1)
                if mode=='Тираж':
                    label=app.repeat_duplex_check;bounds=label.bbox('check_label')
                    check(language+' duplex caption',bounds[2]<=label.winfo_width() and bounds[3]<=label.winfo_height())
                if mode in ('Разделить лист','Открытка со сгибом','Фото с рамкой'):
                    check(mode+' no overlay',not app.production_box.winfo_ismapped())
        app.language_var.set('Русский');app.mode_var.set('Тираж');app.repeat_lock_var.set(False)
        app.repeat_w_var.set('60');app.repeat_h_var.set('40');app.repeat_lock_var.set(True)
        app.repeat_fill_var.set('Задать тираж');app.repeat_quantity_var.set('100')
        app.repeat_back_var.set(list(app._repeat_sources)[1]);app.refresh();settle()
        original=(app.repeat_w_var.get(),app.repeat_h_var.get())
        app.repeat_lock_button.invoke();app.repeat_lock_button.invoke()
        check('lock preserves dimensions',original==(app.repeat_w_var.get(),app.repeat_h_var.get()))
        app.repeat_duplex_check.invoke();app.refresh();settle();check('back appears',app.repeat_back_row.winfo_ismapped())
        app.repeat_duplex_check.invoke();app.refresh();settle();check('back hides',not app.repeat_back_row.winfo_ismapped())
        app.individual_color_check.invoke();settle();check('individual enabled',app.individual_editing())
        app.individual_color_check.invoke();settle();check('individual disabled',not app.individual_editing())
        app.unit_var.set('in');settle();app.unit_var.set('mm');settle()
        check('units retain dimensions',original==(app.repeat_w_var.get(),app.repeat_h_var.get()))
        app.page=page_count(app.photos,app.layout)-1;app.refresh();settle()
        export_pdf(folder/'repeat-control.pdf',app.photos,app.layout,app.correction,300)
        check('pdf created',(folder/'repeat-control.pdf').stat().st_size>1000)
        app.page=0;app.refresh();settle();app.settings_canvas.yview_moveto(0);settle()
        app.open_advanced();settle();app.gamma_scale._changed('1.2');app.gamma_scale.reset();app._advanced.destroy();settle()
        check('gamma reset',app._number(app.gamma_var)==1)
        check('no callback exceptions',not report['errors']);report['passed']=True
    except Exception:report['failure']=traceback.format_exc()
    finally:
        (folder/'polish-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if not keep_open:app.root.after(100,app.root.destroy)
        else:
            app.root.deiconify();app.root.attributes('-topmost',True)
            app.root.lift();app.root.focus_force()
    return report
