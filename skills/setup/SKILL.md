---
name: setup
description: Checks and fixes the anki plugin's setup - Anki and AnkiConnect reachable, Image Occlusion note type present, Graphviz installed - and explains each fix. Use when the anki tools fail, when the user installs the plugin, or when they ask whether everything is set up.
---

# Setup check

Run the checks in order and report a short checklist (ok / problem + exact fix).

1. **Anki and AnkiConnect**: call `overview`.
   - Fails with "doesn't respond": Anki is closed or AnkiConnect is missing. Fix: open Anki; install AnkiConnect via Tools > Add-ons > Get Add-ons, code `2055492159`, then restart Anki.
   - Fails with a timeout: a dialog is open in Anki (often the profile chooser or a sync conflict). Fix: close it; set a default profile.
2. **Note types**: in the `overview` output look for a type marked `[io]`.
   - Missing: Image Occlusion needs Anki 23.10+. Fix: Tools > Manage Note Types > Add > "Add: Image Occlusion".
3. **Graphviz** (for `render_graph`): call `render_graph` with `digraph { A -> B }`.
   - "Graphviz is not installed": macOS `brew install graphviz`, Windows `winget install graphviz`, Linux the `graphviz` package.
4. **Sync**: ask whether the user wants cards on the phone; if yes, `sync` and check that AnkiWeb login exists in Anki.

Do not change anything in the collection during the check.
