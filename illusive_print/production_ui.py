"""Mode controls backed by the shared physical layout model."""
from dataclasses import replace
import math
import tkinter as tk
from tkinter import ttk

from .core import PAPERS,EdgeInsets,source_size,page_count
from .widgets import CapsuleButton,RoundedCombo,NumberSpin,CheckMark,FoldSection,ToolTip,LockButton
from .i18n import messagebox,localize_tree
from .paper_presets import PaperStore


class ProductionMixin:
    def _variables(self):
        self._legacy_variables()
        self.paper_store=PaperStore()
        self.repeat_front_var=tk.StringVar();self.repeat_back_var=tk.StringVar(value='Пустой оборот')
        self.repeat_duplex_var=tk.BooleanVar(value=False)
        self.repeat_fill_var=tk.StringVar(value='Заполнить один лист')
        self.repeat_quantity_var=tk.StringVar(value='100')
        self.repeat_w_var=tk.StringVar(value='100');self.repeat_h_var=tk.StringVar(value='150')
        self.repeat_lock_var=tk.BooleanVar(value=True)
        self.repeat_edge_var=tk.StringVar(value='Длинный край')
        self.booklet_method_var=tk.StringVar(value='По размеру листа')
        self.booklet_format_var=tk.StringVar(value='A5 · 148 × 210 мм')
        self.booklet_w_var=tk.StringVar(value='148');self.booklet_h_var=tk.StringVar(value='210')
        self.booklet_copies_var=tk.StringVar(value='1')
        self.bleed_vars=[tk.StringVar(value='0') for _ in range(4)]
        self.bleed_lock_var=tk.BooleanVar(value=True)
        self._bleed_updating=False
        self.production_hint_var=tk.StringVar()
        self._repeat_initialized=False;self._repeat_ratio=2/3;self._repeat_updating=False
        self._repeat_sources={};self._repeat_source_signature=None
        self._mode_settings['Тираж']=dict(self._mode_settings['Задать размер фото'])
        self._factory_settings['Тираж']=dict(self._mode_settings['Тираж'])
        for i,v in enumerate(self.bleed_vars):
            self._mode_vars['bleed_'+str(i)]=v
            for settings in (self._mode_settings,self._factory_settings):
                for values in settings.values():values['bleed_'+str(i)]='0'
        self._mode_vars['bleed_lock']=self.bleed_lock_var
        for settings in (self._mode_settings,self._factory_settings):
            for values in settings.values():values['bleed_lock']=True

    def reset_production_settings(self):
        self._repeat_updating=True
        try:
            for var,value in ((self.repeat_duplex_var,False),(self.repeat_fill_var,'Заполнить один лист'),(self.repeat_quantity_var,'100'),(self.repeat_w_var,'100'),(self.repeat_h_var,'150'),(self.repeat_lock_var,True),(self.repeat_edge_var,'Длинный край'),(self.repeat_back_var,'Пустой оборот'),(self.booklet_method_var,'По размеру листа'),(self.booklet_format_var,'A5 · 148 × 210 мм'),(self.booklet_w_var,'148'),(self.booklet_h_var,'210'),(self.booklet_copies_var,'1')):var.set(value)
            self._repeat_initialized=False;self._repeat_ratio=2/3
        finally:self._repeat_updating=False

    def _build_settings(self,parent):
        self._legacy_build_settings(parent)
        for widget in self.settings_inner.grid_slaves():
            row=int(widget.grid_info()['row'])
            if row>=5:widget.grid_configure(row=row+3)
        self.mode_combo.values=('Задать размер фото','Тираж','Буклет','Разделить лист','Фото с рамкой','Открытка со сгибом')
        captions={'Задать размер фото':'Точный размер · N-Up','Тираж':'Тираж · Step & Repeat'}
        self.mode_combo.format_value=lambda key:self.display_text(captions.get(key,key))
        self.mode_combo.format_popup_value=self.mode_combo.format_value
        self.mode_combo._sync()
        CapsuleButton(self.paper_combo.master,text='Управление форматами…',height=24,command=self.manage_papers).grid(row=3,column=0,columnspan=2,sticky='ew',pady=(3,0))
        self.fixed_orientation_label=ttk.Label(self.paper_combo.master,text='Альбомная',style='Muted.TLabel')
        self.fixed_orientation_label.grid(row=1,column=1,sticky='ew',padx=(6,0))
        self.production_box=ttk.Frame(self.settings_inner)
        self.production_box.grid(row=3,column=0,columnspan=2,sticky='ew',pady=3)
        self.production_box.columnconfigure(1,weight=1)
        self.repeat_box=ttk.Frame(self.production_box);self.repeat_box.grid(row=0,column=0,columnspan=2,sticky='ew')
        self.repeat_box.columnconfigure(1,weight=1)
        self.repeat_front_combo=self._combo_row(self.repeat_box,0,'Лицо',self.repeat_front_var,())
        self.repeat_duplex_check=CheckMark(self.repeat_box,text='Двусторонний тираж',variable=self.repeat_duplex_var)
        self.repeat_duplex_check.grid(row=1,column=0,columnspan=2,sticky='ew')
        self.repeat_back_row=ttk.Frame(self.repeat_box);self.repeat_back_row.grid(row=2,column=0,columnspan=2,sticky='ew');self.repeat_back_row.columnconfigure(1,weight=1)
        self.repeat_back_combo=self._combo_row(self.repeat_back_row,0,'Оборот',self.repeat_back_var,('Пустой оборот',))
        for combo in (self.repeat_front_combo,self.repeat_back_combo):
            combo._literal_text=True
            combo.format_value=lambda key:key if key in self._repeat_sources else self.display_text(key)
            combo.format_popup_value=combo.format_value
            ToolTip(combo,lambda c=combo:c.display_value(c.get()))
        self._combo_row(self.repeat_back_row,1,'Переворот',self.repeat_edge_var,('Длинный край','Короткий край'))
        size=ttk.Frame(self.repeat_box);size.grid(row=3,column=0,columnspan=2,sticky='ew');size.columnconfigure(0,weight=1);size.columnconfigure(2,weight=1)
        size_label=ttk.Label(size,text='Размер изделия после реза',wraplength=300)
        size_label.grid(row=0,column=0,columnspan=3,sticky='ew')
        size_label.bind('<Configure>',lambda e:size_label.configure(wraplength=max(100,e.width)))
        self.production_fields=list(self.combined_trim_entries)
        for col,var in ((0,self.repeat_w_var),(2,self.repeat_h_var)):
            entry=NumberSpin(size,var,minimum=1);entry.grid(row=1,column=col,sticky='ew');self.production_fields.append(entry)
        self.repeat_lock_button=LockButton(size,self.repeat_lock_var)
        self.repeat_lock_button.grid(row=1,column=1,padx=3)
        CapsuleButton(self.repeat_box,text='Исходный размер',height=24,command=self.repeat_original).grid(row=4,column=0,columnspan=2,sticky='ew',pady=2)
        self._combo_row(self.repeat_box,5,'Тираж',self.repeat_fill_var,('Заполнить один лист','Задать тираж'))
        self.repeat_quantity_row=ttk.Frame(self.repeat_box);self.repeat_quantity_row.grid(row=6,column=0,columnspan=2,sticky='ew')
        ttk.Label(self.repeat_quantity_row,text='Готовых изделий').pack(side='left')
        self.repeat_quantity_entry=NumberSpin(self.repeat_quantity_row,self.repeat_quantity_var,minimum=1,maximum=1000000000,width=10,integer=True)
        self.repeat_quantity_entry.pack(side='right')
        self.repeat_quantity_entry.bind_units(self,units=False)
        self.booklet_size_box=ttk.Frame(self.production_box);self.booklet_size_box.grid(row=0,column=0,columnspan=2,sticky='ew');self.booklet_size_box.columnconfigure(1,weight=1)
        method_combo=self._combo_row(self.booklet_size_box,0,'Размер страницы',self.booklet_method_var,('По размеру листа','Точный размер страницы'))
        method_combo.grid_configure(row=1,column=0,columnspan=2)
        self.booklet_exact_box=ttk.Frame(self.booklet_size_box);self.booklet_exact_box.grid(row=2,column=0,columnspan=2,sticky='ew');self.booklet_exact_box.columnconfigure(1,weight=1)
        self._combo_row(self.booklet_exact_box,0,'После реза',self.booklet_format_var,('A5 · 148 × 210 мм','A4 · 210 × 297 мм','Свой размер'))
        fields=ttk.Frame(self.booklet_exact_box);fields.grid(row=1,column=0,columnspan=2,sticky='ew')
        self.production_fields.extend(self._dimensions(fields,self.booklet_w_var,self.booklet_h_var))
        self.booklet_copies_combo=self._combo_row(self.booklet_exact_box,2,'Экземпляров на листе',self.booklet_copies_var,('1',))
        self.booklet_exact_box.grid_slaves(row=2,column=0)[0].grid_configure(columnspan=2)
        self.booklet_copies_combo.grid_configure(row=3,column=0,columnspan=2)
        self.bleed_section=FoldSection(self.settings_inner,'Вылеты',opened=False);self.bleed_section.grid(row=6,column=0,columnspan=2,sticky='ew',pady=2)
        self.bleed_entries=[]
        for row,(label,var) in enumerate(zip(('Слева','Сверху','Справа','Снизу'),self.bleed_vars)):
            ttk.Label(self.bleed_section.body,text=label).grid(row=row,column=0,sticky='w')
            entry=NumberSpin(self.bleed_section.body,var,minimum=0,width=7);entry.grid(row=row,column=1,sticky='e');self.production_fields.append(entry);self.bleed_entries.append(entry)
            var.trace_add('write',lambda *_,index=row:self.bleed_changed(index))
        self.bleed_section.body.columnconfigure(1,weight=1)
        self.bleed_lock_check=LockButton(self.bleed_section.body,self.bleed_lock_var,tips=('Разблокировать вылеты','Связать вылеты'))
        self.bleed_lock_check.grid(row=0,column=2,padx=(6,0))
        ttk.Label(self.bleed_section.body,text='Зазор — между внешними границами вылетов',wraplength=315,style='Muted.TLabel').grid(row=4,column=0,columnspan=2,sticky='w')
        self.production_hint=ttk.Label(self.settings_inner,textvariable=self.production_hint_var,wraplength=325,style='Muted.TLabel')
        self.production_hint.grid(row=7,column=0,columnspan=2,sticky='ew',pady=(3,6))
        for field in self.production_fields:field.bind_units(self)
        for var in (self.repeat_front_var,self.repeat_back_var,self.repeat_duplex_var,self.repeat_fill_var,self.repeat_quantity_var,self.repeat_w_var,self.repeat_h_var,self.repeat_lock_var,self.repeat_edge_var,self.booklet_method_var,self.booklet_format_var,self.booklet_w_var,self.booklet_h_var,self.booklet_copies_var):
            var.trace_add('write',self.schedule_refresh)
        self.repeat_w_var.trace_add('write',lambda *_:self.repeat_dimension('width'))
        self.repeat_h_var.trace_add('write',lambda *_:self.repeat_dimension('height'))
        self.repeat_lock_var.trace_add('write',self.repeat_relock)
        self.size_lock_var.trace_add('write',self.exact_relock)
        self.booklet_format_var.trace_add('write',self.booklet_format_changed)
        from .ui_icons import install_icons
        install_icons(self)
        self._wheel(self.production_box,self.settings_canvas)
        self._wheel(self.bleed_section,self.settings_canvas)
        self._wheel(self.production_hint,self.settings_canvas)

    def bleed_changed(self,index):
        # Restoring mode/order values must preserve independently stored sides.
        if self._bleed_updating or self._switching_mode:return
        value=self.bleed_vars[index].get()
        if self.bleed_lock_var.get():
            try:number=self._number(self.bleed_vars[index])
            except ValueError:return
            if not math.isfinite(number) or number<0:return
            self._bleed_updating=True
            try:
                for i,var in enumerate(self.bleed_vars):
                    if i!=index and var.get()!=value:var.set(value)
            finally:self._bleed_updating=False
        self.schedule_refresh()

    def setup_paper_captions(self):
        self.paper_combo.values=(*PAPERS,*self.paper_store.presets,'Свой размер')
        self.paper_combo.format_value=self.production_paper_caption
        self.paper_combo.format_popup_value=self.production_paper_caption
        self.paper_combo._sync()

    def production_paper_caption(self,key):
        custom=self.paper_store.presets.get(key)
        if custom:name,w,h=custom.name,custom.width,custom.height
        elif key in PAPERS:name=key;w,h=PAPERS[key]
        else:
            try:name='Пользовательский лист';w=self._number(self.paper_w_var);h=self._number(self.paper_h_var)
            except ValueError:return self.display_text('Свой размер')
        if self.unit_var.get()=='in':return f'{name} · {w/25.4:.3f} × {h/25.4:.3f} in'
        return f'{name} · {w:g} × {h:g} '+self.display_text('мм')

    def exact_relock(self,*_):
        if self.size_lock_var.get() and not self._size_updating and not self._switching_mode:
            try:self._custom_ratio=self._number(self.print_w_var)/self._number(self.print_h_var)
            except (ValueError,ZeroDivisionError):pass

    def repeat_relock(self,*_):
        if self.repeat_lock_var.get() and not self._repeat_updating:
            try:self._repeat_ratio=self._number(self.repeat_w_var)/self._number(self.repeat_h_var)
            except (ValueError,ZeroDivisionError):pass

    def repeat_dimension(self,side):
        if self._repeat_updating or not self.repeat_lock_var.get():return
        self._repeat_updating=True
        try:
            value=self._number(self.repeat_w_var if side=='width' else self.repeat_h_var)
            if value>0 and math.isfinite(value):
                other=self.repeat_h_var if side=='width' else self.repeat_w_var
                other.set(self.size_text(value/self._repeat_ratio if side=='width' else value*self._repeat_ratio))
        except (ValueError,ZeroDivisionError):pass
        finally:self._repeat_updating=False

    def repeat_original(self):
        uid=self._repeat_sources.get(self.repeat_front_var.get())
        photo=next((p for p in self.photos if p.uid==uid),None)
        if photo is None:return
        info=source_size(photo);ppi=int(self.output_ppi_var.get())
        w,h=info.physical_mm or (info.width_px*25.4/ppi,info.height_px*25.4/ppi)
        self._repeat_updating=True
        try:
            self.repeat_w_var.set(repr(w));self.repeat_h_var.set(repr(h));self._repeat_ratio=w/h
            self._repeat_initialized=True
        finally:self._repeat_updating=False
        self.schedule_refresh()

    def booklet_format_changed(self,*_):
        if self.booklet_format_var.get()=='Свой размер':return
        w,h=(148,210) if self.booklet_format_var.get().startswith('A5') else (210,297)
        self.booklet_w_var.set(str(w));self.booklet_h_var.set(str(h))

    def _sync_controls(self):
        self._legacy_sync_controls()
        mode=self.mode_var.get();repeat=mode=='Тираж';booklet=mode=='Буклет';exact=mode=='Задать размер фото'
        self.repeat_box.grid() if repeat else self.repeat_box.grid_remove()
        self.booklet_size_box.grid() if booklet else self.booklet_size_box.grid_remove()
        # Exact-size controls retain their established group above bleed controls.
        # grid_configure also maps a hidden frame. Only place this group in modes
        # that use it, or its empty surface covers the photo-count/panel controls.
        if repeat or booklet:self.production_box.grid(row=3)
        else:self.production_box.grid_remove()
        if exact:self.spacing.grid_configure(in_=self.exact_box,row=3)
        if not exact and mode!='Фото с рамкой':self.spacing.grid_configure(row=5)
        self.bleed_section.grid() if repeat or booklet or exact or mode=='Открытка со сгибом' else self.bleed_section.grid_remove()
        if repeat:self.cells_box.grid_remove();self.exact_box.grid_remove()
        for pair,entry in zip(self.copy_buttons,self.copy_entries):
            for button in pair:self._state(button,not repeat)
            self._state(entry,not repeat)
        self.repeat_back_row.grid() if self.repeat_duplex_var.get() else self.repeat_back_row.grid_remove()
        self.repeat_quantity_row.grid() if self.repeat_fill_var.get()=='Задать тираж' else self.repeat_quantity_row.grid_remove()
        fixed=booklet and self.booklet_method_var.get()=='Точный размер страницы'
        if booklet:self.duplex_info.grid_remove()
        fixed_orientation=mode in ('Буклет','Открытка со сгибом') and not fixed
        self.fixed_orientation_label.grid() if fixed_orientation else self.fixed_orientation_label.grid_remove()
        self.paper_orientation_combo.grid_remove() if fixed_orientation else self.paper_orientation_combo.grid()
        self.booklet_exact_box.grid() if fixed else self.booklet_exact_box.grid_remove()
        if fixed:self._state(self.paper_orientation_combo,True)
        signature=tuple((p.uid,p.name) for p in self.photos)
        if signature!=self._repeat_source_signature:
            previous_front=self._repeat_sources.get(self.repeat_front_var.get());previous_back=self._repeat_sources.get(self.repeat_back_var.get())
            self._repeat_sources={f'{i+1} · {p.name}':p.uid for i,p in enumerate(self.photos)}
            self.repeat_front_combo.values=tuple(self._repeat_sources)
            self.repeat_back_combo.values=('Пустой оборот',*self._repeat_sources)
            self.repeat_front_var.set(next((key for key,uid in self._repeat_sources.items() if uid==previous_front),next(iter(self._repeat_sources),'')))
            self.repeat_back_var.set(next((key for key,uid in self._repeat_sources.items() if uid==previous_back),'Пустой оборот'))
            self._repeat_source_signature=signature
        if repeat and self.photos and not self._repeat_initialized:self.repeat_original()
        if fixed:
            try:
                from .production_geometry import spread_grid
                layout=self.read_layout();grid=spread_grid(layout);capacity=grid[0]*grid[1]
                self.booklet_copies_combo.values=tuple(str(i) for i in range(1,min(100,capacity)+1)) or ('1',)
            except ValueError:pass
        self.production_hint.grid() if repeat or booklet or exact else self.production_hint.grid_remove()

    def read_layout(self):
        mode=self.mode_var.get();repeat=mode=='Тираж';fixed=mode=='Буклет' and self.booklet_method_var.get()=='Точный размер страницы'
        layout=self._legacy_read_layout()
        key=self.paper_var.get();custom=self.paper_store.presets.get(key)
        if custom or fixed:
            if custom:w,h=custom.width,custom.height
            elif key in PAPERS:w,h=PAPERS[key]
            else:w,h=self._number(self.paper_w_var),self._number(self.paper_h_var)
            landscape=self.orientation_var.get()=='Альбомная'
            if mode in ('Буклет','Открытка со сгибом') and not fixed:landscape=True
            w,h=sorted((w,h),reverse=landscape)
            layout=replace(layout,paper_width=w,paper_height=h)
        layout=replace(layout,paper_id=key,bleed=EdgeInsets(*(self._number(v) for v in self.bleed_vars)))
        if repeat:
            quantity=None
            if self.repeat_fill_var.get()=='Задать тираж':
                text=self.repeat_quantity_var.get().strip()
                if not text.isascii() or not text.isdigit() or int(text)<1:raise ValueError('Тираж должен быть целым положительным числом.')
                quantity=int(text)
            layout=replace(layout,mode='repeat',print_width=self._number(self.repeat_w_var),print_height=self._number(self.repeat_h_var),repeat_front=self._repeat_sources.get(self.repeat_front_var.get()),repeat_back=self._repeat_sources.get(self.repeat_back_var.get()),repeat_duplex=self.repeat_duplex_var.get(),repeat_quantity=quantity,flip_edge='short' if self.repeat_edge_var.get()=='Короткий край' else 'long',autorotate=True,trim_mode={'Нет':'none','Линии':'lines','Метки':'marks','Метки и линии':'both'}[self.trim_var.get()],trim_inset=self._number(self.trim_inset_var))
        if fixed:
            try:copies=int(self.booklet_copies_var.get())
            except ValueError:raise ValueError('Укажите целое число экземпляров на листе.')
            layout=replace(layout,booklet_page_size=(self._number(self.booklet_w_var),self._number(self.booklet_h_var)),booklet_copies=copies,trim_mode={'Нет':'none','Линии':'lines','Метки':'marks','Метки и линии':'both'}[self.trim_var.get()],trim_inset=0)
        if self.trim_var.get()=='Метки и линии' and layout.mode in ('booklet','postcard'):
            layout=replace(layout,trim_mode='both')
        return layout

    def refresh(self):
        self._legacy_refresh()
        if not self.layout:return
        layout=self.layout;parts=[]
        values=layout.bleed.values()
        factor=25.4 if self.unit_var.get()=='in' else 1
        shown=(values[0],) if len(set(values))==1 else values
        self.bleed_section.update_header(' / '.join(f'{v/factor:.3f}'.rstrip('0').rstrip('.') or '0' for v in shown)+(' in' if factor!=1 else ' мм'))
        if layout.mode=='repeat':
            cols,rows,*_=layout.exact_grid();qty=layout.repeat_quantity or layout.count;sheets=math.ceil(qty/layout.count);sides=sheets*(2 if layout.duplex else 1);remainder=qty%layout.count
            parts.append(f'Сетка {cols} × {rows} · вместимость {layout.count}\n{qty} изделий · {sheets} листов · {sides} сторон\nПоследний лист: {remainder or layout.count} изделий')
            self.counter_var.set(f'{qty} изделий · {sheets} листов · {sides} сторон')
        if layout.mode=='booklet' and layout.booklet_page_size:
            from .production_geometry import spread_grid
            w,h=layout.booklet_page_size;capacity=math.prod(spread_grid(layout)[:2])
            parts.append(f'Разворот {2*w:g} × {h:g} мм · доступно {capacity}\n{layout.booklet_copies} экземпляров на стороне')
        if layout.duplex:parts.append('Переворот: '+('короткий край' if layout.binding_edge=='short' else 'длинный край'))
        from .vector_pdf import pdf_export_notices
        notices=pdf_export_notices(self.photos,self.correction)
        parts.extend(notices[:2])
        if any(layout.bleed.values()):
            from .vector_pdf import bleed_shortfalls
            from .production_geometry import placements
            unique=set()
            sides=(0,1) if layout.duplex else (self.page,)
            for side in sides:
                for item in placements(self.photos,layout,side):
                    p=item.photo
                    if p.pdf_page is not None and p.uid not in unique:
                        unique.add(p.uid)
                        missing=[f'{side}: {value:.2f} мм' for side,value in zip(('слева','сверху','справа','снизу'),bleed_shortfalls(p,item.reference or item.trim,item.paint,item.autorotate,layout.paper_height,item.source_box)) if value>.01]
                        if missing:parts.append(p.name+' · не хватает вылета '+', '.join(missing))
            if any(p.pdf_page is None and p.mode=='fill' for p in self.photos):parts.append('Растр заполняет область вылета; размер после реза сохранён.')
        self.production_hint_var.set('\n'.join(parts))
        self.setup_paper_captions()

    def _paper_snapshot_before_change(self,identifier,new_size=None):
        p=self.paper_store.presets.get(identifier)
        if not p:return
        if new_size is not None and (p.width,p.height)==new_size:return
        if self.paper_var.get()==identifier:
            self.paper_w_var.set(repr(p.width));self.paper_h_var.set(repr(p.height));self.paper_var.set('Свой размер')
        for settings in self._mode_settings.values():
            if settings['paper']==identifier:settings.update(paper='Свой размер',paper_w=repr(p.width),paper_h=repr(p.height))

    def manage_papers(self):
        window=tk.Toplevel(self.root);window.title('Управление форматами');window.transient(self.root)
        body=ttk.Frame(window,padding=14);body.pack(fill='both',expand=True)
        selected=tk.StringVar(value=self.paper_var.get());name=tk.StringVar();width=tk.StringVar();height=tk.StringVar();error=tk.StringVar()
        combo=RoundedCombo(body,selected,(*PAPERS,*self.paper_store.presets));combo.pack(fill='x')
        combo.format_value=self.production_paper_caption;combo.format_popup_value=self.production_paper_caption;combo._sync()
        for caption,var in (('Название',name),('Ширина',width),('Высота',height)):
            row=ttk.Frame(body);row.pack(fill='x',pady=3);ttk.Label(row,text=caption,width=12).pack(side='left')
            if var is name:ttk.Entry(row,textvariable=var,width=28).pack(side='right')
            else:
                field=NumberSpin(row,var,minimum=1,width=14);field.bind_units(self);field.pack(side='right')
        ttk.Label(body,textvariable=error,foreground='#ad275b',wraplength=370).pack(fill='x',pady=4)
        def load(*_):
            key=selected.get();p=self.paper_store.presets.get(key)
            if p:n,w,h=p.name,p.width,p.height
            elif key in PAPERS:n=key;w,h=PAPERS[key]
            else:n,w,h='',330,488
            name.set(n);width.set(str(w));height.set(str(h));error.set('Встроенный формат можно дублировать.' if key in PAPERS else '')
        def save(new=False):
            key=selected.get()
            if key in PAPERS and not new:error.set('Встроенный формат можно только дублировать.');return
            try:
                w,h=self._number(width),self._number(height)
                from .paper_presets import PaperPreset
                PaperPreset('',name.get(),w,h).validate()
                if not new:self._paper_snapshot_before_change(key,(w,h))
                p=self.paper_store.put(name.get(),w,h,None if new or not key else key)
                combo.values=(*PAPERS,*self.paper_store.presets);selected.set(p.identifier);error.set('Сохранено.');self.setup_paper_captions();self.refresh()
            except (ValueError,OSError) as exc:error.set(str(exc))
        def delete():
            key=selected.get()
            if key not in self.paper_store.presets:error.set('Встроенный формат нельзя удалить.');return
            try:
                self._paper_snapshot_before_change(key);self.paper_store.delete(key);combo.values=(*PAPERS,*self.paper_store.presets);selected.set('A4');self.setup_paper_captions();self.refresh()
            except OSError as exc:error.set(str(exc))
        buttons=ttk.Frame(body);buttons.pack(fill='x')
        CapsuleButton(buttons,text='Создать',command=lambda:(selected.set(''),name.set('Новый формат'))).pack(side='left')
        CapsuleButton(buttons,text='Дублировать',command=lambda:save(True)).pack(side='left',padx=3)
        CapsuleButton(buttons,text='Сохранить',command=save).pack(side='left')
        CapsuleButton(buttons,text='Удалить',command=delete).pack(side='left',padx=3)
        CapsuleButton(body,text='Закрыть',command=window.destroy).pack(anchor='e',pady=(8,0))
        selected.trace_add('write',load);load();localize_tree(window);window.grab_set()
