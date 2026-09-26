---
{
  "id": "exploration-map",
  "title": "Explore the visible map conservatively",
  "card_version": 1,
  "sources": [
    {
      "title": "Dungeon feature",
      "url": "https://nethackwiki.com/wiki/Dungeon_feature"
    },
    {
      "title": "Movement",
      "url": "https://nethackwiki.com/wiki/Movement"
    },
    {
      "title": "Command",
      "url": "https://nethackwiki.com/wiki/Command"
    }
  ],
  "retrieved_at": "2026-09-27",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Target: vanilla NetHack 3.6.7 in NLE 1.3.0 NetHackStaircase-v0.",
  "uncertainty": "The Command page is tagged for NetHack 3.6.1; Movement has no explicit version tag; Dungeon feature carries a broad current-wiki tag. Only basic movement and display facts are used. Character-only prompt maps omit color, so several symbols remain deliberately ambiguous.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Explore the visible map conservatively

## Actionable facts

- A plain direction command moves one square. Prefer single-square moves while exploring; running commands can continue until an obstacle and can pass corridor forks.
- In the default display, `+` is a closed door, `.` can be room floor or a doorway, `#` can be a corridor or several other features, and `-` or `|` can be a wall or open door. Color and surrounding geometry disambiguate these symbols; a character-only map does not.
- A blank can mean solid rock or unexplored dungeon. Treat map edges beside known floors and corridors as possible unexplored space, not as confirmed traversable terrain.
- The search command checks for unseen nearby features. Search near plausible room boundaries when exploration leaves a substantial unrevealed region.

## Non-goals

- Do not infer unseen terrain, paths through walls, or exact feature identity from an ambiguous ASCII character alone.
- Do not use long-running movement, travel, teleportation, digging, or magic mapping as a default exploration policy.
