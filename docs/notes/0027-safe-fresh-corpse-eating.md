# 0027: Fresh, observed safe-corpse eating

Date: 2026-10-01

Milestone 2 item 8 enables a deterministic corpse skill only with
`nle-survival-actions`. No policy-version or active knowledge-bundle change is
made. Seeds 1130–1149 are registered as used development seeds, not eligible
for the later fresh-sample acceptance draw.

## Stored-episode opportunity evidence

A read-only re-derivation used the actual `traversal-v2`, `scout-v1`, and
`eat-v1` reports' run IDs and their SQLite step observations: 25 **episode
records**, including repeated seed trajectories under different traversal
cases. It counted 258 observed kills. Of those, 116 were one of the five
reviewed species; a generic food-object corpse glyph at the inferred kill
cell or an exact matching look-here message was observed within the next
three steps for 53. Kills by monster name:

| Monster | Kills | Monster | Kills |
| --- | ---: | --- | ---: |
| newt | 48 | grid bug | 40 |
| lichen | 38 | jackal | 36 |
| goblin | 21 | kobold | 16 |
| sewer rat | 13 | fox | 10 |
| kobold zombie | 10 | gecko | 9 |
| giant rat | 8 | shrieker | 2 |
| iguana | 2 | gnome zombie | 1 |
| bat | 1 | coyote | 1 |
| large kobold | 1 | wererat | 1 |

An opportunity was counted at most once per killed monster when its corpse
was observed at age ≤19 game turns and within five **Chebyshev** squares of
the hero. That distance is an approximate evidence-filter, **not** proof of
a traversable route; the implemented skill requires a real BFS route of at
most five actions. The original Hungry-or-worse trigger produced just **four
opportunities / 432 potential nutrition**. Relaxing it to Not Hungry or worse
(NLE hunger ≥1, never Satiated) produced **54 opportunities / 5,426 potential
nutrition**, of which **35 / 4,284 nutrition** were observed before each
record's first Hungry turn. Taking one nutrition point as about one turn of
hunger postponement is [INFERENCE], not a measured agent result. Corpse glyphs
are generically named; attribution by location in the historical script was
[INFERENCE], not proof that a particular species' corpse was underneath.

The reviewed local [safe-corpse card](../../nethack-agent/knowledge/safe-corpses.md)
and NetHackWiki dump give the potential nutrition values below. The page
revisions are preserved in the card, not substituted from live web content:

| Allowed corpse | Potential nutrition | Local wiki revision |
| --- | ---: | --- |
| lichen | 200 | 2024-11-17 |
| newt | 20 | 2026-06-02 |
| sewer rat | 12 | 2024-12-10 |
| giant rat | 30 | 2024-02-09 |
| gecko | 20 | 2023-11-22 |

The card's ordinary-corpse age calculation justifies the ≤19-turn bound even
with unknown BUC, but a separate 1/7 rotten-food risk remains; this policy
is **low risk, not guaranteed safe**. Cannibalism, stoning, poison, acid,
sliming, lycanthropy, old and undead meat, pets, and unknown form or species
are never authorization by implication. Jackal, fox, and coyote are excluded
despite their frequency, as are kobolds and wererats. A parser recognizing a
name does not overrule the card's hard exclusions.

## Exact decision and replay boundaries

The coordinator remembers only a public `You kill the <name>!` message paired
with an attack against a displayed same-species monster on the before-map.
It considers a fresh corpse only on that kill cell on the same level, while
Not Hungry or worse, with no covering item, through a known passable route of
at most five steps. On the cell itself, the exact
`You see here a <name> corpse.` message must identify the same allow-listed
species before an `EAT` hunger-role permit is issued. An EAT that instead
opens the item-selection prompt is canceled with ESC. Only the exact next
`There is a <name> corpse here; eat it? [ynq] (n) ` prompt for **that same
observed kill** can be answered `y` through
`PromptPermit(y, CORPSE_CONFIRMATION)`; every other floor corpse is declined.
The model cannot request EAT, prompt-only keys, or the ambiguous `y` response.
The skill does not start another EAT while an existing meal is in progress.

The priority is adjacent-safe-hostile defense, eligible Weak prayer, a known
ration at Hungry or worse, a verified fresh corpse, then stairs/exploration.
A known ration still blocks Weak prayer under prayer's existing no-ration
safety rule. A corpse intent records the species, kill turn, age, kill cell,
and the live meal result when observable (finished, interrupted, or declined).
The evaluator re-derives the kill, age, cell, species, pending EAT, exact prompt,
and outcome from earlier persisted observations with the same authorization
predicate; a plausible-looking intent or a corpse of the wrong species is
never independent evidence.

Terminal or truncated confirmation and meal-continuation steps deliberately
carry no classified outcome, because NLE terminal statistics are not live
evidence. Live finished/interrupted messages must record the matching outcome;
a live meal still in progress carries none until its result is observable.
Regression coverage exercises both terminal and truncated cases for `y` and
WAIT and rejects fabricated outcomes or missing live completion evidence.

A direct NLE 1.3.0 control on seed 10, before gate adoption, observed a
lichen kill at game turn 2 while Not Hungry, an exact look-here message at
turn 3, the exact named floor prompt on EAT at turn 3, and an immediate `y`
completion at turn 7: `This lichen corpse tastes okay.  You finish eating the
lichen corpse.` Hunger moved from Not Hungry to Satiated. This illustrates
prompt timing, **not** the later coordinator regression or a survival rate.

## Coordinator regression and negative controls

A real scripted-coordinator `NetHackScore-v0` / `nle-survival-actions` run on
development seed **1131** observed a lichen kill at game turn 3 while
Not Hungry (hunger 1). At turn 4 the hero stood on the kill cell and observed
`You see here a lichen corpse.`; EAT received
`There is a lichen corpse here; eat it? [ynq] (n) ` at that same game turn.
The deterministic confirmation `y` finished at turn 8, moved hunger from
Not Hungry (1) to Satiated (0), and reported
`This lichen corpse tastes okay.  You finish eating the lichen corpse.`
The regression checks gated EAT and `y`, typed evidence, and the complete
event-stream evaluator audit (`invalid_actions = 0`, `gate_rejections = 0`).
Synthetic negative prompt controls verify that a jackal corpse offer is
declined, and that a corpse EAT yielding an inventory item prompt is canceled
with ESC instead of selecting an arbitrary item.

A separate actual-coordinator smoke reproduced this trajectory on 2026-10-03,
including kill cell `(48, 7)`, kill turn 3, EAT age 1, and the typed finished
outcome at turn 8. The scripted staircase regression also ran on
`NetHackStaircase-v0` / `nle-task-actions`, cap 1000: seeds 1–10 all ended
`task_success` at steps 217, 44, 222, 47, 147, 151, 286, 222, 102, and 430.

Seeds 1150–1169 are recorded separately in the ledger as development evidence:
bounded-search probe at `a58902a`, coordinator, `reach_level(0,5)`, cap 3000.
That registration does not claim a bounded-search implementation or acceptance
result in this item.

This is a one-seed behavioral regression, not a milestone survival evaluation.
The entire reserved 1130–1149 development range is excluded from the future
fresh sample in the used-seed ledger.
