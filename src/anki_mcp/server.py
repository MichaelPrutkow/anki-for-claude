import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

import httpx
from mcp.server import MCPServer

from anki_mcp.anki.client import AnkiClient
from anki_mcp.anki.models import NoteTypes
from anki_mcp.config import load_config
from anki_mcp.core.drafts import DraftStore
from anki_mcp.core.journal import Journal
from anki_mcp.state import AppState
from anki_mcp.tools import collection, drafts, notes, sources, system

INSTRUCTIONS = """\
Tools for the user's real Anki collection.
To write flashcards, follow the 'cards' skill if it is available.
Workflow: overview -> draft_add -> show every card to the user -> draft_commit only after explicit approval.
Fix wrong cards with update_notes (keeps review history) instead of deleting them.
Every commit and update returns a batch id that undo can revert.
"""

logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncGenerator[AppState, None]:
    config = load_config()
    draft_store = DraftStore(config.data_dir / "drafts")
    draft_store.cleanup()
    journal = Journal(config.data_dir / "journal.jsonl")
    async with httpx.AsyncClient(timeout=30.0) as http:
        anki = AnkiClient(http, config)
        yield AppState(
            config=config,
            anki=anki,
            note_types=NoteTypes(anki),
            drafts=draft_store,
            journal=journal,
        )


mcp = MCPServer(
    "anki",
    version=version("anki-mcp-server"),
    instructions=INSTRUCTIONS,
    lifespan=lifespan,
)

for module in (collection, drafts, notes, sources, system):
    module.register(mcp)
