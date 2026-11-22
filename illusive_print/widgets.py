"""Small Tk widgets: pill actions, bounded millimetre inputs and marked scales."""

import tkinter as tk
import math
from decimal import Decimal, InvalidOperation
from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageTk
from .i18n import ui_text


PINK = "#f53286"


def ellipsize(widget, text, width):
    font = tkfont.Font(font=widget.cget("font"))
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"


class CapsuleButton(tk.Canvas):
    """A resizable capsule with a real tab stop and Space/Enter activation."""

    def __init__(self, master, text="", command=None, style="TButton", width=None, height=34, padding=None, **kwargs):
        self.text, self.command, self.style_name = text, command, style
        self.enabled, self.hover, self.pressed = True, False, False
        self.label_font = tkfont.Font(master, family="Segoe UI", size=10)
        requested = max(height, self.label_font.measure(text) + 24)
        if width is not None:
            requested = max(height, width * 8 + 12)
        super().__init__(master, width=requested, height=height, highlightthickness=0, bd=0, takefocus=True, **kwargs)
        self._image = None
        self._redraw_job = None
        self.bind("<Configure>", lambda event: self.redraw())
        self.bind("<Expose>", self._queue_redraw)
        self.bind("<Map>", self._queue_redraw)
        self.bind("<Destroy>", self._cancel_redraw, add=True)
        self.bind("<FocusIn>", lambda event: self.redraw())
        self.bind("<FocusOut>", lambda event: self.redraw())
        self.bind("<Enter>", lambda event: self._hover(True))
        self.bind("<Leave>", lambda event: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", self._key)
        self.bind("<space>", self._key)

    def _key(self, event):
        self.invoke()
        return "break"

    def _queue_redraw(self, event=None):
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self._finish_redraw)

    def _finish_redraw(self):
        self._redraw_job = None
        if self.winfo_ismapped():
            self.redraw()

    def _cancel_redraw(self, event):
        if event.widget == self and self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
            self._redraw_job = None

    def _hover(self, value):
        self.hover = value
        self.redraw()

    def _press(self, event):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self.redraw()

    def _release(self, event):
        pressed, self.pressed = self.pressed, False
        self.redraw()
        if pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        if self.enabled and self.command:
            return self.command()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        dirty=False
        if "text" in kwargs:
            text=kwargs.pop('text')
            dirty |= text!=self.text
            self.text=text
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if "style" in kwargs:
            style=kwargs.pop('style')
            dirty |= style!=self.style_name
            self.style_name=style
        if "state" in kwargs:
            enabled=kwargs.pop('state')!='disabled'
            if enabled!=self.enabled:
                dirty=True
                self.enabled=enabled
                kwargs['takefocus']=enabled
        dirty |= bool(kwargs) or cnf is not None
        result = super().configure(cnf, **kwargs) if cnf is not None or kwargs else None
        if dirty and hasattr(self, "label_font") and self.winfo_exists():
            self.redraw()
        return result

    config = configure

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return "normal" if self.enabled else "disabled"
        if key == "style":
            return self.style_name
        return super().cget(key)

    __getitem__ = cget

    def redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        try:
            background = self.master.cget("background")
        except tk.TclError:
            background = "#faf8fa"
        super().configure(background=background)
        accent = self.style_name == "Accent.TButton"
        chosen = self.style_name == "Chosen.TButton"
        fill = PINK if accent else "#f8d8e4" if chosen else "#ffffff"
        outline = PINK if accent else "#d3cfd5"
        foreground = "white" if accent else "#9b2454" if self.style_name == "Section.TButton" else "#24242c"
        if not self.enabled:
            fill, outline, foreground = ("#edb9cb", "#edb9cb", "#fff5f9") if accent else ("#f4f2f4", "#e0dce1", "#a5a0a8")
        elif self.hover or self.pressed:
            fill = "#cc326a" if accent else "#fcebf2"
        scale = 3
        image = Image.new("RGB", (w * scale, h * scale), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, w * scale - 2, h * scale - 2), radius=(h * scale - 2) / 2,
                               fill=fill, outline=outline, width=scale)
        if self.focus_get() == self and self.enabled:
            draw.rounded_rectangle((4 * scale, 4 * scale, (w - 4) * scale, (h - 4) * scale),
                                   radius=max(1, (h - 8) * scale / 2), outline="#a82258", width=scale)
        self._image = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.LANCZOS))
        self.delete("all")
        self.create_image(0, 0, image=self._image, anchor="nw")
        label = self.text if getattr(self, "_literal_text", False) else ui_text(self, self.text)
        font = self.label_font
        if self.style_name == "Section.TButton":
            font = tkfont.Font(self, family="Segoe UI", size=10, weight="bold")
        if font.measure(label) > w - 12:
            font = ("Segoe UI", max(7, round(10 * (w - 12) / max(1, font.measure(label)))))
        if hasattr(self, "values"):
            metric = tkfont.Font(self, font=font)
            if metric.measure(label) > w - 12:
                label = label.removesuffix("  ▾")
                while label and metric.measure(label + "…  ▾") > w - 12:
                    label = label[:-1]
                label += "…  ▾"
        self.create_text(w / 2, h / 2, text=label, fill=foreground, font=font)
        if hasattr(self, "draw_alignment_icon"):
            self.draw_alignment_icon()
        if hasattr(self,'draw_outline_icon'):
            self.draw_outline_icon()


class RoundedCombo(CapsuleButton):
    """Whole-field capsule, including arrow. Read-only dropdown with keyboard."""
    def __init__(self, master, textvariable, values, state="readonly", width=20, **kwargs):
        self.variable, self.values = textvariable, tuple(values)
        self.popup = None
        super().__init__(master, text=textvariable.get() + "  ▾", width=width, command=self.open, **kwargs)
        self._trace = textvariable.trace_add("write", self._sync)
        self.bind("<Destroy>", self._destroy, add=True)
        self.bind("<Down>", lambda e: self.cycle(1))
        self.bind("<Up>", lambda e: self.cycle(-1))
        self.bind("<Alt-Down>", lambda e: self.open())
        self.configure(state=state)

    def _sync(self, *_):
        self.text = self.display_value(self.variable.get()) + "  ▾"
        self.redraw()

    def display_value(self, value):
        return getattr(self, "format_value", lambda v: ui_text(self, v))(value)

    def popup_value(self, value):
        return getattr(self, "format_popup_value", self.display_value)(value)

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)

    def current(self, index=None):
        if index is None:
            return self.values.index(self.get()) if self.get() in self.values else -1
        self.set(self.values[index])

    def cycle(self, delta):
        if self.enabled and self.values:
            self.current((self.current() + delta) % len(self.values))
            self.event_generate("<<ComboboxSelected>>")
        return "break"

    def open(self):
        if not self.enabled:
            return "break"
        if self.popup:
            self.close()
            return "break"
        popup = self.popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg="#bcb4c1")
        popup_font = tkfont.Font(self, family="Segoe UI", size=11)
        width = min(self.winfo_screenwidth()-20, max(self.winfo_width(), *(popup_font.measure(self.popup_value(v))+28 for v in self.values))) if self.values else self.winfo_width()
        popup.geometry(f"{width}x{min(9, len(self.values)) * 27 + 4}+{min(self.winfo_rootx(), self.winfo_screenwidth()-width-5)}+{self.winfo_rooty() + self.winfo_height()}")
        box = self.listbox = tk.Listbox(popup, font=("Segoe UI", 11), bd=0, highlightthickness=0,
                                       activestyle="none", selectbackground="#f8d8e4", selectforeground="#24242c")
        box.pack(fill="both", expand=True, padx=1, pady=1)
        for value in self.values:
            box.insert("end", self.popup_value(value))
        if self.current() >= 0:
            box.selection_set(self.current())
            box.activate(self.current())
        box.focus_set()
        popup.grab_set()
        box.bind("<ButtonRelease-1>", self.choose)
        box.bind("<Return>", self.choose)
        box.bind("<space>", self.choose)
        box.bind("<Escape>", lambda e: self.close())
        popup.bind("<Button-1>", lambda e: self.close() if e.widget == popup else None)
        popup.bind("<FocusOut>", lambda e: self.after_idle(self._focus_out))
        return "break"

    def _focus_out(self):
        if self.popup and self.focus_get() != self.listbox:
            self.close()

    def choose(self, event=None):
        selection = self.listbox.curselection()
        if selection:
            self.current(selection[0])
            self.event_generate("<<ComboboxSelected>>")
        self.close()
        return "break"

    def close(self):
        if self.popup:
            self.popup.grab_release()
            self.popup.destroy()
            self.popup = None
            self.focus_set()
        return "break"

    def _destroy(self, event):
        if event.widget == self:
            self.variable.trace_remove("write", self._trace)


class FoldSection(ttk.Frame):
    """A full-width, keyboard-accessible header; hiding never changes values."""
    def __init__(self, master, title, opened=True):
        super().__init__(master)
        self.title, self.opened, self.summary = title, opened, ""
        self.header = CapsuleButton(self, height=28, command=self.toggle, style="Section.TButton")
        self.header.pack(fill="x")
        self.body = ttk.Frame(self, padding=(5, 3))
        self.set_open(opened)

    def set_open(self, opened):
        self.opened = opened
        if opened:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()
        self.update_header()

    def update_header(self, summary=None):
        if summary is not None:
            self.summary = summary
        shown = self.summary_provider(self.opened) if hasattr(self, 'summary_provider') else self.summary
        self.header.configure(text=("▾ " if self.opened else "▸ ") + self.title +
                              (" · " + shown if shown else ""))

    def toggle(self):
        self.set_open(not self.opened)


class CheckMark(CapsuleButton):
    """Explicit ✓, full-label hit target and a keyboard focus rectangle."""
    def __init__(self, master, text, variable, command=None, **kwargs):
        self.variable, self.changed = variable, command
        super().__init__(master, text=text, height=30, command=self.toggle, **kwargs)
        self._trace = variable.trace_add("write", lambda *_: self.redraw())
        self.bind("<Destroy>", self._destroy_check, add=True)

    def _destroy_check(self, event):
        if event.widget == self:
            self.variable.trace_remove("write", self._trace)

    def toggle(self):
        self.variable.set(not self.variable.get())
        if self.changed:
            self.changed()

    def redraw(self):
        if not hasattr(self, "variable"):
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2:
            return
        self.delete("all")
        bg = "#faf8fa"
        super(CapsuleButton, self).configure(background=bg)
        checked = self.variable.get()
        box=max(16,min(24,self.label_font.metrics('linespace')-2))
        tx=box+12
        label=self.create_text(tx,5,text=ui_text(self,self.text),anchor='nw',width=max(20,w-tx-5),font=self.label_font,
                               fill="#24242c" if self.enabled else "#a5a0a8",tags='check_label')
        bounds=self.bbox(label)
        needed=max(30,box+10,bounds[3]+5)
        if int(float(self.cget('height')))!=needed:tk.Canvas.configure(self,height=needed)
        cy=needed/2
        self.create_rectangle(3,cy-box/2,3+box,cy+box/2, fill=PINK if checked else "white", outline=PINK if checked else "#b9b2bc")
        if checked:
            point=max(9,round(box*72/self.winfo_fpixels('1i')))
            self.create_text(3+box/2,cy,text="✓",font=("Segoe UI Symbol",point,"bold"),fill="white")
        if self.focus_get() == self and self.enabled:
            self.create_rectangle(1, 1, w - 2, h - 2, outline="#a82258", dash=(2, 2))


class LockButton(CapsuleButton):
    """Compact outline lock with the same keyboard actions as other buttons."""
    def __init__(self,master,variable,tips=('Разблокировать пропорции','Связать пропорции'),**kwargs):
        self.variable,self.tips=variable,tips
        super().__init__(master,width=3,height=30,command=self.toggle,**kwargs)
        self._lock_trace=variable.trace_add('write',lambda *_:self.redraw())
        self.bind('<Destroy>',self._destroy_lock,add=True)
        ToolTip(self,lambda:self.tips[0 if self.variable.get() else 1])

    def toggle(self):self.variable.set(not self.variable.get())

    def redraw(self):
        super().redraw()
        w,h=self.winfo_width(),self.winfo_height()
        if w<2 or h<2:return
        f=min(w,h)/28;x=w/2;y=h/2
        color='#9b2454' if self.variable.get() else '#737782'
        self.create_rectangle(x-6*f,y-1*f,x+6*f,y+8*f,outline=color,width=max(1,1.4*f),tags='lock_icon')
        dx=0 if self.variable.get() else 4*f
        self.create_arc(x-4*f+dx,y-9*f,x+4*f+dx,y+3*f,start=0,extent=180,style='arc',outline=color,width=max(1,1.4*f),tags='lock_icon')
        if self.variable.get():
            for side in (-1,1):self.create_line(x+side*4*f,y-3*f,x+side*4*f,y-f,fill=color,width=max(1,1.4*f),tags='lock_icon')

    def _destroy_lock(self,event):
        if event.widget==self:self.variable.trace_remove('write',self._lock_trace)


class NumberSpin(ttk.Spinbox):
    def __init__(self, master, variable, minimum=0, maximum=2000, width=6, increment=1, integer=False, **kwargs):
        super().__init__(master, textvariable=variable, from_=minimum, to=maximum, increment=increment,
                         width=width, justify="center", **kwargs)
        self.variable, self.minimum, self.maximum = variable, minimum, maximum
        self.increment_value = increment
        self.integer_only=integer
        self.bind("<Up>", lambda event: self.step(1))
        self.bind("<Down>", lambda event: self.step(-1))
        self.bind("<Button-1>", self._click)

    def _click(self, event):
        element = self.identify(event.x, event.y)
        if "uparrow" in element:
            self.focus_set()
            return self.step(1)
        if "downarrow" in element:
            self.focus_set()
            return self.step(-1)

    def step(self, delta):
        try:
            value = float(str(self.variable.get()).replace(",", ".").replace("−", "-"))
        except ValueError:
            value = self.minimum
        increment = .254 if hasattr(self, "unit_context") and self.use_units and self.unit_context.unit_var.get() == "in" else self.increment_value
        value = min(self.maximum, max(self.minimum, value + delta * increment))
        self.variable.set(f"{value:.12g}".replace(".", ","))
        return "break"

    def bind_units(self, context, *, units=True):
        # Production fields also appear in the app's common unit-field list.
        # Bind once: replacing unit_display leaves orphan traces and destroy hooks.
        if hasattr(self, 'unit_context'):
            if self.unit_context is not context:
                raise ValueError('A number field cannot use two unit contexts')
            self.update_unit_display()
            return
        self.unit_context = context
        self.use_units=units
        self.unit_display = tk.StringVar(master=self)
        self._unit_sync = False
        self.configure(textvariable=self.unit_display)
        self._mm_trace = self.variable.trace_add("write", self.update_unit_display)
        self._unit_trace = self.unit_display.trace_add("write", self._unit_edited)
        self.bind("<Destroy>", self._unit_destroyed, add=True)
        self.bind('<Return>',self._commit_unit,add=True)
        self.bind('<FocusOut>',self._commit_unit,add=True)
        self.update_unit_display()

    def update_unit_display(self, *_):
        if self._unit_sync:
            return
        self._unit_sync = True
        try:
            text = self.variable.get()
            if self.use_units and self.unit_context.unit_var.get() == "in":
                try:
                    text = f"{float(text.replace(',', '.')) / 25.4:.12g}"
                except ValueError:
                    pass
            self.unit_display.set(text)
        finally:
            self._unit_sync = False

    def _unit_edited(self, *_):
        if self._unit_sync:
            return
        self._unit_sync = True
        try:
            text = self.unit_display.get()
            if self.use_units and self.unit_context.unit_var.get() == "in":
                try:
                    text = str(Decimal(text.replace(',', '.')) * Decimal('25.4'))
                except (ValueError, InvalidOperation):
                    pass
            try:number=float(text.replace(',','.').replace('−','-'))
            except ValueError:return
            if not math.isfinite(number) or not self.minimum<=number<=self.maximum:return
            if self.integer_only:
                if not number.is_integer():return
                text=str(int(number))
            self.variable.set(text)
        finally:
            self._unit_sync = False

    def _commit_unit(self,event=None):
        self.update_unit_display()

    def _unit_destroyed(self, event):
        if event.widget == self:
            self.variable.trace_remove("write", self._mm_trace)
            self.unit_display.trace_remove("write", self._unit_trace)


class GradientTrack(tk.Canvas):
    """Color track with the same values/steps as TickScale; keyboard operable."""
    def __init__(self, master, variable, start, end, step, command, colors):
        super().__init__(master, height=22, width=180, bg="#faf8fa", bd=0,
                         highlightthickness=1, highlightbackground="#faf8fa", highlightcolor="#a82258", takefocus=True)
        self.variable, self.start, self.end, self.step_size = variable, start, end, step
        self.command, self.colors, self.hover = command, colors, False
        self._image = None
        self._trace = variable.trace_add('write', self.draw)
        self.bind('<Configure>',self.draw)
        self.bind('<Button-1>',self.position)
        self.bind('<B1-Motion>',self.position)
        self.bind('<Enter>',lambda e:self._hover(True))
        self.bind('<Leave>',lambda e:self._hover(False))
        self.bind('<FocusIn>',self.draw)
        self.bind('<FocusOut>',self.draw)
        for key,direction in (('Left',-1),('Down',-1),('Right',1),('Up',1)):
            self.bind('<'+key+'>',lambda e,d=direction:self.nudge(d))
        self.bind('<Home>',lambda e:self.set(self.start))
        self.bind('<End>',lambda e:self.set(self.end))
        self.bind('<Destroy>',self.destroy_trace,add=True)

    def destroy_trace(self,event):
        if event.widget == self:
            self.variable.trace_remove('write',self._trace)

    def _hover(self,hover):
        self.hover=hover
        self.draw()

    def get(self): return self.variable.get()

    def set(self,value):
        value=max(self.start,min(self.end,round(float(value)/self.step_size)*self.step_size))
        self.variable.set(value)
        self.command(str(value))
        return 'break'

    def nudge(self,direction): return self.set(self.get()+direction*self.step_size)

    def position(self,event):
        self.focus_set()
        return self.set(self.start+(self.end-self.start)*max(0,min(1,(event.x-9)/max(1,self.winfo_width()-18))))

    def draw(self,*_):
        width=max(2,self.winfo_width()-18)
        if width<3:return
        image=Image.new('RGB',(width,6))
        colors=[tuple(int(c[i:i+2],16) for i in (1,3,5)) for c in self.colors]
        for x in range(width):
            position=x/(width-1)*(len(colors)-1)
            index=min(len(colors)-2,int(position)); t=position-index
            rgb=tuple(round(a+(b-a)*t) for a,b in zip(colors[index],colors[index+1]))
            for y in range(6): image.putpixel((x,y),rgb)
        self._image=ImageTk.PhotoImage(image,master=self)
        self.delete('all')
        self.create_image(9,8,image=self._image,anchor='nw',tags='gradient')
        zero=9+(0-self.start)/(self.end-self.start)*width
        self.create_line(zero,5,zero,17,fill='#6b5561',tags='neutral_mark')
        x=9+(self.get()-self.start)/(self.end-self.start)*width
        r=7 if self.hover else 6
        self.create_oval(x-r,11-r,x+r,11+r,fill='#a82258',outline='white',width=2,tags='thumb')


class TickScale(ttk.Frame):
    def __init__(self, master, variable, start, end, step, tick, reset, command, decimals=0, compact=False, gradient=None):
        super().__init__(master)
        self.variable, self.start, self.end, self.tick = variable, start, end, tick
        self.step_size, self.decimals, self.reset_value = step, decimals, reset
        self.command = command
        self.compact = compact
        self.value = tk.DoubleVar(value=float(str(variable.get()).replace(",", ".")))
        self.scale = GradientTrack(self, self.value, start, end, step, self._changed, gradient) if gradient else tk.Scale(self, from_=start, to=end, resolution=step, variable=self.value,
                              orient="horizontal", showvalue=False, borderwidth=0, highlightthickness=0,
                              sliderlength=12 if compact else 14, width=6 if compact else 8,
                              troughcolor="#d9d4dd", background="#e7437c",
                              activebackground="#c93167", relief="flat", sliderrelief="flat", command=self._changed)
        self.scale.pack(fill="x", expand=True)
        self.ticks = tk.Canvas(self, height=16 if compact else 20, highlightthickness=0, bg="#faf8fa")
        self.ticks.pack(fill="x")
        self.ticks.bind("<Configure>", lambda event: self.draw_ticks())
        self.scale.bind("<Double-Button-1>", lambda event: self.reset())
        self.ticks.bind("<Double-Button-1>", lambda event: self.reset())
        self._trace = variable.trace_add("write", self._sync)
        self.bind("<Destroy>", self._destroy, add=True)

    def _destroy(self, event):
        if event.widget == self:
            self.variable.trace_remove("write", self._trace)

    def _sync(self, *_args):
        try:
            value = float(str(self.variable.get()).replace(",", ".").replace("−", "-"))
            if self.value.get() != value:
                self.value.set(value)
        except (ValueError, tk.TclError):
            pass

    def _changed(self, value):
        number = round(float(value) / self.step_size) * self.step_size
        text = f"{number:.{self.decimals}f}".replace(".", ",")
        try:
            current = float(str(self.variable.get()).replace(",", ".").replace("−", "-"))
        except ValueError:
            current = None
        # External entry edits also move the Scale. Do not rewrite their text
        # (e.g. the intermediate '-12,') when its numeric value is unchanged.
        if current != number:
            self.variable.set(text)
        self.command(text)

    def reset(self):
        self._changed(str(self.reset_value))
        return "break"

    def draw_ticks(self):
        self.ticks.delete("all")
        width = self.ticks.winfo_width()
        count = round((self.end - self.start) / self.tick)
        for i in range(count + 1):
            x = 9 + (width - 18) * i / count
            self.ticks.create_line(x, 0, x, 5, fill="#aaa2af")
            # Every tick stays visible; sparse labels prevent collisions.
            stride = 5 if count > 8 else 1
            if (self.compact and (i in (0,count) or abs(self.start+i*self.tick)<1e-8)) or (not self.compact and (i % stride == 0 or i == count)):
                value = self.start + i * self.tick
                text = f"{value:g}".replace(".", ",")
                self.ticks.create_text(x, 11, text=text, font=("Segoe UI", 8, "bold") if abs(value)<1e-8 else ("Segoe UI", 7), fill="#654653" if abs(value)<1e-8 else "#82798a")


class ToolTip:
    def __init__(self, widget, text):
        self.widget, self.text, self.window, self.job = widget, text, None, None
        widget.bind("<Enter>", self.schedule, add=True)
        widget.bind("<Leave>", self.hide, add=True)
        widget.bind("<Destroy>", self.hide, add=True)
        widget.bind("<Button-1>", self.hide, add=True)

    def schedule(self, event=None):
        self.hide()
        self.job = self.widget.after(500, self.show)

    def show(self):
        self.job = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}")
        text = self.text() if callable(self.text) else self.text
        text = text if getattr(self.widget, "_l10n_skip", False) else ui_text(self.widget, text)
        tk.Label(self.window, text=text, bg="#fff6fb", relief="solid", borderwidth=1,
                 padx=8, pady=4, wraplength=440, font=("Segoe UI", 9)).pack()

    def hide(self, event=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None
