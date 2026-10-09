
<h1 align="center">Anki for Claude</h1>

<p align="center">
  <b>Turn lecture material, YouTube videos or any other context from your chat into Anki cards.</b>
</p>

<p align="center">
  <a href="https://github.com/MichaelPrutkow/anki-for-claude/stargazers"><img src="https://img.shields.io/github/stars/MichaelPrutkow/anki-for-claude?style=flat&color=yellow" alt="Stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/Claude-plugin-D97757" alt="Claude plugin">
  <img src="https://img.shields.io/badge/Anki-23.10%2B-orange" alt="Anki 23.10+">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB" alt="Python 3.10+">
</p>

A Claude plugin that reads your lecture material, transcribes YouTube videos and writes Anki
flashcards from it, including pictures and native image occlusion cards. It talks to your
running Anki through [AnkiConnect](https://ankiweb.net/shared/info/2055492159).

Most LLM-to-Anki tools only take text, produce cards and write them. That produces a lot
of cards and not much learning. This plugin connects Claude directly to Anki and has it write
cards that are actually worth reviewing, grounded in your own material, and then uses your
review history to find and fix the cards that do not work.

> Unofficial. Not affiliated with or endorsed by Ankitects Pty Ltd.

## Demo

**Asking Claude for cards from a YouTube video combined with lecture slides**

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

**Output, clicked through in Anki**

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## Requirements

- **Anki 23.10 or newer**, with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
  add-on (code `2055492159`). Install it under ***Tools → Add-ons → Get Add-ons***, then restart Anki.
- **[uv](https://docs.astral.sh/uv/)**, which starts the plugin's Python server:
  `brew install uv` on macOS, or `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Claude Code** or the **Claude desktop app**.
- Optional: **[Graphviz](https://graphviz.org/download/)** for drawn graphs, trees and automata
  (`brew install graphviz`).

## Install

### Claude Code

```
/plugin marketplace add MichaelPrutkow/anki-for-claude
/plugin install anki@michaelprutkow
```

### Claude desktop app

***Customize → Plugins → Add → Add marketplace***, enter `MichaelPrutkow/anki-for-claude`,
then install **Anki Flashcards**.

The first start takes a few seconds while uv installs the dependencies. Ask Claude to
*"check my Anki setup"* to make sure everything is in place.

### Settings

| Option | Default | |
| --- | --- | --- |
| AnkiConnect URL | `http://127.0.0.1:8765` | Only change this if you moved AnkiConnect |
| Start Anki automatically | on | Opens Anki when it is not running (macOS) |
| Materials folder | empty | Folder with your lecture PDFs and images. File names are looked up here, so you can say *"figure 3 in vorlesung5.pdf"*. |

### Upgrading from 1.x

Remove the old Anki extension (`.mcpb`) from Claude Desktop, otherwise Claude sees two sets of
Anki tools. Cards created with 1.x keep working: they are still tagged `mcp::created`, and their
batches can still be undone.

### Any other MCP client, from source

The MCP server also runs without the plugin, for example in Cursor. You only get the tools then,
not the skills and agents.

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

## Usage

Just ask: *"Make flashcards from this lecture for my deck Analysis 2."* Claude loads the card
rules, drafts the cards and opens a preview in your browser. Nothing is written before you
approve it.

| Skill | When it is used |
| --- | --- |
| `/anki:cards` | Writing cards from any material. Holds the card-design rules and the workflow. |
| `/anki:visuals` | Cards with pictures: Graphviz graphs, figures cut from PDFs, plots, image occlusion. |
| `/anki:maintain` | Searching, fixing, deleting and undoing existing cards. |
| `/anki:weekly-review` | Finds your weakest cards from your review history and prepares fixes. |
| `/anki:exam-prep` | Turns a whole course (slides, exercise sheets, past exams) into a prioritised deck. |
| `/anki:setup` | Checks Anki, AnkiConnect, the image occlusion note type and Graphviz. |

Claude picks the right skill on its own; the slash commands are there if you want to force one.

### Weekly review on autopilot

Schedule `/anki:weekly-review unattended` once a week, for example as a local scheduled task in
the Claude desktop app. In unattended mode it only reads and drafts: it never commits, edits or
deletes. The next morning, run `/anki:weekly-review` and go through the proposed fixes.

Mark a bad card with the red flag while you study on your phone. The review picks it up.

## Design decisions

### Nothing is written until you approve it

Cards go into a **draft** first. A draft is validated against your note type and checked for
duplicates. Only the cards you accept in the preview are written to your collection.

Drafts are saved on disk, so they survive restarts and closing the app. Notes on single cards
lead to edits of only those cards, instead of rewriting the whole batch.

### A real preview instead of cards in the chat

`review` opens the draft in your browser, one card at a time like Anki's own preview, rendered
with your note types: their templates and CSS, MathJax, cloze gaps, images and image occlusion
masks. Question on the left, answer on the right. Accept (✓), reject (✕) or leave a note for
Claude, then press *Commit*.

Claude waits for you in the same turn. Accepted cards go to Anki immediately, rejected ones are
dropped, and cards with a note are revised and shown again, without a new prompt from you.

Claude no longer writes every card a second time into the chat. That saves the most expensive
tokens of the whole workflow.

<details>
  <summary><h3> Click to view: Example of an in-chat draft (1.x)</h3></summary>
  <br>
  <img width="513" alt="image" src="https://github.com/user-attachments/assets/65a415b6-f8fd-4c58-8db5-ceb7c0adc09a" />
</details>

### If the exam shows a picture, the card shows a picture

- **Graphs, trees, automata** are drawn with Graphviz in one consistent style.
- **Figures from your PDFs** are found with their captions (*"Abb. 3.2"*) and cut out exactly,
  without screenshots.
- **Own plots** are drawn with matplotlib in a house style that stays readable on a phone.
- **Image occlusion**: Claude creates Anki's native image occlusion notes. Labels are located
  through the PDF's text layer or the graph's node positions, not guessed from pixels, so the
  masks sit exactly on *"Mitralklappe"*.

Only image and PDF files are read, and images reach Anki only when you accept the card.

### Your review history decides what to fix

`stats` ranks the notes you struggle with: again rate, lapses, FSRS difficulty, answer
time, leeches and red flags. Each one gets a reason (*answer too long, list-like, slow,
leech*), and the weekly review proposes the matching fix: split it, sharpen the question, add
a picture or a prerequisite card.

### Everything can be undone

Every review and every edit returns a batch id. `undo` with that id removes the cards a review
added, or restores the fields an edit changed. A card you edited yourself in the meantime is
left alone and reported.

Cards this plugin did not create carry no `mcp::created` tag, so they cannot be deleted or
edited by accident. Editing one requires an explicit `force=True` after asking you.

### Specific card rules, loaded only when needed

The card-design rules live in a skill. Claude only loads them when you actually ask for cards,
so they cost nothing in any other conversation. They are opinionated and specific:

- One fact per card. If the answer contains an "and", it is usually two cards.
- No yes/no questions. A coin flip is right half the time and retrieves nothing.
- Never a set or a list: those become separate cloze deletions.
- For a theorem: separate cards for the statement, the hypotheses, what breaks without them,
  and the key idea of the proof.
- Rules on phrasing, so the wording stays human instead of clanker-like, inspired by
  [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing).

<details>
  <summary><h3>Click to view: Example of the generated Anki cards</h3></summary>
  <br>
  <img width="700" alt="image" src="https://github.com/user-attachments/assets/d1c2b2d4-5ec1-4048-b8a8-94ab4bd81a61" />
</details>

### A whole course, with the right model for each step

`/anki:exam-prep` splits a course into stages. One `source-analyst` agent (Sonnet) per source
reads it in its own context, so 200 pages of slides never fill your conversation. You approve
a blueprint of topics weighted by past exams before any card is written. `card-writer` agents
then write the cards in parallel, a `visual-designer` (Opus) makes and checks the pictures, and
a `card-auditor` (Haiku) checks every card against the rules.

### One bad card does not kill the batch

Cards are written individually in a single request. If one collides with an existing card, the
others still land, and the failed one stays in the draft with the reason attached.

### Compact tool output

Tools return short plain-text lines instead of verbose JSON, and one `overview` call replaces
several lookups. Less of your context goes to bookkeeping, more to the cards.

### YouTube lectures without burning your context

`youtube_transcript` returns a timestamped outline for long videos instead of the full
transcript. Claude picks the intervals that matter and reads only those.

## Tools

| Tool | Access | What it does |
| --- | --- | --- |
| `overview` | read | Decks with card counts, note types with their exact field names |
| `search_notes` | read | Search with Anki's query syntax, one compact line per note |
| `draft_add` | draft | Validate cards and add them to a draft. Writes nothing to Anki. |
| `draft_add_occlusion` | draft | Add an image occlusion note, masks by label or region |
| `draft_edit` | draft | Change or remove single draft cards by number |
| `stage_image` | draft | Prepare an image or a PDF crop for a card |
| `pdf_figures` | read | Find figures and their captions in a PDF |
| `render_graph` | draft | Draw a graph, tree or automaton with Graphviz |
| `stats` | read | Card counts, retention, and the cards you struggle with, with a reason for each |
| `youtube_transcript` | web | Transcript or navigable outline of a YouTube video |
| `review` | **write** | Open the preview, wait for you, add the accepted cards (missing decks are created) |
| `update_notes` | **write** | Fix cards without losing their review history. Undoable. |
| `undo` | **write** | Revert a commit or an edit by its batch id |
| `delete_notes` | **write** | Delete notes this plugin created. Asks for confirmation. |
| `sync` | **write** | Sync with AnkiWeb so the cards reach your phone |

Every tool is annotated as read-only or not, so clients that ask for permission only ask for
the ones that change something.

> [!TIP]
> Say *"sync"* after the review and the new cards are on your phone before you close the laptop.

## Safety

> [!IMPORTANT]
> This plugin writes to your real collection. Make a backup before the first run:
> ***File → Export → Anki Collection Package***.

What the plugin will not do:

- Write cards you did not accept in the preview (or in the chat)
- Delete a note it did not create
- Edit a note it did not create, unless you approve `force=True`
- Read files other than images and PDFs

## Privacy

Everything runs on your computer. The plugin talks to Anki through AnkiConnect on `127.0.0.1`
and stores drafts, staged images and its undo journal in Claude's plugin data folder. The
preview is served on `127.0.0.1` with a random port and a secret token.

Outside services: YouTube when you ask for a transcript, and the preview loads MathJax from
the jsDelivr CDN to render formulas.

## Known limits

- **No dialog window may be open in Anki.** A modal blocks AnkiConnect entirely, and every call
  runs into a timeout until you close it.
- **Works in Claude Code and the Claude desktop app.** claude.ai in the browser cannot reach Anki
  on your computer.
- **Starting Anki automatically works on macOS only.** On Windows and Linux, open Anki yourself.
- **Drafts are deleted after 14 days without changes.**
- **Duplicate detection follows Anki's rule**: only the first field of a note type is compared.
  Two cards with the same question and different answers count as duplicates.
- **Deleting cannot be undone.** Prefer fixing a card over deleting it.
- **The preview renders a subset of Anki's template language**: fields, `FrontSide`, cloze,
  conditionals, hint and type. The answer side is shown without `{{FrontSide}}`. Custom JavaScript in your templates runs, add-on specific
  features may not.
- **Image occlusion uses rectangles**, and needs a PDF text layer or a Graphviz graph to place
  masks by label. For scanned images, Claude places them by region.
- **Statistics are read through AnkiConnect**, which does not expose FSRS memory states directly.
  Difficulty is read from the review log instead, which is precise enough for ranking.

## Development

```bash
uv sync
claude --plugin-dir .
```

The tests run against an in-memory fake of AnkiConnect, so they need no Anki.

## Personal AI Use

I wrote the core of this project myself because I wanted to use it to learn: the AnkiConnect
client, drafts, the undo journal and the card tools. I used AI assistance for the long card-rule
prompt and this README, and Claude Code wrote the image, preview and statistics modules and the
tests in 2.0.

## Credits

- [AnkiConnect](https://git.sr.ht/~foosoft/anki-connect) by foosoft, the add-on this talks to
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) by jdepoix
- [pdfplumber](https://github.com/jsvine/pdfplumber), [pypdfium2](https://github.com/pypdfium2-team/pypdfium2),
