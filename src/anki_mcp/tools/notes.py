import secrets
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from anki_mcp.anki.client import AnkiActionError
from anki_mcp.anki.models import normalize_fields
from anki_mcp.core.tags import BATCH_PREFIX, CREATED_TAG
from anki_mcp.state import Ctx, state
from anki_mcp.tools.annotations import OVERWRITES
from anki_mcp.tools.drafts import ASK_USER


class UpdateIn(BaseModel):
    note_id: int
    fields: dict[str, str] = Field(description="Only the fields that change")


async def update_notes(
    ctx: Ctx,
    updates: Annotated[list[UpdateIn], Field(min_length=1, max_length=50)],
    force: bool = False,
) -> str:
    """Change fields of existing notes. Keeps the review history, so prefer this over deleting.

    Notes not created by this plugin need force=True: ask the user first.
    Returns a batch id for undo.
    """
    app = state(ctx)
    infos = await app.anki.invoke("notesInfo", notes=[u.note_id for u in updates])

    errors: list[str] = []
    planned: list[tuple[int, dict[str, str], dict[str, str]]] = []
    for update, info in zip(updates, infos, strict=True):
        if not info:
            errors.append(f"{update.note_id}: note does not exist")
            continue
        if CREATED_TAG not in info["tags"] and not force:
            errors.append(
                f"{update.note_id}: not created by this plugin. Ask the user, then retry with force=True"
            )
            continue
        nt = await app.note_types.get(info["modelName"])
        fields, unknown = normalize_fields(nt, update.fields)
        if unknown:
            errors.append(
                f"{update.note_id}: unknown fields {unknown}, valid: {', '.join(nt.fields)}"
            )
            continue
        before = {name: info["fields"][name]["value"] for name in fields}
        planned.append((update.note_id, fields, before))
    if errors:
        raise ToolError("Nothing changed:\n" + "\n".join(errors))

    results = await app.anki.multi(
        [
            ("updateNoteFields", {"note": {"id": nid, "fields": fields}})
            for nid, fields, _ in planned
        ]
    )
    after = await app.anki.invoke("notesInfo", notes=[nid for nid, _, _ in planned])

    applied: list[dict[str, Any]] = []
    problems: list[str] = []
    for (nid, fields, before), result, info in zip(
        planned, results, after, strict=True
    ):
        if isinstance(result, AnkiActionError):
            problems.append(f"{nid}: {result.message}")
        elif all(
            info["fields"][name]["value"] == value for name, value in fields.items()
        ):
            applied.append(
                {
                    "note_id": nid,
                    "before": before,
                    "after": fields,
                    "mod_after": info["mod"],
                }
            )
        else:
            problems.append(
                f"{nid}: change not saved. Is the note open in Anki's browser?"
            )

    lines = []
    if applied:
        batch_id = secrets.token_hex(4)
        app.journal.append({"batch_id": batch_id, "kind": "update", "updated": applied})
        lines.append(
            f"Batch {batch_id}: {len(applied)} notes updated. Undo with undo('{batch_id}')."
        )
    lines.extend(problems)
    return "\n".join(lines)


async def delete_notes(
    ctx: Ctx,
    note_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
) -> str:
    """Delete notes created by this plugin. Deleting loses the review history and cannot be undone; prefer update_notes for wrong cards."""
    app = state(ctx)
    infos = await app.anki.invoke("notesInfo", notes=note_ids)
    missing = [nid for nid, info in zip(note_ids, infos, strict=True) if not info]
    foreign = [
        nid
        for nid, info in zip(note_ids, infos, strict=True)
        if info and CREATED_TAG not in info["tags"]
    ]
    problems = []
    if missing:
        problems.append(f"missing: {missing}")
    if foreign:
        problems.append(f"not created by this plugin: {foreign}")
    if problems:
        raise ToolError("Nothing deleted, " + "; ".join(problems))
    await app.anki.invoke("deleteNotes", notes=note_ids)
    return f"{len(note_ids)} notes deleted."


async def undo(ctx: Ctx, batch_id: str) -> str:
    """Revert a commit or update batch. Added cards are deleted, changed fields restored unless edited since."""
    app = state(ctx)
    if app.journal.is_undone(batch_id):
        raise ToolError(f"Batch {batch_id} was already undone.")
    tag = f"{BATCH_PREFIX}{batch_id}"
    entry = app.journal.find(batch_id)

    if entry is None:
        ids = await app.anki.invoke("findNotes", query=f"tag:{tag}")
        if not ids:
            raise ToolError(f"Unknown batch '{batch_id}'.")
        await app.anki.invoke("deleteNotes", notes=ids)
        message = f"Batch {batch_id}: {len(ids)} cards deleted."
    elif entry["kind"] == "commit":
        infos = await app.anki.invoke("notesInfo", notes=entry["created"])
        ids = [info["noteId"] for info in infos if info and tag in info["tags"]]
        if ids:
            await app.anki.invoke("deleteNotes", notes=ids)
        message = f"Batch {batch_id}: {len(ids)} cards deleted."
    else:
        updates = entry["updated"]
        infos = await app.anki.invoke(
            "notesInfo", notes=[u["note_id"] for u in updates]
        )
        restore = []
        conflicts = []
        for update, info in zip(updates, infos, strict=True):
            if not info:
                continue
            if info["mod"] != update["mod_after"]:
                conflicts.append(update["note_id"])
                continue
            restore.append(
                (
                    "updateNoteFields",
                    {"note": {"id": update["note_id"], "fields": update["before"]}},
                )
            )
        if restore:
            await app.anki.multi(restore)
        message = f"Batch {batch_id}: {len(restore)} notes restored."
        if conflicts:
            message += f" Not touched because edited since: {conflicts}."

    app.journal.append(
        {"batch_id": secrets.token_hex(4), "kind": "undo", "undo_of": batch_id}
    )
    return message


def register(mcp: MCPServer) -> None:
    mcp.add_tool(
        update_notes,
        title="Update notes",
        annotations=OVERWRITES,
        structured_output=False,
    )
    mcp.add_tool(
        delete_notes,
        title="Delete notes",
        annotations=OVERWRITES,
        meta=ASK_USER,
        structured_output=False,
    )
    mcp.add_tool(
        undo, title="Undo batch", annotations=OVERWRITES, structured_output=False
    )
