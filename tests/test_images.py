import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from ean_tools.core import MODULES, encode_modules  # noqa: E402
from ean_tools.images import (  # noqa: E402
    QUIET_LEFT,
    ImageError,
    ImageOptions,
    compute_layout,
    render,
    save_png,
)

CODE = "2000100400234"


def test_default_size_is_40x25mm_at_300dpi():
    layout = compute_layout(ImageOptions())
    assert (layout.width_px, layout.height_px) == (472, 295)
    assert layout.module_px == 4
    assert layout.warnings == []


def test_small_module_warns():
    assert compute_layout(ImageOptions(30, 20, 203)).warnings


@pytest.mark.parametrize(
    "options, fragment",
    [
        (ImageOptions(9, 25, 300), "estrecho"),
        (ImageOptions(25, 15, 203), "demasiado fina"),  # 1 px = 0.125 mm
        (ImageOptions(40, 5, 300), "alto"),
        (ImageOptions(0, 25, 300), "positivos"),
        (ImageOptions(40, 25, 0), "positivos"),
    ],
)
def test_impossible_sizes(options, fragment):
    with pytest.raises(ImageError, match=fragment):
        compute_layout(options)


@pytest.mark.parametrize("options", [ImageOptions(), ImageOptions(30, 20, 203), ImageOptions(40, 25, 600, False)])
def test_bars_are_pixel_exact(options):
    """Each module is a whole number of pure black/white pixels: no blur."""
    img = render(CODE, options)
    layout = compute_layout(options)
    assert img.size == (layout.width_px, layout.height_px)
    assert {color for _, color in img.convert("L").getcolors()} <= {0, 255}
    m = layout.module_px
    x0 = layout.left_px + QUIET_LEFT * m
    y = layout.top_px + layout.bar_px // 2
    read = "".join(
        "1" if img.getpixel((x0 + i * m + m // 2, y)) == 0 else "0" for i in range(MODULES)
    )
    assert read == encode_modules(CODE)
    # Quiet zones are blank.
    assert all(img.getpixel((x, y)) for x in range(0, x0))
    assert all(img.getpixel((x, y)) for x in range(x0 + MODULES * m, layout.width_px))


def test_saved_png_has_dpi(tmp_path):
    path = save_png(CODE, tmp_path / "sub" / "x.png", ImageOptions(dpi=600))
    with Image.open(path) as img:
        assert round(img.info["dpi"][0]) == 600


@pytest.mark.parametrize("options", [ImageOptions(), ImageOptions(30, 20, 203), ImageOptions(50, 15, 300, False)])
def test_images_scan(options):
    zxingcpp = pytest.importorskip("zxingcpp")
    for code in [CODE, "2000700100008", "2999999999991"]:
        results = zxingcpp.read_barcodes(render(code, options).convert("L"))
        assert [r.text for r in results] == [code]
