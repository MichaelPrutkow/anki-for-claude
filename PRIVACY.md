# Privacy

Anki for Claude does not collect, store or send any data to the author or to third parties for analytics.

- The plugin's server runs on your own computer and talks to your running Anki through
  AnkiConnect on `http://127.0.0.1:8765`. Your cards and review history never leave your computer
  through this plugin.
- Files you ask Claude to use (PDFs, images) are read locally from your computer.
- The `youtube_transcript` tool, when you ask for it, sends the video's ID to YouTube to download
  its transcript.
- The `sync` tool, when you ask for it, makes Anki sync with AnkiWeb under your own Anki account.

What Claude itself does with the content of your chat is governed by
[Anthropic's privacy policy](https://www.anthropic.com/legal/privacy).

Questions: open an issue at https://github.com/MichaelPrutkow/anki-for-claude/issues.
