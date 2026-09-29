import uuid
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

import anki_mcp.constants as myConsts
from anki_mcp.anki import invoke
from anki_mcp.models import (
    AddResult,
    NoteInput,
    SearchResult,
    TimeInterval,
    YouTubeVideoData,
)
from anki_mcp.youtube_api import (
    extract_full_transcript,
    extract_outline,
    extract_Segments,
    get_youtube_data,
)

mcp = MCPServer(
    "anki", version=version("anki-mcp-server"), instructions=myConsts.INSTRUCTIONS
)


@mcp.tool(title="List Decks", annotations=myConsts.READ_ONLY)
def list_decks() -> list[str]:
    """
    Returns:
        List of all Decknames
    """
    return invoke("deckNames")


@mcp.tool(title="Create a new Deck", annotations=myConsts.ADDS_IF_MISSING)
def create_deck(
    name: Annotated[str, Field(description="Deck, '::' creates Subdecks")],
) -> int:
    """
    Create a new empty deck. Will not overwrite a deck that exists with the same name.

    Returns:
        DeckID of the new deck
    """
    return invoke("createDeck", deck=name)


@mcp.tool(title="Describe note type", annotations=myConsts.READ_ONLY)
def describe_note_type(name: str | None = None) -> list[str]:
    """
    Gets the complete list of model names for the current user, if the name is None.
    Otherwise gets the complete list of field names for the provided model name.

    Args:
        name: modelName

    Returns:
        List of model names for the current user or list of field names for the provided model name.
    """
    if name is None:
        return invoke("modelNames")
    return invoke("modelFieldNames", modelName=name)


@mcp.tool(title="Search for Notes", annotations=myConsts.READ_ONLY)
def search_notes(
    query: Annotated[str, Field(description=myConsts.ANKI_SEARCH_RULES)],
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    with_fields: bool = False,
) -> SearchResult:
    """
    Finds notes in the Anki collection.

    - total_found is the number of matches for the whole query
    - note_ids is capped at limit.

    A total_found of 0 usually means the query was malformed
    rather than that the collection is empty.

    Set with_field=True to also get field contents, tags and note type. This is
    considerably more expensive, so leave it off unless the content is needed
    """
    ids: list[int] = invoke("findNotes", query=query)
    selected = ids[:limit]

    notes: list[dict[str, Any]] = []
    if with_fields and selected:
        # notes = invoke("notesInfo", notes=selected)
        for n in invoke("notesInfo", notes=selected):
            notes.append(
                {
                    "id": n["noteId"],
                    "type": n["modelName"],
                    "tags": n["tags"],
                    "fields": {k: v["value"][:300] for k, v in n["fields"].items()},
                }
            )

    return SearchResult(
        query=query, total_found=len(ids), note_ids=selected, notes=notes
    )


active_drafts: dict[str, dict[str, Any]] = {}


@mcp.tool(title="Create Draft Batch", annotations=myConsts.DRAFT_ONLY)
def create_draft_batch(
    deck: str,
    note_type: str,
    notes: Annotated[
        list[NoteInput] | None, Field(default=None, min_length=1, max_length=50)
    ] = None,
    tags: list[str] | None = None,
    allow_duplicate: bool = False,
) -> str:
    """
    IMPORTANT: If you have not called 'get_card_rules' in this conversation, do that before drafting.

    Start a new draft batch and optionally fill it in the same call.

    A draft is validated but NOT written to Anki. It exists only in this server's
    memory and disapears when the server restarts. Pas the notes right here unless you need
    to build the batch across several calls.

    Returns the draft_id. Pass it to 'add_to_draft' to append more notes, or to 'commit_draft'
    to write everything to Anki.

    Fails if the deck or the note type does not exist.

    Drafts are deleted from servers memory after 30 Minutes, if not used.
    """

    decks = list_decks()
    if deck not in decks:
        raise Exception(
            f"The deck '{deck}' does not exist! \nOnly these Decks currently exist: {list(decks)}"
        )

    models: list[str] = invoke("modelNames")
    if note_type not in models:
        raise Exception(f"Note type '{note_type}' not found. Available: {models}")

    for id, draft in list(active_drafts.items()):
        time_diff: timedelta = datetime.now() - draft["created_at"]
        if time_diff.total_seconds() > 1800:
            del active_drafts[id]

    draft_id = f"draft_{uuid.uuid4().hex[:8]}"
    active_drafts[draft_id] = {
        "created_at": datetime.now(),
        "deck": deck,
        "note_type": note_type,
        "shared_tags": tags or [],
        "allow_duplicate": allow_duplicate,
        "notes": [],
    }
    if notes:
        add_to_draft(draft_id=draft_id, notes=notes)
    return draft_id


@mcp.tool(title="Add Notes to Draft", annotations=myConsts.DRAFT_ONLY)
def add_to_draft(
    draft_id: str,
    notes: Annotated[list[NoteInput], Field(min_length=1, max_length=50)],
) -> str:
    """
    Append notes to an existing draft. Nothing is written to Anki.

    Every note is validated against the note type's field names and checked for duplicates
    before it enters the draft. If any note fails, NONE are appended and the eror names every
    problem at once, so you can fix them in one go.

    Calling this twice with the same notes appends them twice. Use it to build a large batch
    across multiple calls, not to retry a failed call.
    """

    if draft_id not in active_drafts:
        raise Exception(
            f"Draft '{draft_id}' does not exist. Call 'create_draft_batch' to create a new one"
        )

    draft = active_drafts[draft_id]

    note_type = draft["note_type"]
    valid: list[str] = invoke("modelFieldNames", modelName=note_type)
    valid_lower = {v.lower() for v in valid}
    unknown: dict[str, list[int]] = {}
    for i, n in enumerate(notes):
        for field in n.fields:
            if field.lower() not in valid_lower:
                unknown.setdefault(field, []).append(i)
    if unknown:
        msg1 = ", ".join(
            [f"Unknown field '{key}' in notes '{val}' " for key, val in unknown.items()]
        )
        raise Exception(f"{msg1} \nThe only valid fields currently are: {valid}")

    test_anki_notes = [
        {
            "deckName": draft["deck"],
            "modelName": draft["note_type"],
            "fields": n.fields,
            "options": {
                "allowDuplicate": draft["allow_duplicate"],
            },
            "tags": [*draft["shared_tags"], *n.tags],  # add note specific tags
        }
        for n in notes
    ]

    first = valid[0]
    dupes: list[int] = []
    seen = [
        {k.lower(): v for k, v in an["fields"].items()}.get(first.lower(), "")
        .strip()
        .lower()
        for an in draft["notes"]
    ]

    for i, an in enumerate(test_anki_notes):
        key = (
            {k.lower(): v for k, v in an["fields"].items()}.get(first.lower(), "")
            .strip()
            .lower()
        )
        if key in seen:
            dupes.append(i)
        seen.append(key)

    if dupes and not draft["allow_duplicate"]:
        raise Exception(
            f"Notes '{dupes}' are duplicates of other notes in this same draft. darft_ID: {draft_id}. "
            f"\nAnky only compares the field '{first}. Nothing was added.'"
        )

    status_and_details = invoke("canAddNotesWithErrorDetail", notes=test_anki_notes)
    errors: dict[str, list[int]] = {}
    for i, detail in enumerate(status_and_details):
        if detail["canAdd"]:
            continue
        errors.setdefault(detail["error"], []).append(i)

    if errors:
        msg2 = ", ".join(
            [f"Error '{key}' in notes '{val}' " for key, val in errors.items()]
        )
        raise Exception(
            f"{msg2} \nPlease try fixing these Errors, the Errormessages may contain Hints"
        )

    draft["notes"].extend(test_anki_notes)

    count = len(draft["notes"])
    return f"Added {len(notes)} Notes. Draft '{draft_id}' now containts {count} Notes. Call 'commit_draft' to add Notes to the Users Deck"


@mcp.tool(title="Commit Draft", annotations=myConsts.ADDS_NEW)
def commit_draft(draft_id: str) -> AddResult:
    """
    Write a draft to Anki. This is the only tool in this workflow that changes the collection.

    Do not call this on your own initiative. Present the drafted cards to the user first and wait for
    their approval.

    Every note gets tagged 'mcp::batch::<batch_id>'. The returned batch_id can be passed to 'undo_batch'
    to remove the entire batch again.
    """

    if draft_id not in active_drafts:
        raise Exception(
            f"Draft '{draft_id}' does not exist. Call 'create_draft_batch' to create a new one."
        )

    draft = active_drafts[draft_id]
    anki_notes = draft["notes"]

    if not anki_notes:
        raise Exception(f"Draft {draft_id} is empty / does not contain any notes.")

    batch_id = uuid.uuid4().hex[:8]
    batch_tags = ["mcp::created", f"mcp::batch::{batch_id}"]

    payload = [{**an, "tags": [*an["tags"], *batch_tags]} for an in anki_notes]
    result = invoke(
        "multi", actions=[{"action": "addNote", "params": {"note": n}} for n in payload]
    )

    note_ids = [r for r in result if isinstance(r, int)]
    failed_indices = [i for i, r in enumerate(result) if not isinstance(r, int)]

    draft["notes"] = [anki_notes[i] for i in failed_indices]
    if not draft["notes"]:
        del active_drafts[draft_id]

    return AddResult(
        batch_id=batch_id,
        note_count=len(note_ids),
        note_ids=note_ids,
        failed_indices=failed_indices,
    )


@mcp.tool(title="Delete generated Batch of Notes", annotations=myConsts.OVERWRITES)
def undo_batch(batch_id: str) -> int:
    """
    Delete a Batch of Notes, which you created.

    Returns number of deleted Nodes.
    """
    query: str = f"tag:mcp::batch::{batch_id}"
    ids: list[int] = invoke("findNotes", query=query)
    if ids:
        invoke("deleteNotes", notes=ids)
    return len(ids)


@mcp.tool(title="Delete individual notes", annotations=myConsts.OVERWRITES)
def delete_notes(
    note_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
) -> int:
    """
    Delete individual notes by ID. Only notes created by this server can be deleted,
    identified by the 'mcp::created' tag.

    Prefer 'update_note_fields' when a card is merely wrong. Editing keeps the card's
    review history, deleting throws it away. Only delete when the card should not exist at all.

    Note IDs come from 'commit_draft' result or from 'search_notes'.
    Returns the number of notes deleted.
    """
    info = invoke("notesInfo", notes=note_ids)

    missing_ids = [note_ids[i] for i, note in enumerate(info) if not note]
    if missing_ids:
        raise Exception(f"Notes at following IDs do not exist: {missing_ids}")

    prohibited_ids = [
        note_ids[i]
        for i, note in enumerate(info)
        if "mcp::created" not in note.get("tags", [])
    ]
    if prohibited_ids:
        raise Exception(
            f"Access denied: the following notes were not created by this server: {prohibited_ids}"
            "\nOnly notes tagged 'mcp::created' can be deleted."
        )

    invoke("deleteNotes", notes=note_ids)
    return len(note_ids)


@mcp.tool(title="Update Fields of specific Note", annotations=myConsts.OVERWRITES)
def update_note_fields(
    note_id: int, fields: dict[str, str], force: bool = False
) -> dict[str, str]:
    """
    Modify the fields of an existing note.
    Returns old (pre-change) fields of the given Note.

    If need to undo changes, just update call 'update_note_fields'
    with same node_id, and return value of initial update.
    """
    info = invoke("notesInfo", notes=[note_id])
    if not info or not info[0]:
        raise Exception(f"No note with id {note_id}")

    if "mcp::created" not in info[0].get("tags", []) and not force:
        raise Exception(
            f"Note {note_id} was not created by this server. Changing it overwrites the user's own work"
            "\nIf unsure: Ask the user first, then call again with force=True"
        )

    before = {k: v["value"] for k, v in info[0]["fields"].items()}

    valid: list[str] = invoke("modelFieldNames", modelName=info[0]["modelName"])
    valid_lower = {v.lower() for v in valid}
    unknown = [k for k in fields if k.lower() not in valid_lower]
    if unknown:
        raise Exception(
            f"Unknown fields '{unknown}'. \nThe only valid fiels are: {valid}"
        )

    invoke("updateNoteFields", note={"id": note_id, "fields": fields})
    return before


active_videos: dict[tuple[str, str], YouTubeVideoData] = {}


@mcp.tool(title="Read Transcript from YouTube Video", annotations=myConsts.READ_ONLY)
def extract_youtube_video_transcript(
    url: str,
    intervals: Annotated[
        list[TimeInterval] | None,
        Field(
            default=None,
            description="Pick important Parts from Video",
            min_length=1,
            max_length=30,
        ),
    ] = None,
    targetlanguage: Annotated[
        str,
        Field(
            default="en", description="Specify target language if needed", min_length=1
        ),
    ] = "en",
) -> str:
    """
    Extracts transcript from a YouTube video. If the video is long, it returns an outline.
    You MUST then call this tool again with SAME url and specific 'intervals' to read the relevant
    parts before creating Anki cards with the Context created.

    If you call this Tool without Intervals, you will receive the complete Transcript, unless
    of course the video is too long - in which case you will receive an Outline and should call again.
    """

    vid = active_videos.get((url, targetlanguage))
    if vid is None:
        vid = get_youtube_data(url, targetlanguage)
        if len(active_videos) >= 8:
            active_videos.pop(next(iter(active_videos)))
        active_videos[url, targetlanguage] = vid

    if intervals:
        return extract_Segments(vid, intervals)

    full = extract_full_transcript(vid)

    if len(full) > 8000:
        return (
            "The transcript is too long. Pick the relevant parts from the outline and call"
            f"this tool again INCLUDING 'intervals'. \nOutline:\n{extract_outline(vid)}"
        )

    return full


@mcp.tool(title="Sync with AnkiWeb", annotations=myConsts.READ_ONLY)
def sync() -> str:
    """Pusheds the collection to AnkiWeb so the new cards reach he users's phone."""
    invoke("sync")
    return "Sync started"


@mcp.tool(title="Card design rules", annotations=myConsts.READ_ONLY)
def get_card_rules() -> str:
    """
    Returns the rules for writing Anki cards: what is worth remembering at all, how
    to handle LaTex and cloze syntax, and the draft/commit workflow.
    Call this once before writing any cards.
    """
    return myConsts.CARD_RULES


# NOTE: Deleted Prompt - not used nor useful

if __name__ == "__main__":
    mcp.run()
