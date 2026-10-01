# 0024: Reviewed early-survival knowledge

Date: 2026-10-01

## Sources and boundaries

This review extracted only the named pages from the ignored local
`docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml`; the dump is
research evidence, not player context. Pages are NetHackWiki contributors'
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) work. Their
snapshot revision timestamps and canonical pages are:

| Page and local-dump revision (UTC) | Reviewed claim and version check |
| --- | --- |
| [Nutrition](https://nethackwiki.com/wiki/Nutrition), 2026-08-27T17:21:31Z | Starting nutrition 900, normally one per game turn; Hungry 50–149, Weak 0–49, Fainting below zero, prayer restores to 900; article cites NetHack 3.6.7 `eat.c` and `attrib.c`. |
| [Food ration](https://nethackwiki.com/wiki/Food_ration), 2026-08-28T10:28:40Z | 800 nutrition, about five actions, Valkyrie 1–2 starting rations; 3.6.7 source references. |
| [Prayer timeout](https://nethackwiki.com/wiki/Prayer_timeout), 2026-05-11T14:09:43Z | Initial 300, decreases by game turn; major trouble accepts timeout below 201, minor below 101; pleased-god 95th-percentile reset 1,229. Page carries a 3.4.3 tag; 3.7-only changes are excluded, and these are not promises of a successful prayer. |
| [Prayer](https://nethackwiki.com/wiki/Prayer), 2026-06-09T21:29:39Z | Three helpless turns; negative Luck/alignment record, divine anger, unsuitable altar/form, Gehennom and too-short timeout can defeat prayer. Page includes 3.6.7 and 3.6.6 source references. |
| [Corpse](https://nethackwiki.com/wiki/Corpse), 2026-08-27T17:10:32Z | Age-dependent rottenness, +2 for cursed, old at ≥4, tainted at ≥6, independent 1/7 rotten-food chance; poisonous, acidic, petrifying, undead and slime hazards. Aging portions cite 3.6.0 source code and are applied conservatively to 3.6.7. |
| [Cannibalism](https://nethackwiki.com/wiki/Cannibalism), 2025-08-24T17:32:45Z; [Lycanthropy](https://nethackwiki.com/wiki/Lycanthropy), 2026-08-22T04:43:20Z | Eating one's race costs 2–5 Luck and aggravates monsters; werecreature meat can convey lycanthropy. Both cite 3.6.7 code. |
| [Lichen](https://nethackwiki.com/wiki/Lichen), 2024-11-17T19:34:55Z; [Newt](https://nethackwiki.com/wiki/Newt), 2026-06-02T18:31:39Z; [Sewer rat](https://nethackwiki.com/wiki/Sewer_rat), 2024-12-10T06:26:39Z; [Giant rat](https://nethackwiki.com/wiki/Giant_rat), 2024-02-09T13:46:19Z; [Gecko](https://nethackwiki.com/wiki/Gecko), 2023-11-22T11:10:12Z | Narrow candidate corpses. Lichen does not rot; newt can raise power. Other species pages list no intrinsic meal hazard; this is not a proof of zero risk, so observed identity/freshness and residual rotten-food risk remain mandatory. |
| [Grid bug](https://nethackwiki.com/wiki/Grid_bug), 2026-05-14T03:49:35Z; [Jackal](https://nethackwiki.com/wiki/Jackal), 2026-08-20T02:09:20Z; [Coyote](https://nethackwiki.com/wiki/Coyote), 2026-08-20T02:10:49Z; [Fox](https://nethackwiki.com/wiki/Fox), 2026-08-20T02:09:04Z | Grid bug is corpseless. Canids may count as cannibalism with werejackal lycanthropy; the current pages mix 5.0 text with explicit 3.6.1 historical references, so all are excluded rather than treating them as unconditionally safe for 3.6.7. |
| [Green slime](https://nethackwiki.com/wiki/Green_slime), 2026-05-14T04:16:30Z; [Medusa](https://nethackwiki.com/wiki/Medusa), 2026-09-13T22:39:37Z | Green slime globs cause sliming (3.6.0+); Medusa's flesh stones the eater (3.6.7 references). The Corpse page separately covers these and cockatrice/chickatrice petrification. |

The revised **19-game-turn** age cap corrects ADR 0005's proposed 30-turn
limit: with an unknown cursed corpse, `19 / 10 + 2 = 3` (<4 old and <6
tainted), whereas `30 / 10 + 2 = 5` can be **old**. `Corpse` still gives a
separate 1/7 rotten-food chance for many ordinary fresh corpses; no card
promises that a meal is perfectly safe. Do not infer corpse age from a corpse
glyph or infer species from a coincident monster glyph. Only a matching
observed kill and current corpse on its cell may supply conservative evidence;
all other corpse offers are declined. NLE's exact yes/no corpse and prayer
prompt texts were not verified by this dump review. Choking thresholds appear
in Nutrition but are omitted from these narrow cards rather than made into a
new prompt rule. Exact divine timeout, Luck, alignment record, and
anger are not fields in the projected player observation; prayer safety cannot
be guaranteed from hunger status alone. Later gate/skill work must provide
and audit its own evidence, not defer actions to model speculation.

## Bundle choice

The new named, explicitly loadable
`nethack-agent/knowledge/manifest.survival-reviewed-v1.json` is
`survival-reviewed-v1`: `survival` names the new scope and `v1` begins a new
bundle lineage after the existing `staircase-reviewed-v3`. It pins existing
stairs and exploration cards plus `prayer-hunger.md` and `safe-corpses.md`,
with SHA-256 per card. `safe-interaction.md` remains in the **unchanged** default
manifest but is not repeated here: all five cards would exceed the existing
6,000-character/1,500-estimated-token prompt budget. Prompt answers, eating,
and prayer are deterministic gate concerns, not delegated to the model.

The explicitly selected context rendered to **5,917 characters / 1,480
estimated tokens** (limit 6,000 / 1,500); unchanged default rendered to
4,546 / 1,137. The named version's SHA-256 is
`adc8e5d31ecc5ed02a218553fcbdfc402cb6d4045f8f44aa072b1aceb15562da`.
Current policy `hierarchical-task-specialists-v1`, committed suite pins, and
`load_default_knowledge_bundle()` still use `staircase-reviewed-v3`; adoption
is reserved for the new milestone policy after action gates and skills are
implemented and tested. No playing episode or real-model milestone evaluation
was performed for this source review.
