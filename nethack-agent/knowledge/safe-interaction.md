---
{
  "id": "safe-interaction",
  "title": "Handle nearby monsters and doors without risky improvisation",
  "card_version": 1,
  "sources": [
    {
      "title": "Melee",
      "url": "https://nethackwiki.com/wiki/Melee"
    },
    {
      "title": "Movement",
      "url": "https://nethackwiki.com/wiki/Movement"
    },
    {
      "title": "Door",
      "url": "https://nethackwiki.com/wiki/Door"
    },
    {
      "title": "Command",
      "url": "https://nethackwiki.com/wiki/Command"
    }
  ],
  "retrieved_at": "2026-09-27",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Target: vanilla NetHack 3.6.7 in NLE 1.3.0 NetHackStaircase-v0.",
  "uncertainty": "Door includes explicit NetHack 3.6.7 source references and a 3.6.7 page tag. Melee is tagged 3.4.3, Movement is untagged, and Command is tagged 3.6.1; only basic interaction facts are retained. No general prompt-answering rule was found in the reviewed pages.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Handle nearby monsters and doors without risky improvisation

## Actionable facts

- A normal move into a monster initiates a melee attack. Most monster melee attacks require adjacency, but this does not protect against ranged attacks or special exceptions.
- The scenario explicitly enables NetHack's `autoopen` option: an orthogonal move into an unlocked closed door attempts to open it. A locked door will not open normally; first look for another route rather than forcing it.
- Open doorways do not permit diagonal movement into or out of the doorway. Use orthogonal movement at intact doorways.
- Kicking or striking a door makes noise, and damaging doors in shops or Minetown can cause serious consequences. Do not force doors for routine Staircase exploration.
- A closed door can temporarily separate the hero from many monsters, but some monsters and ranged effects can bypass or destroy it.
- Prompt safety is deterministic policy: acknowledge only known wait-for-space prompts and decline or cancel known risky text/yes-no prompts. Do not invent an answer to an unfamiliar prompt.

## Non-goals

- Do not provide a general combat strategy, select equipment, use unidentified items, attack peaceful creatures, or authorize door destruction.
- Do not treat a door as guaranteed protection or answer prompts based only on this card.
