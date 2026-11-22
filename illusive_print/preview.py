"""Screen-only sources and reusable cell tiles; final output never uses these."""
from dataclasses import dataclass
import math
from PIL import Image,ImageOps
from .core import (Photo, Rect, Correction, _source_key, load_source, source_size,
                   effective_correction, correct_image, rotation_turns, image_rect, photo_slot, page_items)
from .image_cache import PREVIEW_IMAGES, image_memo
from .preview_tasks import check_preview_cancelled


def load_preview_source(photo,long_edge=1024):
    if not isinstance(photo,Photo):photo=Photo(photo)
    # A small screen pyramid; dragging/selection never changes its key.
    bucket=max(1024,2**math.ceil(math.log2(max(1,long_edge))))
    return _screen_source(*_source_key(photo.path),photo.pdf_page,bucket)


@image_memo(PREVIEW_IMAGES,'screen')
def _screen_source(path,modified,length,page,bucket):
    from pathlib import Path
    photo=Photo(Path(path),pdf_page=page)
    if page is not None:
        from .document_sources import pdf_size,pdf_render
        w,h=pdf_size(photo.path,page)
        image=pdf_render(photo.path,page,bucket/max(w,h)*25.4)
    elif photo.path.suffix.lower() in ('.jpg','.jpeg'):
        from .color_management import to_srgb
        # libjpeg decodes only the screen pyramid resolution. EXIF and the
        # original embedded ICC profile still use the common conversion path.
        with Image.open(photo.path) as opened:
            opened.draft(opened.mode,(bucket,bucket))
            image=to_srgb(ImageOps.exif_transpose(opened))
    else:
        image=load_source(photo)
    factor=min(1,bucket/max(image.size))
    if factor<1:
        return image.resize((max(1,round(image.width*factor)),max(1,round(image.height*factor))),
                            Image.Resampling.LANCZOS,reducing_gap=3)
    return image


@image_memo(PREVIEW_IMAGES,'screen-color')
def _screen_color(path,modified,length,page,bucket,turns,width,height,correction):
    image=_screen_source(path,modified,length,page,bucket)
    if turns:
        image=image.transpose({1:Image.Transpose.ROTATE_270,2:Image.Transpose.ROTATE_180,3:Image.Transpose.ROTATE_90}[turns])
    # Corrections operate on screen-sized pixels, using the same sRGB algorithm.
    factor=min(1,width/image.width,height/image.height)
    if factor<1:
        image=image.resize((max(1,round(image.width*factor)),max(1,round(image.height*factor))),Image.Resampling.LANCZOS)
    return correct_image(image,correction)


def render_tile(photo,cell,size,correction,autorotate,source_key,clip=None):
    info=source_size(photo)
    native=(info.width_px,info.height_px)
    if photo.pdf_page is not None:
        native=info.millimetres
    turns=rotation_turns(native,cell,photo,autorotate)
    oriented=native[::-1] if turns%2 else native
    placed=image_rect(oriented,cell,photo)
    clip=clip or cell
    px,py=size[0]/clip.width,size[1]/clip.height
    # Correct only the actual screen pixels. Crop coordinates still use native
    # dimensions and final output independently starts from the original.
    width=max(1,math.ceil(placed.width*px))
    height=max(1,math.ceil(placed.height*py))
    bucket=max(1024,2**math.ceil(math.log2(max(width,height))))
    source=_screen_color(*source_key,photo.pdf_page,bucket,turns,width,height,correction)
    output=Image.new('RGB',size,'white')
    left,top=max(clip.x,placed.x),max(clip.y,placed.y)
    right,bottom=min(clip.x+clip.width,placed.x+placed.width),min(clip.y+clip.height,placed.y+placed.height)
    x0,y0=round((left-clip.x)*px),round((top-clip.y)*py)
    x1,y1=round((right-clip.x)*px),round((bottom-clip.y)*py)
    if x1>x0 and y1>y0:
        box=(max(0,(left-placed.x)/placed.width*source.width),max(0,(top-placed.y)/placed.height*source.height),
             min(source.width,(right-placed.x)/placed.width*source.width),min(source.height,(bottom-placed.y)/placed.height*source.height))
        output.paste(source.resize((x1-x0,y1-y0),Image.Resampling.LANCZOS,box=box),(x0,y0))
    return output


@dataclass
class PreviewFrame:
    image: Image.Image
    structure: tuple
    changed: list


class PreviewRenderer:
    def __init__(self):
        self.frame=None
        self.tokens=[]
        self._production_key=None

    def clear(self):
        self.frame=None
        self.tokens=[]
        self._production_key=None

    def prepare(self,photos,layout,page,correction,scale,apply_correction=True):
        if layout.production:
            from .production_geometry import render_planned_page
            items=page_items(photos,layout,page)
            sources={}
            for _,p in items:
                if p.path not in sources:sources[p.path]=_source_key(p.path)
            key=(layout,page,scale,correction,apply_correction,tuple((tuple(vars(p).items()),sources[p.path]) for _,p in items))
            if self.frame is not None and self._production_key==key:
                self.frame=PreviewFrame(self.frame.image,self.frame.structure,[])
                return self.frame
            image=render_planned_page(photos,layout,page,correction,scale,apply_correction,marks=False,screen=True)
            box=(0,0,image.width,image.height)
            self.frame=PreviewFrame(image,(layout,page,image.size),[(box,image)])
            self._production_key=key
            return self.frame
        self._production_key=None
        items=page_items(photos,layout,page)
        slots=[]
        source_keys={}
        for (index,photo),cell in zip(items,layout.cells(limit=len(items))):
            check_preview_cancelled()
            photo,area,auto=photo_slot(photo,cell,layout)
            x0,y0=round(area.x*scale),round(area.y*scale)
            x1,y1=round((area.x+area.width)*scale),round((area.y+area.height)*scale)
            if x1<=x0 or y1<=y0:continue
            path=photo.path
            if path not in source_keys:source_keys[path]=_source_key(path)
            chosen=effective_correction(photo,correction) if apply_correction else Correction()
            shape=(area.width,area.height,x1-x0,y1-y0)
            token=('tile',source_keys[path],photo.pdf_page,shape,auto,photo.mode,photo.rotation,
                   photo.offset_x,photo.offset_y,photo.zoom,chosen)
            slots.append((token,photo,Rect(0,0,area.width,area.height),(x0,y0,x1,y1),auto,chosen,source_keys[path]))
        dimensions=(max(1,round(layout.paper_width*scale)),max(1,round(layout.paper_height*scale)))
        structure=(layout,page,dimensions,tuple(slot[3] for slot in slots),len(items))
        reset=self.frame is None or self.frame.structure!=structure
        image=Image.new('RGB',dimensions,'white') if reset else self.frame.image
        changed=[]
        tokens=[]
        for i,(token,photo,cell,box,auto,chosen,source_key) in enumerate(slots):
            check_preview_cancelled()
            tokens.append(token)
            if not reset and i<len(self.tokens) and self.tokens[i]==token:continue
            tile=PREVIEW_IMAGES.get(token)
            if tile is None:
                tile=render_tile(photo,cell,(box[2]-box[0],box[3]-box[1]),chosen,auto,source_key)
                PREVIEW_IMAGES.put(token,tile)
            image.paste(tile,box[:2])
            changed.append((box,tile))
        self.tokens=tokens
        self.frame=PreviewFrame(image,structure,changed)
        return self.frame
