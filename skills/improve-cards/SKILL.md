---
name: improve-cards
description: Works on the user's existing Anki cards - searches the collection, finds the cards they struggle with from their review history (again rate, lapses, FSRS difficulty, leeches, red flags), works out why each one fails and fixes it without losing its review history, deletes cards and undoes earlier changes. Use when the user asks what is in their collection, wants cards corrected, improved, cleaned up or removed, asks which cards are hard for them, or wants to undo something this plugin did.
---

# Improving existing cards

If `overview` and the other anki tools are not among your tools, call `get_device_info` first (search for it if it is not loaded): in the Claude app, that connects the tools on the user's computer to the chat. Then search for the anki tools again. Only if they are still missing, follow the `check-setup` skill.

## Finding cards

`search_notes` takes Anki's search syntax, and the query has to follow it exactly:

| Syntax | Meaning |
| --- | --- |
| `dog cat` | both words (a space means AND) |
| `dog or cat` | either word |
| `-cat` | without cat |
| `dog (cat or mouse)` | grouping |
| `"a dog"` | exact phrase; also needed for spaces in names: `deck:"French Words"` |
| `d*g` | wildcard: dog, dug, dg |
| `deck:Name`, `deck:Name::Sub` | a deck, including its subdecks |
| `tag:Name`, `tag:none` | a tag; tags are hierarchical, `tag:mcp::batch::*` matches every batch |
| `note:Basic` | a note type |
| `Front:dog` | the whole field is exactly "dog"; `Front:*dog*` finds it anywhere in the field |
| `Front:` / `Front:_*` | field empty / not empty |
| `nid:123,456` | notes by id |
| `is:new`, `is:due`, `is:learn`, `is:review`, `is:suspended` | card state |
| `prop:lapses>3`, `prop:ivl>=21` | numeric card properties |
| `rated:7:1` | answered "again" in the last 7 days |
| `added:7`, `edited:7` | added or edited in the last 7 days |
| `flag:1` | red flag |
| `\*`, `\_`, `\"`, `\:` | a literal `*`, `_`, `"` or `:` |

Cards created by this plugin have the tag `mcp::created`, and each commit adds `mcp::batch::<id>`.

No hits usually means the query is malformed, not that nothing matches.

## Finding the cards that do not work

1. Call `sync`, so reviews from the phone count. If it fails, go on without it.
2. Call `stats`, with `scope` set to the deck the user cares about (for example `deck:"Analysis 2"`).
3. For each weak note, read its fields (`search_notes` with `nid:<id>` and a higher `max_chars` shows all of it) and pick the most likely cause:

| Signal | Likely cause | Fix |
| --- | --- | --- |
| LONG_ANSWER, LIST_LIKE, MANY_CLOZES | the card asks for several facts | split it: rewrite the card into the first part and add the others as new cards |
| high again rate, short answer | the question is ambiguous, or a similar card interferes | add the qualifier that pins the answer down |
| SLOW | the answer is worked out, not recalled | add an example card or a picture (`visuals` skill) |
| LEECH, many lapses | the concept is not understood | add a prerequisite card or a small worked example |
| FLAGGED | the user marked it while studying | the strongest signal; read the card carefully |
| none of the above | the material is hard | leave it and say so |

4. Propose the fixes in the chat, note by note: what is wrong and the new text. New cards from splits, examples and prerequisites go into one draft with `draft_add`, written by the rules of the `create-cards` skill.
5. Change nothing until the user approves. Then apply the approved rewrites with `update_notes`, add the approved new cards with `draft_commit`, and report the batch ids.

## Changing cards

- `update_notes` changes fields and keeps the review history. Prefer it to deleting and adding a new card.
- Send only the fields that change, each with its full new content.
- Notes without the tag `mcp::created` were written by the user. Ask before changing them, then call `update_notes` again with `force=true`.
- The formatting rules of the `create-cards` skill apply to every field you write.
- To add a picture to an existing card, make it with the tools from the `visuals` skill and put its `<img>` tag into the field.

## Deleting

Delete a card only when it should not exist at all, and ask the user first. `delete_notes` removes only notes this plugin created, takes their review history with them and cannot be undone.

## Undoing

- `draft_commit` and `update_notes` return a batch id. `undo` with that id deletes the notes a commit added, or restores the fields an update changed.
- A note the user edited since is left alone and reported.
- Deleting cannot be undone.
