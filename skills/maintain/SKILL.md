---
name: maintain
description: Finds, inspects, fixes and cleans up existing Anki notes with the anki MCP tools: Anki search syntax, updating cards without losing review history, deleting, and undoing batches. Use when the user wants to search, review, correct, rewrite or remove existing cards, or asks what is in their collection.
---

# Maintaining existing cards

## Searching
`search_notes` takes Anki's search syntax. The query must follow it exactly:

| Syntax | Meaning |
| --- | --- |
| `dog cat` | both words (space = AND) |
| `dog or cat` | either word |
| `-cat` | without cat |
| `dog (cat or mouse)` | grouping |
| `"a dog"` | exact phrase, also needed for spaces in names: `deck:"French Words"` |
| `d*g` | wildcard: dog, dug, dg |
| `deck:Name`, `deck:Name::Sub` | deck, including its subdecks |
| `tag:Name`, `tag:none` | tag; tags are hierarchical, `tag:mcp::batch::*` matches all subtags |
| `note:Basic` | note type |
| `Front:dog` | field search is an EXACT match of the whole field; use `Front:*dog*` for a part |
| `Front:` / `Front:_*` | field empty / not empty |
| `nid:123,456` | notes by id |
| `is:new`, `is:due`, `is:learn`, `is:review`, `is:suspended` | card state |
| `prop:lapses>3`, `prop:ivl>=21` | numeric card properties |
| `rated:7:1` | answered "again" in the last 7 days |
| `added:7`, `edited:7` | added or edited in the last 7 days |
| `flag:1` | red flag |
| `\*`, `\_`, `\"`, `\:` | a literal `*`, `_`, `"` or `:` |

Cards created by this plugin carry `tag:mcp::created`, each commit `tag:mcp::batch::<id>`.

A result of 0 hits usually means the query is malformed, not that the collection is empty.

## Changing cards
- Use `update_notes` for wrong or weak cards. It keeps the review history; deleting throws it away.
- Send only the fields that change.
- Notes without the tag `mcp::created` were written by the user. Ask before changing them, then call again with `force=True`.
- For weak cards (high again rate, leeches, red flags) use the `weekly-review` skill.
- Only delete a card when it should not exist at all. `delete_notes` only removes notes created by this plugin and cannot be undone.

## Undo
- Every `review` that adds cards and every `update_notes` call returns a batch id.
- `undo(batch_id)` deletes the cards a commit added, or restores the fields an update changed. A note that was edited since is left alone and reported.
- Batches from the old version (tag `mcp::batch::<id>`, no journal) are undone by deleting every note with that tag.