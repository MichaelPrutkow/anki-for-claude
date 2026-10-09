from dataclasses import dataclass

from mcp.server.mcpserver import Context

from anki_mcp.anki.client import AnkiClient
from anki_mcp.anki.models import NoteTypes
from anki_mcp.config import Config
from anki_mcp.core.drafts import DraftStore
from anki_mcp.core.journal import Journal


@dataclass
class AppState:
    config: Config
    anki: AnkiClient
    note_types: NoteTypes
    drafts: DraftStore
    journal: Journal


Ctx = Context[AppState]


def state(ctx: Ctx) -> AppState:
    return ctx.request_context.lifespan_context
