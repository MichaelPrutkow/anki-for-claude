---
name: exam-prep
description: Turns a whole course (lecture PDFs, exercise sheets, past exams, transcripts) into a prioritised Anki deck in stages - source analysis, a blueprint the user approves, card writing, pictures, audit and review. Use when the user wants cards for an entire exam or course from several sources at once.
---

# Exam preparation pipeline

Work in a run folder `anki-run/<date>/` inside the current project or workspace. Every step reads and writes files there; keep only short summaries in the conversation.

## 1. Intake
Ask once for anything missing: target deck, list of sources, exam date, rough card budget, language.

## 2. Analyse the sources
For every source start one `anki:source-analyst` agent in parallel, each with: the source path, the run folder, and the output file `inventory/<source-name>.md`. Without agents, analyse the sources yourself one by one into the same files.

## 3. Blueprint
Merge the inventories into `blueprint.md`, one row per topic:
`topic | priority (from past exams) | card types | picture needed | est. cards | already in deck`.
Check existing cards with `search_notes` to avoid duplicates. Show the blueprint as a short table and **wait for the user's approval**. This is the cheapest moment to change direction.

## 4. Write
Create the draft once with `draft_add` (title = course name). Then start one `anki:card-writer` agent per topic cluster (at most 5 in parallel), each with the draft id, its blueprint rows and the inventory files. Writers note picture needs in `visual-requests.md`. Then start one `anki:visual-designer` agent for `visual-requests.md`.

## 5. Audit
Start one `anki:card-auditor` agent with the draft id. It writes `audit.md`. Fix real problems with `draft_edit`; ignore false alarms.

## 6. Review and commit
`review` opens the preview and waits; accepted cards are added right away. Apply the user's notes with `draft_edit` and call `review` again until none are left. Finish with `sync`.
