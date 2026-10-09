import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, path: Path):
        self._path = path

    def append(self, entry: dict[str, Any]) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def find(self, batch_id: str) -> dict[str, Any] | None:
        for entry in reversed(self.entries()):
            if entry.get("batch_id") == batch_id and entry.get("kind") != "undo":
                return entry
        return None

    def is_undone(self, batch_id: str) -> bool:
        return any(e.get("undo_of") == batch_id for e in self.entries())
