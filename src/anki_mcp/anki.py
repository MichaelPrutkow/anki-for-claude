import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from mcp.server.mcpserver.exceptions import ToolError

API_VERSION = 6
LAUNCH_WAIT_SECONDS = 30


class AnkiError(ToolError):
    """Anything that went wrong talking to Anki. The message is shown to Claude."""


class AnkiTimeout(AnkiError):
    pass


class AnkiClient:
    def __init__(self, http: httpx.AsyncClient, url: str):
        self._http = http
        self._url = url
        self._launch_lock = asyncio.Lock()

    async def invoke(self, action: str, *, timeout: float = 30.0, **params: Any) -> Any:
        body = await self._request({"action": action, "version": API_VERSION, "params": params}, timeout)
        return _unwrap(action, body)

    async def multi(self, calls: list[tuple[str, dict[str, Any]]], *, timeout: float = 50.0) -> list[Any]:
        """Several actions in one request. Failed actions come back as AnkiError instead of raising."""
        actions = [{"action": a, "version": API_VERSION, "params": p} for a, p in calls]
        results = await self.invoke("multi", timeout=timeout, actions=actions)
        out: list[Any] = []
        for (action, _), item in zip(calls, results, strict=True):
            try:
                out.append(_unwrap(action, item))
            except AnkiError as exc:
                out.append(exc)
        return out

    async def _request(self, payload: dict[str, Any], timeout: float) -> Any:
        try:
            return await self._send(payload, timeout)
        except httpx.ConnectError:
            await self._ensure_running()
            return await self._send(payload, timeout)

    async def _send(self, payload: dict[str, Any], timeout: float) -> Any:
        try:
            response = await self._http.post(self._url, json=payload, timeout=timeout)
        except httpx.TimeoutException:
            raise AnkiTimeout(
                "Anki did not answer in time. Usually a dialog window is open in Anki: ask the user to close it."
            ) from None
        try:
            return response.json()
        except ValueError:
            raise AnkiError(f"The answer from {self._url} is not JSON. Is AnkiConnect running there?") from None

    async def _ensure_running(self) -> None:
        async with self._launch_lock:
            if await self._is_up():
                return
            if sys.platform != "darwin":
                raise AnkiError(
                    "AnkiConnect does not answer. Ask the user to start Anki and to check that the AnkiConnect "
                    "add-on is installed."
                )
            process = await asyncio.create_subprocess_exec("open", "-ga", "Anki")
            if await process.wait() != 0:
                raise AnkiError("Anki is not installed, or macOS could not start it. Ask the user to start it.")
            for _ in range(LAUNCH_WAIT_SECONDS):
                await asyncio.sleep(1)
                if await self._is_up():
                    return
            raise AnkiError(
                "Anki was started, but AnkiConnect does not answer. Either a window is waiting in Anki "
                "(for example the profile chooser) or the AnkiConnect add-on is not installed."
            )

    async def _is_up(self) -> bool:
        try:
            await self._send({"action": "version", "version": API_VERSION}, timeout=2.0)
            return True
        except (httpx.HTTPError, AnkiError):
            return False


def _unwrap(action: str, body: Any) -> Any:
    if not isinstance(body, dict) or "result" not in body or "error" not in body:
        raise AnkiError(f"{action}: unexpected response from AnkiConnect")
    if body["error"] is not None:
        raise AnkiError(f"{action}: {body['error']}")
    return body["result"]


Kind = Literal["basic", "cloze", "io"]

IO_STOCK_KIND = 6
IO_ROLES = {0: "occlusion", 1: "image", 2: "header", 3: "back_extra", 4: "comments"}


@dataclass(frozen=True)
class NoteType:
    name: str
    kind: Kind
    fields: tuple[str, ...]
    io_fields: dict[str, str] | None = None  # role -> field name, only for Image Occlusion

    @classmethod
    def from_anki(cls, model: dict[str, Any]) -> "NoteType":
        flds = sorted(model["flds"], key=lambda f: f["ord"])
        names = tuple(f["name"] for f in flds)
        if model.get("originalStockKind") == IO_STOCK_KIND:
            io_fields = {}
            for f in flds:
                role = IO_ROLES.get(f["tag"] if f.get("tag") is not None else f["ord"])
                if role:
                    io_fields[role] = f["name"]
            return cls(model["name"], "io", names, io_fields)
        return cls(model["name"], "cloze" if model.get("type") == 1 else "basic", names)

    @property
    def label(self) -> str:
        return {"basic": "basic", "cloze": "cloze", "io": "image occlusion"}[self.kind]

    def normalize(self, fields: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        """Map field names case-insensitively to the real ones. Returns (fields, unknown names)."""
        lookup = {name.lower(): name for name in self.fields}
        lookup.update(self.io_fields or {})
        normalized, unknown = {}, []
        for key, value in fields.items():
            real = lookup.get(key.strip().lower())
            if real is None:
                unknown.append(key)
            else:
                normalized[real] = value
        return normalized, unknown


class NoteTypes:
    """The collection's note types, cached for five minutes."""

    def __init__(self, anki: AnkiClient):
        self._anki = anki
        self._cache: dict[str, NoteType] = {}
        self._loaded_at = 0.0

    async def all(self) -> list[NoteType]:
        if time.monotonic() - self._loaded_at > 300:
            await self._reload()
        return list(self._cache.values())

    async def get(self, name: str) -> NoteType:
        if name not in self._cache or time.monotonic() - self._loaded_at > 300:
            await self._reload()
        if name not in self._cache:
            raise AnkiError(f"Note type '{name}' does not exist. Available: {', '.join(sorted(self._cache))}")
        return self._cache[name]

    async def _reload(self) -> None:
        names = await self._anki.invoke("modelNames")
        models = await self._anki.invoke("findModelsByName", modelNames=names)
        self._cache = {m["name"]: NoteType.from_anki(m) for m in models}
        self._loaded_at = time.monotonic()
