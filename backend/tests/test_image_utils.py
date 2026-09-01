import io

from PIL import Image

import image_utils


def _make_image_bytes(width, height, fmt, **save_kwargs):
    img = Image.new("RGB", (width, height), color="white")
    buffer = io.BytesIO()
    img.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def test_oversized_image_is_resized_and_keeps_format():
    raw = _make_image_bytes(4000, 3000, "JPEG", quality=95)

    resized = image_utils.downscale_if_oversized(raw, "image/jpeg")

    assert len(resized) < len(raw)
    with Image.open(io.BytesIO(resized)) as img:
        assert max(img.size) <= image_utils.config.MAX_IMAGE_DIMENSION
        assert img.format == "JPEG"


def test_normal_sized_image_passes_through_untouched():
    raw = _make_image_bytes(800, 600, "PNG")

    out = image_utils.downscale_if_oversized(raw, "image/png")

    assert out == raw


def test_resized_png_stays_lossless_format():
    raw = _make_image_bytes(3000, 3000, "PNG")

    resized = image_utils.downscale_if_oversized(raw, "image/png")

    with Image.open(io.BytesIO(resized)) as img:
        assert img.format == "PNG"
        assert max(img.size) == image_utils.config.MAX_IMAGE_DIMENSION
