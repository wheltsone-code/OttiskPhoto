"""Opt-in packaged UI/DPI/gesture regression checks without physical printing."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace
from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium

from .core import Correction,booklet_pages,page_items,page_labels,export_pdf,render_page
from .preview import PreviewRenderer
from .metadata import VERSION


def run(app,output,scale='100',keep_open=False):
    if keep_open:app.root.attributes('-topmost',True)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'executable':sys.executable,'requested_Tk_percent':int(scale),'tk_pixels_per_inch':app.root.winfo_fpixels('1i'),'checks':{},'passed':False}
    checks=report['checks']
    def point(widget):return SimpleNamespace(x_root=widget.winfo_rootx()+widget.winfo_width()/2,y_root=widget.winfo_rooty()+widget.winfo_height()/2,widget=widget)
    def slot(n):
        cell=app.layout.cells()[n]
        return SimpleNamespace(x=app.preview_origin[0]+(cell.x+cell.width/2)*app.preview_scale,y=app.preview_origin[1]+(cell.y+cell.height/2)*app.preview_scale)
    def grab(index):
        app.select_photo(index,keep_page=True);app.draw_preview();h=app._print_handle
        assert h is not None
        app.begin_drag(SimpleNamespace(x=h[0]+4,y=h[1]+4))
    def compare_pdf(name):
        path=output/(name+'.pdf');export_pdf(path,app.photos,app.layout,Correction())
        reader=PdfReader(path);doc=pdfium.PdfDocument(path)
        okay=True
        for page in range(len(reader.pages)):
            raster=render_page(app.photos,app.layout,page,Correction(),1)
            screen=PreviewRenderer().prepare(app.photos,app.layout,page,Correction(),1).image
            pdf=doc[page].render(scale=25.4/72).to_pil().convert('RGB')
            for x in (30,220):
                pixel=raster.getpixel((x,60))
                okay &= pixel==screen.getpixel((x,60)) and max(abs(a-b) for a,b in zip(pixel,pdf.getpixel((x,60))))<=1
            pdf.save(output/f'{name}-{page+1}.png')
        doc.close();checks[name+'_pdf_preview']=bool(okay)
    try:
        import ctypes
        report['native_window_dpi']=ctypes.windll.user32.GetDpiForWindow(app.root.winfo_id())
        folder=output/'fixtures';folder.mkdir(exist_ok=True)
        paths=[]
        for i in range(24):
            path=folder/(f'{i+1:02}-'+'Длинное имя фотографии для проверки списка '+'.png')
            Image.new('RGB',(420,140),(30+i*7,60+i*5,220-i*6)).save(path);paths.append(path)
        app.root.geometry('1080x740+20+20');app.add_paths(paths);app.root.update();app.refresh();app.root.update()
        first=app.thumbnail_widgets[0][0]
        checks['left_handle']=first._handle.winfo_x()<app.thumbnail_widgets[0][1].winfo_x()
        checks['ellipsized_name']='…' in app.thumbnail_widgets[0][2].cget('text')
        checks['copies_fit']=app.copy_buttons[0][1].winfo_rootx()+app.copy_buttons[0][1].winfo_width()<=first.winfo_rootx()+first.winfo_width()
        checks['scrollbar_separate']=app.library_scrollbar.winfo_rootx()>=app.library_canvas.winfo_rootx()+app.library_canvas.winfo_width()
        scroll=app.library_scrollbar;y,length,_=scroll.geometry_values()
        scroll.press(SimpleNamespace(y=y+length/2));scroll.motion(SimpleNamespace(y=y+length/2+60));scroll.release(None);app.root.update()
        checks['thumb_drag']=app.library_canvas.yview()[0]>0
        before=app.library_canvas.yview()[0];app.library_canvas.event_generate('<MouseWheel>',delta=-120);app.root.update()
        checks['wheel']=app.library_canvas.yview()[0]>before
        app.library_canvas.yview_moveto(0);app.root.update()
        app.begin_library_move(0,point(first._handle))
        app._library_pointer=(app.library_canvas.winfo_rootx()+10,app.library_canvas.winfo_rooty()+app.library_canvas.winfo_height()-1)
        app.root.after_cancel(app._library_scroll_job);app._library_scroll_job=None;app.library_autoscroll();app.root.update()
        checks['autoscroll']=app.library_canvas.yview()[0]>0
        checks['insertion_line']=app._insert_line.winfo_manager()=='place'
        app._library_target=0;app.end_library_move(None)
        app.mode_var.set('Открытка со сгибом');app.panel_ids=[p.uid for p in app.photos[:4]];app.refresh();app.root.update()
        checks['postcard_counter']=app.counter_var.get()=='1 лист · 2 стороны'
        for left,right in ((app.previous_button,app.page_label),(app.page_label,app.next_button)):
            checks['navigation_no_overlap_'+str(left)]=left.winfo_rootx()+left.winfo_width()<=right.winfo_rootx()
        app.photos[0].offset_x=.3;original=list(app.panel_ids)
        grab(0);app.end_drag(slot(0));checks['panel_swap']=app.panel_ids[:2]==[original[1],original[0]]
        app.assign_panel(2,clear=True);grab(0);app.drag_motion(point(app.panel_buttons[2]))
        checks['target_highlight']=app.panel_buttons[2].cget('bg')=='#ffd8e9'
        app.end_drag(point(app.panel_buttons[2]));checks['cross_side_move']=app.panel_ids[1] is None and app.panel_ids[2]==original[0]
        checks['crop_kept']=app.photos[0].offset_x==.3
        app.begin_library_move(4,point(app.thumbnail_widgets[4][0]._handle));app.end_library_move(point(app.panel_buttons[1]))
        checks['library_to_panel']=app.panel_ids[1]==app.photos[4].uid
        app.page=1;app.refresh();event=slot(0);app.begin_drag(event);app.drag_motion(SimpleNamespace(x=event.x+20,y=event.y));app.end_drag()
        checks['crop_drag']=app.photos[0].offset_x!=.3
        compare_pdf('postcard')
        app.mode_var.set('Буклет');app.refresh();app.root.update()
        covers=list(app.booklet_cover_ids)
        app.begin_library_move(1,point(app.thumbnail_widgets[1][0]._handle));app._library_target=4;app.end_library_move(None)
        checks['pinned_covers']=app.booklet_cover_ids==covers
        app.selected_rows=set(range(5,len(app.photos)));app.remove_selected()
        # Explicitly assign current first/last to make the five-page example.
        app.assign_cover(0,uid=app.photos[0].uid);app.assign_cover(1,uid=app.photos[-1].uid);app.refresh();app.root.update()
        checks['padding_before_END']=[label for token,label in booklet_pages(app.photos,app.layout)]==['0','1','2','3','Пусто','Пусто','Пусто','END']
        checks['covers_outside']=page_labels(app.photos,app.layout,0)==('END','0')
        checks['booklet_counter']=app.counter_var.get()=='2 листа · 4 стороны'
        app.select_photo(2);checks['list_navigation']=any(i==2 for i,p in page_items(app.photos,app.layout,app.page))
        checks['UI_only_labels']=bool(app.preview_canvas.find_withtag('page_badge'))
        compare_pdf('booklet')
        report['passed']=all(checks.values())
    except Exception:report['error']=traceback.format_exc()
    finally:
        (output/'duplex-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not keep_open:app.root.destroy()
        else:
            app.root.title('Оттиск Фото — проверка жестов')
            app.mode_var.set('Открытка со сгибом');app.panel_ids=[p.uid for p in app.photos[:4]];app.page=0;app.refresh()
            def state():
                data={'panels':app.panel_ids,'photos':[p.uid for p in app.photos],'names':[p.name for p in app.photos],'page':app.page,'counter':app.counter_var.get(),'scroll':app.library_canvas.yview(),'crops':[(p.offset_x,p.offset_y) for p in app.photos]}
                (output/'live-state.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                if not app._closing:app.root.after(500,state)
            state()
