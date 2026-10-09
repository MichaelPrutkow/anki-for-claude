---
name: visuals
description: Adds pictures to Anki cards with the anki MCP tools - graphs, trees and automata drawn with Graphviz, figures cut out of lecture PDFs, own matplotlib plots, and native Image Occlusion cards that hide labels on a diagram. Use when a card is about something that is drawn in the lecture or exam (graph traversals, heaps, automata, plots, anatomy, circuits, diagrams), or when the user asks for images or image occlusion.
---

# Cards with pictures

If the exam shows it as a picture, the card shows a picture. A DFS order asked on an edge list is a bad card; the same question on a drawn graph is a good one.

## When a picture beats text
- Algorithms on structures: graph and tree traversals, shortest paths, heaps, AVL rotations, hash tables, sorting states.
- Automata, state machines, recursion trees, circuits.
- Function plots, geometric meaning of a theorem, vectors and transformations.
- Anatomy, pathways, any labelled diagram: use Image Occlusion.
- A figure the lecture or a past exam uses: cut it out instead of describing it.

Keep text cards for definitions, statements and reasons. A picture must carry information, never decorate.

## Three ways to get an image
1. **Graphviz** for graphs, trees and automata: `render_graph` with DOT. It returns an `<img>` tag and a thumbnail; check the thumbnail. For front and back variants (e.g. visit order only on the back) call it twice with two DOT versions; the layout stays the same.
2. **From a PDF**: `pdf_figures` lists figures with captions (`overlay=true` shows the page with numbered boxes and a 10% grid). Then `stage_image` with `page` and `figure`, or with `region` = [left, top, right, bottom] as fractions read off the grid.
3. **Own plot**: write a matplotlib script using the house style, run it with `uv run --no-project --with matplotlib python <script>.py`, then pass the absolute path it prints to `stage_image`:
   ```python
   import sys; sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/visuals/scripts")
   import ankiplot
   fig, ax = ankiplot.figure()
   ...
   ankiplot.save(fig, "tangent.png")
   ```

Put the returned `<img>` tag into a field. Images are copied into Anki only when the user accepts the card in `review`.

## Image Occlusion
- `draft_add_occlusion` with the staged image and masks. A mask is `{"label": "Mitralklappe"}` (text found on a PDF figure or a Graphviz node name/label) or `{"region": [left, top, width, height]}` as fractions of the image. Masks with the same `group` become one card.
- `hide_all=true` (default) hides all labels and asks for one; use `false` when the other labels are needed as hints.
- Always look at the returned preview: every mask must cover exactly its label.
- Needs Anki 23.10+ with the Image Occlusion note type. If it is missing, run the `setup` skill.

## Style
- White background, black lines, at most 3 accent colours, readable on a phone (labels at least 14 pt at the saved size).
- Nothing on the front may give the answer away: no visit order, no highlighted path, no solution in the caption.
- One idea per picture. Crop away slide titles, page numbers and logos.
