---
name: maintain
description: Finds, inspects, fixes and cleans up existing Anki notes with the anki MCP tools: Anki search syntax, updating cards without losing review history, deleting, and undoing batches. Use when the user wants to search, review, correct, rewrite or remove existing cards, or asks what is in their collection.
---

# Maintaining existing cards

## Searching
`search_notes` takes Anki's search syntax. The query <HIER DEN TEXT VON ANKI_SEARCH_RULES EINFÜGEN>

A result of 0 hits usually means the query is malformed, not that the collection is empty.

## Changing cards
- Use `update_notes` for wrong or weak cards. It keeps the review history; deleting throws it away.
- Send only the fields that change.
- Notes without the tag `mcp::created` were written by the user. Ask before changing them, then call again with `force=True`.
- Only delete a card when it should not exist at all. `delete_notes` only removes notes created by this plugin and cannot be undone.

## Undo
- Every `draft_commit` and every `update_notes` call returns a batch id.
- `undo(batch_id)` deletes the cards a commit added, or restores the fields an update changed. A note that was edited since is left alone and reported.
- Batches from the old version (tag `mcp::batch::<id>`, no journal) are undone by deleting every note with that tag.