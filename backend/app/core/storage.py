"""File storage behind an interface (decision D26): a local folder in development, S3 (or any
S3-compatible store: MinIO, Cloudflare R2) in production — `STORAGE_BACKEND=s3`."""

import secrets
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class StoredFile:
    key: str  # e.g. "tenants/<uuid>/gallery/9f2c...e1.webp"
    url: str
    size: int
    content_type: str


class StorageBackend(Protocol):
    async def save(self, folder: str, data: bytes, *, extension: str, content_type: str) -> StoredFile: ...
    async def delete(self, key: str) -> None: ...
    def url_for(self, key: str) -> str: ...


def _safe_relpath(key: str) -> PurePosixPath:
    p = PurePosixPath(key)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise AppError("Invalid storage key.", code="INVALID_STORAGE_KEY")
    return p


class LocalStorage:
    def __init__(self, root: Path, base_url: str) -> None:
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_relpath(key)).resolve()
        if not path.is_relative_to(self.root):
            raise AppError("Invalid storage key.", code="INVALID_STORAGE_KEY")
        return path

    async def save(self, folder: str, data: bytes, *, extension: str, content_type: str) -> StoredFile:
        ext = extension.lower().lstrip(".")
        if not ext.isalnum():
            raise AppError("Invalid file extension.", code="INVALID_FILE_EXTENSION")
        # Random name: never trust the uploaded file name
        key = str(_safe_relpath(folder) / f"{secrets.token_hex(16)}.{ext}")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredFile(key=key, url=self.url_for(key), size=len(data), content_type=content_type)

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url_for(self, key: str) -> str:
        return f"{self.base_url}/{_safe_relpath(key)}"


class S3Storage:
    """Objects are public-read through the CDN / bucket URL; keys stay random (never the uploaded name).

    boto3 is synchronous, so calls run in a worker thread. Credentials come from the AWS chain
    (environment variables or the server's IAM role) — never from the database.
    """

    def __init__(
        self,
        bucket: str,
        *,
        region: str,
        prefix: str = "",
        endpoint_url: str = "",
        public_base_url: str = "",
        client=None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region
        self.endpoint_url = endpoint_url.rstrip("/")
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url or None)
        self.client = client
        if public_base_url:
            self.base_url = public_base_url.rstrip("/")
        elif endpoint_url:
            self.base_url = f"{self.endpoint_url}/{bucket}"
        else:
            self.base_url = f"https://{bucket}.s3.{region}.amazonaws.com"

    def _object(self, key: str) -> str:
        rel = str(_safe_relpath(key))
        return f"{self.prefix}/{rel}" if self.prefix else rel

    async def save(self, folder: str, data: bytes, *, extension: str, content_type: str) -> StoredFile:
        import asyncio

        ext = extension.lower().lstrip(".")
        if not ext.isalnum():
            raise AppError("Invalid file extension.", code="INVALID_FILE_EXTENSION")
        key = str(_safe_relpath(folder) / f"{secrets.token_hex(16)}.{ext}")
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=self._object(key),
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",  # names are random: safe to cache forever
        )
        return StoredFile(key=key, url=self.url_for(key), size=len(data), content_type=content_type)

    async def delete(self, key: str) -> None:
        import asyncio

        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=self._object(key))

    def url_for(self, key: str) -> str:
        return f"{self.base_url}/{self._object(key)}"


def get_storage() -> StorageBackend:
    s = get_settings()
    if s.storage_backend == "s3":
        global _s3
        if _s3 is None:
            _s3 = S3Storage(
                s.s3_bucket,
                region=s.s3_region,
                prefix=s.s3_prefix,
                endpoint_url=s.s3_endpoint_url,
                public_base_url=s.s3_public_base_url,
            )
        return _s3
    return LocalStorage(s.media_root, s.media_url)


_s3: S3Storage | None = None
