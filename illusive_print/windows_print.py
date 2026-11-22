"""Windows GDI adapter. No PDF application, ShellExecute or automatic retry.

DocumentProperties returns the complete per-job DEVMODE, private bytes included.
The only spool-creating call is StartDoc in submit(), after preparation finishes.
"""
from dataclasses import dataclass
import ctypes
import math
from ctypes import wintypes
from .diagnostics import record, devmode


class PrintCancelled(Exception):
    pass

class PrinterOpenError(RuntimeError):
    pass

class PrintContextError(RuntimeError):
    pass

class PrintSubmissionError(RuntimeError):
    pass


def close_paper(actual, target):
    """Oriented physical dimensions; tolerance never changes output scale."""
    return all(math.isfinite(a) and math.isfinite(t) and a > 0 and t > 0
               and abs(a - t) <= min(3.2, .03 * t) + 1e-7
               for a, t in zip(actual, target))


@dataclass(frozen=True)
class PaperFormat:
    identifier: int
    name: str
    width: float
    height: float

    def oriented(self, target):
        short, long = sorted((self.width, self.height))
        return (long, short) if target[0] > target[1] else (short, long)


def select_paper(formats, target):
    candidates = [p for p in formats if close_paper(p.oriented(target), target)]
    def rank(p):
        differences = [abs(a - t) for a, t in zip(p.oriented(target), target)]
        return (max(differences) > .1, max(d / t for d, t in zip(differences, target)), sum(differences))
    return min(candidates, key=rank, default=None)


@dataclass(frozen=True)
class DriverPaper:
    width: float
    height: float
    scale: int = 100
    copies: int = 1
    name: str = ''
    margins: object = None
    duplex_supported: bool | None = None

    def mismatch(self, layout) -> str:
        orientation = lambda w, h: "альбомная" if w > h else "книжная"
        if layout.duplex and self.duplex_supported is False:
            return 'Драйвер не заявляет автоматическую двустороннюю печать. Проверьте ручной переворот в свойствах драйвера; для явной отправки используйте «Печатать с настройками драйвера».'
        if (not close_paper((self.width, self.height), layout.page_size)
                or self.scale != 100 or self.copies != 1):
            return (f"Макет: {layout.paper_width:g} × {layout.paper_height:g} мм, "
                    f"{orientation(layout.paper_width, layout.paper_height)}.\n"
                    f"Драйвер: {self.width:g} × {self.height:g} мм, {orientation(self.width, self.height)}, "
                    f"масштаб {self.scale}%, копий {self.copies}.\n"
                    "Вернитесь в «Свойства принтера…»: нужен формат макета, масштаб 100% и одна копия. "
                    "Макет не подгоняется.")
        return ""


def clone_devmode(source):
    import pywintypes
    result = pywintypes.DEVMODEType(source.DriverExtra)
    # Every public scalar plus the complete opaque driver extension survives.
    for field in dir(source):
        if field.startswith("_") or field in ("Clear", "DriverExtra", "DriverData", "Size", "Fields"):
            continue
        value = getattr(source, field)
        if isinstance(value, (int, str, bytes)):
            setattr(result, field, value)
    result.DriverData = source.DriverData
    result.Fields = source.Fields
    return result


class WindowsPrinter:
    def __init__(self):
        import win32print
        self.api = win32print

    def printers(self):
        return sorted({item[2] for item in self.api.EnumPrinters(2 | 4)})

    def default(self):
        try:
            return self.api.GetDefaultPrinter()
        except Exception:
            return ""

    def configure(self, name, layout):
        handle = self._open(name)
        try:
            info = self.api.GetPrinter(handle, 2)
            dm = clone_devmode(info["pDevMode"]) if info["pDevMode"] is not None else None
            if dm is None:
                raise ValueError("Драйвер не вернул параметры DEVMODE.")
            try:
                formats = self.paper_formats(name, info['pPortName'])
            except Exception as error:
                record('printer.paper_list.error', printer=name, error=repr(error))
                formats = []
            match = select_paper(formats, layout.page_size)
            if match is None:
                width,height=sorted(layout.page_size)
                dm.PaperSize=256  # DMPAPER_USER; read back the driver's accepted form.
                dm.PaperWidth,dm.PaperLength=round(width*10),round(height*10)
                dm.Orientation=2 if layout.paper_width>layout.paper_height else 1
                dm.Fields=(dm.Fields|2|4|8)&~65536
            else:
                dm.Orientation = 1 if (match.width > match.height) == (layout.paper_width > layout.paper_height) else 2
                dm.PaperSize = match.identifier
                dm.Fields = (dm.Fields | 2) & ~(4 | 8 | 65536)
            dm.Scale, dm.Copies = 100, 1
            dm.Fields |= 1 | 16 | 256  # ORIENTATION, SCALE, COPIES
            if layout.duplex:
                dm.Duplex=3 if layout.binding_edge=='short' else 2
                dm.Fields|=4096
            returned = clone_devmode(dm)
            result = self.api.DocumentProperties(0, handle, name, returned, dm, 2 | 8)
            if result != 1:
                raise ValueError(f"Драйвер отклонил параметры бумаги (код {result}).")
            record('printer.configure', printer=name, layout=layout.page_size, selected=vars(match) if match else 'custom', returned=devmode(returned))
            return returned
        finally:
            self.api.ClosePrinter(handle)

    def paper_formats(self, name, port=None):
        if port is None:
            handle = self._open(name)
            try:
                port = self.api.GetPrinter(handle, 2)['pPortName']
            finally:
                self.api.ClosePrinter(handle)
        ids = self.api.DeviceCapabilities(name, port, 2) or ()
        sizes = self.api.DeviceCapabilities(name, port, 3) or ()
        try:
            names = self.api.DeviceCapabilities(name, port, 16) or ()
        except Exception:
            names = ()
        return [PaperFormat(identifier, str(names[index]).strip('\x00 ') if index < len(names) else '',
                            size['x'] / 10, size['y'] / 10)
                for index, (identifier, size) in enumerate(zip(ids, sizes))]

    def paper_name(self, name, settings):
        try:
            return next(p.name for p in self.paper_formats(name) if p.identifier == settings.PaperSize)
        except Exception:
            return getattr(settings, 'FormName', '')

    def properties(self, hwnd, name, settings):
        handle = self._open(name)
        try:
            returned = clone_devmode(settings)
            input_settings = clone_devmode(settings)
            result = self.api.DocumentProperties(hwnd, handle, name, returned, input_settings, 2 | 4 | 8)
            if result == 2:
                record('printer.properties.cancel', printer=name, previous=devmode(settings))
                return None  # native Cancel preserves the previous job settings
            if result != 1:
                raise ValueError(f"Не удалось открыть свойства драйвера (код {result}).")
            record('printer.properties.ok', printer=name, returned=devmode(returned))
            return returned
        finally:
            self.api.ClosePrinter(handle)

    def _dc(self, name, settings):
        import win32gui
        import win32ui
        try:
            # Always a fresh DC from this job's entire DEVMODE, never defaults.
            return win32ui.CreateDCFromHandle(win32gui.CreateDC("WINSPOOL", name, settings))
        except Exception as error:
            record('printer.context.error', printer=name, error=repr(error))
            raise PrintContextError(f"Не удалось создать контекст печати: {error}") from error

    def _open(self, name):
        try:
            return self.api.OpenPrinter(name)
        except Exception as error:
            record('printer.open.error', printer=name, error=repr(error))
            raise PrinterOpenError(f"Не удалось открыть принтер: {error}") from error

    def inspect(self, name, settings):
        dc = self._dc(name, settings)
        try:
            paper = DriverPaper(dc.GetDeviceCaps(110) * 25.4 / dc.GetDeviceCaps(88),
                               dc.GetDeviceCaps(111) * 25.4 / dc.GetDeviceCaps(90),
                               settings.Scale if settings.Fields & 16 else 100,
                               settings.Copies if settings.Fields & 256 else 1,
                               self.paper_name(name, settings))
            from .core import EdgeInsets
            dx,dy=dc.GetDeviceCaps(88)/25.4,dc.GetDeviceCaps(90)/25.4
            from dataclasses import replace
            paper=replace(paper,margins=EdgeInsets(dc.GetDeviceCaps(112)/dx,dc.GetDeviceCaps(113)/dy,
                max(0,(dc.GetDeviceCaps(110)-dc.GetDeviceCaps(112)-dc.GetDeviceCaps(8))/dx),
                max(0,(dc.GetDeviceCaps(111)-dc.GetDeviceCaps(113)-dc.GetDeviceCaps(10))/dy)))
            try:
                handle=self._open(name)
                try:port=self.api.GetPrinter(handle,2)['pPortName']
                finally:self.api.ClosePrinter(handle)
                capability=self.api.DeviceCapabilities(name,port,7)
                if capability in (0,1):paper=replace(paper,duplex_supported=bool(capability))
            except Exception:pass
            record('printer.inspect', printer=name, settings=devmode(settings), physical=vars(paper),
                   printable_pixels=[dc.GetDeviceCaps(8), dc.GetDeviceCaps(10)])
            if paper.width <= 0 or paper.height <= 0:
                raise ValueError('Физический формат бумаги драйвера не удалось подтвердить.')
            return paper
        finally:
            dc.DeleteDC()

    def profile_mode(self, settings):
        return f"media={settings.MediaType};quality={settings.PrintQuality};y={settings.YResolution};color={settings.Color}"

    def submit(self, name, settings, paths, layout, app_managed, title, before_start=None, allow_driver_settings=False):
        from PIL import Image, ImageWin
        dm = clone_devmode(settings)
        # Preserve paper and opaque vendor choices. Set the ICM owner and the
        # application's 100%/single-job-copy contract, never fit the layout.
        dm.ICMMethod = 1 if app_managed else 3  # NONE / DRIVER
        dm.Scale, dm.Copies = 100, 1
        dm.Fields |= 0x00800000 | 16 | 256
        dc = self._dc(name, dm)
        started = False
        try:
            gdi = ctypes.WinDLL("gdi32", use_last_error=True)
            gdi.SetICMMode.argtypes = [wintypes.HDC, ctypes.c_int]
            gdi.SetICMMode.restype = ctypes.c_int
            # DONE_OUTSIDEDC disables WCS AND legacy halftone matching. In the
            # default mode only system matching is disabled, leaving the driver.
            if not gdi.SetICMMode(dc.GetHandleOutput(), 4 if app_managed else 1):
                raise OSError("Windows не разрешила задать режим управления цветом. Задание не создано.")
            paper = DriverPaper(dc.GetDeviceCaps(110) * 25.4 / dc.GetDeviceCaps(88),
                                dc.GetDeviceCaps(111) * 25.4 / dc.GetDeviceCaps(90),
                                dm.Scale if dm.Fields & 16 else 100, dm.Copies if dm.Fields & 256 else 1)
            record('printer.submit.context', printer=name, settings=devmode(dm), physical=vars(paper),
                   layout=layout.page_size, manual=allow_driver_settings)
            if paper.mismatch(layout) and not allow_driver_settings:
                raise ValueError(paper.mismatch(layout))
            dc.SetMapMode(1)  # MM_TEXT: physical printer pixels, never fit-to-page
            offset_x, offset_y = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
            width = round(layout.paper_width * dc.GetDeviceCaps(88) / 25.4)
            height = round(layout.paper_height * dc.GetDeviceCaps(90) / 25.4)
            if before_start and not before_start():
                raise PrintCancelled()
            try:
                job_id = dc.StartDoc(title)
            except Exception as error:
                raise PrintSubmissionError(f"Не удалось создать задание печати: {error}") from error
            started = True
            for path in paths:
                dc.StartPage()
                with Image.open(path) as image:
                    ImageWin.Dib(image).draw(dc.GetHandleOutput(),
                                           (-offset_x, -offset_y, width - offset_x, height - offset_y))
                dc.EndPage()
            dc.EndDoc()
            started = False
            return job_id
        except Exception:
            if started:
                dc.AbortDoc()
            raise
        finally:
            dc.DeleteDC()
