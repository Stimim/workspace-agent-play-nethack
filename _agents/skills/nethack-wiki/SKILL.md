# NetHackWiki dump skill

Use this skill when a task needs NetHack mechanics, strategy, item behavior, or terminology that may be documented in the local wiki dump.

## Source

Default dump: `docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml`. It is intentionally gitignored. Acquisition and licensing are documented beside the dump.

## Procedure

All commands run through project `uv run` from the repository root (or prefix the script path with `../` from `nethack-agent/`):

1. Search titles before searching full page text:
   ```bash
   uv run python _agents/skills/nethack-wiki/scripts/wiki_dump.py search "stair"
   ```
2. Extract only the likely page:
   ```bash
   uv run python _agents/skills/nethack-wiki/scripts/wiki_dump.py page "Stairs"
   ```
3. If the title is unknown, search page text explicitly:
   ```bash
   uv run python _agents/skills/nethack-wiki/scripts/wiki_dump.py search "down staircase" --in-text --limit 10
   ```
4. Check version qualifiers and distinguish vanilla NetHack from variants.
5. For runtime use, summarize only necessary facts in a focused file under `nethack-agent/knowledge/`. Include source page title, canonical URL, dump date if known, supported game version, and review date.
6. Do not copy large passages. NetHackWiki text is generally CC BY-SA 3.0 but can include separately licensed material; preserve required attribution and flag exceptions.

The script streams MediaWiki XML with `ElementTree.iterparse`; it does not hold the 188 MB dump in memory. Raw output is evidence, not automatically trusted policy.
