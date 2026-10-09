from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from anki_mcp.core.textutil import strip_html, truncate
from anki_mcp.state import Ctx, state
from anki_mcp.tools.annotations import ADDS_IF_MISSING, READ_ONLY


async def overview(ctx: Ctx, deck: str | None = None) -> str:
    """List decks with card counts and note types with their exact field names.
    Cal this before drafting cards."""
    app = state(ctx)
    decks: list[str] = await app.anki.invoke("deckNames")
    if deck:
        decks = [d for d in decks if d == deck or d.startswith(deck + "::")]
        if not decks:
            raise ToolError(f"The deck '{deck}' does not exist.")
    stats: dict[str, Any] = await app.anki.invoke("getDeckStats", decks=decks)
    note_types = await app.note_types.all()

    lines = ["Decks (new today/due/total):"]
    for s in sorted(stats.values(), key=lambda s: s["name"]):
        due = s["learn_count"] + s["review_count"]
        lines.append(f"{s['name']} {s['new_count']}/{due}/{s['total_in_deck']}")

    lines.append("Note types:")
    for nt in sorted(note_types, key=lambda n: n.name):
        lines.append(f"{nt.name} [{nt.kind}] " + " | ".join(nt.fields))

    return "\n".join(lines)


async def search_notes(
    ctx: Ctx,
    query: Annotated[
        str, Field(description="Anki search query, e.g. 'deck:GAD tag:heap'")
    ],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    fields: list[str] | None = None,
    max_chars: Annotated[int, Field(ge=20, le=1000)] = 120,
) -> str:
    """Find notes with Anki search syntax. One compact line per note, newest first."""

    app = state(ctx)
    ids = sorted(await app.anki.invoke("findNotes", query=query), reverse=True)

    if not ids:
        return f"No notes found with query: '{query}'. Check if the search syntax is correct!"

    shown = ids[:limit]
    notes = await app.anki.invoke("notesInfo", notes=shown)
    wanted = {f.lower() for f in fields} if fields else None

    lines = [f"{len(ids)} Hits for '{query}', showing {len(shown)}"]
    for note in notes:
        if not note:
            continue
        parts = []
        for name, field in sorted(
            note["fields"].items(), key=lambda kv: kv[1]["order"]
        ):
            if wanted and name.lower() not in wanted:
                continue
            text = truncate(strip_html(field["value"]), max_chars)
            if text:
                parts.append(f"{name}: {text}")

        line = f"{note['noteId']} - {note['modelName']} - " + " | ".join(parts)
        tags = [t for t in note["tags"] if not t.startswith("mcp::batch::")]
        if tags:
            line += " - tags: " + " ".join(tags)
        lines.append(line)
    return "\n".join(lines)


async def create_deck(
    ctx: Ctx,
    name: Annotated[str, Field(description="Deck name, '::' creates subdecks")],
) -> str:
    """Create an empty deck. Does nothing if it already exists."""
    deck_id = await state(ctx).anki.invoke("createDeck", deck=name)
    return f"Deck '{name}' is ready (ID {deck_id})."


def register(mcp: MCPServer) -> None:
    mcp.add_tool(
        overview,
        title="Decks and note types",
        annotations=READ_ONLY,
        structured_output=False,
    )
    mcp.add_tool(
        search_notes,
        title="Search notes",
        annotations=READ_ONLY,
        structured_output=False,
    )
    mcp.add_tool(
        create_deck,
        title="Create deck",
        annotations=ADDS_IF_MISSING,
        structured_output=False,
    )
