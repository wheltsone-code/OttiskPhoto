"""Beta contracts: physical size, ICC, native settings and no real print jobs."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from PIL import Image, ImageChops, ImageCms
from pypdf import PdfReader
from pypdf.generic import ContentStream

from illusive_print.app import IllusivePrintApp, create_root
from illusive_print.color_management import OutputProfile, ProfileStore, srgb_bytes
from illusive_print.core import Correction, EdgeInsets, Layout, Photo, effective_ppi, export_pdf, load_source, render_page
from illusive_print.print_dialog import APP_COLOR, PrintDialog
from illusive_print.print_job import PrintJob, PrintSnapshot
from illusive_print.windows_print import DriverPaper, PrintCancelled, WindowsPrinter, clone_devmode
from tests.support import make_photos


class FakePrinter:
    """Records spooling without ever calling a Windows printing function."""
    def __init__(self):
        self.calls = []
        self.prop_calls = []
        self.paper = DriverPaper(100, 150)
        self.returned = {"token": "native private settings"}
        self.failure = None

    def printers(self): return ["Тестовый принтер"]
    def default(self): return "Тестовый принтер"
    def configure(self, name, layout):
        self.paper = DriverPaper(*layout.page_size)
        return {"token": "initial", "scale": 100}
    def inspect(self, name, settings): return self.paper
    def properties(self, hwnd, name, settings):
        self.prop_calls.append((hwnd, name, settings))
        return self.returned
    def profile_mode(self, settings): return settings["token"]
    def submit(self, name, settings, paths, layout, managed, title, before_start=None):
        if before_start and not before_start():
            raise PrintCancelled()
        if self.failure:
            raise self.failure
        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(image.copy())
        self.calls.append((name, settings, images, layout, managed, [p.name for p in paths]))
        return 42


class BetaCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.paths = make_photos(self.folder / "photos")

    def tearDown(self):
        self.temp.cleanup()

    def test_four_40mm_photos_keep_pdf_size_at_both_resolutions_and_srgb(self):
        photos = [Photo(self.paths[0], copies=4)]
        layout = Layout(mode="exact", paper_width=100, paper_height=150, print_width=40, print_height=40, gap=5)
        for ppi in (300, 600):
            with self.subTest(ppi=ppi):
                output = self.folder / f"{ppi}.pdf"
                export_pdf(output, photos, layout, Correction(.2, 1.1), ppi)
                reader = PdfReader(output)
                self.assertEqual(len(reader.pages), 1)
                page = reader.pages[0]
                clips = [v for v, op in ContentStream(page.get_contents(), reader).operations if op == b"re"]
                self.assertEqual(len(clips), 4)
                for _, _, w, h in clips:
                    self.assertAlmostEqual(float(w) * 25.4 / 72, 40, places=4)
                    self.assertAlmostEqual(float(h) * 25.4 / 72, 40, places=4)
                for ref in page["/Resources"]["/XObject"].values():
                    obj = ref.get_object()
                    self.assertEqual((obj["/Width"], obj["/Height"]), (round(40 * ppi / 25.4),) * 2)
                    self.assertEqual(obj["/ColorSpace"][0], "/ICCBased")
                    profile = obj["/ColorSpace"][1].get_object()
                    self.assertEqual(profile["/N"], 3)
                    ImageCms.ImageCmsProfile(BytesIO(profile.get_data()))
                self.assertEqual(reader.trailer["/Root"]["/OutputIntents"][0].get_object()["/OutputConditionIdentifier"], "sRGB IEC61966-2.1")
                self.assertIn("Оттиск Фото", reader.metadata.title)

    def test_size_return_is_identical_and_effective_ppi_not_upscaled(self):
        photo = Photo(self.paths[0], offset_x=.6, rotation=1, curve=((0, 0), (128, 175), (255, 255)))
        layout = Layout(mode="exact", paper_width=100, paper_height=150, print_width=90, print_height=120)
        direct = render_page([photo], layout, 0, Correction(.25, 1.13), 300 / 25.4)
        smaller = replace(layout, print_width=45, print_height=60)
        render_page([photo], smaller, 0, Correction(.25, 1.13), 300 / 25.4)
        returned = render_page([photo], layout, 0, Correction(.25, 1.13), 300 / 25.4)
        self.assertIsNone(ImageChops.difference(direct, returned).getbbox())
        self.assertLess(effective_ppi(photo, layout.cells()[0]), 300)
        snapshot = PrintSnapshot.capture([replace(photo, copies=3)], layout, Correction(), 1)
        self.assertEqual(len(snapshot.pages(False)), 3)
        self.assertEqual(snapshot.prints(True), 1)
        rotated = replace(layout, print_width=120, print_height=90)
        self.assertEqual(sorted((rotated.cells()[0].width, rotated.cells()[0].height)), [90, 120])
        self.assertEqual(replace(layout, driver_margins=EdgeInsets(30, 30, 30, 30)).cells(), layout.cells())

    def test_embedded_icc_import_broken_profile_and_output_validation(self):
        valid = self.folder / "valid.png"
        original = Image.open(self.paths[0]).convert("RGB")
        original.save(valid, icc_profile=srgb_bytes())
        self.assertEqual(load_source(valid).tobytes(), original.tobytes())
        self.assertEqual(load_source(valid).info["icc_profile"], srgb_bytes())
        broken = self.folder / "broken.png"
        original.save(broken, icc_profile=b"not a profile")
        with self.assertRaisesRegex(ValueError, "Встроенный ICC"):
            load_source(broken)
        path = self.folder / "output.icc"
        path.write_bytes(srgb_bytes())
        profile = OutputProfile.read(path)
        self.assertEqual(profile.convert(original).tobytes(), original.tobytes())
        path.write_bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes())
        with self.assertRaisesRegex(ValueError, "RGB ICC"):
            OutputProfile.read(path)
        store = ProfileStore(self.folder / "profiles.json")
        store.put("Printer|100x150|quality", path)
        self.assertEqual(store.get("Printer|100x150|quality"), path)
        self.assertIsNone(store.get("another printer"))

    def test_non_srgb_embedded_profile_really_converts_and_cmyk_imports(self):
        color_dir = Path(r"C:\Windows\System32\spool\drivers\color")
        adobe = color_dir / "AdobeRGB1998.icc"
        if not adobe.is_file():
            self.skipTest("Adobe RGB test profile is not installed on this Windows machine")
        image = Image.new("RGB", (20, 20), (70, 150, 90))
        path = self.folder / "adobe-rgb.png"
        image.save(path, icc_profile=adobe.read_bytes())
        expected = ImageCms.profileToProfile(image, str(adobe), ImageCms.ImageCmsProfile(BytesIO(srgb_bytes())), outputMode="RGB")
        converted = load_source(path)
        self.assertEqual(converted.tobytes(), expected.tobytes())
        self.assertNotEqual(converted.getpixel((0, 0)), image.getpixel((0, 0)))
        cmyk_profile = color_dir / "CoatedFOGRA39.icc"
        if cmyk_profile.is_file():
            path = self.folder / "cmyk.jpg"
            Image.new("CMYK", (20, 20), (30, 80, 100, 20)).save(path, icc_profile=cmyk_profile.read_bytes())
            with Image.open(path) as source:
                expected = ImageCms.profileToProfile(source, str(cmyk_profile), ImageCms.ImageCmsProfile(BytesIO(srgb_bytes())), outputMode="RGB")
            self.assertEqual(load_source(path).tobytes(), expected.tobytes())

    def wait_job(self, job):
        deadline = time.monotonic() + 15
        while job.state in ("preparing", "sending") and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertNotIn(job.state, ("preparing", "sending"))

    def test_current_page_exact_snapshot_uses_its_actual_copies_no_relayout(self):
        photos = [Photo(self.paths[0], copies=3, offset_x=.7), Photo(self.paths[1], copies=2, rotation=1)]
        layout = Layout(paper_width=100, paper_height=150, per_sheet=2)
        snapshot = PrintSnapshot.capture(photos, layout, Correction(.2, 1.1), 1)
        photos[0].offset_x = -1  # edits after opening do not change the print snapshot
        self.assertEqual(snapshot.pages(True), (1,))
        self.assertEqual(snapshot.prints(True), 2)
        backend, job = FakePrinter(), PrintJob()
        settings = {"private": "preserved"}
        self.assertTrue(job.start(snapshot, True, 300, backend, "Printer", settings, None))
        self.assertFalse(job.start(snapshot, True, 300, backend, "Printer", settings, None))
        self.wait_job(job)
        self.assertEqual(job.state, "sent")
        self.assertEqual(len(backend.calls), 1)
        call = backend.calls[0]
        self.assertIs(call[1], settings)
        self.assertEqual(call[5], ["1.bmp"])
        expected = render_page(snapshot.photos, layout, 1, snapshot.correction, 300 / 25.4)
        self.assertEqual(call[2][0].tobytes(), expected.tobytes())
        self.assertFalse(job.start(snapshot, True, 300, backend, "Printer", settings, None))

    def test_cancel_preparation_and_at_native_boundary_creates_no_job(self):
        snapshot = PrintSnapshot.capture([Photo(self.paths[0])], Layout(paper_width=100, paper_height=150), Correction(), 0)
        backend, job = FakePrinter(), PrintJob()
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(5)
            return Image.new("RGB", (100, 150), "red")
        with patch("illusive_print.print_job.render_page", side_effect=slow):
            job.start(snapshot, False, 300, backend, "Printer", {}, None)
            self.assertTrue(entered.wait(5))
            self.assertTrue(job.cancel())
            release.set()
            self.wait_job(job)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(backend.calls, [])
        # Even cancellation while native context is being validated wins before StartDoc.
        class DelayedNative(FakePrinter):
            def submit(inner, *args, **kwargs):
                job.cancel()
                return super().submit(*args, **kwargs)
        backend = DelayedNative()
        job.start(snapshot, False, 300, backend, "Printer", {}, None)
        self.wait_job(job)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(backend.calls, [])

    def test_queue_failure_no_auto_retry_and_one_output_profile_transform_per_page(self):
        snapshot = PrintSnapshot.capture([Photo(self.paths[0], copies=3)], Layout(paper_width=100, paper_height=150), Correction(), 0)
        backend, job = FakePrinter(), PrintJob()
        backend.failure = OSError("Spooler unavailable")
        path = self.folder / "output.icc"
        path.write_bytes(srgb_bytes())
        profile = OutputProfile.read(path)
        with patch.object(OutputProfile, "convert", autospec=True, side_effect=lambda _, image: image) as convert:
            job.start(snapshot, False, 300, backend, "Printer", {}, profile)
            self.wait_job(job)
            self.assertEqual(convert.call_count, 2)
        self.assertEqual(job.state, "error")
        self.assertEqual(backend.calls, [])
        self.assertTrue(any(kind == "error" and "Spooler" in text for kind, text in list(job.events.queue)))


class BetaDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.paths = make_photos(self.folder / "photos")
        self.root = create_root()
        self.app = IllusivePrintApp(self.root)
        self.app.count_var.set('2')
        self.app.add_paths(self.paths[:2])
        self.app.paper_var.set("10 × 15 см")
        self.app.copy_vars[0].set("3")
        self.app.copy_vars[1].set("2")
        self.app.refresh()
        self.root.update()
        self.backend = FakePrinter()
        self.dialog = None

    def tearDown(self):
        if self.dialog:
            self.dialog.window.destroy()
        self.root.destroy()
        self.temp.cleanup()

    def open(self):
        self.dialog = PrintDialog(self.app, self.backend, ProfileStore(self.folder / "profiles.json"))
        self.root.update()
        return self.dialog

    def test_properties_return_cancel_mismatch_summary_and_second_sheet(self):
        self.app.turn_page(1)
        dialog = self.open()
        self.assertEqual(dialog.scope_var.get(), "Все листы")
        dialog.scope_var.set("Текущий лист")
        self.assertIn("текущий лист 2 из 3", dialog.summary_var.get())
        self.assertIn("2 отпечатков", dialog.summary_var.get())
        dialog.properties_button.invoke()
        self.assertIs(dialog.settings, self.backend.returned)
        self.assertEqual(len(self.backend.prop_calls), 1)
        self.backend.returned = None
        previous = dialog.settings
        dialog.properties()
        self.assertIs(dialog.settings, previous)
        self.backend.returned = previous
        self.backend.paper = DriverPaper(150, 100)
        dialog.properties()
        self.assertIn("Макет: 100 × 150", dialog.problem_var.get())
        self.assertIn("Драйвер: 150 × 100", dialog.problem_var.get())
        self.assertEqual(dialog.confirm_button.cget("state"), "disabled")
        dialog.confirm()
        self.assertEqual(self.backend.calls, [])
        self.backend.paper = DriverPaper(100, 150)
        dialog.properties()
        dialog.confirm()
        dialog.confirm()  # duplicate Enter/handler path is also blocked
        deadline = time.monotonic() + 15
        while dialog.job.state in ("preparing", "sending") and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(dialog.job.state, "sent")
        self.assertEqual(len(self.backend.calls), 1)
        self.assertIs(self.backend.calls[0][1], previous)
        self.assertEqual(self.backend.calls[0][5], ["1.bmp"])
        dialog.confirm_button.invoke()
        self.assertEqual(len(self.backend.calls), 1)

    def test_rgb_checkbox_label_keyboard_tick_and_rounded_fields(self):
        self.assertFalse(hasattr(self.app, "auto_check"))
        self.assertTrue(self.app.read_layout().autorotate)
        self.assertIn("Размер фото", self.app.size_hint_var.get())
        self.app.open_curves()
        editor = self.app._curves_editor
        self.root.update()
        import win32gui
        for window in (self.root, editor.window):
            self.assertTrue(win32gui.SendMessage(win32gui.GetParent(window.winfo_id()), 0x7F, 1, 0))
        check = self.app.individual_color_check
        # Clicking the caption, not just its square, toggles the actual scope.
        check.event_generate("<ButtonPress-1>", x=100, y=15)
        check.event_generate("<ButtonRelease-1>", x=100, y=15)
        self.root.update()
        self.assertTrue(self.app.individual_color_var.get())
        self.assertIn("✓", [check.itemcget(item, "text") for item in check.find_all() if check.type(item) == "text"])
        self.assertEqual(self.app.photos[self.app.selected].curve, self.app.global_curve)
        check.focus_force()
        check.event_generate("<KeyPress-space>")
        self.root.update()
        self.assertFalse(self.app.individual_color_var.get())
        self.assertIsNone(self.app.photos[self.app.selected].curve)
        for combo in (self.app.mode_combo, self.app.paper_combo, self.app.paper_orientation_combo):
            self.assertEqual(type(combo).__name__, "RoundedCombo")
        self.app.paper_orientation_combo.cycle(1)
        self.assertEqual(self.app.orientation_var.get(), "Альбомная")
        self.assertEqual(self.app.color_reset_button.cget("text"), "Сбросить цвет")

    def test_missing_profile_blocks_output_and_import_error_is_explicit(self):
        dialog = self.open()
        dialog.color_var.set(APP_COLOR)
        dialog.icc_var.set(str(self.folder / "missing.icc"))
        self.assertIsNone(dialog.profile)
        self.assertEqual(dialog.confirm_button.cget("state"), "disabled")
        self.assertIn("заново", dialog.profile_hint.get())
        dialog.close()
        self.dialog = None
        bad = self.folder / "bad-icc.png"
        Image.new("RGB", (20, 20)).save(bad, icc_profile=b"broken")
        with patch("illusive_print.app.messagebox.showwarning") as warning:
            self.app.add_paths([bad])
        self.assertIn("Встроенный ICC", warning.call_args.args[1])
        self.assertEqual(len(self.app.photos), 2)


class WindowsAdapterTests(unittest.TestCase):
    def test_gdi_uses_driver_private_settings_100_percent_and_no_second_icm(self):
        import pywintypes
        dm = pywintypes.DEVMODEType(8)
        dm.DriverData = b"12345678"
        dm.Scale, dm.Copies, dm.Fields = 100, 1, 16 | 256
        backend = WindowsPrinter()
        dc = Mock()
        caps = {110: 2362, 111: 3543, 88: 600, 90: 600, 112: 48, 113: 60}
        dc.GetDeviceCaps.side_effect = caps.__getitem__
        dc.GetHandleOutput.return_value = 123
        dc.StartDoc.return_value = 42
        gdi = Mock()
        gdi.SetICMMode.return_value = 1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.bmp"
            Image.new("RGB", (100, 150), "red").save(path)
            with patch.object(backend, "_dc", return_value=dc) as create, \
                 patch("illusive_print.windows_print.ctypes.WinDLL", return_value=gdi), \
                 patch("PIL.ImageWin.Dib") as dib:
                self.assertEqual(backend.submit("Fake", dm, [path], Layout(paper_width=100, paper_height=150),
                                                True, "Test", before_start=lambda: True), 42)
                used = create.call_args.args[1]
                self.assertEqual(used.DriverData, dm.DriverData)
                self.assertEqual(used.ICMMethod, 1)
                gdi.SetICMMode.assert_called_once_with(123, 4)
                dc.StartDoc.assert_called_once_with("Test")
                dib.return_value.draw.assert_called_once_with(123, (-48, -60, 2314, 3483))
                dc.EndDoc.assert_called_once()
                dc.AbortDoc.assert_not_called()
        # A rejected cancellation boundary occurs before any StartDoc.
        dc.reset_mock()
        with patch.object(backend, "_dc", return_value=dc), \
             patch("illusive_print.windows_print.ctypes.WinDLL", return_value=gdi):
            with self.assertRaises(PrintCancelled):
                backend.submit("Fake", dm, [], Layout(paper_width=100, paper_height=150),
                               False, "Test", before_start=lambda: False)
        dc.StartDoc.assert_not_called()

    def test_clone_retains_native_private_data_and_properties_cancel(self):
        import pywintypes
        dm = pywintypes.DEVMODEType(8)
        dm.DriverData = b"12345678"
        dm.Orientation, dm.PaperWidth, dm.PaperLength = 2, 1000, 1500
        dm.Scale, dm.Copies, dm.Fields = 100, 1, 1 | 4 | 8 | 16 | 256
        clone = clone_devmode(dm)
        self.assertEqual(clone.DriverData, dm.DriverData)
        self.assertEqual((clone.Orientation, clone.PaperWidth, clone.PaperLength), (2, 1000, 1500))
        backend = WindowsPrinter()
        with patch.object(backend.api, "OpenPrinter", return_value=123), \
             patch.object(backend.api, "ClosePrinter"), \
             patch.object(backend.api, "DocumentProperties", return_value=2) as properties:
            self.assertIsNone(backend.properties(0, "Fake", dm))
            self.assertEqual(properties.call_args.args[-1], 2 | 4 | 8)


if __name__ == "__main__":
    unittest.main()
