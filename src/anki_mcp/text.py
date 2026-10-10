"""Field content as text: for search results, the chat preview and formatting checks."""

import html
import re

_IMAGE = re.compile(r'<img\b[^>]*?\bsrc="([^"]*)"[^>]*>', re.IGNORECASE)
_ANY_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BREAK = re.compile(r"<br\s*/?>|</(?:div|p|li|ul|ol|pre)>", re.IGNORECASE)
_ITEM = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_CLOZE = re.compile(r"\{\{c(\d+)::")


def strip_html(value: str) -> str:
    """One line of plain text."""
    text = _ANY_IMAGE.sub(" [image] ", value)
    text = _TAG.sub("", _BREAK.sub(" ", text))
    return " ".join(html.unescape(text).split())


def readable(value: str) -> str:
    """Field content for the chat: line breaks kept, images as [image: name], other markup removed."""
    text = _IMAGE.sub(lambda m: f"\n[image: {m[1]}]\n", value)
    text = _ITEM.sub("\n- ", text)
    text = _TAG.sub("", _BREAK.sub("\n", text))
    lines = (_SPACE.sub(" ", line).strip() for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cloze_ords(fields: dict[str, str]) -> list[int]:
    return sorted({int(n) for value in fields.values() for n in _CLOZE.findall(value)})


_MATH = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)
_CODE = re.compile(r"<(pre|code)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_LOOSE_LATEX = re.compile(r"\\[a-zA-Z]+|[_^]\{")
_DOLLAR_MATH = re.compile(r"\$\$?[^$\s\d][^$]*\$|\[/?\$\$?\]|\[/?latex\]")
_RAW_LT = re.compile(r"<(?!br\s*/?>)", re.IGNORECASE)


def lint(fields: dict[str, str]) -> list[str]:
    """Formatting slips that Anki accepts but renders wrong."""
    problems = []
    for name, value in fields.items():
        if value.count("\\(") != value.count("\\)") or value.count("\\[") != value.count("\\]"):
            problems.append(f"{name}: unbalanced \\( \\) or \\[ \\]")
            continue
        maths = _MATH.findall(value)
        outside = _TAG.sub(" ", _MATH.sub(" ", _CODE.sub(" ", value)))
        if m := _DOLLAR_MATH.search(outside):
            problems.append(f"{name}: '{m[0][:30]}' does not render in Anki, use \\( \\) or \\[ \\]")
        elif loose := next((word for word in outside.split() if _LOOSE_LATEX.search(word)), None):
            problems.append(f"{name}: LaTeX outside \\( \\): '{loose}'")
        if any(_RAW_LT.search(math) for math in maths):
            problems.append(f"{name}: '<' inside math is read as HTML, write \\lt")
        if "{{c" in value and "}}}" in value:
            problems.append(f"{name}: '}}}}}}' ends the cloze too early, put a space before the closing braces")
    return problems
