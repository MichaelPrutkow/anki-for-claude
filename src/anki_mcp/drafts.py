"""Drafts: cards that are validated but not yet in Anki, the review loop and the commit."""

import asyncio
import os
import re
import secrets
import webbrowser
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image as McpImage
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image
from pydantic import BaseModel, Field

from anki_mcp.anki import AnkiError
from anki_mcp.media import MEDIA_REF, downscale, png_bytes
from anki_mcp.occlusion import Mask, build_field, draw_masks, find_label
from anki_mcp.preview import Preview
from anki_mcp.render import strip_html
from anki_mcp.server import ADDS_NEW, BATCH_PREFIX, CREATED_TAG, DRAFT_ONLY, App, Ctx, app, tool

REVIEW_WAIT_SECONDS = 600
KEEPALIVE_SECONDS = 15


# --- models and storage --------------------------------------------------------------


class NoteIn(BaseModel):
    fields: dict[str, str] = Field(description="Field name -> content (HTML), names as listed by 'overview'")
    tags: list[str] = []
    note_type: str | None = Field(default=None, description="Overrides the draft's note type for this note")
    deck: str | None = Field(default=None, description="Overrides the draft's deck for this note")


class DraftNote(BaseModel):
    n: int = 0
    deck: str
    note_type: str
    fields: dict[str, str]
    tags: list[str] = []
    allow_duplicate: bool = False
    error: str | None = None  # why the last commit of this note failed
    review: Literal["open", "accepted", "rejected"] = "open"
    comment: str | None = None  # the user's note from the preview


class Draft(BaseModel):
    id: str
    title: str | None = None
    deck: str
    note_type: str
    tags: list[str] = []
    allow_duplicate: bool = False
    updated: datetime
    next_n: int = 1
    submitted: bool = False  # the user pressed Commit in the preview, review has not reported it yet
    notes: list[DraftNote] = []


def _cards(count: int) -> str:
    return f"{count} card" if count == 1 else f"{count} cards"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DraftStore:
    """One JSON file per draft, so drafts survive restarts. Drafts untouched for 14 days are removed."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        cutoff = _now() - timedelta(days=14)
        for draft in self.all():
            if draft.updated < cutoff:
                self.delete(draft.id)

    def create(self, **values: Any) -> Draft:
        draft = Draft(id="d_" + secrets.token_hex(3), updated=_now(), **values)
        self._save(draft)
        return draft

    def load(self, draft_id: str) -> Draft:
        path = self._path(draft_id)
        if not path.exists():
            raise ToolError(f"Draft '{draft_id}' does not exist. Call review without draft_id to list open drafts.")
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))

    @asynccontextmanager
    async def edit(self, draft_id: str) -> AsyncGenerator[Draft, None]:
        async with self._locks.setdefault(draft_id, asyncio.Lock()):
            draft = self.load(draft_id)
            yield draft
            draft.updated = _now()
            self._save(draft)

    def all(self) -> list[Draft]:
        drafts = [Draft.model_validate_json(p.read_text(encoding="utf-8")) for p in self._root.glob("d_*.json")]
        return sorted(drafts, key=lambda d: d.updated, reverse=True)

    def delete(self, draft_id: str) -> None:
        self._path(draft_id).unlink(missing_ok=True)

    def _path(self, draft_id: str) -> Path:
        if not re.fullmatch(r"d_[0-9a-f]{6}", draft_id):
            raise ToolError(f"'{draft_id}' is not a valid draft id.")
        return self._root / f"{draft_id}.json"

    def _save(self, draft: Draft) -> None:
        path = self._path(draft.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(draft.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)


# --- validation and commit -----------------------------------------------------------


def _anki_note(note: DraftNote, deck: str, allow_duplicate: bool, tags: list[str]) -> dict[str, Any]:
    return {
        "deckName": deck,
        "modelName": note.note_type,
        "fields": note.fields,
        "tags": tags,
        "options": {"allowDuplicate": allow_duplicate or note.allow_duplicate},
    }


async def _check(
    a: App, candidates: list[tuple[str, DraftNote]], others: list[DraftNote], allow_duplicate: bool
) -> list[str]:
    """Validate candidates against Anki. Normalizes field names in place, returns error lines."""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for other in others:
        nt = await a.note_types.get(other.note_type)
        seen.add((other.note_type, strip_html(other.fields.get(nt.fields[0], "")).lower()))

    decks = set(await a.anki.invoke("deckNames"))
    to_ask: list[tuple[str, DraftNote, str]] = []
    for label, note in candidates:
        if note.deck not in decks:
            # A bare subdeck name would silently create a new top-level deck on commit.
            similar = [d for d in decks if d.lower().endswith("::" + note.deck.lower())]
            if similar:
                errors.append(f"{label}: deck '{note.deck}' does not exist. Did you mean '{similar[0]}'?")
                continue
        try:
            nt = await a.note_types.get(note.note_type)
        except AnkiError as exc:
            errors.append(f"{label}: {exc}")
            continue
        fields, unknown = nt.normalize(note.fields)
        if unknown:
            errors.append(f"{label}: unknown fields {unknown}, valid: {', '.join(nt.fields)}")
            continue
        note.fields = fields
        key = (note.note_type, strip_html(fields.get(nt.fields[0], "")).lower())
        if key in seen and not (allow_duplicate or note.allow_duplicate):
            errors.append(f"{label}: same '{nt.fields[0]}' as another card in this draft")
            continue
        seen.add(key)
        to_ask.append((label, note, nt.kind))

    if to_ask:
        # Missing decks are created on commit; Anki's duplicate check is collection-wide anyway.
        payload = [
            _anki_note(note, note.deck if note.deck in decks else "Default", allow_duplicate, note.tags)
            for _, note, _ in to_ask
        ]
        results = await a.anki.invoke("canAddNotesWithErrorDetail", notes=payload)
        for (label, _, kind), result in zip(to_ask, results, strict=True):
            if not result["canAdd"]:
                message = result["error"]
                if kind == "cloze" and "unknown reason" in message:
                    message += " (a Cloze note needs at least one {{c1::...}})"
                errors.append(f"{label}: {message}")
    return errors


async def _store_media(a: App, notes: list[DraftNote]) -> dict[str, str]:
    """Copy staged images into Anki's media folder. Returns image id -> Anki file name."""
    ids = sorted({m for n in notes for v in n.fields.values() for m in MEDIA_REF.findall(v)})
    if not ids:
        return {}
    calls = [
        (
            "storeMediaFile",
            {"filename": f"mcp-{media_id}.png", "path": str(a.media.get(media_id).path), "deleteExisting": False},
        )
        for media_id in ids
    ]
    results = await a.anki.multi(calls)
    return {media_id: r for media_id, r in zip(ids, results, strict=True) if isinstance(r, str)}


async def _commit(a: App, draft_id: str) -> tuple[str | None, list[int], list[DraftNote]]:
    """Add all accepted notes to Anki. Returns (batch id, created note ids, failed notes)."""
    batch_id = secrets.token_hex(4)
    batch_tags = [CREATED_TAG, f"{BATCH_PREFIX}{batch_id}"]
    async with a.drafts.edit(draft_id) as draft:
        selected = [n for n in draft.notes if n.review == "accepted"]
        if not selected:
            return None, [], []
        decks = set(await a.anki.invoke("deckNames"))
        for deck in sorted({n.deck for n in selected} - decks):
            await a.anki.invoke("createDeck", deck=deck)
        stored = await _store_media(a, selected)

        calls, sendable = [], []
        for note in selected:
            missing = [m for v in note.fields.values() for m in MEDIA_REF.findall(v) if m not in stored]
            if missing:
                note.error = "an image could not be copied to Anki"
                continue
            payload = _anki_note(note, note.deck, draft.allow_duplicate, [*draft.tags, *note.tags, *batch_tags])
            payload["fields"] = {
                k: MEDIA_REF.sub(lambda m: f'src="{stored[m.group(1)]}"', v) for k, v in note.fields.items()
            }
            calls.append(("addNote", {"note": payload}))
            sendable.append(note)

        responses = await a.anki.multi(calls, timeout=120) if calls else []
        created: list[int] = []
        succeeded: set[int] = set()
        for note, response in zip(sendable, responses, strict=True):
            if isinstance(response, int):
                created.append(response)
                succeeded.add(note.n)
            else:
                note.error = str(response)
        draft.notes = [n for n in draft.notes if n.n not in succeeded]
        failed = [n for n in selected if n.n not in succeeded]

    if created:
        a.journal.append({"batch_id": batch_id, "kind": "commit", "draft_id": draft_id, "created": created})
    return (batch_id if created else None), created, failed


async def _finish(a: App, draft_id: str) -> str:
    """Commit what the user accepted, drop what they rejected and report the rest."""
    batch_id, created, failed = await _commit(a, draft_id)
    async with a.drafts.edit(draft_id) as draft:
        rejected = [n.n for n in draft.notes if n.review == "rejected"]
        draft.notes = [n for n in draft.notes if n.review != "rejected"]
        draft.submitted = False
        revise = [n for n in draft.notes if n.comment]
        undecided = [n.n for n in draft.notes if not n.comment and n.review == "open"]
        left = len(draft.notes)

    lines = []
    if created:
        lines.append(f"Batch {batch_id}: {_cards(len(created))} added to Anki. Undo with undo('{batch_id}').")
    if rejected:
        lines.append("Rejected and removed: " + ", ".join(f"#{n}" for n in rejected))
    lines.extend(f"Failed #{n.n}: {n.error}" for n in failed)
    if revise:
        lines.append(f"Revise (still in draft {draft_id}), apply with draft_edit and call review again:")
        lines.extend(f'#{n.n}: "{n.comment}"' for n in revise)
    if undecided:
        lines.append("Not decided yet: " + ", ".join(f"#{n}" for n in undecided))
    if left == 0:
        a.drafts.delete(draft_id)
        lines.append("Draft finished.")
    return "\n".join(lines) or "Nothing changed."


def _as_text(draft: Draft) -> str:
    lines = [f"{draft.id} · {draft.title or 'untitled'} · {_cards(len(draft.notes))}"]
    for note in draft.notes:
        lines.append(f"#{note.n} [{note.note_type} -> {note.deck}]")
        lines.extend(f"  {name}: {value}" for name, value in note.fields.items() if value)
    return "\n".join(lines)


# --- tools ---------------------------------------------------------------------------


async def _append(a: App, draft_id: str | None, notes: list[DraftNote], **new: Any) -> str:
    if not draft_id:
        draft_id = a.drafts.create(**new).id
    async with a.drafts.edit(draft_id) as draft:
        first = draft.next_n
        for note in notes:
            note.n = draft.next_n
            draft.next_n += 1
            draft.notes.append(note)
        total = len(draft.notes)
    return f"Draft {draft_id}: +{_cards(len(notes))} (#{first}-#{draft.next_n - 1}), {total} in total."


@tool("Add cards to draft", DRAFT_ONLY)
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

    Without draft_id a new draft is created; then deck and note_type are required (missing decks are
    created on commit). Each card may override note_type and deck. If any card fails, none are added
    and every problem is listed. Next step: review.
    """
    a = app(ctx)
    others: list[DraftNote] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        deck, note_type, allow_duplicate, others = draft.deck, draft.note_type, draft.allow_duplicate, draft.notes
    elif not deck or not note_type:
        raise ToolError("A new draft needs 'deck' and 'note_type'.")
    candidates = [
        (
            f"[{i}]",
            DraftNote(deck=n.deck or deck, note_type=n.note_type or note_type, fields=n.fields, tags=n.tags),
        )
        for i, n in enumerate(notes)
    ]
    errors = await _check(a, candidates, others, allow_duplicate)
    if errors:
        raise ToolError("Nothing added:\n" + "\n".join(errors))
    summary = await _append(
        a,
        draft_id,
        [note for _, note in candidates],
        deck=deck,
        note_type=note_type,
        tags=tags or [],
        title=title,
        allow_duplicate=allow_duplicate,
    )
    new_decks = sorted({note.deck for _, note in candidates} - set(await a.anki.invoke("deckNames")))
    if new_decks:
        summary += " New decks, created when the cards are added: " + ", ".join(new_decks) + "."
    return summary + " Next: review."


class MaskIn(BaseModel):
    label: str | None = Field(default=None, description="Text on the image (PDF label or graph node) to hide")
    region: list[float] | None = Field(
        default=None, min_length=4, max_length=4, description="[left, top, width, height] as fractions of the image"
    )
    group: int | None = Field(default=None, description="Masks with the same group become one card")


@tool("Add image occlusion to draft", DRAFT_ONLY)
async def draft_add_occlusion(
    ctx: Ctx,
    image: Annotated[str, Field(description="Staged image id, e.g. 'img:ab12cd34'")],
    masks: Annotated[list[MaskIn], Field(min_length=1, max_length=50)],
    header: str = "",
    back_extra: str = "",
    hide_all: Annotated[bool, Field(description="True: hide all, guess one. False: hide one, guess one")] = True,
    draft_id: str | None = None,
    deck: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
) -> list[Any]:
    """Add an Image Occlusion note (Anki 23.10+) to a draft. Each mask group becomes one card."""
    a = app(ctx)
    io_types = [nt for nt in await a.note_types.all() if nt.kind == "io"]
    if not io_types:
        raise ToolError(
            "No Image Occlusion note type found. In Anki: Tools > Manage Note Types > Add > Image Occlusion."
        )
    nt = io_types[0]
    others: list[DraftNote] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        deck, others = draft.deck, draft.notes
    elif not deck:
        raise ToolError("A new draft needs 'deck'.")
    staged = a.media.get(image)
    boxes = staged.meta.get("boxes", [])

    resolved: list[Mask] = []
    problems = []
    next_group = max([m.group or 0 for m in masks] + [0]) + 1
    for i, m in enumerate(masks):
        if m.label:
            mask = find_label(boxes, m.label)
            if mask is None:
                known = ", ".join(sorted({b["text"] for b in boxes})[:30]) or "none (no text layer)"
                problems.append(f"[{i}] label '{m.label}' not found. Known words: {known}")
                continue
        elif m.region:
            left, top, width, height = m.region
            if not (0 <= left <= 1 and 0 <= top <= 1 and 0 < width <= 1 and 0 < height <= 1):
                problems.append(f"[{i}] region must be fractions between 0 and 1")
                continue
            mask = Mask(left, top, width, height, 0)
        else:
            problems.append(f"[{i}] needs 'label' or 'region'")
            continue
        if m.group is None:
            mask.group, next_group = next_group, next_group + 1
        else:
            mask.group = m.group
        resolved.append(mask)
    if problems:
        raise ToolError("Nothing added:\n" + "\n".join(problems))

    io = nt.io_fields or {}
    fields = {
        io["occlusion"]: build_field(resolved, hide_all),
        io["image"]: f'<img src="{staged.ref}">',
        io.get("header", "Header"): header,
        io.get("back_extra", "Back Extra"): back_extra,
    }
    note = DraftNote(deck=deck, note_type=nt.name, fields=fields, tags=tags or [], allow_duplicate=True)
    errors = await _check(a, [("[0]", note)], others, True)
    if errors:
        raise ToolError("Nothing added:\n" + "\n".join(errors))
    summary = await _append(a, draft_id, [note], deck=deck, note_type=nt.name, tags=tags or [], title=title)

    with Image.open(staged.path) as img:
        preview = draw_masks(img.convert("RGB"), resolved)
    groups = len({m.group for m in resolved})
    return [
        f"{summary} Image occlusion with {len(resolved)} masks, {_cards(groups)}. Check the mask positions in the image.",
        McpImage(data=png_bytes(downscale(preview, 800)), format="png"),
    ]


class EditIn(BaseModel):
    n: int = Field(description="Card number in the draft")
    fields: dict[str, str] | None = Field(default=None, description="Only the fields that change")
    tags: list[str] | None = Field(default=None, description="Replaces the card's tags")
    remove: bool = False


@tool("Edit draft cards", DRAFT_ONLY)
async def draft_edit(ctx: Ctx, draft_id: str, edits: Annotated[list[EditIn], Field(min_length=1)]) -> str:
    """Change or remove single cards of a draft by number. Fields are merged, so send only what changes."""
    a = app(ctx)
    async with a.drafts.edit(draft_id) as draft:
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
            note.error, note.review, note.comment = None, "open", None
            changed.append((f"#{e.n}", note))

        touched = removed | {note.n for _, note in changed}
        others = [note for note in draft.notes if note.n not in touched]
        errors = await _check(a, changed, others, draft.allow_duplicate)
        if errors:
            raise ToolError("Nothing changed:\n" + "\n".join(errors))

        replaced = {note.n: note for _, note in changed}
        draft.notes = [replaced.get(n.n, n) for n in draft.notes if n.n not in removed]
        left = len(draft.notes)
    return f"Draft {draft_id}: {len(changed)} changed, {len(removed)} removed, {_cards(left)} left."


@tool("Review and add to Anki", ADDS_NEW)
async def review(
    ctx: Ctx,
    draft_id: Annotated[str | None, Field(description="Without it: list open drafts")] = None,
    in_chat: Annotated[
        bool, Field(description="Only if the browser preview cannot be used: return the cards as text instead")
    ] = False,
    accept: Annotated[
        list[int] | None, Field(description="With in_chat: card numbers the user approved in the chat; adds them")
    ] = None,
) -> str:
    """Show the draft to the user and add the cards they accept to Anki.

    Opens a preview in the browser and WAITS until the user has gone through the cards. Accepted cards
    are added to Anki right away, rejected ones are dropped. The result lists the user's notes on cards
    to revise: apply them with draft_edit and call review again in the same turn. No notes: you are done.
    """
    a = app(ctx)
    if draft_id is None:
        drafts = a.drafts.all()
        return (
            "\n".join(
                f"{d.id} · {d.title or 'untitled'} · {d.deck} · {_cards(len(d.notes))} · {d.updated:%Y-%m-%d %H:%M} UTC"
                for d in drafts
            )
            or "No open drafts."
        )

    draft = a.drafts.load(draft_id)
    if in_chat:
        if accept is None:
            return _as_text(draft) + "\n\nShow these to the user, then call review with in_chat and accept=[...]."
        async with a.drafts.edit(draft_id) as d:
            for note in d.notes:
                if note.n in accept:
                    note.review = "accepted"
        return await _finish(a, draft_id)

    if not draft.submitted:
        if a.preview is None:
            a.preview = Preview(a)
        url = await a.preview.open(draft_id)
        if url:
            await asyncio.to_thread(webbrowser.open, url)
        waited = 0
        try:
            while not await a.preview.wait(draft_id, KEEPALIVE_SECONDS):
                waited += KEEPALIVE_SECONDS
                if waited >= REVIEW_WAIT_SECONDS:
                    return "The user has not finished the preview yet. Call review again to keep waiting."
                await ctx.report_progress(waited, message="Waiting for the user to review the cards")
        except asyncio.CancelledError:
            a.preview.forget(draft_id)
            raise
    if a.preview:
        a.preview.forget(draft_id)
    return await _finish(a, draft_id)
