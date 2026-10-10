# Anki for Claude

**Turn lecture material, YouTube videos or anything else in your chat into Anki cards.**

[![Stars](https://img.shields.io/github/stars/MichaelPrutkow/anki-for-claude?style=flat&color=yellow)](https://github.com/MichaelPrutkow/anki-for-claude/stargazers)
[![MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Claude plugin](https://img.shields.io/badge/Claude-plugin-D97757)
![Anki 23.10+](https://img.shields.io/badge/Anki-23.10%2B-orange)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)

A Claude plugin that reads your lecture material, transcribes YouTube videos and writes Anki
flashcards from it, including pictures and native image occlusion cards. It talks to your
running Anki through [AnkiConnect](https://ankiweb.net/shared/info/2055492159).

Most LLM-to-Anki tools only take text, produce cards and write them. That produces a lot of
cards and not much learning. This plugin has Claude write cards that are worth reviewing,
grounded in your own material, shows them to you before anything is added, and later uses your
review history to find and fix the cards that do not work.

> Unofficial. Not affiliated with or endorsed by Ankitects Pty Ltd.

## Demo

**Asking Claude for cards from a YouTube video combined with lecture slides**

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

**Output, clicked through in Anki**

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## Requirements

- **Anki 23.10 or newer** with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
  add-on: in Anki, *Tools → Add-ons → Get Add-ons*, code `2055492159`, then restart Anki.
- **[uv](https://docs.astral.sh/uv/)**, which starts the plugin's Python server: `brew install uv`
  on macOS, or `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Claude Code** or the **Claude desktop app**.
- Optional: **[Graphviz](https://graphviz.org/download/)** for drawn graphs, trees and automata
  (`brew install graphviz`).

## Install

**Claude Code**

```
/plugin marketplace add MichaelPrutkow/anki-for-claude
/plugin install anki@michaelprutkow
```

**Claude desktop app:** *Customize → Plugins → Add → Add marketplace*, enter
`MichaelPrutkow/anki-for-claude`, then install **Anki Flashcards**.

The first start takes a few seconds while uv installs the dependencies. Then ask Claude to
*"check my Anki setup"*.

Nothing needs to be configured. The plugin talks to AnkiConnect on `http://127.0.0.1:8765` and
starts Anki when it is not running (macOS only).

## Usage

Ask for cards: *"Make flashcards from this lecture for my deck Analysis 2."* Claude writes them
into a draft and shows every card in the chat. You say what to change, and only after you say
yes are they added to Anki.

| Skill | What it is for |
| --- | --- |
| `/anki:create-cards` | Writing cards from any material: the card rules and the workflow |
| `/anki:visuals` | Cards with pictures: Graphviz graphs, figures cut from PDFs, plots, image occlusion |
| `/anki:improve-cards` | Finding your weakest cards and fixing, searching, deleting or undoing cards |
| `/anki:exam-prep` | Turning a whole course (slides, exercise sheets, past exams) into a prioritised deck |
| `/anki:check-setup` | Checking Anki, AnkiConnect, the image occlusion note type and Graphviz |

Claude picks the right skill on its own; the slash commands are there to force one.

Flag a bad card red while you study on your phone. The next time you ask Claude to improve your
cards, it picks it up. If you want that regularly, schedule a prompt such as *"improve my
weakest cards in Analysis 2"* as a task in the Claude desktop app.

PDFs and images are opened from your computer by their full path. A file you attach to a chat in
the desktop app is not on your computer yet: Claude saves it there first or asks you for the path.

## How it works

**Nothing is added until you approve it.** Cards go into a draft first, which is checked against
your note types and for duplicates. Claude shows you every card word for word, changes single
cards on request, and adds only the cards you approve. Drafts are saved on disk, so they survive
restarts.

**Pictures where the exam has pictures.** Graphs, trees and automata are drawn with Graphviz in
one consistent style. Figures from your PDFs are found with their captions (*"Abb. 3.2"*) and
cut out exactly. Plots are drawn with matplotlib. Image occlusion notes are Anki's native ones,
and their masks are placed through the PDF's text layer or the graph's node positions, not
guessed from pixels. Pictures are saved in `~/Pictures/Anki for Claude`, so you can look at them
while you review the cards; image occlusion cards also get a `<name>-masks.png` that shows the
masks.

**Card rules that are loaded only when needed.** The rules live in a skill, so they cost nothing
in other conversations. One fact per card, no yes/no questions, no lists (they become separate
cloze deletions), separate cards for a theorem's statement, hypotheses and key idea, and wording
rules inspired by [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing).
The tools also catch the most common formatting slips: LaTeX outside `\( \)`, `$...$` math that
Anki does not render, a `<` inside a formula, and braces that end a cloze too early.

![Example of generated Anki cards](https://github.com/user-attachments/assets/d1c2b2d4-5ec1-4048-b8a8-94ab4bd81a61)

**Your review history decides what to fix.** `stats` ranks the notes you struggle with by again
rate, lapses, FSRS difficulty, answer time, leeches and red flags, with a hint at the cause.
Claude proposes the fix (split the card, sharpen the question, add a picture or a prerequisite
card) and changes nothing until you approve it.

**Everything can be undone.** Every commit and every edit returns a batch id, and `undo` removes
the added cards or restores the changed fields. A card you edited yourself in the meantime is
left alone. Cards the plugin did not create cannot be deleted by it and are only edited after
you agree.

**A whole course at once.** `/anki:exam-prep` analyses each source with its own agent, so 200
pages of slides never fill your conversation, lets you approve a blueprint of topics weighted by
past exams, writes the cards in parallel, checks them against the rules and has you approve them
topic by topic.

**Compact output.** Tools answer in short plain text: what happened, the data, the next step.
Long YouTube videos come back as a timestamped outline, and Claude reads only the parts it needs.

## Tools

| Tool | Access | What it does |
| --- | --- | --- |
| `overview` | read | Decks with card counts, note types with their exact field names |
| `search_notes` | read | Search with Anki's query syntax, one line per note |
| `draft_add` | draft | Check cards and add them to a draft |
| `draft_add_occlusion` | draft | Add an image occlusion note, masks by label or region |
| `draft_edit` | draft | Change or remove draft cards by number |
| `draft_show` | read | Show a draft's cards, or list the open drafts |
| `stage_image` | draft | Save an image, a PDF figure or part of a PDF page for a card |
| `pdf_figures` | read | Find figures and their captions in a PDF |
| `render_graph` | draft | Draw a graph, tree or automaton with Graphviz |
| `stats` | read | Card counts, retention, and the cards you struggle with |
| `youtube_transcript` | web | Transcript or outline of a YouTube video |
| `draft_commit` | **write** | Add the approved cards to Anki, creating missing decks |
| `update_notes` | **write** | Fix cards without losing their review history |
| `undo` | **write** | Revert a commit or an edit by its batch id |
| `delete_notes` | **write** | Delete notes this plugin created |
| `sync` | **write** | Sync with AnkiWeb so the cards reach your phone |

*Draft* tools change only drafts and pictures, never your collection.

## Safety

> **Back up first.** This plugin writes to your real collection. Make a backup before the first
> run: *File → Export → Anki Collection Package*.

The plugin will not:

- add cards you did not approve in the chat,
- delete a note it did not create,
- edit a note it did not create without your consent,
- open files other than images and PDFs.

## Privacy and data

Everything runs on your computer, and nothing is sent to the author of this plugin.

- **Anki:** the plugin talks to AnkiConnect on `127.0.0.1`.
- **Stored on your computer:** drafts (deleted after 14 days without changes) and the undo
  journal in Claude's plugin data folder, pictures in `~/Pictures/Anki for Claude` until you
  delete them.
- **Sent elsewhere, only when you ask for it:** the video id to YouTube for a transcript, a
  request to the web address of an image you want on a card, and your collection to AnkiWeb
  when Anki syncs.
- **Programs it starts:** Anki, when it is not running (macOS), and Graphviz's `dot` to draw
  graphs.

## Known limits

- **No dialog window may be open in Anki.** A modal blocks AnkiConnect, and every call times out
  until you close it.
- **Claude Code and the Claude desktop app only.** claude.ai in the browser cannot reach Anki on
  your computer.
- **Anki starts automatically on macOS only.** On Windows and Linux, open it yourself.
- **Duplicates are detected the way Anki does it:** only the first field is compared, so two cards
  with the same question count as duplicates.
- **Deleting cannot be undone.** Prefer fixing a card over deleting it.
- **Image occlusion uses rectangles**, and placing masks by label needs a PDF text layer or a
  Graphviz graph. For other images, Claude places them by region.
- **FSRS difficulty is read from the review log**, because AnkiConnect does not expose FSRS
  memory states. That is precise enough for ranking.

## Upgrading from 1.x

Remove the old Anki extension (`.mcpb`) under *Settings → Extensions* in the Claude desktop app,
otherwise Claude sees two sets of Anki tools. Cards created with 1.x keep their `mcp::created`
tag, and their batches can still be undone.

## Other MCP clients

The MCP server also runs without the plugin, for example in Cursor. You get the tools then, but
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

## Development

```bash
uv sync
uv run pytest            # the tools against an in-memory fake of AnkiConnect, no Anki needed
claude plugin eval .     # Claude with the plugin against mocked tools, compared with Claude without it
claude --plugin-dir .    # try it in Claude Code
```

## Personal AI use

I wrote the core of this project myself because I wanted to use it to learn: the AnkiConnect
client, drafts, the undo journal and the card tools. I used AI assistance for the long card-rule
prompt and this README, and Claude Code wrote the image and statistics modules in 2.0 and the
chat review, the tests and the reworked skills in 2.1.

## Credits

- [AnkiConnect](https://git.sr.ht/~foosoft/anki-connect) by foosoft, the add-on this talks to
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) by jdepoix
- [pdfplumber](https://github.com/jsvine/pdfplumber), [Pillow](https://python-pillow.org) and
  [Graphviz](https://graphviz.org) for the pictures
- The [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
