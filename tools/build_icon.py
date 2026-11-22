"""Convert the supplied PDF-compatible Illustrator logo to SVG and Windows ICO.

Requires the development dependency PyMuPDF; production only reads the ICO.
Run: python tools/build_icon.py path/to/source.ai
"""

from io import BytesIO
from pathlib import Path
import shutil
import sys

import pymupdf
from PIL import Image, ImageOps


def main() -> None:
    source = Path(sys.argv[1])
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copy2(source, assets / "logo-source.ai")
    with pymupdf.open(source) as document:
        page = document[0]
        svg = page.get_svg_image(text_as_path=True)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=True)
        logo = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
    (assets / "logo.svg").write_text(svg, encoding="utf-8")
    # Render icons from the original AI/PDF to preserve its shading effects.
    icon = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    contained = ImageOps.contain(logo, (480, 480), Image.Resampling.LANCZOS)
    icon.alpha_composite(contained, ((512 - contained.width) // 2, (512 - contained.height) // 2))
    icon.save(assets / "logo.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    icon.save(assets / "logo.png")
    print("Created assets/logo.svg, logo.ico (16–256 px), logo.png; original preserved as logo-source.ai")


if __name__ == "__main__":
    main()
