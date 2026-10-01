# Local-player knowledge

This directory holds concise, reviewed knowledge cards injected into the local
playing model's context. It is deliberately separate from `_agents/skills/`,
which serves coding agents.

## Reviewed bundle

`manifest.json` is the unchanged default runtime entry point
(`staircase-reviewed-v3`). `manifest.survival-reviewed-v1.json` is an
explicitly selectable, *not yet active* successor: pass
`bundle_id=\"survival-reviewed-v1\"` to `load_knowledge_bundle(directory, ...)`.
It reuses the staircase and exploration cards, adds the two reviewed survival
cards, and omits `safe-interaction.md` to remain within the existing 6,000
character/1,500 estimated-token budget. Prompt and action safety remain the
deterministic gate's responsibility; switching bundles requires the later new
policy and its regression evaluation. Each manifest allowlists cards in prompt
order and pins SHA-256; files not listed there, including this README, never
enter a prompt.

| Card | Question answered | Sources |
| --- | --- | --- |
| `stairs-traversal.md` | How do I recognize, reach, and use staircases, and what can the display not tell me? | [Staircase](https://nethackwiki.com/wiki/Staircase), [Command](https://nethackwiki.com/wiki/Command), [Gnomish Mines](https://nethackwiki.com/wiki/Gnomish_Mines), [Sokoban](https://nethackwiki.com/wiki/Sokoban) |
| `exploration-map.md` | How should I read the ASCII map and explore conservatively? | [Dungeon feature](https://nethackwiki.com/wiki/Dungeon_feature), [Movement](https://nethackwiki.com/wiki/Movement), [Command](https://nethackwiki.com/wiki/Command) |
| `safe-interaction.md` | What basic monster, door, and prompt facts prevent risky improvisation? | [Melee](https://nethackwiki.com/wiki/Melee), [Movement](https://nethackwiki.com/wiki/Movement), [Door](https://nethackwiki.com/wiki/Door), [Command](https://nethackwiki.com/wiki/Command) |
| `prayer-hunger.md` | When does hunger become urgent, and when is prayer plausibly safe rather than guaranteed? | [Nutrition](https://nethackwiki.com/wiki/Nutrition), [Food ration](https://nethackwiki.com/wiki/Food_ration), [Prayer timeout](https://nethackwiki.com/wiki/Prayer_timeout), [Prayer](https://nethackwiki.com/wiki/Prayer) |
| `safe-corpses.md` | Which observed fresh corpses may an unpolymorphed dwarven Valkyrie consider, and which must never be eaten? | [Corpse](https://nethackwiki.com/wiki/Corpse), [Cannibalism](https://nethackwiki.com/wiki/Cannibalism), [Lycanthropy](https://nethackwiki.com/wiki/Lycanthropy), [Lichen](https://nethackwiki.com/wiki/Lichen), [Newt](https://nethackwiki.com/wiki/Newt), [Sewer rat](https://nethackwiki.com/wiki/Sewer_rat), [Giant rat](https://nethackwiki.com/wiki/Giant_rat), [Gecko](https://nethackwiki.com/wiki/Gecko) |

The original facts were extracted on 2026-09-27 (the
`stairs-traversal.md` replacement on 2026-09-28). The new survival cards were
reviewed on 2026-10-01 from the local NetHackWiki current-page dump
(`docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml`); every factual
claim cites a page and the page's dump revision date. The cards' metadata and
[note 0024](../../docs/notes/0024-reviewed-survival-knowledge.md) record
revision timestamps, version caveats, and excluded candidates. The raw dump is
neither committed nor read at runtime.

## Card format

Each card starts with a JSON metadata block between `---` lines. Required
fields are `id` (equal to the filename stem), `title`, `card_version`,
`sources` (page title and canonical `https://nethackwiki.com/wiki/` URL),
`retrieved_at`, `source_path`, `applicable_version`, `uncertainty`,
`attribution`, `license`, and `license_url`. The body contains exactly:

```markdown
# <title>

## Actionable facts

- ...

## Non-goals

- ...
```

Only actionable facts and non-goals are injected. Metadata remains auditable in
the card and the run records the bundle version.

## Changing cards

1. Extract a narrowly relevant page with
   `_agents/skills/nethack-wiki/scripts/wiki_dump.py page "<title>"`.
2. Check version tags and source references; record uncertainty explicitly.
3. Paraphrase only necessary actionable facts. Do not copy large passages,
   bulk-convert wiki pages, or add model-generated claims without review.
4. Update the card's SHA-256 in the selected manifest; when a card set changes
   semantically, create or bump its `bundle_id` without mutating existing
   report/suite pins.
5. Run `uv run pytest -q tests/test_knowledge.py` from `nethack-agent/`.

The loader enforces the manifest's `max_context_characters` (at most 6,000) and
a 1,500 estimated-token limit (`ceil(characters / 4)`) on the rendered context.

## Attribution and license

Card content is adapted from NetHackWiki contributors under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). The source
pages used here did not identify a separate license. Derived card text is
distributed under the same license; retain source titles, URLs, and attribution
when copying or modifying it. See
[NetHackWiki:Copyrights](https://nethackwiki.com/wiki/NetHackWiki:Copyrights).

## Evaluation rule

The knowledge set is versioned and fixed for an entire evaluation suite. The
service loads it once at startup; every run records the same content-derived
version. Changes are made between suites after a coding agent reviews run
evidence; the playing model does not rewrite this directory.
