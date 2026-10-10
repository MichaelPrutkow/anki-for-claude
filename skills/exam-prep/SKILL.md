---
name: exam-prep
description: Turns a whole course (lecture PDFs, exercise sheets, past exams, transcripts) into a prioritised Anki deck in stages - source analysis, a blueprint the user approves, card writing, pictures, an audit, and approval in the chat. Use when the user wants cards for an entire exam or course from several sources at once.
---

# Exam preparation

Work in a run folder `anki-run/<date>/` in the current project. Every step reads and writes files there; keep only short summaries in the conversation. Where agents are not available, do each step yourself, one source or one topic at a time.

1. **Intake.** Ask once for whatever is missing: target deck, the sources, exam date, a rough card budget, language.
2. **Sources.** Start one `anki:source-analyst` agent per source, in parallel, each with the source path and its output file `inventory/<source-name>.md`.
3. **Blueprint.** Merge the inventories into `blueprint.md`, one row per topic: `topic | priority (from past exams) | card types | picture needed | est. cards | already in deck`. Check existing cards with `search_notes`. Show the blueprint as a short table and **wait for the user's approval**: this is the cheapest moment to change direction.
4. **Cards.** Start one `anki:card-writer` agent per topic cluster, at most five at once, each with the deck, the note type, its blueprint rows and the inventory files. Each writer puts its cards into a draft of its own, titled with its topics, and reports the draft id. Writers list picture needs in `visual-requests.md`.
5. **Pictures.** Start one `anki:visual-designer` agent for `visual-requests.md`.
6. **Audit.** Start one `anki:card-auditor` agent with the draft ids. It writes `audit.md`. Fix the real problems with `draft_edit` and ignore false alarms.
7. **Approval.** Go through the drafts with the user one at a time: show the cards with `draft_show`, word for word, apply changes with `draft_edit`, and add the approved cards with `draft_commit`. If the user studies on a phone, finish with `sync`.
