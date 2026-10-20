---
{
  "id": "nutrition-foraging-v2",
  "title": "Reviewed food and canonical slime molds",
  "card_version": 1,
  "sources": [
    {"title": "Slime mold", "url": "https://nethackwiki.com/wiki/Slime_mold"},
    {"title": "Comestible", "url": "https://nethackwiki.com/wiki/Comestible"},
    {"title": "Food ration", "url": "https://nethackwiki.com/wiki/Food_ration"},
    {"title": "Clove of garlic", "url": "https://nethackwiki.com/wiki/Clove_of_garlic"}
  ],
  "retrieved_at": "2026-10-18",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Vanilla NetHack 3.6.7 in NLE 1.3.0 for an unpolymorphed dwarven Valkyrie.",
  "uncertainty": "Local dump revisions: Slime mold 2026-03-14T02:38:01Z; Comestible 2026-05-23T01:30:13Z; Food ration 2026-08-28T10:28:40Z; Clove of garlic 2024-07-14T06:28:47Z. Primary source: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/objects.c#L773-L785 confirms vegetable material and nutrition. Fruit-option and bones names can differ; only the canonical slime mold name is reviewed here.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0; version-pinned NetHack source independently confirms nutrition and vegetable material.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Reviewed food and canonical slime molds

## Actionable facts

- Resume partly-eaten identified rations/fruit.
- Collect reviewed identified non-shop food cheaply reachable only while unburdened; otherwise floor-eat at Hungry+ with the exact offer.
- Canonical slime molds: vegetable food, 250 nutrition; require matching food glyph/class (3.6.7 objects.c:775). Renamed fruit text is not a reviewed identity.
- Skip garlic while undead: it causes vomiting rather than nutrition.

## Non-goals

- No other new food, renamed-fruit aliases, shop acquisition, encumbered pickup, or changed corpse/prayer/eating thresholds.
