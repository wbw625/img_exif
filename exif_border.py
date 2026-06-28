#!/usr/bin/env python3
"""Add a bottom white EXIF caption bar to an image."""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

try:
    from PIL import ExifTags, Image, ImageDraw, ImageFont, ImageOps
except ModuleNotFoundError as exc:  # pragma: no cover - exercised before deps exist.
    missing = exc.name or "Pillow"
    raise SystemExit(
        f"Missing dependency: {missing}. Install dependencies with:\n"
        f"  pip install -r requirements.txt"
    ) from exc


FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
COMPANY_WORDS = {
    "camera",
    "cameras",
    "co",
    "company",
    "corp",
    "corporation",
    "digital",
    "gmbh",
    "imaging",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "optical",
    "optics",
    "systems",
}
BRAND_DISPLAY_NAMES = {
    "apple": "Apple",
    "canon": "Canon",
    "fujifilm": "FUJIFILM",
    "hasselblad": "Hasselblad",
    "huawei": "Huawei",
    "leica": "Leica",
    "nikon": "Nikon",
    "olympus": "Olympus",
    "panasonic": "Panasonic",
    "pentax": "PENTAX",
    "ricoh": "Ricoh",
    "samsung": "Samsung",
    "sony": "Sony",
    "xiaomi": "Xiaomi",
}


@dataclass(frozen=True)
class CaptionContent:
    title: str
    exposure_line: str
    secondary_line: str
    brand: str
    raw_brand: str


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add a white bottom border with camera EXIF details."
    )
    parser.add_argument("image", type=Path, help="Input image path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path. Defaults to '<input-stem>_exif.<ext>'.",
    )
    parser.add_argument(
        "--bar-ratio",
        type=float,
        default=0.14,
        help="Bottom bar height as a ratio of image height. Default: 0.14",
    )
    parser.add_argument(
        "--font",
        type=Path,
        help="Optional TrueType/OpenType font path.",
    )
    parser.add_argument(
        "--icon-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "icon",
        help="Directory containing brand icons, matched by file name. Default: ./icon",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=95,
        help="JPEG/WebP output quality. Default: 95",
    )
    return parser


def normalized_exif(image: Image.Image) -> dict[str, Any]:
    raw_exif = image.getexif()
    result: dict[str, Any] = {}

    for tag_id, value in raw_exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        result[name] = value

    # LensModel and a few newer tags can live in the Exif IFD.
    exif_ifd_id = next(
        (tag for tag, name in ExifTags.TAGS.items() if name == "ExifOffset"),
        None,
    )
    if exif_ifd_id is not None:
        try:
            for tag_id, value in raw_exif.get_ifd(exif_ifd_id).items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                result[name] = value
        except (KeyError, TypeError):
            pass

    return result


def rational_to_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        if isinstance(value, tuple) and len(value) == 2:
            numerator, denominator = value
            if denominator == 0:
                return None
            return float(Fraction(int(numerator), int(denominator)))
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    return " ".join(str(value).replace("\x00", " ").split())


def brand_tokens(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", value)]


def brand_key(value: str) -> str:
    tokens = [token for token in brand_tokens(value) if token not in COMPANY_WORDS]
    if not tokens:
        tokens = brand_tokens(value)
    return "".join(tokens)


def display_brand_name(value: str) -> str:
    tokens = [token for token in brand_tokens(value) if token not in COMPANY_WORDS]
    if not tokens:
        return clean_text(value)

    key = "".join(tokens)
    if key in BRAND_DISPLAY_NAMES:
        return BRAND_DISPLAY_NAMES[key]

    return " ".join(BRAND_DISPLAY_NAMES.get(token, token.capitalize()) for token in tokens)


def camera_title(exif: dict[str, Any]) -> str:
    make = clean_text(exif.get("Make"))
    model = clean_text(exif.get("Model"))

    if model:
        return model
    if make:
        return "Unknown model"
    return "Unknown camera"


def format_aperture(exif: dict[str, Any]) -> str:
    f_number = rational_to_float(exif.get("FNumber"))
    if not f_number:
        aperture_value = rational_to_float(exif.get("ApertureValue"))
        if aperture_value:
            f_number = math.sqrt(2**aperture_value)

    if not f_number:
        return ""
    return f"f/{f_number:.1f}".replace(".0", "")


def format_focal_length(value: Any) -> str:
    focal_length = rational_to_float(value)
    if not focal_length:
        return ""
    rounded = round(focal_length, 1)
    text = f"{rounded:.1f}".rstrip("0").rstrip(".")
    return f"{text} mm"


def format_exposure(exif: dict[str, Any]) -> str:
    exposure = rational_to_float(exif.get("ExposureTime"))
    if not exposure:
        shutter_speed = rational_to_float(exif.get("ShutterSpeedValue"))
        if shutter_speed:
            exposure = 2 ** -shutter_speed

    if not exposure:
        return ""
    if exposure < 1:
        denominator = round(1 / exposure)
        return f"1/{denominator} s"
    return f"{exposure:.1f} s".replace(".0", "")


def format_iso(exif: dict[str, Any]) -> str:
    iso = (
        exif.get("ISOSpeedRatings")
        or exif.get("PhotographicSensitivity")
        or exif.get("StandardOutputSensitivity")
        or exif.get("RecommendedExposureIndex")
        or exif.get("ISOSpeed")
    )
    if isinstance(iso, (tuple, list)) and iso:
        iso = iso[0]
    if not iso:
        return ""
    try:
        return f"ISO {int(iso)}"
    except (TypeError, ValueError):
        return f"ISO {clean_text(iso)}"


def format_date(value: Any) -> str:
    text = clean_text(value)
    if len(text) >= 10 and text[4] == ":" and text[7] == ":":
        date = text[:10].replace(":", "-")
        time = text[11:16] if len(text) >= 16 else ""
        return f"{date} {time}".rstrip()
    return text


def format_number(value: Any) -> str:
    number = rational_to_float(value)
    if number is None:
        return clean_text(value)
    return f"{number:.1f}".rstrip("0").rstrip(".")


def format_lens_specification(value: Any) -> str:
    if not isinstance(value, (tuple, list)) or len(value) < 4:
        return ""

    min_focal, max_focal, min_aperture, max_aperture = value[:4]
    min_focal_text = format_number(min_focal)
    max_focal_text = format_number(max_focal)
    min_aperture_text = format_number(min_aperture)
    max_aperture_text = format_number(max_aperture)

    if not min_focal_text:
        return ""

    focal_text = f"{min_focal_text} mm"
    if max_focal_text and max_focal_text != min_focal_text:
        focal_text = f"{min_focal_text}-{max_focal_text} mm"

    aperture_text = ""
    if min_aperture_text:
        aperture_text = f"f/{min_aperture_text}"
        if max_aperture_text and max_aperture_text != min_aperture_text:
            aperture_text = f"f/{min_aperture_text}-{max_aperture_text}"

    return " ".join(part for part in (focal_text, aperture_text) if part)


def lens_name(exif: dict[str, Any]) -> str:
    lens = clean_text(exif.get("LensModel") or exif.get("LensMake"))
    if lens:
        return lens
    lens_spec = format_lens_specification(exif.get("LensSpecification"))
    if lens_spec:
        return f"Lens {lens_spec}"
    return ""


def exif_lines(exif: dict[str, Any], image: Image.Image, input_path: Path) -> CaptionContent:
    raw_brand = clean_text(exif.get("Make"))
    brand = display_brand_name(raw_brand) if raw_brand else ""
    lens = lens_name(exif)
    title_items = [item for item in (camera_title(exif), lens) if item]
    title = "   |   ".join(title_items)
    exposure_items = [
        format_aperture(exif),
        format_focal_length(exif.get("FocalLength")),
        format_exposure(exif),
        format_iso(exif),
    ]

    date = format_date(exif.get("DateTimeOriginal") or exif.get("DateTime"))
    second_line_items = [item for item in (*exposure_items, date) if item]
    exposure_line = "   |   ".join(second_line_items)

    secondary_line = ""
    if not exposure_line:
        secondary_line = "   |   ".join([f"{image.width} x {image.height}", input_path.name])

    return CaptionContent(title, exposure_line, secondary_line, brand, raw_brand)


def brand_icon_path(brand: str, raw_brand: str, icon_dir: Path) -> Path | None:
    if not icon_dir.exists() or not icon_dir.is_dir():
        return None

    target_keys = {brand_key(brand), brand_key(raw_brand)}
    target_keys = {key for key in target_keys if key}
    if not target_keys:
        return None

    for icon_path in sorted(icon_dir.iterdir()):
        if not icon_path.is_file() or icon_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        icon_key = brand_key(icon_path.stem)
        if not icon_key:
            continue
        if any(icon_key == key or icon_key in key or key in icon_key for key in target_keys):
            return icon_path

    return None


def load_font(size: int, explicit_font: Path | None = None) -> ImageFont.FreeTypeFont:
    candidates: list[Path] = []
    if explicit_font:
        candidates.append(explicit_font)
    candidates.extend(Path(font_path) for font_path in FONT_CANDIDATES)

    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue

    return ImageFont.load_default(size=size)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_size: int,
    max_width: int,
    explicit_font: Path | None,
    min_size: int = 14,
) -> ImageFont.ImageFont:
    size = max(font_size, min_size)
    while size > min_size:
        font = load_font(size, explicit_font)
        if text_width(draw, text, font) <= max_width:
            return font
        size -= 2
    return load_font(min_size, explicit_font)


def fit_common_font(
    draw: ImageDraw.ImageDraw,
    texts: list[str],
    font_size: int,
    max_width: int,
    explicit_font: Path | None,
    min_size: int = 14,
) -> ImageFont.ImageFont:
    visible_texts = [text for text in texts if text]
    if not visible_texts:
        return load_font(font_size, explicit_font)

    size = max(font_size, min_size)
    while size > min_size:
        font = load_font(size, explicit_font)
        if all(text_width(draw, text, font) <= max_width for text in visible_texts):
            return font
        size -= 2
    return load_font(min_size, explicit_font)


def compose_image(
    image: Image.Image,
    content: CaptionContent,
    bar_ratio: float,
    font_path: Path | None,
    icon_dir: Path,
) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    bar_height = max(int(height * bar_ratio), int(width * 0.075), 160)
    margin_x = max(int(width * 0.045), 48)

    output = Image.new("RGB", (width, height + bar_height), "white")
    output.paste(image, (0, 0))

    draw = ImageDraw.Draw(output)
    title = content.title
    exposure_line = content.exposure_line
    secondary_line = content.secondary_line

    text_size = max(int(width * 0.017), 24)
    brand_gap = max(int(width * 0.03), 56)
    max_brand_width = max(int(width * 0.18), 180)
    max_brand_height = max(int(bar_height * 0.62), 80)
    brand_image: Image.Image | None = None
    brand_font: ImageFont.ImageFont | None = None
    brand_text = content.brand
    brand_width = 0
    brand_height = 0

    icon_path = brand_icon_path(content.brand, content.raw_brand, icon_dir)
    if icon_path:
        with Image.open(icon_path) as icon:
            brand_image = ImageOps.exif_transpose(icon).convert("RGBA")
            brand_image.thumbnail((max_brand_width, max_brand_height), Image.Resampling.LANCZOS)
        brand_width, brand_height = brand_image.size
    elif brand_text:
        brand_font = fit_font(
            draw,
            brand_text,
            max(int(width * 0.024), 28),
            max_brand_width,
            font_path,
            min_size=16,
        )
        brand_box = draw.textbbox((0, 0), brand_text, font=brand_font)
        brand_width = brand_box[2] - brand_box[0]
        brand_height = brand_box[3] - brand_box[1]

    reserved_width = brand_width + brand_gap if brand_width else 0
    text_left = margin_x + reserved_width
    text_right = width - margin_x
    max_text_width = max(text_right - text_left, 1)

    common_font = fit_common_font(
        draw,
        [title, exposure_line, secondary_line],
        text_size,
        max_text_width,
        font_path,
        min_size=14,
    )
    title_font = common_font
    info_font = common_font
    secondary_font = common_font

    title_box = draw.textbbox((0, 0), title, font=title_font)
    exposure_box = draw.textbbox((0, 0), exposure_line, font=info_font)
    secondary_box = draw.textbbox((0, 0), secondary_line, font=secondary_font)
    line_gap = max(int(bar_height * 0.08), 12)
    block_height = (
        (title_box[3] - title_box[1])
        + (exposure_box[3] - exposure_box[1] if exposure_line else 0)
        + (secondary_box[3] - secondary_box[1] if secondary_line else 0)
        + line_gap * (1 + bool(exposure_line) + bool(secondary_line))
    )
    y = height + max((bar_height - block_height) // 2, 20)

    title_width = text_width(draw, title, title_font)
    draw.text((text_right - title_width, y), title, fill=(18, 18, 18), font=title_font)
    y += title_box[3] - title_box[1] + line_gap

    if exposure_line:
        exposure_width = text_width(draw, exposure_line, info_font)
        draw.text(
            (text_right - exposure_width, y),
            exposure_line,
            fill=(34, 34, 34),
            font=info_font,
        )
        y += exposure_box[3] - exposure_box[1] + line_gap

    if secondary_line:
        secondary_width = text_width(draw, secondary_line, secondary_font)
        draw.text(
            (text_right - secondary_width, y),
            secondary_line,
            fill=(112, 112, 112),
            font=secondary_font,
        )

    brand_x = margin_x
    brand_y = height + (bar_height - brand_height) // 2
    if brand_image:
        output.paste(brand_image, (brand_x, brand_y), brand_image)
    elif brand_text and brand_font:
        draw.text((brand_x, brand_y), brand_text, fill=(18, 18, 18), font=brand_font)

    return output


def default_output_path(input_path: Path) -> Path:
    suffix = input_path.suffix or ".jpg"
    return input_path.with_name(f"{input_path.stem}_exif{suffix}")


def save_image(image: Image.Image, output_path: Path, quality: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    save_kwargs: dict[str, Any] = {}

    if suffix in {".jpg", ".jpeg"}:
        save_kwargs.update(quality=quality, optimize=True, subsampling=0)
    elif suffix == ".webp":
        save_kwargs.update(quality=quality, method=6)

    image.save(output_path, **save_kwargs)


def run(args: argparse.Namespace) -> Path:
    input_path = args.image.expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input image not found: {input_path}")

    if args.bar_ratio <= 0:
        raise SystemExit("--bar-ratio must be greater than 0")

    output_path = (args.output or default_output_path(input_path)).expanduser().resolve()

    with Image.open(input_path) as image:
        exif = normalized_exif(image)
        content = exif_lines(exif, image, input_path)
        composed = compose_image(image, content, args.bar_ratio, args.font, args.icon_dir)
        save_image(composed, output_path, args.quality)

    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_path = run(args)
    print(output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
