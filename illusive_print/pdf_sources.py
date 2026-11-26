"""Physical PDF page boxes, normalised rotation and UserUnit, without rasterising."""
from copy import copy
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,NumberObject,RectangleObject
from .image_cache import FULL_IMAGES, object_memo


def source_key(path):
    from .vector_import import document_pdf
    path=document_pdf(path)
    path=Path(path);stat=path.stat()
    return str(path.resolve()),stat.st_mtime_ns,stat.st_size


@object_memo(FULL_IMAGES,'pdf-parser',lambda args,value:args[2]*3+8192)
def reader(path,modified,length):
    return PdfReader(path)


@object_memo(FULL_IMAGES,'pdf-normalized',lambda args,value:args[2]*3+8192)
def normalized_page(path,modified,length,index):
    owner=PdfWriter()
    page=owner.add_page(reader(path,modified,length).pages[index])
    # Materialise fallbacks before rotation so all boxes undergo the same CTM.
    page.trimbox=RectangleObject(page.get('/TrimBox',page.get('/CropBox',page.mediabox)))
    page.bleedbox=RectangleObject(page.get('/BleedBox',page.get('/CropBox',page.mediabox)))
    if page.rotation:page.transfer_rotation_to_content()
    unit=float(page.get('/UserUnit',1))
    if unit<=0:raise ValueError('Некорректный UserUnit страницы PDF.')
    if unit!=1:page.scale_by(unit)
    page[NameObject('/UserUnit')]=NumberObject(1)
    return page


def pdf_page(path,index):
    return normalized_page(*source_key(path),index)


def trim_size(path,index):
    box=pdf_page(path,index).trimbox
    return float(box.width)*25.4/72,float(box.height)*25.4/72


@object_memo(FULL_IMAGES,'pdf-display',lambda args,value:len(value)+1024)
def display_bytes(path,modified,length,index):
    page=copy(normalized_page(path,modified,length,index))
    page.mediabox=RectangleObject(page.trimbox);page.cropbox=RectangleObject(page.trimbox)
    writer=PdfWriter();writer.add_page(page)
    result=BytesIO();writer.write(result)
    return result.getvalue()


def available_bleeds(path,index):
    page=pdf_page(path,index);t=page.trimbox;b=page.bleedbox
    return tuple(max(0,float(value)*25.4/72) for value in (t.left-b.left,b.top-t.top,b.right-t.right,t.bottom-b.bottom))
