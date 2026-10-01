---
{
  "id": "prayer-hunger",
  "title": "Plan food and prayer without claiming certainty",
  "card_version": 1,
  "sources": [
    {"title": "Nutrition", "url": "https://nethackwiki.com/wiki/Nutrition"},
    {"title": "Food ration", "url": "https://nethackwiki.com/wiki/Food_ration"},
    {"title": "Prayer timeout", "url": "https://nethackwiki.com/wiki/Prayer_timeout"},
    {"title": "Prayer", "url": "https://nethackwiki.com/wiki/Prayer"}
  ],
  "retrieved_at": "2026-10-01",
  "source_path": "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml",
  "applicable_version": "Vanilla NetHack 3.6.7 in NLE 1.3.0; Nutrition cites 3.6.7 code, Prayer cites 3.6.7 and 3.6.6; Prayer timeout is tagged 3.4.3 and its 3.7-only notes are excluded.",
  "uncertainty": "Dump revisions: Nutrition 2026-08-27T17:21:31Z; Food ration 2026-08-28T10:28:40Z; Prayer timeout 2026-05-11T14:09:43Z; Prayer 2026-06-09T21:29:39Z. The exact timeout, Luck, alignment record and divine anger are not in the projected observations; 95% is not a guarantee. Prayer confirmation prompts in NLE are unverified.",
  "attribution": "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
  "license": "CC BY-SA 3.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/3.0/"
}
---
# Plan food and prayer without claiming certainty

## Actionable facts

- Nutrition starts at 900 and normally falls by 1 per game turn; combat and equipment can burn more. Hungry is 50-149, Weak 0-49, Fainting below 0 and may cause unconsciousness. Act before Weak. (Nutrition, rev 2026-08-27)
- A food ration gives about 800 nutrition over about five actions; Valkyries start with 1-2. A successful prayer may restore nutrition to 900. (Food ration, rev 2026-08-28; Nutrition, rev 2026-08-27)
- Hungry is minor trouble; Weak or worse is major. Timeout starts at 300, drops per game turn, and must be <101 for minor, <201 for major, or zero otherwise. Its random reset after prayer is usually 50-1000; 1,229 covers only 95% of pleased-god resets. (Nutrition, rev 2026-08-27; Prayer timeout, rev 2026-05-11)
- Consider prayer for Weak+ only with an estimated safe timeout and no known disqualifier. Negative Luck/alignment, divine anger, another god's altar, Gehennom or an unsuitable polymorph can spoil it; prayer consumes three helpless turns. Do not claim hidden values or guaranteed success. (Prayer, rev 2026-06-09)

## Non-goals

- Do not infer exact nutrition, timeout, Luck or alignment from hunger text; do not choose prayer from this card alone or invent confirmation keys. (Nutrition, rev 2026-08-27; Prayer, rev 2026-06-09)
