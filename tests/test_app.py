from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.core import EdgeInsets, page_items, render_photo
from tests.support import make_photos


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.paths = make_photos(cls.folder / "фотографии")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.count_var.set('2')
        self.root.update()
        self.app.add_paths(self.paths[:1])
        self.root.update()

    def tearDown(self):
        if self.app._refresh_job:
            self.root.after_cancel(self.app._refresh_job)
        self.root.destroy()

    def wait_for_export(self):
        deadline = time.monotonic() + 15
        while self.app._exporting and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app._exporting)

    def exact_order(self):
        app = self.app
        app.mode_var.set("Задать размер фото")
        app.paper_var.set("10 × 15 см")
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.gap_var.set("5")
        app.copy_vars[0].set("10")
        app.refresh()

    def test_copy_keyboard_buttons_selection_rotation_and_pagination(self):
        app = self.app
        self.assertEqual(self.root.title(), "Оттиск Фото")
        self.assertEqual(app.mode_var.get(), "Разделить лист")
        self.assertEqual(app.orientation_var.get(), "Книжная")
        app.add_paths(self.paths[:1])  # No duplicate source row.
        self.assertEqual(len(app.photos), 1)
        entry = app.copy_entries[0]
        entry.delete(0, "end")
        entry.insert(0, "10")
        app.refresh()
        self.assertEqual(app.photos[0].copies, 10)
        self.assertEqual(app.counter_var.get(), "Отпечатков: 10  ·  Листов: 5")
        self.assertEqual(len(app.thumbnail_widgets), 1)
        app.copy_buttons[0][0].invoke()
        self.assertEqual(app.photos[0].copies, 9)
        app.copy_buttons[0][1].invoke()
        self.assertEqual(app.photos[0].copies, 10)
        app.turn_page(1)
        app.turn_page(1)
        cell = app.layout.cells()[1]
        app.preview_click(SimpleNamespace(
            x=app.preview_origin[0] + (cell.x + cell.width / 2) * app.preview_scale,
            y=app.preview_origin[1] + (cell.y + cell.height / 2) * app.preview_scale))
        self.assertEqual(app.page, 2)  # A later copy must not jump to the first sheet.
        app.add_paths(self.paths[1:2])
        app.rotate_button.invoke()
        self.assertEqual([p.rotation for p in app.photos], [1, 0])
        app.all_mode("fill")
        app.fit_button.invoke()
        self.assertTrue(all(p.mode == "fit" for i, p in page_items(app.photos, app.layout, 2) if i == 0))
        self.assertEqual(app.photos[1].mode, "fill")
        app.copy_vars[0].set("")
        app.refresh()
        self.assertEqual(str(app.save_button["state"]), "disabled")
        app.commit_copies(0)
        self.assertEqual(app.copy_vars[0].get(), "10")
        app.copy_vars[0].set("1")
        app.copy_buttons[0][0].invoke()
        self.assertEqual(app.photos[0].copies, 1)
        app.select_photo(0)
        app.remove_selected()
        self.assertEqual(len(app.photos), 1)
        self.assertEqual(app.photos[0].path, self.paths[1])
        app.copy_buttons[0][1].invoke()
        self.assertEqual(app.photos[0].copies, 2)

    def test_modes_restore_settings_capacity_custom_fields_and_driver_margins(self):
        app = self.app
        app.count_var.set("4")
        app.margin_var.set("5")
        app.gap_var.set("2")
        app.paper_var.set("A3")
        app.orientation_var.set("Альбомная")
        app.refresh()
        self.assertEqual(app.exact_box.winfo_manager(), "")
        self.assertEqual(app.paper_custom.winfo_manager(), "")
        self.exact_order()
        self.assertEqual(app.orientation_var.get(), "Книжная")
        self.assertEqual(app.cells_box.winfo_manager(), "")
        self.assertEqual(app.exact_box.winfo_manager(), "grid")
        self.assertEqual(app.print_custom.winfo_manager(), "grid")
        self.assertEqual(app.layout.count, 6)
        self.assertEqual(app.capacity_var.get(), "До 6 фото на листе")
        self.assertEqual(app.counter_var.get(), "Отпечатков: 10  ·  Листов: 2")
        self.assertEqual(app.fill_button["text"], "Обрезать до краёв")
        app.set_printer_margins(EdgeInsets(10, 1, 10, 1))
        self.assertEqual(app.layout.count, 6)
        self.assertEqual(app.counter_var.get(), "Отпечатков: 10  ·  Листов: 2")
        self.assertTrue(all((c.width, c.height) == (40, 40) for c in app.layout.cells()))
        app.mode_var.set("Разделить лист")
        self.assertEqual((app.paper_var.get(), app.orientation_var.get(), app.count_var.get(),
                          app.margin_var.get(), app.gap_var.get()), ("A3", "Альбомная", "4", "5", "2"))
        self.assertEqual(app.fill_button["text"], "Обрезать до краёв")
        app.mode_var.set("Задать размер фото")
        self.assertEqual((app.paper_var.get(), app.print_w_var.get(), app.print_h_var.get(), app.gap_var.get()),
                         ("10 × 15 см", "40", "40", "5"))
        self.assertEqual(app.layout.count, 6)
        app.print_w_var.set("200")
        app.refresh()
        self.assertIsNone(app.layout)
        self.assertEqual(str(app.save_button["state"]), "disabled")
        self.assertEqual(str(app.print_button["state"]), "disabled")
        texts = [app.preview_canvas.itemcget(item, "text") for item in app.preview_canvas.find_all()]
        self.assertTrue(any("не помещается" in text for text in texts))

    def test_pdf_before_toggle_and_print_dialog(self):
        app = self.app
        self.exact_order()
        app.gamma_var.set("1,3")
        app.saturation_changed("40")
        app.rotate_photo()
        app.set_before(True)
        destination = self.folder / "Проверка.pdf"
        with patch("illusive_print.app.filedialog.asksaveasfilename", return_value=str(destination)):
            app.save_button.invoke()
        self.wait_for_export()
        reader = PdfReader(destination)
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual([p.get_contents().get_data().count(b" Do") for p in reader.pages], [6, 4])
        embedded = next(iter(reader.pages[0]["/Resources"]["/XObject"].values())).get_object()
        cell = app.layout.cells()[0]
        expected = render_photo(app.photos[0], cell, app.correction,
                                (round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4))).getpixel((0, 0))
        self.assertEqual(tuple(embedded.get_data()[:3]), expected)
        self.assertTrue(app.preview_before)
        self.assertEqual(app.correction.gamma, 1.3)
        self.assertEqual(app.correction.vibrance, .4)
        with patch("illusive_print.print_dialog.PrintDialog") as dialog:
            app.print_button.invoke()
            dialog.assert_called_once_with(app)


if __name__ == "__main__":
    unittest.main()
