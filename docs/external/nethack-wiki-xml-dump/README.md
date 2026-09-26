# NetHackWiki XML dump

The current-page dump is local source material for research and reviewed
knowledge extraction. It is intentionally excluded from Git.

## Download

Primary instructions: <https://nethackwiki.com/wiki/NetHackWiki:Download>

```bash
curl -fLO https://archive.alt.org/nethackwiki/nethackwiki_current.xml.gz
gzip -dk nethackwiki_current.xml.gz
```

Place the uncompressed file at:

```text
docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml
```

The dump present during project initialization was approximately 188 MB.

## Inspect without importing

From the repository root:

```bash
python _agents/skills/nethack-wiki/scripts/wiki_dump.py search "stair"
python _agents/skills/nethack-wiki/scripts/wiki_dump.py page "Stairs"
python _agents/skills/nethack-wiki/scripts/wiki_dump.py search \
  "down staircase" --in-text --limit 10
```

The reader streams the XML and does not load the whole dump into memory. Never
feed the raw file to a model.

## Licensing and attribution

NetHackWiki states that most contributions are licensed under CC BY-SA 3.0,
with some separately licensed source, screenshots, and imported spoilers:
<https://nethackwiki.com/wiki/NetHackWiki:Copyrights>.

Extracted runtime knowledge must cite page titles and canonical URLs, preserve
required attribution, and flag content whose page identifies another license.
The dump itself remains external and is not distributed by this repository.
