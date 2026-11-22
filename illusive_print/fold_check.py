"""Opt-in release QA: actual Tk controls, shared output, no printer submission."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import traceback

from PIL import Image,ImageDraw,ImageFont
from pypdf import PdfReader,PdfWriter
from .core import (Photo,Layout,Correction,page_items,page_count,ordered_tokens,
                   export_pdf,render_photo,render_page,load_source,_source_key)
from .preview import PreviewRenderer,render_tile
from .print_job import PrintSnapshot
from .metadata import VERSION


def panel_image(path,number,label):
    image=Image.new('RGB',(600,840),'white'); draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32)
    big=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',170)
    for x,y,color,text in ((20,20,'red','TL ●'),(470,20,'green','TR ■'),(20,760,'blue','BL ▲'),(470,760,'magenta','BR ◆')):
        draw.rectangle((x,y,x+110,y+55),outline=color,width=5)
        draw.text((x+6,y+9),text,font=font,fill=color)
    draw.line((300,220,300,90),fill='black',width=8)
    draw.polygon(((300,70),(280,110),(320,110)),fill='black')
    draw.text((255,230),'Верх',font=font,fill='black')
    draw.text((245,335),str(number),font=big,fill='black')
    draw.text((55,580),label,font=font,fill='black')
    image.save(path)


def run(app,output,portrait=None,landscape=None,keep_open=False):
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True)
    sources=output/'panels'; sources.mkdir(exist_ok=True)
    report={'version':VERSION,'executable':sys.executable,'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'passed':False}
    checks=report['checks']
    try:
        paths=[]
        for i in range(8):
            p=sources/f'panel-{i+1}.png'; panel_image(p,i+1,'Страница '+str(i+1)); paths.append(p)
        app.add_paths(paths); app.root.update()
        app.count_var.set('4'); app.copy_vars[0].set('2'); app.refresh()
        app.photos[0].offset_x=.37
        app.photos[0].correction=Correction(teal_orange='a_to_b')
        app.selected=0; app.selected_rows={0}; app.draw_preview()
        deadline=time.monotonic()+10
        while app._preview_pending and time.monotonic()<deadline:
            app.root.update(); time.sleep(.002)
        from types import SimpleNamespace
        handle=app._print_handle
        app.begin_drag(SimpleNamespace(x=handle[0]+8,y=handle[1]+8))
        cell=app.layout.cells()[2]
        app.end_drag(SimpleNamespace(x=app.preview_origin[0]+(cell.x+cell.width/2)*app.preview_scale,y=app.preview_origin[1]+(cell.y+cell.height/2)*app.preview_scale))
        checks['swap_specific_copy']=[i for i,p in page_items(app.photos,app.layout,0)]==[1,0,0,2]
        checks['swap_preserves_crop_color']=app.photos[0].offset_x==.37 and app.photos[0].correction.teal_orange=='a_to_b'
        expected=[t[0] for t in ordered_tokens(app.photos,app.print_sequence)]
        for count in ('1','2','6'):
            app.count_var.set(count); app.paper_var.set('A3'); app.refresh()
            actual=[p.uid for page in range(page_count(app.photos,app.layout)) for i,p in page_items(app.photos,app.layout,page)]
            checks['reflow_'+count]=actual==expected
        app.begin_library_move(0,SimpleNamespace(y_root=0)); app._library_target=3; app.end_library_move(None)
        checks['move_photo_group']=app.photos[2].copies==2 and app.photos[2].offset_x==.37
        for axis in ('Вертикальная','Горизонтальная'):
            app.center_line_var.set(axis); app.refresh()
            checks['center_'+axis]=bool(app.layout.output_segments(0))
        app.center_line_var.set('Нет')
        app.mode_var.set('Открытка со сгибом')
        for n in range(4): app.selected=n; app.assign_panel(n)
        checks['postcard_ui']=[[i for i,p in page_items(app.photos,app.layout,page)] for page in (0,1)]==[[1,0],[2,3]]
        app.assign_panel(2,clear=True); app.assign_panel(3,clear=True)
        checks['white_inside']=render_page(app.photos,app.layout,1,Correction(curve=((0,25),(255,220))),.5).getextrema()==((255,255),)*3
        photos=[Photo(p,mode='fit') for p in paths]
        layout=Layout(mode='booklet',paper_width=297,paper_height=210,margin=8,autorotate=False,fold_marks='ticks')
        combined=PdfWriter()
        postcard=replace(layout,mode='postcard',panels=tuple(p.uid for p in photos[:4]))
        for name,subset,l in [('postcard',photos,postcard)]+[(f'booklet-{n}',photos[:n],layout) for n in (4,5,8)]:
            destination=output/f'{name}.pdf'
            export_pdf(destination,subset,l,Correction(),300)
            reader=PdfReader(destination)
            checks[name+'_pdf_pages']=len(reader.pages)==page_count(subset,l)
            for page in reader.pages: combined.add_page(page)
            for page in range(page_count(subset,l)):
                screen=PreviewRenderer().prepare(subset,l,page,Correction(),1).image
                raster=render_page(subset,l,page,Correction(),1)
                # Compare image areas, avoiding vector marks and rounding edges.
                checks[name+f'_preview_{page}']=all(screen.getpixel((x,y))==raster.getpixel((x,y)) for x,y in ((40,40),(240,40)))
        combined.write(output/'OttiskPhoto_Duplex_Control.pdf')
        app.mode_var.set('Буклет'); app.refresh()
        snap=PrintSnapshot.capture(app.photos,app.layout,app.correction,1)
        checks['physical_sheet_two_sides']=snap.pages(True)==(0,1)
        checks['short_edge_upright']=not snap.layout.autorotate
        for name,source in (('portrait',portrait),('landscape',landscape)):
            if not source: continue
            source=Path(source)
            with Image.open(source) as opened:
                image=opened.convert('RGB'); image.thumbnail((700,700))
            if name=='portrait':
                white=Image.new('RGB',(image.width+100,image.height+100),'white'); white.paste(image,(50,50)); image=white
            source=output/f'{name}-input.png'; image.save(source)
            photo=Photo(source)
            l=Layout(per_sheet=1,paper_width=image.width/10,paper_height=image.height/10,autorotate=False)
            cell=l.cells()[0]
            montage=Image.new('RGB',(3*320,400),'white')
            for col,mode in enumerate(('none','a_to_b','b_to_a')):
                c=Correction(teal_orange=mode)
                preview=render_tile(photo,cell,image.size,c,False,_source_key(photo.path))
                expected=render_photo(photo,cell,c,image.size,False)
                checks[name+'_'+mode+'_preview']=preview.tobytes()==expected.tobytes()
                for individual in (False,True):
                    chosen=replace(photo,correction=c) if individual else photo
                    global_color=Correction() if individual else c
                    pdf=output/f'{name}-{mode}-{individual}.pdf'
                    export_pdf(pdf,[chosen],l,global_color)
                    embedded=next(iter(PdfReader(pdf).pages[0]['/Resources']['/XObject'].values())).get_object()
                    final=render_photo(chosen,cell,global_color,(round(cell.width*300/25.4),round(cell.height*300/25.4)),False)
                    checks[name+f'_{mode}_pdf_{individual}']=embedded.get_data()==final.tobytes()
                if name=='portrait': checks['white_'+mode]=preview.getpixel((0,0))==(255,255,255)
                thumb=preview.copy(); thumb.thumbnail((310,360)); montage.paste(thumb,(col*320,30))
                ImageDraw.Draw(montage).text((col*320+10,10),mode,fill='black')
            montage.save(output/f'{name}-comparison.png')
        app.selected=0; app.selected_rows={0}; app.set_individual_color(False)
        app.toggle_teal_orange('a_to_b'); checks['to_global']=app.correction.teal_orange=='a_to_b'
        app.toggle_teal_orange('b_to_a'); checks['to_switch']=app.correction.teal_orange=='b_to_a'
        app.toggle_teal_orange('b_to_a'); checks['to_off']=app.correction.teal_orange=='none'
        app.set_individual_color(True); app.toggle_teal_orange('a_to_b')
        checks['to_individual']=app.photos[0].correction.teal_orange=='a_to_b'
        app.reset_color(); checks['to_reset']=app.photos[0].correction.teal_orange=='none'
        report['passed']=all(checks.values())
    except Exception: report['error']=traceback.format_exc()
    finally:
        (output/'fold-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not keep_open: app.root.destroy()

