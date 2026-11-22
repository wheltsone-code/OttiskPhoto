"""Reading-order edits performed before the shared booklet imposition."""
import re
import tkinter as tk
from tkinter import ttk
from dataclasses import replace
from uuid import uuid4

def blank_page_plan(leaves, covers, text):
    """Place blanks at final reading numbers without discarding any photo.

    Covers use 0/END; internal numbers start at 1. Only the remaining suffix
    needed to reach a multiple of four is automatic padding.
    """
    requested=set()
    text=re.sub(r'\s*(-|\.\.)\s*',r'\1',text.strip().upper().replace('–','-').replace('—','-'))
    for part in re.split(r'[,;\s]+',text):
        if not part:continue
        if part=='END':requested.add('END');continue
        match=re.fullmatch(r'(\d+)(?:(?:-|\.\.)(\d+))?',part)
        if not match:raise ValueError('Укажите номера: 0, 1, 4-6, END.')
        first=int(match[1]);last=int(match[2]) if match[2] else first
        if first>last or last>10000:raise ValueError('Неверный диапазон страниц.')
        requested.update(range(first,last+1))
    covers=list(covers)
    content=[leaf['token'] for leaf in leaves if leaf['token'] is not None]
    for number,index in ((0,0),('END',1)):
        if number in requested and covers[index] is not None:
            token=(covers[index],0)
            content.insert(0,token) if index==0 else content.append(token)
            covers[index]=None
        elif number not in requested and covers[index] is None:
            raise ValueError('Пустую обложку сначала заполните фотографией или укажите 0 / END.')
    internal={n for n in requested if isinstance(n,int) and n>0}
    needed=max(len(content)+len(internal),max(internal,default=0))
    total=needed+2
    total+=(-total)%4
    iterator=iter(content)
    result=[]
    for number in range(1,total-1):
        token=None if number in internal else next(iterator,None)
        result.append({'token':token,'auto':token is None and number not in internal})
    return result,covers


class BookletEditorMixin:
    def show_booklet_dialog(self,window):
        window.update_idletasks()
        width,height=window.winfo_reqwidth(),window.winfo_reqheight()
        x=max(0,self.root.winfo_rootx()+(self.root.winfo_width()-width)//2)
        y=max(0,self.root.winfo_rooty()+(self.root.winfo_height()-height)//2)
        window.geometry(f'+{x}+{y}')
        window.bind('<Escape>',lambda e:window.destroy())
        window.grab_set()

    def booklet_token(self,position):
        if position in ('0','END'):
            uid=self.booklet_cover_ids[0 if position=='0' else 1]
            return (uid,0) if uid else None
        return self.booklet_leaves[position]['token']

    def set_booklet_token(self,position,token):
        if position in ('0','END'):
            self.booklet_cover_ids[0 if position=='0' else 1]=token[0] if token else None
        else:self.booklet_leaves[position].update(token=token,auto=False)

    def booklet_position_at(self,slot):
        from .core import spread_positions
        count=len(self.booklet_leaves)+2
        number=spread_positions(count,self.page)[slot%2]
        return '0' if number==0 else 'END' if number==count-1 else number-1

    def booklet_blank_summary(self):
        labels=[]
        if not self.booklet_cover_ids[0]:labels.append('0')
        labels.extend(str(i+1) for i,leaf in enumerate(self.booklet_leaves) if leaf['token'] is None)
        if not self.booklet_cover_ids[1]:labels.append('END')
        return ', '.join(labels)

    def apply_booklet_blank_numbers(self,text):
        leaves,covers=blank_page_plan(self.booklet_leaves,self.booklet_cover_ids,text)
        self.booklet_leaves[:]=leaves;self.booklet_cover_ids[:]=covers
        self._booklet_selected=None;self._selected_instance=None
        # Cover photos moved to the reading sequence must not be imported again.
        self._booklet_tokens_seen=getattr(self,'_booklet_tokens_seen',set())|{leaf['token'] for leaf in leaves if leaf['token']}
        self.refresh()

    def edit_booklet_blank_numbers(self):
        window=tk.Toplevel(self.root);window.title(self.display_text('Пустые страницы'))
        window.transient(self.root);window.resizable(False,False)
        body=ttk.Frame(window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text=self.display_text('Номера пустых страниц в порядке чтения'),font=('Segoe UI',11,'bold')).pack(anchor='w')
        value=tk.StringVar(value=self.booklet_blank_summary())
        entry=ttk.Entry(body,textvariable=value,width=48);entry.pack(fill='x',pady=8)
        ttk.Label(body,text=self.display_text('Например: 0, 1, 4-6, END. Фотографии сохранят свой порядок.'),wraplength=440).pack(anchor='w')
        result=tk.StringVar();ttk.Label(body,textvariable=result,wraplength=440).pack(anchor='w',pady=10)
        def preview(*_):
            try:
                leaves,covers=blank_page_plan(self.booklet_leaves,self.booklet_cover_ids,value.get())
                total=len(leaves)+2
                labels=(['0'] if covers[0] is None else [])+[str(i+1) for i,p in enumerate(leaves) if p['token'] is None]+(['END'] if covers[1] is None else [])
                result.set(self.display_text(f'Страниц: {total} · Листов: {total//4} · Сторон: {total//2}\nПустые страницы: '+(', '.join(labels) or '—')))
                apply.configure(state='normal')
            except ValueError as error:
                result.set(self.display_text(str(error)));apply.configure(state='disabled')
        def commit():
            self.apply_booklet_blank_numbers(value.get());window.destroy()
        bar=ttk.Frame(body);bar.pack(fill='x')
        apply=ttk.Button(bar,text=self.display_text('Применить'),command=commit);apply.pack(side='right')
        ttk.Button(bar,text=self.display_text('Отмена'),command=window.destroy).pack(side='right',padx=8)
        value.trace_add('write',preview);preview();entry.focus_set();self.show_booklet_dialog(window)

    def insert_booklet_at(self,number,after=True,count=1):
        number=str(number).strip().upper()
        if count<1 or count>10000:raise ValueError('Неверное количество страниц.')
        if number=='END':
            if after:raise ValueError('Вставляйте внутренние страницы между 0 и END.')
            position=len(self.booklet_leaves)
        elif number.isdecimal() and 0<=int(number)<=len(self.booklet_leaves):
            if int(number)==0 and not after:raise ValueError('Вставляйте внутренние страницы между 0 и END.')
            position=int(number) if after else int(number)-1
        else:raise ValueError('Неверный номер страницы.')
        self.booklet_leaves[position:position]=[{'token':None,'auto':False} for _ in range(count)]
        self.refresh();self.select_booklet_page(position)

    def insert_booklet_dialog(self):
        window=tk.Toplevel(self.root);window.title(self.display_text('Вставить пустые страницы'))
        window.transient(self.root);body=ttk.Frame(window,padding=16);body.pack()
        selected=self.selected_booklet_position()
        number=tk.StringVar(value=str(selected+1) if selected is not None else 'END')
        side=tk.StringVar(value='before' if selected is None else 'after');count=tk.StringVar(value='1')
        ttk.Label(body,text=self.display_text('Страница № (0, 1… или END)')).grid(row=0,column=0,sticky='w')
        ttk.Entry(body,textvariable=number,width=10).grid(row=0,column=1,padx=8)
        ttk.Radiobutton(body,text=self.display_text('Перед'),variable=side,value='before').grid(row=1,column=0,sticky='w')
        ttk.Radiobutton(body,text=self.display_text('После'),variable=side,value='after').grid(row=1,column=1,sticky='w')
        ttk.Label(body,text=self.display_text('Количество')).grid(row=2,column=0,sticky='w')
        ttk.Spinbox(body,from_=1,to=10000,textvariable=count,width=10).grid(row=2,column=1,pady=8)
        error=tk.StringVar();ttk.Label(body,textvariable=error,wraplength=350).grid(row=3,column=0,columnspan=2)
        def apply():
            try:
                if not count.get().isdecimal():raise ValueError('Неверное количество страниц.')
                self.insert_booklet_at(number.get(),side.get()=='after',int(count.get()))
            except ValueError as failure:error.set(self.display_text(str(failure)));return
            window.destroy()
        ttk.Button(body,text=self.display_text('Добавить'),command=apply).grid(row=4,column=1,pady=8)
        self.show_booklet_dialog(window)

    def duplicate_photo(self,index,position=None):
        clone=replace(self.photos[index],uid=uuid4().hex,copies=1)
        if not self.layout or self.layout.mode!='booklet':
            self.photos.insert(index+1,clone)
            self.thumbnail_images.insert(index+1,self.thumbnail_images[index])
            self.rebuild_library()
            self.selected=index+1;self.selected_rows={index+1};self._selected_instance=None
            self.update_selection();self.refresh();return
        new_index=len(self.photos)
        self.photos.append(clone);self.thumbnail_images.append(self.thumbnail_images[index])
        self._add_thumbnail(new_index,self.thumbnail_images[-1])
        if self.layout and self.layout.mode=='booklet':
            self._booklet_seen.add(clone.uid);self.booklet_interior_ids.append(clone.uid)
            token=(clone.uid,0);self._booklet_tokens_seen.add(token)
            if position is None:position=self.selected_booklet_position()
            destination=0 if position=='0' else len(self.booklet_leaves) if position in (None,'END') else position+1
            self.trim_booklet_padding()
            destination=min(destination,len(self.booklet_leaves))
            self.booklet_leaves.insert(destination,{'token':token,'auto':False})
            self._booklet_selected=destination
        self.selected=new_index;self.selected_rows={new_index};self._selected_instance=None
        self.update_selection();self.refresh()

    def fill_booklet_page(self,position):
        """Recover a cleared/unassigned source without adding a reading page."""
        used={token[0] for token in (self.booklet_token('0'),self.booklet_token('END')) if token}
        used.update(p['token'][0] for p in self.booklet_leaves if p['token'])
        candidates=[p for p in self.photos if p.uid not in used]
        window=tk.Toplevel(self.root);window.title(self.display_text('Заполнить страницу'))
        window.transient(self.root);body=ttk.Frame(window,padding=16);body.pack(fill='both',expand=True)
        if not candidates:
            ttk.Label(body,text=self.display_text('Добавьте фото или создайте дубликат и перетащите его на пустую страницу.'),wraplength=360).pack()
            ttk.Button(body,text=self.display_text('Закрыть'),command=window.destroy).pack(pady=8)
        else:
            listing=tk.Listbox(body,width=48,height=min(12,len(candidates)))
            for p in candidates:listing.insert('end',p.name)
            listing.pack(fill='both',expand=True);listing.selection_set(0)
            def apply():
                chosen=listing.curselection()
                if chosen:
                    self.set_booklet_token(position,(candidates[chosen[0]].uid,0))
                    self.refresh();window.destroy()
            ttk.Button(body,text=self.display_text('Заполнить страницу'),command=apply).pack(pady=8)
        self.show_booklet_dialog(window)
