"""An in-memory AnkiConnect with just enough of the API for the plugin's tools."""

import base64
import json
import re
from typing import Any

import httpx

MODELS = [
    {"name": "Basic", "type": 0, "flds": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}]},
    {"name": "Cloze", "type": 1, "flds": [{"name": "Text", "ord": 0}, {"name": "Back Extra", "ord": 1}]},
    {
        "name": "Image Occlusion",
        "type": 1,
        "originalStockKind": 6,
        "flds": [
            {"name": "Occlusion", "ord": 0, "tag": 0},
            {"name": "Image", "ord": 1, "tag": 1},
            {"name": "Header", "ord": 2, "tag": 2},
            {"name": "Back Extra", "ord": 3, "tag": 3},
            {"name": "Comments", "ord": 4, "tag": 4},
        ],
    },
]


class FakeAnki:
    def __init__(self) -> None:
        self.decks = {"Default": 1, "Math": 2, "Math::Analysis": 3}
        self.notes: dict[int, dict[str, Any]] = {}
        self.media: dict[str, bytes] = {}
        self._next_id = 1000

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=self.call(json.loads(request.content)))

        return httpx.MockTransport(handle)

    def call(self, body: dict[str, Any]) -> dict[str, Any]:
        action = getattr(self, body["action"], None)
        if action is None:
            return {"result": None, "error": f"unsupported action: {body['action']}"}
        try:
            return {"result": action(**body.get("params", {})), "error": None}
        except (ValueError, KeyError, OSError) as exc:  # AnkiConnect reports failures as an error string
            return {"result": None, "error": str(exc)}

    def add_user_note(self, front: str, back: str) -> int:
        """A note the user wrote, without the plugin's tag."""
        return self.addNote({"deckName": "Math", "modelName": "Basic", "fields": {"Front": front, "Back": back}})

    # --- actions ---

    def version(self) -> int:
        return 6

    def multi(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.call(action) for action in actions]

    def deckNames(self) -> list[str]:
        return list(self.decks)

    def deckNamesAndIds(self) -> dict[str, int]:
        return dict(self.decks)

    def createDeck(self, deck: str) -> int:
        self.decks.setdefault(deck, len(self.decks) + 1)
        return self.decks[deck]

    def getDeckStats(self, decks: list[str]) -> dict[str, Any]:
        out = {}
        for name in decks:
            total = sum(1 for n in self.notes.values() if n["deck"] == name)
            out[str(self.decks[name])] = {
                "total_in_deck": total,
                "new_count": total,
                "learn_count": 0,
                "review_count": 0,
            }
        return out

    def modelNames(self) -> list[str]:
        return [m["name"] for m in MODELS]

    def findModelsByName(self, modelNames: list[str]) -> list[dict[str, Any]]:
        return [m for m in MODELS if m["name"] in modelNames]

    def canAddNotesWithErrorDetail(self, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for note in notes:
            try:
                self._validate(note)
                out.append({"canAdd": True})
            except ValueError as exc:
                out.append({"canAdd": False, "error": str(exc)})
        return out

    def addNote(self, note: dict[str, Any]) -> int:
        self._validate(note)
        if note["deckName"] not in self.decks:
            raise ValueError("deck was not found")
        self._next_id += 1
        model = next(m for m in MODELS if m["name"] == note["modelName"])
        self.notes[self._next_id] = {
            "noteId": self._next_id,
            "modelName": note["modelName"],
            "deck": note["deckName"],
            "tags": list(note.get("tags", [])),
            "fields": {
                f["name"]: {"value": note["fields"].get(f["name"], ""), "order": f["ord"]} for f in model["flds"]
            },
            "mod": 1,
        }
        return self._next_id

    def notesInfo(self, notes: list[int]) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(self.notes[n])) if n in self.notes else {} for n in notes]

    def updateNoteFields(self, note: dict[str, Any]) -> None:
        stored = self.notes[note["id"]]
        for name, value in note["fields"].items():
            stored["fields"][name]["value"] = value
        stored["mod"] += 1

    def deleteNotes(self, notes: list[int]) -> None:
        for n in notes:
            self.notes.pop(n, None)

    def findNotes(self, query: str) -> list[int]:
        if m := re.fullmatch(r"tag:(\S+)", query):
            return [n for n, note in self.notes.items() if m[1] in note["tags"]]
        if m := re.fullmatch(r"nid:([\d,]+)", query):
            return [int(n) for n in m[1].split(",") if int(n) in self.notes]
        if m := re.fullmatch(r"deck:(\S+)", query):
            return [n for n, note in self.notes.items() if note["deck"] == m[1]]
        return list(self.notes)

    def storeMediaFile(self, filename: str, data: str, deleteExisting: bool = True) -> str:
        content = base64.b64decode(data)
        if filename in self.media and self.media[filename] != content and not deleteExisting:
            filename = filename.replace(".png", "-1.png")
        self.media[filename] = content
        return filename

    def findCards(self, query: str) -> list[int]:
        return []

    def sync(self) -> None:
        return None

    def _validate(self, note: dict[str, Any]) -> None:
        model = next((m for m in MODELS if m["name"] == note["modelName"]), None)
        if model is None:
            raise ValueError("model was not found")
        first = model["flds"][0]["name"]
        value = note["fields"].get(first, "")
        if not value.strip():
            raise ValueError("cannot create note because it is empty")
        if model["type"] == 1 and "{{c" not in value:
            raise ValueError("cannot create note for unknown reason")
        if not note.get("options", {}).get("allowDuplicate"):
            for other in self.notes.values():
                if other["modelName"] == note["modelName"] and other["fields"][first]["value"] == value:
                    raise ValueError("cannot create note because it is a duplicate")
