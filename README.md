
<h1 align="center">Anki for Claude</h1>

<p align="center">
  <b>Turn lecture material, YouTube videos or any other context from your chat into Anki cards.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/github/downloads/MichaelPrutkow/anki-mcp-server/total?color=purple" alt="Downloads">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/Claude-plugin-D97757" alt="Claude plugin">
  <img src="https://img.shields.io/badge/Anki-23.10%2B-orange" alt="Anki 23.10+">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB" alt="Python 3.10+">
</p>

A Claude plugin that reads your lecture material, transcribes YouTube videos and writes Anki
flashcards from it. It talks to your running Anki through
[AnkiConnect](https://ankiweb.net/shared/info/2055492159).

Most LLM-to-Anki tools only take text, produce cards and write them. That produces a lot
of cards and not much learning. This plugin connects Claude directly to Anki and has it write
cards that are actually worth reviewing, grounded in your own material.

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

## Install

### Claude Code

```
/plugin marketplace add MichaelPrutkow/anki-mcp-server
/plugin install anki@michaelprutkow
```

### Claude desktop app

***Customize → Plugins → Add → Add marketplace***, enter `MichaelPrutkow/anki-mcp-server`,ss
then install **Anki Flashcards**.

The first start takes a few seconds while uv installs the dependencies.

### Settings

| Option | Default | |
| --- | --- | --- |
| AnkiConnect URL | `http://127.0.0.1:8765` | Only change this if you moved AnkiConnect |
| Start Anki automatically | on | Opens Anki when it is not running (macOS) |

### Upgrading from 1.x

Remove the old Anki extension (`.mcpb`) from Claude Desktop, otherwise Claude sees two sets of
Anki tools. Cards created with 1.x keep working: they are still tagged `mcp::created`, and their
batches can still be undone.

### Any other MCP client, from source

The MCP server also runs without the plugin, for example in Cursor. You only get the tools then,
not the card-writing skills.

```bash
git clone https://github.com/MichaelPrutkow/anki-mcp-server.git
cd anki-mcp-server
uv sync
```

```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/anki-mcp-server", "-m", "anki_mcp"]
    }
  }
}
```

## Usage

Just ask: *"Make flashcards from this lecture for my deck Analysis 2."* Claude loads the card
rules, drafts the cards, shows them to you and asks before anything is written.

| Skill | When it is used |
| --- | --- |
| `/anki:cards` | Writing cards from any material. Holds the card-design rules and the workflow. |
| `/anki:maintain` | Searching, fixing, deleting and undoing existing cards. |

Claude picks the right skill on its own; the slash commands are there if you want to force one.

## Design decisions

### Nothing is written until you approve it

Cards go into a **draft** first. A draft is validated against your note type and deck, checked
for duplicates, and every card is shown to you in the chat with a number. Only `draft_commit`
writes to your collection, and Claude asks for your confirmation before it runs, even in
auto mode.

Drafts are saved on disk, so they survive restarts and closing the app. Ask for changes by
number (*"make #3 shorter, drop #7"*) and only those cards are edited, instead of rewriting
the whole batch.

<details>
  <summary><h3> Click to view: Example of an in-chat draft</h3></summary>
  <br>
  <img width="513" alt="image" src="https://github.com/user-attachments/assets/65a415b6-f8fd-4c58-8db5-ceb7c0adc09a" />
</details>

### Everything can be undone

Every commit and every edit returns a batch id. `undo` with that id removes the cards a commit
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
| `draft_edit` | draft | Change or remove single draft cards by number |
| `draft_show` | read | List open drafts, or show every card of one draft |
| `youtube_transcript` | web | Transcript or navigable outline of a YouTube video |
| `create_deck` | **write** | Create a deck, `::` creates subdecks |
| `draft_commit` | **write** | Write a draft to Anki. Asks for your confirmation. |
| `update_notes` | **write** | Fix cards without losing their review history. Undoable. |
| `undo` | **write** | Revert a commit or an edit by its batch id |
| `delete_notes` | **write** | Delete notes this plugin created. Asks for confirmation. |
| `sync` | **write** | Sync with AnkiWeb so the cards reach your phone |

Every tool is annotated as read-only or not, so clients that ask for permission only ask for
the ones that change something.

> [!TIP]
> Say *"sync"* after committing and the new cards are on your phone before you close the laptop.

## Safety

> [!IMPORTANT]
> This plugin writes to your real collection. Make a backup before the first run:
> ***File → Export → Anki Collection Package***.

What the plugin will not do:

- Write cards without `draft_commit`, which asks for your confirmation
- Delete a note it did not create
- Edit a note it did not create, unless you approve `force=True`

## Privacy

Everything runs on your computer. The plugin talks to Anki through AnkiConnect on `127.0.0.1`
and stores drafts and its undo journal in Claude's plugin data folder. The only outside service
it contacts is YouTube, when you ask for a transcript.

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
- **No image support yet.** Cropping figures from PDFs, generated diagrams and image-occlusion
  cards are planned.

## Personal AI Use
I wrote almost all of this code myself because I wanted to use this project to learn. I did use some AI assistance, but strictly for formulating my ideas for the long system prompt and this README, as well as for minor bug fixes and some helper and utility functions.

## Credits

- [AnkiConnect](https://git.sr.ht/~foosoft/anki-connect) by foosoft, the add-on this talks to
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) by jdepoix