"""Testable, single-submit print lifecycle, with no Windows calls while rendering."""
from dataclasses import dataclass, replace
from pathlib import Path
import queue
import tempfile
import threading

from .core import Correction, Layout, Photo, page_count, page_items, render_page, validate_output
from .color_management import OutputProfile
from .metadata import APP_NAME
from .windows_print import PrintCancelled


@dataclass(frozen=True)
class PrintSnapshot:
    photos: tuple[Photo, ...]
    layout: Layout
    correction: Correction
    current_page: int

    @classmethod
    def capture(cls, photos, layout, correction, page):
        layout = replace(layout, driver_margins=None)
        validate_output(photos, layout)
        return cls(tuple(replace(p) for p in photos), layout, correction, page)

    def pages(self, current):
        count = page_count(self.photos, self.layout)
        if current:
            if not 0 <= self.current_page < count:
                raise ValueError("Текущий лист недоступен.")
            if self.layout.duplex:
                first=self.current_page//2*2
                return (first,first+1)
            return (self.current_page,)
        return range(count)

    def prints(self, current):
        if self.layout.mode=='repeat' and not current:
            quantity=self.layout.repeat_quantity or self.layout.count
            back=bool(self.layout.repeat_back) if self.layout.duplex else False
            return quantity*(1+back)
        return sum(sum(index>=0 for index,photo in page_items(self.photos,self.layout,page)) for page in self.pages(current))


class PrintJob:
    def __init__(self):
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.state = "idle"

    def start(self, snapshot, current, ppi, backend, printer, settings, profile: OutputProfile | None,
              allow_driver_settings=False):
        with self.lock:
            if self.state in ("preparing", "sending", "sent"):
                return False
            self.state = "preparing"
            self.cancelled.clear()
        threading.Thread(target=self._run, args=(snapshot, current, ppi, backend, printer, settings, profile, allow_driver_settings), daemon=True).start()
        return True

    def cancel(self):
        with self.lock:
            if self.state == "preparing":
                self.cancelled.set()
                return True
            return False

    def _run(self, snapshot, current, ppi, backend, printer, settings, profile, allow_driver_settings=False):
        try:
            if ppi not in (300, 600):
                raise ValueError("Выберите 300 или 600 ppi.")
            pages = snapshot.pages(current)
            if not pages:
                raise ValueError("В заказе нет листов.")
            with tempfile.TemporaryDirectory(prefix="ottisk-print-") as folder:
                paths = []
                for index, page in enumerate(pages):
                    if self.cancelled.is_set():
                        break
                    self.events.put(("progress", f"Подготовка листа {index + 1} из {len(pages)}"))
                    image = render_page(snapshot.photos, snapshot.layout, page, snapshot.correction, ppi / 25.4)
                    if profile:
                        image = profile.convert(image)  # exactly ONE output ICC transform
                    path = Path(folder) / f"{page}.bmp"
                    image.save(path)  # fast disk spool, one full page in memory
                    image.close()
                    paths.append(path)
                with self.lock:
                    cancelled = self.cancelled.is_set()
                    if cancelled:
                        self.state = "cancelled"
                if cancelled:
                    self.events.put(("cancelled", "Печать отменена. Задание не создано."))
                    return
                options = {'allow_driver_settings': True} if allow_driver_settings else {}
                job_id = backend.submit(printer, settings, paths, snapshot.layout, profile is not None,
                                        f"{APP_NAME} · {len(pages)} листов", before_start=self.commit, **options)
                self.state = "sent"
                suffix = f" · задание {job_id}" if job_id else ""
                self.events.put(("sent", "Отправлено в очередь печати" + suffix))
        except PrintCancelled:
            self.state = "cancelled"
            self.events.put(("cancelled", "Печать отменена. Задание не создано."))
        except Exception as error:
            self.state = "error"
            self.events.put(("error", str(error)))

    def commit(self):
        """Atomic cancellation boundary, immediately BEFORE native StartDoc."""
        with self.lock:
            if self.cancelled.is_set():
                return False
            self.state = "sending"
        self.events.put(("sending", "Передача в очередь Windows…"))
        return True
