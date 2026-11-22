"""Pinned covers, assignment targets and drag gestures over shared core pages."""
import tkinter as tk
from dataclasses import replace
from tkinter import ttk
from .booklet_editor import BookletEditorMixin
from .widgets import CapsuleButton,ellipsize,ToolTip
from .folding import FoldingMixin as BaseFoldingMixin
from .core import ordered_tokens,page_items,page_count,page_labels,booklet_pages,spread_positions
from .production_geometry import page_cells


class FoldingMixin(BookletEditorMixin,BaseFoldingMixin):
    def select_booklet_page(self,position):
        self._booklet_selected=position
        token=self.booklet_token(position)
        self.selected=next((i for i,p in enumerate(self.photos) if token and p.uid==token[0]),-1)
        self.selected_rows={self.selected} if self.selected>=0 else set()
        count=len(self.booklet_leaves)+2
        number=0 if position=='0' else count-1 if position=='END' else position+1
        for page in range(count//2):
            positions=spread_positions(count,page)
            if number in positions:
                self.page=page; self._selected_instance=(page,positions.index(number)); break
        self.update_selection(); self.refresh()

    def insert_booklet_blank(self):
        position=self.selected_booklet_position()
        position=len(self.booklet_leaves) if position is None else position+1
        self.booklet_leaves.insert(position,{'token':None,'auto':False})
        self._booklet_selected=position
        self.refresh()
        self.select_booklet_page(position)

    def selected_booklet_position(self):
        position=self._booklet_selected
        if isinstance(position,int) and 0<=position<len(self.booklet_leaves):
            token=self.booklet_leaves[position]['token']
            if (token is None and self.selected<0) or (token and 0<=self.selected<len(self.photos) and token[0]==self.photos[self.selected].uid):return position
        return next((i for i,leaf in enumerate(self.booklet_leaves) if leaf['token'] and 0<=self.selected<len(self.photos) and leaf['token'][0]==self.photos[self.selected].uid),None)

    def edit_booklet_page(self,position,delete=False):
        if position in ('0','END'):
            self.set_booklet_token(position,None)
            self._booklet_selected=position;self.selected=-1;self.selected_rows=set()
            self.refresh();return
        if delete:
            self.booklet_leaves.pop(position)
            self.trim_booklet_padding()
            self._booklet_selected=None; self._selected_instance=None
        else:
            self.booklet_leaves[position].update(token=None,auto=False)
            self._booklet_selected=position; self.selected=-1; self.selected_rows=set()
        self.refresh()

    def sync_booklet_cards(self):
        if not hasattr(self,'library_inner'):return
        active=self.layout and self.layout.mode=='booklet'
        # Imported/rebuilt source rows can be packed after END even when the
        # reading sequence did not change. Always hide them in booklet mode.
        if active:
            for widgets in self.thumbnail_widgets:widgets[0].pack_forget()
            self.empty_label.pack_forget()
            self.booklet_blank_var.set('Пустые страницы: '+(self.booklet_blank_summary() or '—'))
        key=(bool(active),tuple((leaf['token'],leaf['auto']) for leaf in self.booklet_leaves),tuple((p.uid,p.copies) for p in self.photos),tuple(self.booklet_cover_ids),self.selected,self._booklet_selected,len(self.thumbnail_widgets),self.language_var.get())
        if key==self._booklet_card_key:return
        self._booklet_card_key=key
        for frame in self._booklet_cards:frame.destroy()
        self._booklet_cards=[]
        if not active:
            for widgets in self.thumbnail_widgets:widgets[0].pack(fill='x',pady=(0,6))
            return
        for widgets in self.thumbnail_widgets:widgets[0].pack_forget()
        self.empty_label.pack_forget()
        lookup={p.uid:i for i,p in enumerate(self.photos)}
        current=replace(self.layout,booklet_covers=tuple(self.booklet_cover_ids),booklet_interiors=tuple(self.booklet_interior_ids),
                        booklet_sequence=tuple(leaf['token'] for leaf in self.booklet_leaves))
        pages=booklet_pages(self.photos,current)
        rows=[(token,label,'0' if i==0 else 'END' if i==len(pages)-1 else i-1) for i,(token,label) in enumerate(pages)]
        for token,label,position in rows:
            index=lookup.get(token[0]) if token else None
            frame=tk.Frame(self.library_inner,bg='white',highlightbackground='#e4dfe5',highlightthickness=1,padx=5,pady=8)
            frame.pack(fill='x',pady=(0,6)); frame.columnconfigure(2,weight=1)
            frame._position=position
            chosen=position==self._booklet_selected or (index==self.selected and self._booklet_selected is None and index is not None)
            frame.configure(highlightbackground='#f53286' if chosen else '#e4dfe5',highlightthickness=2 if chosen else 1)
            handle=tk.Label(frame,text='⠿',cursor='fleur',bg='white',width=2)
            handle.grid(row=0,column=0,sticky='ns');frame._handle=handle
            thumb=tk.Label(frame,bg='white',text='□' if index is None else '')
            if index is not None:
                thumb.configure(image=self.thumbnail_widgets[index][1]._image)
            thumb.grid(row=0,column=1,rowspan=3)
            name=self.photos[index].name if index is not None else self.display_text('Пустая страница')
            caption=tk.Label(frame,text=(label+' · ' if label else '')+name,bg='white',anchor='w',justify='left',wraplength=140,font=('Segoe UI',10,'bold'))
            caption.grid(row=0,column=2,sticky='ew',padx=(6,0))
            caption._l10n_skip=True
            if index is not None:
                full_caption=(label+' · ' if label else '')+name
                def resize_title(event=None,widget=caption,text=full_caption):
                    widget.configure(text=ellipsize(widget,text,max(75,widget.winfo_width()-4)),wraplength=0)
                caption.bind('<Configure>',resize_title,add=True)
                ToolTip(caption,full_caption)
            def select(event=None,pos=position,idx=index):
                self.select_booklet_page(pos)
            for widget in (frame,thumb,caption):widget.bind('<Button-1>',select)
            # A thumbnail drag fills a preview page; only the handle reorders
            # the reading list. A press/release on the thumbnail still selects.
            thumb.bind('<Button-1>',lambda e,pos=position:self.begin_booklet_photo_drag(pos,e))
            thumb.bind('<B1-Motion>',self.library_move_motion)
            thumb.bind('<ButtonRelease-1>',self.end_library_move)
            handle.bind('<Button-1>',lambda e,pos=position:self.begin_booklet_move(pos,e))
            handle.bind('<B1-Motion>',self.library_move_motion)
            handle.bind('<ButtonRelease-1>',self.end_library_move)
            handle.grid_configure(rowspan=3)
            menu=tk.Menu(frame,tearoff=False)
            if index is not None:
                menu.add_command(label=self.display_text('Дублировать'),command=lambda idx=index,pos=position:self.duplicate_photo(idx,pos))
                menu.add_command(label=self.display_text('Очистить страницу'),command=lambda pos=position:self.edit_booklet_page(pos))
                controls=tk.Frame(frame,bg='white');controls.grid(row=1,column=2,sticky='w',padx=6,pady=(5,0))
                tk.Label(controls,text=self.display_text('Копий'),bg='white',font=('Segoe UI',8)).pack(side='left')
                CapsuleButton(controls,text='−',width=2,height=24,command=lambda idx=index:self.change_copies(idx,-1)).pack(side='left')
                entry=ttk.Entry(controls,textvariable=self.copy_vars[index],width=3,justify='center');entry.pack(side='left',padx=2)
                entry.bind('<Return>',lambda e,idx=index:self.commit_copies(idx))
                entry.bind('<FocusOut>',lambda e,idx=index:self.commit_copies(idx))
                CapsuleButton(controls,text='+',width=2,height=24,command=lambda idx=index:self.change_copies(idx,1)).pack(side='left')
                CapsuleButton(frame,text='Дублировать',height=24,command=lambda idx=index,pos=position:self.duplicate_photo(idx,pos)).grid(row=2,column=2,sticky='w',padx=6,pady=(4,0))
            else:
                menu.add_command(label=self.display_text('Заполнить страницу'),command=lambda pos=position:self.fill_booklet_page(pos))
                hint='Добавлена для сгиба' if isinstance(position,int) and self.booklet_leaves[position]['auto'] else 'Перетащите сюда фото'
                tk.Label(frame,text=self.display_text(hint),bg='white',fg='#625767',font=('Segoe UI',8),wraplength=140).grid(row=1,column=2,sticky='w',padx=6,pady=6)
            if isinstance(position,int):
                menu.add_command(label=self.display_text('Удалить страницу'),command=lambda pos=position:self.edit_booklet_page(pos,delete=True))
                frame.bind('<Delete>',lambda e,pos=position:self.edit_booklet_page(pos,delete=True))
            button=tk.Label(frame,text='⋮',bg='white',cursor='hand2');button.grid(row=0,column=3)
            for widget in (frame,thumb,caption,button):widget.bind('<Button-3>',lambda e,m=menu:m.tk_popup(e.x_root,e.y_root))
            button.bind('<Button-1>',lambda e,m=menu:m.tk_popup(e.x_root,e.y_root))
            frame.configure(takefocus=True)
            self._wheel(frame,self.library_canvas)
            self._booklet_cards.append(frame)

    def begin_booklet_move(self,position,event,uid=None):
        if position is not None:
            token=self.booklet_token(position)
            uid=token[0] if token else None
        if position is None and uid in self.booklet_cover_ids:return 'break'
        self._booklet_move=(position,uid)
        self._library_target=position if isinstance(position,int) else len(self.booklet_leaves)
        self._library_grab=event.widget; self._library_grab.grab_set()
        self._insert_line=tk.Frame(self.library_inner,bg='#f53286',height=3)
        self._library_pointer=self.event_root(event)
        self.booklet_move_motion(event)
        self._library_scroll_job=self.root.after(60,self.library_autoscroll)
        return 'break'

    def begin_booklet_photo_drag(self,position,event):
        result=self.begin_booklet_move(position,event)
        self._booklet_photo_drag=True
        return result

    def booklet_move_motion(self,event):
        x,y=self.event_root(event);self._library_pointer=(x,y)
        self.highlight_target(self.target_at(x,y))
        if not self.library_canvas.winfo_rootx()<=x<self.library_canvas.winfo_rootx()+self.library_canvas.winfo_width():
            self._insert_line.place_forget();return
        target=len(self.booklet_leaves)
        for frame in self._booklet_cards:
            if isinstance(frame._position,int) and y<frame.winfo_rooty()+frame.winfo_height()/2:
                target=frame._position;break
        self._library_target=target
        frame=self._booklet_cards[target+1]
        self._insert_line.place(x=0,y=frame.winfo_y(),relwidth=1,height=3); self._insert_line.lift()
        if y<self.library_canvas.winfo_rooty()+24:self.library_canvas.yview_scroll(-1,'units')
        elif y>self.library_canvas.winfo_rooty()+self.library_canvas.winfo_height()-24:self.library_canvas.yview_scroll(1,'units')

    def end_booklet_move(self,event):
        if event:self.booklet_move_motion(event)
        source,uid=self._booklet_move;del self._booklet_move
        photo_drag=getattr(self,'_booklet_photo_drag',False);self._booklet_photo_drag=False
        self._library_grab.grab_release()
        if self._library_scroll_job:self.root.after_cancel(self._library_scroll_job)
        self._library_scroll_job=None;self._insert_line.destroy();self.highlight_target(None)
        point=self.event_root(event) if event else None
        destination=self.target_at(*point) if point else None
        if destination and uid:
            position='0' if destination._target[1]==0 else 'END'
            if self.booklet_token(position) is None:
                token=self.booklet_token(source) if source is not None else (uid,0)
                if source is not None:self.set_booklet_token(source,None)
                self.set_booklet_token(position,token);self.refresh()
            return
        slot=self.preview_slot_at(*point) if point else None
        if slot is not None and uid:
            position=self.booklet_position_at(slot)
            if self.booklet_token(position) is None:
                token=self.booklet_token(source) if source is not None else (uid,0)
                if source is not None:self.set_booklet_token(source,None)
                self.set_booklet_token(position,token)
                self._booklet_selected=position;self.refresh()
            return
        if point and not self.library_canvas.winfo_rootx()<=point[0]<self.library_canvas.winfo_rootx()+self.library_canvas.winfo_width():return
        if photo_drag:
            if source is not None:self.select_booklet_page(source)
            return
        if not isinstance(source,int):return
        target=self._library_target
        if source<target:target-=1
        if source==target:return
        leaf=self.booklet_leaves.pop(source);leaf['auto']=False
        self.booklet_leaves.insert(target,leaf);self._booklet_selected=target
        self.refresh();self.select_booklet_page(target)

    def ensure_booklet_covers(self):
        if not self._booklet_initialized and self.photos:
            self.booklet_cover_ids=[self.photos[0].uid,self.photos[-1].uid if len(self.photos)>1 else None]
            self.booklet_interior_ids=[p.uid for p in self.photos[1:-1]]
            self._booklet_seen={p.uid for p in self.photos}
            self._booklet_initialized=True
        elif self._booklet_initialized:
            self.booklet_interior_ids.extend(p.uid for p in self.photos if p.uid not in self._booklet_seen)
            self._booklet_seen.update(p.uid for p in self.photos)
        if self._booklet_initialized:
            valid=set(ordered_tokens(self.photos))
            # Keep edited padding, and consume untouched padding when photos arrive.
            previous=getattr(self,'_booklet_tokens_seen',set())
            wanted=[t for t in ordered_tokens(self.photos,self.print_sequence) if (t[0] in self.booklet_interior_ids and t[0] not in self.booklet_cover_ids) or (t[0] in self.booklet_cover_ids and t[1]>0)]
            new=[t for t in wanted if t not in previous]
            self._booklet_tokens_seen=valid
            if new:
                self.trim_booklet_padding()
                for token in new:
                    same=[i for i,p in enumerate(self.booklet_leaves) if p['token'] and p['token'][0]==token[0]]
                    position=same[-1]+1 if same else 0 if token[0]==self.booklet_cover_ids[0] else len(self.booklet_leaves)
                    self.booklet_leaves.insert(position,{'token':token,'auto':False})
            for leaf in self.booklet_leaves:
                if leaf['token'] is not None and leaf['token'] not in valid:
                    leaf.update(token=None,auto=False)
        # The reading list must own padding even before a source is imported.
        # Otherwise core adds virtual blanks that the cards cannot address.
        self.booklet_leaves.extend({'token':None,'auto':True} for _ in range((-(len(self.booklet_leaves)+2))%4))

    def trim_booklet_padding(self):
        # Only the untouched suffix is disposable. Removing padding before a
        # user-positioned page would silently change that page's reading position.
        while self.booklet_leaves and self.booklet_leaves[-1]['auto']:
            self.booklet_leaves.pop()

    def assign_cover(self,cover,clear=False,uid=None):
        self._booklet_initialized=True
        if clear:self.booklet_cover_ids[cover]=None
        elif uid is not None:self.booklet_cover_ids[cover]=uid
        elif 0<=self.selected<len(self.photos):self.booklet_cover_ids[cover]=self.photos[self.selected].uid
        assigned=self.booklet_cover_ids[cover]
        if not clear:
            self.booklet_interior_ids[:]=[uid for uid in self.booklet_interior_ids if uid!=assigned]
            for leaf in self.booklet_leaves:
                if leaf['token'] and leaf['token'][0]==assigned:leaf.update(token=None,auto=False)
        self.refresh()

    def create_assignment_target(self,parent,index,title,kind):
        frame=tk.Frame(parent,bg='white',highlightbackground='#dfd6dc',highlightthickness=1,padx=4,pady=3)
        frame.columnconfigure(1,weight=1)
        caption=tk.Label(frame,text=title,bg='white',anchor='w',font=('Segoe UI',9,'bold'))
        caption.grid(row=0,column=0,columnspan=2,sticky='ew')
        thumb=tk.Label(frame,text='Пусто',bg='white',anchor='w',font=('Segoe UI',8))
        thumb.grid(row=1,column=0,columnspan=2,sticky='w')
        clear=tk.Label(frame,text='×',bg='white',cursor='hand2'); clear.grid(row=0,column=2,sticky='ne')
        action=self.assign_panel if kind=='panel' else self.assign_cover
        clear.bind('<Button-1>',lambda e:action(index,clear=True))
        def click(event):
            if kind=='cover':
                uid=self.booklet_cover_ids[index]
                found=next((i for i,p in enumerate(self.photos) if p.uid==uid),None)
                if found is not None:self.select_photo(found);return
                self.select_booklet_page('0' if index==0 else 'END');return
            action(index)
        for widget in (frame,caption,thumb):widget.bind('<Button-1>',click)
        frame._target=(kind,index); frame._thumb=thumb
        return frame

    def sync_panel_buttons(self):
        valid={p.uid for p in self.photos}
        self.panel_ids[:]=[uid if uid in valid else None for uid in self.panel_ids]
        self.booklet_cover_ids[:]=[uid if uid in valid else None for uid in self.booklet_cover_ids]
        lookup={p.uid:i for i,p in enumerate(self.photos)}
        for kind,widgets,ids in (('panel',self.panel_buttons,self.panel_ids),('cover',self.cover_targets,self.booklet_cover_ids)):
            for i,widget in enumerate(widgets):
                uid=ids[i]; key=(kind,i,uid)
                if uid in lookup:
                    if key not in self._target_images:
                        image=tk.PhotoImage(master=self.root)
                        self.root.tk.call(str(image),'copy',str(self.thumbnail_images[lookup[uid]]),'-subsample',2,2)
                        self._target_images[key]=image
                    widget._thumb.configure(image=self._target_images[key],text='')
                else:widget._thumb.configure(image='',text=self.display_text('Пусто'))

    def side_caption(self,layout,page,total):
        if layout.duplex:
            side=('Внутри' if page%2 else 'Снаружи') if layout.mode=='postcard' else ('Оборот' if page%2 else 'Лицевая')
            return f'Лист {page//2+1} из {total//2} · '+side
        return super().side_caption(layout,page,total)

    def navigate_photo(self,index):
        if self.layout is None:return
        if self.layout.mode=='repeat':
            if self.layout.duplex and 0<=index<len(self.photos):
                uid=self.photos[index].uid
                if uid==self.layout.repeat_front:self.page=self.page//2*2
                elif uid==self.layout.repeat_back:self.page=self.page//2*2+1
            return
        if self.layout.duplex:
            for page in range(page_count(self.photos,self.layout)):
                if any(i==index for i,p in page_items(self.photos,self.layout,page)):
                    self.page=page; return
        else:self.page=self.photo_print_index(index,self.layout)//self.layout.count

    def sync_library_labels(self):
        from .widgets import ellipsize
        self.sync_booklet_cards()
        labels={}
        if self.layout and self.layout.mode=='booklet':
            for token,label in booklet_pages(self.photos,self.layout):
                if token is not None:labels.setdefault(token[0],[]).append(label)
        for i,widgets in enumerate(self.thumbnail_widgets):
            frame,thumb,label=widgets[:3]
            prefix=', '.join(labels.get(self.photos[i].uid,[]))
            name=(prefix+' · ' if prefix else '')+self.photos[i].name
            available=max(20,frame.winfo_width()-frame._handle.winfo_width()-thumb.winfo_reqwidth()-30)
            text=ellipsize(label,name,available)
            if label.cget('text')!=text:label.configure(text=text)

    def reveal_library_photo(self,index):
        if self.layout and self.layout.mode=='booklet':
            position=self.selected_booklet_position()
            frame=next((frame for frame in self._booklet_cards if frame._position==position),None)
            if frame is None:return
        else:frame=self.thumbnail_widgets[index][0]
        canvas=self.library_canvas
        top=canvas.canvasy(0); bottom=top+canvas.winfo_height()
        y=frame.winfo_y(); height=frame.winfo_height()
        extent=max(1,self.library_inner.winfo_height())
        if y<top:canvas.yview_moveto(y/extent)
        elif y+height>bottom:canvas.yview_moveto((y+height-canvas.winfo_height())/extent)

    def event_root(self,event):
        return (getattr(event,'x_root',self.preview_canvas.winfo_rootx()+getattr(event,'x',0)),getattr(event,'y_root',self.preview_canvas.winfo_rooty()+getattr(event,'y',0)))

    def target_at(self,x,y):
        widgets=self.panel_buttons if self.mode_var.get()=='Открытка со сгибом' else self.cover_targets if self.mode_var.get()=='Буклет' else []
        return next((w for w in widgets if w.winfo_ismapped() and w.winfo_rootx()<=x<w.winfo_rootx()+w.winfo_width() and w.winfo_rooty()<=y<w.winfo_rooty()+w.winfo_height()),None)

    def highlight_target(self,target):
        for widget in self.panel_buttons+self.cover_targets:
            color='#ffd8e9' if widget is target else 'white'
            widget.configure(bg=color,highlightbackground='#f53286' if widget is target else '#dfd6dc')
            for child in widget.winfo_children():child.configure(bg=color)

    def preview_slot_at(self,x,y):
        if not self.layout:return None
        x=(x-self.preview_canvas.winfo_rootx()-self.preview_origin[0])/self.preview_scale
        y=(y-self.preview_canvas.winfo_rooty()-self.preview_origin[1])/self.preview_scale
        return next((i for i,c in enumerate(page_cells(self.photos,self.layout,self.page)) if c.contains(x,y)),None)

    def begin_print_swap(self,event):
        self._swap_from=None; handle=getattr(self,'_print_handle',None)
        if self.layout and handle and handle[0]<=event.x<=handle[2] and handle[1]<=event.y<=handle[3]:
            self._swap_from=(self.page,handle[4]); self.preview_canvas.grab_set()
            self.preview_canvas.configure(cursor='exchange'); return True
        return False

    def print_swap_motion(self,event):self.highlight_target(self.target_at(*self.event_root(event)))

    def end_print_swap(self,event):
        source=getattr(self,'_swap_from',None)
        if source is None:return False
        self._swap_from=None; self.preview_canvas.grab_release()
        if event:
            point=self.event_root(event); target=self.target_at(*point); slot=self.preview_slot_at(*point)
            if self.layout.mode=='postcard':
                src=(1,0,2,3)[source[0]*2+source[1]]
                dst=target._target[1] if target and target._target[0]=='panel' else (1,0,2,3)[self.page*2+slot] if slot is not None else None
                if dst is not None:self.panel_ids[src],self.panel_ids[dst]=self.panel_ids[dst],self.panel_ids[src]
            elif slot is not None:
                tokens=ordered_tokens(self.photos,self.print_sequence)
                if self.layout.mode=='booklet':
                    pages=booklet_pages(self.photos,self.layout)
                    i=spread_positions(len(pages),source[0])[source[1]%2]-1
                    j=spread_positions(len(pages),self.page)[slot%2]-1
                    if source[0]==self.page and 0<=i<len(self.booklet_leaves) and 0<=j<len(self.booklet_leaves):
                        a,b=self.booklet_leaves[i],self.booklet_leaves[j]
                        a['token'],b['token']=b['token'],a['token']; a['auto']=b['auto']=False
                        self._booklet_selected=j
                else:
                    i,j=source[0]*self.layout.count+source[1],self.page*self.layout.count+slot
                    tokens[i],tokens[j]=tokens[j],tokens[i]
                self.print_sequence=tuple(tokens); self._selected_instance=(self.page,slot)
        self.highlight_target(None); self.preview_canvas.configure(cursor='hand2'); self.refresh(); return True

    def begin_library_move(self,index,event):
        if self.layout and self.layout.mode=='booklet':
            position=next((i for i,leaf in enumerate(self.booklet_leaves) if leaf['token'] and leaf['token'][0]==self.photos[index].uid),None)
            return self.begin_booklet_move(position,event,uid=self.photos[index].uid)
        self._library_pointer=(getattr(event,'x_root',self.library_canvas.winfo_rootx()+10),event.y_root)
        self._library_grab=getattr(event,'widget',self.thumbnail_widgets[index][0]._handle)
        self._library_grab.grab_set()
        result=super().begin_library_move(index,event)
        self._library_scroll_job=self.root.after(60,self.library_autoscroll)
        return result

    def library_autoscroll(self):
        self._library_scroll_job=None
        if not hasattr(self,'_library_from') and not hasattr(self,'_booklet_move'):return
        x,y=self._library_pointer
        self.library_move_motion(type('Pointer',(),{'x_root':x,'y_root':y})())
        self._library_scroll_job=self.root.after(60,self.library_autoscroll)

    def library_move_motion(self,event):
        if hasattr(self,'_booklet_move'):
            self.booklet_move_motion(event); return
        if not hasattr(self,'_library_from'):return
        x=getattr(event,'x_root',self.library_canvas.winfo_rootx()+10); y=event.y_root
        self._library_pointer=(x,y); self.highlight_target(self.target_at(x,y))
        if not self.library_canvas.winfo_rootx()<=x<self.library_canvas.winfo_rootx()+self.library_canvas.winfo_width():
            self._insert_line.place_forget(); return
        super().library_move_motion(event); self._insert_line.lift()

    def end_library_move(self,event):
        if hasattr(self,'_booklet_move'):
            self.end_booklet_move(event); return
        if not hasattr(self,'_library_from'):return
        # Fast native drags can coalesce motion messages. Always hit-test release.
        if event:self.library_move_motion(event)
        self._library_grab.grab_release()
        if self._library_scroll_job:self.root.after_cancel(self._library_scroll_job)
        self._library_scroll_job=None; self.highlight_target(None)
        destination=self.target_at(*self.event_root(event)) if event else None
        if destination:
            uid=self.photos[self._library_from].uid; self._insert_line.destroy(); del self._library_from
            kind,index=destination._target
            if kind=='panel':self.panel_ids[index]=uid
            else:self.assign_cover(index,uid=uid)
            self.refresh(); return
        outside=event and not self.library_canvas.winfo_rootx()<=self.event_root(event)[0]<self.library_canvas.winfo_rootx()+self.library_canvas.winfo_width()
        cover=self.layout and self.layout.mode=='booklet' and self.photos[self._library_from].uid in self.booklet_cover_ids
        if outside or cover:
            self._insert_line.destroy(); del self._library_from; return
        if self.layout and self.layout.mode=='booklet':
            uid=self.photos[self._library_from].uid
            if uid not in self.booklet_interior_ids:self.booklet_interior_ids.append(uid)
        super().end_library_move(event)
        if self.selected>=0:self.navigate_photo(self.selected); self.refresh()
