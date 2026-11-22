"""Portrait/gradient QA through the real preview and PDF pipeline."""
import json
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw, ImageStat
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from illusive_print.color import temperature_tint
from illusive_print.core import (Photo, Correction, Layout, load_source, photo_image,
                                 render_photo, export_pdf, _source_key)
from illusive_print.preview import render_tile


def run(portrait, output):
    output.mkdir(parents=True, exist_ok=True)
    photo = Photo(portrait.resolve())
    source = load_source(photo)
    layout = Layout(paper_width=source.width / 10, paper_height=source.height / 10,
                    per_sheet=1, margin=0, autorotate=False)
    cell = layout.cells()[0]
    images = {}
    report = {'source': str(portrait), 'source_url': 'https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/mpl-data/sample_data/grace_hopper.jpg',
              'cases': [], 'passed': False}
    for field in ('temperature', 'tint'):
        for value in (-100, -20, -10, 10, 20, 100):
            correction = Correction(**{field: value / 100})
            chosen = ((0, 1) if value > 0 else (2,)) if field == 'temperature' else ((0, 2) if value > 0 else (1,))
            changed = photo_image(photo, correction, cell, False)
            preview = render_tile(photo, cell, source.size, correction, False, _source_key(photo.path))
            assert changed.tobytes() == preview.tobytes()
            for channel in range(3):
                before, after = source.getchannel(channel), changed.getchannel(channel)
                assert ImageChops.subtract(before, after).getbbox() is None
                if channel not in chosen:
                    assert before.tobytes() == after.tobytes()
            pdf_path = output / f'{field}-{value}.pdf'
            export_pdf(pdf_path, [photo], layout, correction, ppi=300)
            embedded = next(iter(PdfReader(pdf_path).pages[0]['/Resources']['/XObject'].values())).get_object()
            size = (round(cell.width * 300 / 25.4), round(cell.height * 300 / 25.4))
            expected = render_photo(photo, cell, correction, size, False)
            assert embedded.get_data() == expected.tobytes()
            white = temperature_tint(Image.new('RGB', (1, 1), 'white'), correction.temperature, correction.tint)
            assert white.getpixel((0, 0)) == (255, 255, 255)
            images[field, value] = changed
            report['cases'].append({'field': field, 'value': value, 'selected_channels': chosen,
                'mean_channel_lift': ImageStat.Stat(ImageChops.difference(source, changed)).mean,
                'preview_exact_at_source_resolution': True, 'pdf_pixels_exact': True})

    montage = Image.new('RGB', (5 * 256, 2 * 326), '#eeeeee')
    draw = ImageDraw.Draw(montage)
    for row, field in enumerate(('temperature', 'tint')):
        for column, value in enumerate((0, 10, 20, -100, 100)):
            image = source if value == 0 else images[field, value]
            image = image.resize((256, 300), Image.Resampling.LANCZOS)
            montage.paste(image, (column * 256, row * 326 + 26))
            draw.text((column * 256 + 10, row * 326 + 7), f'{field} {value:+d}; other = 0', fill='black')
    montage.save(output / 'portrait-comparison.png')
    gradient = Image.new('RGB', (512, 160))
    for x in range(512):
        value = x // 2
        for band, pixel in enumerate(((value, 0, 0), (0, value, 0), (0, 0, value), (value,) * 3)):
            gradient.paste(pixel, (x, band * 40, x + 1, (band + 1) * 40))
    gradient_sheet = Image.new('RGB', (512, 5 * 184), '#eeeeee')
    draw = ImageDraw.Draw(gradient_sheet)
    for row, (label, temperature, tint) in enumerate((('Original', 0, 0), ('Warm R+G', 1, 0),
            ('Cool B', -1, 0), ('Magenta R+B', 0, 1), ('Green G', 0, -1))):
        draw.text((8, row * 184 + 6), label, fill='black')
        gradient_sheet.paste(temperature_tint(gradient, temperature, tint), (0, row * 184 + 24))
    gradient_sheet.save(output / 'gradient-comparison.png')
    report['passed'] = True
    (output / 'portrait-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'portrait_cases': len(report['cases']), 'output': str(output)}, indent=2))


if __name__ == '__main__':
    run(Path(sys.argv[1]), Path(sys.argv[2]))
