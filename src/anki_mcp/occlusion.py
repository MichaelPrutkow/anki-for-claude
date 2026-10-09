import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from anki_mcp.anki import NoteType

_SHAPE = re.compile(
    r"\{\{c(\d+)::image-occlusion:rect:left=([\d.]+):top=([\d.]+):width=([\d.]+):height=([\d.]+)(:oi=1)?\}\}"
)
_IMG_SRC = re.compile(r'<img[^>]*src="([^"]+)"')


@dataclass
class Mask:
    left: float
    top: float
    width: float
    height: float
    group: int


def build_field(masks: list[Mask], hide_all: bool) -> str:
    """Anki's Image Occlusion syntax. Coordinates are fractions of the image size."""
    oi = ":oi=1" if hide_all else ""
    return "<br>".join(
        f"{{{{c{m.group}::image-occlusion:rect:left={m.left:.4f}:top={m.top:.4f}"
        f":width={m.width:.4f}:height={m.height:.4f}{oi}}}}}"
        for m in masks
    )


def parse_field(value: str) -> tuple[list[Mask], bool]:
    masks, hide_all = [], False
    for m in _SHAPE.finditer(value):
        masks.append(Mask(float(m[2]), float(m[3]), float(m[4]), float(m[5]), int(m[1])))
        hide_all = hide_all or bool(m[6])
    return masks, hide_all


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w]+", "", text)


def find_label(boxes: list[dict[str, Any]], label: str, pad: float = 0.01) -> Mask | None:
    """Box around consecutive words (or one graph node) that spell the label."""
    wanted = [_norm(t) for t in label.split() if _norm(t)]
    texts = [_norm(b["text"]) for b in boxes]
    for i in range(len(boxes) - len(wanted) + 1):
        if texts[i : i + len(wanted)] == wanted:
            hit = boxes[i : i + len(wanted)]
            left = min(b["left"] for b in hit) - pad
            top = min(b["top"] for b in hit) - pad
            right = max(b["left"] + b["width"] for b in hit) + pad
            bottom = max(b["top"] + b["height"] for b in hit) + pad
            left, top = max(left, 0.0), max(top, 0.0)
            return Mask(left, top, min(right, 1.0) - left, min(bottom, 1.0) - top, 0)
    whole = _norm(label)
    for b in boxes:
        if _norm(b.get("name", "")) == whole:
            return Mask(b["left"], b["top"], b["width"], b["height"], 0)
    return None


def draw_masks(image: Image.Image, masks: list[Mask]) -> Image.Image:
    """Preview for Claude: masks as translucent boxes with their card number."""
    canvas = image.convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = canvas.size
    font = ImageFont.load_default(size=max(14, h // 25))
    for m in masks:
        box = (m.left * w, m.top * h, (m.left + m.width) * w, (m.top + m.height) * h)
        draw.rectangle(box, fill=(255, 196, 0, 150), outline=(200, 120, 0, 255), width=2)
        draw.text((box[0] + 4, box[1] + 2), f"c{m.group}", fill=(0, 0, 0, 255), font=font)
    return Image.alpha_composite(canvas, layer).convert("RGB")


def io_cards(fields: dict[str, str], nt: NoteType) -> list[tuple[str, str, str]]:
    """Preview HTML for an Image Occlusion note: one (name, front, back) per group."""
    io = nt.io_fields or {}
    masks, hide_all = parse_field(fields.get(io.get("occlusion", ""), ""))
    src = _IMG_SRC.search(fields.get(io.get("image", ""), ""))
    header = fields.get(io.get("header", ""), "")
    extra = fields.get(io.get("back_extra", ""), "")
    if not src:
        return []

    def side(active: int, back: bool) -> str:
        boxes = []
        for m in masks:
            if m.group != active and not hide_all:
                continue
            color = "#ff8c8c" if m.group == active else "#ffeba2"
            if back and m.group == active:
                color = "transparent;outline:2px solid #e53935"
            boxes.append(
                f'<div style="position:absolute;left:{m.left * 100}%;top:{m.top * 100}%;'
                f'width:{m.width * 100}%;height:{m.height * 100}%;background:{color}"></div>'
            )
        body = (
            f'<div style="position:relative;display:inline-block"><img src="{src[1]}" '
            f'style="max-width:100%;display:block">{"".join(boxes)}</div>'
        )
        return f"{header}<br>{body}" + (f"<br>{extra}" if back and extra else "")

    groups = sorted({m.group for m in masks})
    return [(f"c{g}", side(g, False), side(g, True)) for g in groups]
