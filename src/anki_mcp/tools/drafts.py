import secrets
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from anki_mcp.anki.client import AnkiActionError, AnkiError
from anki_mcp.anki.models import normalize_fields
from anki_mcp.core.drafts import DraftNote, NoteIn
from anki_mcp.core.tags import BATCH_PREFIX, CREATED_TAG
from anki_mcp.core.textutil import strip_html
from anki_mcp.state import AppState, Ctx, state
from anki_mcp.tools.annotations import ADDS_NEW, DRAFT_ONLY, READ_ONLY

ASK_USER = {"anthropic/requiresUserInteraction": True}


class EditIn(BaseModel):
    n: int = Field(description="Card number in the draft")
    fields: dict[str, str] | None = Field(
        default=None, description="Only the fields that change"
    )
    tags: list[str] | None = Field(default=None, description="Replaces the card's tags")
    remove: bool = False


def _anki_note(
    note: DraftNote, allow_duplicate: bool, tags: list[str]
) -> dict[str, Any]:
    return {
        "deckName": note.deck,
        "modelName": note.note_type,
        "fields": note.fields,
        "tags": tags,
        "options": {"allowDuplicate": allow_duplicate},
    }


async def _check(
    app: AppState,
    candidates: list[tuple[str, DraftNote]],
    others: list[DraftNote],
    allow_duplicate: bool,
) -> list[str]:
    """Validate candidates against Anki. Normalizes field names in place, returns error lines."""
    errors: list[str] = []
    decks = set(await app.anki.invoke("deckNames"))

    seen: set[tuple[str, str]] = set()
    for other in others:
        nt = await app.note_types.get(other.note_type)
        seen.add(
            (other.note_type, strip_html(other.fields.get(nt.fields[0], "")).lower())
        )

    to_ask: list[tuple[str, DraftNote, str]] = []
    for label, note in candidates:
        if note.deck not in decks:
            errors.append(
                f"{label}: deck '{note.deck}' does not exist (create_deck creates it)"
            )
            continue
        try:
            nt = await app.note_types.get(note.note_type)
        except AnkiError as exc:
            errors.append(f"{label}: {exc}")
            continue
        fields, unknown = normalize_fields(nt, note.fields)
        if unknown:
            errors.append(
                f"{label}: unknown fields {unknown}, valid: {', '.join(nt.fields)}"
            )
            continue
        note.fields = fields
        key = (note.note_type, strip_html(fields.get(nt.fields[0], "")).lower())
        if key in seen and not allow_duplicate:
            errors.append(
                f"{label}: same '{nt.fields[0]}' as another card in this draft"
            )
            continue
        seen.add(key)
        to_ask.append((label, note, nt.kind))

    if to_ask:
        payload = [
            _anki_note(note, allow_duplicate, note.tags) for _, note, _ in to_ask
        ]
        results = await app.anki.invoke("canAddNotesWithErrorDetail", notes=payload)
        for (label, _, kind), result in zip(to_ask, results, strict=True):
            if result["canAdd"]:
                continue
            message = result["error"]
            if kind == "cloze" and "unknown reason" in message:
                message += " (a Cloze note needs at least one {{c1::...}})"
            errors.append(f"{label}: {message}")
    return errors


async def draft_add(
    ctx: Ctx,
    notes: Annotated[list[NoteIn], Field(min_length=1, max_length=50)],
    draft_id: str | None = None,
    deck: str | None = None,
    note_type: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    allow_duplicate: bool = False,
) -> str:
    """Validate cards and add them to a draft. Nothing is written to Anki.

    Without draft_id a new draft is created; then deck and note_type are required.
    Each card may override note_type and deck. If any card fails, none are added
    and every problem is listed. Drafts survive restarts.
    """
    app = state(ctx)
    if draft_id:
        draft = app.drafts.load(draft_id)
        deck, note_type, allow_duplicate = (
            draft.deck,
            draft.note_type,
            draft.allow_duplicate,
        )
        others = draft.notes
    elif not deck or not note_type:
        raise ToolError("A new draft needs 'deck' and 'note_type'.")
    else:
        others = []

    candidates = [
        (
            f"[{i}]",
            DraftNote(
                deck=n.deck or deck,
                note_type=n.note_type or note_type,
                fields=n.fields,
                tags=n.tags,
            ),
        )
        for i, n in enumerate(notes)
    ]
    errors = await _check(app, candidates, others, allow_duplicate)
    if errors:
        raise ToolError("Nothing added:\n" + "\n".join(errors))

    if not draft_id:
        draft_id = app.drafts.create(
            deck=deck,
            note_type=note_type,
            tags=tags or [],
            title=title,
            allow_duplicate=allow_duplicate,
        ).id
    async with app.drafts.edit(draft_id) as draft:
        first = draft.next_n
        for _, note in candidates:
            note.n = draft.next_n
            draft.next_n += 1
            draft.notes.append(note)
        total = len(draft.notes)
    return (
        f"Draft {draft_id}: +{len(candidates)} cards (#{first}-#{first + len(candidates) - 1}), "
        f"{total} in total. Show the cards to the user before calling draft_commit."
    )


async def draft_edit(
    ctx: Ctx,
    draft_id: str,
    edits: Annotated[list[EditIn], Field(min_length=1)],
) -> str:
    """Change or remove single cards of a draft by number. Fields are merged, so send only what changes."""
    app = state(ctx)
    async with app.drafts.edit(draft_id) as draft:
        by_n = {note.n: note for note in draft.notes}
        missing = [e.n for e in edits if e.n not in by_n]
        if missing:
            raise ToolError(f"Draft {draft_id} has no cards {missing}.")

        removed = {e.n for e in edits if e.remove}
        changed: list[tuple[str, DraftNote]] = []
        for e in edits:
            if e.remove:
                continue
            note = by_n[e.n].model_copy(deep=True)
            if e.fields:
                note.fields = {**note.fields, **e.fields}
            if e.tags is not None:
                note.tags = e.tags
            note.error = None
            changed.append((f"#{e.n}", note))

        touched = removed | {note.n for _, note in changed}
        others = [note for note in draft.notes if note.n not in touched]
        errors = await _check(app, changed, others, draft.allow_duplicate)
        if errors:
            raise ToolError("Nothing changed:\n" + "\n".join(errors))

        replaced = {note.n: note for _, note in changed}
        draft.notes = [replaced.get(n.n, n) for n in draft.notes if n.n not in removed]
        left = len(draft.notes)
    return f"Draft {draft_id}: {len(changed)} changed, {len(removed)} removed, {left} cards left."


async def draft_show(ctx: Ctx, draft_id: str | None = None) -> str:
    """Without draft_id: list open drafts. With draft_id: every card of the draft with its full fields."""
    app = state(ctx)
    if draft_id is None:
        drafts = app.drafts.all()
        if not drafts:
            return "No open drafts."
        return "\n".join(
            f"{d.id} · {d.title or 'untitled'} · {d.deck} · {len(d.notes)} cards · {d.updated:%Y-%m-%d %H:%M} UTC"
            for d in drafts
        )

    draft = app.drafts.load(draft_id)
    lines = [f"{draft.id} · {draft.title or 'untitled'} · {len(draft.notes)} cards"]
    for note in draft.notes:
        head = f"#{note.n} [{note.note_type} -> {note.deck}]"
        if note.error:
            head += f" FAILED: {note.error}"
        lines.append(head)
        lines.extend(
            f"  {name}: {value}" for name, value in note.fields.items() if value
        )
    return "\n".join(lines)


async def draft_commit(
    ctx: Ctx,
    draft_id: str,
    only: Annotated[
        list[int] | None, Field(description="Card numbers; default: all")
    ] = None,
) -> str:
    """Write a draft to Anki. Only after the user has seen the cards and approved them."""
    app = state(ctx)
    batch_id = secrets.token_hex(4)
    batch_tags = [CREATED_TAG, f"{BATCH_PREFIX}{batch_id}"]

    async with app.drafts.edit(draft_id) as draft:
        selected = [n for n in draft.notes if only is None or n.n in only]
        if not selected:
            raise ToolError("Nothing to commit.")
        calls = [
            (
                "addNote",
                {
                    "note": _anki_note(
                        n, draft.allow_duplicate, [*draft.tags, *n.tags, *batch_tags]
                    )
                },
            )
            for n in selected
        ]
        results = await app.anki.multi(calls, timeout=120)

        created: list[int] = []
        succeeded: set[int] = set()
        for note, result in zip(selected, results, strict=True):
            if isinstance(result, int):
                created.append(result)
                succeeded.add(note.n)
                note.error = None
            else:
                note.error = (
                    result.message
                    if isinstance(result, AnkiActionError)
                    else str(result)
                )
        draft.notes = [n for n in draft.notes if n.n not in succeeded]
        failed = (
            list(draft.notes)
            if only is None
            else [n for n in draft.notes if n.n in only]
        )
        left = len(draft.notes)

    if created:
        app.journal.append(
            {
                "batch_id": batch_id,
                "kind": "commit",
                "draft_id": draft_id,
                "created": created,
            }
        )
    if left == 0:
        app.drafts.delete(draft_id)

    lines = []
    if created:
        lines.append(
            f"Batch {batch_id}: {len(created)} cards added. Undo with undo('{batch_id}')."
        )
    if failed:
        lines.append(f"{len(failed)} failed, still in draft {draft_id}:")
        lines.extend(f"#{n.n}: {n.error}" for n in failed)
    return "\n".join(lines) or "Nothing added."


def register(mcp: MCPServer) -> None:
    mcp.add_tool(
        draft_add,
        title="Add cards to draft",
        annotations=DRAFT_ONLY,
        structured_output=False,
    )
    mcp.add_tool(
        draft_edit,
        title="Edit draft cards",
        annotations=DRAFT_ONLY,
        structured_output=False,
    )
    mcp.add_tool(
        draft_show, title="Show drafts", annotations=READ_ONLY, structured_output=False
    )
    mcp.add_tool(
        draft_commit,
        title="Commit draft to Anki",
        annotations=ADDS_NEW,
        meta=ASK_USER,
        structured_output=False,
    )
