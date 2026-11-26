import ctypes
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import win32gui

from illusive_print.app import create_root, IllusivePrintApp
from illusive_print.file_drop import folder_images


def send_drop(hwnd, paths):
    """Exercise the registered Tcl/TkDnD callback, explicitly not a mouse gesture."""
    widget = hwnd
    payload = widget.tk.call('format','%s',widget.tk.call('list',*map(str,paths)))
    command = widget.tk.splitlist(widget.dnd_bind('<<Drop>>'))[0]
    result=widget.tk.call(command,'copy','copy',1,'','','','',payload,'Drop','','','','DND_Files','','',str(widget),0,0)
    # Import now runs off the UI thread. Drive the real event loop to completion.
    import time
    root=widget.winfo_toplevel()
    root.update()
    until=time.monotonic()+60
    while getattr(root,'_ottisk_import_pending',False) and time.monotonic()<until:
        root.update();time.sleep(.01)
    assert not getattr(root,'_ottisk_import_pending',False), 'background import timed out'
    return result


class FileDropTests(unittest.TestCase):
    def test_tcl_paths_braces_bad_file_and_diagnostic_boundary(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(Path(folder)/'preferences.json')}):
            folder = Path(folder)
            good = folder/'{Фото} с пробелами.jpg'
            bad = folder/'Повреждённый.jpg'
            Image.new('RGB',(100,80),'red').save(good)
            bad.write_bytes(b'not a jpeg')
            root = create_root()
            app = IllusivePrintApp(root)
            try:
                root.update()
                send_drop(app.preview_canvas,[good,bad])
                root.update()
                self.assertEqual([p.path for p in app.photos],[good])
                self.assertEqual(len(app.last_import_errors),1)
                self.assertIn('Повреждённый.jpg',app.status_var.get())
                self.assertEqual(app.explorer_drop.drop(SimpleNamespace(widget=app.preview_canvas,data='{')),'refuse_drop')
                self.assertIn('import.drop.error',(folder/'diagnostics.jsonl').read_text(encoding='utf-8'))
            finally:
                root.destroy()

    def test_tcl_multi_folder_append_skip_unicode_and_mouse_bindings(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'OTTISK_PHOTO_PREFERENCES':str(Path(folder)/'preferences.json')}):
            folder = Path(folder)
            photos = []
            for name in ('Первое фото.jpg','Второе фото.png'):
                path = folder/name
                Image.new('RGB',(300,200),'red').save(path)
                photos.append(path)
            album = folder/'Папка с кириллицей'
            album.mkdir()
            Image.new('RGB',(200,300),'blue').save(album/'Третье фото.JPEG')
            (album/'не фото.txt').write_text('unsupported',encoding='utf-8')
            (album/'подпапка').mkdir()
            Image.new('RGB',(30,30)).save(album/'подпапка'/'не импортировать.png')
            root = create_root()
            app = IllusivePrintApp(root)
            try:
                root.update()
                bindings = [app.preview_canvas.bind(event) for event in ('<Button-1>','<B1-Motion>','<ButtonRelease-1>')]
                send_drop(root,photos)
                root.update()
                self.assertEqual([p.path for p in app.photos],photos)
                self.assertIn('Добавлено 2',app.status_var.get())
                self.assertTrue(all(bindings))
                send_drop(app.preview_canvas,[album,photos[0]])
                root.update()
                self.assertEqual(len(app.photos),3)
                self.assertIn('Добавлено 1 фото, пропущено 2 файлов',app.status_var.get())
                self.assertEqual(len(folder_images(album)[0]),1)
                self.assertEqual(bindings,[app.preview_canvas.bind(event) for event in ('<Button-1>','<B1-Motion>','<ButtonRelease-1>')])
                self.assertEqual(len(app.thumbnail_widgets),3)
                self.assertEqual(app.layout.count,1)
                app.language_var.set('English')
                self.assertEqual(app.display_text('Перетащите фото или папку сюда'),'Drop photos or a folder here')
                self.assertNotIn('фото',app.display_text(app.status_var.get()))
            finally:
                root.destroy()
            self.assertEqual(len(app.explorer_drop.targets),3)


if __name__ == '__main__':
    unittest.main()
