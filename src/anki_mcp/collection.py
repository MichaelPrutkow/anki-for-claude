import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from anki_mcp.anki import AnkiError, AnkiTimeout
from anki_mcp.images import dot_command, local_images, replace_images, upload_images
from anki_mcp.server import BATCH_PREFIX, CREATED_TAG, OVERWRITES, READ_ONLY, SYNC, Ctx, app, tool
from anki_mcp.text import strip_html, truncate


class Journal:
    """Append-only log of commits, updates and undos, so batches can be reverted."""

    def __init__(self, path: Path):
        self._path = path

    def append(self, entry: dict[str, Any]) -> None:
        line = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


@tool("Decks and note types", READ_ONLY)
async def overview(
    ctx: Ctx, deck: Annotated[str | None, Field(description="Only this deck and its subdecks")] = None
) -> str:
    """The decks with their card counts and the note types with their exact field names. Call it before drafting."""
    a = app(ctx)
    ids: dict[str, int] = await a.anki.invoke("deckNamesAndIds")
    if deck:
        ids = {n: i for n, i in ids.items() if n == deck or n.startswith(deck + "::")}
        if not ids:
            raise ToolError(f"There is no deck '{deck}'.")
    # getDeckStats is keyed by deck id and counts only the deck itself, without its subdecks.
    stats: dict[str, Any] = await a.anki.invoke("getDeckStats", decks=list(ids))
    by_name = {name: stats.get(str(deck_id), {}) for name, deck_id in ids.items()}

    lines = ["Decks (full name: cards including subdecks, due today, new today):"]
    empty: list[str] = []
    for name in sorted(by_name, key=str.lower):
        total = sum(s.get("total_in_deck", 0) for n, s in by_name.items() if n == name or n.startswith(name + "::"))
        if total == 0:
            if name != "Default":
                empty.append(name)
            continue
        s = by_name[name]
        due = s.get("learn_count", 0) + s.get("review_count", 0)
        lines.append(f"{name}: {total} cards, {due} due, {s.get('new_count', 0)} new")
    if empty:
        lines.append("Empty decks: " + ", ".join(empty))

    lines += ["", "Note types (name [kind]: fields in order):"]
    for nt in sorted(await a.note_types.all(), key=lambda n: n.name.lower()):
        lines.append(f"{nt.name} [{nt.label}]: " + " | ".join(nt.fields))
    if not dot_command():
        lines += ["", "Graphviz is not installed, so render_graph does not work (macOS: brew install graphviz)."]
    return "\n".join(lines)


@tool("Search notes", READ_ONLY)
async def search_notes(
    ctx: Ctx,
    query: Annotated[str, Field(description="Anki search, e.g. 'deck:GAD tag:heap' or 'nid:1234'")],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    fields: Annotated[list[str] | None, Field(description="Only show these fields")] = None,
    max_chars: Annotated[int, Field(ge=20, le=2000, description="Characters shown per field")] = 120,
) -> str:
    """Find notes with Anki's search syntax. One line per note, newest first."""
    a = app(ctx)
    ids = sorted(await a.anki.invoke("findNotes", query=query), reverse=True)
    if not ids:
        return f"No notes match '{query}'. If you expected hits, check the search syntax."

    shown = ids[:limit]
    wanted = {f.lower() for f in fields} if fields else None
    lines = [f"{len(ids)} notes match '{query}', showing the newest {len(shown)}:"]
    for note in await a.anki.invoke("notesInfo", notes=shown):
        if not note:
            continue
        parts = []
        for name, field in sorted(note["fields"].items(), key=lambda kv: kv[1]["order"]):
            text = truncate(strip_html(field["value"]), max_chars)
            if text and (not wanted or name.lower() in wanted):
                parts.append(f"{name}: {text}")
        line = f"{note['noteId']} [{note['modelName']}] " + " | ".join(parts)
        tags = [t for t in note["tags"] if not t.startswith(BATCH_PREFIX)]
        if tags:
            line += " | tags: " + " ".join(tags)
        lines.append(line)
    return "\n".join(lines)


class UpdateIn(BaseModel):
    note_id: int
    fields: dict[str, str] = Field(description="Only the fields that change, with their full new content")


@tool("Update notes", OVERWRITES)
async def update_notes(
    ctx: Ctx,
    updates: Annotated[list[UpdateIn], Field(min_length=1, max_length=50)],
    force: Annotated[bool, Field(description="Needed for notes the user wrote. Ask the user first")] = False,
) -> str:
    """Change fields of existing notes. Keeps the review history, so prefer it over deleting and re-adding.

    Notes not created by this plugin need force=true: ask the user first. Returns a batch id for undo.
    """
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=[u.note_id for u in updates])

    errors: list[str] = []
    planned: list[tuple[int, dict[str, str], dict[str, str]]] = []
    for update, info in zip(updates, infos, strict=True):
        if not info:
            errors.append(f"{update.note_id}: there is no such note")
            continue
        if CREATED_TAG not in info["tags"] and not force:
            errors.append(f"{update.note_id}: the user wrote this note. Ask them, then call again with force=true")
            continue
        nt = await a.note_types.get(info["modelName"])
        fields, unknown = nt.normalize(update.fields)
        if unknown:
            errors.append(f"{update.note_id}: unknown fields {unknown}. {nt.name} has: {', '.join(nt.fields)}")
            continue
        before = {name: info["fields"][name]["value"] for name in fields}
        planned.append((update.note_id, fields, before))
    if errors:
        raise ToolError("Nothing was changed:\n" + "\n".join(errors))

    # Images new to a note come from the images folder; images it already had are in Anki already.
    new_images = sorted(
        {
            name
            for _, fields, before in planned
            for value in fields.values()
            for name in local_images(value)
            if a.images.has(name) and not any(name in local_images(old) for old in before.values())
        }
    )
    stored = await upload_images(a, new_images)
    if len(stored) < len(new_images):
        raise ToolError("Nothing was changed: could not copy " + ", ".join(sorted(set(new_images) - set(stored))))
    planned = [(nid, {k: replace_images(v, stored) for k, v in f.items()}, before) for nid, f, before in planned]

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
            problems.append(f"{nid}: not saved. Is the note open in Anki's browser or editor?")

    lines = []
    if applied:
        batch_id = uuid4().hex[:8]
        a.journal.append({"batch_id": batch_id, "kind": "update", "updated": applied})
        noun = "note" if len(applied) == 1 else "notes"
        lines.append(f'Updated {len(applied)} {noun}. Batch id {batch_id}: undo("{batch_id}") restores them.')
    if problems:
        lines += ["Not updated:", *problems]
    return "\n".join(lines)


@tool("Delete notes", OVERWRITES)
async def delete_notes(
    ctx: Ctx,
    note_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
) -> str:
    """Delete notes created by this plugin, with their review history. This cannot be undone.

    Only for cards that should not exist at all; fix wrong cards with update_notes instead.
    """
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=note_ids)
    missing = [nid for nid, info in zip(note_ids, infos, strict=True) if not info]
    foreign = [nid for nid, info in zip(note_ids, infos, strict=True) if info and CREATED_TAG not in info["tags"]]
    if missing or foreign:
        lines = ["Nothing was deleted."]
        if missing:
            lines.append(f"No such notes: {missing}")
        if foreign:
            lines.append(f"Written by the user, so this plugin does not delete them: {foreign}")
        raise ToolError("\n".join(lines))
    await a.anki.invoke("deleteNotes", notes=note_ids)
    return f"Deleted {len(note_ids)} {'note' if len(note_ids) == 1 else 'notes'}."


@tool("Undo a batch", OVERWRITES)
async def undo(ctx: Ctx, batch_id: str) -> str:
    """Revert a draft_commit or update_notes by its batch id: added notes are deleted, changed fields restored.

    A note the user edited since is left alone.
    """
    a = app(ctx)
    entries = a.journal.entries()
    if any(e.get("undo_of") == batch_id for e in entries):
        raise ToolError(f"Batch {batch_id} was already undone.")
    entry = next((e for e in reversed(entries) if e.get("batch_id") == batch_id and e["kind"] != "undo"), None)

    if entry is None or entry["kind"] == "commit":
        ids = await a.anki.invoke("findNotes", query=f"tag:{BATCH_PREFIX}{batch_id}")
        if not ids and entry is None:
            raise ToolError(f"There is no batch '{batch_id}'.")
        if ids:
            await a.anki.invoke("deleteNotes", notes=ids)
        message = f"Undid batch {batch_id}: deleted {len(ids)} {'note' if len(ids) == 1 else 'notes'}."
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
        message = f"Undid batch {batch_id}: restored {len(restore)} {'note' if len(restore) == 1 else 'notes'}."
        if conflicts:
            message += f" Left alone because they were edited since: {conflicts}."

    a.journal.append({"batch_id": uuid4().hex[:8], "kind": "undo", "undo_of": batch_id})
    return message


@tool("Sync with AnkiWeb", SYNC)
async def sync(ctx: Ctx) -> str:
    """Sync the collection with AnkiWeb, so new cards reach the user's phone and reviews from the phone count."""
    try:
        await app(ctx).anki.invoke("sync", timeout=50)
    except AnkiTimeout:
        return "The sync is taking longer than usual and continues in Anki."
    return "Synced with AnkiWeb."
