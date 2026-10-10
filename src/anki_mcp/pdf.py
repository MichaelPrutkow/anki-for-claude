"""Figures in PDFs: finding them with their captions, cutting them out, and a page overview for Claude."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image, ImageDraw

_CAPTION = re.compile(r"^(abb\.?|abbildung|fig\.?|figure|grafik|tab\.?|tabelle)\s*\d", re.IGNORECASE)
_FIGURE_ID = re.compile(r"p(\d+)f\d+")
MERGE_GAP = 8.0  # points
MIN_AREA, MAX_AREA = 0.015, 0.85  # of the page
MAX_OBJECTS = 3000
MAX_PAGES = 20

Box = tuple[float, float, float, float]  # left, top, right, bottom as fractions of the page


@dataclass
class Figure:
    id: str
    page: int
    box: Box
    caption: str | None = None


def page_of(figure_id: str) -> int:
    match = _FIGURE_ID.fullmatch(figure_id)
    if not match:
        raise ToolError(f"'{figure_id}' is not a figure id. Figure ids look like 'p3f1' and come from pdf_figures.")
    return int(match[1])


def parse_pages(spec: str, count: int) -> list[int]:
    pages: set[int] = set()
    try:
        for part in spec.split(","):
            first, _, last = part.strip().partition("-")
            pages.update(range(max(int(first), 1), min(int(last or first), count) + 1))
    except ValueError:
        raise ToolError(f"'{spec}' is not a page list. Examples: '3', '2-5', '2-5,8'.") from None
    if not pages:
        raise ToolError(f"No pages selected. The PDF has {count} pages.")
    return sorted(pages)[:MAX_PAGES]


def _merge(boxes: list[list[float]], gap: float) -> list[list[float]]:
    boxes = [b[:] for b in boxes]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for b in boxes:
            for o in out:
                if b[0] <= o[2] + gap and o[0] <= b[2] + gap and b[1] <= o[3] + gap and o[1] <= b[3] + gap:
                    o[0], o[1] = min(o[0], b[0]), min(o[1], b[1])
                    o[2], o[3] = max(o[2], b[2]), max(o[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def _page_figures(page: Any, page_no: int) -> list[Figure]:
    width, height = float(page.width), float(page.height)
    area = width * height
    objects = (page.rects + page.lines + page.curves)[:MAX_OBJECTS]
    boxes = [
        [o["x0"], o["top"], o["x1"], o["bottom"]]
        for o in page.images + objects
        # skip page backgrounds, they would swallow every figure
        if (o["x1"] - o["x0"]) * (o["bottom"] - o["top"]) / area <= MAX_AREA
    ]
    clusters = [b for b in _merge(boxes, MERGE_GAP) if MIN_AREA <= (b[2] - b[0]) * (b[3] - b[1]) / area <= MAX_AREA]
    clusters.sort(key=lambda b: (round(b[1]), b[0]))
    captions = [line for line in page.extract_text_lines() if _CAPTION.match(line["text"].strip())]

    figures = []
    for i, (x0, top, x1, bottom) in enumerate(clusters, start=1):
        caption = None
        for line in captions:
            overlaps = line["x0"] < x1 and line["x1"] > x0
            if overlaps and (0 <= line["top"] - bottom <= 60 or 0 <= top - line["bottom"] <= 60):
                caption = line["text"].strip()
                break
        # Drawings may reach past the page edge.
        box = (max(x0 / width, 0.0), max(top / height, 0.0), min(x1 / width, 1.0), min(bottom / height, 1.0))
        figures.append(Figure(f"p{page_no}f{i}", page_no, box, caption))
    return figures


def find_figures(path: Path, pages: str) -> tuple[list[int], list[Figure]]:
    """Raster images and clusters of vector graphics on the given pages. Returns (pages, figures)."""
    with pdfplumber.open(path) as pdf:
        selected = parse_pages(pages, len(pdf.pages))
        figures = [f for page_no in selected for f in _page_figures(pdf.pages[page_no - 1], page_no)]
    return selected, figures


def figure_box(path: Path, figure_id: str) -> Box:
    page = page_of(figure_id)
    _, figures = find_figures(path, str(page))
    for f in figures:
        if f.id == figure_id:
            return f.box
    found = ", ".join(f.id for f in figures) or "none"
    raise ToolError(f"There is no figure '{figure_id}'. Figures on page {page}: {found}.")


def _page(pdf: Any, page_no: int) -> Any:
    if not 1 <= page_no <= len(pdf.pages):
        raise ToolError(f"Page {page_no} does not exist. The PDF has {len(pdf.pages)} pages.")
    return pdf.pages[page_no - 1]


def _render(page: Any, dpi: int) -> Image.Image:
    return page.to_image(resolution=dpi, antialias=True).original.convert("RGB")


def crop(path: Path, page_no: int, box: Box, dpi: int = 200) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Render a region of a page. Returns the image and the words inside it, positioned relative to the crop."""
    left, top, right, bottom = box
    with pdfplumber.open(path) as pdf:
        page = _page(pdf, page_no)
        x0, y0 = left * float(page.width), top * float(page.height)
        x1, y1 = right * float(page.width), bottom * float(page.height)
        image = _render(page.crop((x0, y0, x1, y1)), dpi)
        words = page.within_bbox((x0, y0, x1, y1)).extract_words()
    labels = [
        {
            "text": word["text"],
            "left": (word["x0"] - x0) / (x1 - x0),
            "top": (word["top"] - y0) / (y1 - y0),
            "width": (word["x1"] - word["x0"]) / (x1 - x0),
            "height": (word["bottom"] - word["top"]) / (y1 - y0),
        }
        for word in words
    ]
    return image, labels


def overview(path: Path, page_no: int, figures: list[Figure], dpi: int = 100) -> Image.Image:
    """The page with the found figures as numbered boxes and a 10 % grid, so Claude can name any region."""
    with pdfplumber.open(path) as pdf:
        image = _render(_page(pdf, page_no), dpi)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for i in range(1, 10):
        x, y = w * i / 10, h * i / 10
        draw.line([(x, 0), (x, h)], fill=(120, 160, 255), width=1)
        draw.line([(0, y), (w, y)], fill=(120, 160, 255), width=1)
        draw.text((x + 2, 2), f"{i * 10}%", fill=(40, 80, 200))
        draw.text((2, y + 2), f"{i * 10}%", fill=(40, 80, 200))
    for f in figures:
        if f.page != page_no:
            continue
        left, top, right, bottom = f.box
        draw.rectangle((left * w, top * h, right * w, bottom * h), outline=(220, 30, 30), width=3)
        draw.text((left * w + 4, top * h + 4), f.id, fill=(220, 30, 30))
    return image
