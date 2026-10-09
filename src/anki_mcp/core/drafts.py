import asyncio
import os
import re
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

_DRAFT_ID = re.compile(r"d_[0-9a-f]{6}")


class DraftNotFound(LookupError):
    pass


class NoteIn(BaseModel):
    fields: dict[str, str] = Field(
        description="Field name -> content (HTML), names as listed by 'overview'"
    )
    tags: list[str] = []
    note_type: str | None = Field(
        default=None, description="Overrides the draft's note type for this note"
    )
    deck: str | None = Field(
        default=None, description="Overrides the draft's deck for this note"
    )


class DraftNote(BaseModel):
    n: int = 0
    deck: str
    note_type: str
    fields: dict[str, str]
    tags: list[str] = []
    error: str | None = None


class Draft(BaseModel):
    id: str
    title: str | None = None
    deck: str
    note_type: str
    tags: list[str] = []
    allow_duplicate: bool = False
    created: datetime
    updated: datetime
    next_n: int = 1
    notes: list[DraftNote] = []


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DraftStore:
    def __init__(self, root: Path, max_age_days: int = 14):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_age = timedelta(days=max_age_days)
        self._locks: dict[str, asyncio.Lock] = {}

    def create(
        self,
        *,
        deck: str,
        note_type: str,
        tags: list[str],
        title: str | None,
        allow_duplicate: bool,
    ) -> Draft:
        now = _now()
        draft = Draft(
            id="d_" + secrets.token_hex(3),
            title=title,
            deck=deck,
            note_type=note_type,
            tags=tags,
            allow_duplicate=allow_duplicate,
            created=now,
            updated=now,
        )
        self._save(draft)
        return draft

    def load(self, draft_id: str) -> Draft:
        path = self._path(draft_id)
        if not path.exists():
            raise DraftNotFound(
                f"Draft '{draft_id}' does not exist. Call draft_show to list open drafts."
            )
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))

    @asynccontextmanager
    async def edit(self, draft_id: str) -> AsyncGenerator[Draft, None]:
        lock = self._locks.setdefault(draft_id, asyncio.Lock())
        async with lock:
            draft = self.load(draft_id)
            yield draft
            draft.updated = _now()
            self._save(draft)

    def all(self) -> list[Draft]:
        drafts = [
            Draft.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self._root.glob("d_*.json")
        ]
        return sorted(drafts, key=lambda d: d.updated, reverse=True)

    def delete(self, draft_id: str) -> None:
        self._path(draft_id).unlink(missing_ok=True)

    def cleanup(self) -> None:
        cutoff = _now() - self._max_age
        for draft in self.all():
            if draft.updated < cutoff:
                self.delete(draft.id)

    def _path(self, draft_id: str) -> Path:
        if not _DRAFT_ID.fullmatch(draft_id):
            raise DraftNotFound(f"'{draft_id}' is not a valid draft id.")
        return self._root / f"{draft_id}.json"

    def _save(self, draft: Draft) -> None:
        path = self._path(draft.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(draft.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)
