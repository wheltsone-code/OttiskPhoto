"""Bounded local import worker; every Tk operation remains on the UI thread."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageOps, ImageTk
from .core import Photo, SUPPORTED
from .document_sources import pdf_pages
from .preview import load_preview_source
from .vector_import import VECTOR_EXTENSIONS, prepare_document, ImportCancelled, cancelled
from .i18n import localize_tree, messagebox
from .metadata import set_icon


class ImportMixin:
    def start_import(self, paths, folder_batch=False, skipped=0):
        if getattr(self, '_import_job', None) is not None:
            self._import_job['cancel'].set()
            self.status_var.set('Отмена… / Cancelling…')
            return
        paths = tuple(Path(p).resolve() for p in paths)
        policy = None
        if folder_batch and any(p.suffix.lower() in VECTOR_EXTENSIONS|{'.pdf'} for p in paths):
            policy = self.choose_pdf_import()
        events = queue.Queue(maxsize=3)
        event = threading.Event()
        window = tk.Toplevel(self.root); window.transient(self.root); set_icon(window)
        window.title(self.display_text('Подготовка документов…'))
        label = ttk.Label(window, text=self.display_text('Подготовка документов…'), width=60)
        label.pack(padx=16,pady=10)
        bar = ttk.Progressbar(window, maximum=max(1,len(paths)), length=400)
        bar.pack(padx=16,pady=4)
        ttk.Button(window,text=self.display_text('Отмена'),command=event.set).pack(pady=10)
        window.protocol('WM_DELETE_WINDOW',event.set)
        localize_tree(window)
        job = dict(cancel=event, events=events, window=window, label=label, bar=bar,
                   added=0, skipped=skipped, errors=[], warnings=[], existing={(p.path.resolve(),p.pdf_page) for p in self.photos})
        self._import_job = job
        self._interactive_background = True
        self.root._ottisk_import_pending = True
        def emit(value):
            while not event.is_set():
                try: events.put(value, timeout=.05); return
                except queue.Full: pass
            raise ImportCancelled()
        def worker():
            try:
                for number,path in enumerate(paths):
                    cancelled(event)
                    emit(('progress', number, path.name))
                    try:
                        if path.suffix.lower() not in SUPPORTED: raise ValueError('Неподдерживаемый формат файла / Unsupported file format')
                        document = path.suffix.lower() in VECTOR_EXTENSIONS|{'.pdf'}
                        if document and folder_batch and policy in (None,'Пропустить PDF'):
                            emit(('skip',)); continue
                        if path.suffix.lower() in VECTOR_EXTENSIONS:
                            result = prepare_document(path,event)
                            if result.warnings: emit(('warnings',path.name,result.warnings))
                        pages = [None]
                        if document:
                            count = pdf_pages(path)
                            if count==1 or policy=='Только первые страницы': pages=[0]
                            elif policy=='Все страницы': pages=list(range(count))
                            else:
                                response=queue.Queue(maxsize=1)
                                emit(('choose',path,count,response))
                                while True:
                                    cancelled(event)
                                    try: pages=response.get(timeout=.05); break
                                    except queue.Empty: pass
                                if pages is None: emit(('skip',)); continue
                        for page in pages:
                            cancelled(event)
                            if (path,page) in job['existing']: emit(('skip',)); continue
                            photo=Photo(path,pdf_page=page)
                            image=load_preview_source(photo)
                            cancelled(event)
                            thumb=ImageOps.contain(image,(90,72),Image.Resampling.LANCZOS)
                            emit(('photo',photo,thumb))
                    except ImportCancelled: raise
                    except Exception as error: emit(('error',path.name+': '+str(error)))
                emit(('done',))
            except ImportCancelled: pass
            finally: job['finished'].set()
        job['finished']=threading.Event()
        job['thread']=threading.Thread(target=worker,name='OttiskImport',daemon=True)
        job['thread'].start()
        self._import_poll_job=self.root.after(16,self.poll_import)

    def poll_import(self):
        self._import_poll_job=None
        job=self._import_job
        if self._closing: job['cancel'].set(); return
        changed=False
        try:
            # Bounded UI work per tick, even when all documents are cached.
            for _ in range(3):
                message=job['events'].get_nowait(); kind,*args=message
                if job['cancel'].is_set(): continue
                if kind=='photo':
                    photo,thumb=args
                    if (photo.path,photo.pdf_page) in job['existing']: job['skipped']+=1; continue
                    image=ImageTk.PhotoImage(thumb,master=self.root)
                    self.photos.append(photo); self.thumbnail_images.append(image)
                    self._add_thumbnail(len(self.photos)-1,image)
                    job['existing'].add((photo.path,photo.pdf_page)); job['added']+=1; changed=True
                elif kind=='choose':
                    path,count,response=args
                    response.put(self.choose_pdf_import(path,count))
                elif kind=='progress':
                    number,name=args; job['bar']['value']=number; job['label'].configure(text=name)
                elif kind=='skip': job['skipped']+=1
                elif kind=='error': job['errors'].append(args[0]); job['skipped']+=1
                elif kind=='warnings': job['warnings'].extend(args[0]+': '+w for w in args[1])
        except queue.Empty: pass
        if changed:
            self.empty_label.pack_forget()
            if self.selected<0:
                self.selected=0;self.selected_rows={0};self.selection_anchor=0
            self.update_selection();self.custom_preset_changed();self.refresh()
        if job['finished'].is_set() and (job['events'].empty() or job['cancel'].is_set()):
            job['window'].destroy();self._import_job=None
            self.root._ottisk_import_pending=False
            self.last_import_errors=job['errors'];self.last_import_warnings=job['warnings']
            self.status_var.set(f"Добавлено {job['added']} фото, пропущено {job['skipped']} файлов"+
                                (' · Отменено / Cancelled' if job['cancel'].is_set() else ''))
            if job['errors']:
                self.status_var.set(self.status_var.get()+' · '+job['errors'][0])
                from .diagnostics import record
                for error in job['errors']: record('import.file.error',error=error)
            if job['warnings']: messagebox.showwarning('Предупреждения импорта','\n'.join(dict.fromkeys(job['warnings']))[:8000],parent=self.root)
            return
        self._import_poll_job=self.root.after(16,self.poll_import)
