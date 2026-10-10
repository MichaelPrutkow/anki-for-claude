"""Drafts: cards that are checked against Anki but not yet added. The user approves them in the chat,
then draft_commit adds them."""

import asyncio
import os
import re
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Image as McpImage
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from anki_mcp.anki import AnkiError, NoteType
from anki_mcp.images import downscale, local_images, png_bytes, replace_images, upload_images
from anki_mcp.occlusion import Mask, build_field, draw_masks, find_label, parse_field
from anki_mcp.server import ADDS, BATCH_PREFIX, CREATED_TAG, DRAFT, READ_ONLY, App, Ctx, app, tool
from anki_mcp.text import cloze_ords, lint, readable, strip_html

MAX_AGE = timedelta(days=14)


class CardIn(BaseModel):
    fields: dict[str, str] = Field(description="Field name -> content (HTML), names exactly as overview lists them")
    tags: list[str] = []
    note_type: str | None = Field(default=None, description="Only if it differs from the draft's note type")
    deck: str | None = Field(default=None, description="Only if it differs from the draft's deck")


class DraftCard(BaseModel):
    n: int = 0
    deck: str
    note_type: str
    fields: dict[str, str]
    tags: list[str] = []
    allow_duplicate: bool = False
    error: str | None = None  # why the last draft_commit of this card failed


class Draft(BaseModel):
    id: str
    title: str | None = None
    deck: str
    note_type: str
    tags: list[str] = []
    updated: datetime
    next_n: int = 1
    cards: list[DraftCard] = []


def _now() -> datetime:
    return datetime.now(UTC)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class DraftStore:
    """One JSON file per draft, so drafts survive restarts. Drafts untouched for 14 days are removed."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        for draft in self.all():
            if not draft.cards or draft.updated < _now() - MAX_AGE:
                self.delete(draft.id)

    def create(self, **values: Any) -> Draft:
        draft = Draft(id="d_" + secrets.token_hex(3), updated=_now(), **values)
        self._save(draft)
        return draft

    def load(self, draft_id: str) -> Draft:
        path = self._path(draft_id)
        if not path.exists():
            raise ToolError(f"Draft '{draft_id}' does not exist. draft_show without an id lists the open drafts.")
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))

    @asynccontextmanager
    async def edit(self, draft_id: str) -> AsyncGenerator[Draft, None]:
        async with self._locks.setdefault(draft_id, asyncio.Lock()):
            draft = self.load(draft_id)
            yield draft
            if draft.cards:
                draft.updated = _now()
                self._save(draft)
            else:
                self.delete(draft_id)

    def all(self) -> list[Draft]:
        drafts = []
        for path in self._root.glob("d_*.json"):
            try:
                drafts.append(Draft.model_validate_json(path.read_text(encoding="utf-8")))
            except ValidationError:
                continue
        return sorted(drafts, key=lambda d: d.updated, reverse=True)

    def delete(self, draft_id: str) -> None:
        self._path(draft_id).unlink(missing_ok=True)

    def _path(self, draft_id: str) -> Path:
        if not re.fullmatch(r"d_[0-9a-f]{6}", draft_id):
            raise ToolError(f"'{draft_id}' is not a draft id. Draft ids look like 'd_1a2b3c'.")
        return self._root / f"{draft_id}.json"

    def _save(self, draft: Draft) -> None:
        path = self._path(draft.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(draft.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)


# --- checks --------------------------------------------------------------------------


async def _check(a: App, cards: list[tuple[str, DraftCard]], others: list[DraftCard]) -> tuple[list[str], set[str]]:
    """Check new or changed cards against Anki and the rest of the draft. Normalizes field names in place.

    Returns (errors, decks that do not exist yet).
    """
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for other in others:
        nt = await a.note_types.get(other.note_type)
        seen.add((other.note_type, strip_html(other.fields.get(nt.fields[0], "")).lower()))

    decks = set(await a.anki.invoke("deckNames"))
    to_ask: list[tuple[str, DraftCard, NoteType]] = []
    for label, card in cards:
        if card.deck not in decks:
            # A bare subdeck name would silently create a new top-level deck.
            similar = [d for d in decks if d.lower().endswith("::" + card.deck.lower())]
            if similar:
                errors.append(f"{label}: there is no deck '{card.deck}'. Did you mean '{similar[0]}'?")
                continue
        try:
            nt = await a.note_types.get(card.note_type)
        except AnkiError as exc:
            errors.append(f"{label}: {exc}")
            continue
        fields, unknown = nt.normalize(card.fields)
        if unknown:
            errors.append(f"{label}: unknown fields {unknown}. {card.note_type} has: {', '.join(nt.fields)}")
            continue
        card.fields = fields
        missing = [name for value in fields.values() for name in local_images(value) if not a.images.has(name)]
        if missing:
            errors.append(f"{label}: no image {', '.join(missing)} in {a.images.folder}. Create it first.")
            continue
        key = (card.note_type, strip_html(fields.get(nt.fields[0], "")).lower())
        if key in seen and not card.allow_duplicate:
            errors.append(f"{label}: another card in this draft has the same {nt.fields[0]}")
            continue
        seen.add(key)
        to_ask.append((label, card, nt))

    if to_ask:
        # Decks that do not exist yet are created by draft_commit. Anki's duplicate check is collection-wide anyway.
        notes = [
            {
                "deckName": card.deck if card.deck in decks else "Default",
                "modelName": card.note_type,
                "fields": card.fields,
                "tags": card.tags,
                "options": {"allowDuplicate": card.allow_duplicate},
            }
            for _, card, _ in to_ask
        ]
        results = await a.anki.invoke("canAddNotesWithErrorDetail", notes=notes)
        for (label, _, nt), result in zip(to_ask, results, strict=True):
            if not result["canAdd"]:
                message = result["error"]
                if nt.kind == "cloze" and "unknown reason" in message:
                    message += " (a cloze card needs at least one {{c1::...}})"
                errors.append(f"{label}: {message}")
    return errors, {card.deck for _, card in cards} - decks


def _warnings(cards: list[DraftCard], note_types: dict[str, NoteType]) -> list[str]:
    lines = []
    for card in cards:
        nt = note_types.get(card.note_type)
        if nt and nt.kind != "io":
            lines.extend(f"#{card.n} {problem}" for problem in lint(card.fields))
    return lines


# --- how cards look in the chat ------------------------------------------------------


def _header(draft: Draft) -> str:
    title = f' "{draft.title}"' if draft.title else ""
    return f"Draft {draft.id}{title}, deck {draft.deck}"


def _card_text(card: DraftCard, nt: NoteType | None, deck: str) -> str:
    head = f"#{card.n} {card.note_type}"
    fields = dict(card.fields)
    if nt and nt.kind == "cloze":
        head += " (" + ", ".join(f"c{n}" for n in cloze_ords(fields)) + ")"
    elif nt and nt.kind == "io" and nt.io_fields:
        masks, hide_all = parse_field(fields.pop(nt.io_fields.get("occlusion", ""), ""))
        groups = len({m.group for m in masks})
        mode = "all hidden, one asked" if hide_all else "one hidden at a time"
        head += f" ({_count(len(masks), 'mask')}, {_count(groups, 'card')}, {mode})"
        images = local_images(fields.get(nt.io_fields.get("image", ""), ""))
        if images:
            head += f", masks drawn in {Path(images[0]).stem}-masks.png"
    if card.deck != deck:
        head += f", deck {card.deck}"

    lines = [head]
    for name, value in fields.items():
        first, *rest = readable(value).split("\n")
        if first:
            lines.append(f"{name}: {first}")
            lines.extend(f"  {line}" for line in rest)
    if card.tags:
        lines.append("Tags: " + " ".join(card.tags))
    if card.error:
        lines.append(f"Last draft_commit failed: {card.error}")
    return "\n".join(lines)


async def _cards_text(a: App, draft: Draft, cards: list[DraftCard]) -> list[str]:
    """The cards as text for the chat, plus where their images are."""
    note_types = {nt.name: nt for nt in await a.note_types.all()}
    blocks = [_card_text(card, note_types.get(card.note_type), draft.deck) for card in cards]
    if any(local_images(v) for card in cards for v in card.fields.values()):
        blocks.append(f"The images are in {a.images.folder}.")
    return blocks


def _numbers(cards: list[DraftCard] | list[int]) -> str:
    """'#1-#3, #5' for cards 1, 2, 3 and 5."""
    numbers = sorted(c if isinstance(c, int) else c.n for c in cards)
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(f"#{run[0]}" if len(run) == 1 else f"#{run[0]}-#{run[-1]}" for run in runs)


# --- tools ---------------------------------------------------------------------------


async def _append(a: App, draft_id: str | None, cards: list[DraftCard], **new: Any) -> Draft:
    if not draft_id:
        draft_id = a.drafts.create(**new).id
    async with a.drafts.edit(draft_id) as draft:
        for card in cards:
            card.n = draft.next_n
            draft.next_n += 1
            draft.cards.append(card)
    return draft


def _added(draft: Draft, cards: list[DraftCard], new_decks: set[str]) -> list[str]:
    total = _count(len(draft.cards), "card")
    lines = [f"{_header(draft)}: added {_numbers(cards)}. The draft has {total}, none of them is in Anki yet."]
    if new_decks:
        lines.append("New deck, created by draft_commit: " + ", ".join(sorted(new_decks)))
    return lines


NEXT_STEP = "Show the cards to the user. Apply their changes with draft_edit; when they approve, call draft_commit."


@tool("Add cards to a draft", DRAFT)
async def draft_add(
    ctx: Ctx,
    cards: Annotated[list[CardIn], Field(min_length=1, max_length=50)],
    draft_id: Annotated[str | None, Field(description="Add to this draft. Without it a new draft is created")] = None,
    deck: Annotated[str | None, Field(description="New draft: full deck name, e.g. 'Math::Analysis'")] = None,
    note_type: Annotated[str | None, Field(description="New draft: note type, e.g. 'Basic'")] = None,
    tags: Annotated[list[str] | None, Field(description="New draft: tags for all its cards")] = None,
    title: Annotated[str | None, Field(description="New draft: a short name")] = None,
    allow_duplicate: Annotated[bool, Field(description="Allow cards whose first field already exists")] = False,
) -> str:
    """Check cards against Anki and add them to a draft. Nothing is written to Anki.

    Returns the cards as text to show the user. If any card has a problem, none is added and every problem is listed.
    """
    a = app(ctx)
    others: list[DraftCard] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        deck, note_type, others = draft.deck, draft.note_type, draft.cards
    elif not deck or not note_type:
        raise ToolError("A new draft needs 'deck' and 'note_type'. To add to an existing draft, pass its draft_id.")
    new = [
        DraftCard(
            deck=c.deck or deck,
            note_type=c.note_type or note_type,
            fields=c.fields,
            tags=c.tags,
            allow_duplicate=allow_duplicate,
        )
        for c in cards
    ]
    errors, new_decks = await _check(a, [(f"cards[{i}]", card) for i, card in enumerate(new)], others)
    if errors:
        raise ToolError("Nothing was added. Fix these and send all cards again:\n" + "\n".join(errors))
    draft = await _append(a, draft_id, new, deck=deck, note_type=note_type, tags=tags or [], title=title)

    lines = _added(draft, new, new_decks)
    warnings = _warnings(new, {nt.name: nt for nt in await a.note_types.all()})
    if warnings:
        lines += ["Possible formatting problems, fix the real ones with draft_edit:", *warnings]
    return "\n\n".join(["\n".join(lines), *await _cards_text(a, draft, new), NEXT_STEP])


class MaskIn(BaseModel):
    label: str | None = Field(default=None, description="Text on the image (a PDF word or a graph node) to hide")
    region: list[float] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Area to hide instead of a label: [left, top, right, bottom] as fractions (0-1) of the image",
    )
    group: int | None = Field(default=None, description="Masks with the same group are asked together on one card")


@tool("Add an image occlusion card to a draft", DRAFT)
async def draft_add_occlusion(
    ctx: Ctx,
    image: Annotated[str, Field(description="Image file name from stage_image or render_graph, e.g. 'heart.png'")],
    masks: Annotated[list[MaskIn], Field(min_length=1, max_length=50)],
    header: Annotated[str, Field(description="Shown above the image, e.g. what to name")] = "",
    back_extra: Annotated[str, Field(description="Shown below the image on the back")] = "",
    hide_all: Annotated[
        bool, Field(description="True: all masks hidden, one asked. False: only the asked mask hidden")
    ] = True,
    draft_id: Annotated[str | None, Field(description="Add to this draft. Without it a new draft is created")] = None,
    deck: Annotated[str | None, Field(description="New draft: full deck name")] = None,
    tags: Annotated[list[str] | None, Field(description="New draft: tags for all its cards")] = None,
    title: Annotated[str | None, Field(description="New draft: a short name")] = None,
) -> list[Any]:
    """Add an Image Occlusion note (Anki 23.10+) to a draft. Each mask, or each group of masks, becomes one card.

    Returns the image with the masks drawn in. Check that every mask covers exactly its label.
    """
    a = app(ctx)
    io_types = [nt for nt in await a.note_types.all() if nt.kind == "io"]
    if not io_types:
        raise ToolError(
            "There is no Image Occlusion note type. It needs Anki 23.10 or newer; "
            "then in Anki: Tools > Manage Note Types > Add > 'Add: Image Occlusion'."
        )
    nt = io_types[0]
    others: list[DraftCard] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        deck, others = draft.deck, draft.cards
    elif not deck:
        raise ToolError("A new draft needs 'deck'. To add to an existing draft, pass its draft_id.")
    staged = a.images.get(image)

    resolved: list[Mask] = []
    problems = []
    next_group = max([m.group or 0 for m in masks] + [0]) + 1
    for i, m in enumerate(masks):
        if m.label:
            mask = find_label(staged.labels, m.label)
            if mask is None:
                known = (
                    ", ".join(sorted({b["text"] for b in staged.labels})[:40]) or "none, the image has no text layer"
                )
                problems.append(f"masks[{i}]: label '{m.label}' not found. Labels on the image: {known}")
                continue
        elif m.region:
            left, top, right, bottom = m.region
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                problems.append(f"masks[{i}]: region needs 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
                continue
            mask = Mask(left, top, right - left, bottom - top)
        else:
            problems.append(f"masks[{i}]: needs 'label' or 'region'")
            continue
        if m.group is None:
            mask.group, next_group = next_group, next_group + 1
        else:
            mask.group = m.group
        resolved.append(mask)
    if problems:
        raise ToolError("Nothing was added:\n" + "\n".join(problems))

    io = nt.io_fields or {}
    fields = {
        io["occlusion"]: build_field(resolved, hide_all),
        io["image"]: staged.tag(),
        io.get("header", "Header"): header,
        io.get("back_extra", "Back Extra"): back_extra,
    }
    card = DraftCard(deck=deck, note_type=nt.name, fields=fields, tags=[], allow_duplicate=True)
    errors, new_decks = await _check(a, [("card", card)], others)
    if errors:
        raise ToolError("Nothing was added:\n" + "\n".join(errors))
    draft = await _append(a, draft_id, [card], deck=deck, note_type=nt.name, tags=tags or [], title=title)

    with Image.open(staged.path) as img:
        preview = draw_masks(img.convert("RGB"), resolved)
    a.images.save_preview(preview, f"{staged.path.stem}-masks.png")
    blocks = ["\n".join(_added(draft, [card], new_decks)), *await _cards_text(a, draft, [card]), NEXT_STEP]
    text = "\n\n".join(blocks)
    return [text, McpImage(data=png_bytes(downscale(preview, 800)), format="png")]


class EditIn(BaseModel):
    card: int = Field(description="Card number in the draft, e.g. 3 for #3")
    fields: dict[str, str] | None = Field(default=None, description="Only the fields that change")
    tags: list[str] | None = Field(default=None, description="Replaces the card's tags")
    remove: bool = Field(default=False, description="Remove the card from the draft")


@tool("Change cards in a draft", DRAFT)
async def draft_edit(ctx: Ctx, draft_id: str, edits: Annotated[list[EditIn], Field(min_length=1)]) -> str:
    """Change or remove cards of a draft by number. Send only the fields that change; the others stay.

    Returns the changed cards as text to show the user.
    """
    a = app(ctx)
    async with a.drafts.edit(draft_id) as draft:
        by_n = {card.n: card for card in draft.cards}
        missing = [e.card for e in edits if e.card not in by_n]
        if missing:
            raise ToolError(f"Draft {draft_id} has no card {_numbers(missing)}.")

        removed = {e.card for e in edits if e.remove}
        changed: list[DraftCard] = []
        for e in edits:
            if e.remove:
                continue
            card = by_n[e.card].model_copy(deep=True)
            if e.fields:
                card.fields = {**card.fields, **e.fields}
            if e.tags is not None:
                card.tags = e.tags
            card.error = None
            changed.append(card)

        touched = removed | {card.n for card in changed}
        others = [card for card in draft.cards if card.n not in touched]
        errors, _ = await _check(a, [(f"#{card.n}", card) for card in changed], others)
        if errors:
            raise ToolError("Nothing was changed:\n" + "\n".join(errors))

        replaced = {card.n: card for card in changed}
        draft.cards = [replaced.get(card.n, card) for card in draft.cards if card.n not in removed]

    if not draft.cards:
        return f"Draft {draft_id} has no cards left and was deleted."
    done = []
    if changed:
        done.append(f"changed {_numbers(changed)}")
    if removed:
        done.append(f"removed {_numbers(sorted(removed))}")
    lines = [
        f"Draft {draft_id}: {' and '.join(done)}. {_count(len(draft.cards), 'card')} left, none of them is in Anki yet."
    ]
    warnings = _warnings(changed, {nt.name: nt for nt in await a.note_types.all()})
    if warnings:
        lines += ["Possible formatting problems:", *warnings]
    if not changed:
        return "\n".join(lines)
    return "\n\n".join(["\n".join(lines), *await _cards_text(a, draft, changed), "Show the changed cards to the user."])


@tool("Show a draft", READ_ONLY)
async def draft_show(
    ctx: Ctx,
    draft_id: Annotated[str | None, Field(description="Without it: list the open drafts")] = None,
    cards: Annotated[list[int] | None, Field(description="Only these card numbers")] = None,
) -> str:
    """Show the cards of a draft as text, or list the open drafts. Drafts survive restarts."""
    a = app(ctx)
    if draft_id is None:
        drafts = a.drafts.all()
        if not drafts:
            return "No open drafts."
        lines = ["Open drafts, newest first:"]
        for d in drafts:
            title = f' "{d.title}"' if d.title else ""
            changed = f"{d.updated:%Y-%m-%d %H:%M} UTC"
            lines.append(f"{d.id}{title}: deck {d.deck}, {_count(len(d.cards), 'card')}, last changed {changed}")
        return "\n".join(lines)

    draft = a.drafts.load(draft_id)
    shown = [card for card in draft.cards if cards is None or card.n in cards]
    header = f"{_header(draft)}: {_count(len(draft.cards), 'card')}, none of them is in Anki yet."
    return "\n\n".join([header, *await _cards_text(a, draft, shown)])


@tool("Add draft cards to Anki", ADDS)
async def draft_commit(
    ctx: Ctx,
    draft_id: str,
    cards: Annotated[
        list[int] | None, Field(min_length=1, description="Only these card numbers. Without it: all cards")
    ] = None,
) -> str:
    """Add the cards the user approved to Anki. Missing decks are created. Returns a batch id for undo.

    Cards that fail stay in the draft with the reason. The draft is deleted when no cards are left.
    """
    a = app(ctx)
    batch_id = secrets.token_hex(4)
    async with a.drafts.edit(draft_id) as draft:
        wanted = set(cards) if cards is not None else {card.n for card in draft.cards}
        missing = sorted(wanted - {card.n for card in draft.cards})
        if missing:
            raise ToolError(f"Draft {draft_id} has no card {_numbers(missing)}.")
        selected = [card for card in draft.cards if card.n in wanted]

        decks = set(await a.anki.invoke("deckNames"))
        for deck in sorted({card.deck for card in selected} - decks):
            await a.anki.invoke("createDeck", deck=deck)
        images = sorted({name for card in selected for value in card.fields.values() for name in local_images(value)})
        stored = await upload_images(a, images)

        calls, sent = [], []
        for card in selected:
            failed = [name for value in card.fields.values() for name in local_images(value) if name not in stored]
            if failed:
                card.error = f"could not copy {', '.join(failed)} to Anki"
                continue
            note = {
                "deckName": card.deck,
                "modelName": card.note_type,
                "fields": {name: replace_images(value, stored) for name, value in card.fields.items()},
                "tags": [*draft.tags, *card.tags, CREATED_TAG, BATCH_PREFIX + batch_id],
                "options": {"allowDuplicate": card.allow_duplicate},
            }
            calls.append(("addNote", {"note": note}))
            sent.append(card)

        results = await a.anki.multi(calls) if calls else []
        created: list[int] = []
        added: list[DraftCard] = []
        for card, result in zip(sent, results, strict=True):
            if isinstance(result, int):
                created.append(result)
                added.append(card)
            else:
                card.error = str(result).removeprefix("addNote: ")
        done = {card.n for card in added}
        draft.cards = [card for card in draft.cards if card.n not in done]
        failed_cards = [card for card in selected if card.n not in done]

    lines = []
    if created:
        a.journal.append({"batch_id": batch_id, "kind": "commit", "draft_id": draft_id, "created": created})
        decks_used = ", ".join(sorted({card.deck for card in added}))
        lines.append(
            f"Added {_count(len(created), 'card')} to Anki ({_numbers(added)}, deck {decks_used}). "
            f'Batch id {batch_id}: undo("{batch_id}") removes {"it" if len(created) == 1 else "them"} again.'
        )
    else:
        lines.append("Nothing was added to Anki.")
    if failed_cards:
        lines.append("Not added:")
        lines.extend(f"#{card.n}: {card.error}" for card in failed_cards)
        lines.append("They stay in the draft. Fix them with draft_edit and call draft_commit again, or remove them.")
    waiting = [card for card in draft.cards if card.n not in wanted]
    if waiting:
        lines.append(f"Not committed yet, still in draft {draft_id}: {_numbers(waiting)}.")
    if not draft.cards:
        lines.append(f"Draft {draft_id} is finished and was deleted.")
    return "\n".join(lines)
