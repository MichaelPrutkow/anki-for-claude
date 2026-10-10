import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from fake_anki import FakeAnki
from mcp.client import Client
from PIL import Image, ImageDraw

from anki_mcp.text import lint, readable

pytestmark = pytest.mark.anyio

IMAGES = Path("Pictures/Anki for Claude")


async def call(client: Client, tool: str, **args: Any) -> str:
    result = await client.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    assert not result.is_error, text
    return text


async def fails(client: Client, tool: str, **args: Any) -> str:
    result = await client.call_tool(tool, args)
    assert result.is_error
    return "\n".join(c.text for c in result.content if c.type == "text")


def draft_id(text: str) -> str:
    match = re.search(r"d_[0-9a-f]{6}", text)
    assert match, text
    return match[0]


def batch_id(text: str) -> str:
    match = re.search(r'undo\("([0-9a-f]{8})"\)', text)
    assert match, text
    return match[1]


BASIC = {"fields": {"Front": "Warum ist \\(Q\\) invertierbar?", "Back": "Aus \\(Q^TQ = I\\) folgt es"}}
CLOZE = {
    "fields": {"Text": "Eine Äquivalenzrelation ist {{c1::reflexiv}} und {{c2::symmetrisch}}"},
    "note_type": "Cloze",
}


async def test_overview_lists_decks_and_note_types(client: Client, anki: FakeAnki) -> None:
    anki.add_user_note("a", "b")
    text = await call(client, "overview")
    assert "Math: 1 cards" in text
    assert "Empty decks: Math::Analysis" in text
    assert "Basic [basic]: Front | Back" in text
    assert "Image Occlusion [image occlusion]: Occlusion | Image | Header | Back Extra | Comments" in text


async def test_draft_edit_and_commit_in_steps(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC, CLOZE], deck="Math::Analysis", note_type="Basic")
    draft = draft_id(text)
    assert "added #1-#2" in text and "none of them is in Anki yet" in text
    assert "#1 Basic\nFront: Warum ist \\(Q\\) invertierbar?" in text
    assert "#2 Cloze (c1, c2)" in text
    assert not anki.notes

    text = await call(
        client, "draft_edit", draft_id=draft, edits=[{"card": 1, "fields": {"Back": "Weil \\(Q^T = Q^{-1}\\)"}}]
    )
    assert "changed #1" in text and "Back: Weil" in text and "#2" not in text

    text = await call(client, "draft_commit", draft_id=draft, cards=[1])
    assert "Added 1 card to Anki (#1, deck Math::Analysis)" in text
    assert "Not committed yet, still in draft" in text and "#2" in text
    [note] = anki.notes.values()
    assert note["fields"]["Back"]["value"] == "Weil \\(Q^T = Q^{-1}\\)"
    assert "mcp::created" in note["tags"]

    text = await call(client, "draft_commit", draft_id=draft)
    assert "is finished and was deleted" in text
    assert len(anki.notes) == 2
    assert await call(client, "draft_show") == "No open drafts."

    text = await call(client, "undo", batch_id=batch_id(text))
    assert "deleted 1 note" in text
    assert len(anki.notes) == 1


async def test_draft_add_reports_every_problem_and_adds_nothing(client: Client, anki: FakeAnki) -> None:
    anki.add_user_note("Warum ist \\(Q\\) invertierbar?", "x")
    cards = [
        BASIC,
        {"fields": {"Question": "x"}},
        {"fields": {"Front": "y"}, "deck": "Analysis"},
        {"fields": {"Text": "no gap"}, "note_type": "Cloze"},
        {"fields": {"Front": "z", "Back": '<img src="missing.png">'}},
    ]
    text = await fails(client, "draft_add", cards=cards, deck="Math", note_type="Basic")
    assert "Nothing was added" in text
    assert "cards[0]: cannot create note because it is a duplicate" in text
    assert "cards[1]: unknown fields ['Question']" in text
    assert "cards[2]: there is no deck 'Analysis'. Did you mean 'Math::Analysis'?" in text
    assert "cards[3]: cannot create note for unknown reason (a cloze card needs" in text
    assert "cards[4]: no image missing.png" in text
    assert await call(client, "draft_show") == "No open drafts."


async def test_new_deck_is_created_on_commit(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC], deck="Physics::Optics", note_type="Basic")
    assert "New deck, created by draft_commit: Physics::Optics" in text
    await call(client, "draft_commit", draft_id=draft_id(text))
    assert "Physics::Optics" in anki.decks


async def test_formatting_slips_are_reported(client: Client) -> None:
    card = {"fields": {"Front": "Was ist D_{C,B}?", "Back": "{{c1::x}}}"}}
    text = await call(client, "draft_add", cards=[card], deck="Math", note_type="Basic")
    assert "#1 Front: LaTeX outside \\( \\): 'D_{C,B}?'" in text


async def test_failed_card_stays_in_draft(client: Client, anki: FakeAnki) -> None:
    text = await call(
        client, "draft_add", cards=[BASIC, {"fields": {"Front": "other", "Back": "b"}}], deck="Math", note_type="Basic"
    )
    draft = draft_id(text)
    anki.add_user_note("other", "b")  # becomes a duplicate after the draft was checked
    text = await call(client, "draft_commit", draft_id=draft)
    assert "Added 1 card" in text
    assert "#2: cannot create note because it is a duplicate" in text
    shown = await call(client, "draft_show", draft_id=draft)
    assert "Last draft_commit failed: cannot create note because it is a duplicate" in shown


async def test_images_are_named_shown_and_copied_on_commit(client: Client, anki: FakeAnki, tmp_path: Path) -> None:
    picture = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(picture).rectangle((50, 50, 250, 150), fill="black")
    picture.save(tmp_path / "slide.png")

    text = await call(client, "stage_image", source=str(tmp_path / "slide.png"), name="Mitralklappe Übersicht")
    assert 'Put <img src="Mitralklappe-Ubersicht.png"> into a card field' in text
    assert (tmp_path / IMAGES / "Mitralklappe-Ubersicht.png").exists()

    card = {"fields": {"Front": "Was zeigt das Bild?", "Back": 'Das Herz<br><img src="Mitralklappe-Ubersicht.png">'}}
    text = await call(client, "draft_add", cards=[card], deck="Math", note_type="Basic")
    assert "Back: Das Herz\n  [image: Mitralklappe-Ubersicht.png]" in text
    assert f"The images are in {tmp_path / IMAGES}" in text

    await call(client, "draft_commit", draft_id=draft_id(text))
    assert "Mitralklappe-Ubersicht.png" in anki.media


async def test_same_name_different_picture_gets_a_number(client: Client, tmp_path: Path) -> None:
    for i, colour in enumerate(["red", "blue"]):
        Image.new("RGB", (100, 100), colour).save(tmp_path / f"p{i}.png")
    first = await call(client, "stage_image", source=str(tmp_path / "p0.png"), name="plot")
    second = await call(client, "stage_image", source=str(tmp_path / "p1.png"), name="plot")
    again = await call(client, "stage_image", source=str(tmp_path / "p0.png"), name="plot")
    assert "is not an absolute path" in await fails(client, "stage_image", source="p0.png", name="plot")
    assert "Saved plot.png" in first and "Saved plot-2.png" in second and "Saved plot.png" in again


async def test_files_outside_the_computer_get_a_clear_error(client: Client) -> None:
    text = await fails(client, "stage_image", source="/mnt/user-data/uploads/slides.pdf", name="x", page=1)
    assert "is not on the user's computer" in text
    text = await fails(client, "stage_image", source="/etc/passwd", name="x")
    assert "only .gif, .jpeg, .jpg, .png, .webp files can be opened" in text


@pytest.mark.skipif(not shutil.which("dot") and not Path("/opt/homebrew/bin/dot").exists(), reason="needs Graphviz")
async def test_graph_and_occlusion(client: Client, tmp_path: Path) -> None:
    text = await call(client, "render_graph", dot="digraph { Vorhof -> Kammer -> Aorta }", name="herz")
    assert "Saved herz.png" in text and "text labels" in text

    masks = [{"label": "Kammer"}, {"label": "Aorta", "group": 5}, {"region": [0.1, 0.1, 0.3, 0.2], "group": 5}]
    text = await call(client, "draft_add_occlusion", image="herz.png", masks=masks, header="Blutfluss", deck="Math")
    assert "Image Occlusion (3 masks, 2 cards, all hidden, one asked), masks drawn in herz-masks.png" in text
    assert "Header: Blutfluss" in text and "Occlusion:" not in text
    assert (tmp_path / IMAGES / "herz-masks.png").exists()

    text = await fails(client, "draft_add_occlusion", image="herz.png", masks=[{"label": "Lunge"}], deck="Math")
    assert "label 'Lunge' not found. Labels on the image: Aorta, Kammer, Vorhof" in text


async def test_user_notes_are_protected(client: Client, anki: FakeAnki) -> None:
    nid = anki.add_user_note("Frage", "Antwort")
    text = await fails(client, "update_notes", updates=[{"note_id": nid, "fields": {"Back": "neu"}}])
    assert "the user wrote this note" in text
    text = await fails(client, "delete_notes", note_ids=[nid])
    assert "Written by the user" in text

    text = await call(client, "update_notes", updates=[{"note_id": nid, "fields": {"back": "neu"}}], force=True)
    assert anki.notes[nid]["fields"]["Back"]["value"] == "neu"
    await call(client, "undo", batch_id=batch_id(text))
    assert anki.notes[nid]["fields"]["Back"]["value"] == "Antwort"


async def test_old_batches_without_journal_can_be_undone(client: Client, anki: FakeAnki) -> None:
    nid = anki.add_user_note("old", "card")
    anki.notes[nid]["tags"] += ["mcp::created", "mcp::batch::0badc0de"]
    assert "deleted 1 note" in await call(client, "undo", batch_id="0badc0de")
    assert "already undone" in await fails(client, "undo", batch_id="0badc0de")


def test_readable_turns_html_into_chat_text() -> None:
    html = 'Erst<br>dann <b>fett</b><ul><li>a &amp; b</li><li>c</li></ul><img src="x.png" width="200">'
    assert readable(html) == "Erst\ndann fett\n- a & b\n- c\n[image: x.png]"


def test_lint_finds_formatting_slips() -> None:
    assert lint({"Front": "\\(a < b\\)"}) == ["Front: '<' inside math is read as HTML, write \\lt"]
    assert lint({"Front": "$x^2$"}) == ["Front: '$x^2$' does not render in Anki, use \\( \\) or \\[ \\]"]
    assert lint({"Front": "\\(x"}) == ["Front: unbalanced \\( \\) or \\[ \\]"]
    assert lint({"Text": "{{c1::\\frac{1}{2}}}"})[-1].startswith("Text: '}}}' ends the cloze too early")
    assert (
        lint({"Front": "costs $5 and $10, \\(\\frac{1}{2}\\)<br>\\(a \\lt b\\)", "Back": "<pre><code>\\n</code></pre>"})
        == []
    )


async def test_stats_runs_on_a_fresh_collection(client: Client) -> None:
    text = await call(client, "stats", scope="deck:Math")
    assert "Scope: deck:Math" in text
    assert "No weak cards" in text


async def test_tool_schemas_have_no_references(client: Client) -> None:
    # The Claude desktop app forwards only "properties" and "required" of each schema to chats.
    for tool in (await client.list_tools()).tools:
        schema = str(tool.input_schema)
        assert "$ref" not in schema and "$defs" not in schema, tool.name
