import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_SHAPE = re.compile(
    r"\{\{c(\d+)::image-occlusion:rect:left=([\d.]+):top=([\d.]+):width=([\d.]+):height=([\d.]+)(:oi=1)?\}\}"
)


@dataclass
class Mask:
    left: float
    top: float
    width: float
    height: float
    group: int = 0


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


def find_label(labels: list[dict[str, Any]], text: str, pad: float = 0.01) -> Mask | None:
    """Box around consecutive words (or one graph node) that spell the text."""
    wanted = [_norm(t) for t in text.split() if _norm(t)]
    words = [_norm(b["text"]) for b in labels]
    for i in range(len(labels) - len(wanted) + 1):
        if wanted and words[i : i + len(wanted)] == wanted:
            hit = labels[i : i + len(wanted)]
            left = max(min(b["left"] for b in hit) - pad, 0.0)
            top = max(min(b["top"] for b in hit) - pad, 0.0)
            right = min(max(b["left"] + b["width"] for b in hit) + pad, 1.0)
            bottom = min(max(b["top"] + b["height"] for b in hit) + pad, 1.0)
            return Mask(left, top, right - left, bottom - top)
    whole = _norm(text)
    for b in labels:
        if _norm(b.get("name", "")) == whole:
            return Mask(b["left"], b["top"], b["width"], b["height"])
    return None


def draw_masks(image: Image.Image, masks: list[Mask]) -> Image.Image:
    """The image with every mask as a translucent box, labelled with its card (c1, c2, ...)."""
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
