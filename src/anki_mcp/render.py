import html
import re

_IMAGES = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BREAKS = re.compile(r"<\s*(br|/div|/p|/li)\s*/?>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_ANSWER_HR = re.compile(r"^\s*<hr[^>]*>", re.IGNORECASE)


def strip_html(value: str) -> str:
    text = _IMAGES.sub(" [image] ", value)
    text = _TAGS.sub("", _BREAKS.sub(" ", text))
    return _SPACE.sub(" ", html.unescape(text)).strip()


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_SECTION = re.compile(r"\{\{([#^])\s*([^}]+?)\s*\}\}(.*?)\{\{/\s*\2\s*\}\}", re.DOTALL)
_TAG = re.compile(r"\{\{(?![#^/])\s*([^}]+?)\s*\}\}")
_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.DOTALL)


def cloze_ords(fields: dict[str, str]) -> list[int]:
    found = {int(m.group(1)) for value in fields.values() for m in _CLOZE.finditer(value)}
    return sorted(found)


def _in_math(text: str, pos: int) -> bool:
    before = text[:pos]
    inline = before.count("\\(") > before.count("\\)")
    display = before.count("\\[") > before.count("\\]")
    return inline or display


def render_cloze(text: str, ord_: int, back: bool) -> str:
    def replace(m: re.Match[str]) -> str:
        n, content, hint = int(m.group(1)), m.group(2), m.group(3)
        if n != ord_:
            return content
        shown = content if back else f"[{hint or '...'}]"
        if _in_math(text, m.start()):
            # An HTML span would break MathJax, so Anki uses \class inside formulas.
            return "\\class{cloze}{" + (shown if back else f"\\text{{{shown}}}") + "}"
        return f'<span class="cloze">{shown}</span>'

    return _CLOZE.sub(replace, text)


def _field(fields: dict[str, str], name: str) -> str:
    if name in fields:
        return fields[name]
    lowered = {k.lower(): v for k, v in fields.items()}
    return lowered.get(name.lower(), "")


def render_template(
    template: str,
    fields: dict[str, str],
    *,
    front_side: str = "",
    ord_: int | None = None,
    back: bool = False,
) -> str:
    """Render a subset of Anki's template language."""

    def section(m: re.Match[str]) -> str:
        kind, name, body = m.group(1), m.group(2), m.group(3)
        filled = bool(strip_html(_field(fields, name)))
        return body if filled == (kind == "#") else ""

    previous = None
    while previous != template:
        previous, template = template, _SECTION.sub(section, template)

    def tag(m: re.Match[str]) -> str:
        *filters, name = [part.strip() for part in m.group(1).split(":")]
        if name == "FrontSide":
            return front_side
        value = _field(fields, name)
        for f in reversed(filters):
            if f == "cloze":
                value = render_cloze(value, ord_ or 1, back)
            elif f == "text":
                value = html.escape(strip_html(value))
            elif f == "hint":
                value = f"<details class='hint'><summary>Hint</summary>{value}</details>"
            elif f == "type":
                value = "<input class='type' placeholder='type answer'>"
            elif f.startswith("tts"):
                value = ""
        return value

    return _TAG.sub(tag, template)


def render_cards(
    templates: dict[str, dict[str, str]], fields: dict[str, str], is_cloze: bool
) -> list[tuple[str, str, str]]:
    """(card name, front html, answer html) for every card the note would create.

    The answer is the back template without {{FrontSide}}, so the question is not shown twice.
    """
    cards: list[tuple[str, str, str]] = []
    if is_cloze:
        name, tpl = next(iter(templates.items()))
        for ord_ in cloze_ords(fields):
            front = render_template(tpl["Front"], fields, ord_=ord_)
            back = render_template(tpl["Back"], fields, ord_=ord_, back=True)
            cards.append((f"{name} c{ord_}", front, _ANSWER_HR.sub("", back)))
        return cards

    empty = {k: "" for k in fields}
    for name, tpl in templates.items():
        front = render_template(tpl["Front"], fields)
        if strip_html(front) == strip_html(render_template(tpl["Front"], empty)):
            continue
        back = render_template(tpl["Back"], fields, back=True)
        cards.append((name, front, _ANSWER_HR.sub("", back)))
    return cards
