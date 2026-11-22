"""UI gestures; document geometry and sequence live in core, not in widgets."""
from .core import ordered_tokens, page_items


class FoldingMixin:
    def toggle_teal_orange(self, mode):
        self.apply_color_changes({'teal_orange':'none' if self.active_color().teal_orange==mode else mode})
        self.sync_color_controls(force=True)
        self.refresh()

    def assign_panel(self, panel, clear=False):
        if clear: self.panel_ids[panel]=None
        elif 0<=self.selected<len(self.photos): self.panel_ids[panel]=self.photos[self.selected].uid
        self.refresh()

    def sync_panel_buttons(self):
        names=('Лицевая сторона','Задняя сторона','Внутри слева','Внутри справа')
        lookup={p.uid:p.name for p in self.photos}
        for i,b in enumerate(self.panel_buttons):
            name=lookup.get(self.panel_ids[i],'—')
            b.configure(text=names[i]+': '+(name if len(name)<21 else name[:18]+'…'))

    def side_caption(self, layout, page, total):
        if layout.mode=='postcard': return 'Снаружи' if page==0 else 'Внутри'
        if layout.mode=='booklet': return f'Лист {page//2+1} из {total//2} · '+('Оборот' if page%2 else 'Лицевая')
        return f'Лист {page+1 if total else 0} из {total}'

    def photo_print_index(self,index,layout):
        if not layout.order:
            return sum(p.copies for p in self.photos[:index])
        return next(i for i,t in enumerate(ordered_tokens(self.photos,layout.order)) if t[0]==self.photos[index].uid)

    def begin_print_swap(self,event):
        self._swap_from=None
        handle=getattr(self,'_print_handle',None)
        if handle and handle[0]<=event.x<=handle[2] and handle[1]<=event.y<=handle[3]:
            self._swap_from=self.page*self.layout.count+handle[4]
            self.preview_canvas.configure(cursor='exchange')
            return True
        return False

    def end_print_swap(self,event):
        source=getattr(self,'_swap_from',None)
        if source is None: return False
        self._swap_from=None
        if event:
            x=(event.x-self.preview_origin[0])/self.preview_scale
            y=(event.y-self.preview_origin[1])/self.preview_scale
            items=page_items(self.photos,self.layout,self.page)
            for slot,cell in enumerate(self.layout.cells(limit=len(items))):
                if cell.contains(x,y):
                    tokens=ordered_tokens(self.photos,self.print_sequence)
                    target=self.page*self.layout.count+slot
                    tokens[source],tokens[target]=tokens[target],tokens[source]
                    self.print_sequence=tuple(tokens)
                    self._selected_instance=(self.page,slot)
                    break
        self.preview_canvas.configure(cursor='hand2')
        self.refresh()
        return True

    def begin_library_move(self,index,event):
        self._library_from=index
        self._library_target=index
        import tkinter as tk
        self._insert_line=tk.Frame(self.library_inner if hasattr(self,'library_inner') else self.thumbnail_widgets[0][0].master,bg='#f53286',height=3)
        self.library_move_motion(event)
        return 'break'

    def library_move_motion(self,event):
        if not hasattr(self,'_library_from'): return
        target=len(self.photos)
        for i,widgets in enumerate(self.thumbnail_widgets):
            frame=widgets[0]
            if event.y_root < frame.winfo_rooty()+frame.winfo_height()/2:
                target=i; break
        self._library_target=target
        frame=self.thumbnail_widgets[min(target,len(self.photos)-1)][0]
        y=frame.winfo_y()+(frame.winfo_height() if target==len(self.photos) else 0)
        self._insert_line.place(x=0,y=y,relwidth=1,height=3)
        if event.y_root<self.library_canvas.winfo_rooty()+24: self.library_canvas.yview_scroll(-1,'units')
        elif event.y_root>self.library_canvas.winfo_rooty()+self.library_canvas.winfo_height()-24: self.library_canvas.yview_scroll(1,'units')

    def end_library_move(self,event):
        if not hasattr(self,'_library_from'): return
        source,target=self._library_from,self._library_target
        self._insert_line.destroy()
        del self._library_from
        if source<target: target-=1
        if source==target: return
        moved=self.photos[source]
        tokens=ordered_tokens(self.photos,self.print_sequence)
        group=[t for t in tokens if t[0]==moved.uid]
        tokens=[t for t in tokens if t[0]!=moved.uid]
        self.photos.insert(target,self.photos.pop(source))
        self.thumbnail_images.insert(target,self.thumbnail_images.pop(source))
        following=self.photos[target+1].uid if target+1<len(self.photos) else None
        pos=next((i for i,t in enumerate(tokens) if t[0]==following),len(tokens))
        self.print_sequence=tuple(tokens[:pos]+group+tokens[pos:])
        self.rebuild_library()
        self.selected=target
        self.selected_rows={target}
        self._selected_instance=None
        self.update_selection()
        self.refresh()

    def rebuild_library(self):
        for variable,trace in zip(self.copy_vars,self.copy_traces): variable.trace_remove('write',trace)
        for name in ('copy_vars','copy_entries','copy_traces','copy_buttons','curve_badges'):
            getattr(self,name).clear()
        for widgets in self.thumbnail_widgets: widgets[0].destroy()
        self.thumbnail_widgets.clear()
        for i,image in enumerate(self.thumbnail_images): self._add_thumbnail(i,image)
