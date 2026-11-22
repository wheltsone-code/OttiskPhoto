import unittest

from PIL import Image

from illusive_print.color import temperature_tint


class ChannelGainTests(unittest.TestCase):
    DIRECTIONS = ((1, 0, (0, 1)), (-1, 0, (2,)), (0, 1, (0, 2)), (0, -1, (1,)))

    def test_rgb_ramp_selected_channels_only_monotone_and_fixed_endpoints(self):
        ramp = Image.new('RGB', (256, 1))
        ramp.putdata([(v, v, v) for v in range(256)])
        for temperature, tint, selected in self.DIRECTIONS:
            for amount in (.1, .2, 1):
                result = list(temperature_tint(ramp, temperature * amount, tint * amount).getdata())
                self.assertEqual(result[0], (0, 0, 0))
                self.assertEqual(result[-1], (255, 255, 255))
                for channel in range(3):
                    values = [pixel[channel] for pixel in result]
                    self.assertEqual(values, sorted(values))
                    if channel in selected:
                        self.assertTrue(all(after >= before for before, after in enumerate(values)))
                        self.assertGreater(values[128], 128)
                        self.assertLess(values[248], 255)
                    else:
                        self.assertEqual(values, list(range(256)))

    def test_small_steps_extremes_and_textured_grey(self):
        sample = Image.new('RGB', (3, 1))
        sample.putdata([(182, 126, 102), (240, 240, 240), (255, 255, 255)])
        for temperature, tint, selected in self.DIRECTIONS:
            outputs = [list(temperature_tint(sample, temperature * amount, tint * amount).getdata())
                       for amount in (.1, .2, 1)]
            for channel in selected:
                gains = [out[0][channel] - sample.getpixel((0, 0))[channel] for out in outputs]
                self.assertGreater(gains[0], 0)
                self.assertLessEqual(gains[0], 10)
                self.assertGreater(gains[1], gains[0])
                self.assertGreater(gains[2], gains[1] * 2)
                self.assertGreater(outputs[-1][1][channel], 240)
            self.assertTrue(all(out[-1] == (255, 255, 255) for out in outputs))
        self.assertIs(temperature_tint(sample, 0, 0), sample)

    def test_all_slider_combinations_keep_input_white_and_black(self):
        for temperature in (-1, -.2, 0, .2, 1):
            for tint in (-1, -.2, 0, .2, 1):
                for value in (0, 255):
                    image = Image.new('RGB', (2, 2), (value,) * 3)
                    self.assertEqual(temperature_tint(image, temperature, tint).tobytes(), image.tobytes())
