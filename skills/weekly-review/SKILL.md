---
name: weekly-review
description: Weekly maintenance of the user's Anki collection - finds the cards they struggle with (again rate, lapses, FSRS difficulty, leeches, red flags), diagnoses why, and prepares rewrites, splits and new cards for approval. Use when the user asks to review, clean up or improve weak cards, or when it runs as a scheduled task with the word "unattended".
---

# Weekly review

## Mode
If the request contains "unattended", nobody is watching: never call `review`, `update_notes`, `delete_notes` or `undo`. Only read, draft and report.

## Steps
1. `sync`, so the reviews from the phone are included. If it fails, continue.
2. `stats` (scope from the user, else the whole collection).
3. For each weak note, read its fields (`search_notes` with `nid:<id>` if you need more) and pick one cause:

| Signal | Likely cause | Fix |
| --- | --- | --- |
| LONG_ANSWER, LIST_LIKE, MANY_CLOZES | the card asks for several facts | split into atomic cards, suspend nothing yet |
| high again rate, short answer | ambiguous question or interference with a similar card | add the qualifier that pins the answer down |
| SLOW | answer is reconstructed, not recalled | add an example card or a picture (`visuals` skill) |
| LEECH, many lapses | concept not understood | add a prerequisite card or a worked mini example |
| FLAGGED | the user marked it while learning | treat as the strongest signal; read it carefully |
| good card, still hard | genuinely hard material | leave it, say so |

4. Prepare the fixes:
   - Changes to existing cards: a list of proposed `update_notes` calls (note id, field, new text, one-line reason). Do not apply them yet.
   - New cards: one draft via `draft_add`, title `Weekly review <date>`, following the `cards` skill.
5. Report in at most 15 lines: retention, the top problems, the draft id, the proposed updates.
6. Interactive mode only: show the proposed fixes in the chat, ask which updates to apply, then call `update_notes` for the approved ones and report the batch ids.
