"""Deterministic full-resolution colour/position targets, not thumbnails."""

from pathlib import Path

from PIL import Image, ImageDraw


COLOR_SAMPLES = {
    "neutral_dark": (32, 32, 32), "neutral_mid": (128, 128, 128), "neutral_light": (230, 230, 230),
    "muted_blue": (120, 150, 200), "saturated_blue": (0, 50, 200),
    "skin_warm": (200, 150, 120), "muted_green": (120, 200, 150),
}


def make_color_samples() -> Image.Image:
    image = Image.new("RGB", (len(COLOR_SAMPLES) * 40, 40))
    draw = ImageDraw.Draw(image)
    for index, colour in enumerate(COLOR_SAMPLES.values()):
        draw.rectangle((index * 40, 0, (index + 1) * 40 - 1, 39), fill=colour)
    return image


def make_photos(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    sizes = [(1200, 800), (800, 1200), (1100, 700), (900, 900), (1000, 650)]
    paths = []
    for index, (width, height) in enumerate(sizes):
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            t = y / height
            draw.line((0, y, width, y), fill=(int(35 + 125 * t), int(105 + 70 * t), int(210 - 90 * t)))
        draw.ellipse((width * .65, height * .12, width * .82, height * .12 + width * .17), fill=(255, 214, 115))
        draw.polygon([(0, height * .75), (width * .3, height * .32), (width * .6, height * .75)], fill=(54, 85, 109))
        draw.polygon([(width * .25, height), (width * .72, height * .38), (width, height)], fill=(51, 122, 117))
        for x in range(0, width, 100):
            draw.line((x, 0, x, height), fill=(160, 195, 205), width=2)
        for y in range(0, height, 100):
            draw.line((0, y, width, y), fill=(160, 195, 205), width=2)
        draw.rectangle((0, 0, 28, height), fill=(225, 62, 102))
        draw.rectangle((width - 28, 0, width, height), fill=(58, 190, 114))
        draw.text((60, 40), f"PHOTO {index + 1} / {width} x {height}", fill="white", font_size=36)
        path = folder / f"Фото {index + 1}.{'jpg' if index % 2 == 0 else 'png'}"
        image.save(path)
        paths.append(path)
    return paths
