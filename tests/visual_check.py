"""Generate reproducible PDF/preview pairs under tmp/verification for visual QA.

Run from the repository root: python -m tests.visual_check
"""

from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import time

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat
from pypdf import PdfReader

from illusive_print.core import Correction, Layout, Photo, correct_image, export_pdf, print_count, render_page
from tests.support import make_photos, make_color_samples


def main():
    folder = Path("tmp/verification")
    paths = make_photos(folder / "photos")
    photos = [Photo(path) for path in paths]
    photos[0].copies = 3
    photos[0].curve = ((0, 0), (100, 135), (255, 255))
    photos[0].move(.8, -.6)
    photos[1].set_mode("fit")
    photos[1].rotate_clockwise()
    photos[1].move(-.7, .9)
    photos[2].set_mode("fit")
    photos[2].move(.8, -.8)
    correction = Correction(.35, 1.12, ((0, 0), (70, 60), (180, 200), (255, 255)))
    layouts = {
        "two": Layout(),
        "four": Layout(per_sheet=4, margin=8, gap=3),
        "six": Layout(paper_width=297, paper_height=210, per_sheet=6),
        "nine": Layout(per_sheet=9),
        "exact": Layout(mode="exact", paper_width=100, paper_height=150, print_width=40, print_height=40, gap=5),
        "exact-a4": Layout(mode="exact", print_width=150, print_height=100, gap=5),
    }
    results = []
    for name, layout in layouts.items():
        order = [Photo(paths[0], copies=10)] if name == "exact" else photos
        pdf_path = folder / f"{name}.pdf"
        export_pdf(pdf_path, order, layout, correction)
        with pymupdf.open(pdf_path) as pdf:
            for index, page in enumerate(pdf):
                preview = render_page(order, layout, index, correction, 2)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(2 * 25.4 / 72, 2 * 25.4 / 72), alpha=False)
                rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).crop((0, 0, preview.width, preview.height))
                raw = ImageStat.Stat(ImageChops.difference(preview, rendered)).mean
                smoothed = ImageStat.Stat(ImageChops.difference(preview.filter(ImageFilter.GaussianBlur(1)),
                                                               rendered.filter(ImageFilter.GaussianBlur(1)))).mean
                results.append({"layout": name, "page": index + 1, "mean_rgb_error": raw, "blurred_error": smoothed})
                preview.save(folder / f"{name}-{index + 1}-preview.png")
                rendered.save(folder / f"{name}-{index + 1}-pdf.png")
                pair = Image.new("RGB", (preview.width * 2 + 30, preview.height + 48), "#e4e6eb")
                pair.paste(preview, (10, 32))
                pair.paste(rendered, (preview.width + 20, 32))
                draw = ImageDraw.Draw(pair)
                draw.text((10, 8), "PREVIEW", fill="black")
                draw.text((preview.width + 20, 8), "PDF / PyMuPDF", fill="black")
                pair.save(folder / f"{name}-{index + 1}-comparison.png")
    first_page = PdfReader(folder / "exact.pdf").pages[0]
    report = {"python": platform.python_version(), "correction": asdict(correction),
              "exact_size_mm": [float(first_page.mediabox.width) * 25.4 / 72, float(first_page.mediabox.height) * 25.4 / 72],
              "comparisons": results}
    samples = make_color_samples()
    panel = Image.new("RGB", (samples.width, 110), "white")
    panel.paste(samples, (0, 0))
    panel.paste(correct_image(samples, Correction(vibrance=1)), (0, 65))
    ImageDraw.Draw(panel).text((0, 43), "BEFORE / AFTER VIBRANCE +100", fill="black")
    panel.save(folder / "colour-samples.png")
    benchmark_order = [replace(photo, curve=None) for photo in photos]
    render_page(benchmark_order, Layout(), 0, correction, 2, fast=True)
    elapsed = []
    for value in range(115, 135):
        moving = Correction(.35, 1.12, ((0, 0), (128, value), (255, 255)))
        before = time.perf_counter()
        render_page(benchmark_order, Layout(), 0, moving, 2, fast=True)
        elapsed.append((time.perf_counter() - before) * 1000)
    report["fast_preview_ms_mean"] = sum(elapsed) / len(elapsed)
    report["fast_preview_ms_max"] = max(elapsed)
    (folder / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Comparisons:", len(results), "max raw:", max(max(r['mean_rgb_error']) for r in results),
          "max blurred:", max(max(r['blurred_error']) for r in results))
    print("Exact case: 10 copies, 6 + 4; paper:", report["exact_size_mm"], "mm; frames: 40 x 40 mm")
    print("Live renderer: mean %.1f ms, max %.1f ms" % (report["fast_preview_ms_mean"], report["fast_preview_ms_max"]))


if __name__ == "__main__":
    main()
