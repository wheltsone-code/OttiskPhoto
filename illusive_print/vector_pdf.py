"""Embed original PDF content as shared Form XObjects; raster sources stay ICC tagged."""
from pathlib import Path
import io
from pypdf import PdfReader,PdfWriter
from pypdf.generic import (ArrayObject,DecodedStreamObject,DictionaryObject,NameObject,
                          NumberObject,RectangleObject)
from .pdf_sources import pdf_page,source_key


def raster_reason(photo,correction):
    from .core import Correction,effective_correction
    if photo.pdf_page is None:return ''
    if effective_correction(photo,correction)!=Correction():
        return 'Цветокоррекция требует растрового вывода этой страницы PDF.'
    page=pdf_page(photo.path,photo.pdf_page)
    if any(a.get_object().get('/Subtype')!='/Link' for a in page.get('/Annots',[])):
        return 'Формы или аннотации этой страницы PDF требуют растрового вывода.'
    return ''


def pdf_export_notices(photos,correction):
    return [p.name+': '+reason for p in photos if p.pdf_page is not None and (reason:=raster_reason(p,correction))]


def compose(a,b):
    """a after b, using PDF column-vector affine coordinates."""
    aa,ab,ac,ad,ae,af=a;ba,bb,bc,bd,be,bf=b
    return (aa*ba+ac*bb,ab*ba+ad*bb,aa*bc+ac*bd,ab*bc+ad*bd,
            aa*be+ac*bf+ae,ab*be+ad*bf+af)


def source_box(photo,reference_box='trim'):
    page=pdf_page(photo.path,photo.pdf_page)
    return page.bleedbox if reference_box=='bleed' else page.trimbox


def vector_matrix(photo,cell,autorotate,paper_height,reference_box='trim'):
    from .core import rotation_turns,image_rect
    box=source_box(photo,reference_box)
    w,h=float(box.width),float(box.height)
    transform=(1,0,0,1,-float(box.left),-float(box.bottom))
    turns=rotation_turns((w,h),cell,photo,autorotate)
    for _ in range(turns):
        transform=compose((0,-1,1,0,0,w),transform);w,h=h,w
    placed=image_rect((w,h),cell,photo)
    mm=72/25.4;factor=placed.width*mm/w
    return compose((factor,0,0,factor,placed.x*mm,(paper_height-placed.y-placed.height)*mm),transform)


def bleed_shortfalls(photo,trim,paint,autorotate,paper_height,reference_box='trim'):
    """Missing millimetres after crop, scaling and rotation, in sheet axes."""
    a,b,c,d,e,f=vector_matrix(photo,trim,autorotate,paper_height,reference_box)
    box=pdf_page(photo.path,photo.pdf_page).bleedbox;mm=72/25.4
    corners=[((a*x+c*y+e)/mm,paper_height-(b*x+d*y+f)/mm) for x in (float(box.left),float(box.right)) for y in (float(box.bottom),float(box.top))]
    left=min(x for x,y in corners);right=max(x for x,y in corners);top=min(y for x,y in corners);bottom=max(y for x,y in corners)
    return tuple(max(0,v) for v in (left-paint.x,top-paint.y,paint.x+paint.width-right,paint.y+paint.height-bottom))


def attach_vectors(source,destination,placements,paper_height,segments=None):
    writer=PdfWriter(clone_from=PdfReader(source));forms={}
    jobs=placements.items() if hasattr(placements,'items') else placements
    for number,items in jobs:
        page=writer.pages[number];resources=page.setdefault(NameObject('/Resources'),DictionaryObject())
        xobjects=resources.setdefault(NameObject('/XObject'),DictionaryObject())
        commands=[]
        for item in items:
            photo,cell,clip,autorotate,*extra=item
            reference_box=extra[0] if extra else 'trim'
            key=(*source_key(photo.path),photo.pdf_page)
            if key not in forms:
                original=pdf_page(photo.path,photo.pdf_page)
                form=DecodedStreamObject();content=original.get_contents()
                form.set_data(content.get_data() if content is not None else b'')
                form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                             NameObject('/FormType'):NumberObject(1),NameObject('/BBox'):RectangleObject(original.bleedbox),
                             NameObject('/Resources'):original.get('/Resources',DictionaryObject()).get_object().clone(writer)})
                if '/Group' in original:form[NameObject('/Group')]=original['/Group'].clone(writer)
                name=NameObject('/OriginalPDF'+str(len(forms)))
                forms[key]=(name,writer._add_object(form.flate_encode()))
            name,ref=forms[key];xobjects[name]=ref
            matrix=vector_matrix(photo,cell,autorotate,paper_height,reference_box)
            mm=72/25.4
            commands.append('q '+f'{clip.x*mm:.9f} {(paper_height-clip.y-clip.height)*mm:.9f} {clip.width*mm:.9f} {clip.height*mm:.9f} re W n '+
                            ' '.join(f'{v:.10f}' for v in matrix)+' cm '+str(name)+' Do Q\n')
        old=page.get_contents();stream=DecodedStreamObject()
        stream.set_data((old.get_data() if old is not None else b'')+b'\n'+''.join(commands).encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream.flate_encode())
    if segments:
        mm=72/25.4
        lines_by_page=((i,segments(i)) for i in range(len(writer.pages))) if callable(segments) else segments.items()
        for number,lines in lines_by_page:
            page=writer.pages[number];old=page.get_contents();stream=DecodedStreamObject()
            command='q 0 G .283464567 w\n'+''.join(f'{x0*mm:.8f} {(paper_height-y0)*mm:.8f} m {x1*mm:.8f} {(paper_height-y1)*mm:.8f} l S\n' for x0,y0,x1,y1 in lines)+'Q\n'
            stream.set_data((old.get_data() if old is not None else b'')+command.encode('ascii'))
            page[NameObject('/Contents')]=writer._add_object(stream.flate_encode())
    writer.write(destination)


def raster_tile(photo,trim,paint,size,reference_box='trim'):
    """Render the same vector transform for preview and Windows raster printing."""
    from .core import Rect
    from reportlab.pdfgen.canvas import Canvas
    import pypdfium2 as pdfium
    mm=72/25.4
    buffer=io.BytesIO();pdf=Canvas(buffer,pagesize=(paint.width*mm,paint.height*mm));pdf.showPage();pdf.save();buffer.seek(0)
    result=io.BytesIO()
    local=Rect(trim.x-paint.x,trim.y-paint.y,trim.width,trim.height)
    attach_vectors(buffer,result,{0:[(photo,local,Rect(0,0,paint.width,paint.height),False,reference_box)]},paint.height)
    with pdfium.PdfDocument(result.getvalue()) as document:
        page=document[0]
        try:
            bitmap=page.render(scale=max(size[0]/(paint.width*mm),size[1]/(paint.height*mm)))
            try:image=bitmap.to_pil().convert('RGB')
            finally:bitmap.close()
        finally:page.close()
    if image.size!=size:
        from PIL import Image
        image=image.resize(size,Image.Resampling.LANCZOS)
    return image
