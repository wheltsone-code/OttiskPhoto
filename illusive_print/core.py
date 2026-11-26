"""Shared millimetre geometry for the Tk preview and ReportLab PDF.

Coordinates start at the top left. Only the PDF adapter reverses the Y axis.
Offsets are fractions of available movement, in [-1, 1]; zero is centred.
"""

from __future__ import annotations

from dataclasses import dataclass, replace, field
from uuid import uuid4
from functools import lru_cache
import math
import os
from pathlib import Path
import tempfile
import shutil
from typing import Literal

from PIL import Image, ImageDraw, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from .color import Curve, IDENTITY, curve_lut, vibrance, temperature_tint, teal_orange
from .color_management import to_srgb, srgb_bytes
from .metadata import APP_NAME, VERSION
from .diagnostics import record
from .image_cache import FULL_IMAGES, PREVIEW_IMAGES, image_memo
from .resources import RESOURCES, working_budget


SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf", ".psd", ".svg", ".ai", ".eps", ".cdr"}
PAPERS = {"10 × 15 см": (100.0, 150.0), "13 × 18 см": (130.0, 180.0),
          "15 × 21 см": (150.0, 210.0), "A4": (210.0, 297.0), "A3": (297.0, 420.0), "US Letter": (215.9, 279.4),
          "5 × 7″": (127.0, 177.8), "SRA3": (320.0,450.0), "A3+": (329.0,483.0)}
PRINT_SIZES = {
    "100 × 150 мм": (100.0, 150.0),
    "130 × 180 мм": (130.0, 180.0),
    "150 × 210 мм": (150.0, 210.0),
    "A4 · 210 × 297 мм": (210.0, 297.0),
    "4 × 6″": (101.6, 152.4),
    "5 × 7″": (127.0, 177.8),
    "8 × 10″": (203.2, 254.0),
}


class CutGeometryError(ValueError):
    """The sheet is usable, but an active knife/contour inset is invalid."""


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


@dataclass(frozen=True)
class CardTemplate:
    width: float
    height: float
    window_width: float
    window_height: float
    top: float
    left: float

    def validate(self):
        if any(not math.isfinite(v) or not 1 <= v <= 2000 for v in
               (self.width, self.height, self.window_width, self.window_height)):
            raise ValueError("Размеры карточки и окна должны быть от 1 до 2000 мм.")
        if any(not math.isfinite(v) or v < 0 for v in (self.top, self.left)):
            raise ValueError("Отступы окна должны быть неотрицательными.")
        if (self.left + self.window_width > self.width + 1e-8
                or self.top + self.window_height > self.height + 1e-8):
            raise ValueError("Окно выходит за пределы карточки. Уменьшите окно или отступы сверху и слева.")


# Manufacturer card/window dimensions; top offsets are our template settings.
CARD_TEMPLATES = {
    "Polaroid 600 / SX-70 / i-Type": CardTemplate(88.47, 107.52, 78.94, 76.81, 4.8, (88.47 - 78.94) / 2),
    "Instax Mini": CardTemplate(54, 86, 46, 62, 4, 4),
    "Instax Square": CardTemplate(72, 86, 62, 62, 5, 5),
    "Instax Wide": CardTemplate(108, 86, 99, 62, 5, 4.5),
}


@dataclass
class Photo:
    path: Path
    mode: Literal["fill", "fit"] = "fill"
    offset_x: float = 0.0
    offset_y: float = 0.0
    copies: int = 1
    rotation: int = 0  # Clockwise quarter-turns, added AFTER automatic rotation.
    curve: Curve | None = None
    zoom: float = 1.0  # Individual crop magnification; never changes the print area.
    correction: Correction | None = None
    pdf_page: int | None = None
    uid: str = field(default_factory=lambda: uuid4().hex)
    flip_x: bool = False  # Axes of the oriented image, after auto/manual rotation.
    flip_y: bool = False

    @property
    def name(self):
        return self.path.name + (f' · стр. {self.pdf_page + 1}' if self.pdf_page is not None else '')

    def __post_init__(self) -> None:
        if type(self.copies) is not int or self.copies < 1:
            raise ValueError("Количество копий должно быть целым числом не меньше 1.")

    def rotate_clockwise(self) -> None:
        self.rotation = (self.rotation + 1) % 4
        self.flip_x, self.flip_y = self.flip_y, self.flip_x

    def reflect(self, horizontal=True):
        if horizontal:
            self.flip_x = not self.flip_x
            self.offset_x = -self.offset_x
        else:
            self.flip_y = not self.flip_y
            self.offset_y = -self.offset_y

    def set_mode(self, mode: Literal["fill", "fit"]) -> None:
        self.mode = mode

    def reset_frame(self) -> None:
        self.offset_x = self.offset_y = 0.0
        self.rotation = 0
        self.zoom = 1.0
        self.flip_x = self.flip_y = False

    def move(self, dx: float, dy: float) -> None:
        self.offset_x = max(-1.0, min(1.0, round(self.offset_x + dx, 6)))
        self.offset_y = max(-1.0, min(1.0, round(self.offset_y + dy, 6)))


def set_all_modes(photos: list[Photo], mode: Literal["fill", "fit"]) -> None:
    for photo in photos:
        photo.set_mode(mode)


@dataclass(frozen=True)
class Correction:
    vibrance: float = 0.0
    gamma: float = 1.0
    curve: Curve = IDENTITY
    temperature: float = 0.0
    tint: float = 0.0
    teal_orange: str = "none"

    def __post_init__(self) -> None:
        if not math.isfinite(self.vibrance) or not -1 <= self.vibrance <= 1:
            raise ValueError("Сочность должна быть от −100 до +100.")
        if not math.isfinite(self.gamma) or not .5 <= self.gamma <= 2:
            raise ValueError("Gamma должна быть от 0,50 до 2,00.")
        if any(not math.isfinite(v) or not -1 <= v <= 1 for v in (self.temperature, self.tint)):
            raise ValueError("Температура и оттенок должны быть от −100 до +100.")
        if self.teal_orange not in ("none", "a_to_b", "b_to_a"):
            raise ValueError("Неизвестный эффект Lab.")
        curve_lut(self.curve)


@dataclass(frozen=True)
class EdgeInsets:
    """Millimetres in paper coordinates, after the driver applies orientation."""
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    def values(self) -> tuple[float, float, float, float]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class Layout:
    mode: Literal["cells", "exact", "postcard", "booklet", "repeat"] = "cells"
    paper_width: float = 210.0
    paper_height: float = 297.0
    per_sheet: int = 2
    margin: float | None = None
    gap: float = 0.0
    print_width: float = 100.0
    print_height: float = 150.0
    driver_margins: EdgeInsets | None = None
    autorotate: bool = True
    align_x: Literal["left", "center", "right"] = "center"
    align_y: Literal["top", "center", "bottom"] = "center"
    keep_positions: bool = False
    placement: Literal["auto", "beside", "stack"] = "auto"
    card: CardTemplate | None = None
    trim_mode: Literal["none", "lines", "marks", "both"] = "none"
    trim_inset: float = 0.0
    mark_inset: float = 2.0
    line_inset: float = 0.0
    order: tuple[tuple[str, int], ...] = ()
    panels: tuple[str | None, ...] = (None, None, None, None)
    booklet_covers: tuple[str | None, str | None] | None = None
    booklet_interiors: tuple[str, ...] | None = None
    booklet_sequence: tuple[tuple[str, int] | None, ...] | None = None
    center_line: str = "none"
    fold_marks: str = "none"
    fold_side: str = "both"
    bleed: EdgeInsets = field(default_factory=lambda:EdgeInsets(0,0,0,0))
    repeat_front: str | None = None
    repeat_back: str | None = None
    repeat_duplex: bool = False
    repeat_quantity: int | None = None
    booklet_page_size: tuple[float,float] | None = None
    booklet_copies: int = 1
    flip_edge: str = 'auto'
    paper_id: str | None = None

    @property
    def duplex(self):
        return self.mode in ("postcard", "booklet") or (self.mode=='repeat' and self.repeat_duplex)

    @property
    def effective_trim_inset(self):
        return self.mark_inset if self.trim_mode=='both' else self.trim_inset if self.trim_mode!='none' else 0

    @property
    def production(self):
        # Enabling a knife overlay must not select a different PDF placement
        # path. All ordinary N-Up layouts use the same geometry as repeat.
        return self.trim_mode=='both' or self.mode=='repeat' or (self.mode=='exact' and not self.card) or (self.mode=='booklet' and self.booklet_page_size is not None) or any(self.bleed.values())

    @property
    def binding_edge(self):
        from .production_geometry import binding_edge
        return binding_edge(self)

    def output_segments(self, page, limit=None):
        if self.production:
            from .production_geometry import output_segments
            return output_segments(self,page,limit)
        result = list(self.cut_segments(limit))
        w,h,m = self.paper_width,self.paper_height,self.margin
        if self.center_line == "vertical": result.append((w/2,m,w/2,h-m))
        if self.center_line == "horizontal": result.append((m,h/2,w-m,h/2))
        active = self.fold_side == "both" or self.fold_side == ("back" if page%2 else "front")
        if self.duplex and active:
            if self.fold_marks == "line": result.append((w/2,m,w/2,h-m))
            if self.fold_marks == "ticks":
                result.extend(((w/2,m,w/2,min(h/2,m+4)),(w/2,max(h/2,h-m-4),w/2,h-m)))
        return merge_segments(result)


    def __post_init__(self) -> None:
        if self.margin is None:
            object.__setattr__(self, "margin", 3.0 if self.mode == "exact" else 0.0)

    @property
    def page_size(self) -> tuple[float, float]:
        return self.paper_width, self.paper_height

    @property
    def count(self) -> int:
        if self.mode=='booklet':return 2*self.booklet_copies
        if self.mode=='postcard':return 2
        if self.mode in ("exact",'repeat'):
            cols, rows, _, _ = self.exact_grid()
            return cols * rows
        return self.per_sheet

    @property
    def effective_margins(self) -> EdgeInsets:
        minimum = self.margin if self.margin is not None else 0.0
        # Layout is independent of the driver. Exact output uses explicit user
        # margins, never printable-area fitting or inferred driver margins.
        return EdgeInsets(minimum, minimum, minimum, minimum)

    def exact_grids(self) -> tuple[tuple[int, int, float, float], ...]:
        """The two existing uniform orientations; sizes remain millimetres."""
        edges = self.effective_margins
        usable_w = self.paper_width - edges.left - edges.right
        usable_h = self.paper_height - edges.top - edges.bottom
        candidates = []
        for width, height in ((self.print_width, self.print_height), (self.print_height, self.print_width)):
            turned=(width,height)!=(self.print_width,self.print_height)
            left,top,right,bottom=self.bleed.values()
            if turned:left,top,right,bottom=bottom,left,top,right
            cols = max(0, math.floor((usable_w + self.gap + 1e-8) / (width+left+right + self.gap)))
            rows = max(0, math.floor((usable_h + self.gap + 1e-8) / (height+top+bottom + self.gap)))
            grid = (cols, rows, width, height)
            if grid not in candidates:
                candidates.append(grid)
        return tuple(candidates)

    def placement_choices(self) -> bool:
        valid = [g for g in self.exact_grids() if g[0] * g[1]]
        return (len(valid) == 2 and max(valid,key=lambda g:(g[0],-g[2])) !=
                max(valid,key=lambda g:(g[1],-g[3])))

    def exact_grid(self) -> tuple[int, int, float, float]:
        """Compare full rectangular grids, including rotating EVERY frame 90°.

        A tie uses the shorter occupied height. No mixed packing/scaling.
        """
        candidates = self.exact_grids()
        valid = [grid for grid in candidates if grid[0] * grid[1]]
        if len(valid) == 2 and self.placement != "auto":
            if self.placement == "beside":
                return max(valid, key=lambda g: (g[0], -g[2]))
            return max(valid, key=lambda g: (g[1], -g[3]))
        return max(candidates, key=lambda grid: (grid[0] * grid[1],
                   -(grid[1] * grid[3] + max(0, grid[1] - 1) * self.gap)))

    def capacity_grid(self) -> tuple[int, int]:
        cols, rows, _, _ = self.exact_grid()
        return cols, rows

    def available_counts(self) -> tuple[int, ...]:
        if self.mode == "cells":
            return (1, 2, 4, 6, 9)
        return (self.count,) if self.count else ()

    def validate(self) -> None:
        assert self.margin is not None  # __post_init__ resolves the mode default.
        for value in (self.paper_width, self.paper_height, self.print_width, self.print_height):
            if not math.isfinite(value) or not 1 <= value <= 2000:
                raise ValueError("Размеры должны быть от 1 до 2000 мм.")
        if any(not math.isfinite(v) or v < 0 for v in (self.margin, self.gap)):
            raise ValueError("Поля и промежуток должны быть неотрицательными.")
        if self.driver_margins and any(not math.isfinite(v) or v < 0 for v in self.driver_margins.values()):
            raise ValueError("Некорректные непечатаемые поля принтера.")
        if self.mode not in ("cells", "exact", "postcard", "booklet",'repeat'):
            raise ValueError("Неизвестная раскладка.")
        if self.center_line not in ("none", "vertical", "horizontal") or self.fold_marks not in ("none", "ticks", "line") or self.fold_side not in ("front", "back", "both"):
            raise ValueError("Неизвестные метки листа.")
        if self.mode in ('postcard','booklet') and self.booklet_page_size is None and (self.paper_width <= self.paper_height or 2*self.margin >= min(self.paper_width/2,self.paper_height)):
            raise ValueError("Для сгиба нужен альбомный лист и допустимые поля.")
        if self.card:
            self.card.validate()
            if self.mode != "exact" or (self.print_width, self.print_height) != (self.card.width, self.card.height):
                raise ValueError("Раскладка карточек должна использовать их внешний размер.")
        if self.trim_mode not in ("none", "lines", "marks", "both"):
            raise ValueError("Неизвестный режим подрезки.")
        if self.trim_mode != "none":
            insets=((self.mark_inset,'чистовой рез'),(self.line_inset,'вспомогательный контур')) if self.trim_mode=='both' else ((self.trim_inset,'рез'),)
            width,height=(2*self.booklet_page_size[0],self.booklet_page_size[1]) if self.mode=='booklet' and self.booklet_page_size else (self.print_width,self.print_height)
            if self.mode in ('booklet','postcard') and not self.booklet_page_size:
                width,height=self.paper_width/2-2*self.margin,self.paper_height-2*self.margin
            for inset,kind in insets:
                if not math.isfinite(inset) or inset<0:
                    raise CutGeometryError(f'Отступ ({kind}) должен быть конечным неотрицательным числом.')
                check_width,check_height=width,height
                if self.trim_mode=='both' and kind=='вспомогательный контур':
                    check_width+=self.bleed.left+self.bleed.right
                    check_height+=self.bleed.top+self.bleed.bottom
                    if self.mode=='booklet' and not self.booklet_page_size:
                        check_width=width+min(self.bleed.left,self.bleed.right)
                if min(check_width,check_height)<=2*inset:
                    raise CutGeometryError(f'Схлопывается {kind}: исходный размер {width:g} × {height:g} мм, отступ {inset:g} мм. Уменьшите отступ.')
        if (self.align_x not in ("left", "center", "right") or self.align_y not in ("top", "center", "bottom")
                or self.placement not in ("auto", "beside", "stack")):
            raise ValueError("Неизвестное выравнивание или вариант размещения.")
        if self.per_sheet < 1 or not isinstance(self.per_sheet, int):
            raise ValueError("Укажите целое число фото на листе.")
        if self.mode == "cells" and self.per_sheet not in self.available_counts():
            raise ValueError("Для ячеек выберите 1, 2, 4, 6 или 9 фото.")
        if self.flip_edge not in ('auto','short','long') or any(not math.isfinite(v) or v<0 or v>1000 for v in self.bleed.values()):
            raise ValueError('Некорректные вылеты или край переворота.')
        if self.mode=='repeat' and self.repeat_quantity is not None and (type(self.repeat_quantity) is not int or self.repeat_quantity<1):
            raise ValueError('Тираж должен быть целым положительным числом изделий.')
        if self.mode=='booklet' and self.booklet_page_size is not None:
            from .production_geometry import spread_grid
            if any(not math.isfinite(v) or not 1<=v<=2000 for v in self.booklet_page_size):raise ValueError('Размер страницы должен быть от 1 до 2000 мм.')
            capacity=spread_grid(self)[0]*spread_grid(self)[1]
            if type(self.booklet_copies) is not int or not 1<=self.booklet_copies<=capacity:
                w,h=self.booklet_page_size
                raise ValueError(f'Разворот {2*w:g} × {h:g} мм с вылетами и зазором: доступно экземпляров {capacity}. Область листа: {self.paper_width-2*self.margin:g} × {self.paper_height-2*self.margin:g} мм. Выберите другой лист или уменьшите физические параметры.')
        elif self.mode=='booklet' and self.booklet_copies!=1:
            raise ValueError('Для повторения разворотов выберите точный размер страницы.')
        if self.mode in ("exact",'repeat'):
            if self.count == 0:
                edges = self.effective_margins
                width = self.paper_width - edges.left - edges.right
                height = self.paper_height - edges.top - edges.bottom
                raise ValueError(f"Размер фото {self.print_width:g} × {self.print_height:g} мм не помещается даже с поворотом. "
                                 f"Доступная область: {max(0, width):g} × {max(0, height):g} мм. "
                                 "Выберите бумагу больше или уменьшите размер фото.")

    def cells(self, limit: int | None = None) -> tuple[Rect, ...]:
        self.validate()
        if self.mode=='booklet' and self.booklet_page_size is not None:
            from .production_geometry import side_cells
            return side_cells(self,0,limit)
        if self.mode in ('postcard','booklet'):
            w,h,m=self.paper_width,self.paper_height,self.margin
            return (Rect(m,m,w/2-2*m,h-2*m), Rect(w/2+m,m,w/2-2*m,h-2*m))
        edges = self.effective_margins
        usable_w = self.paper_width - edges.left - edges.right
        usable_h = self.paper_height - edges.top - edges.bottom
        count = self.count if limit is None else min(self.count, max(0, limit))
        if self.mode == "cells":
            landscape = self.paper_width > self.paper_height
            cols, rows = {
                1: (1, 1),
                2: (2, 1) if landscape else (1, 2),
                4: (2, 2),
                6: (3, 2) if landscape else (2, 3),
                9: (3, 3),
            }[self.per_sheet]
            width = (usable_w - (cols - 1) * self.gap) / cols
            height = (usable_h - (rows - 1) * self.gap) / rows
            if width <= 0 or height <= 0:
                raise ValueError("Поля и промежутки занимают всю рабочую область листа.")
            x0, y0 = edges.left, edges.top
        else:
            cols, rows, width, height = self.exact_grid()
            left,top,right,bottom=self.bleed.values()
            if (width,height)!=(self.print_width,self.print_height):left,top,right,bottom=bottom,left,top,right
            outer_w,outer_h=width+left+right,height+top+bottom
            used_cols = cols if self.keep_positions else min(cols, count)
            used_rows = rows if self.keep_positions else math.ceil(count / cols)
            group_w = used_cols * outer_w + max(0, used_cols - 1) * self.gap
            group_h = used_rows * outer_h + max(0, used_rows - 1) * self.gap
            x0 = edges.left + (usable_w - group_w) * {"left": 0, "center": .5, "right": 1}[self.align_x]
            y0 = edges.top + (usable_h - group_h) * {"top": 0, "center": .5, "bottom": 1}[self.align_y]
            x0+=left;y0+=top
            step_w,step_h=outer_w+self.gap,outer_h+self.gap
        if self.mode=='cells':step_w,step_h=width+self.gap,height+self.gap
        return tuple(
            Rect(x0 + (index % cols) * step_w, y0 + (index // cols) * step_h, width, height)
            for index in range(count)
        )

    @property
    def card_turned(self) -> bool:
        return bool(self.card and not math.isclose(self.card.width, self.card.height)
                    and math.isclose(self.exact_grid()[2], self.card.height))

    def photo_area(self, cell: Rect) -> Rect:
        if not self.card:
            return cell
        c = self.card
        if self.card_turned:
            return Rect(cell.x + c.height - c.top - c.window_height, cell.y + c.left,
                        c.window_height, c.window_width)
        return Rect(cell.x + c.left, cell.y + c.top, c.window_width, c.window_height)

    def cut_rects(self, limit: int | None = None) -> tuple[Rect, ...]:
        if self.mode == "cells" or self.trim_mode == "none":
            return ()
        inset = self.effective_trim_inset
        return tuple(Rect(c.x + inset, c.y + inset, c.width - 2 * inset, c.height - 2 * inset)
                     for c in self.cells(limit))

    def cut_segments(self, limit: int | None = None) -> tuple[tuple[float, float, float, float], ...]:
        if self.trim_mode=='both':
            from .production_geometry import cut_output_segments
            return cut_output_segments(self,0,limit)
        rects = self.cut_rects(limit)
        if not rects:
            return ()
        edges = []
        for r in rects:
            edges.extend(((r.x, r.y, r.x + r.width, r.y), (r.x, r.y + r.height, r.x + r.width, r.y + r.height),
                          (r.x, r.y, r.x, r.y + r.height), (r.x + r.width, r.y, r.x + r.width, r.y + r.height)))
        if self.trim_mode == "lines":
            return merge_segments(edges)
        cells = self.cells(limit)
        full_card = (self.card is not None and len(cells) == 1 and abs(cells[0].x) < 1e-8
                     and abs(cells[0].y) < 1e-8 and abs(cells[0].width - self.paper_width) < 1e-8
                     and abs(cells[0].height - self.paper_height) < 1e-8)
        if full_card:
            r = rects[0]
            marks = []
            for x in (r.x, r.x + r.width):
                marks.extend(((x, max(0, r.y - 2.8), x, min(self.paper_height, r.y + 1)),
                              (x, max(0, r.y + r.height - 1), x, min(self.paper_height, r.y + r.height + 2.8))))
            for y in (r.y, r.y + r.height):
                marks.extend(((max(0, r.x - 2.8), y, min(self.paper_width, r.x + 1), y),
                              (max(0, r.x + r.width - 1), y, min(self.paper_width, r.x + r.width + 2.8), y)))
            return merge_segments(marks)
        # Guillotine marks share the infinite cut lines. Find waste intervals
        # over the WHOLE page, excluding every finished print, including stroke.
        marks = []
        for vertical in (False, True):
            coordinates = sorted({round(edge[0] if vertical else edge[1], 8) for edge in edges
                                  if (edge[0] == edge[2]) == vertical})
            extent = self.paper_height if vertical else self.paper_width
            for coordinate in coordinates:
                blocked = []
                for r in rects:
                    across, across_size = (r.x, r.width) if vertical else (r.y, r.height)
                    start, length = (r.y, r.height) if vertical else (r.x, r.width)
                    if across - .05 <= coordinate <= across + across_size + .05:
                        blocked.append((max(.05, start - .4), min(extent - .05, start + length + .4)))
                free, cursor = [], .05
                for start, end in sorted(blocked):
                    if start > cursor:
                        free.append((cursor, start))
                    cursor = max(cursor, end)
                if cursor < extent - .05:
                    free.append((cursor, extent - .05))
                candidates = []
                for start, end in free:
                    if end - start >= 2 - 1e-8:
                        candidates.append((start, start + 2))
                        if end - start >= 4.4:
                            candidates.append((end - 2, end))
                if len(candidates) < 2 or candidates[-1][0] < candidates[0][1] + .1:
                    raise ValueError("Полный комплект меток реза не помещается вне готовых отпечатков. "
                                     "Увеличьте поля листа или зазор; размеры и раскладка не изменены.")
                # Prefer marks next to the group when exterior margins exist.
                first, last = candidates[0], candidates[-1]
                if len(free) >= 2 and free[0][1] - free[0][0] >= 2 and free[-1][1] - free[-1][0] >= 2:
                    first = (free[0][1] - 2, free[0][1])
                    last = (free[-1][0], free[-1][0] + 2)
                for start, end in (first, last):
                    marks.append((coordinate, start, coordinate, end) if vertical else (start, coordinate, end, coordinate))
        extended = []
        for x0, y0, x1, y1 in marks:
            vertical = x0 == x1
            coordinate = x0 if vertical else y0
            middle = (y0 + y1) / 2 if vertical else (x0 + x1) / 2
            boundaries = []
            for r in rects:
                across, size = (r.x, r.width) if vertical else (r.y, r.height)
                start, length = (r.y, r.height) if vertical else (r.x, r.width)
                if across - .05 <= coordinate <= across + size + .05:
                    boundaries.extend(((start, 1), (start + length, -1)))
            boundary, inward = min(boundaries, key=lambda b: abs(b[0] - middle))
            a, b = sorted((boundary - 2.8 * inward, boundary + 1 * inward))
            extent = self.paper_height if vertical else self.paper_width
            if a < .05 or b > extent - .05:
                raise ValueError("Удлинённые метки не помещаются. Увеличьте поля листа или зазор.")
            for r in rects:
                across, size = (r.x, r.width) if vertical else (r.y, r.height)
                start, length = (r.y, r.height) if vertical else (r.x, r.width)
                if across - .049 <= coordinate <= across + size + .049:
                    overlap = min(b, start + length) - max(a, start)
                    if overlap > 1.00001:
                        raise ValueError("Удлинённые метки задевают соседний отпечаток. Увеличьте поля листа или зазор.")
            extended.append((coordinate, a, coordinate, b) if vertical else (a, coordinate, b, coordinate))
        return merge_segments(extended)


def merge_segments(segments):
    """Union collinear closed intervals, so shared contours are drawn once."""
    groups = {}
    for x0, y0, x1, y1 in segments:
        vertical = abs(x0 - x1) < 1e-8
        key = vertical, round(x0 if vertical else y0, 8)
        groups.setdefault(key, []).append((min(y0, y1), max(y0, y1)) if vertical else (min(x0, x1), max(x0, x1)))
    result = []
    for (vertical, coordinate), spans in groups.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + 1e-7:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        result.extend((coordinate, a, coordinate, b) if vertical else (a, coordinate, b, coordinate) for a, b in merged)
    return tuple(result)


def validate_output(photos, layout):
    layout.validate()
    if layout.production:
        from .production_geometry import validate_production
        validate_production(photos,layout)
        return
    if layout.trim_mode != "none":
        for page in range(page_count(photos, layout)):
            layout.cut_segments(len(page_items(photos, layout, page)))


def photo_slot(photo: Photo, cell: Rect, layout: Layout) -> tuple[Photo, Rect, bool]:
    """Rotate the card AND the native-window crop, including its offset axes."""
    area = layout.photo_area(cell)
    if layout.mode=='booklet' and layout.booklet_page_size is not None:
        from .production_geometry import spread_grid
        if spread_grid(layout)[4]:
            native=Rect(0,0,*layout.booklet_page_size)
            info=source_size(photo);turns=rotation_turns((info.width_px,info.height_px),native,photo,layout.autorotate)
            return replace(photo,rotation=(turns+1)%4,offset_x=-photo.offset_y,offset_y=photo.offset_x,flip_x=photo.flip_y,flip_y=photo.flip_x),area,False
    if not layout.card:
        return photo, area, layout.autorotate
    c = layout.card
    native = Rect(0, 0, c.window_width, c.window_height)
    info = source_size(photo)
    turns = rotation_turns((info.width_px, info.height_px), native, photo, layout.autorotate)
    if layout.card_turned:
        return replace(photo, rotation=(turns + 1) % 4, offset_x=-photo.offset_y, offset_y=photo.offset_x,flip_x=photo.flip_y,flip_y=photo.flip_x), area, False
    return replace(photo, rotation=turns), area, False


def print_count(photos: list[Photo]) -> int:
    if any(type(photo.copies) is not int or photo.copies < 1 for photo in photos):
        raise ValueError("Количество копий должно быть целым числом не меньше 1.")
    return sum(photo.copies for photo in photos)


def first_print_index(photos: list[Photo], photo_index: int) -> int:
    return sum(photo.copies for photo in photos[:photo_index])


def page_count(photos: list[Photo], layout: Layout) -> int:
    layout.validate()
    if layout.mode=='repeat':
        quantity=layout.repeat_quantity or layout.count
        return ((quantity+layout.count-1)//layout.count)*(2 if layout.duplex else 1)
    if layout.mode == "postcard": return 2
    if layout.mode == "booklet": return len(booklet_pages(photos,layout))//2
    return (print_count(photos) + layout.count - 1) // layout.count


def page_items(photos: list[Photo], layout: Layout, page: int) -> list[tuple[int, Photo]]:
    """Return only this page's copies, retaining their original row indices.

    Does not expand the entire order, even for a large number of copies.
    """
    layout.validate()
    print_count(photos)
    if layout.mode=='repeat':
        quantity=layout.repeat_quantity or layout.count
        sheet=page//2 if layout.duplex else page
        filled=max(0,min(layout.count,quantity-sheet*layout.count))
        uid=layout.repeat_back if layout.duplex and page%2 else layout.repeat_front
        lookup={p.uid:(i,p) for i,p in enumerate(photos)}
        return [lookup.get(uid,blank_item())]*filled
    if layout.order or layout.duplex:
        tokens = ordered_tokens(photos, layout.order)
        lookup = {p.uid:(i,p) for i,p in enumerate(photos)}
        def item(token):
            if token is None: return blank_item()
            return lookup.get(token[0], blank_item())
        if layout.mode == "postcard":
            # Assignment order: front, back, inside left, inside right.
            ids = (layout.panels[1],layout.panels[0]) if page == 0 else layout.panels[2:4]
            return [lookup.get(uid,blank_item()) for uid in ids]
        if layout.mode == "booklet":
            pages=booklet_pages(photos,layout)
            return [item(pages[i][0]) for i in spread_positions(len(pages),page)]*layout.booklet_copies
        return [item(t) for t in tokens[page*layout.count:(page+1)*layout.count]]
    start, end = page * layout.count, (page + 1) * layout.count
    position = 0
    result = []
    for index, photo in enumerate(photos):
        following = position + photo.copies
        overlap = max(0, min(end, following) - max(start, position))
        result.extend([(index, photo)] * overlap)
        position = following
        if position >= end:
            break
    return result


def ordered_tokens(photos, order=()):
    natural=[(p.uid,c) for p in photos for c in range(p.copies)]
    valid=set(natural)
    kept=list(dict.fromkeys(t for t in order if t in valid))
    seen=set(kept)
    return kept+[t for t in natural if t not in seen]


def spread_positions(count,page):
    sheet=page//2
    return (count-1-2*sheet,2*sheet) if page%2==0 else (2*sheet+1,count-2-2*sheet)


def booklet_pages(photos,layout):
    """Reading sequence with pinned covers and padding immediately before END."""
    tokens=ordered_tokens(photos,layout.order)
    if layout.booklet_covers is None:
        front=tokens[0] if tokens else None
        back=tokens[-1] if len(tokens)>1 else None
        inside=tokens[1:-1] if len(tokens)>1 else []
    else:
        lookup={p.uid for p in photos}
        a,b=layout.booklet_covers
        front=(a,0) if a in lookup else None
        back=(b,0) if b in lookup else None
        inside=[t for t in tokens if t[0] in layout.booklet_interiors] if layout.booklet_interiors is not None else [t for t in tokens if t[0] not in (a,b)]
    if layout.booklet_sequence is not None:
        valid=set(tokens)
        inside=[token if token in valid else None for token in layout.booklet_sequence]
    inside += [None] * ((-(len(inside)+2))%4)
    result=[(front,'0')]+[(token,str(i+1)) for i,token in enumerate(inside)]
    result.append((back,'END'))
    return result


def page_labels(photos,layout,page):
    if layout.mode=='postcard':
        return ('Задняя','Лицевая') if page%2==0 else ('Внутри слева','Внутри справа')
    if layout.mode=='booklet':
        pages=booklet_pages(photos,layout)
        return tuple(pages[i][1] for i in spread_positions(len(pages),page))*layout.booklet_copies
    return ()


@lru_cache(maxsize=1)
def blank_item():
    from .metadata import ASSETS
    return (-1,Photo(ASSETS / "blank-panel.png", mode="fit", correction=Correction(), uid="blank"))


def page_photos(photos: list[Photo], layout: Layout, page: int) -> list[Photo]:
    return [photo for _, photo in page_items(photos, layout, page)]


def _source_key(path: Path) -> tuple[str, int, int]:
    from .vector_import import document_pdf, VECTOR_EXTENSIONS
    if path.suffix.lower() in VECTOR_EXTENSIONS: path = document_pdf(path)
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


@image_memo(FULL_IMAGES,'source')
def _read_source(path: str, modified: int, length: int) -> Image.Image:
    if Path(path).suffix.lower() == '.psd':
        from .document_sources import psd_composite
        return psd_composite(path)
    if Path(path).suffix.lower() in ('.heic','.heif'):
        from pillow_heif import register_heif_opener
        register_heif_opener()
    with Image.open(path) as opened:
        with RESOURCES.working(opened.width*opened.height*20):
            upright = ImageOps.exif_transpose(opened)
            return to_srgb(upright)


def load_source(path: Path) -> Image.Image:
    """Load full resolution and EXIF orientation; callers must not mutate it."""
    photo = path if isinstance(path, Photo) else Photo(path)
    if photo.pdf_page is not None or photo.path.suffix.lower() == '.pdf':
        from .document_sources import pdf_render
        return pdf_render(photo.path, photo.pdf_page or 0)
    return _read_source(*_source_key(photo.path))


@dataclass(frozen=True)
class SourceSize:
    width_px: int
    height_px: int
    ppi: float
    fallback: bool
    physical_mm: tuple[float, float] | None = None

    @property
    def millimetres(self) -> tuple[float, float]:
        return self.physical_mm or (self.width_px * 25.4 / self.ppi, self.height_px * 25.4 / self.ppi)


def source_size(path: Path) -> SourceSize:
    """EXIF-upright pixels, with finite 36–2400 ppi metadata or 300 ppi.

    Prefer native DPI; then EXIF resolution (inch or cm). One physical PPI
    preserves square-pixel proportions even with inconsistent density pairs.
    """
    photo = path if isinstance(path, Photo) else Photo(path)
    if photo.pdf_page is not None or photo.path.suffix.lower() == '.pdf':
        from .document_sources import pdf_size
        w,h = pdf_size(photo.path, photo.pdf_page or 0)
        return SourceSize(round(w*300/25.4),round(h*300/25.4),300,False,(w,h))
    if photo.path.suffix.lower() in ('.psd','.heic','.heif'):
        return _special_source_size(*_source_key(photo.path))
    return _source_size(*_source_key(photo.path))


@lru_cache(maxsize=128)
def _special_source_size(path,modified,length):
    try:
        if Path(path).suffix.lower() in ('.heic','.heif'):
            from pillow_heif import register_heif_opener
            register_heif_opener()
        with Image.open(path) as image:
            width,height=image.size
            if image.getexif().get(274,1) in (5,6,7,8):width,height=height,width
            return SourceSize(width,height,300,True)
    except OSError:
        return SourceSize(*_read_source(path,modified,length).size,300,True)


@lru_cache(maxsize=128)
def _source_size(path: str, modified: int, length: int) -> SourceSize:
    with Image.open(path) as image:
        width, height = image.size
        exif = image.getexif()
        if exif.get(274, 1) in (5, 6, 7, 8):
            width, height = height, width
        candidates = []
        dpi = image.info.get("dpi", ())
        if isinstance(dpi, (tuple, list)):
            candidates.extend(dpi)
        unit = exif.get(296, 2)
        if unit in (2, 3):
            for tag in (282, 283):
                try:
                    candidates.append(float(exif[tag]) * (2.54 if unit == 3 else 1))
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    pass
        for candidate in candidates:
            try:
                ppi = float(candidate)
                if math.isfinite(ppi) and 36 <= ppi <= 2400:
                    return SourceSize(width, height, ppi, False)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    return SourceSize(width, height, 300.0, True)


def correct_image(image: Image.Image, correction: Correction) -> Image.Image:
    # Identical sRGB pipeline in preview, PDF and printing.
    result = temperature_tint(image, correction.temperature, correction.tint)
    result = vibrance(result, correction.vibrance)
    if correction.gamma != 1.0 or correction.curve != IDENTITY:
        curve = curve_lut(correction.curve)
        lut = [curve[round(255 * (value / 255) ** (1 / correction.gamma))] for value in range(256)]
        result = result.point(lut * 3)
    return teal_orange(result, correction.teal_orange)


@image_memo(FULL_IMAGES,'corrected')
def _corrected_source(path: str, modified: int, length: int, correction: Correction, turns: int, flip_x=False, flip_y=False) -> Image.Image:
    source = _read_source(path, modified, length)
    with RESOURCES.working(source.width*source.height*16):
        result = correct_image(source, correction)
    if turns:
        result = result.transpose({1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180,
                                   3: Image.Transpose.ROTATE_90}[turns])
    return reflected(result,flip_x,flip_y)


def reflected(image, flip_x=False, flip_y=False):
    if flip_x: image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_y: image=image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


def rotation_turns(image_size: tuple[int, int], cell: Rect, photo: Photo, autorotate: bool = True) -> int:
    iw, ih = image_size
    square_frame = math.isclose(cell.width, cell.height, abs_tol=1e-8)
    automatic = int(autorotate and not square_frame and iw != ih and ((iw > ih) != (cell.width > cell.height)))
    return (automatic + photo.rotation) % 4


def effective_correction(photo: Photo, correction: Correction) -> Correction:
    if photo.correction is not None:
        return photo.correction
    return replace(correction, curve=photo.curve) if photo.curve is not None else correction


def photo_image(photo: Photo, correction: Correction, cell: Rect, autorotate: bool = True,
                apply_correction: bool = True, pdf_ppi: float = 96) -> Image.Image:
    if photo.pdf_page is not None:
        from .document_sources import pdf_render
        source = pdf_render(photo.path, photo.pdf_page, pdf_ppi)
        chosen = effective_correction(photo,correction) if apply_correction else Correction()
        source = correct_image(source,chosen)
        turns = rotation_turns(source.size,cell,photo,autorotate)
        source = source.transpose({1:Image.Transpose.ROTATE_270,2:Image.Transpose.ROTATE_180,
                                 3:Image.Transpose.ROTATE_90}[turns]) if turns else source
        return reflected(source,photo.flip_x,photo.flip_y)
    info = source_size(photo)
    correction = effective_correction(photo, correction) if apply_correction else Correction()
    return _corrected_source(*_source_key(photo.path), correction, rotation_turns((info.width_px,info.height_px), cell, photo, autorotate),photo.flip_x,photo.flip_y)


@image_memo(PREVIEW_IMAGES,'legacy-preview-source')
def _preview_source(path: str, modified: int, length: int, turns: int, width: int, height: int) -> Image.Image:
    source = _read_source(path, modified, length)
    # Resize before rotating: dragging a curve never recolours a full original.
    size = (height, width) if turns % 2 else (width, height)
    source = source.resize(size, Image.Resampling.LANCZOS) if size != source.size else source
    return source.transpose({1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180,
                             3: Image.Transpose.ROTATE_90}[turns]) if turns else source


@image_memo(PREVIEW_IMAGES,'legacy-preview-corrected')
def _preview_corrected(path: str, modified: int, length: int, turns: int, width: int, height: int,
                       correction: Correction) -> Image.Image:
    return correct_image(_preview_source(path, modified, length, turns, width, height), correction)


def image_rect(image_size: tuple[int, int], cell: Rect, photo: Photo) -> Rect:
    iw, ih = image_size
    ratios = (cell.width / iw, cell.height / ih)
    scale = (max(ratios) if photo.mode == "fill" else min(ratios)) * photo.zoom
    width, height = iw * scale, ih * scale
    free_x, free_y = cell.width - width, cell.height - height
    # Increasing an offset always moves the image right/down, in either mode.
    x = cell.x + free_x / 2 + abs(free_x) / 2 * max(-1, min(1, photo.offset_x))
    y = cell.y + free_y / 2 + abs(free_y) / 2 * max(-1, min(1, photo.offset_y))
    return Rect(x, y, width, height)


@working_budget(lambda photos,layout,page,correction,pixels_per_mm,**kw: round(layout.paper_width*pixels_per_mm)*round(layout.paper_height*pixels_per_mm)*12)
def render_page(
    photos: list[Photo], layout: Layout, page: int, correction: Correction, pixels_per_mm: float,
    *, fast: bool = False, apply_correction: bool = True,
) -> Image.Image:
    """Raster preview from originals, sharing all geometry with export_pdf."""
    if layout.production:
        from .production_geometry import render_planned_page
        return render_planned_page(photos,layout,page,correction,pixels_per_mm,apply_correction)
    items = page_photos(photos, layout, page)
    cells = layout.cells(limit=len(items))
    pw, ph = layout.page_size
    output = Image.new("RGB", (max(1, round(pw * pixels_per_mm)), max(1, round(ph * pixels_per_mm))), "white")
    for photo, cell in zip(items, cells):
        photo, cell, autorotate = photo_slot(photo, cell, layout)
        if not fast or photo.pdf_page is not None:
            x0, y0 = round(cell.x * pixels_per_mm), round(cell.y * pixels_per_mm)
            x1, y1 = round((cell.x + cell.width) * pixels_per_mm), round((cell.y + cell.height) * pixels_per_mm)
            if x1 > x0 and y1 > y0:
                tile = render_photo(photo, cell, correction, (x1 - x0, y1 - y0), autorotate, apply_correction)
                output.paste(tile, (x0, y0))
            continue
        if fast:
            info = source_size(photo)
            original_size = (info.width_px, info.height_px)
            turns = rotation_turns(original_size, cell, photo, autorotate)
            oriented_size = original_size[::-1] if turns % 2 else original_size
            placed = image_rect(oriented_size, cell, photo)
            width = max(1, min(oriented_size[0], math.ceil(placed.width * pixels_per_mm)))
            height = max(1, min(oriented_size[1], math.ceil(placed.height * pixels_per_mm)))
            chosen = effective_correction(photo, correction) if apply_correction else Correction()
            source = reflected(_preview_corrected(*_source_key(photo.path), turns, width, height, chosen),photo.flip_x,photo.flip_y)
        else:
            source = photo_image(photo, correction, cell, autorotate, apply_correction)
        if not fast:
            placed = image_rect(source.size, cell, photo)
        # Prefilter before the affine crop. A direct bicubic transform aliases
        # fine details when a full-resolution photograph is much larger than
        # the preview. Geometry still comes from the original dimensions.
        sample_size = (max(1, min(source.width, math.ceil(placed.width * pixels_per_mm))),
                       max(1, min(source.height, math.ceil(placed.height * pixels_per_mm))))
        if sample_size != source.size:
            source = source.resize(sample_size, Image.Resampling.LANCZOS)
        x0, y0 = round(cell.x * pixels_per_mm), round(cell.y * pixels_per_mm)
        x1, y1 = round((cell.x + cell.width) * pixels_per_mm), round((cell.y + cell.height) * pixels_per_mm)
        if x1 <= x0 or y1 <= y0:
            continue
        # Pixel-aligned page boundaries avoid seams between adjacent cells.
        box = (
            (x0 / pixels_per_mm - placed.x) * source.width / placed.width,
            (y0 / pixels_per_mm - placed.y) * source.height / placed.height,
            (x1 / pixels_per_mm - placed.x) * source.width / placed.width,
            (y1 / pixels_per_mm - placed.y) * source.height / placed.height,
        )
        tile = source.transform((x1 - x0, y1 - y0), Image.Transform.EXTENT, box,
                                resample=Image.Resampling.BICUBIC, fillcolor="white")
        output.paste(tile, (x0, y0))
    draw = ImageDraw.Draw(output)
    for segment in layout.output_segments(page,len(items)):
        draw.line(tuple(round(v * pixels_per_mm) for v in segment), fill="black", width=max(1, round(.1 * pixels_per_mm)))
    return output


def render_photo(photo: Photo, cell: Rect, correction: Correction, size: tuple[int, int],
                 autorotate: bool = True, apply_correction: bool = True, *, clip: Rect | None = None) -> Image.Image:
    """One Lanczos resize from corrected ORIGINAL pixels, including cropping.

    The same millimetre placement serves preview, PDF tiles and print pages.
    Never feed this function a previously scaled output.
    """
    pdf_ppi = 96
    if photo.pdf_page is not None:
        from .document_sources import pdf_size
        native = pdf_size(photo.path,photo.pdf_page)
        if rotation_turns(native,cell,photo,autorotate) % 2:
            native = native[::-1]
        placed_mm = image_rect(native,cell,photo)
        pdf_ppi = max(size[0]/cell.width,size[1]/cell.height) * max(placed_mm.width/native[0],placed_mm.height/native[1]) * 25.4
    source = photo_image(photo, correction, cell, autorotate, apply_correction, pdf_ppi)
    placed = image_rect(source.size, cell, photo)
    cell=clip or cell
    left, top = max(cell.x, placed.x), max(cell.y, placed.y)
    right = min(cell.x + cell.width, placed.x + placed.width)
    bottom = min(cell.y + cell.height, placed.y + placed.height)
    px, py = size[0] / cell.width, size[1] / cell.height
    x0, y0 = round((left - cell.x) * px), round((top - cell.y) * py)
    x1, y1 = round((right - cell.x) * px), round((bottom - cell.y) * py)
    output = Image.new("RGB", size, "white")
    if x1 > x0 and y1 > y0:
        box = (max(0., (left - placed.x) / placed.width * source.width),
               max(0., (top - placed.y) / placed.height * source.height),
               min(float(source.width), (right - placed.x) / placed.width * source.width),
               min(float(source.height), (bottom - placed.y) / placed.height * source.height))
        output.paste(source.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS, box=box), (x0, y0))
    output.info["icc_profile"] = srgb_bytes()
    return output


def effective_ppi(photo: Photo, cell: Rect, autorotate: bool = True) -> float:
    if photo.pdf_page is not None:
        return float('inf')  # PDF is rerendered for the requested output density.
    info = source_size(photo)
    size = (info.width_px, info.height_px)
    if rotation_turns(size, cell, photo, autorotate) % 2:
        size = size[::-1]
    placed = image_rect(size, cell, photo)
    return min(size[0] / placed.width, size[1] / placed.height) * 25.4


def _tag_srgb_pdf(source: Path, destination: Path, page_size=None, output_intent=True) -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject, RectangleObject, FloatObject
    writer = PdfWriter(clone_from=PdfReader(source))
    stream = DecodedStreamObject()
    stream.set_data(srgb_bytes())
    stream.update({NameObject("/N"): NumberObject(3), NameObject("/Alternate"): NameObject("/DeviceRGB")})
    profile = writer._add_object(stream.flate_encode())
    for page in writer.pages:
        if page_size:
            # Page boxes come directly from millimetres, never from raster pixels.
            box = [0, 0, FloatObject(page_size[0] * 72 / 25.4), FloatObject(page_size[1] * 72 / 25.4)]
            page.mediabox = RectangleObject(box)
            page.cropbox = RectangleObject(box)
            page[NameObject('/UserUnit')] = NumberObject(1)
        for ref in page.get("/Resources", {}).get("/XObject", {}).values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image":
                obj[NameObject("/ColorSpace")] = ArrayObject([NameObject("/ICCBased"), profile])
    intent = DictionaryObject({NameObject("/Type"): NameObject("/OutputIntent"),
                              NameObject("/S"): NameObject("/GTS_PDFA1"),
                              NameObject("/OutputConditionIdentifier"): TextStringObject("sRGB IEC61966-2.1"),
                              NameObject("/DestOutputProfile"): profile})
    if output_intent:writer._root_object[NameObject("/OutputIntents")] = ArrayObject([writer._add_object(intent)])
    writer.write(destination)


PDF_REPLACE_MESSAGE = 'Не удалось заменить PDF. Возможно, он открыт в другой программе или папка недоступна для записи'

class PDFReplaceError(OSError):
    def __init__(self, prepared, destination, error):
        super().__init__(PDF_REPLACE_MESSAGE)
        self.prepared, self.destination, self.original_error = prepared, Path(destination), error

@dataclass
class PreparedPDF:
    path: Path
    pages: int

    def cleanup(self):
        self.path.unlink(missing_ok=True)

    def commit(self, destination):
        destination = Path(destination).resolve()
        temporary = None
        try:
            descriptor, name = tempfile.mkstemp(prefix='.ottisk-', suffix='.pdf', dir=destination.parent)
            os.close(descriptor)
            temporary = Path(name)
            shutil.copyfile(self.path, temporary)
            os.replace(temporary, destination)
        except OSError as error:
            record('pdf.replace.error', destination=str(destination), error=repr(error))
            raise PDFReplaceError(self, destination, error) from error
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self.cleanup()


@working_budget(lambda destination,photos,layout,correction,ppi=300,app_name=APP_NAME,**kw: round(layout.paper_width*ppi/25.4)*round(layout.paper_height*ppi/25.4)*12)
def export_pdf(destination: Path, photos: list[Photo], layout: Layout, correction: Correction, ppi: int = 300,
               app_name: str = APP_NAME) -> int:
    """Export original-resolution corrected images, with millimetre PDF clips.

    Write atomically so errors cannot leave a truncated PDF at the target path.
    Cut lines/marks are vector paths; preview selection is never exported.
    """
    validate_output(photos, layout)
    if ppi not in (300, 600):
        raise ValueError("Разрешение вывода должно быть 300 или 600 ppi.")
    if not photos:
        raise ValueError("Сначала добавьте фотографии.")
    destination = Path(destination).resolve()
    if any(destination == photo.path.resolve() for photo in photos):
        raise ValueError("Нельзя перезаписать исходную фотографию.")
    pw, ph = layout.page_size
    descriptor, temporary = tempfile.mkstemp(prefix=".illusive-", suffix=".pdf")
    os.close(descriptor)
    prepared = None
    tagged = Path(temporary + '.tagged')
    vector_output=Path(temporary+'.vector')
    has_vectors=False
    pending_mark_pages=set()
    def slots_for_page(page):
        items=page_photos(photos,layout,page)
        if layout.production:
            from .production_geometry import placements
            return [(p.photo,p.trim,p.paint,p.autorotate,p) for p in placements(photos,layout,page)]
        result=[]
        for photo,cell in zip(items,layout.cells(limit=len(items))):
            p,area,auto=photo_slot(photo,cell,layout)
            result.append((p,area,area,auto,None))
        return result
    def vector_jobs():
        from .vector_pdf import raster_reason
        for page in range(page_count(photos,layout)):
            items=[(p,(planned.reference or cell) if planned else cell,paint,auto,planned.source_box if planned else 'trim') for p,cell,paint,auto,planned in slots_for_page(page) if p.pdf_page is not None and not raster_reason(p,correction)]
            if items:yield page,items
    def final_segments(page):return layout.output_segments(page,len(page_items(photos,layout,page)))
    try:
        pdf = canvas.Canvas(temporary, pagesize=(pw * mm, ph * mm), pageCompression=1)
        pdf.setTitle(app_name)
        pdf.setCreator(f"{app_name} {VERSION} · {ppi} ppi")
        for page in range(page_count(photos, layout)):
            page_has_vectors=False
            items = page_photos(photos, layout, page)
            from .production_geometry import render_placement
            slots=slots_for_page(page)
            for slot_index,(photo, cell, paint, autorotate, planned) in enumerate(slots):
                if layout.card:
                    card_cell=layout.cells(limit=len(items))[slot_index]
                    pdf.setFillColorRGB(1, 1, 1)
                    pdf.rect(card_cell.x * mm, (ph - card_cell.y - card_cell.height) * mm, card_cell.width * mm, card_cell.height * mm,
                             stroke=0, fill=1)
                if photo.pdf_page is not None:
                    from .vector_pdf import raster_reason
                    if not raster_reason(photo,correction):
                        has_vectors=True
                        page_has_vectors=True
                        continue
                size=(max(1,round(paint.width*ppi/25.4)),max(1,round(paint.height*ppi/25.4)))
                source=render_placement(planned,correction,size) if planned else render_photo(photo,cell,correction,size,autorotate)
                cell=paint
                pdf.saveState()
                clipping = pdf.beginPath()
                clipping.rect(cell.x * mm, (ph - cell.y - cell.height) * mm, cell.width * mm, cell.height * mm)
                pdf.clipPath(clipping, stroke=0, fill=0)
                pdf.drawImage(ImageReader(source), cell.x * mm, (ph - cell.y - cell.height) * mm,
                              width=cell.width * mm, height=cell.height * mm)
                pdf.restoreState()
            pdf.setStrokeColorRGB(0, 0, 0)
            pdf.setLineWidth(.1 * mm)
            if page_has_vectors:
                # Draw exactly once, after the original vector content, so
                # an opaque PDF background cannot cover the helper contour.
                pending_mark_pages.add(page)
            else:
                for x0, y0, x1, y1 in final_segments(page):
                    pdf.line(x0 * mm, (ph - y0) * mm, x1 * mm, (ph - y1) * mm)
            pdf.showPage()
        pdf.save()
        _tag_srgb_pdf(Path(temporary), tagged, layout.page_size,output_intent=not has_vectors)
        if has_vectors:
            from .vector_pdf import attach_vectors
            attach_vectors(tagged,vector_output,vector_jobs(),ph,lambda page:final_segments(page) if page in pending_mark_pages else ())
            os.replace(vector_output,tagged)
        prepared = PreparedPDF(tagged, page_count(photos, layout))
        prepared.commit(destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
        if prepared is None:
            tagged.unlink(missing_ok=True)
        vector_output.unlink(missing_ok=True)
    return page_count(photos, layout)
