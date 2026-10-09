import time
from dataclasses import dataclass, field
from statistics import median
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from anki_mcp.anki import AnkiError
from anki_mcp.render import cloze_ords, strip_html, truncate
from anki_mcp.server import READ_ONLY, App, Ctx, app, tool

WEAK = "-is:new -is:suspended (tag:leech OR prop:lapses>=3 OR rated:{days}:1 OR prop:d>0.7 OR prop:r<0.75 OR flag:1 OR tag:mcp::fix)"
WEAK_WITHOUT_FSRS = "-is:new -is:suspended (tag:leech OR prop:lapses>=3 OR rated:{days}:1 OR flag:1 OR tag:mcp::fix)"
MAX_CANDIDATES = 300
MAX_REVIEWED = 5000
REVIEW = 1  # revlog type: 0 learn, 1 review, 2 relearn, 3 filtered


@dataclass
class CardStats:
    card_id: int
    note_id: int
    ord: int
    lapses: int
    reviews: int
    again: int
    median_seconds: float | None
    difficulty: float | None
    flags: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def again_rate(self) -> float:
        return self.again / self.reviews if self.reviews else 0.0


def card_stats(info: dict[str, Any], log: list[dict[str, Any]], since_ms: int) -> CardStats:
    log = sorted(log, key=lambda r: r["id"])
    window = [r for r in log if r["id"] >= since_ms]
    answers = [r for r in window if r["type"] == REVIEW]
    times = [r["time"] / 1000 for r in window if r["time"] > 0]
    fsrs = [r["factor"] for r in log if 100 <= r["factor"] <= 1100]  # FSRS stores difficulty here
    return CardStats(
        card_id=info["cardId"],
        note_id=info["note"],
        ord=info["ord"],
        lapses=info["lapses"],
        reviews=len(answers),
        again=sum(1 for r in answers if r["ease"] == 1),
        median_seconds=median(times) if times else None,
        difficulty=round(fsrs[-1] / 1000 - 0.1, 2) if fsrs else None,
    )


def score(s: CardStats) -> float:
    return round(0.5 * s.again_rate + 0.3 * min(s.lapses / 8, 1) + 0.2 * (s.difficulty or 0), 3)


def content_flags(fields: dict[str, str], is_cloze: bool) -> list[str]:
    values = [strip_html(v) for v in fields.values()]
    flags = []
    answer = values[1] if len(values) > 1 and not is_cloze else ""
    if len(answer.split()) > 15:
        flags.append("LONG_ANSWER")
    if answer.count(",") >= 2:
        flags.append("LIST_LIKE")
    if is_cloze and len(cloze_ords(fields)) > 5:
        flags.append("MANY_CLOZES")
    return flags


def _query(scope: str, rest: str) -> str:
    return f"({scope}) {rest}" if scope else rest


async def _weak_cards(a: App, scope: str, window_days: int, limit: int) -> str:
    """Rank the notes the user struggles with most."""
    try:
        ids = await a.anki.invoke("findCards", query=_query(scope, WEAK.format(days=window_days)))
    except AnkiError:  # collections without FSRS reject prop:d / prop:r
        ids = await a.anki.invoke("findCards", query=_query(scope, WEAK_WITHOUT_FSRS.format(days=window_days)))
    if not ids:
        return "No weak cards found in this scope."
    ids = ids[:MAX_CANDIDATES]
    infos, logs, leeches = await a.anki.multi(
        [
            ("cardsInfo", {"cards": ids}),
            ("getReviewsOfCards", {"cards": ids}),
            ("findCards", {"query": _query(scope, "tag:leech")}),
        ]
    )
    for result in (infos, logs, leeches):
        if isinstance(result, AnkiError):
            raise ToolError(str(result))

    since = int((time.time() - window_days * 86400) * 1000)
    rows: list[tuple[CardStats, dict[str, Any]]] = []
    for info in infos:
        if info:
            rows.append((card_stats(info, logs.get(str(info["cardId"]), []), since), info))
    times = [s.median_seconds for s, _ in rows if s.median_seconds]
    typical = median(times) if times else None
    leech_ids = set(leeches)

    worst: dict[int, tuple[CardStats, dict[str, Any], bool]] = {}
    for s, info in rows:
        nt = await a.note_types.get(info["modelName"])
        fields = {k: v["value"] for k, v in sorted(info["fields"].items(), key=lambda kv: kv[1]["order"])}
        s.flags = content_flags(fields, nt.kind == "cloze")
        if typical and s.median_seconds and s.median_seconds > 2 * typical:
            s.flags.append("SLOW")
        if s.card_id in leech_ids:
            s.flags.append("LEECH")
        if info.get("flags"):
            s.flags.append("FLAGGED")
        s.score = score(s)
        if s.note_id not in worst or s.score > worst[s.note_id][0].score:
            worst[s.note_id] = (s, {**info, "_fields": fields}, nt.kind == "cloze")

    ranked = sorted(worst.values(), key=lambda t: t[0].score, reverse=True)[:limit]
    lines = [f"{len(ranked)} weak notes (from {len(ids)} candidate cards, last {window_days} days):"]
    for i, (s, info, is_cloze) in enumerate(ranked, start=1):
        parts = [
            f"{i}. note {s.note_id}" + (f" (c{s.ord + 1})" if is_cloze else ""),
            f"score {s.score:.2f}",
            f"again {s.again_rate:.0%} of {s.reviews}",
            f"lapses {s.lapses}",
        ]
        if s.difficulty is not None:
            parts.append(f"D {s.difficulty:.2f}")
        if s.median_seconds:
            parts.append(f"{s.median_seconds:.0f}s")
        if s.flags:
            parts.append(",".join(s.flags))
        content = " | ".join(f"{k}: {truncate(strip_html(v), 80)}" for k, v in list(info["_fields"].items())[:2])
        lines.append(" · ".join(parts) + " | " + content)
    return "\n".join(lines)


async def _health(a: App, scope: str, days: int) -> str:
    """Card counts, leeches, unstudied plugin cards, reviews per day and true retention."""
    base = scope or "deck:*"
    queries = {
        "total": base,
        "new": f"{base} is:new",
        "suspended": f"{base} is:suspended",
        "leeches": f"{base} tag:leech",
        "unstudied": f"{base} tag:mcp::created is:new",
        "reviewed": f"{base} rated:{days}",
    }
    results = await a.anki.multi([("findCards", {"query": q}) for q in queries.values()])
    found: dict[str, list[int]] = {}
    for key, result in zip(queries, results, strict=True):
        if isinstance(result, AnkiError):
            raise ToolError(f"Search failed ({queries[key]}): {result}")
        found[key] = result

    reviewed = found["reviewed"][:MAX_REVIEWED]
    logs = await a.anki.invoke("getReviewsOfCards", cards=reviewed) if reviewed else {}
    since = int((time.time() - days * 86400) * 1000)
    entries = [r for log in logs.values() for r in log if r["id"] >= since]
    answers = [r for r in entries if r["type"] == 1]
    again = sum(1 for r in answers if r["ease"] == 1)
    minutes = sum(r["time"] for r in entries) / 60000

    lines = [
        f"Scope: {scope or 'whole collection'}",
        f"Cards: {len(found['total'])} · new {len(found['new'])} · suspended {len(found['suspended'])} · leeches {len(found['leeches'])}",
        f"Created by this plugin but never studied: {len(found['unstudied'])}",
        f"Last {days} days: {len(entries)} reviews ({len(entries) / days:.0f}/day), {minutes / days:.0f} min/day",
    ]
    if answers:
        lines.append(f"True retention: {1 - again / len(answers):.0%} on {len(answers)} review answers")
    return "\n".join(lines)


@tool("Study statistics", READ_ONLY)
async def stats(
    ctx: Ctx,
    scope: Annotated[str, Field(description="Anki search that limits the cards, e.g. 'deck:GAD'")] = "",
    days: Annotated[int, Field(ge=1, le=365)] = 60,
    weak_limit: Annotated[int, Field(ge=0, le=100, description="How many weak notes to list; 0 for none")] = 25,
) -> str:
    """Collection health (counts, reviews per day, true retention) and the notes the user struggles with most:
    again rate, lapses, FSRS difficulty, slow answers, leeches and flagged cards."""
    a = app(ctx)
    parts = [await _health(a, scope, days)]
    if weak_limit:
        parts.append(await _weak_cards(a, scope, days, weak_limit))
    return "\n\n".join(parts)
