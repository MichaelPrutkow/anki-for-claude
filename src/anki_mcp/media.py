"""Images for cards: staging, PDF figures and Graphviz drawings. Nothing reaches Anki before a commit."""

import asyncio
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import httpx
import pdfplumber
import pypdfium2 as pdfium
from mcp.server.mcpserver import Image as McpImage
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image, ImageChops, ImageDraw
from pydantic import Field

from anki_mcp.server import DRAFT_ONLY, READ_ONLY, Ctx, app, tool

MEDIA_REF = re.compile(r'src="img:([0-9a-f]{8})"')
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_DOWNLOAD_BYTES = 10_000_000
THUMBNAIL_PX = 512
MAX_PAGES = 20


# --- staged images -------------------------------------------------------------------


@dataclass
class StagedImage:
    id: str
    path: Path
    width: int
    height: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"img:{self.id}"


class MediaStore:
    """Images waiting for a commit, stored as PNG plus a small JSON with metadata."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, image: Image.Image, meta: dict[str, Any] | None = None) -> StagedImage:
        data = png_bytes(image)
        media_id = hashlib.sha256(data).hexdigest()[:8]
        path = self._root / f"{media_id}.png"
        path.write_bytes(data)
        info = {"width": image.width, "height": image.height, **(meta or {})}
        (self._root / f"{media_id}.json").write_text(json.dumps(info), encoding="utf-8")
        return StagedImage(media_id, path, image.width, image.height, info)

    def get(self, media_id: str) -> StagedImage:
        media_id = media_id.removeprefix("img:")
        path = self._root / f"{media_id}.png"
        if not re.fullmatch(r"[0-9a-f]{8}", media_id) or not path.exists():
            raise ToolError(f"Unknown image 'img:{media_id}'. Stage it first with stage_image.")
        meta = json.loads((self._root / f"{media_id}.json").read_text(encoding="utf-8"))
        return StagedImage(media_id, path, meta["width"], meta["height"], meta)


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def downscale(image: Image.Image, max_px: int) -> Image.Image:
    if max(image.size) <= max_px:
        return image
    copy = image.copy()
    copy.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return copy


def trim(image: Image.Image, margin: int = 8) -> Image.Image:
    """Cut away the uniform border (colour of the top-left pixel)."""
    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    box = ImageChops.difference(image, background).getbbox()
    if not box:
        return image
    left, top, right, bottom = box
    return image.crop(
        (
            max(left - margin, 0),
            max(top - margin, 0),
            min(right + margin, image.width),
            min(bottom + margin, image.height),
        )
    )


def thumbnail(staged: StagedImage) -> McpImage:
    with Image.open(staged.path) as img:
        return McpImage(data=png_bytes(downscale(img.convert("RGB"), THUMBNAIL_PX)), format="png")


def resolve_path(source: str, roots: list[Path], suffixes: set[str]) -> Path:
    """Find a local file. Relative paths are looked up in the workspace folders."""
    candidate = Path(source).expanduser()
    if candidate.suffix.lower() not in suffixes:
        raise ToolError(f"'{source}': only {', '.join(sorted(suffixes))} files are allowed.")
    if candidate.is_absolute():
        if not candidate.is_file():
            raise ToolError(f"'{source}' does not exist.")
        return candidate
    matches = [root / candidate for root in roots if (root / candidate).is_file()]
    if not matches:
        matches = [p for root in roots for p in root.rglob(candidate.name) if p.is_file()]
    if not matches:
        raise ToolError(f"'{source}' not found in {', '.join(map(str, roots)) or 'no folders configured'}.")
    if len(matches) > 1:
        raise ToolError(f"'{source}' is ambiguous: {', '.join(map(str, matches[:5]))}")
    return matches[0]


async def load_image(source: str, roots: list[Path]) -> Image.Image:
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
            response = await http.get(source)
            response.raise_for_status()
            if len(response.content) > MAX_DOWNLOAD_BYTES:
                raise ToolError("Image is larger than 10 MB.")
            return Image.open(io.BytesIO(response.content)).convert("RGB")
    return Image.open(resolve_path(source, roots, IMAGE_SUFFIXES)).convert("RGB")


def img_tag(staged: StagedImage, display_width: int | None = None) -> str:
    width = f' width="{display_width}"' if display_width else ""
    return f'<img src="{staged.ref}"{width}>'


# --- Graphviz ------------------------------------------------------------------------

GRAPH_PAD = 0.06  # inches; without it node outlines at the edge get cut off
GRAPH_STYLE = (
    f'graph [pad={GRAPH_PAD}, dpi=200, bgcolor="white", fontname="Helvetica"];'
    ' node [fontname="Helvetica", fontsize=16, penwidth=1.6];'
    ' edge [fontname="Helvetica", fontsize=14, penwidth=1.6, arrowsize=0.8];'
)
_FORBIDDEN_DOT = re.compile(r"\b(image|shapefile|imagepath|fontpath|imagescale)\s*=", re.IGNORECASE)


def render_dot(source: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Render DOT in the house style. Returns the image and node boxes as fractions of the image."""
    if _FORBIDDEN_DOT.search(source):
        raise ToolError("DOT attributes that read files (image, shapefile, ...) are not allowed.")
    brace = source.find("{")
    if brace < 0:
        raise ToolError("Not a DOT graph: missing '{'.")
    path = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])
    dot = shutil.which("dot", path=path)
    if not dot:
        raise ToolError("Graphviz is not installed. Install it (macOS: brew install graphviz).")

    with tempfile.TemporaryDirectory() as tmp:
        png, plain = Path(tmp, "g.png"), Path(tmp, "g.txt")
        run = subprocess.run(
            [dot, "-Tpng", "-o", str(png), "-Tplain", "-o", str(plain)],
            input=(source[: brace + 1] + GRAPH_STYLE + source[brace + 1 :]).encode(),
            capture_output=True,
            timeout=10,
        )
        if run.returncode != 0:
            raise ToolError("Graphviz error: " + run.stderr.decode(errors="replace").strip())
        image = Image.open(png).convert("RGB")
        lines = plain.read_text(encoding="utf-8").splitlines()

    # -Tplain gives inches from the bottom left, without the padding around the drawing.
    width = height = 1.0
    boxes = []
    for line in lines:
        parts = shlex.split(line)
        if parts[0] == "graph":
            width, height = float(parts[2]) + 2 * GRAPH_PAD, float(parts[3]) + 2 * GRAPH_PAD
        elif parts[0] == "node":
            name, x, y, w, h, label = parts[1], *map(float, parts[2:6]), parts[6]
            boxes.append(
                {
                    "name": name,
                    "text": label,
                    "left": (x + GRAPH_PAD - w / 2) / width,
                    "top": 1 - (y + GRAPH_PAD + h / 2) / height,
                    "width": w / width,
                    "height": h / height,
                }
            )
    return image, boxes


# --- PDF -----------------------------------------------------------------------------

_CAPTION = re.compile(r"^(abb\.?|abbildung|fig\.?|figure|grafik|tab\.?|tabelle)\s*\d", re.IGNORECASE)
MERGE_GAP = 8.0  # points
MIN_AREA, MAX_AREA = 0.015, 0.85  # of the page
MAX_OBJECTS = 3000


@dataclass
class Figure:
    id: str
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    caption: str | None = None


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


def find_figures(path: Path, page_no: int) -> list[Figure]:
    """Raster images and clusters of vector graphics on one page, with captions."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[page_no - 1]
        area = float(page.width * page.height)
        objects = (page.rects + page.lines + page.curves)[:MAX_OBJECTS]
        boxes = [
            [o["x0"], o["top"], o["x1"], o["bottom"]]
            for o in page.images + objects
            # skip page backgrounds, they would swallow every figure
            if (o["x1"] - o["x0"]) * (o["bottom"] - o["top"]) / area <= MAX_AREA
        ]
        clusters = [b for b in _merge(boxes, MERGE_GAP) if MIN_AREA <= (b[2] - b[0]) * (b[3] - b[1]) / area <= MAX_AREA]
        captions = [ln for ln in page.extract_text_lines() if _CAPTION.match(ln["text"].strip())]

    clusters.sort(key=lambda b: (round(b[1]), b[0]))
    figures = []
    for i, (x0, top, x1, bottom) in enumerate(clusters, start=1):
        caption = None
        for ln in captions:
            overlaps = ln["x0"] < x1 and ln["x1"] > x0
            if overlaps and (0 <= ln["top"] - bottom <= 60 or 0 <= top - ln["bottom"] <= 60):
                caption = ln["text"].strip()
                break
        figures.append(Figure(f"p{page_no}f{i}", page_no, x0, top, x1, bottom, caption))
    return figures


def pdf_info(path: Path, page_no: int) -> tuple[int, float, float]:
    """(page count, page width, page height) in points."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[min(page_no, len(pdf.pages)) - 1]
        return len(pdf.pages), float(page.width), float(page.height)


def render_page(path: Path, page_no: int, dpi: int) -> Image.Image:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return pdf[page_no - 1].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def crop_pdf(path: Path, page_no: int, bbox: tuple[float, float, float, float], dpi: int = 200):
    """Render a region (points, origin top-left) and return the words inside it, normalized to the crop."""
    x0, top, x1, bottom = bbox
    scale = dpi / 72
    image = render_page(path, page_no, dpi).crop(
        (round(x0 * scale), round(top * scale), round(x1 * scale), round(bottom * scale))
    )
    w, h = x1 - x0, bottom - top
    with pdfplumber.open(path) as pdf:
        words = pdf.pages[page_no - 1].within_bbox(bbox).extract_words()
    boxes = [
        {
            "text": wd["text"],
            "left": (wd["x0"] - x0) / w,
            "top": (wd["top"] - top) / h,
            "width": (wd["x1"] - wd["x0"]) / w,
            "height": (wd["bottom"] - wd["top"]) / h,
        }
        for wd in words
    ]
    return image, boxes


def pdf_overlay(path: Path, page_no: int, figures: list[Figure], dpi: int = 100) -> Image.Image:
    """Page with numbered figure boxes and a 10 % grid, so Claude can point at regions."""
    image = render_page(path, page_no, dpi)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for i in range(1, 10):
        x, y = w * i / 10, h * i / 10
        draw.line([(x, 0), (x, h)], fill=(120, 160, 255), width=1)
        draw.line([(0, y), (w, y)], fill=(120, 160, 255), width=1)
        draw.text((x + 2, 2), f"{i * 10}%", fill=(40, 80, 200))
        draw.text((2, y + 2), f"{i * 10}%", fill=(40, 80, 200))
    scale = dpi / 72
    for f in figures:
        box = (f.x0 * scale, f.top * scale, f.x1 * scale, f.bottom * scale)
        draw.rectangle(box, outline=(220, 30, 30), width=3)
        draw.text((box[0] + 4, box[1] + 4), f.id, fill=(220, 30, 30))
    return image


def _pages(spec: str, count: int) -> list[int]:
    pages: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.update(range(max(int(a), 1), min(int(b or a), count) + 1))
    if not pages:
        raise ToolError(f"No pages selected; the PDF has {count} pages.")
    return sorted(pages)[:MAX_PAGES]


# --- tools ---------------------------------------------------------------------------


@tool("Stage image", DRAFT_ONLY)
async def stage_image(
    ctx: Ctx,
    source: Annotated[
        str, Field(description="Image or PDF path (absolute or relative to the workspace), or an image URL")
    ],
    page: Annotated[int | None, Field(description="PDF page (1-based); required for PDFs")] = None,
    figure: Annotated[str | None, Field(description="Figure id from pdf_figures, e.g. 'p3f1'")] = None,
    region: Annotated[
        list[float] | None,
        Field(
            min_length=4,
            max_length=4,
            description="PDF region [left, top, right, bottom] as fractions of the page (read them off the pdf_figures grid)",
        ),
    ] = None,
    max_px: Annotated[int, Field(ge=200, le=2400)] = 1200,
    show: bool = True,
) -> list[Any]:
    """Prepare an image for a card. Returns an <img> tag to put into a field. Nothing is written to Anki before the review."""
    a = app(ctx)
    meta: dict[str, Any] = {"source": source}
    if source.lower().endswith(".pdf"):
        path = resolve_path(source, a.roots, {".pdf"})
        if page is None:
            raise ToolError("PDF sources need 'page'.")
        if figure:
            found = {f.id: f for f in await asyncio.to_thread(find_figures, path, page)}
            if figure not in found:
                raise ToolError(f"No figure '{figure}' on page {page}. Found: {', '.join(found) or 'none'}")
            f = found[figure]
            bbox = (f.x0, f.top, f.x1, f.bottom)
            meta["caption"] = f.caption
        else:
            _, width, height = await asyncio.to_thread(pdf_info, path, page)
            left, top, right, bottom = region or [0, 0, 1, 1]
            bbox = (left * width, top * height, right * width, bottom * height)
        image, boxes = await asyncio.to_thread(crop_pdf, path, page, bbox)
        meta["boxes"] = boxes
    else:
        image = trim(await load_image(source, a.roots))
    staged = a.media.put(downscale(image, max_px), meta)
    text = f"{staged.ref} staged ({staged.width}x{staged.height}). Put {img_tag(staged)} into a field."
    return [text, thumbnail(staged)] if show else [text]


@tool("Find figures in PDF", READ_ONLY)
async def pdf_figures(
    ctx: Ctx,
    path: str,
    pages: Annotated[str, Field(description="e.g. '3' or '2-5,8'")] = "1",
    overlay: Annotated[
        bool, Field(description="Also return the page with numbered boxes and a 10% grid (first page only)")
    ] = False,
) -> list[Any]:
    """Find figures (diagrams, images, plots) in a PDF with their captions."""
    pdf_path = resolve_path(path, app(ctx).roots, {".pdf"})
    count, _, _ = await asyncio.to_thread(pdf_info, pdf_path, 1)
    selected = _pages(pages, count)
    lines, first_figures = [], []
    for page_no in selected:
        figures = await asyncio.to_thread(find_figures, pdf_path, page_no)
        if page_no == selected[0]:
            first_figures = figures
        _, width, height = await asyncio.to_thread(pdf_info, pdf_path, page_no)
        for f in figures:
            pos = f"x {f.x0 / width:.0%}-{f.x1 / width:.0%}, y {f.top / height:.0%}-{f.bottom / height:.0%}"
            lines.append(f"{f.id} · page {page_no} · {pos}" + (f" · {f.caption}" if f.caption else ""))
    out: list[Any] = ["\n".join(lines) or "No figures found. Use overlay=true and pass a region to stage_image."]
    if overlay:
        image = await asyncio.to_thread(pdf_overlay, pdf_path, selected[0], first_figures)
        out.append(McpImage(data=png_bytes(downscale(image, 1000)), format="png"))
    return out


@tool("Render graph", DRAFT_ONLY)
async def render_graph(
    ctx: Ctx,
    dot: Annotated[str, Field(description="Graphviz DOT source, e.g. 'digraph { A -> B }'")],
    show: bool = True,
) -> list[Any]:
    """Draw a graph, tree or automaton with Graphviz in a consistent style. Node labels can later be masked by image occlusion."""
    image, boxes = await asyncio.to_thread(render_dot, dot)
    staged = app(ctx).media.put(image, {"source": "graphviz", "boxes": boxes})
    # Rendered at 200 dpi: showing it at half its pixel width keeps it sharp and card-sized.
    tag = img_tag(staged, staged.width // 2)
    text = f"{staged.ref} rendered ({staged.width}x{staged.height}). Put {tag} into a field."
    return [text, thumbnail(staged)] if show else [text]
