"""Image upload pipeline (PRD §5.2, §5.3, §26 "secure file uploads").

The raw upload is never stored. Every image is:
  1. size-limited while streaming (MAX_UPLOAD_MB)
  2. decoded by Pillow (content sniffing, not the file name / Content-Type), bomb-protected
  3. limited to JPEG / PNG / WebP input
  4. auto-rotated from EXIF, then re-encoded to WebP — which drops EXIF/GPS and any embedded payload
  5. resized to the kind's maximum, checked against its minimum
  6. stored under a random name in the tenant's folder
"""

import io
import logging
import uuid
from dataclasses import dataclass

import anyio.to_thread
from fastapi import UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.storage import get_storage
from app.models.profile import MediaFile

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 40_000_000  # ~ 8000 x 5000; larger raises DecompressionBombError
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class ImageSpec:
    max_w: int
    max_h: int
    min_w: int
    min_h: int
    quality: int


SPECS: dict[str, ImageSpec] = {
    "logo": ImageSpec(max_w=512, max_h=512, min_w=64, min_h=64, quality=90),
    "cover": ImageSpec(max_w=2400, max_h=1600, min_w=800, min_h=300, quality=82),
    "gallery": ImageSpec(max_w=2000, max_h=2000, min_w=400, min_h=300, quality=82),
    "menu_item": ImageSpec(max_w=1200, max_h=1200, min_w=300, min_h=300, quality=82),
}


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int


class InvalidImageError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "INVALID_IMAGE"


def process_image(data: bytes, kind: str) -> ProcessedImage:
    """CPU-bound; call through a worker thread."""
    spec = SPECS[kind]
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()  # structural check; the image must be reopened afterwards
        if fmt not in ALLOWED_FORMATS:
            raise AppError(
                "Upload a JPEG, PNG or WebP image.",
                code="UNSUPPORTED_IMAGE_TYPE",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        with Image.open(io.BytesIO(data)) as src:
            src.load()
            img = ImageOps.exif_transpose(src)
    except Image.DecompressionBombError as exc:
        raise InvalidImageError("This image is too large to process.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError("This file is not a valid image.") from exc

    if img.width < spec.min_w or img.height < spec.min_h:
        raise InvalidImageError(
            f"Image is too small. Use at least {spec.min_w} x {spec.min_h} pixels.",
            details={"min_width": spec.min_w, "min_height": spec.min_h, "width": img.width, "height": img.height},
        )

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    img.thumbnail((spec.max_w, spec.max_h), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, "WEBP", quality=spec.quality, method=4)  # no exif= argument → no metadata
    return ProcessedImage(data=out.getvalue(), width=img.width, height=img.height)


async def read_upload(upload: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await upload.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > limit:
            raise AppError(
                f"File is larger than {get_settings().max_upload_mb} MB.",
                code="FILE_TOO_LARGE",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
    if not buf:
        raise InvalidImageError("The file is empty.")
    return bytes(buf)


async def store_image(
    session: AsyncSession, *, tenant_id: uuid.UUID, kind: str, upload: UploadFile, actor_user_id: uuid.UUID | None
) -> MediaFile:
    """Validate, process and store an image; adds the MediaFile row to the session (caller commits)."""
    raw = await read_upload(upload)
    processed = await anyio.to_thread.run_sync(process_image, raw, kind)
    stored = await get_storage().save(
        f"tenants/{tenant_id}/{kind}", processed.data, extension="webp", content_type="image/webp"
    )
    media = MediaFile(
        tenant_id=tenant_id,
        kind=kind,
        storage_key=stored.key,
        mime="image/webp",
        width=processed.width,
        height=processed.height,
        bytes=stored.size,
        created_by=actor_user_id,
    )
    session.add(media)
    try:
        await session.flush()
    except Exception:
        await get_storage().delete(stored.key)  # don't leave an orphan file behind
        raise
    return media


async def delete_files(keys: list[str]) -> None:
    """Remove stored files after the database change committed. Failures are logged, not raised."""
    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:
            log.warning("Could not delete media file %s", key, exc_info=True)


def media_url(media: MediaFile | None) -> str | None:
    return get_storage().url_for(media.storage_key) if media else None
