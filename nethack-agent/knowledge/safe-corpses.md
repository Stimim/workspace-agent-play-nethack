---
{
  "id": "safe-corpses",
  "title": "Eat only identified fresh low-risk corpses",
  "card_version": 1,
  "sources": [
    {"title": "Corpse", "url": "https://nethackwiki.com/wiki/Corpse"},
    {"title": "Cannibalism", "url": "https://nethackwiki.com/wiki/Cannibalism"},
    {"title": "Lycanthropy", "url": "https://nethackwiki.com/wiki/Lycanthropy"},
    {"title": "Lichen", "url": "https://nethackwiki.com/wiki/Lichen"},
    {"title": "Newt", "url": "https://nethackwiki.com/wiki/Newt"},
    {"title": "Sewer rat", "url": "https://nethackwiki.com/wiki/Sewer_rat"},
    {"title": "Giant rat", "url": "https://nethackwiki.com/wiki/Giant_rat"},
    {"title": "Gecko", "url": "https://nethackwiki.com/wiki/Gecko"}
  ],
  "retrieved_at": "2026-10-01",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Vanilla NetHack 3.6.7 in NLE 1.3.0 for an unpolymorphed dwarven Valkyrie. Corpse's aging source references 3.6.0; Cannibalism and Lycanthropy cite 3.6.7.",
  "uncertainty": "Dump revisions: Corpse 2026-08-27T17:10:32Z; Cannibalism 2025-08-24T17:32:45Z; Lycanthropy 2026-08-22T04:43:20Z; Lichen 2024-11-17T19:34:55Z; Newt 2026-06-02T18:31:39Z; Sewer rat 2024-12-10T06:26:39Z; Giant rat 2024-02-09T13:46:19Z; Gecko 2023-11-22T11:10:12Z. Species pages do not independently prove every harmful effect absent; only fresh kills with unambiguous identity qualify. Exact NLE corpse prompt is unverified.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Eat only identified fresh low-risk corpses

## Actionable facts

- For a normal dwarven Valkyrie, consider only an unambiguous corpse of an observed kill on its cell: lichen, newt, sewer rat, giant rat or gecko. Require age <=19 game turns, or choose a ration. Lichen never rots; newt may restore power; the other pages list no food hazard. (Corpse, rev 2026-08-27; Lichen, rev 2024-11-17; Newt, rev 2026-06-02; Sewer rat, rev 2024-12-10; Giant rat, rev 2024-02-09; Gecko, rev 2023-11-22)
- For ordinary corpses, rottenness is age / random(10..29), +2 if cursed: at age <=19, even unknown BUC gives <4 (old) and <6 (tainted). A separate 1/7 rotten-food risk remains; this is not guaranteed safe. Reject unobserved, old, displaced or unidentified corpses. (Corpse, rev 2026-08-27)
- Never eat cockatrice/chickatrice or Medusa (stoning), green slime globs (sliming), acidic or poisonous corpses, werecreatures (lycanthropy), any dwarf or human, kobolds, rabid rats, bats, cats, dogs, or undead. Same-race meat costs Luck and aggravates monsters; undead are pre-aged. (Corpse, rev 2026-08-27; Cannibalism, rev 2025-08-24; Lycanthropy, rev 2026-08-22)

## Non-goals

- This allow-list does not authorize eating under an unknown race/form, a guessed monster glyph, a covered corpse, or an unfamiliar prompt; decline all other corpse offers. (Corpse, rev 2026-08-27; Cannibalism, rev 2025-08-24)
