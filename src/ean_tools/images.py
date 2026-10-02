"""Printable barcode images (PNG) at an exact physical size.

The bars are drawn directly with Pillow using a whole number of pixels per
module. Rendering at another size and resizing afterwards (what many scripts
do) blurs bar edges and makes bar widths uneven, which hurts scanning.

Requires the optional dependency Pillow (``pip install ean-tools[images]``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .core import MODULES, encode_modules, guard_modules

MM_PER_INCH = 25.4
QUIET_LEFT = 11  # modules, GS1 minimum quiet zones for EAN-13
QUIET_RIGHT = 7
TOTAL_MODULES = QUIET_LEFT + MODULES + QUIET_RIGHT
GS1_MIN_MODULE_MM = 0.264  # 80 % magnification, the GS1 lower limit
# Below this, label printers cannot reproduce the bars reliably: refuse
# instead of producing an image that looks fine on screen but won't scan.
HARD_MIN_MODULE_MM = 0.2
GUARD_EXTENSION = 5  # modules that guard bars extend below data bars
MIN_BAR_MODULES = 15  # below this the code is too squat to scan reliably


class ImageError(ValueError):
    """The requested size cannot hold a scannable barcode."""


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class ImageOptions:
    width_mm: float = 40.0
    height_mm: float = 25.0
    dpi: int = 300
    show_text: bool = True


@dataclass(frozen=True)
class Layout:
    width_px: int
    height_px: int
    module_px: int
    left_px: int
    top_px: int
    bar_px: int
    font_px: int
    module_mm: float
    warnings: list[str] = field(default_factory=list)


def compute_layout(options: ImageOptions) -> Layout:
    """Work out pixel geometry for the requested physical size.

    Raises ImageError if the size is too small at that resolution.
    """
    if options.dpi <= 0 or options.width_mm <= 0 or options.height_mm <= 0:
        raise ImageError("ancho, alto y DPI deben ser positivos")
    width_px = round(options.width_mm * options.dpi / MM_PER_INCH)
    height_px = round(options.height_mm * options.dpi / MM_PER_INCH)

    module_px = width_px // TOTAL_MODULES
    if module_px < 1:
        min_mm = TOTAL_MODULES * MM_PER_INCH / options.dpi
        raise ImageError(
            f"{options.width_mm} mm a {options.dpi} DPI es demasiado estrecho: "
            f"mínimo {min_mm:.1f} mm (o sube los DPI)"
        )

    margin = 2 * module_px
    font_px = 8 * module_px if options.show_text else 0
    text_px = (module_px + font_px) if options.show_text else GUARD_EXTENSION * module_px
    bar_px = height_px - 2 * margin - text_px
    if bar_px < MIN_BAR_MODULES * module_px:
        min_mm = (2 * margin + text_px + MIN_BAR_MODULES * module_px) * MM_PER_INCH / options.dpi
        raise ImageError(
            f"{options.height_mm} mm de alto es insuficiente para este ancho: "
            f"mínimo {min_mm:.1f} mm"
        )

    warnings = []
    module_mm = module_px * MM_PER_INCH / options.dpi
    if module_mm < HARD_MIN_MODULE_MM:
        raise ImageError(
            f"barra mínima de {module_mm:.3f} mm: demasiado fina para imprimirse "
            f"(mínimo {HARD_MIN_MODULE_MM} mm); aumenta el ancho o los DPI"
        )
    if module_mm < GS1_MIN_MODULE_MM:
        warnings.append(
            f"barra mínima de {module_mm:.3f} mm, por debajo del mínimo GS1 "
            f"({GS1_MIN_MODULE_MM} mm): puede costar leerlo; aumenta ancho o DPI"
        )
    symbol_px = TOTAL_MODULES * module_px
    content_px = 2 * margin + bar_px + text_px
    return Layout(
        width_px=width_px,
        height_px=height_px,
        module_px=module_px,
        left_px=(width_px - symbol_px) // 2,
        top_px=(height_px - content_px) // 2 + margin,
        bar_px=bar_px,
        font_px=font_px,
        module_mm=module_mm,
        warnings=warnings,
    )


def _load_font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # old Pillow or no FreeType
        return ImageFont.load_default()


def render(code: str, options: ImageOptions = ImageOptions()):
    """Return a PIL ``Image`` (mode "1", black and white) of the barcode."""
    from PIL import Image, ImageDraw

    layout = compute_layout(options)
    pattern = encode_modules(code)
    guards = guard_modules()
    m = layout.module_px

    img = Image.new("1", (layout.width_px, layout.height_px), 1)
    draw = ImageDraw.Draw(img)

    x0 = layout.left_px + QUIET_LEFT * m
    y0 = layout.top_px
    for i, bit in enumerate(pattern):
        if bit != "1":
            continue
        bottom = y0 + layout.bar_px
        if i in guards:
            bottom += GUARD_EXTENSION * m
        x = x0 + i * m
        draw.rectangle([x, y0, x + m - 1, bottom - 1], fill=0)

    if options.show_text:
        font = _load_font(layout.font_px)
        text_top = y0 + layout.bar_px + m
        # First digit sits in the left quiet zone; then two groups of six,
        # one per 7-module digit slot.
        slots = [(layout.left_px + (QUIET_LEFT - 7) * m, code[0])]
        slots += [(x0 + (3 + 7 * k) * m, d) for k, d in enumerate(code[1:7])]
        slots += [(x0 + (50 + 7 * k) * m, d) for k, d in enumerate(code[7:13])]
        for slot_x, digit in slots:
            left, top, right, _ = draw.textbbox((0, 0), digit, font=font)
            x = slot_x + (7 * m - (right - left)) // 2 - left
            draw.text((x, text_top - top), digit, font=font, fill=0)
    return img


def save_png(code: str, path: str | os.PathLike[str], options: ImageOptions = ImageOptions()) -> Path:
    """Render and save a PNG with the DPI stored in its metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    render(code, options).save(path, format="PNG", dpi=(options.dpi, options.dpi))
    return path


def png_bytes(code: str, options: ImageOptions = ImageOptions()) -> bytes:
    import io

    buf = io.BytesIO()
    render(code, options).save(buf, format="PNG", dpi=(options.dpi, options.dpi))
    return buf.getvalue()
