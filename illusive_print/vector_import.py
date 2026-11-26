"""Local, content-checked vector preparation. Originals are never rewritten."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from .disk_cache import document_cache
from .resources import RESOURCES, MiB, working_budget

VECTOR_EXTENSIONS = {'.svg', '.ai', '.eps', '.cdr'}
_serial = threading.Lock()  # PDFium and converters have substantial working sets.
_ready = {}


class ImportCancelled(Exception):
    pass


@dataclass(frozen=True)
class PreparedDocument:
    path: Path
    kind: str
    warnings: tuple = ()
    cache_hit: bool = False


def cancelled(event):
    if event is not None and event.is_set(): raise ImportCancelled()


def identify(path):
    path=Path(path).resolve();stat=path.stat()
    return _identify(str(path),stat.st_mtime_ns,stat.st_size)


@lru_cache(maxsize=256)
@working_budget(lambda path,modified,length:length*6)
def _identify(path,modified,length):
    path = Path(path)
    with path.open('rb') as stream: head = stream.read(65536)
    ext = path.suffix.lower()
    if ext == '.ai':
        if b'%PDF-' in head[:1024]: return 'ai-pdf'
        if head.startswith(b'%!PS') and re.search(br'Adobe Illustrator|Adobe_Illustrator|AI\d+_CreatorVersion', head):
            return 'ai-postscript'
        raise ValueError('AI: содержимое не является PDF или Illustrator PostScript / not a PDF-compatible or PostScript AI')
    if ext == '.eps':
        if head.startswith(b'\xc5\xd0\xd3\xc6'): return 'eps-binary'
        if head.startswith(b'%!PS') and b'EPSF-' in head[:256]: return 'eps'
        raise ValueError('EPS: неверная сигнатура / invalid content signature')
    if ext == '.cdr':
        if head.startswith(b'PK'):
            try:
                with zipfile.ZipFile(path) as archive:
                    name = next(n for n in archive.namelist() if n.lower().endswith('content/riffdata.cdr'))
                    with archive.open(name) as stream: head = stream.read(12)
            except (ValueError, StopIteration, zipfile.BadZipFile, KeyError) as error:
                raise ValueError('CDR: неизвестный контейнер / unknown container') from error
        if len(head) >= 12 and head[:4] == b'RIFF' and head[8:11] == b'CDR':
            code = chr(head[11])
            # RIFF CDR6..9 and CDRA.. encode the actual file generation.
            if code.isdigit(): version = int(code)
            elif 'A' <= code <= 'Z': version = ord(code)-ord('A')+10
            else: version = '?'
            if isinstance(version, int) and version < 6:
                raise ValueError(f'CDR {version}: неподдерживаемая старая версия / unsupported legacy version')
            return f'cdr-{version}'
        raise ValueError('CDR: неизвестная версия или сигнатура / unknown version or signature')
    if ext == '.svg':
        data = path.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('SVG: DTD/ENTITY не поддерживаются / not supported')
        try: root = ET.fromstring(data)
        except ET.ParseError as error: raise ValueError(f'SVG: {error}') from error
        if root.tag != '{http://www.w3.org/2000/svg}svg':
            raise ValueError('SVG: отсутствует корневой SVG / missing SVG root')
        for node in root.iter():
            for key, value in node.attrib.items():
                if key.split('}')[-1] == 'href' and not value.startswith(('#', 'data:')):
                    raise ValueError('SVG: встроите связанные изображения и шрифты / embed linked images and fonts')
        urls = re.findall(rb'url\(\s*[\x22\x27]?([^\)\x22\x27]+)',data,re.I)
        if re.search(rb'@import|<script', data, re.I) or any(not u.startswith((b'#',b'data:')) for u in urls):
            raise ValueError('SVG: внешние ресурсы и скрипты не поддерживаются / external resources and scripts are not supported')
        return 'svg'
    raise ValueError('Неподдерживаемый формат файла / Unsupported file format')


def module_root():
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    return base/'import-module'


def converter(kind):
    root = module_root()
    if kind.startswith(('eps', 'ai-postscript')):
        path = root/'ghostscript'/'bin'/'gswin64c.exe'
    else: path = root/'inkscape'/'bin'/'inkscape.com'
    if not path.is_file():
        raise ValueError('Отсутствует локальный модуль импорта. Поместите import-module рядом с EXE / '
                         'Local import module is missing. Place import-module beside the EXE')
    return path


def run_process(args, event=None, timeout=180):
    # Log to disk, not a PIPE: a verbose converter cannot deadlock the worker.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                cancelled(event)
                if time.monotonic()-started > timeout:
                    raise ValueError('Преобразование заняло слишком много времени / Conversion timed out')
                time.sleep(.05)
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                else: process.kill()
            process.wait()
        log.seek(0); output = log.read(256*1024).decode('utf-8', errors='replace')
        if process.returncode:
            raise ValueError('Ошибка локального преобразования / Local conversion failed: '+output[-2000:])
        return output


@lru_cache(maxsize=16)
def converter_identity(path, modified, size):
    with open(path, 'rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return (run_process([path, '--version'], timeout=20).strip(), digest)


@lru_cache(maxsize=4)
def font_environment(minute):
    roots = [Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts',
             Path(os.environ.get('LOCALAPPDATA', ''))/'Microsoft'/'Windows'/'Fonts']
    files = []
    for root in roots:
        if root.is_dir():
            for path in root.iterdir():
                try:
                    stat = path.stat(); files.append((str(path), stat.st_mtime_ns, stat.st_size))
                except OSError: pass
    return document_cache().key(sorted(files))


@lru_cache(maxsize=4)
def installed_font_names(environment):
    names=set()
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        label=winreg.EnumValue(key,i)[0]
                        names.add(re.sub(r'\s*\(.*?\)','',label).casefold())
            except OSError:pass
    return names


def missing_svg_fonts(path):
    text=Path(path).read_text('utf-8-sig')
    families=re.findall(r'font-family\s*(?:=\s*[\x22\x27]([^\x22\x27]+)|:\s*([^;\x22\x27}]+))',text,re.I)
    installed=installed_font_names(font_environment(int(time.time()//60)))
    missing=[]
    if installed:
        for pair in families:
            family=next(v for v in pair if v).split(',')[0].strip(' \x22\x27')
            if family.casefold() not in ('sans-serif','serif','monospace','cursive','fantasy','system-ui') and not any(
                family.casefold()==name or name.startswith(family.casefold()+' ') for name in installed):
                missing.append(family)
    return sorted(set(missing))


def svg_page_sizes(path):
    """Recover declared physical dimensions before Inkscape pixel rounding."""
    root=ET.parse(path).getroot()
    factors={'mm':72/25.4,'cm':72/2.54,'in':72,'pt':1,'pc':12,'px':.75,'q':72/101.6,'':.75}
    def points(value):
        match=re.fullmatch(r'\s*([\d.eE+\-]+)\s*([a-zA-Z]*)\s*',value or '')
        if not match or match[2].lower() not in factors:return None
        number=float(match[1])*factors[match[2].lower()]
        return number if 0<number<1e7 else None
    width,height=points(root.get('width')),points(root.get('height'))
    pages=root.findall('.//{http://www.inkscape.org/namespaces/inkscape}page')
    if not pages:return [(width,height)] if width and height else []
    view=[float(v) for v in re.split(r'[\s,]+',root.get('viewBox','').strip()) if v]
    sx=width/view[2] if width and len(view)==4 and view[2]>0 else .75
    sy=height/view[3] if height and len(view)==4 and view[3]>0 else .75
    return [(float(p.get('width'))*sx,float(p.get('height'))*sy) for p in pages]


@lru_cache(maxsize=128)
def source_digest(path, modified, size):
    with open(path, 'rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


@lru_cache(maxsize=128)
def checked_pdf(path,modified,length):
    from .document_sources import pdf_pages
    return pdf_pages(path,prepared=True)


@lru_cache(maxsize=8)
def module_manifest(path,modified,length):
    return Path(path).read_text('utf-8-sig')


def prepare_document(path, event=None):
    path = Path(path).resolve(); cancelled(event)
    kind = identify(path)
    if kind == 'ai-pdf':
        # Validate actual PDF parser acceptance, rather than just its header.
        stat=path.stat();checked_pdf(str(path),stat.st_mtime_ns,stat.st_size)
        return PreparedDocument(path, kind)
    exe = converter(kind); stat = exe.stat(); source = path.stat()
    identity = converter_identity(str(exe), stat.st_mtime_ns, stat.st_size)
    manifest=module_root()/'manifest.json'
    manifest_stat=manifest.stat() if manifest.is_file() else None
    key = document_cache().key(('vector-pdf-v3', kind, source_digest(str(path), source.st_mtime_ns, source.st_size),
        str(path), identity, font_environment(int(time.time()//60)),
        module_manifest(str(manifest),manifest_stat.st_mtime_ns,manifest_stat.st_size) if manifest_stat else '',
        'page=all;pdf=1.5;embed-fonts'))
    # One converter at a time; cancellation while waiting is responsive.
    while not _serial.acquire(timeout=.05): cancelled(event)
    try:
        cancelled(event)
        ready = _ready.get(key)
        if ready and ready.path.is_file():
            return PreparedDocument(ready.path,kind,ready.warnings,True)
        cached = document_cache().get(key, '.pdf')
        if cached:
            result=PreparedDocument(cached[0], kind, tuple(cached[1]), True)
            _ready[key]=result
            return result
        warnings = []
        if kind=='svg':
            missing=missing_svg_fonts(path)
            if missing:
                warnings.append('Не найдены шрифты / Missing fonts: '+', '.join(missing)+
                                '. Возможна подстановка / Substitution is possible')
        if kind.startswith('cdr'):
            warnings.append(f'{kind.upper()}: импортируются страницы, доступные Inkscape; проверьте полноту / '
                            'only pages exposed by Inkscape are imported; check completeness')
        with RESOURCES.working(max(384*MiB, source.st_size*12)), tempfile.TemporaryDirectory(prefix='ottisk-vector-') as temp:
            output = Path(temp)/'document.pdf'
            if kind.startswith(('eps', 'ai-postscript')):
                args = [exe, '-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.7',
                        '-dEmbedAllFonts=true', '-dSubsetFonts=true', '-dAutoRotatePages=/None',
                        '-sOutputFile='+str(output)]
                with path.open('rb') as source_stream: eps_header=b'EPSF-' in source_stream.read(256)
                if kind.startswith('eps') or eps_header: args.append('-dEPSCrop')
                args += ['-f', path]
            else:
                args = [exe, path, '--export-area-page', '--export-page=all', '--export-type=pdf',
                        '--export-pdf-version=1.5', '--export-filename='+str(output)]
            log = run_process(args, event)
            cancelled(event)
            # Inkscape 1.4 emits one PDF per exposed page when page=all.
            # Reassemble the page objects without rasterising or resizing them.
            if not output.is_file():
                parts=sorted(Path(temp).glob('document_p*.pdf'),key=lambda p:int(re.search(r'_p(\d+)\.pdf$',p.name)[1]))
                if parts:
                    from pypdf import PdfWriter
                    writer=PdfWriter()
                    for part in parts:
                        cancelled(event);writer.append(part)
                    if kind=='svg':
                        dimensions=svg_page_sizes(path)
                        if len(dimensions)==len(writer.pages):
                            for page,(w,h) in zip(writer.pages,dimensions):
                                page.scale_to(w,h)
                    writer.write(output);writer.close()
            if not output.is_file():
                raise ValueError('Конвертер не создал PDF; формат или версия не поддерживается / '
                                 'Converter produced no PDF; unsupported format or version')
            from .document_sources import pdf_pages
            if pdf_pages(output, prepared=True) < 1: raise ValueError('Пустой документ / Empty document')
            if re.search(r'substitut|warning|error|font.*not found|cannot find.*font', log, re.I):
                warnings.append('Предупреждение конвертера / Converter warning: '+log[-2500:])
            # Font substitution may be silent; never claim font equivalence.
            if kind != 'ai-pdf':
                warnings.append('Проверьте шрифты макета: конвертер может заменить отсутствующие гарнитуры / '
                                'Check document fonts: the converter may substitute missing families')
            stat_after = path.stat()
            if (stat_after.st_mtime_ns, stat_after.st_size) != (source.st_mtime_ns, source.st_size):
                raise ValueError('Исходник изменился во время импорта / Source changed during import')
            result = document_cache().publish(key, '.pdf', output, warnings)
            result=PreparedDocument(result, kind, tuple(warnings))
            _ready[key]=result
            return result
    finally: _serial.release()


def document_pdf(path):
    path = Path(path)
    return prepare_document(path).path if path.suffix.lower() in VECTOR_EXTENSIONS else path
