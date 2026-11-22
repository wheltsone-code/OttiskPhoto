"""Composite RGB curves and selective vibrance; no third-party curve engine."""

from functools import lru_cache
import math

from PIL import Image, ImageChops
from .preview_tasks import check_preview_cancelled


def _rgb_lab(rgb):
    """D65 sRGB -> CIELAB, floating point (no 8-bit Lab quantisation)."""
    import numpy as np
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=linear @ np.array([[.4124564,.3575761,.1804375], [.2126729,.7151522,.0721750], [.0193339,.1191920,.9503041]]).T
    xyz/=np.array([.95047,1,1.08883])
    f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack((116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])),axis=-1)


def _lab_linear(lab):
    import numpy as np
    y=(lab[...,0]+16)/116
    f=np.stack((y+lab[...,1]/500,y,y-lab[...,2]/200),axis=-1)
    xyz=np.where(f>6/29,f**3,3*(6/29)**2*(f-4/29))*np.array([.95047,1,1.08883])
    return xyz @ np.array([[3.2404542,-1.5371385,-.4985314],[-.9692660,1.8760108,.0415560],[.0556434,-.2040259,1.0572252]]).T


def copy_lab_channels(lab, mode):
    result=lab.copy()
    if mode == 'a_to_b': result[...,2]=lab[...,1]
    elif mode == 'b_to_a': result[...,1]=lab[...,2]
    elif mode != 'none': raise ValueError('Unknown Lab effect')
    return result


def teal_orange(image, mode='none'):
    """Copy a/b at fixed L; compress chroma along the same hue into sRGB.

    Work in strips to bound memory for 600 ppi output. Exact sRGB neutrals
    bypass the round trip, including white created by previous stages.
    """
    if mode == 'none': return image
    import numpy as np
    output=Image.new('RGB',image.size)
    for top in range(0,image.height,128):
        check_preview_cancelled()
        source=np.asarray(image.crop((0,top,image.width,min(top+128,image.height))))
        lab=copy_lab_channels(_rgb_lab(source.astype(np.float64)/255),mode)
        raw=_lab_linear(lab)
        outside=np.any((raw < -1e-7)|(raw > 1+1e-7),axis=-1)
        if outside.any():
            colors = lab[outside]
            candidate = colors.copy()
            lo = np.zeros(len(colors))
            hi = np.ones(len(colors))
            for _ in range(16):
                check_preview_cancelled()
                mid = (lo + hi) / 2
                candidate[:, 1:] = colors[:, 1:] * mid[:, None]
                linear = _lab_linear(candidate)
                valid = np.all((linear >= -1e-7) & (linear <= 1 + 1e-7), axis=-1)
                lo = np.where(valid, mid, lo)
                hi = np.where(valid, hi, mid)
            candidate[:, 1:] = colors[:, 1:] * lo[:, None]
            raw[outside] = _lab_linear(candidate)
        raw=np.clip(raw,0,1)
        encoded=np.where(raw<=.0031308,12.92*raw,1.055*raw**(1/2.4)-.055)
        pixels=np.rint(encoded*255).astype(np.uint8)
        neutral=(source[...,0]==source[...,1])&(source[...,1]==source[...,2])
        pixels[neutral]=source[neutral]
        output.paste(Image.fromarray(pixels),(0,top))
    return output


Curve = tuple[tuple[int, int], ...]
IDENTITY: Curve = ((0, 0), (255, 255))


@lru_cache(maxsize=256)
def _channel_gain_lut(strength: float) -> tuple[int, ...]:
    """Linear-sRGB lift: f(x)=x/(x+(1-x)*exp(-strength)).

    f(0)=0, f(1)=1, f'(x)>0. The derivative approaches exp(-strength)
    at white: highlights roll off continuously rather than clipping a gain.
    """
    if strength == 0:
        return tuple(range(256))
    shoulder = math.exp(-strength)
    values = []
    for value in range(256):
        encoded = value / 255
        linear = encoded / 12.92 if encoded <= .04045 else ((encoded + .055) / 1.055) ** 2.4
        lifted = linear / (linear + (1 - linear) * shoulder)
        encoded = 12.92 * lifted if lifted <= .0031308 else 1.055 * lifted ** (1 / 2.4) - .055
        values.append(round(255 * encoded))
    return tuple(values)


def temperature_tint(image: Image.Image, temperature: float, tint: float) -> Image.Image:
    """Lift only selected channels; no luminance/saturation compensation.

    Warm: R+G (stronger R); cool: B; magenta: R+B (stronger B); green: G.
    Both controls combine their positive linear-light strengths before LUT
    construction. Unselected channels pass through byte-for-byte.
    """
    if temperature == 0 and tint == 0:
        return image
    warm, cool = max(temperature, 0), max(-temperature, 0)
    magenta, green = max(tint, 0), max(-tint, 0)
    strengths = (1.35 * warm + .75 * magenta,
                 .50 * warm + 1.0 * green,
                 1.25 * cool + 1.10 * magenta)
    return image.point([value for strength in strengths for value in _channel_gain_lut(strength)])


@lru_cache(maxsize=256)
def curve_lut(points: Curve = IDENTITY) -> tuple[int, ...]:
    """Shape-preserving piecewise cubic Hermite interpolation (PCHIP).

    Tangents are zero at extrema and use a weighted harmonic mean otherwise.
    Each segment stays between its endpoint values, including non-monotone
    user curves. Outside the endpoint X values, extend their output constantly.
    """
    if (len(points) < 2
            or any(not 0 <= x <= 255 or not 0 <= y <= 255 for x, y in points)
            or any(a[0] >= b[0] for a, b in zip(points, points[1:]))):
        raise ValueError("Точки кривой должны идти слева направо от 0 до 255.")
    if points[0] == (0, 0) and points[-1] == (255, 255) and all(x == y for x, y in points):
        return tuple(range(256))
    h = [b[0] - a[0] for a, b in zip(points, points[1:])]
    slopes = [(b[1] - a[1]) / length for a, b, length in zip(points, points[1:], h)]
    if len(points) == 2:
        tangents = [slopes[0], slopes[0]]
    else:
        tangents = [0.0] * len(points)
        for i in range(1, len(points) - 1):
            before, after = slopes[i - 1], slopes[i]
            if before * after > 0:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                tangents[i] = (w1 + w2) / (w1 / before + w2 / after)

        def endpoint(a: float, b: float, da: float, db: float) -> float:
            slope = ((2 * a + b) * da - a * db) / (a + b)
            if slope * da <= 0:
                return 0.0
            if da * db <= 0 and abs(slope) > 3 * abs(da):
                return 3 * da
            return slope

        tangents[0] = endpoint(h[0], h[1], slopes[0], slopes[1])
        tangents[-1] = endpoint(h[-1], h[-2], slopes[-1], slopes[-2])
    result = []
    segment = 0
    for value in range(256):
        if value <= points[0][0]:
            result.append(points[0][1])
            continue
        if value >= points[-1][0]:
            result.append(points[-1][1])
            continue
        while segment < len(points) - 2 and value > points[segment + 1][0]:
            segment += 1
        x0, y0 = points[segment]
        _, y1 = points[segment + 1]
        length = h[segment]
        t = (value - x0) / length
        y = ((2 * t**3 - 3 * t**2 + 1) * y0
             + (t**3 - 2 * t**2 + t) * length * tangents[segment]
             + (-2 * t**3 + 3 * t**2) * y1
             + (t**3 - t**2) * length * tangents[segment + 1])
        result.append(round(max(min(y0, y1), min(max(y0, y1), y))))
    return tuple(result)


def vibrance(image: Image.Image, amount: float) -> Image.Image:
    """Own vibrance implementation with a soft, colour-based skin safeguard.

    Saturation gain falls with existing saturation. Smooth hue/saturation/value
    masks soften the gain around warm skin-like colours, without hard bands.
    S=0 is invariant; fully saturated colours receive no additional boost.
    """
    if amount == 0:
        return image
    hue, saturation, value = image.convert("HSV").split()
    adjusted = saturation.point([max(0, min(255, round(s + amount * s * (1 - s / 255)))) for s in range(256)])
    hue_mask = hue.point([round(255 * math.exp(-.5 * ((h * 360 / 255 - 25) / 19) ** 2)) for h in range(256)])
    sat_mask = saturation.point([round(255 * math.exp(-.5 * ((s / 255 - .38) / .25) ** 2)) for s in range(256)])
    value_mask = value.point([round(255 * min(1, max(0, (v / 255 - .12) / .28))) for v in range(256)])
    skin = ImageChops.multiply(ImageChops.multiply(hue_mask, sat_mask), value_mask)
    weight = skin.point([round(255 - .7 * strength) for strength in range(256)])
    adjusted = Image.composite(adjusted, saturation, weight)
    return Image.merge("HSV", (hue, adjusted, value)).convert("RGB")
