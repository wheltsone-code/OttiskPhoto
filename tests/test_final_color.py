import unittest
from types import SimpleNamespace

from PIL import Image

from illusive_print.color import IDENTITY, curve_lut, temperature_tint
from illusive_print.core import Correction, correct_image
from illusive_print.curves_editor import CurvesEditor


class FinalColorTests(unittest.TestCase):
    def test_endpoint_plateaus_and_inner_diagonal(self):
        lut = curve_lut(((20, 0), (235, 255)))
        self.assertEqual(lut[:21], (0,) * 21)
        self.assertEqual(lut[235:], (255,) * 21)
        self.assertEqual(curve_lut(((20, 20), (235, 235))),
                         tuple(max(20, min(235, x)) for x in range(256)))
        self.assertEqual(curve_lut(IDENTITY), tuple(range(256)))
        ramp = Image.new('RGB', (256, 1))
        ramp.putdata([(x, x, x) for x in range(256)])
        self.assertEqual(list(correct_image(ramp, Correction(curve=((20, 0), (235, 255)))).getdata()),
                         [(x, x, x) for x in lut])

    def test_endpoint_drag_nudge_crossing_and_delete_protection(self):
        editor = object.__new__(CurvesEditor)
        editor.points = ((0, 0), (100, 120), (255, 255))
        editor.app = SimpleNamespace(set_curve=lambda *a, **kw: None)
        editor.draw = lambda: None
        editor.selected, editor.dragging = 0, True
        x, y = editor.to_canvas(200, 30)
        editor.motion(SimpleNamespace(x=x, y=y))
        self.assertEqual(editor.points[0], (99, 30))
        editor.delete_point()
        self.assertEqual(len(editor.points), 3)
        editor.selected = 2
        x, y = editor.to_canvas(0, 240)
        editor.motion(SimpleNamespace(x=x, y=y))
        self.assertEqual(editor.points[-1], (101, 240))
        editor.delete_point()
        self.assertEqual(len(editor.points), 3)
        editor.nudge(1, 1)
        self.assertEqual(editor.points[-1], (102, 241))
