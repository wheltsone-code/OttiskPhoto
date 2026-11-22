"""Explicit ICC boundaries: imported pixels and corrections are working sRGB."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path

from PIL import Image, ImageCms


@lru_cache(maxsize=1)
def srgb_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def to_srgb(image: Image.Image) -> Image.Image:
    """Never claim a broken/unsupported embedded ICC has been converted."""
    embedded = image.info.get("icc_profile")
    alpha = image.convert("RGBA").getchannel("A") if "A" in image.getbands() or "transparency" in image.info else None
    if embedded:
        try:
            profile = ImageCms.ImageCmsProfile(BytesIO(embedded))
            mode = image.mode if image.mode in ("RGB", "CMYK", "LAB", "L") else "RGB"
            result = ImageCms.profileToProfile(image.convert(mode), profile,
                                               ImageCms.ImageCmsProfile(BytesIO(srgb_bytes())), outputMode="RGB")
        except (OSError, ValueError, TypeError, ImageCms.PyCMSError) as error:
            raise ValueError(f"Встроенный ICC не читается или несовместим: {error}. Фото не импортировано.") from error
    else:
        result = image.convert("RGB")
    if alpha is not None:
        white = Image.new("RGB", result.size, "white")
        white.paste(result, mask=alpha)
        result = white
    result.info["icc_profile"] = srgb_bytes()
    return result


@dataclass(frozen=True)
class OutputProfile:
    path: Path
    name: str
    data: bytes

    @classmethod
    def read(cls, path: Path):
        try:
            data = path.read_bytes()
            profile = ImageCms.ImageCmsProfile(BytesIO(data))
            # GDI's bitmap transport is RGB. CMYK/Lab/device-link profiles cannot
            # be silently treated as RGB device output.
            if profile.profile.xcolor_space.strip() != "RGB" or profile.profile.device_class.strip() == "link":
                raise ValueError("для вывода GDI нужен обычный RGB ICC; CMYK, Lab и DeviceLink не поддерживаются")
            ImageCms.buildTransformFromOpenProfiles(ImageCms.ImageCmsProfile(BytesIO(srgb_bytes())), profile, "RGB", "RGB")
            return cls(path.resolve(), ImageCms.getProfileDescription(profile).strip(), data)
        except (OSError, ValueError, TypeError, ImageCms.PyCMSError) as error:
            raise ValueError(f"Несовместимый или недоступный выходной ICC: {path.name}. {error}") from error

    def convert(self, image):
        transform = _output_transform(self.data)
        return ImageCms.applyTransform(image, transform)


@lru_cache(maxsize=4)
def _output_transform(data):
    return ImageCms.buildTransformFromOpenProfiles(
        ImageCms.ImageCmsProfile(BytesIO(srgb_bytes())), ImageCms.ImageCmsProfile(BytesIO(data)), "RGB", "RGB")


def installed_profiles() -> list[Path]:
    folder = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/spool/drivers/color"
    return sorted((p for p in folder.glob("*") if p.suffix.lower() in (".icc", ".icm")), key=lambda p: p.name.casefold())


class ProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OttiskPhoto" / "profiles.json"

    def load(self):
        try:
            result = json.loads(self.path.read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key):
        value = self.load().get(key)
        return Path(value) if isinstance(value, str) else None

    def put(self, key, profile):
        values = self.load()
        values[key] = str(profile)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
