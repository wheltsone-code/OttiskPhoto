from dataclasses import replace
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tkinter as tk
from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium

from illusive_print.app import create_root,IllusivePrintApp
from illusive_print.core import Layout,Photo,Correction,booklet_pages,page_labels,page_items,page_count,render_page,export_pdf


class DuplexGestureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.env=patch.dict('os.environ',OTTISK_PHOTO_PREFERENCES=str(self.folder/'prefs.json')); self.env.start()
        self.root=create_root(); self.app=IllusivePrintApp(self.root)
        self.paths=[]
        for i in range(12):
            path=self.folder/(f'{i:02}-'+('Очень длинное название фото '*3)+'.png')
            Image.new('RGB',(360,120),(20+i*15,80+i*10,200-i*10)).save(path); self.paths.append(path)
        self.app.add_paths(self.paths); self.root.update(); self.app.refresh()

    def tearDown(self):self.root.destroy(); self.env.stop(); self.temp.cleanup()

    def point(self,widget,x=None,y=None):
        return SimpleNamespace(x_root=widget.winfo_rootx()+(widget.winfo_width()/2 if x is None else x),y_root=widget.winfo_rooty()+(widget.winfo_height()/2 if y is None else y),widget=widget)

    def grab_panel(self,photo):
        a=self.app; a.select_photo(photo,keep_page=True); a.draw_preview(); h=a._print_handle
        self.assertIsNotNone(h)
        a.begin_drag(SimpleNamespace(x=h[0]+3,y=h[1]+3))
        self.assertIsNotNone(a._swap_from)

    def slot_event(self,slot):
        a=self.app;c=a.layout.cells()[slot]
        return SimpleNamespace(x=a.preview_origin[0]+(c.x+c.width/2)*a.preview_scale,y=a.preview_origin[1]+(c.y+c.height/2)*a.preview_scale)

    def test_postcard_swap_empty_cross_side_list_target_and_remove(self):
        a=self.app;a.mode_var.set('Открытка со сгибом');a.panel_ids=[a.photos[0].uid,a.photos[1].uid,None,None];a.refresh();self.root.update()
        a.photos[0].offset_x=.4;a.photos[0].correction=Correction(gamma=1.2)
        self.grab_panel(0);a.end_drag(self.slot_event(0))
        self.assertEqual(a.panel_ids[:2],[a.photos[1].uid,a.photos[0].uid])
        self.grab_panel(0)
        event=self.point(a.panel_buttons[2]);a.drag_motion(event)
        self.assertEqual(a.panel_buttons[2].cget('bg'),'#ffd8e9')
        a.end_drag(event)
        self.assertIsNone(a.panel_ids[1]);self.assertEqual(a.panel_ids[2],a.photos[0].uid)
        self.assertEqual(a.photos[0].offset_x,.4);self.assertEqual(a.photos[0].correction.gamma,1.2)
        a.begin_library_move(3,self.point(a.thumbnail_widgets[3][0]._handle))
        a.library_move_motion(self.point(a.panel_buttons[3]));a.end_library_move(self.point(a.panel_buttons[3]))
        self.assertEqual(a.panel_ids[3],a.photos[3].uid)
        a.panel_ids[0]=a.photos[0].uid;a.selected_rows={0};a.remove_selected()
        self.assertIsNone(a.panel_ids[0]);self.assertIsNone(a.panel_ids[2])

    def test_crop_image_does_not_swap_and_occupied_cross_side_exchange(self):
        a=self.app;a.mode_var.set('Открытка со сгибом');a.panel_ids=[p.uid for p in a.photos[:4]];a.refresh();self.root.update()
        original=list(a.panel_ids);event=self.slot_event(1)
        a.begin_drag(event);a.drag_motion(SimpleNamespace(x=event.x+30,y=event.y));a.end_drag()
        self.assertEqual(a.panel_ids,original);self.assertNotEqual(a.photos[0].offset_x,0)
        self.grab_panel(0);a.end_drag(self.point(a.panel_buttons[3]))
        self.assertEqual(a.panel_ids,[original[3],original[1],original[2],original[0]])

    def test_booklet_covers_padding_reorder_navigation_counts_and_pdf(self):
        a=self.app
        a.selected_rows=set(range(5,12));a.remove_selected();a.mode_var.set('Буклет');a.refresh();self.root.update()
        self.assertEqual([label for token,label in booklet_pages(a.photos,a.layout)],['0','1','2','3','4','5','6','END'])
        self.assertEqual(page_labels(a.photos,a.layout,0),('END','0'))
        covers=list(a.booklet_cover_ids);first_internal=a.photos[1].uid
        a.begin_library_move(1,self.point(a.thumbnail_widgets[1][0]._handle));a._library_target=4;a.end_library_move(None)
        self.assertEqual(a.booklet_cover_ids,covers)
        inside=[t[0] for t,label in booklet_pages(a.photos,a.layout) if t and label not in ('0','END')]
        self.assertEqual(inside[-1],first_internal)
        self.assertEqual(a.counter_var.get(),'2 листа · 4 стороны')
        a.select_photo(0);self.assertEqual(a.page,0)
        a.select_photo(2);self.assertTrue(any(i==2 for i,p in page_items(a.photos,a.layout,a.page)))
        destination=self.folder/'booklet.pdf';export_pdf(destination,a.photos,a.layout,Correction())
        self.assertEqual(len(PdfReader(destination).pages),4)
        doc=pdfium.PdfDocument(destination)
        for page in range(4):
            raster=render_page(a.photos,a.layout,page,Correction(),1)
            rendered=doc[page].render(scale=25.4/72).to_pil().convert('RGB')
            for x in (40,230):self.assertLessEqual(max(abs(c-d) for c,d in zip(raster.getpixel((x,70)),rendered.getpixel((x,70)))),1)
        doc.close()

    def test_booklet_editable_blanks_keep_volume_and_pdf_panels(self):
        a=self.app
        a.selected_rows={9,10,11};a.remove_selected()
        a.mode_var.set('Буклет');a.refresh();self.root.update()
        self.assertEqual(len(booklet_pages(a.photos,a.layout)),12)
        self.assertEqual(a.counter_var.get(),'3 листа · 6 сторон')
        covers=a.booklet_cover_ids[:]
        self.assertEqual(len(a._booklet_cards),12)
        self.assertEqual(sum(leaf['token'] is None for leaf in a.booklet_leaves),3)
        # Move the first automatically added blank immediately after the cover.
        frame=a._booklet_cards[8]
        a.begin_booklet_move(7,self.point(frame._handle))
        a._library_target=0;a.end_library_move(None);self.root.update()
        self.assertIsNone(a.booklet_leaves[0]['token'])
        self.assertFalse(a.booklet_leaves[0]['auto'])
        labels=[w.cget('text') for w in a._booklet_cards[1].winfo_children() if isinstance(w,tk.Label)]
        self.assertIn('1 · Пустая страница',labels)
        # Fill a different blank by dropping a photo on the preview panel.
        source=1;target=8;token=a.booklet_leaves[source]['token']
        a.select_booklet_page(target);self.root.update()
        deadline=time.monotonic()+10
        while a._preview_pending and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        a.draw_preview()
        slot=a._selected_instance[1]
        a.begin_booklet_photo_drag(source,self.point(a._booklet_cards[source+1].grid_slaves(row=0,column=1)[0]))
        drop=self.slot_event(slot)
        self.assertEqual(a.preview_slot_at(*a.event_root(drop)),slot)
        self.assertIsNone(a.target_at(*a.event_root(drop)))
        a.end_library_move(drop);self.root.update()
        self.assertEqual(a.booklet_leaves[target]['token'],token)
        self.assertIsNone(a.booklet_leaves[source]['token'])
        self.assertEqual(len(booklet_pages(a.photos,a.layout)),12)
        # Preview handle swaps a photo with a blank on the same printed side.
        a.select_booklet_page(1);self.root.update();a.draw_preview()
        deadline=time.monotonic()+10
        while a._preview_pending and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        a.draw_preview();h=a._print_handle;self.assertIsNotNone(h)
        a.begin_drag(SimpleNamespace(x=h[0]+3,y=h[1]+3))
        a.end_drag(self.slot_event(1-a._selected_instance[1]))
        self.assertIsNotNone(a.booklet_leaves[1]['token'])
        self.assertIsNone(a.booklet_leaves[8]['token'])
        before=tuple(leaf['token'] for leaf in a.booklet_leaves)
        for _ in range(3):a.refresh()
        self.assertEqual(tuple(leaf['token'] for leaf in a.booklet_leaves),before)
        destination=self.folder/'editable-booklet.pdf';export_pdf(destination,a.photos,a.layout,Correction())
        reader=PdfReader(destination);self.assertEqual(len(reader.pages),6)
        self.assertTrue(all(not page.extract_text().strip() for page in reader.pages))
        doc=pdfium.PdfDocument(destination)
        for page in range(6):
            raster=render_page(a.photos,a.layout,page,Correction(),1)
            rendered=doc[page].render(scale=25.4/72).to_pil().convert('RGB')
            for slot,cell in enumerate(a.layout.cells()):
                x,y=round(cell.x+cell.width/2),round(cell.y+cell.height/2)
                self.assertLessEqual(max(abs(c-d) for c,d in zip(raster.getpixel((x,y)),rendered.getpixel((x,y)))),1)
                if page_items(a.photos,a.layout,page)[slot][0]<0:self.assertEqual(rendered.getpixel((x,y)),(255,255,255))
        doc.close()
        # Clearing and removing a source retain its reading position.
        position=next(i for i,leaf in enumerate(a.booklet_leaves) if leaf['token'])
        a.edit_booklet_page(position)
        self.assertIsNone(a.booklet_leaves[position]['token']);self.assertEqual(len(a.booklet_leaves),10)
        position=next(i for i,leaf in enumerate(a.booklet_leaves) if leaf['token'])
        uid=a.booklet_leaves[position]['token'][0]
        a.selected_rows={next(i for i,p in enumerate(a.photos) if p.uid==uid)};a.remove_selected()
        self.assertIsNone(a.booklet_leaves[position]['token']);self.assertEqual(len(a.booklet_leaves),10)
        a.add_paths(self.paths[9:10]);a.refresh()
        self.assertIsNone(a.booklet_leaves[0]['token'])
        self.assertIsNone(a.booklet_leaves[position]['token'])
        self.assertEqual(len(booklet_pages(a.photos,a.layout)),12)
        a.selected=-1;a._booklet_selected=None;a.insert_booklet_blank()
        self.assertIsNone(a.booklet_leaves[10]['token']);self.assertFalse(a.booklet_leaves[10]['auto'])
        a.add_paths(self.paths[10:11]);a.refresh()
        self.assertIsNone(a.booklet_leaves[10]['token']);self.assertFalse(a.booklet_leaves[10]['auto'])
        a.select_booklet_page(1);a.insert_booklet_blank()
        self.assertIsNone(a.booklet_leaves[2]['token']);self.assertFalse(a.booklet_leaves[2]['auto'])
        a.edit_booklet_page(2,delete=True)
        self.assertEqual(a.booklet_cover_ids,covers)

    def test_empty_covers_numbered_blanks_ordered_cards_and_duplicate(self):
        a=self.app
        a.selected_rows={9,10,11};a.remove_selected()
        a.mode_var.set('Буклет');a.refresh();self.root.update()
        a.apply_booklet_blank_numbers('1,4')
        self.assertEqual(a.booklet_blank_summary(),'1, 4, 10')
        self.assertEqual([f._position for f in a._booklet_cards],['0']+list(range(10))+['END'])
        before=a.layout
        # Both pinned positions may be genuinely blank and stay blank on refresh.
        a.edit_booklet_page('0');a.edit_booklet_page('END')
        for _ in range(3):a.refresh()
        self.assertEqual(a.booklet_cover_ids,[None,None])
        self.assertEqual([i for i,p in page_items(a.photos,a.layout,0)],[-1,-1])
        self.assertIsNone(booklet_pages(a.photos,a.layout)[0][0])
        self.assertIsNone(booklet_pages(a.photos,a.layout)[-1][0])
        a.page=0;a.select_booklet_page('0');self.root.update()
        deadline=time.monotonic()+10
        while a._preview_pending and time.monotonic()<deadline:self.root.update();time.sleep(.01)
        a.draw_preview()
        badges=[a.preview_canvas.itemcget(item,'text') for item in a.preview_canvas.find_withtag('page_badge')]
        self.assertTrue(any('0' in b and 'Пустая страница' in b for b in badges))
        self.assertTrue(any('END' in b and 'Пустая страница' in b for b in badges))
        self.assertEqual(len(a.preview_canvas.find_withtag('page_badge_background')),2)
        # Filling the empty front cover transfers the photo, preserving 12 pages.
        source=next(i for i,p in enumerate(a.booklet_leaves) if p['token'])
        token=a.booklet_leaves[source]['token']
        a.begin_booklet_move(source,self.point(a._booklet_cards[source+1]._handle))
        a.end_library_move(self.slot_event(1))
        self.assertEqual(a.booklet_cover_ids[0],token[0]);self.assertIsNone(a.booklet_leaves[source]['token'])
        self.assertEqual(len(booklet_pages(a.photos,a.layout)),12)
        # A duplicate is a new editable photo and a separate reading card.
        source=next(i for i,p in enumerate(a.booklet_leaves) if p['token'])
        uid=a.booklet_leaves[source]['token'][0]
        index=next(i for i,p in enumerate(a.photos) if p.uid==uid)
        a.photos[index].offset_x=.37;a.photos[index].correction=Correction(gamma=1.2)
        a.duplicate_photo(index,source)
        clone=a.photos[-1]
        self.assertNotEqual(clone.uid,uid);self.assertEqual(clone.path,a.photos[index].path)
        self.assertEqual((clone.copies,clone.offset_x,clone.correction),(1,.37,Correction(gamma=1.2)))
        self.assertEqual(a.booklet_leaves[source+1]['token'],(clone.uid,0))
        clone.offset_x=-.4;clone.correction=Correction(gamma=.8)
        self.assertEqual((a.photos[index].offset_x,a.photos[index].correction),(.37,Correction(gamma=1.2)))
        # Import, duplicate and rebuild must never pack source rows after END.
        a.add_paths(self.paths[9:10]);a.rebuild_library();a.refresh();self.root.update()
        packed=[widget for widget in a.library_inner.pack_slaves() if widget.winfo_manager()=='pack']
        self.assertEqual(packed,a._booklet_cards)
        self.assertEqual(a._booklet_cards[-1]._position,'END')
        self.assertEqual([f._position for f in a._booklet_cards[1:-1]],list(range(len(a.booklet_leaves))))
        # Copied instances remain individually numbered in the reading list.
        a.change_copies(index,1)
        self.assertIn((uid,1),[p['token'] for p in a.booklet_leaves])
        dest=self.folder/'empty-cover.pdf';a.edit_booklet_page('0');a.edit_booklet_page('END')
        export_pdf(dest,a.photos,a.layout,Correction())
        doc=pdfium.PdfDocument(dest)
        raster=doc[0].render(scale=25.4/72).to_pil().convert('RGB')
        self.assertEqual(raster.getextrema(),((255,255),)*3)
        self.assertFalse(PdfReader(dest).pages[0].extract_text().strip());doc.close()

    def test_duplicate_outside_booklet_is_a_separate_next_card(self):
        a=self.app;source=a.photos[2];a.duplicate_photo(2)
        clone=a.photos[3]
        self.assertEqual(clone.path,source.path);self.assertNotEqual(clone.uid,source.uid)
        self.assertEqual(len(a.photos),13)
        a.mode_var.set('Буклет');a.refresh()
        a.insert_booklet_at('0',True,2)
        self.assertTrue(all(p['token'] is None and not p['auto'] for p in a.booklet_leaves[:2]))
        a.insert_booklet_at('END',False)
        self.assertTrue(any(p['token'] is None and not p['auto'] for p in a.booklet_leaves))
        with self.assertRaises(ValueError):a.insert_booklet_at('END',True)

    def test_scrollbar_handle_names_and_navigation_geometry(self):
        a=self.app;self.root.geometry('1080x700');self.root.update()
        self.assertEqual(a.library_scrollbar.winfo_manager(),'grid')
        frame,thumb,label=a.thumbnail_widgets[0][:3]
        self.assertLess(frame._handle.winfo_x(),thumb.winfo_x())
        self.assertIn('…',label.cget('text'))
        before=a.library_canvas.yview()[0]
        scroll=a.library_scrollbar;y,length,_=scroll.geometry_values()
        scroll.press(SimpleNamespace(y=y+length/2));scroll.motion(SimpleNamespace(y=y+length/2+60));scroll.release(None)
        self.assertGreater(a.library_canvas.yview()[0],before)
        a.library_canvas.yview_moveto(0);self.root.update()
        a.begin_library_move(0,self.point(frame._handle));a._library_pointer=(a.library_canvas.winfo_rootx()+10,a.library_canvas.winfo_rooty()+a.library_canvas.winfo_height()-2)
        self.root.after_cancel(a._library_scroll_job);a._library_scroll_job=None
        a.library_autoscroll();self.root.update();self.assertGreater(a.library_canvas.yview()[0],0);a.end_library_move(None)
        a.mode_var.set('Буклет');a.refresh();self.root.update()
        for left,right in ((a.previous_button,a.page_label),(a.page_label,a.next_button)):
            self.assertLessEqual(left.winfo_rootx()+left.winfo_width(),right.winfo_rootx())

    def test_cover_replacement_does_not_insert_old_cover_as_inside(self):
        a=self.app;a.mode_var.set('Буклет');a.refresh()
        old=a.booklet_cover_ids[0];source=a.photos[2].uid
        a.assign_cover(0,uid=source)
        reading=booklet_pages(a.photos,a.layout)
        self.assertEqual(reading[0][0],(source,0))
        self.assertNotIn(old,[token[0] for token,label in reading if token and label not in ('0','END')])
        before=a.booklet_cover_ids[:]
        a.cover_targets[0].event_generate('<Button-1>');self.root.update()
        self.assertEqual(a.booklet_cover_ids,before)
        self.assertEqual(a.photos[a.selected].uid,source)

    def test_handle_press_release_without_motion_recomputes_insertion(self):
        a=self.app;first=a.photos[0].uid;handle=a.thumbnail_widgets[0][0]._handle
        target=a.thumbnail_widgets[3][0]
        x=target.winfo_rootx()+target.winfo_width()/2
        y=target.winfo_rooty()+2
        handle.event_generate('<ButtonPress-1>',x=2,y=2);self.root.update()
        handle.event_generate('<ButtonRelease-1>',x=2,y=2,rootx=int(x),rooty=int(y));self.root.update()
        self.assertEqual(a.photos[2].uid,first)

