---
{
  "id": "stairs-traversal",
  "title": "Recognize, reach, and use staircases",
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
  "retrieved_at": "2026-09-28",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Target: vanilla NetHack 3.6.7 in NLE 1.3.0 NetHackStaircase-v0 and NetHackScore-v0.",
  "uncertainty": "Staircase and Gnomish Mines are tagged for NetHack 3.4.3, Command for 3.6.1, and Sokoban for 3.6.7. The branch depths and staircase directions are documented for vanilla NetHack and agree with the NLE 1.3.0 NetHack 3.6.7 data. NLE's public glyph arrays expose one displayed glyph per cell. Whether a staircase is the main or a branch staircase is not displayed; the project establishes it only from its own traversal records.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Recognize, reach, and use staircases

## Actionable facts

- NetHack displays a downstairs as `>` and an upstairs as `<`. Standing on a staircase and using it are different actions: the separate `>` command goes down a downstairs and the `<` command goes up an upstairs to another dungeon level.
- A normal level usually has one staircase in each direction, and each staircase can be used in both directions. A branching level has an additional staircase: the Gnomish Mines entrance adds a downstairs on dungeon levels 2-4, and the Sokoban entrance adds an upstairs on dungeon levels 6-10. Both staircases of one direction look identical, so the display does not show which one enters the branch.
- The upstairs of dungeon level 1 leaves the dungeon; without the Amulet of Yendor that ends the game. NetHack first warns "Beware, there will be no return!".
- Staircases themselves are never secret, but an item, boulder, or monster can cover one, and the room containing one can be behind a secret door or hidden corridor.
- NLE exposes one displayed glyph per map cell. A covering object or monster replaces the staircase glyph in the agent's current observation; there is no separate public underlying-terrain array. A covered staircase is known only if it was observed before being covered, or from the look-here message "There is a staircase down here." or "There is a staircase up here." when standing on it.
- If no staircase of the needed direction is visible or remembered, explore unrevealed map regions and search plausible room boundaries. Step onto item squares when safe because an item can obscure the staircase.

## Non-goals

- This card does not decide whether to stand on a staircase or use it; the current goal states that.
- Do not climb the upstairs of dungeon level 1, dig a replacement hole, or change level by any means other than a staircase.
- Do not assume which of two same-direction staircases enters a branch from the display alone.
