import io

import pytest
from PIL import Image

from app.core.errors import AppError
from app.services.media import process_image
from tests.conftest import image_bytes


def test_png_becomes_resized_webp() -> None:
    out = process_image(image_bytes(3000, 1500), "gallery")
    img = Image.open(io.BytesIO(out.data))
    assert img.format == "WEBP"
    assert (out.width, out.height) == (2000, 1000) == img.size


def test_logo_keeps_transparency() -> None:
    raw = image_bytes(300, 300, mode="RGBA")
    out = process_image(raw, "logo")
    assert Image.open(io.BytesIO(out.data)).mode == "RGBA"


def test_exif_and_gps_are_removed() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x8825] = {2: (18.0, 31.0, 0.0)}  # GPSInfo → latitude
    raw = image_bytes(800, 600, fmt="JPEG", exif=exif.tobytes())
    assert Image.open(io.BytesIO(raw)).getexif()  # input really carries EXIF
    out = Image.open(io.BytesIO(process_image(raw, "gallery").data))
    assert not out.getexif()
    assert "exif" not in out.info


def test_rejects_non_images() -> None:
    with pytest.raises(AppError) as e:
        process_image(b"<?php echo 'hi'; ?>", "gallery")
    assert e.value.code == "INVALID_IMAGE"


def test_rejects_unsupported_formats() -> None:
    with pytest.raises(AppError) as e:
        process_image(image_bytes(600, 400, fmt="GIF"), "gallery")
    assert e.value.code == "UNSUPPORTED_IMAGE_TYPE" and e.value.status_code == 415


def test_rejects_too_small() -> None:
    with pytest.raises(AppError) as e:
        process_image(image_bytes(32, 32), "logo")
    assert e.value.code == "INVALID_IMAGE" and e.value.details["min_width"] == 64


def test_rejects_decompression_bomb() -> None:
    bomb = image_bytes(9500, 9500, mode="1")  # tiny file, 90 megapixels when decoded
    assert len(bomb) < 200_000
    with pytest.raises(AppError) as e:
        process_image(bomb, "gallery")
    assert e.value.code == "INVALID_IMAGE"
