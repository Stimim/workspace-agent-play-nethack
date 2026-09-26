# 0005: Reviewed local-model knowledge cards

Date: 2026-09-27

## Scope

The first reviewed runtime knowledge bundle, `staircase-reviewed-v1`, is in
`nethack-agent/knowledge/`. It has three cards: staircase goal semantics,
conservative map exploration, and safe monster, door, and prompt interaction.
`nethack_agent.knowledge` loads it deterministically. Ollama skill-selection
and fallback-action prompts include it, and every run records its version.

## Source review

Pages were extracted from the local current-page dump
`docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml`
(MediaWiki 1.43.9 export; site base `https://nethackwiki.com/wiki/Main_Page`)
with `_agents/skills/nethack-wiki/scripts/wiki_dump.py`:

- [Staircase](https://nethackwiki.com/wiki/Staircase) (`Stairs` redirects
  here); tagged NetHack 3.4.3.
- [Command](https://nethackwiki.com/wiki/Command); tagged NetHack 3.6.1.
- [Dungeon feature](https://nethackwiki.com/wiki/Dungeon_feature); carries a
  broad current-wiki tag.
- [Movement](https://nethackwiki.com/wiki/Movement); no version tag.
- [Door](https://nethackwiki.com/wiki/Door); tagged NetHack 3.6.7 with 3.6.7
  source references.
- [Melee](https://nethackwiki.com/wiki/Melee) (`Melee combat` redirects here);
  tagged NetHack 3.4.3.

The dump search found no general prompt-answering page. Prompt safety in the
card therefore restates the deterministic project policy rather than a wiki
fact. Card uncertainty fields record every version mismatch. Cards paraphrase
only short actionable facts and preserve CC BY-SA 3.0 attribution.

## Decisions

- Cards use JSON front matter so metadata is strictly validated without a YAML
  dependency. Only the body's facts and non-goals enter prompts.
- `manifest.json` is an allowlist and ordering contract. Each card is pinned by
  SHA-256; unlisted files and the raw dump are ignored at runtime.
- The bundle version is `<bundle_id>+sha256:<digest>` over a canonical manifest
  and exact card bytes. At this note's delivery, the initial version was
  `staircase-reviewed-v1+sha256:96dd923822c16527cfc9a9e4b3b334e66818375f3faf72d419627b45ae8ee324`.
- The rendered context must satisfy the manifest bound (6,000 characters max)
  and a 1,500 estimated-token cap (`ceil(characters / 4)`). The initial context
  was 3,444 characters, about 861 estimated tokens. Later reviewed revisions
  are recorded in their chronological notes and the manifest.
- `RunManager` loads one bundle at construction and uses it for all runs.
  The former `KNOWLEDGE_VERSION = "none"` constant was removed.
- `ScriptedDevelopmentModel` does not consume knowledge. Its runs still record
  the service bundle version for comparable metadata.
- Wheels include the reviewed directory as `nethack_agent/knowledge`.

## Verification

- `uv run pytest -q`: 99 passed. Knowledge tests cover deterministic manifest
  order and version, reorder sensitivity, invalid manifest shapes, missing and
  tampered cards, unlisted cards, context bounds, attribution validation,
  prompt inclusion without raw-wiki markers, and run metadata.
- `uv run ruff check .` and `uv run ruff format --check .` passed for 33 files.
- An offline smoke with socket connections blocked loaded the real bundle, built
  real Ollama skill (3,924 characters) and fallback-action (7,833 characters)
  prompts from NLE seed 6 through recording clients, found the full knowledge
  context in both, found no MediaWiki markup, dump path, or card metadata, and
  confirmed that a created run recorded the same bundle version.
- `uv build --wheel` included the manifest, the three cards, and the README.

## Limitations

- No live Ollama inference was run with the knowledge context. Its effect on
  decision quality and latency is unmeasured until the 10-seed evaluation.
- Several source pages are not tagged for NetHack 3.6.7. Cards retain only
  basic, stable facts and flag the mismatch.
- Character-only prompt maps cannot resolve symbols that depend on color. The
  exploration card states this ambiguity instead of guessing.
