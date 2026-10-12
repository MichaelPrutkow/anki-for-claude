![Anki for Claude logo](.claude-plugin/icon.svg)

# Anki for Claude

Claude writes your Anki cards. From lecture slides, PDFs, YouTube videos or whatever's in the chat.

[![Stars](https://img.shields.io/github/stars/MichaelPrutkow/anki-for-claude?style=flat&color=yellow)](https://github.com/MichaelPrutkow/anki-for-claude/stargazers)
[![MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Claude plugin](https://img.shields.io/badge/Claude-plugin-D97757)
![Anki 23.10+](https://img.shields.io/badge/Anki-23.10%2B-orange)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)

A Claude plugin that runs locally against your Anki. It reads your material, writes the cards,
draws the diagrams and makes native image occlusion cards. Later it goes through your review
history and fixes the cards you keep failing.

Nothing hits your collection until you say yes.

> Unofficial. Not affiliated with Ankitects Pty Ltd.

## Demo

YouTube video + lecture slides in:

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

Cards out, clicked through in Anki:

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## What's different

Most AI flashcard tools turn a PDF into 300 cards you'll never review. This one writes fewer
cards, from your own material, and keeps fixing the ones that don't stick.

- Cards follow actual rules. One fact per card, no yes/no questions, no lists (they become
  clozes), and a theorem gets separate cards for statement, hypotheses and key idea. The wording
  rules come from [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
  so the cards don't read like an LLM wrote them.
- You see every card word for word before it's added. Tell Claude what to change, approve, done.
- Real pictures. Graphs, trees and automata via Graphviz. Figures cut out of your PDF by their
  caption (*"Fig. 3.2"*). Plots via matplotlib. Native image occlusion, with masks placed from the
  PDF's text layer or the graph's node positions instead of guessed from pixels.
- Your review history decides what gets fixed. `stats` ranks notes by again rate, lapses, FSRS
  difficulty, answer time, leeches and red flags. Flag a card red on your phone and Claude picks
  it up next time.
- A whole course in one go. `/anki:exam-prep` gives every source its own agent, so 200 pages of
  slides never touch your context. You approve a topic blueprint weighted by past exams, the cards
  get written in parallel, audited, and approved topic by topic.
- Everything is undoable. Every commit and edit returns a batch id, `undo` reverts it.

## Setup

You need:

- **Anki 23.10+** with [AnkiConnect](https://ankiweb.net/shared/info/2055492159):
  *Tools → Add-ons → Get Add-ons*, code `2055492159`, restart Anki.
- **[uv](https://docs.astral.sh/uv/)**: `brew install uv`, or see the
  [install guide](https://docs.astral.sh/uv/getting-started/installation/).
- **Claude Code** or the **Claude desktop app**.
- Optional: **[Graphviz](https://graphviz.org/download/)** for graphs, trees and automata
  (`brew install graphviz`).

**Claude Code**

```
/plugin marketplace add MichaelPrutkow/anki-for-claude
/plugin install anki@michaelprutkow
```

**Desktop app:** *Customize → Plugins → Add → Add marketplace*, enter
`MichaelPrutkow/anki-for-claude`, install **Anki Flashcards**.

Then say *"check my Anki setup"*. First start takes a few seconds while uv pulls the dependencies.

In the desktop app, add a folder to the chat before your first message (your lecture folder, for
example). The server runs on your machine, and without a folder the chat doesn't reliably reach
it. Claude needs the folder for your PDFs anyway.

No config. It uses AnkiConnect on `http://127.0.0.1:8765` and launches Anki if it's closed
(macOS).

## Usage

*"Make flashcards from this lecture for my deck Analysis 2."*

Claude drafts, you review in the chat, it commits when you say yes. That's the loop.

| Skill | For |
| --- | --- |
| `/anki:create-cards` | Cards from any material |
| `/anki:visuals` | Graphs, PDF figures, plots, image occlusion |
| `/anki:improve-cards` | Find and fix weak cards, search, delete, undo |
| `/anki:exam-prep` | A whole course (slides, exercise sheets, past exams) into a prioritised deck |
| `/anki:check-setup` | Check Anki, AnkiConnect, the image occlusion note type and Graphviz |

Claude picks the skill itself. The slash commands are there to force one.

- Want it on autopilot? Schedule *"improve my weakest cards in Analysis 2"* as a task in the
  desktop app.
- PDFs and images are opened by their full path. A file you attach in the desktop app isn't on
  disk yet, so Claude saves it first or asks you for the path.

## Under the hood

- Drafts are saved to disk, so they survive restarts. Every card is checked against your note
  types and for duplicates before you see it.
- The tools catch the usual formatting slips: LaTeX outside `\( \)`, `$...$` math Anki won't
  render, a `<` inside a formula, braces that close a cloze too early.
- Pictures land in `~/Pictures/Anki for Claude`, so you can look at them while reviewing. Image
  occlusion cards also get a `<name>-masks.png` that shows the masks.
- The card rules live in a skill, so they cost nothing in chats that aren't about Anki.
- Tool output is short plain text. Long YouTube videos come back as a timestamped outline, and
  Claude only pulls the parts it needs.
- `undo` skips cards you edited yourself in the meantime. Cards the plugin didn't create can't be
  deleted by it and are only edited after you agree.

## Tools

| Tool | Access | What it does |
| --- | --- | --- |
| `overview` | read | Decks, card counts, note types and their exact field names |
| `search_notes` | read | Search with Anki's query syntax, one line per note |
| `draft_add` | draft | Check cards and add them to a draft |
| `draft_add_occlusion` | draft | Image occlusion note, masks by label or region |
| `draft_edit` | draft | Change or remove draft cards by number |
| `draft_show` | read | Show a draft, or list the open ones |
| `stage_image` | draft | Save an image, a PDF figure or part of a PDF page for a card |
| `pdf_figures` | read | Find figures and their captions in a PDF |
| `render_graph` | draft | Draw a graph, tree or automaton with Graphviz |
| `stats` | read | Card counts, retention and the cards you struggle with |
| `youtube_transcript` | web | Transcript or outline of a YouTube video |
| `draft_commit` | **write** | Add the approved cards, create missing decks |
| `update_notes` | **write** | Fix cards without losing their review history |
| `undo` | **write** | Revert a commit or an edit by its batch id |
| `delete_notes` | **write** | Delete notes this plugin created |
| `sync` | **write** | Sync with AnkiWeb so the cards reach your phone |

*Draft* tools only touch drafts and pictures, never your collection.

## Safety

> **Back up first.** This writes to your real collection: *File → Export → Anki Collection Package*.

It won't:

- add cards you didn't approve in the chat
- delete a note it didn't create
- edit a note it didn't create without asking
- open anything except images and PDFs

## Privacy

Runs on your machine. Nothing is sent to me.

- **Anki:** AnkiConnect on `127.0.0.1`.
- **Stored locally:** drafts (deleted after 14 days untouched) and the undo journal in
  `~/.anki-mcp`, pictures in `~/Pictures/Anki for Claude` until you delete them.
- **Only when you ask:** the video id goes to YouTube for a transcript, an image URL you want on a
  card gets fetched, and Anki syncs your collection to AnkiWeb.
- **Programs it starts:** Anki if it's closed (macOS), and Graphviz's `dot` for graphs.

Full policy: [PRIVACY.md](PRIVACY.md).

## Known limits

- An open dialog in Anki blocks AnkiConnect. Every call times out until you close it.
- Claude Code and Cowork only. The server runs locally, so a plain chat (including claude.ai in
  the browser) can't reach it.
- Anki auto-starts on macOS only. On Windows and Linux, open it yourself.
- Duplicates work like in Anki: only the first field is compared.
- Deleting can't be undone. Fix a card instead.
- Image occlusion is rectangles only. Masks by label need a PDF text layer or a Graphviz graph,
  otherwise Claude places them by region.
- FSRS difficulty is read from the review log, because AnkiConnect doesn't expose FSRS memory
  states. Good enough for ranking.

## Other MCP clients

The MCP server works without the plugin too, e.g. in Cursor. You get the tools, not the skills
and agents.

```bash
git clone https://github.com/MichaelPrutkow/anki-for-claude.git
cd anki-for-claude
uv sync --no-dev
```

```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/anki-for-claude", "--no-dev", "-m", "anki_mcp"]
    }
  }
}
```

## Development

```bash
uv sync
uv run pytest            # tools against an in-memory fake of AnkiConnect, no Anki needed
claude plugin eval .     # Claude with the plugin vs. without it, against mocked tools
claude --plugin-dir .    # try it in Claude Code
```

## Credits

- [AnkiConnect](https://git.sr.ht/~foosoft/anki-connect) by foosoft
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) by jdepoix
- [pdfplumber](https://github.com/jsvine/pdfplumber), [Pillow](https://python-pillow.org) and
  [Graphviz](https://graphviz.org) for the pictures
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
