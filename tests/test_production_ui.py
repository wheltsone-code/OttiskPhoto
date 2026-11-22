import gc,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from illusive_print.app import create_root,IllusivePrintApp
from illusive_print.core import page_count,page_items
from tests.support import make_photos


class ProductionUITests(unittest.TestCase):
    def setUp(self):
        gc.collect();self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,OTTISK_PHOTO_PREFERENCES=str(Path(self.temp.name)/'preferences.json'));self.env.start()
        self.root=create_root();self.app=IllusivePrintApp(self.root)
        self.app.add_paths(make_photos(Path(self.temp.name)/'photos')[:2]);self.root.update()

    def tearDown(self):
        self.root.destroy();self.env.stop();self.temp.cleanup()

    def repeat(self):
        a=self.app;a.mode_var.set('Тираж');a.repeat_lock_var.set(False)
        a.repeat_w_var.set('60');a.repeat_h_var.set('40');a.margin_var.set('0');a.repeat_fill_var.set('Задать тираж');a.repeat_quantity_var.set('100');a.refresh()
        return a

    def test_impossible_crop_marks_keep_preview_and_disable_only_output(self):
        a=self.repeat();a.repeat_w_var.set('90');a.repeat_h_var.set('50')
        a.paper_var.set('Свой размер');a.paper_w_var.set('90');a.paper_h_var.set('50')
        a.orientation_var.set('Альбомная');a.repeat_quantity_var.set('1')
        a.trim_var.set('Метки');a.trim_inset_var.set('0');a.refresh();self.root.update()
        self.assertIsNotNone(a.layout)
        self.assertTrue(a._mark_issues)
        self.assertIn('Метка',a.quality_var.get())
        self.assertTrue(a.preview_canvas.find_withtag('preview_base'))
        self.assertEqual(str(a.save_button.cget('state')),'disabled')
        self.assertEqual(str(a.print_button.cget('state')),'disabled')
        a.trim_var.set('Нет');a.refresh();self.root.update()
        self.assertFalse(a._mark_issues)
        self.assertEqual(str(a.save_button.cget('state')),'normal')

    def test_exact_has_no_empty_production_container_after_mode_cycle(self):
        a=self.app;self.root.geometry('1080x768')
        for mode in ('Тираж','Задать размер фото','Тираж','Задать размер фото'):
            a.mode_var.set(mode);a.refresh();self.root.update()
            if mode!='Задать размер фото':continue
            self.assertFalse(a.production_box.winfo_ismapped())
            for opened in (True,False,True,False):
                a.layout_advanced.set_open(opened);self.root.update()
                gap=a.bleed_section.winfo_rooty()-(a.layout_advanced.winfo_rooty()+a.layout_advanced.winfo_height())
                self.assertGreaterEqual(gap,0);self.assertLess(gap,15)

    def test_collapsed_bleed_header_shows_actual_values_and_units(self):
        a=self.repeat();a.bleed_section.set_open(False);a.refresh()
        self.assertEqual(a.bleed_section.summary,'0 мм')
        a.bleed_lock_var.set(False)
        for var,value in zip(a.bleed_vars,('1','2','3','4')):var.set(value)
        a.refresh();self.assertEqual(a.bleed_section.summary,'1 / 2 / 3 / 4 мм')
        a.unit_var.set('in');a.refresh()
        self.assertEqual(a.bleed_section.summary,'0.039 / 0.079 / 0.118 / 0.157 in')
        self.assertEqual(a.layout.bleed.values(),(1,2,3,4))

    def test_combined_cut_defaults_memory_warning_and_invalid_preview(self):
        a=self.repeat();a.repeat_w_var.set('94');a.repeat_h_var.set('54');a.margin_var.set('7')
        a.trim_inset_var.set('1');a.trim_var.set('Метки и линии');a.refresh();self.root.update()
        self.assertEqual((a.layout.mark_inset,a.layout.line_inset),(2,0))
        self.assertIn('90 × 50',a.trim_hint_var.get())
        self.assertTrue(a.combined_trim_box.winfo_manager());self.assertFalse(a.trim_entry.winfo_manager())
        a.mark_inset_var.set('3');a.line_inset_var.set('1')
        for mode in ('Метки','Линии','Метки и линии'):
            a.trim_var.set(mode);a.refresh()
            self.assertEqual(a.trim_inset_var.get(),'1')
        self.assertEqual((a.layout.mark_inset,a.layout.line_inset),(3,1))
        a.line_inset_var.set('3');a.refresh();self.assertIn('штриха',a.quality_var.get())
        a.mark_inset_var.set('27');a.refresh();self.root.update()
        self.assertIsNotNone(a.layout);self.assertIsNotNone(a._cut_error)
        self.assertTrue(a.preview_canvas.find_withtag('preview_base'));self.assertTrue(a.preview_canvas.find_withtag('invalid_cut'))
        self.assertEqual(str(a.save_button.cget('state')),'disabled')
        a.mark_inset_var.set('3');a.refresh();self.assertIsNone(a._cut_error)
        self.assertEqual(a.layout.trim_mode,'both');self.assertEqual(str(a.save_button.cget('state')),'normal')

    def test_invalid_cut_also_blocks_keyboard_and_direct_export_handlers(self):
        a=self.repeat();a.trim_var.set('Метки и линии');a.mark_inset_var.set('30');a.refresh()
        self.assertIsNotNone(a._cut_error)
        with patch('illusive_print.app.filedialog.asksaveasfilename') as choose,patch('illusive_print.print_dialog.PrintDialog') as dialog:
            a.save_pdf();a.print_order()
            choose.assert_not_called();dialog.assert_not_called()
        dest=Path(self.temp.name)/'must-not-exist.pdf';a._start_export(dest)
        self.assertFalse(a._exporting);self.assertFalse(dest.exists())

    def test_bleed_section_has_own_row_and_pushes_following_controls(self):
        a=self.app
        for mode in ('Открытка со сгибом','Буклет','Открытка со сгибом'):
            a.mode_var.set(mode);a.refresh();self.root.update()
            self.assertTrue(a.bleed_section.winfo_ismapped())
            self.assertEqual(a.bleed_section.master,a.settings_inner)
            a.bleed_section.set_open(False);self.root.update()
            closed_y=a.trim_section.winfo_y()
            a.bleed_section.toggle();self.root.update()
            self.assertGreater(a.trim_section.winfo_y(),closed_y)
            self.assertGreaterEqual(a.bleed_section.winfo_y(),a.spacing.winfo_y()+a.spacing.winfo_height())
            if mode=='Открытка со сгибом':
                self.assertGreaterEqual(a.bleed_section.winfo_y(),a.panel_box.winfo_y()+a.panel_box.winfo_height())
            self.assertTrue(all(e.winfo_ismapped() for e in a.bleed_entries))
            self.assertTrue(a.bleed_lock_check.winfo_ismapped())
            a.bleed_section.toggle();self.root.update()
            self.assertEqual(a.trim_section.winfo_y(),closed_y)

    def test_bleed_link_input_arrows_and_restore_without_cascade(self):
        a=self.app;a.mode_var.set('Буклет');self.assertTrue(a.bleed_lock_var.get())
        with patch.object(a,'schedule_refresh') as refresh:
            a.bleed_entries[2].unit_display.set('3')
            self.assertEqual([a._number(v) for v in a.bleed_vars],[3]*4)
            refresh.assert_called_once();refresh.reset_mock()
            a.bleed_entries[1].step(1)
            self.assertEqual([a._number(v) for v in a.bleed_vars],[4]*4)
            refresh.assert_called_once();refresh.reset_mock()
            a.bleed_lock_check.invoke();a.bleed_entries[0].unit_display.set('2,5')
            self.assertEqual([a._number(v) for v in a.bleed_vars],[2.5,4,4,4])
            refresh.assert_called_once();refresh.reset_mock()
            a.bleed_lock_check.invoke()
            self.assertEqual([a._number(v) for v in a.bleed_vars],[2.5,4,4,4])
            refresh.assert_not_called()
        a.mode_var.set('Открытка со сгибом');a.mode_var.set('Буклет')
        self.assertEqual([a._number(v) for v in a.bleed_vars],[2.5,4,4,4])
        self.assertTrue(a.bleed_lock_var.get())

    def test_brightness_caption_preserves_gamma_control(self):
        a=self.app
        for language,caption,gamma in (('Русский','Яркость','Гамма'),('English','Brightness','Gamma')):
            a.language_var.set(language);a.color_section.set_open(True);a.open_advanced();self.root.update()
            self.assertEqual(a._advanced.title(),caption)
            labels=[str(w.cget('text')) for w in a.gamma_scale.master.winfo_children() if 'text' in w.keys()]
            self.assertIn(gamma,labels)
            a.gamma_scale._changed('1.3');self.assertAlmostEqual(a._number(a.gamma_var),1.3)
            a.gamma_scale.reset();self.assertAlmostEqual(a._number(a.gamma_var),1)
            a._advanced.destroy()

    def test_unit_binding_is_idempotent_and_destroy_has_no_callback_errors(self):
        a=self.app;field=a.bleed_entries[0]
        display=field.unit_display;traces=field.variable.trace_info()
        field.bind_units(a);field.bind_units(a)
        self.assertIs(field.unit_display,display)
        self.assertEqual(field.variable.trace_info(),traces)
        errors=[];self.root.report_callback_exception=lambda *args:errors.append(args)
        field.destroy();self.root.update()
        self.assertEqual(errors,[])

    def test_empty_booklet_builds_complete_cards_without_interrupting_refresh(self):
        self.root.destroy();self.root=create_root();self.app=IllusivePrintApp(self.root)
        a=self.app;errors=[];self.root.report_callback_exception=lambda *args:errors.append(args)
        for mode in ('Буклет','Открытка со сгибом','Разделить лист','Буклет'):
            a.mode_var.set(mode);self.root.update()
        self.assertEqual(errors,[])
        self.assertEqual(len(a.booklet_leaves),2)
        self.assertEqual(len(a._booklet_cards),4)
        self.assertTrue(a.color_section.winfo_ismapped())

    def test_repeat_numeric_draft_lock_and_scroll_collapse(self):
        from illusive_print.round_scrollbar import RoundScrollbar
        a=self.repeat();entry=next(e for e in a.production_fields if e.variable is a.repeat_w_var)
        previous=a.repeat_w_var.get();entry.unit_display.set('');a.refresh()
        self.assertEqual(a.repeat_w_var.get(),previous);self.assertIsNotNone(a.layout)
        entry.unit_display.set('NaN');entry._commit_unit();self.assertEqual(entry.unit_display.get(),previous)
        entry.unit_display.set('61,5');self.assertEqual(a._number(a.repeat_w_var),61.5)
        before=(a.repeat_w_var.get(),a.repeat_h_var.get());a.repeat_lock_button.invoke()
        self.assertEqual((a.repeat_w_var.get(),a.repeat_h_var.get()),before)
        a.repeat_quantity_entry.unit_display.set('');a.refresh();self.assertEqual(a.layout.repeat_quantity,100)
        a.repeat_quantity_entry._commit_unit();self.assertEqual(a.repeat_quantity_entry.unit_display.get(),'100')
        self.assertIsInstance(a.settings_scrollbar,RoundScrollbar)
        a.color_section.set_open(True);a.bleed_section.set_open(True);a.trim_section.set_open(True);self.root.update()
        a.settings_canvas.yview_moveto(1);self.root.update()
        a.color_section.set_open(False);a.bleed_section.set_open(False);a.trim_section.set_open(False);self.root.update()
        first,last=a.settings_canvas.yview();self.assertTrue(0<=first<=last<=1)
        self.assertGreaterEqual(a.settings_scrollbar.winfo_x(),a.settings_canvas.winfo_x()+a.settings_canvas.winfo_width())

    def test_repeat_duplex_labels_and_deleting_assigned_back(self):
        a=self.repeat();a.repeat_duplex_check.invoke();a.repeat_back_var.set(list(a._repeat_sources)[1]);a.refresh();self.root.update()
        check=a.repeat_duplex_check
        self.assertEqual(check.itemcget(check.find_withtag('check_label')[0],'text'),'Двусторонний тираж')
        bounds=check.bbox('check_label');self.assertLessEqual(bounds[2],check.winfo_width());self.assertLessEqual(bounds[3],check.winfo_height())
        self.assertTrue(a.repeat_back_row.winfo_ismapped())
        a.selected=1;a.selected_rows={1};a.remove_selected();self.root.update()
        self.assertIsNone(a.layout.repeat_back);self.assertEqual(a.selected_rows,{0})
        self.assertTrue(a.layout.repeat_duplex)

    def test_buttons_recover_after_expose_scroll_resize_and_remap(self):
        a=self.app;errors=[];self.root.report_callback_exception=lambda *args:errors.append(args)
        for mode in ('Буклет','Открытка со сгибом','Тираж','Задать размер фото','Разделить лист'):
            a.mode_var.set(mode);a.bleed_section.set_open(True);a.color_section.set_open(True)
            self.root.geometry('1080x740');self.root.update()
            a.settings_canvas.yview_moveto(1);self.root.update()
            a.settings_canvas.yview_moveto(0);self.root.update()
            self.root.geometry('1250x850');self.root.update()
            if mode in ('Открытка со сгибом','Разделить лист'):
                self.assertFalse(a.production_box.winfo_ismapped())
                probe=a.count_combo if mode=='Разделить лист' else a.panel_buttons[0]
                # Native hit testing also sees unrelated windows over the test.
                # Assert the actual defect: no production frame may cover this row.
                self.assertTrue(probe.winfo_ismapped())
        button=a.count_combo
        button.delete('all');button.event_generate('<Expose>');self.root.update()
        self.assertTrue(any(button.type(i)=='text' for i in button.find_all()))
        self.assertTrue(any(button.type(i)=='image' for i in button.find_all()))
        self.root.withdraw();self.root.update();self.root.deiconify();self.root.update()
        self.assertTrue(button.winfo_ismapped())
        self.assertTrue(button.find_all())
        self.assertTrue(a.color_section.header.find_withtag('outline_icon'))
        self.assertEqual(errors,[])

    def test_repeat_exact_quantity_current_ratio_and_mode_memory(self):
        a=self.repeat();self.assertIsNotNone(a.layout)
        self.assertEqual(a.layout.count,21);self.assertEqual(page_count(a.photos,a.layout),5)
        self.assertEqual(len(page_items(a.photos,a.layout,4)),16)
        a.repeat_lock_var.set(True);a.repeat_w_var.set('90')
        self.assertAlmostEqual(a._number(a.repeat_h_var),60)
        a.repeat_lock_var.set(False);a.repeat_h_var.set('30');a.repeat_lock_var.set(True)
        self.assertEqual((a._number(a.repeat_w_var),a._number(a.repeat_h_var)),(90,30))
        a.repeat_w_var.set('60');self.assertAlmostEqual(a._number(a.repeat_h_var),20)
        a.mode_var.set('Буклет');a.mode_var.set('Тираж');a.refresh()
        self.assertEqual(a.layout.print_height,20)

    def test_fixed_booklet_preserves_size_paper_switch_and_copies(self):
        a=self.app;a.mode_var.set('Буклет');a.booklet_method_var.set('Точный размер страницы');a.paper_var.set('SRA3');a.orientation_var.set('Книжная');a.booklet_copies_var.set('2');a.margin_var.set('5');a.gap_var.set('5');a.refresh();self.root.update()
        self.assertIsNotNone(a.layout);self.assertEqual(a.layout.booklet_page_size,(148,210))
        self.assertEqual(len(a.layout.cells()),4)
        self.assertEqual(len(a.preview_canvas.find_withtag('page_badge')),4)
        a.paper_var.set('A3+');a.refresh();self.assertEqual(a.layout.booklet_page_size,(148,210))
        a.mode_var.set('Тираж');a.mode_var.set('Буклет');self.assertEqual(a.booklet_copies_var.get(),'2')

    def test_custom_paper_snapshot_and_units(self):
        a=self.app;p=a.paper_store.put('Меловка',330,488);a.setup_paper_captions();a.paper_var.set(p.identifier);a.refresh()
        self.assertEqual(a.layout.page_size,(330,488))
        before=a.layout;a.unit_var.set('in');a.refresh();self.assertEqual(a.layout,before)
        a._paper_snapshot_before_change(p.identifier);a.paper_store.put('Переименован',320,450,p.identifier);a.refresh()
        self.assertEqual(a.layout.page_size,(330,488));self.assertEqual(a.paper_var.get(),'Свой размер')

    def test_large_quantity_navigation_builds_only_current_sheet(self):
        a=self.repeat();a.repeat_quantity_var.set('1000000000');a.refresh()
        start=time.monotonic();a.page=page_count(a.photos,a.layout)-1;a.refresh()
        self.assertLess(time.monotonic()-start,4)
        self.assertEqual(len(page_items(a.photos,a.layout,a.page)),1000000000%21)
        a.add_paths(make_photos(Path(self.temp.name)/'photos')[2:3])
        a.repeat_duplex_var.set(True);a.repeat_back_var.set(list(a._repeat_sources)[1]);a.refresh()
        a.page=page_count(a.photos,a.layout)-1
        # A navigation operation must never enumerate the billion-product job.
        # Guard page_count in this test so a regression fails immediately.
        last=a.page
        with patch('illusive_print.duplex_ui.page_count',side_effect=AssertionError('Navigation expanded the run')):
            a.select_photo(2,keep_page=False)
            self.assertEqual(a.page,last)
            a.select_photo(0,keep_page=False)
            self.assertEqual(a.page,last-1)
            a.select_photo(1,keep_page=False)
            self.assertEqual(a.page,last)

    def test_reset_returns_new_modes_to_defaults(self):
        a=self.repeat();a.booklet_method_var.set('Точный размер страницы');a.booklet_copies_var.set('2')
        with patch('illusive_print.app.messagebox.askyesno',return_value=True):a.reset_settings()
        self.assertEqual(a.count_var.get(),'1');self.assertEqual(a.booklet_method_var.get(),'По размеру листа')
        self.assertEqual(a.booklet_copies_var.get(),'1');self.assertTrue(a.repeat_lock_var.get());self.assertEqual(a.repeat_fill_var.get(),'Заполнить один лист')

    def test_moving_blank_updates_card_before_the_next_layout_snapshot(self):
        a=self.app;a.add_paths(make_photos(Path(self.temp.name)/'photos')[2:])
        a.mode_var.set('Буклет');a.booklet_method_var.set('Точный размер страницы');a.paper_var.set('SRA3');a.orientation_var.set('Книжная');a.refresh()
        blank=next(i for i,leaf in enumerate(a.booklet_leaves) if leaf['token'] is None)
        leaf=a.booklet_leaves.pop(blank);leaf['auto']=False;a.booklet_leaves.insert(0,leaf)
        a.select_booklet_page(0);a.refresh();self.root.update()
        labels=[str(w.cget('text')) for w in a._booklet_cards[1].winfo_children() if 'text' in w.keys()]
        self.assertIn('1 · Пустая страница',labels)
