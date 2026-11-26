"""Original PDF pages and saved PSD composites; never composite Photoshop layers."""
from functools import lru_cache
from pathlib import Path
from threading import RLock
from .color_management import to_srgb
from .image_cache import FULL_IMAGES, image_memo
from .resources import RESOURCES

_pdf_lock = RLock()
PSD_COMPATIBILITY = 'Сохраните PSD в Photoshop с включённой максимальной совместимостью или экспортируйте в PNG/TIFF'


def pdf_pages(path, prepared=False):
    import pypdfium2 as pdfium
    if not prepared:
        from .vector_import import document_pdf
        path = document_pdf(path)
    try:
        with _pdf_lock, pdfium.PdfDocument(str(path)) as document:
            return len(document)
    except Exception as error:
        raise ValueError(f'{Path(path).name}: PDF не читается или требует пароль: {error}') from error


@lru_cache(maxsize=128)
def _pdf_size(path, modified, length, index):
    from .pdf_sources import trim_size
    return trim_size(Path(path),index)


def pdf_size(path, index):
    from .vector_import import document_pdf
    path = document_pdf(path)
    stat = path.stat()
    return _pdf_size(str(path.resolve()),stat.st_mtime_ns,stat.st_size,index)


@image_memo(FULL_IMAGES,'pdf-original')
def _pdf_render(path, modified, length, index, ppi):
    import pypdfium2 as pdfium
    from .pdf_sources import display_bytes
    with _pdf_lock, pdfium.PdfDocument(display_bytes(path,modified,length,index)) as document:
        page = document[0]
        try:
            width,height=page.get_size()
            with RESOURCES.working(int(width*height*(ppi/72)**2*16)):
                bitmap = page.render(scale=ppi/72,fill_color=(255,255,255,255))
                try:
                    image = bitmap.to_pil().copy()
                finally:
                    bitmap.close()
        finally:
            page.close()
    return to_srgb(image)


def pdf_render(path, index, ppi=96):
    from .vector_import import document_pdf
    path = document_pdf(path)
    stat = path.stat()
    return _pdf_render(str(path.resolve()),stat.st_mtime_ns,stat.st_size,index,round(ppi,4))


def psd_composite(path):
    from psd_tools import PSDImage
    from psd_tools.constants import Resource
    psd = PSDImage.open(path)
    if not psd.has_preview():
        raise ValueError(PSD_COMPATIBILITY)
    image = psd.topil(apply_icc=False)
    if image is None:
        raise ValueError(PSD_COMPATIBILITY)
    profile = psd.image_resources.get_data(Resource.ICC_PROFILE)
    if profile:
        image.info['icc_profile'] = profile
    return to_srgb(image)


def parse_pages(text, count):
    result = []
    try:
        for part in text.replace('–','-').replace('—','-').split(','):
            ends = [int(v.strip()) for v in part.strip().split('-')]
            if len(ends) == 1:
                start = end = ends[0]
            elif len(ends) == 2:
                start,end = ends
            else:
                raise ValueError()
            if not 1 <= start <= end <= count:
                raise ValueError()
            for page in range(start-1,end):
                if page not in result:
                    result.append(page)
    except ValueError as error:
        raise ValueError(f'Неверный диапазон страниц. Допустимы страницы 1–{count}, например 1–3, 7.') from error
    if not result:
        raise ValueError('Выберите хотя бы одну страницу.')
    return result
