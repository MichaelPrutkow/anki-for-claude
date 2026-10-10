---
name: visuals
description: Adds pictures to Anki cards - graphs, trees and automata drawn with Graphviz, figures cut out of PDFs, matplotlib plots, and image occlusion cards that hide the labels of a diagram. Use when a card is about something drawn in the lecture or exam (graph algorithms, heaps, automata, plots, circuits, anatomy, any labelled diagram), or when the user asks for images or image occlusion.
---

# Cards with pictures

If the exam shows it as a picture, the card shows a picture. A DFS order asked on an edge list is a bad card; the same question on a drawn graph is a good one.

## When a picture beats text

- Algorithms on structures: graph and tree traversals, shortest paths, heaps, AVL rotations, hash tables, sorting states.
- Automata, state machines, recursion trees, circuits.
- Function plots, the geometric meaning of a theorem, vectors and transformations.
- Anatomy, pathways and any labelled diagram: use image occlusion.
- A figure from the lecture or a past exam: cut it out instead of describing it.

Keep text cards for definitions, statements and reasons. A picture has to carry information, not decorate.

## How images work

Each image tool saves a PNG under the name you give it into the user's images folder (the result says where), shows you a thumbnail and returns the `<img>` tag for a card field. Anki gets a copy only when the card is committed. In the chat preview the user sees the file name and can open the file in that folder.

Look at every thumbnail. Redo the image if something is cut off, too small to read on a phone, or gives the answer away.

The anki tools run on the user's computer and open files there by absolute path. A file attached to the chat, or a plot you made in a sandbox of your own, is not on that computer: save it there first if you can, otherwise ask the user where the file is.

## Getting an image

- **Graphs, trees, automata:** `render_graph` with DOT source and a name. For a front and a back version (for example the visit order only on the back), call it twice with the same nodes and edges and labels of the same length, so both drawings line up.
- **Figures from a PDF:** `pdf_figures` lists the figures on the given pages with id, region and caption. `show_page=true` adds a picture of the page with the figures boxed and a 10 % grid. Then call `stage_image` with the PDF and the figure id, or with `page` and a `region` [left, top, right, bottom] read off the grid as fractions.
- **Image files and URLs:** `stage_image` with the path or URL. `region` crops it.
- **Plots:** draw them with matplotlib in this style, save the PNG on the user's computer and pass its path to `stage_image`. If you need a Python with matplotlib, `uv run --no-project --with matplotlib python plot.py` gives you one.
  ```python
  import matplotlib.pyplot as plt

  plt.rcParams.update({
      "font.size": 15, "lines.linewidth": 2.4, "axes.grid": True, "grid.alpha": 0.3,
      "axes.spines.top": False, "axes.spines.right": False,
      "axes.prop_cycle": plt.cycler(color=["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00"]),
  })
  fig, ax = plt.subplots(figsize=(6, 4))
  ax.plot(...)
  fig.savefig("tangent.png", dpi=200, bbox_inches="tight", facecolor="white")
  ```

## Image occlusion

`draft_add_occlusion` turns a saved image into an Image Occlusion note (Anki 23.10 or newer).

- A mask is `{"label": "Mitralklappe"}` for text on a PDF figure or a graph node, or `{"region": [left, top, right, bottom]}` in fractions of the image for anything else.
- Every mask becomes its own card. Masks with the same `group` are asked together on one card.
- `hide_all=true` (the default) hides all masks and asks for one. Use `false` when the other labels are needed as hints.
- Check the returned picture: every mask has to cover exactly its label. The user finds the same picture as `<name>-masks.png` in the images folder.
- If there is no Image Occlusion note type, follow the `check-setup` skill.

## Style

- White background, black lines, at most three accent colours.
- Readable on a phone: labels at least 14 pt at the saved size.
- Nothing on the front may give the answer away: no visit order, no highlighted path, no solution in a caption.
- One idea per picture. Crop away slide titles, page numbers and logos.
