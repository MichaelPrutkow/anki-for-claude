import html
import re

_IMAGES = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BREAKS = re.compile(r"<\s*(br|/div|/p|/li)\s*/?>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def strip_html(value: str) -> str:
    text = _IMAGES.sub(" [BILD] ", value)
    text = _BREAKS.sub(" ", text)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
