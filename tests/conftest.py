from collections.abc import AsyncGenerator

import httpx
import pytest
from fake_anki import FakeAnki
from mcp.client import Client

from anki_mcp import collection, drafts, images, stats, youtube  # noqa: F401  importing registers the tools
from anki_mcp.server import mcp


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def anki(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeAnki:
    fake = FakeAnki()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=fake.transport(), **kwargs))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ANKI_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("ANKI_AUTO_LAUNCH", "false")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return fake


@pytest.fixture
async def client(anki: FakeAnki) -> AsyncGenerator[Client, None]:
    async with Client(mcp) as c:
        yield c
