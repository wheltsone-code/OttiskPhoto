"""Render the approved SVG geometry into transparent Windows branding assets.

Requires development-only PyMuPDF and Pillow. Runtime reads only the generated ICO.
Run: python tools/build_icon.py [path/to/original.svg]
Without an argument, assets/logo.svg is the sole geometry source.
"""

from io import BytesIO
from pathlib import Path
import re
import shutil
import sys

import pymupdf
from PIL import Image, ImageOps


def main() -> None:
    assets = Path(__file__).resolve().parent.parent / "assets"
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else assets / "logo.svg"
    if source.suffix.lower() != ".svg":
        raise SystemExit("Use the approved original SVG, not a raster image or PDF.")
    assets.mkdir(exist_ok=True)
    # MuPDF does not resolve SVG class rules. Inline the original fill in the
    # in-memory render input only; keep the authoritative SVG byte-for-byte.
    svg = source.read_text(encoding="utf-8")
    fill = re.search(r"fill:\s*(#[0-9a-fA-F]{6})", svg)
    if fill is None or fill.group(1).lower() != "#fd3977":
        raise SystemExit("Expected the approved brand fill #FD3977")
    color = fill.group(1)
    if source.resolve() != (assets / "logo.svg").resolve():
        shutil.copy2(source, assets / "logo.svg")
    render_svg = svg.replace('class="st0"', f'fill="{color}"')
    with pymupdf.open(stream=render_svg.encode("utf-8"), filetype="svg") as document:
        page = document[0]
        # Supersample the unchanged vector before filtering to small Windows sizes.
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2048 / page.rect.width, 2048 / page.rect.height), alpha=True)
        logo = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
    icon = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    contained = ImageOps.contain(logo, (480, 480), Image.Resampling.LANCZOS)
    icon.alpha_composite(contained, ((512 - contained.width) // 2, (512 - contained.height) // 2))
    icon.save(assets / "logo.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    icon.save(assets / "logo.png")
    print("Created transparent logo.ico (16–256 px) and logo.png from assets/logo.svg")


if __name__ == "__main__":
    main()
