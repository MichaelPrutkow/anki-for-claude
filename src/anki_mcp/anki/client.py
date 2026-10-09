import asyncio
import sys
from typing import Any

import httpx

from anki_mcp.config import Config

API_VERSION = 6


class AnkiError(Exception):
    """An Error occured with the AnkiClient"""


class AnkiUnavailable(AnkiError):
    pass


class AnkiTimeout(AnkiError):
    pass


class AnkiActionError(AnkiError):
    def __init__(self, action: str, message: str):
        super().__init__(f"{action}: {message}")
        self.action = action
        self.message = message


class AnkiClient:
    def __init__(self, http: httpx.AsyncClient, config: Config):
        self._http = http
        self._config = config
        self._launch_lock = asyncio.Lock()

    async def invoke(self, action: str, *, timeout: float = 30.0, **params: Any) -> Any:
        payload = {"action": action, "version": API_VERSION, "params": params}
        body = await self._request(payload, timeout)
        return self._unwrap(action, body)

    async def multi(
        self, calls: list[tuple[str, dict[str, Any]]], *, timeout: float = 60.0
    ) -> list[Any]:
        actions = [{"action": a, "version": API_VERSION, "params": p} for a, p in calls]
        results = await self.invoke("multi", timeout=timeout, actions=actions)
        out: list[Any] = []
        for (action, _), item in zip(calls, results, strict=True):
            try:
                out.append(self._unwrap(action, item))
            except AnkiActionError as exc:
                out.append(exc)
        return out

    async def ensure_running(self) -> None:
        async with self._launch_lock:
            if await self._is_up():
                return
            await self._launch()
            for _ in range(45):
                await asyncio.sleep(1)
                if await self._is_up():
                    return
            raise AnkiUnavailable(
                "Anki started, but AnkiConnect doesn't answer. Make sure AnkiConnect is installed and no Dialogue is opended in Anki"
            )

    async def _request(self, payload: dict[str, Any], timeout: float) -> Any:
        try:
            return await self._send(payload, timeout)
        except AnkiUnavailable:
            if not self._config.auto_launch:
                raise
            await self.ensure_running()
            return await self._send(payload, timeout)

    async def _send(self, payload: dict[str, Any], timeout: float) -> Any:
        try:
            response = await self._http.post(
                self._config.anki_url, json=payload, timeout=timeout
            )
        except httpx.ConnectError as exc:
            raise AnkiUnavailable(
                f"AnkiConnect doesn't respound under {self._config.anki_url}. Is it running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AnkiTimeout(
                "Anki doesn't respond in time. Is a dialogue window open?"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise AnkiError(
                "The Response isn't valid JSON. Is AnkiConnect running?"
            ) from exc

    async def _is_up(self) -> bool:
        try:
            await self._send({"action": "version", "version": API_VERSION}, timeout=2.0)
            return True
        except AnkiError:
            return False

    async def _launch(self) -> None:
        if sys.platform != "darwin":
            raise AnkiUnavailable(
                "Anki is not running. Auto-Start is only supported for macOS"
            )
        process = await asyncio.create_subprocess_exec("open", "-ga", "Anki")
        await process.wait()

    @staticmethod
    def _unwrap(action: str, body: Any) -> Any:
        if not isinstance(body, dict) or "result" not in body or "error" not in body:
            raise AnkiError(f"{action}: unexpeted Response from AnkiConnect")
        if body["error"] is not None:
            raise AnkiActionError(action, str(body["error"]))
        return body["result"]
