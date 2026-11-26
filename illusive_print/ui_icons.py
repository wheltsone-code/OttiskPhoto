"""Locally drawn outline icons, rasterized at the current Windows DPI."""
from PIL import Image,ImageDraw,ImageTk
from tkinter import ttk


def icon(master,kind,size=16,color='#737782'):
    # Supersampling retains even strokes at 100, 125 and 150 percent scaling.
    scale=4;image=Image.new('RGBA',(size*scale,size*scale));draw=ImageDraw.Draw(image)
    f=size*scale/16
    def line(points):draw.line([(round(x*f),round(y*f)) for x,y in points],fill=color,width=max(1,round(f)),joint='curve')
    if kind=='grid':
        for x in (2,8,14):line(((x,2),(x,14)))
        for y in (2,8,14):line(((2,y),(14,y)))
    elif kind=='paper':line(((3,1),(10,1),(14,5),(14,15),(3,15),(3,1)));line(((10,1),(10,5),(14,5)))
    elif kind=='size':
        line(((1,4),(15,4)));line(((4,1),(1,4),(4,7)));line(((12,1),(15,4),(12,7)));line(((4,10),(4,15),(14,15)))
    elif kind=='stack':
        for offset in (0,3,6):line(((2+offset,2+offset),(9+offset,2+offset),(9+offset,9+offset),(2+offset,9+offset),(2+offset,2+offset)))
    elif kind=='book':
        line(((8,3),(5,1),(1,2),(1,13),(5,12),(8,14),(11,12),(15,13),(15,2),(11,1),(8,3),(8,14)))
    elif kind=='trim':
        for x,y,dx,dy in ((1,1,1,1),(15,1,-1,1),(1,15,1,-1),(15,15,-1,-1)):line(((x,y+4*dy),(x,y),(x+4*dx,y)))
    else:
        for y,x in ((3,5),(8,11),(13,7)):
            line(((1,y),(15,y)));draw.ellipse(((x-1.5)*f,(y-1.5)*f,(x+1.5)*f,(y+1.5)*f),fill='#faf8fa',outline=color,width=max(1,round(f)))
    return ImageTk.PhotoImage(image.resize((size,size),Image.Resampling.LANCZOS),master=master)


def install_icons(app):
    pixels=max(16,round(16*float(app.root.tk.call('tk','scaling'))/(96/72)))
    app._outline_icons={kind:icon(app.root,kind,pixels,'#FD3977' if kind=='grid' else '#737782') for kind in ('grid','paper','size','stack','book','trim','color')}
    mapping={'Раскладка':'grid','Бумага':'paper','Размер фото':'size','Размер изделия после реза':'size','Размер страницы':'book','Тираж':'stack'}
    def visit(widget):
        if isinstance(widget,ttk.Label):
            kind=mapping.get(str(widget.cget('text')))
            if kind:widget.configure(image=app._outline_icons[kind],compound='left',padding=(0,0,4,0))
        for child in widget.winfo_children():visit(child)
    visit(app.settings_inner)
    for section,kind in ((app.trim_section,'trim'),(app.color_section,'color')):
        header=section.header
        def draw(event=None,widget=header,k=kind):
            widget.delete('outline_icon')
            widget.create_image(15,widget.winfo_height()/2,image=app._outline_icons[k],tags='outline_icon')
        header.draw_outline_icon=draw
        header.bind('<Configure>',draw,add=True);header.bind('<Expose>',draw,add=True)
        draw()
