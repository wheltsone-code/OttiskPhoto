"""Physical placement of products and paired sides, in top-left millimetres."""
from dataclasses import dataclass
import math

from .core import Rect, EdgeInsets, merge_segments


def rotated_edges(edges):
    l,t,r,b=edges.values()
    return EdgeInsets(b,l,t,r)


def spread_grid(layout):
    w,h=layout.booklet_page_size
    candidates=[]
    for cw,ch,turned in ((2*w,h,False),(h,2*w,True)):
        e=rotated_edges(layout.bleed) if turned else layout.bleed
        cols=max(0,math.floor((layout.paper_width-2*layout.margin+layout.gap+1e-8)/(cw+e.left+e.right+layout.gap)))
        rows=max(0,math.floor((layout.paper_height-2*layout.margin+layout.gap+1e-8)/(ch+e.top+e.bottom+layout.gap)))
        candidates.append((cols,rows,cw,ch,turned))
    return max(candidates,key=lambda g:(g[0]*g[1],not g[4]))


def binding_edge(layout):
    if layout.flip_edge!='auto':return layout.flip_edge
    if layout.mode not in ('booklet','postcard'):return 'long'
    turned=bool(layout.booklet_page_size and spread_grid(layout)[4])
    landscape=layout.paper_width>layout.paper_height
    return 'short' if landscape!=turned else 'long'


def mirror_rect(rect,layout):
    mirror_x=(layout.paper_width>layout.paper_height)==(binding_edge(layout)=='short')
    return Rect(layout.paper_width-rect.x-rect.width,rect.y,rect.width,rect.height) if mirror_x else Rect(rect.x,layout.paper_height-rect.y-rect.height,rect.width,rect.height)


def spread_rects(layout,page=0):
    cols,rows,w,h,turned=spread_grid(layout)
    if not cols or not rows:return ()
    e=rotated_edges(layout.bleed) if turned else layout.bleed
    n=layout.booklet_copies
    used_cols=min(cols,n);used_rows=math.ceil(n/cols)
    ow,oh=w+e.left+e.right,h+e.top+e.bottom
    gw=used_cols*ow+max(0,used_cols-1)*layout.gap
    gh=used_rows*oh+max(0,used_rows-1)*layout.gap
    x=layout.margin+(layout.paper_width-2*layout.margin-gw)*{'left':0,'center':.5,'right':1}[layout.align_x]+e.left
    y=layout.margin+(layout.paper_height-2*layout.margin-gh)*{'top':0,'center':.5,'bottom':1}[layout.align_y]+e.top
    rects=tuple(Rect(x+(i%cols)*(ow+layout.gap),y+(i//cols)*(oh+layout.gap),w,h) for i in range(n))
    return tuple(mirror_rect(r,layout) for r in rects) if page%2 else rects


def side_cells(layout,page=0,limit=None):
    if layout.mode=='booklet' and layout.booklet_page_size:
        turned=spread_grid(layout)[4]
        result=[]
        for r in spread_rects(layout,page):
            if turned:
                result.extend((Rect(r.x,r.y,r.width,r.height/2),Rect(r.x,r.y+r.height/2,r.width,r.height/2)))
            else:
                result.extend((Rect(r.x,r.y,r.width/2,r.height),Rect(r.x+r.width/2,r.y,r.width/2,r.height)))
        return tuple(result[:limit] if limit is not None else result)
    result=layout.cells(limit)
    if layout.mode=='repeat' and layout.duplex and page%2:
        return tuple(mirror_rect(r,layout) for r in result)
    return result


def page_cells(photos,layout,page):
    from .core import page_items
    return side_cells(layout,page,len(page_items(photos,layout,page)))


def bleed_rect(layout,cell,index):
    e=layout.bleed
    if layout.mode=='booklet':
        l,t,r,b=e.values()
        e=EdgeInsets(l if index%2==0 else 0,t,r if index%2 else 0,b)
        if layout.booklet_page_size and spread_grid(layout)[4]:e=rotated_edges(e)
    elif layout.mode in ('exact','repeat') and layout.exact_grid()[2:]!=(layout.print_width,layout.print_height):
        e=rotated_edges(e)
    return Rect(cell.x-e.left,cell.y-e.top,cell.width+e.left+e.right,cell.height+e.top+e.bottom)


@dataclass(frozen=True)
class Placement:
    index:int
    photo:object
    trim:Rect
    paint:Rect
    autorotate:bool
    reference:Rect | None = None
    source_box:str = 'trim'


def pdf_reference(photo,area,paint,autorotate):
    """Choose the artwork box independently of the position of the knife.

    A 94x54 page may have a full-page TrimBox or a 90x50 TrimBox plus
    BleedBox. Explicit physical dimensions select the matching source box;
    moving a cut line must never rescale either kind of source.
    """
    from .pdf_sources import pdf_page
    from .core import rotation_turns
    page=pdf_page(photo.path,photo.pdf_page)
    def matches(box,rect):
        w,h=float(box.width)*25.4/72,float(box.height)*25.4/72
        if rotation_turns((w,h),rect,photo,autorotate)%2:w,h=h,w
        return abs(w-rect.width)<.02 and abs(h-rect.height)<.02
    if not matches(page.trimbox,area) and matches(page.bleedbox,paint):
        return paint,'bleed'
    available=any(abs(float(a)-float(b))>1e-5 for a,b in zip(page.trimbox,page.bleedbox))
    if paint!=area and not available:return paint,'trim'
    return area,'trim'


def placements(photos,layout,page):
    from .core import page_items,photo_slot
    items=page_items(photos,layout,page)
    result=[]
    for slot,((index,photo),cell) in enumerate(zip(items,side_cells(layout,page,len(items)))):
        photo,area,auto=photo_slot(photo,cell,layout)
        paint=bleed_rect(layout,area,slot)
        reference=area;source_box='trim'
        if photo.pdf_page is not None and not layout.card:
            reference,source_box=pdf_reference(photo,area,paint,auto)
        result.append(Placement(index,photo,area,paint,auto,reference,source_box))
    return tuple(result)


def fold_guides(layout,page):
    if layout.mode not in ('booklet','postcard'):return ()
    if layout.booklet_page_size:
        turned=spread_grid(layout)[4]
        return tuple((r.x,r.y+r.height/2,r.x+r.width,r.y+r.height/2) if turned else
                     (r.x+r.width/2,r.y,r.x+r.width/2,r.y+r.height) for r in spread_rects(layout,page))
    return ((layout.paper_width/2,layout.margin,layout.paper_width/2,layout.paper_height-layout.margin),)


STROKE_MM = .1
EPSILON_MM = 1e-6


def inset_rect(rect,inset):
    return Rect(rect.x+inset,rect.y+inset,rect.width-2*inset,rect.height-2*inset)


@dataclass(frozen=True)
class CutMark:
    segment:tuple
    owners:tuple


@dataclass(frozen=True)
class MarkIssue:
    page:int
    mark:CutMark
    region:Rect
    message:str


class MarkConflict(ValueError):
    def __init__(self,issues):
        self.issues=tuple(issues)
        super().__init__(self.issues[0].message)


@dataclass(frozen=True)
class CutGeometry:
    source:Rect
    trim:Rect
    contour:Rect | None
    paint:Rect


def cut_geometry(layout,page,limit=None):
    """Source frames, finished rectangles and helper contours stay separate."""
    if layout.mode=='booklet' and layout.booklet_page_size:
        cells=spread_rects(layout,page)
        e=rotated_edges(layout.bleed) if spread_grid(layout)[4] else layout.bleed
        paints=tuple(Rect(r.x-e.left,r.y-e.top,r.width+e.left+e.right,r.height+e.top+e.bottom) for r in cells)
    else:
        cells=side_cells(layout,page,limit)
        paints=tuple(bleed_rect(layout,r,i) for i,r in enumerate(cells))
    line_inset=layout.line_inset if layout.trim_mode=='both' else layout.trim_inset
    return tuple(CutGeometry(paint,inset_rect(r,layout.effective_trim_inset),
                            inset_rect(paint if layout.trim_mode=='both' else r,line_inset) if layout.trim_mode in ('lines','both') else None,paint)
                 for r,paint in zip(cells,paints))


def mark_rects(layout,page,limit=None):
    geometry=cut_geometry(layout,page,limit)
    return tuple(g.trim for g in geometry),tuple(g.paint for g in geometry)


def segment_intersects_rect(segment,rect,stroke=STROKE_MM):
    x0,y0,x1,y1=segment;half=stroke/2;r=rect
    return (min(x0,x1)-half<r.x+r.width-EPSILON_MM and max(x0,x1)+half>r.x+EPSILON_MM
            and min(y0,y1)-half<r.y+r.height-EPSILON_MM and max(y0,y1)+half>r.y+EPSILON_MM)


def cut_warning(layout):
    if layout.trim_mode=='both':
        for g in cut_geometry(layout,0,1):
            t,c=g.trim,g.contour
            clearances=(t.x-c.x,t.y-c.y,c.x+c.width-t.x-t.width,c.y+c.height-t.y-t.height)
            if min(clearances)<=STROKE_MM/2+EPSILON_MM:
                return 'Вспомогательный контур касается чистового реза или находится внутри изделия. Часть штриха может остаться после резки. Уменьшите отступ линий.'
    return ''


def crop_mark_plan(layout,page,limit=None):
    """Finite shared perimeter marks, in the same sheet axes as the artwork.

    Keep both cut coordinates of every gutter. Only occupied rectangles
    contribute; no mark is generated for an unused slot on a partial sheet.
    """
    if layout.trim_mode not in ('marks','both'):return (),()
    cuts,paints=mark_rects(layout,page,limit)
    if not cuts:return (),()
    left=min(r.x for r in paints);top=min(r.y for r in paints)
    right=max(r.x+r.width for r in paints);bottom=max(r.y+r.height for r in paints)
    xs={};ys={}
    for i,r in enumerate(cuts):
        for x in (r.x,r.x+r.width):xs.setdefault(round(x,6),set()).add(i)
        for y in (r.y,r.y+r.height):ys.setdefault(round(y,6),set()).add(i)
    marks=[];issues=[];half=STROKE_MM/2
    def free_candidates(coordinate,vertical):
        extent=layout.paper_height if vertical else layout.paper_width
        blocked=[]
        for r in paints:
            across,size=(r.x,r.width) if vertical else (r.y,r.height)
            start,length=(r.y,r.height) if vertical else (r.x,r.width)
            if across-half-EPSILON_MM<coordinate<across+size+half+EPSILON_MM:
                blocked.append((start-half-.05,start+length+half+.05))
        free=[];cursor=half
        for start,end in sorted(blocked):
            if start>cursor:free.append((cursor,min(start,extent-half)))
            cursor=max(cursor,end)
        if cursor<extent-half:free.append((cursor,extent-half))
        candidates=[]
        for start,end in free:
            space=end-start
            if space>=1.1-EPSILON_MM:
                length=min(2,(space-.1)/2)
                candidates.extend(((start,start+length),(end-length,end)))
            elif space>=.5-EPSILON_MM:candidates.append((start,end))
        return candidates

    def end_mark(coordinate,owners,boundary,edge,vertical,negative):
        # One millimetre of clear paper after the outside bleed. Shorten
        # only the mark, never the grid or the artwork, if the edge is near.
        inner=boundary+(-1 if negative else 1)*(1+half)
        available=inner-half if negative else edge-half-inner
        length=min(2,max(0,available))
        outer=inner+(-1 if negative else 1)*max(length,.5)
        if length<.5-EPSILON_MM:
            # Prefer a compact exterior mark over an internal one.
            inner=boundary+(-.1 if negative else .1)
            outer=max(half,inner-2) if negative else min(edge-half,inner+2)
            length=inner-outer if negative else outer-inner
        line=(coordinate,outer,coordinate,inner) if vertical else (outer,coordinate,inner,coordinate)
        cross_edge=layout.paper_width if vertical else layout.paper_height
        if length>=.5-EPSILON_MM and half-EPSILON_MM<=coordinate<=cross_edge-half+EPSILON_MM:
            return CutMark(line,tuple(sorted(owners)))
        return None

    def place(coordinate,owners,lo,hi,vertical):
        extent=layout.paper_height if vertical else layout.paper_width
        cross=layout.paper_width if vertical else layout.paper_height
        candidates=[m for m in (end_mark(coordinate,owners,lo,extent,vertical,True),
                                end_mark(coordinate,owners,hi,extent,vertical,False)) if m is not None]
        # One clear end is sufficient. Never demand a second mark or push a
        # failed exterior mark into artwork simply to retain a pair.
        if not candidates and half-EPSILON_MM<=coordinate<=cross-half+EPSILON_MM:
            free=free_candidates(coordinate,vertical)
            chosen=free[:1]+free[-1:] if len(free)>1 else free
            for a,b in chosen:
                line=(coordinate,a,coordinate,b) if vertical else (a,coordinate,b,coordinate)
                candidates.append(CutMark(line,tuple(sorted(owners))))
        if candidates:
            marks.extend(candidates);return
        needed=max(0,.65-max(lo,extent-hi),half-coordinate,coordinate-(cross-half))
        line=(coordinate,lo-.6,coordinate,lo-.1) if vertical else (lo-.6,coordinate,lo-.1,coordinate)
        mark=CutMark(line,tuple(sorted(owners)))
        axis='вертикального' if vertical else 'горизонтального'
        message=(f'Метка реза: для {axis} реза {coordinate:g} мм нет свободного отрезка для риски длиной 0,5 мм со штрихом {STROKE_MM:g} мм. '
                 f'Для внешней метки увеличьте поле минимум на {needed:.2f} мм или выберите больший лист. '
                 'Размер изделия, масштаб, сетка и зазор сохранены.')
        region=Rect(min(line[0],line[2])-half,min(line[1],line[3])-half,abs(line[2]-line[0])+STROKE_MM,abs(line[3]-line[1])+STROKE_MM)
        issues.append(MarkIssue(page,mark,region,message))
    for x,owners in sorted(xs.items()):
        place(x,owners,top,bottom,True)
    for y,owners in sorted(ys.items()):
        place(y,owners,left,right,False)
    # Validate the actual finite stroked segment, including its end caps.
    for mark in marks:
        x0,y0,x1,y1=mark.segment
        for i,r in enumerate(paints):
            if segment_intersects_rect(mark.segment,r):
                kind='собственного' if i in mark.owners else 'соседнего'
                issues.append(MarkIssue(page,mark,r,f'Метка {mark.segment} пересекает область {kind} изделия № {i+1}.'))
    return tuple(marks),tuple(issues)


def cut_output_segments(layout,page,limit=None):
    result=[]
    if layout.trim_mode!='none':
        for geometry in cut_geometry(layout,page,limit):
            r=geometry.contour
            if r is not None:
                result.extend(((r.x,r.y,r.x+r.width,r.y),(r.x,r.y+r.height,r.x+r.width,r.y+r.height),(r.x,r.y,r.x,r.y+r.height),(r.x+r.width,r.y,r.x+r.width,r.y+r.height)))
        if layout.trim_mode in ('marks','both'):result.extend(mark.segment for mark in crop_mark_plan(layout,page,limit)[0])
    return merge_segments(result)


def output_segments(layout,page,limit=None):
    result=list(cut_output_segments(layout,page,limit))
    active=layout.fold_side=='both' or layout.fold_side==('back' if page%2 else 'front')
    if active and layout.fold_marks!='none':
        for x0,y0,x1,y1 in fold_guides(layout,page):
            if layout.fold_marks=='line':result.append((x0,y0,x1,y1))
            elif x0==x1:result.extend(((x0,max(0,y0-2),x0,y0),(x1,y1,x1,min(layout.paper_height,y1+2))))
            else:result.extend(((max(0,x0-2),y0,x0,y0),(x1,y1,min(layout.paper_width,x1+2),y1)))
    m=layout.margin
    if layout.center_line=='vertical':result.append((layout.paper_width/2,m,layout.paper_width/2,layout.paper_height-m))
    if layout.center_line=='horizontal':result.append((m,layout.paper_height/2,layout.paper_width-m,layout.paper_height/2))
    return merge_segments(result)


def validate_production(photos,layout):
    from .core import page_count,page_items
    if layout.mode=='repeat':
        if not any(p.uid==layout.repeat_front for p in photos):raise ValueError('Назначьте источник лица.')
        if layout.duplex and layout.repeat_back and not any(p.uid==layout.repeat_back for p in photos):raise ValueError('Источник оборота недоступен.')
    count=page_count(photos,layout)
    pages=sorted({p for p in (0,1,count-2,count-1) if 0<=p<count}) if layout.mode=='repeat' else range(count)
    for page in pages:
        segments=output_segments(layout,page,len(page_items(photos,layout,page)))
        issues=crop_mark_plan(layout,page,len(page_items(photos,layout,page)))[1]
        if issues:raise MarkConflict(issues)
        for x0,y0,x1,y1 in segments:
            if min(x0,x1)<0 or min(y0,y1)<0 or max(x0,x1)>layout.paper_width or max(y0,y1)>layout.paper_height:
                raise ValueError('Метки выходят за край листа. Увеличьте поля или выберите другой лист.')


def render_placement(item,correction,size,apply_correction=True,*,screen=False):
    """Use the original PDF area outside TrimBox when painting its bleed."""
    from dataclasses import replace
    from .core import render_photo,source_size,rotation_turns,Correction,_source_key,effective_correction,correct_image
    from .image_cache import PREVIEW_IMAGES,FULL_IMAGES
    p=item.photo
    chosen=correction if apply_correction else Correction()
    info=source_size(p)
    reference=(item.reference or item.trim) if p.pdf_page is not None else item.trim
    dimensions=info.physical_mm or (info.width_px,info.height_px)
    if p.pdf_page is not None:
        from .vector_pdf import source_box
        box=source_box(p,item.source_box);dimensions=(float(box.width),float(box.height))
    turns=rotation_turns(dimensions,reference,p,item.autorotate)
    p=replace(p,rotation=turns)
    cache=FULL_IMAGES if not screen and size[0]*size[1]>2000000 else PREVIEW_IMAGES
    key=('production-screen' if screen else 'production-tile',_source_key(p.path),p.pdf_page,p.rotation,p.mode,p.zoom,p.offset_x,p.offset_y,
         p.correction,p.curve,chosen,(item.trim.x-item.paint.x,item.trim.y-item.paint.y,item.trim.width,item.trim.height,item.paint.width,item.paint.height),
         None if item.reference is None else (item.reference.x-item.paint.x,item.reference.y-item.paint.y,item.reference.width,item.reference.height),item.source_box,size)
    tile=cache.get(key)
    if tile is not None:return tile
    if p.pdf_page is not None:
        from .vector_pdf import raster_reason,raster_tile
        from .pdf_sources import pdf_page
        original=pdf_page(p.path,p.pdf_page)
        if not any(a.get_object().get('/Subtype')!='/Link' for a in original.get('/Annots',[])):
            tile=raster_tile(p,item.reference or item.trim,item.paint,size,item.source_box)
            color=effective_correction(p,chosen) if apply_correction else Correction()
            if color!=Correction():tile=correct_image(tile,color)
            cache.put(key,tile)
            return tile
    # Raster coverage is calculated against the outside of the bleed. The trim
    # rectangle remains fixed and is shared by preview and all output adapters.
    reference=item.trim if p.mode=='fit' else item.paint
    if screen and p.pdf_page is None:
        from .preview import render_tile
        color=effective_correction(p,chosen) if apply_correction else Correction()
        tile=render_tile(p,reference,size,color,False,_source_key(p.path),clip=item.paint)
    else:tile=render_photo(p,reference,chosen,size,False,apply_correction,clip=item.paint)
    cache.put(key,tile)
    return tile


def render_planned_page(photos,layout,page,correction,scale,apply_correction=True,marks=True,*,screen=False):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(max(1,round(layout.paper_width*scale)),max(1,round(layout.paper_height*scale))),'white')
    for item in placements(photos,layout,page):
        r=item.paint
        x0,y0=round(r.x*scale),round(r.y*scale)
        x1,y1=round((r.x+r.width)*scale),round((r.y+r.height)*scale)
        if x1>x0 and y1>y0:image.paste(render_placement(item,correction,(x1-x0,y1-y0),apply_correction,screen=screen),(x0,y0))
    if marks:
        draw=ImageDraw.Draw(image)
        from .core import page_items
        for line in output_segments(layout,page,len(page_items(photos,layout,page))):
            draw.line(tuple(round(v*scale) for v in line),fill='black',width=max(1,round(.1*scale)))
    return image


def clipping_warning(photos,layout,paper,current=None):
    from .core import page_count,page_items
    e=getattr(paper,'margins',None)
    if e is None:return ''
    count=page_count(photos,layout)
    pages=range(count)
    if current is not None:pages=(current//2*2,current//2*2+1) if layout.duplex else (current,)
    elif layout.mode=='repeat':pages=sorted({p for p in (0,1,count-2,count-1) if 0<=p<count})
    right,bottom=paper.width-e.right,paper.height-e.bottom
    for page in pages:
        occupied=[p.paint for p in placements(photos,layout,page) if p.index>=0]
        lines=layout.output_segments(page,len(page_items(photos,layout,page)))
        points=[(v.x,v.y,v.x+v.width,v.y+v.height) for v in occupied]+list(lines)
        if any(min(x0,x1)<e.left-.1 or min(y0,y1)<e.top-.1 or max(x0,x1)>right+.1 or max(y0,y1)>bottom+.1 for x0,y0,x1,y1 in points):
            return f'Содержимое или метки заходят в непечатаемую область драйвера. Поля: {e.left:g} / {e.top:g} / {e.right:g} / {e.bottom:g} мм; возможна обрезка.'
    return ''
