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
from mcp.types import Tool, ToolAnnotations

if TYPE_CHECKING:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.images import ImageStore

INSTRUCTIONS = """\
Tools for the user's own Anki collection. They run on the user's computer and can only open files there.
New cards (follow the 'create-cards' skill): overview -> draft_add -> show the returned cards to the user ->
draft_edit until they approve -> draft_commit. Nothing reaches Anki before draft_commit.
Existing cards: search_notes, update_notes (keeps the review history), stats for the cards the user struggles with.
Every change to the collection returns a batch id that undo reverts.
"""

CREATED_TAG = "mcp::created"
BATCH_PREFIX = "mcp::batch::"

logging.getLogger("httpx").setLevel(logging.WARNING)


def _annotations(read_only: bool, destructive: bool, idempotent: bool, web: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=web,
    )


READ_ONLY = _annotations(True, False, True)
DRAFT = _annotations(True, False, False)  # changes drafts and images, never the collection
ADDS = _annotations(False, False, False)
OVERWRITES = _annotations(False, True, True)
WEB_READ = _annotations(True, False, True, web=True)
SYNC = _annotations(False, False, True, web=True)


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


@dataclass
class App:
    anki: AnkiClient
    note_types: NoteTypes
    drafts: DraftStore
    journal: Journal
    images: ImageStore
    roots: list[Path]  # folders where relative file names are looked up


Ctx = Context[App]


def app(ctx: Ctx) -> App:
    return ctx.request_context.lifespan_context


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncGenerator[App, None]:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.images import ImageStore

    data_dir = Path(_env("CLAUDE_PLUGIN_DATA") or Path.home() / ".anki-mcp")
    data_dir.mkdir(parents=True, exist_ok=True)
    url = (_env("ANKI_CONNECT_URL") or "http://127.0.0.1:8765").rstrip("/")
    auto_launch = (_env("ANKI_AUTO_LAUNCH") or "true").lower() in {"1", "true", "yes", "on"}
    async with httpx.AsyncClient(timeout=30.0) as http:
        anki = AnkiClient(http, url, auto_launch)
        yield App(
            anki=anki,
            note_types=NoteTypes(anki),
            drafts=DraftStore(data_dir / "drafts"),
            journal=Journal(data_dir / "journal.jsonl"),
            images=ImageStore(Path.home() / "Pictures" / "Anki for Claude"),
            roots=[Path(p).expanduser() for p in (_env("ANKI_WORKSPACE"), _env("CLAUDE_PROJECT_DIR")) if p],
        )


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace every $ref with the definition it points to and drop $defs."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {**target, **{k: resolve(v) for k, v in node.items() if k != "$ref"}}
        return {k: resolve(v) for k, v in node.items() if k != "$defs"}

    return resolve(schema)


class AnkiServer(MCPServer):
    async def list_tools(self) -> list[Tool]:
        # The Claude desktop app passes only "properties" and "required" of a tool schema on to chats,
        # so a $ref into "$defs" would point nowhere there.
        return [t.model_copy(update={"input_schema": inline_refs(t.input_schema)}) for t in await super().list_tools()]


mcp = AnkiServer("anki", version=version("anki-for-claude"), instructions=INSTRUCTIONS, lifespan=lifespan)


def tool(title: str, annotations: ToolAnnotations):
    """Register a tool that returns plain text (or text and images)."""
    return mcp.tool(title=title, annotations=annotations, structured_output=False)
