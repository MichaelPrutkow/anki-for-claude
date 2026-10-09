from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.media import MediaStore
    from anki_mcp.preview import Preview

INSTRUCTIONS = """\
Tools for the user's real Anki collection. To write flashcards, follow the 'cards' skill.
Workflow: overview -> draft_add -> review. review opens a preview, waits for the user, commits the
accepted cards and returns the user's notes; apply them with draft_edit and call review again.
Fix wrong cards with update_notes (keeps review history). Every change returns a batch id for undo.
"""

CREATED_TAG = "mcp::created"
BATCH_PREFIX = "mcp::batch::"

logging.getLogger("httpx").setLevel(logging.WARNING)


def _annotations(read_only: bool, destructive: bool, idempotent: bool, web: bool = False):
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=web,
    )


READ_ONLY = _annotations(True, False, True)
DRAFT_ONLY = _annotations(True, False, False)
ADDS_NEW = _annotations(False, False, False)
OVERWRITES = _annotations(False, True, True)
WEB_READ = _annotations(True, False, True, web=True)
SYNC = _annotations(False, False, True, web=True)
ASK_USER = {"anthropic/requiresUserInteraction": True}


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


@dataclass
class App:
    anki: AnkiClient
    note_types: NoteTypes
    drafts: DraftStore
    journal: Journal
    media: MediaStore
    roots: list[Path]  # folders where relative file names are looked up
    preview: Preview | None = None


Ctx = Context[App]


def app(ctx: Ctx) -> App:
    return ctx.request_context.lifespan_context


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncGenerator[App, None]:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.media import MediaStore

    data_dir = Path(_env("CLAUDE_PLUGIN_DATA") or Path.home() / ".anki-mcp")
    data_dir.mkdir(parents=True, exist_ok=True)
    url = (_env("ANKI_CONNECT_URL") or "http://127.0.0.1:8765").rstrip("/")
    auto_launch = (_env("ANKI_AUTO_LAUNCH") or "true").lower() in {"1", "true", "yes", "on"}
    async with httpx.AsyncClient(timeout=30.0) as http:
        anki = AnkiClient(http, url, auto_launch)
        state = App(
            anki=anki,
            note_types=NoteTypes(anki),
            drafts=DraftStore(data_dir / "drafts"),
            journal=Journal(data_dir / "journal.jsonl"),
            media=MediaStore(data_dir / "media"),
            roots=[Path(p).expanduser() for p in (_env("ANKI_WORKSPACE"), _env("CLAUDE_PROJECT_DIR")) if p],
        )
        try:
            yield state
        finally:
            if state.preview:
                await state.preview.stop()


mcp = MCPServer("anki", version=version("anki-for-claude"), instructions=INSTRUCTIONS, lifespan=lifespan)


def tool(title: str, annotations: ToolAnnotations, meta: dict[str, Any] | None = None):
    """Register a tool that returns plain text (or text + images)."""
    return mcp.tool(title=title, annotations=annotations, meta=meta, structured_output=False)
