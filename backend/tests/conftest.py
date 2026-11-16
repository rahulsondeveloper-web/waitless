import os

# Must be set before any app module reads settings.
os.environ["ENVIRONMENT"] = "test"

from collections.abc import AsyncIterator  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import api  # noqa: E402


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    return get_settings()
