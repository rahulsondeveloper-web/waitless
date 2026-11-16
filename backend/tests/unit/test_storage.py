from pathlib import Path

import pytest

from app.core.errors import AppError
from app.core.storage import LocalStorage


async def test_save_uses_random_name_and_returns_url(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, "/media")
    stored = await storage.save("tenants/abc/gallery", b"img", extension="webp", content_type="image/webp")
    assert stored.key.startswith("tenants/abc/gallery/") and stored.key.endswith(".webp")
    assert stored.url == f"/media/{stored.key}"
    assert (tmp_path / stored.key).read_bytes() == b"img"

    other = await storage.save("tenants/abc/gallery", b"img", extension="webp", content_type="image/webp")
    assert other.key != stored.key


async def test_delete_removes_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, "/media")
    stored = await storage.save("x", b"1", extension="png", content_type="image/png")
    await storage.delete(stored.key)
    assert not (tmp_path / stored.key).exists()
    await storage.delete(stored.key)  # deleting twice is fine


@pytest.mark.parametrize("folder", ["../outside", "/etc", "a/../../b"])
async def test_path_traversal_is_rejected(tmp_path: Path, folder: str) -> None:
    storage = LocalStorage(tmp_path, "/media")
    with pytest.raises(AppError):
        await storage.save(folder, b"x", extension="png", content_type="image/png")


async def test_bad_extension_is_rejected(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, "/media")
    with pytest.raises(AppError):
        await storage.save("x", b"x", extension="php/../x", content_type="text/plain")
