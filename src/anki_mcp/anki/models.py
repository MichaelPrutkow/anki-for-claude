import time
from dataclasses import dataclass
from typing import Any, Literal

from anki_mcp.anki.client import AnkiClient, AnkiError

Kind = Literal["basic", "cloze", "io"]

IO_STOCK_KIND = 6
CLOZE_TYPE = 1
IO_TAGS = {0: "occlusion", 1: "image", 2: "header", 3: "back_extra", 4: "comments"}
CACHE_SECONDS = 300.0


@dataclass(frozen=True)
class NoteType:
    name: str
    kind: Kind
    fields: tuple[str, ...]
    io_fields: dict[str, str] | None = None

    @classmethod
    def from_anki(cls, model: dict[str, Any]) -> "NoteType":
        flds = sorted(model["flds"], key=lambda f: f["ord"])
        names = tuple(f["name"] for f in flds)
        if model.get("originalStockKind") == IO_STOCK_KIND:
            io_fields: dict[str, str] = {}
            for f in flds:
                tag = f.get("tag")
                key = IO_TAGS.get(tag if tag is not None else f["ord"])
                if key:
                    io_fields[key] = f["name"]
            return cls(model["name"], "io", names, io_fields)
        kind: Kind = "cloze" if model.get("type") == CLOZE_TYPE else "basic"
        return cls(model["name"], kind, names)


def normalize_fields(
    nt: NoteType, fields: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    lookup = {name.lower(): name for name in nt.fields}
    if nt.io_fields:
        lookup.update(nt.io_fields)
    normalized: dict[str, str] = {}
    unknown: list[str] = []
    for key, value in fields.items():
        real = lookup.get(key.strip().lower())
        if real is None:
            unknown.append(key)
        else:
            normalized[real] = value
    return normalized, unknown


class NoteTypes:
    def __init__(self, anki: AnkiClient):
        self._anki = anki
        self._cache: dict[str, NoteType] = {}
        self._loaded_at = 0.0

    async def all(self) -> list[NoteType]:
        if self._stale():
            await self._reload()
        return list(self._cache.values())

    async def get(self, name: str) -> NoteType:
        if self._stale() or name not in self._cache:
            await self._reload()
        if name not in self._cache:
            available = ", ".join(sorted(self._cache))
            raise AnkiError(f"Notiztyp '{name}' gibt es nicht. Vorhanden: {available}")
        return self._cache[name]

    def _stale(self) -> bool:
        return time.monotonic() - self._loaded_at > CACHE_SECONDS

    async def _reload(self) -> None:
        names = await self._anki.invoke("modelNames")
        models = await self._anki.invoke("findModelsByName", modelNames=names)
        self._cache = {m["name"]: NoteType.from_anki(m) for m in models}
        self._loaded_at = time.monotonic()
