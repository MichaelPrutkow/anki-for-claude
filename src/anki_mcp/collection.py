import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from anki_mcp.anki import AnkiError
from anki_mcp.render import strip_html, truncate
from anki_mcp.server import (
    ASK_USER,
    BATCH_PREFIX,
    CREATED_TAG,
    OVERWRITES,
    READ_ONLY,
    SYNC,
    Ctx,
    app,
    tool,
)


class Journal:
    """Append-only log of commits, updates and undos, so batches can be reverted."""

    def __init__(self, path: Path):
        self._path = path

    def append(self, entry: dict[str, Any]) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


@tool("Decks and note types", READ_ONLY)
async def overview(ctx: Ctx, deck: str | None = None) -> str:
    """Decks with card counts and note types with their exact field names. Call this before drafting cards."""
    a = app(ctx)
    ids: dict[str, int] = await a.anki.invoke("deckNamesAndIds")
    if deck:
        ids = {n: i for n, i in ids.items() if n == deck or n.startswith(deck + "::")}
        if not ids:
            raise ToolError(f"The deck '{deck}' does not exist.")
    # getDeckStats is keyed by deck id and only knows the last part of the name.
    stats: dict[str, Any] = await a.anki.invoke("getDeckStats", decks=list(ids))
    by_name = {name: stats.get(str(deck_id), {}) for name, deck_id in ids.items()}

    lines = ["Decks, full names to use in draft_add (cards · due · new today):"]
    empty: list[str] = []
    for name in sorted(by_name, key=str.lower):
        total = sum(s.get("total_in_deck", 0) for n, s in by_name.items() if n == name or n.startswith(name + "::"))
        if total == 0:
            if name != "Default":
                empty.append(name)
            continue
        s = by_name[name]
        due = s.get("learn_count", 0) + s.get("review_count", 0)
        lines.append(f"{name}  {total} · {due} · {s.get('new_count', 0)}")
    if empty:
        lines.append("Empty decks: " + ", ".join(empty))

    lines.append("Note types:")
    for nt in sorted(await a.note_types.all(), key=lambda n: n.name):
        lines.append(f"{nt.name} [{nt.kind}] " + " | ".join(nt.fields))
    return "\n".join(lines)


@tool("Search notes", READ_ONLY)
async def search_notes(
    ctx: Ctx,
    query: Annotated[str, Field(description="Anki search query, e.g. 'deck:GAD tag:heap'")],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    fields: list[str] | None = None,
    max_chars: Annotated[int, Field(ge=20, le=1000)] = 120,
) -> str:
    """Find notes with Anki search syntax. One compact line per note, newest first."""
    a = app(ctx)
    ids = sorted(await a.anki.invoke("findNotes", query=query), reverse=True)
    if not ids:
        return f"No notes found for '{query}'. Check the search syntax."

    shown = ids[:limit]
    wanted = {f.lower() for f in fields} if fields else None
    lines = [f"{len(ids)} hits for '{query}', showing {len(shown)}"]
    for note in await a.anki.invoke("notesInfo", notes=shown):
        if not note:
            continue
        parts = []
        for name, field in sorted(note["fields"].items(), key=lambda kv: kv[1]["order"]):
            text = truncate(strip_html(field["value"]), max_chars)
            if text and (not wanted or name.lower() in wanted):
                parts.append(f"{name}: {text}")
        line = f"{note['noteId']} - {note['modelName']} - " + " | ".join(parts)
        tags = [t for t in note["tags"] if not t.startswith(BATCH_PREFIX)]
        if tags:
            line += " - tags: " + " ".join(tags)
        lines.append(line)
    return "\n".join(lines)


class UpdateIn(BaseModel):
    note_id: int
    fields: dict[str, str] = Field(description="Only the fields that change")


@tool("Update notes", OVERWRITES)
async def update_notes(
    ctx: Ctx,
    updates: Annotated[list[UpdateIn], Field(min_length=1, max_length=50)],
    force: bool = False,
) -> str:
    """Change fields of existing notes. Keeps the review history, so prefer this over deleting.

    Notes not created by this plugin need force=True: ask the user first.
    Returns a batch id for undo.
    """
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=[u.note_id for u in updates])

    errors: list[str] = []
    planned: list[tuple[int, dict[str, str], dict[str, str]]] = []
    for update, info in zip(updates, infos, strict=True):
        if not info:
            errors.append(f"{update.note_id}: note does not exist")
            continue
        if CREATED_TAG not in info["tags"] and not force:
            errors.append(f"{update.note_id}: not created by this plugin. Ask the user, then retry with force=True")
            continue
        nt = await a.note_types.get(info["modelName"])
        fields, unknown = nt.normalize(update.fields)
        if unknown:
            errors.append(f"{update.note_id}: unknown fields {unknown}, valid: {', '.join(nt.fields)}")
            continue
        before = {name: info["fields"][name]["value"] for name in fields}
        planned.append((update.note_id, fields, before))
    if errors:
        raise ToolError("Nothing changed:\n" + "\n".join(errors))

    results = await a.anki.multi(
        [("updateNoteFields", {"note": {"id": nid, "fields": fields}}) for nid, fields, _ in planned]
    )
    after = await a.anki.invoke("notesInfo", notes=[nid for nid, _, _ in planned])

    applied: list[dict[str, Any]] = []
    problems: list[str] = []
    for (nid, fields, before), result, info in zip(planned, results, after, strict=True):
        if isinstance(result, AnkiError):
            problems.append(f"{nid}: {result}")
        elif all(info["fields"][name]["value"] == value for name, value in fields.items()):
            applied.append({"note_id": nid, "before": before, "after": fields, "mod_after": info["mod"]})
        else:
            problems.append(f"{nid}: change not saved. Is the note open in Anki's browser?")

    lines = []
    if applied:
        batch_id = secrets.token_hex(4)
        a.journal.append({"batch_id": batch_id, "kind": "update", "updated": applied})
        lines.append(f"Batch {batch_id}: {len(applied)} notes updated. Undo with undo('{batch_id}').")
    return "\n".join(lines + problems)


@tool("Delete notes", OVERWRITES, meta=ASK_USER)
async def delete_notes(
    ctx: Ctx,
    note_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
) -> str:
    """Delete notes created by this plugin. Loses the review history and cannot be undone; prefer update_notes for wrong cards."""
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=note_ids)
    missing = [nid for nid, info in zip(note_ids, infos, strict=True) if not info]
    foreign = [nid for nid, info in zip(note_ids, infos, strict=True) if info and CREATED_TAG not in info["tags"]]
    if missing or foreign:
        raise ToolError(f"Nothing deleted. Missing: {missing or '-'}; not created by this plugin: {foreign or '-'}")
    await a.anki.invoke("deleteNotes", notes=note_ids)
    return f"{len(note_ids)} notes deleted."


@tool("Undo batch", OVERWRITES)
async def undo(ctx: Ctx, batch_id: str) -> str:
    """Revert a commit or update batch. Added cards are deleted, changed fields restored unless edited since."""
    a = app(ctx)
    entries = a.journal.entries()
    if any(e.get("undo_of") == batch_id for e in entries):
        raise ToolError(f"Batch {batch_id} was already undone.")
    tag = f"{BATCH_PREFIX}{batch_id}"
    entry = next((e for e in reversed(entries) if e.get("batch_id") == batch_id and e["kind"] != "undo"), None)

    if entry is None or entry["kind"] == "commit":
        ids = await a.anki.invoke("findNotes", query=f"tag:{tag}")
        if not ids and entry is None:
            raise ToolError(f"Unknown batch '{batch_id}'.")
        if ids:
            await a.anki.invoke("deleteNotes", notes=ids)
        message = f"Batch {batch_id}: {len(ids)} cards deleted."
    else:
        updates = entry["updated"]
        infos = await a.anki.invoke("notesInfo", notes=[u["note_id"] for u in updates])
        restore, conflicts = [], []
        for update, info in zip(updates, infos, strict=True):
            if not info:
                continue
            if info["mod"] != update["mod_after"]:
                conflicts.append(update["note_id"])
            else:
                restore.append(("updateNoteFields", {"note": {"id": update["note_id"], "fields": update["before"]}}))
        if restore:
            await a.anki.multi(restore)
        message = f"Batch {batch_id}: {len(restore)} notes restored."
        if conflicts:
            message += f" Not touched because edited since: {conflicts}."

    a.journal.append({"batch_id": secrets.token_hex(4), "kind": "undo", "undo_of": batch_id})
    return message


@tool("Sync with AnkiWeb", SYNC)
async def sync(ctx: Ctx) -> str:
    """Sync the collection with AnkiWeb so new cards reach the user's phone."""
    await app(ctx).anki.invoke("sync", timeout=120)
    return "Sync started."
