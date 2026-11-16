"""File storage behind an interface: local folder now, S3 later (decision D26)."""

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


def get_storage() -> StorageBackend:
    s = get_settings()
    return LocalStorage(s.media_root, s.media_url)
