"""Local preview of a draft on 127.0.0.1. The page posts the user's decisions back; review() waits for them."""

import asyncio
import base64
import re
import secrets
from importlib.resources import files
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from anki_mcp.media import MEDIA_REF
from anki_mcp.occlusion import io_cards
from anki_mcp.render import render_cards
from anki_mcp.server import App

PAGE = files("anki_mcp").joinpath("preview.html").read_text(encoding="utf-8")


class Preview:
    def __init__(self, app: App):
        self._app = app
        self._token = secrets.token_urlsafe(16)
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._done: dict[str, asyncio.Event] = {}
        self.port = 0

    async def open(self, draft_id: str) -> str | None:
        """Start the server if needed. Returns the URL to open, or None if that page is already open."""
        if self._server is None:
            await self._start()
        if draft_id in self._done:
            return None
        self._done[draft_id] = asyncio.Event()
        return f"http://127.0.0.1:{self.port}/d/{draft_id}?t={self._token}"

    async def wait(self, draft_id: str, seconds: float) -> bool:
        """True once the user pressed Commit on the page."""
        try:
            await asyncio.wait_for(self._done[draft_id].wait(), seconds)
        except asyncio.TimeoutError:
            return False
        del self._done[draft_id]
        return True

    def forget(self, draft_id: str) -> None:
        """The wait was cancelled: open the page again next time."""
        self._done.pop(draft_id, None)

    async def stop(self) -> None:
        if self._server and self._task:
            self._server.should_exit = True
            await self._task

    async def _start(self) -> None:
        routes = [
            Route("/d/{draft_id}", self._page),
            Route("/api/d/{draft_id}", self._cards),
            Route("/api/d/{draft_id}/done", self._submit, methods=["POST"]),
        ]
        config = uvicorn.Config(
            Starlette(routes=routes),
            host="127.0.0.1",
            port=0,
            log_config=None,  # never log to stdout: stdout belongs to MCP
            access_log=False,
            log_level="warning",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                self._task.result()
            await asyncio.sleep(0.02)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]

    def _allowed(self, request: Request) -> bool:
        token = request.query_params.get("t") or request.headers.get("x-token") or ""
        host = request.headers.get("host", "")
        return secrets.compare_digest(token, self._token) and host in {
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
        }

    async def _page(self, request: Request) -> Response:
        if not self._allowed(request):
            return Response("forbidden", status_code=403)
        return HTMLResponse(
            PAGE.replace("__TOKEN__", self._token).replace("__DRAFT__", request.path_params["draft_id"])
        )

    async def _cards(self, request: Request) -> Response:
        if not self._allowed(request):
            return Response("forbidden", status_code=403)
        draft = self._app.drafts.load(request.path_params["draft_id"])

        cards: list[dict[str, Any]] = []
        for note in draft.notes:
            nt = await self._app.note_types.get(note.note_type)
            fields = {k: MEDIA_REF.sub(self._inline_image, v) for k, v in note.fields.items()}
            templates, css = await self._app.note_types.styling(note.note_type)
            sides = io_cards(fields, nt) if nt.kind == "io" else render_cards(templates, fields, nt.kind == "cloze")
            cards.append(
                {
                    "n": note.n,
                    "css": css,
                    "review": note.review,
                    "comment": note.comment or "",
                    "sides": [{"name": name, "front": front, "back": back} for name, front, back in sides],
                }
            )
        return JSONResponse({"cards": cards})

    async def _submit(self, request: Request) -> Response:
        if not self._allowed(request):
            return Response("forbidden", status_code=403)
        draft_id = request.path_params["draft_id"]
        decisions = {d["n"]: d for d in (await request.json())["decisions"]}
        async with self._app.drafts.edit(draft_id) as draft:
            for note in draft.notes:
                d = decisions.get(note.n)
                if d is None:
                    continue
                note.comment = (d.get("comment") or "").strip() or None
                note.review = d.get("review") if d.get("review") in {"accepted", "rejected"} else "open"
                if note.comment and note.review == "accepted":
                    note.review = "open"  # a note means: revise it first
            draft.submitted = True
        if draft_id in self._done:
            self._done[draft_id].set()
        return JSONResponse({"ok": True})

    def _inline_image(self, match: re.Match[str]) -> str:
        # Card frames are sandboxed and cannot load from this server, so images are embedded.
        data = self._app.media.get(match.group(1)).path.read_bytes()
        return f'src="data:image/png;base64,{base64.b64encode(data).decode()}"'
