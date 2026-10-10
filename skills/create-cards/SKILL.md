---
name: create-cards
description: Writes Anki flashcards from study material (lecture notes, slides, PDFs, papers, past exams, YouTube videos or the conversation itself) and adds them to the user's Anki collection once the user approves them in the chat. Use whenever the user wants flashcards, Anki cards, cloze cards or a new deck, in any language (Karteikarten, Lernkarten). Contains the card-writing rules, the HTML, LaTeX and cloze formatting Anki needs, and the draft, approve, commit workflow.
---

# Creating Anki cards

The user will review these cards for years. A weak card costs more than a missing one: it wastes review time every day and trains the wrong thing. Write fewer cards than you are tempted to, and make each one count.

## Workflow

1. **Read the source** and decide what is worth remembering (see below). Read a YouTube video with `youtube_transcript`.
2. **Call `overview`** once per conversation. Use deck names and field names exactly as it lists them. If the target deck already has cards on the topic, check with `search_notes` so you do not write near-duplicates.
3. **Write the cards** by the rules below, then go through the checklist at the end. Rewrite or drop every card that fails.
4. **Call `draft_add`** with up to 50 cards; for more, call it again with the returned `draft_id`. It checks the cards against Anki and keeps them in a draft. Nothing reaches Anki yet.
   - If it reports errors, nothing was added. Fix them and send all cards again.
   - If it reports formatting warnings, fix the real ones with `draft_edit`.
5. **Show the cards** to the user in the chat: every card with all its fields, word for word as `draft_add` returned them, one block per card with its number. Do not summarize, shorten or paraphrase them; the user approves the exact text. Pictures appear as `[image: name.png]`: say once which folder they are in, so the user can open them. If you left out parts of the source on purpose, say which in one sentence. Then ask whether to add the cards or what to change.
6. **Apply the user's changes** with `draft_edit`: the card number and only the fields that change, or `remove` for a rejected card. Show the changed cards again.
7. **Call `draft_commit`** only after the user has said yes. Pass `cards` if they approved only some. Then report in one or two sentences how many cards went into which deck, and the batch id: `undo` with it removes them again. If the user studies on their phone, offer `sync`.

Drafts are kept on the user's computer for 14 days. `draft_show` without an id lists them, so a draft can be continued in a later chat.

If a card is about something drawn (a graph, tree, automaton, plot, diagram or labelled figure), read the `visuals` skill before writing it.

## What deserves a card

Definitions that are used later, theorem statements and the hypotheses they depend on, the key idea of a proof, counterexamples, the reasoning behind solutions to exam-style exercises, and anything that has to be recalled without looking it up. Skip motivation, history and connecting prose.

## Rules

Write the cards in the language of the source unless the user asks for another one. Mathematical notation stays in LaTeX in every language.

1. **One fact per card.** If the answer contains an "and", it is usually two cards.
2. **Never ask for a set or a list.** "Name the axioms of a vector space" is not a card. Break it into cloze deletions, so each part is retrieved on its own.
3. **No yes/no questions.** Ask for the reason, the consequence or the mechanism instead.
4. **Exactly one correct answer.** If a second answer is defensible, the question is underspecified: add the qualifier that pins it down.
5. **The answer is retrieved, not inferred.** If the question already contains enough to guess it, the card teaches nothing.
6. **Keep the answer minimal.** A phrase is usually right, a paragraph is always wrong.
7. **Never copy a sentence verbatim from the source.** A copied sentence trains recognition of the wording instead of the content.
8. **Give the question the context it needs, and no more.** Cards in one deck interfere with each other; a short qualifier ("in finite dimension", "for a symmetric matrix") prevents that.
9. **Redundancy is fine.** The same fact asked from two directions, or a concept approached once through its definition and once through an example, are two legitimate cards.
10. **Add no facts the source does not support.** If the source is unclear, leave that part out and tell the user.

## Theorems, proofs and definitions

For a theorem or a proof, write candidates from these angles and keep the ones that carry weight:

- Statement: what does it assert?
- Hypotheses: what does it require?
- Necessity: what breaks if a hypothesis is dropped? Best answered with a counterexample.
- Key idea: the one or two ideas the proof turns on.
- Single step: one non-obvious step of the proof, asked on its own.
- Interpretation: what it means geometrically or intuitively.
- Boundary: where it fails, and why.
- Converse: state it, and whether it holds.

For a definition:

- The definition, asked from the name.
- The name, asked from the definition.
- One minimal example and one minimal non-example.

Prefer cards that let the student rebuild the idea over cards that test recitation.

## Wording

Answers should read like a person wrote them in a hurry, not like an encyclopedia.

- No em dashes. Use a comma, a colon or two sentences.
- No "not just X, but Y" and no "it's not about X, it's about Y". Say what it is.
- No puffery ("spielt eine zentrale Rolle", "ist von grundlegender Bedeutung", "plays a crucial role"). If it matters, say what it does.
- No vague clause tacked onto a fact ("..., which underlines the importance of ..."). Cut it.
- No phantom attribution ("some argue", "manche argumentieren"). Either the source says it or it does not go on the card.
- No bold term followed by a colon that restates it.
- No forced triplets when two items carry the fact.
- Bold at most one phrase per card, and only the thing being tested.

## Formatting

Fields are HTML. These are not style preferences, they are what Anki actually renders.

**Math**
- Inline `\(...\)`, display `\[...\]`. Never `$...$`, `[latex]` or `[$]`: they do not render, or only on desktop with LaTeX installed.
- Every mathematical symbol goes inside `\(...\)`, single letters and subscripts included: `\(D_{C,B}\)`, not `D_{C,B}`. Outside the delimiters LaTeX shows up as literal characters, braces and all.
- Inside math write `\lt` and `\gt` instead of `<` and `>`. A literal `<` is read as the start of an HTML tag before MathJax sees it.
- Chemistry works with mhchem: `\(\ce{H2O}\)`.

**Text**
- Outside math, escape `&`, `<` and `>` as `&amp;`, `&lt;` and `&gt;`.
- Line breaks are `<br>`, also inside a formula.
- Allowed HTML: `<br> <b> <i> <ul> <li> <pre> <code> <img>`, nothing else. Anki's editor rewrites more complex markup.
- Code goes into `<pre><code>...</code></pre>`, without syntax highlighting.
- Pictures are `<img src="name.png">` tags from the image tools (see the `visuals` skill).

**Cloze**
- `{{c1::hidden text}}`. Each number becomes one card; the same number used twice hides both parts on one card.
- `{{c1::hidden text::hint}}` shows the hint in the gap. Use it when the bare gap would be ambiguous.
- Cloze deletions need the Cloze note type, and a cloze note without any `{{c1::...}}` is rejected.
- LaTeX braces collide with the cloze syntax: `{{c1::\frac{1}{2}}}` ends in three braces and breaks. Put a space before closing braces that do not end the cloze: `{{c1::\frac{1}{2} }}`.

**Note type**
- Cloze for facts inside a sentence, for enumerations broken into gaps, and for formulas where one part is the target.
- Basic for a real question with a separate answer.
- Each card in `draft_add` can set its own `note_type`, so Basic and Cloze cards can share one draft.

## Examples

**Enumeration**
- Bad: Front "Welche Eigenschaften hat eine Äquivalenzrelation?", Back "reflexiv, symmetrisch, transitiv"
- Why: one card holding three items. Some days two of three come back and the card is marked wrong for a partial success.
- Good: Cloze "Eine Äquivalenzrelation ist {{c1::reflexiv}}, {{c2::symmetrisch}} und {{c3::transitiv}}."
- Why: three independent retrievals, each on its own schedule.

**Yes/no**
- Bad: Front "Ist jede orthogonale Matrix invertierbar?", Back "Ja"
- Why: a coin flip is right half the time. Nothing is retrieved.
- Good: Front "Warum ist jede orthogonale Matrix \(Q\) invertierbar?", Back "Aus \(Q^TQ = I\) folgt: \(Q^T\) ist das Inverse"
- Why: the reason is what is worth knowing, and it fits in one phrase.

**Too broad**
- Bad: Front "Was besagt der Spektralsatz?", Back "Eine reelle symmetrische Matrix ist orthogonal diagonalisierbar, ihre Eigenwerte sind reell und Eigenvektoren zu verschiedenen Eigenwerten stehen senkrecht aufeinander."
- Why: three facts in one answer. It gets marked wrong for missing the third.
- Good, three cards:
  1. Front "Spektralsatz (reell): Was gilt für eine symmetrische Matrix \(A\)?", Back "Sie ist orthogonal diagonalisierbar"
  2. Front "Spektralsatz (reell): Was gilt für die Eigenwerte von \(A = A^T\)?", Back "Sie sind reell"
  3. Front "Spektralsatz: Warum genügt 'diagonalisierbar' als Voraussetzung nicht?", Back "Erst Symmetrie erzwingt eine orthogonale Eigenbasis"
- Why: card 3 carries the understanding. It asks why the hypothesis is there.

**Boundary**
- Good: Front "Gib eine lineare Abbildung \(\mathbb{R}^2 \to \mathbb{R}^2\) an, die injektiv, aber nicht surjektiv ist.", Back "Gibt es nicht: bei gleicher endlicher Dimension sind injektiv und surjektiv äquivalent"
- Why: an answer of "this cannot exist" tests a boundary of the theory. These cards are among the most valuable and are rarely spelled out in the source.

**Cloze with LaTeX**
- Good: Cloze "Für eine invertierbare Matrix \(A\) gilt \(A^{-1} = {{c1::\frac{1}{\det A}\operatorname{adj}(A) }}\)"
- Why: the space before `}}` keeps the braces of `\frac` from ending the cloze.

**Math without delimiters**
- Bad: Front "D_{C,B}(φ): Welche Basis steht links (C), welche rechts (B)?"
- Why: the card shows the literal characters `D_{C,B}`, braces included.
- Good: Front "\(D_{C,B}(\varphi)\): Welche Basis steht links, welche rechts?"

## Checklist before draft_add

Go through every card and act on each point:

- Does the answer hold an "and", a comma-separated list or more than one fact? Split it.
- Could a reasonable person give a different correct answer? Add the missing context.
- Can the answer be guessed from the question alone? Rewrite or drop the card.
- Is a sentence copied verbatim from the source? Rewrite it.
- Is the answer longer than about fifteen words? Shorten it or split the card.
- Is every `_`, `^`, `\`, `{` and `}` inside `\(...\)`? A field with such characters and no `\(` is always a bug.
- Does every `\(` have its `\)`, every `{{c` its `}}`, and is there a space before closing braces inside a cloze?
- Is there a literal `<` or `>` inside math? Use `\lt` and `\gt`.
- Do the field names match the ones `overview` listed?

Dropping half of the first draft is a good outcome, not a failure.
