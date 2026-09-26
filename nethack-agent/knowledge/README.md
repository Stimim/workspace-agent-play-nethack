# Local-player knowledge

This directory holds concise, reviewed knowledge cards injected into the local
playing model's context. It is deliberately separate from `_agents/skills/`,
which serves coding agents.

## Reviewed bundle

`manifest.json` is the only runtime entry point. It allowlists cards in prompt
order and pins each file's SHA-256. Files not listed there, including this
README, never enter a prompt.

| Card | Question answered | Sources |
| --- | --- | --- |
| `staircase-goal.md` | How do I recognize and reach the Staircase target without descending? | [Staircase](https://nethackwiki.com/wiki/Staircase), [Command](https://nethackwiki.com/wiki/Command), [Gnomish Mines](https://nethackwiki.com/wiki/Gnomish_Mines), [Sokoban](https://nethackwiki.com/wiki/Sokoban) |
| `exploration-map.md` | How should I read the ASCII map and explore conservatively? | [Dungeon feature](https://nethackwiki.com/wiki/Dungeon_feature), [Movement](https://nethackwiki.com/wiki/Movement), [Command](https://nethackwiki.com/wiki/Command) |
| `safe-interaction.md` | What basic monster, door, and prompt facts prevent risky improvisation? | [Melee](https://nethackwiki.com/wiki/Melee), [Movement](https://nethackwiki.com/wiki/Movement), [Door](https://nethackwiki.com/wiki/Door), [Command](https://nethackwiki.com/wiki/Command) |

Facts were extracted on 2026-09-27 from the local NetHackWiki current-page dump
(`docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml`) with the
repository wiki skill. The raw dump is neither committed nor read at runtime.

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
4. Update the card's SHA-256 in `manifest.json`; when a card set changes
   semantically, also bump `bundle_id`.
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
