"""Repeatable acceptance checks run inside source, portable and MSIX builds."""
from dataclasses import replace
import json,sys,time,traceback
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,RectangleObject
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
import pypdfium2 as pdfium

from .core import Photo,Layout,Correction,EdgeInsets,page_count,page_items,page_labels,export_pdf,render_page,booklet_pages
from .production_geometry import side_cells,mirror_rect,spread_grid
from .metadata import VERSION


def artwork(destination):
    raw=destination.with_suffix('.raw.pdf');pdf=canvas.Canvas(str(raw),pagesize=(66*mm,46*mm))
    for index in range(9):
        pdf.setFillColorCMYK(.15,0,.08,0);pdf.rect(0,0,66*mm,46*mm,fill=1,stroke=0)
        pdf.setStrokeColorCMYK(0,0,0,1);pdf.setLineWidth(.2*mm)
        pdf.rect(3*mm,3*mm,60*mm,40*mm)
        pdf.setFillColorCMYK(0,0,0,1);pdf.setFont('Helvetica-Bold',16)
        pdf.drawCentredString(33*mm,23*mm,('FRONT' if index==0 else 'BACK' if index==1 else 'PAGE '+str(index+1)))
        pdf.setFont('Helvetica',6);pdf.drawCentredString(33*mm,17*mm,'60 x 40 mm / LONG EDGE / 100%')
        pdf.setFont('Helvetica-Bold',8);pdf.drawString(5*mm,36*mm,'TL');pdf.drawRightString(61*mm,5*mm,'BR')
        pdf.setFillColorCMYK(0,1,.5,0);pdf.circle(7*mm,7*mm,2*mm,fill=1,stroke=0)
        pdf.setFillColorCMYK(1,.4,0,0);pdf.rect(57*mm,33*mm,4*mm,4*mm,fill=1,stroke=0)
        pdf.line(13*mm,10*mm,43*mm,10*mm);pdf.line(13*mm,9*mm,13*mm,11*mm);pdf.line(43*mm,9*mm,43*mm,11*mm)
        pdf.showPage()
    pdf.save();writer=PdfWriter(clone_from=raw)
    for page in writer.pages:
        page[NameObject('/TrimBox')]=RectangleObject((3*mm,3*mm,63*mm,43*mm))
        page[NameObject('/BleedBox')]=RectangleObject((0,0,66*mm,46*mm))
    writer.write(destination);raw.unlink()


def run(app,output,dpi='100',keep_open=False):
    folder=Path(output).resolve();folder.mkdir(parents=True,exist_ok=True)
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'executable':sys.executable,'dpi':dpi,'checks':{},'passed':False}
    if sys.platform=='win32':
        import ctypes
        length=ctypes.c_uint32(0);kernel=ctypes.windll.kernel32
        result=kernel.GetCurrentPackageFullName(ctypes.byref(length),None)
        if result==122:
            buffer=ctypes.create_unicode_buffer(length.value)
            if kernel.GetCurrentPackageFullName(ctypes.byref(length),buffer)==0:report['package_identity']=buffer.value
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def settle():
        app.refresh();app.root.update();app.draw_preview();app.root.update()
    try:
        app.root.geometry('1260x860')
        source=folder/'DigitalPrint_Sources.pdf';artwork(source)
        photos=[Photo(source,pdf_page=i,mode='fit') for i in range(9)]
        front,back=photos[:2]
        layout=Layout(mode='repeat',paper_width=210,paper_height=297,print_width=60,print_height=40,margin=8,gap=6,
                      bleed=EdgeInsets(2,2,2,2),repeat_front=front.uid,repeat_back=back.uid,repeat_duplex=True,flip_edge='long',keep_positions=True)
        layout=replace(layout,repeat_quantity=layout.count+3)
        control=folder/'OttiskPhoto_Duplex_Control_A4.pdf'
        check('control_four_sides',export_pdf(control,photos,layout,Correction())==4)
        check('control_three_last_products',len(page_items(photos,layout,2))==3)
        check('reverse_positions_match',side_cells(layout,3,3)==tuple(mirror_rect(r,layout) for r in side_cells(layout,2,3)))
        pdf=PdfReader(control)
        check('control_physical_A4',all(abs(float(p.mediabox.width)/mm-210)<.001 and abs(float(p.mediabox.height)/mm-297)<.001 for p in pdf.pages))
        check('selectable_text',all(('BACK' if i%2 else 'FRONT') in p.extract_text() for i,p in enumerate(pdf.pages)))
        refs=[]
        for p in pdf.pages:
            refs.extend(ref.idnum for ref in p['/Resources']['/XObject'].values() if ref.get_object()['/Subtype']=='/Form')
        check('one_form_per_original',len(set(refs))==2)
        with pdfium.PdfDocument(control) as doc:
            errors=[]
            for i in range(4):
                preview=render_page(photos,layout,i,Correction(),2)
                p=doc[i]
                try:
                    bitmap=p.render(scale=2/mm)
                    try:rendered=bitmap.to_pil().convert('RGB')
                    finally:bitmap.close()
                finally:p.close()
                rendered=rendered.crop((0,0,preview.width,preview.height))
                errors.append(max(ImageStat.Stat(ImageChops.difference(preview,rendered)).mean))
                rendered.save(folder/f'control-side-{i+1}.png')
            report['pdf_preview_mean_error']=errors;check('control_preview_matches_pdf',max(errors)<4)
        blank=replace(layout,repeat_back=None)
        export_pdf(folder/'blank-back.pdf',photos,blank,Correction())
        blank_pdf=PdfReader(folder/'blank-back.pdf')
        check('blank_reverse_sides_retained',len(blank_pdf.pages)==4 and not blank_pdf.pages[1].extract_text().strip() and not blank_pdf.pages[3].extract_text().strip())
        for logical in (4,5,8,9):
            chosen=photos[:logical]
            booklet=Layout(mode='booklet',paper_width=320,paper_height=450,booklet_page_size=(148,210),booklet_copies=2,margin=5,gap=5,bleed=EdgeInsets(2,2,2,2),booklet_covers=(chosen[0].uid,chosen[-1].uid),booklet_sequence=tuple((p.uid,0) for p in chosen[1:-1]))
            pages=booklet_pages(chosen,booklet)
            check(f'booklet_{logical}_pads_multiple_four',len(pages)%4==0)
            check(f'booklet_{logical}_same_spread_repeated',page_labels(chosen,booklet,0)[:2]==page_labels(chosen,booklet,0)[2:])
            dest=folder/f'booklet-{logical}-two-A5-SRA3.pdf';export_pdf(dest,chosen,booklet,Correction())
            check(f'booklet_{logical}_pdf_sides',len(PdfReader(dest).pages)==page_count(chosen,booklet))
            if logical==9:
                with pdfium.PdfDocument(dest) as document:
                    errors=[]
                    for side in range(page_count(chosen,booklet)):
                        preview=render_page(chosen,booklet,side,Correction(),1)
                        p=document[side]
                        try:
                            bitmap=p.render(scale=1/mm)
                            try:rendered=bitmap.to_pil().convert('RGB').crop((0,0,preview.width,preview.height))
                            finally:bitmap.close()
                        finally:p.close()
                        errors.append(max(ImageStat.Stat(ImageChops.difference(preview,rendered)).mean))
                        rendered.save(folder/f'booklet-9-side-{side+1}.png')
                report['booklet_preview_mean_error']=errors;check('booklet_white_panels_match_pdf',max(errors)<4)
        app.choose_pdf_import=lambda path=None,count=None:list(range(count or 9))
        app.add_paths([source])
        for photo in app.photos:photo.mode='fit'
        app.mode_var.set('Тираж');app.repeat_lock_var.set(False);app.repeat_w_var.set('60');app.repeat_h_var.set('40')
        app.repeat_fill_var.set('Задать тираж');app.repeat_quantity_var.set('100');app.margin_var.set('0');app.gap_var.set('0');settle()
        check('ui_100_products_21_capacity',app.layout.count==21 and page_count(app.photos,app.layout)==5)
        check('ui_last_16',len(page_items(app.photos,app.layout,4))==16)
        app.mode_var.set('Буклет');app.booklet_method_var.set('Точный размер страницы');app.paper_var.set('SRA3');app.orientation_var.set('Книжная');app.margin_var.set('5');app.gap_var.set('5');app.booklet_copies_var.set('2');settle()
        check('ui_two_A5_on_SRA3',app.layout.booklet_page_size==(148,210) and spread_grid(app.layout)[:2]==(1,2))
        check('ui_four_page_badges',len(app.preview_canvas.find_withtag('page_badge'))==4)
        check('no_label_after_END',bool(app._booklet_cards) and app._booklet_cards[-1]._position=='END')
        blank_index=next(i for i,leaf in enumerate(app.booklet_leaves) if leaf['token'] is None)
        leaf=app.booklet_leaves.pop(blank_index);leaf['auto']=False;app.booklet_leaves.insert(0,leaf)
        app.select_booklet_page(0);settle()
        report['moved_blank_debug']={'token':app.booklet_token(0),'cards':[(f._position,[str(w.cget('text')) for w in f.winfo_children() if 'text' in w.keys()]) for f in app._booklet_cards[:3]]}
        check('moved_blank_is_page_one',app.booklet_token(0) is None and any('1 · Пустая страница' in str(w.cget('text')) for w in app._booklet_cards[1].winfo_children() if 'text' in w.keys()))
        before=len(app.booklet_leaves)+2
        target=next(i for i,leaf in enumerate(app.booklet_leaves) if i>0 and leaf['token'] is None)
        app.set_booklet_token(target,(app.photos[2].uid,0));settle()
        check('filled_blank_keeps_twelve_pages',len(app.booklet_leaves)+2==before==12 and app.booklet_token(target) is not None)
        check('edited_blank_stays_first',app.booklet_leaves[0]['token'] is None and not app.booklet_leaves[0]['auto'])
        edited=folder/'booklet-edited-two-A5-SRA3.pdf';export_pdf(edited,app.photos,app.layout,app.correction)
        with pdfium.PdfDocument(edited) as document:
            white=True
            for side in range(page_count(app.photos,app.layout)):
                p=document[side]
                try:
                    bitmap=p.render(scale=1/mm)
                    try:rendered=bitmap.to_pil().convert('RGB')
                    finally:bitmap.close()
                finally:p.close()
                for (index,photo),cell in zip(page_items(app.photos,app.layout,side),side_cells(app.layout,side,app.layout.count)):
                    if index<0:white &= min(rendered.getpixel((round(cell.x+cell.width/2),round(cell.y+cell.height/2))))>=250
        check('edited_blanks_are_white_in_pdf',white)
        check('ui_blank_labels_not_in_pdf',all('Пустая страница' not in p.extract_text() for p in PdfReader(edited).pages))
        report['control_pdf']=str(control);report['passed']=True
        app.root.lift();app.root.focus_force();app.root.update()
        def screenshot():
            from PIL import ImageGrab
            try:
                x,y=app.root.winfo_rootx(),app.root.winfo_rooty()
                ImageGrab.grab(bbox=(x,y,x+app.root.winfo_width(),y+app.root.winfo_height())).save(folder/'interface.png')
            except Exception as error:report['screenshot_error']=str(error)
        app.root.after(400,screenshot)
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        (folder/'production-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if not keep_open:app.root.after(800,app.root.destroy)
    return report
