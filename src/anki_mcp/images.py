"""Images for cards: image files, PDF figures and Graphviz drawings. They are saved in a folder the user can
open, and Anki gets a copy when a card that uses one is committed."""

import asyncio
import base64
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import Image as McpImage
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image, ImageChops, UnidentifiedImageError
from pydantic import Field

from anki_mcp import pdf
from anki_mcp.server import DRAFT, READ_ONLY, App, Ctx, app, tool

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_DOWNLOAD_BYTES = 10_000_000
MAX_PX = 1200
THUMBNAIL_PX = 512

_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)


@dataclass
class StagedImage:
    name: str
    path: Path
    width: int
    height: int
    labels: list[dict[str, Any]] = field(default_factory=list)  # words or graph nodes, for occlusion by label

    def tag(self, width: int | None = None) -> str:
        size = f' width="{width}"' if width else ""
        return f'<img src="{self.name}"{size}>'


class ImageStore:
    """PNG files in a folder the user can open. Text positions for image occlusion live in a hidden subfolder."""

    def __init__(self, folder: Path):
        self.folder = folder
        self._labels = folder / ".labels"

    def save(self, image: Image.Image, name: str, labels: list[dict[str, Any]] | None = None) -> StagedImage:
        """Save under the given name. If a different image already has that name, a number is appended."""
        self._labels.mkdir(parents=True, exist_ok=True)
        data = png_bytes(image)
        stem, n = _file_stem(name), 1
        while True:
            filename = f"{stem}.png" if n == 1 else f"{stem}-{n}.png"
            path = self.folder / filename
            if not path.exists() or path.read_bytes() == data:
                break
            n += 1
        path.write_bytes(data)
        label_file = self._labels / f"{filename}.json"
        if labels:
            label_file.write_text(json.dumps(labels), encoding="utf-8")
        else:
            label_file.unlink(missing_ok=True)
        return StagedImage(filename, path, image.width, image.height, labels or [])

    def save_preview(self, image: Image.Image, name: str) -> Path:
        """A picture only for the user to look at. Replaces an older one with the same name."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        path.write_bytes(png_bytes(image))
        return path

    def get(self, name: str) -> StagedImage:
        if not self.has(name):
            raise ToolError(f"There is no image '{name}' in {self.folder}. Create it with stage_image or render_graph.")
        path = self.folder / name
        with Image.open(path) as img:
            width, height = img.size
        label_file = self._labels / f"{name}.json"
        labels = json.loads(label_file.read_text(encoding="utf-8")) if label_file.exists() else []
        return StagedImage(name, path, width, height, labels)

    def has(self, name: str) -> bool:
        return Path(name).name == name and (self.folder / name).is_file()


def _file_stem(name: str) -> str:
    stem = Path(name).stem if Path(name).suffix.lower() in IMAGE_SUFFIXES else name
    ascii_only = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "-", ascii_only).strip("-")[:60] or "image"


def local_images(value: str) -> list[str]:
    """File names of the images in a field, without web and data URLs."""
    return [m[2] for m in _IMG_SRC.finditer(value) if not m[2].startswith(("http://", "https://", "data:"))]


def replace_images(value: str, names: dict[str, str]) -> str:
    return _IMG_SRC.sub(lambda m: m[1] + names.get(m[2], m[2]) + m[3], value)


async def upload_images(a: App, names: list[str]) -> dict[str, str]:
    """Copy images from the folder into Anki's media. Returns file name -> name in Anki; failed ones are missing."""
    if not names:
        return {}
    calls = []
    for name in names:
        data = base64.b64encode((a.images.folder / name).read_bytes()).decode()
        calls.append(("storeMediaFile", {"filename": name, "data": data, "deleteExisting": False}))
    results = await a.anki.multi(calls)
    return {name: result for name, result in zip(names, results, strict=True) if isinstance(result, str)}


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


def thumbnail(image: Image.Image) -> McpImage:
    return McpImage(data=png_bytes(downscale(image, THUMBNAIL_PX)), format="png")


def trim(image: Image.Image, margin: int = 8) -> Image.Image:
    """Cut away a uniform border (the colour of the top-left pixel)."""
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


def resolve_path(source: str, suffixes: set[str]) -> Path:
    """A file on the user's computer, by absolute path."""
    path = Path(source).expanduser()
    if path.suffix.lower() not in suffixes:
        raise ToolError(f"'{source}': only {', '.join(sorted(suffixes))} files can be opened.")
    if not path.is_absolute():
        raise ToolError(f"'{source}' is not an absolute path. Pass the full path of the file on the user's computer.")
    if path.is_file():
        return path
    raise ToolError(
        f"'{source}' is not on the user's computer. Pass an absolute path. Files attached to the chat are not on "
        "the user's computer: save the file there first, or ask the user where it is."
    )


async def load_image(source: str) -> Image.Image:
    try:
        if source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
                response = await http.get(source)
                response.raise_for_status()
            if len(response.content) > MAX_DOWNLOAD_BYTES:
                raise ToolError("The image is larger than 10 MB.")
            with Image.open(io.BytesIO(response.content)) as img:
                return img.convert("RGB")
        with Image.open(resolve_path(source, IMAGE_SUFFIXES)) as img:
            return img.convert("RGB")
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not download '{source}': {exc}") from None
    except UnidentifiedImageError:
        raise ToolError(f"'{source}' is not an image.") from None


def _box(region: list[float] | None) -> pdf.Box | None:
    if region is None:
        return None
    left, top, right, bottom = region
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ToolError("region is [left, top, right, bottom] with 0 <= left < right <= 1 and 0 <= top < bottom <= 1.")
    return left, top, right, bottom


def _saved(a: App, image: StagedImage, tag: str) -> str:
    text = f"Saved {image.name} ({image.width}x{image.height} px) in {a.images.folder}. Put {tag} into a card field."
    if image.labels:
        text += f" It has {len(image.labels)} text labels, so draft_add_occlusion can place masks by label."
    return text


# --- Graphviz ------------------------------------------------------------------------

GRAPH_PAD = 0.06  # inches; without it, node outlines at the edge get cut off
GRAPH_STYLE = (
    f'graph [pad={GRAPH_PAD}, dpi=200, bgcolor="white", fontname="Helvetica"];'
    ' node [fontname="Helvetica", fontsize=16, penwidth=1.6];'
    ' edge [fontname="Helvetica", fontsize=14, penwidth=1.6, arrowsize=0.8];'
)
_FILE_ATTRIBUTES = re.compile(r"\b(image|shapefile|imagepath|fontpath|imagescale)\s*=", re.IGNORECASE)


def dot_command() -> str | None:
    # Apps started from the macOS Dock do not have Homebrew's folders in PATH.
    return shutil.which("dot") or shutil.which("dot", path=os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"]))


def render_dot(source: str) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Render DOT in the plugin's style. Returns the image and the node boxes as fractions of the image."""
    if _FILE_ATTRIBUTES.search(source):
        raise ToolError("DOT attributes that read files (image, shapefile, ...) are not allowed.")
    brace = source.find("{")
    if brace < 0:
        raise ToolError("Not a DOT graph: '{' is missing.")
    dot = dot_command()
    if not dot:
        raise ToolError("Graphviz is not installed. Ask the user to install it (macOS: brew install graphviz).")

    with tempfile.TemporaryDirectory() as tmp:
        png, plain = Path(tmp, "g.png"), Path(tmp, "g.txt")
        try:
            run = subprocess.run(
                [dot, "-Tpng", "-o", str(png), "-Tplain", "-o", str(plain)],
                input=(source[: brace + 1] + GRAPH_STYLE + source[brace + 1 :]).encode(),
                capture_output=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ToolError("Graphviz took longer than 10 seconds. Make the graph smaller.") from None
        if run.returncode != 0:
            raise ToolError("Graphviz error: " + run.stderr.decode(errors="replace").strip())
        with Image.open(png) as img:
            image = img.convert("RGB")
        lines = plain.read_text(encoding="utf-8").splitlines()

    # -Tplain gives inches from the bottom left, without the padding around the drawing.
    width = height = 1.0
    labels = []
    for line in lines:
        parts = shlex.split(line)
        if parts[0] == "graph":
            width, height = float(parts[2]) + 2 * GRAPH_PAD, float(parts[3]) + 2 * GRAPH_PAD
        elif parts[0] == "node":
            name, x, y, w, h, text = parts[1], *map(float, parts[2:6]), parts[6]
            labels.append(
                {
                    "name": name,
                    "text": text,
                    "left": (x + GRAPH_PAD - w / 2) / width,
                    "top": 1 - (y + GRAPH_PAD + h / 2) / height,
                    "width": w / width,
                    "height": h / height,
                }
            )
    return image, labels


# --- tools ---------------------------------------------------------------------------


@tool("Save an image for a card", DRAFT)
async def stage_image(
    ctx: Ctx,
    source: Annotated[str, Field(description="Image or PDF on the user's computer (absolute path), or an image URL")],
    name: Annotated[str, Field(description="Short file name, e.g. 'mitral-valve'")],
    figure: Annotated[str | None, Field(description="PDF: figure id from pdf_figures, e.g. 'p3f1'")] = None,
    page: Annotated[int | None, Field(ge=1, description="PDF: page number, when no figure is given")] = None,
    region: Annotated[
        list[float] | None,
        Field(
            min_length=4,
            max_length=4,
            description="Part to cut out: [left, top, right, bottom] as fractions (0-1) of the page or image",
        ),
    ] = None,
) -> list[Any]:
    """Save an image file, a PDF figure or part of a PDF page for a card and return its <img> tag.

    The image goes into the user's images folder; Anki gets a copy with draft_commit. Look at the returned thumbnail.
    """
    a = app(ctx)
    box = _box(region)
    labels: list[dict[str, Any]] = []
    if source.lower().endswith(".pdf"):
        path = resolve_path(source, {".pdf"})
        if figure:
            page = pdf.page_of(figure)
            box = await asyncio.to_thread(pdf.figure_box, path, figure)
        elif page is None:
            raise ToolError("For a PDF, pass 'figure' (an id from pdf_figures) or 'page'.")
        image, labels = await asyncio.to_thread(pdf.crop, path, page, box or (0, 0, 1, 1))
    else:
        image = await load_image(source)
        if box:
            w, h = image.size
            image = image.crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))
        else:
            image = trim(image)
    staged = a.images.save(downscale(image, MAX_PX), name, labels)
    return [_saved(a, staged, staged.tag()), thumbnail(image)]


@tool("Find figures in a PDF", READ_ONLY)
async def pdf_figures(
    ctx: Ctx,
    path: Annotated[str, Field(description="PDF on the user's computer (absolute path)")],
    pages: Annotated[str, Field(description="Pages to search, e.g. '3' or '2-5,8' (at most 20)")] = "1",
    show_page: Annotated[
        bool, Field(description="Also return the first page as a picture, with the figures boxed and a 10% grid")
    ] = False,
) -> list[Any]:
    """List the figures (diagrams, photos, plots) on PDF pages with their ids, regions and captions."""
    pdf_path = resolve_path(path, {".pdf"})
    selected, figures = await asyncio.to_thread(pdf.find_figures, pdf_path, pages)
    where = f"page {pages}" if pages.strip().isdigit() else f"pages {pages}"
    if figures:
        count = "1 figure" if len(figures) == 1 else f"{len(figures)} figures"
        lines = [f"{count} on {where}. Pass the id to stage_image as 'figure':"]
        for f in figures:
            region = ", ".join(f"{v:.2f}" for v in f.box)
            lines.append(f"{f.id}: region [{region}]" + (f', caption "{f.caption}"' if f.caption else ""))
    else:
        lines = [f"No figures found on {where}. Call again with show_page=true and cut out a region with stage_image."]
    out: list[Any] = ["\n".join(lines)]
    if show_page:
        image = await asyncio.to_thread(pdf.overview, pdf_path, selected[0], figures)
        out.append(McpImage(data=png_bytes(downscale(image, 1000)), format="png"))
    return out


@tool("Draw a graph", DRAFT)
async def render_graph(
    ctx: Ctx,
    dot: Annotated[str, Field(description="Graphviz DOT source, e.g. 'digraph { A -> B }'")],
    name: Annotated[str, Field(description="Short file name, e.g. 'dfs-tree'")],
) -> list[Any]:
    """Draw a graph, tree or automaton with Graphviz and return its <img> tag for a card field.

    The image goes into the user's images folder. Node labels can be hidden later with draft_add_occlusion.
    """
    a = app(ctx)
    image, labels = await asyncio.to_thread(render_dot, dot)
    staged = a.images.save(image, name, labels)
    # Rendered at 200 dpi: shown at half its pixel width it stays sharp and card-sized.
    return [_saved(a, staged, staged.tag(staged.width // 2)), thumbnail(image)]
