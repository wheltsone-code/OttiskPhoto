"""Small arrowless scrollbar; geometry follows the real canvas scroll fractions."""
import tkinter as tk


class RoundScrollbar(tk.Canvas):
    def __init__(self,parent,command,auto_hide=True,**kwargs):
        self.auto_hide=auto_hide
        self.factor=parent.winfo_fpixels('1i')/96
        super().__init__(parent,width=round(12*self.factor),highlightthickness=0,bg='#faf8fa',**kwargs)
        self.command=command
        self.first,self.last=0.,1.
        self.hover=self.dragging=False
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Enter>',lambda e:self.emphasis(True))
        self.bind('<Leave>',lambda e:self.emphasis(False))
        self.bind('<Button-1>',self.press)
        self.bind('<B1-Motion>',self.motion)
        self.bind('<ButtonRelease-1>',self.release)
        self.bind('<MouseWheel>',lambda e:self.command('scroll',-int(e.delta/120),'units'))

    def set(self,first,last):
        self.first,self.last=float(first),float(last)
        if self.auto_hide:
            if self.last-self.first < .999:
                if not self.winfo_manager():self.grid()
            else:
                if self.winfo_manager():self.grid_remove()
        self.draw()

    def geometry_values(self):
        h=max(1,self.winfo_height()-12*self.factor)
        length=min(h,max(24*self.factor,h*(self.last-self.first)))
        travel=max(1,h-length)
        y=6*self.factor+travel*self.first/max(1e-9,1-self.last+self.first)
        return y,length,travel

    def draw(self):
        self.delete('all')
        x=self.winfo_width()/2
        self.create_line(x,6*self.factor,x,max(6*self.factor,self.winfo_height()-6*self.factor),fill='#f0edf1',width=6*self.factor,capstyle='round',tags='track')
        y,length,_=self.geometry_values()
        self.create_line(x,y+3*self.factor,x,max(y+3*self.factor,y+length-3*self.factor),fill='#b67c96' if self.dragging else '#c19cac' if self.hover else '#d6c8d0',width=(7 if self.hover or self.dragging else 5)*self.factor,capstyle='round',tags='thumb')

    def emphasis(self,value):
        self.hover=value; self.draw()

    def press(self,event):
        y,length,_=self.geometry_values()
        if not y<=event.y<=y+length:
            extent=self.last-self.first
            first=max(0,min(1-extent,event.y/max(1,self.winfo_height())))
            self.command('moveto',first)
            self.first,self.last=first,first+extent
        self.dragging=True; self.start_y=event.y; self.start_first=self.first
        self.grab_set(); self.draw()

    def motion(self,event):
        if not self.dragging:return
        _,_,travel=self.geometry_values()
        extent=max(0,1-(self.last-self.first))
        self.command('moveto',max(0,min(extent,self.start_first+(event.y-self.start_y)/travel*extent)))

    def release(self,event):
        self.dragging=False; self.grab_release(); self.draw()
