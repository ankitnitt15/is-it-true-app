import io

from PIL import Image

import config


def downscale_if_oversized(image_bytes: bytes, mime_type: str) -> bytes:
    """Resize (never recompress) an image whose longest side exceeds
    config.MAX_IMAGE_DIMENSION -- large phone-camera photos are the main
    latency cost here. Images already within budget pass through
    untouched, and a resized image keeps its original format, so this
    never introduces lossy re-encoding artifacts that would hurt reading
    small printed text (infographics, screenshots) the extraction step
    depends on.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        if max(width, height) <= config.MAX_IMAGE_DIMENSION:
            return image_bytes

        scale = config.MAX_IMAGE_DIMENSION / max(width, height)
        new_size = (round(width * scale), round(height * scale))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        save_kwargs = {"quality": 90} if img.format == "JPEG" else {}
        resized.save(buffer, format=img.format, **save_kwargs)
        return buffer.getvalue()
