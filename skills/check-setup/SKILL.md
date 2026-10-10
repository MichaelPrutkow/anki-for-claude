---
name: check-setup
description: Checks whether the anki plugin can work on the user's computer - Anki running with the AnkiConnect add-on, the Image Occlusion note type, Graphviz, AnkiWeb sync - and tells the user exactly how to fix what is missing. Use right after the plugin is installed, when the anki tools are missing or fail, or when the user asks whether everything is set up.
---

# Checking the setup

The anki tools run in a small server on the user's computer and talk to Anki through the AnkiConnect add-on. You can test the setup through these tools, but you cannot install programs or click anything in Anki for the user. For every problem, tell the user exactly what to do. Only if you can run commands on the user's computer yourself (for example in Claude Code) may you offer to run an install command for them.

Go through the steps in order. Stop at the first one that fails, explain the fix, and continue once the user has done it.

1. **The anki tools exist.** If `overview` is not among your tools, call `get_device_info` (search for it if it is not loaded) and search for the anki tools again. If they are still missing, this chat does not reach the plugin's server on the user's computer; whether Anki is open does not matter for this. Give the user these fixes in this order, each one only if the one before did not help:
   - In the Claude app: start a new chat, add a folder with the Add folder button before sending the first message (for example the folder with the study material), then send the request again. A chat reaches the tools on the user's computer reliably only with a folder.
   - Quit the Claude app completely, open it again and start a new chat. The first start can take a minute while uv installs the plugin's dependencies.
   - Install uv, which starts the server: `brew install uv` on macOS, `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux, `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` on Windows. Then restart the Claude app.
   - Update the plugin to the newest version.
2. **Anki and AnkiConnect.** Call `overview`.
   - It lists decks and note types: both work.
   - "does not answer" or "not running": Anki is closed or AnkiConnect is missing. The user opens Anki. If that is not enough, they install AnkiConnect in Anki under Tools > Add-ons > Get Add-ons... with the code `2055492159` and restart Anki.
   - "did not answer in time": a window is waiting in Anki, often the profile chooser or a sync question. The user closes it. If the profile chooser comes up every time, they can open their profile once and let Anki remember it.
3. **Image Occlusion** (only for image occlusion cards). `overview` lists a note type marked `[image occlusion]`. If there is none: it needs Anki 23.10 or newer; then the user adds it in Anki under Tools > Manage Note Types > Add > "Add: Image Occlusion".
4. **Graphviz** (only for drawn graphs). `overview` says so when Graphviz is missing. The user installs it with `brew install graphviz` on macOS, `winget install graphviz` on Windows, or the `graphviz` package on Linux.
5. **Phone** (only if the user studies on a phone). Call `sync`. If it fails, the user logs in to AnkiWeb in Anki under Tools > Preferences > Syncing.

End with a short checklist: each item ok, or the fix the user still has to do. Do not change any cards during the check.
