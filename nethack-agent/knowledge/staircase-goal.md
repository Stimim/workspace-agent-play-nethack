---
{
  "id": "staircase-goal",
  "title": "Recognize and reach the downstairs without descending",
  "card_version": 1,
  "sources": [
    {
      "title": "Staircase",
      "url": "https://nethackwiki.com/wiki/Staircase"
    },
    {
      "title": "Command",
      "url": "https://nethackwiki.com/wiki/Command"
    },
    {
      "title": "Gnomish Mines",
      "url": "https://nethackwiki.com/wiki/Gnomish_Mines"
    },
    {
      "title": "Sokoban",
      "url": "https://nethackwiki.com/wiki/Sokoban"
    }
  ],
  "retrieved_at": "2026-09-27",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Target: vanilla NetHack 3.6.7 in NLE 1.3.0 NetHackStaircase-v0.",
  "uncertainty": "Staircase and Gnomish Mines are tagged for NetHack 3.4.3, Command for 3.6.1, and Sokoban for 3.6.7. The branch depths and staircase directions are documented for vanilla NetHack and agree with the NLE 1.3.0 NetHack 3.6.7 data. NLE's public glyph arrays expose one displayed glyph per cell; the no-descent and nearest-remembered-downstairs behavior is project policy.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Recognize and reach the downstairs without descending

## Actionable facts

- Project task policy: finish by standing on a downstairs square; never issue the descend action. Current `stand_on_downstairs` navigation chooses the reachable remembered `>` with the shortest route (breaking equal-distance ties by map row, then column); it does not identify which branch a staircase enters.
- NetHack displays a downstairs as `>` and an upstairs as `<`. Occupying the `>` square and using the separate `>`/down command are different actions.
- A normal level usually has one staircase in each direction. A branching level has an additional staircase: the Gnomish Mines entrance adds a downstairs on dungeon levels 2-4, while the Sokoban entrance adds an upstairs on dungeon levels 6-10. Such levels can therefore contain multiple staircases with the same displayed direction.
- Staircases themselves are never secret, but an item, boulder, or monster can cover one, and the room containing one can be behind a secret door or hidden corridor.
- NLE exposes one displayed glyph per map cell. A covering object or monster replaces the staircase glyph in the agent's current observation; there is no separate public underlying-terrain array. A staircase remains known only if it was observed before being covered and retained in level memory.
- If no downstairs is visible or remembered, explore unrevealed map regions and search plausible room boundaries. Step onto item squares when safe because an item can obscure the staircase.

## Non-goals

- Do not descend, dig a replacement hole, change dungeon levels, or choose a branch. Future branch-aware goals must represent stair direction and identity instead of treating every `>` as interchangeable.
- Do not assume every angle bracket is the target without the current observation and staircase glyph/context.
