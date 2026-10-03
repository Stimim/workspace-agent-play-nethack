---
{
  "id": "safe-corpses-v2",
  "title": "Eat only identified fresh low-risk corpses",
  "card_version": 1,
  "sources": [
    {"title": "Corpse", "url": "https://nethackwiki.com/wiki/Corpse"},
    {"title": "Cannibalism", "url": "https://nethackwiki.com/wiki/Cannibalism"},
    {"title": "Lycanthropy", "url": "https://nethackwiki.com/wiki/Lycanthropy"},
    {"title": "Lichen", "url": "https://nethackwiki.com/wiki/Lichen"},
    {"title": "Jackal", "url": "https://nethackwiki.com/wiki/Jackal"}
  ],
  "retrieved_at": "2026-10-04",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Vanilla NetHack 3.6.7 in NLE 1.3.0 for an unpolymorphed dwarven Valkyrie.",
  "uncertainty": "Dump revisions: Corpse 2026-08-27T17:10:32Z; Cannibalism 2025-08-24T17:32:45Z; Lycanthropy 2026-08-22T04:43:20Z; Lichen 2024-11-17T19:34:55Z; Jackal 2026-08-20T02:09:20Z. Species pages do not prove every hazard absent.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Eat only identified fresh low-risk corpses

## Actionable facts

- Eat only an observed own kill, on its cell, of lichen, newt, sewer rat, giant rat, gecko, garter snake, hobbit, goblin, iguana or shrieker at age <=19 (uncapped for nonrotting lichen); jackal/fox/coyote too, only absent lycanthropy evidence/polymorph. A pet-dragged corpse: only lichen stays eatable, identified at its new cell by its exact text.
- Rottenness is age/random(10..29)+2 if cursed; <=19 avoids tainted/sick even unknown-BUC, 1/7 rotten risk remains.
- Never eat cockatrice/Medusa, slime, acidic/poisonous, dwarves, humans, kobolds, rabid rats, bats, cats, dogs, undead; canids once lycanthropic. (Corpse rev 2026-08-27; Lichen rev 2024-11-17; Jackal rev 2026-08-20)

## Non-goals

- No unknown race/form, guessed glyph, covered corpse, shop cell, or unfamiliar prompt.
