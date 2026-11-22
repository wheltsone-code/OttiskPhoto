"""Opt-in QA of editable booklet pages in source and frozen distributions."""
import json
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium

from .core import Correction,booklet_pages,page_count,page_items,export_pdf
from .metadata import VERSION
from .preview import PreviewRenderer


def run(app,output,keep_open=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
            'executable':sys.executable,'checks':{},'passed':False}
    checks=report['checks']
    def check(name,value):
        checks[name]=bool(value)
        if not value:raise AssertionError(name)
    def settle():
        app.refresh();app.root.update()
        deadline=time.monotonic()+15
        while app._preview_pending and time.monotonic()<deadline:
            app.root.update();time.sleep(.01)
        app.draw_preview()
    def point(widget):
        return SimpleNamespace(widget=widget,x_root=widget.winfo_rootx()+widget.winfo_width()/2,
                               y_root=widget.winfo_rooty()+widget.winfo_height()/2)
    try:
        app.root.geometry('1257x900')
        paths=[]
        for i in range(9):
            path=output/f'photo-{i+1}.png'
            Image.new('RGB',(300,420),(35+i*21,90+i*12,210-i*16)).save(path);paths.append(path)
        app.add_paths(paths);app.mode_var.set('Буклет');settle()
        check('twelve_pages_three_sheets_six_sides',len(booklet_pages(app.photos,app.layout))==12 and page_count(app.photos,app.layout)==6)
        check('three_numbered_auto_blanks',app.booklet_blank_summary()=='8, 9, 10')
        original=[p['token'] for p in app.booklet_leaves if p['token']]
        app.apply_booklet_blank_numbers('1,4');settle()
        check('explicit_blank_numbers',app.booklet_blank_summary()=='1, 4, 10')
        check('photos_keep_order',[p['token'] for p in app.booklet_leaves if p['token']]==original)
        uid=app.booklet_leaves[1]['token'][0];index=next(i for i,p in enumerate(app.photos) if p.uid==uid)
        app.photos[index].offset_x=.3;app.duplicate_photo(index,1);settle()
        clone=app.photos[-1];clone.offset_x=-.4
        check('independent_duplicate',clone.uid!=uid and app.photos[index].offset_x==.3 and clone.copies==1)
        check('duplicate_uses_padding',len(booklet_pages(app.photos,app.layout))==12)
        app.select_booklet_page(0);settle();slot=app._selected_instance[1]
        thumb=app._booklet_cards[3].grid_slaves(row=0,column=1)[0]
        app.begin_booklet_photo_drag(2,point(thumb))
        cell=app.layout.cells()[slot]
        app.end_library_move(SimpleNamespace(x=app.preview_origin[0]+(cell.x+cell.width/2)*app.preview_scale,
                                             y=app.preview_origin[1]+(cell.y+cell.height/2)*app.preview_scale))
        check('drop_fills_without_growth',app.booklet_leaves[0]['token']==(clone.uid,0) and app.booklet_leaves[2]['token'] is None and len(booklet_pages(app.photos,app.layout))==12)
        app.edit_booklet_page('0');app.edit_booklet_page('END');settle()
        for _ in range(3):app.refresh()
        check('empty_covers_stay_empty',app.booklet_cover_ids==[None,None])
        app.rebuild_library();settle()
        check('strict_reading_order',[f._position for f in app._booklet_cards]==['0']+list(range(10))+['END'])
        check('no_source_rows_after_END',app.library_inner.pack_slaves()==app._booklet_cards)
        app.select_booklet_page('0');settle()
        badges=[app.preview_canvas.itemcget(i,'text') for i in app.preview_canvas.find_withtag('page_badge')]
        check('explicit_cover_badges',any('0' in s and 'Пустая страница' in s for s in badges) and any('END' in s and 'Пустая страница' in s for s in badges))
        check('contrasting_badges',len(app.preview_canvas.find_withtag('page_badge_background'))==2)
        dest=output/'booklet.pdf';export_pdf(dest,app.photos,app.layout,Correction())
        reader=PdfReader(dest)
        check('six_pdf_sides',len(reader.pages)==6)
        check('no_interface_text_in_pdf',all(not p.extract_text().strip() for p in reader.pages))
        doc=pdfium.PdfDocument(dest)
        for page in range(6):
            rendered=doc[page].render(scale=25.4/72).to_pil().convert('RGB')
            preview=PreviewRenderer().prepare(app.photos,app.layout,page,Correction(),1).image
            for slot,cell in enumerate(app.layout.cells()):
                pixels=[(round(cell.x+cell.width*fx),round(cell.y+cell.height*fy)) for fx,fy in ((.2,.2),(.5,.5),(.8,.8))]
                check(f'pdf_preview_{page}_{slot}',all(max(abs(a-b) for a,b in zip(preview.getpixel(p),rendered.getpixel(p)))<=2 for p in pixels))
                if page_items(app.photos,app.layout,page)[slot][0]<0:
                    check(f'white_panel_{page}_{slot}',all(rendered.getpixel(p)==(255,255,255) for p in pixels))
            rendered.save(output/f'side-{page+1}.png')
        doc.close();report['passed']=True
    except Exception:report['error']=traceback.format_exc()
    finally:
        (output/'booklet-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if keep_open:
            app.root.title('Оттиск Фото — проверка буклета '+VERSION)
            app.select_booklet_page(3);settle()
        else:app.root.destroy()
