# 0026: Deterministic prayer and real-NLE outcome probes

Date: 2026-10-01

Milestone 2 item 7 activates a deterministic prayer skill only for
`nle-survival-actions`. It does not change `POLICY_VERSION`, the selected
knowledge bundle, existing suite/report pins, or model-owned decisions. Seeds
1100–1129 were development probes, **not** untouched evaluation seeds; the
used-seed ledger records the full range.

## NLE 1.3.0 evidence

A direct SEARCH-only development probe reached the first Weak state at turn
851 on five seeds from 1100–1109, without killing any monsters. All five
issued PRAY, confirmed the exact prayer prompt with `y`, and received an
outcome on that `y` step three game turns later. Two restored hunger; three
finished still Weak. The other five seeds did not reach Weak in that probe.

| SEARCH-only seed | PRAY turn | Following outcome message | Hunger after | Result |
| ---: | ---: | --- | --- | --- |
| 1101 | 851 | `Your stomach feels content.` | Not Hungry | fixed |
| 1104 | 851 | `You finish your prayer.  You feel that Tyr is satisfied.` | Weak | not fixed |
| 1107 | 851 | `You feel that Tyr is satisfied.  Your stomach feels content.` | Not Hungry | fixed |
| 1108 | 851 | `You finish your prayer.  You feel that Tyr is satisfied.` | Weak | not fixed |
| 1109 | 851 | `You finish your prayer.  You feel that Tyr is satisfied.` | Weak | not fixed |

With the real coordinator and scripted development model, 11 of seeds
1110–1129 reached Weak after normal combat and ration handling; every one of
those 11 prayers restored hunger. The other nine died before Weak, so they are
**not** prayer failures:

| Seed | Observed `You kill` messages before PRAY | PRAY turn | Outcome |
| ---: | ---: | ---: | --- |
| 1112 | 10 | 1633 | `Your stomach feels content.`; Not Hungry |
| 1113 | 7 | 2440 | same; Not Hungry |
| 1114 | 26 | 1587 | same; Not Hungry |
| 1115 | 14 | 1623 | same; Not Hungry |
| 1117 | 21 | 1612 | same; Not Hungry |
| 1118 | 17 | 1609 | same; Not Hungry |
| 1119 | 22 | 1621 | same; Not Hungry |
| 1120 | 27 | 1605 | same; Not Hungry |
| 1126 | 18 | 1621 | same; Not Hungry |
| 1127 | 15 | 985 | same; Not Hungry |
| 1128 | 8 | 1635 | same; Not Hungry |

Negative controls prayed at turn 50 while Not Hungry: seed 1110 received
`"Thou must relearn thy lessons!"  You feel foolish!`, while seeds 1111 and
1112 received `You feel that Tyr is displeased.` All three stayed Not Hungry;
no HP loss was observed in those controls. Immediate second prayers after a
first outcome at turn 854 (seeds 1101, 1104, 1107) produced displeased or
foolish messages at turn 857. Those are observations of **bad prayers**, not
evidence of safety in the current skill.

The reviewed [Prayer page](https://nethackwiki.com/wiki/Prayer) in the local
NetHackWiki dump (2026-06-09T21:29:39Z revision) says alignment record
positive but below 4 always yields result 1, “Fix one major problem”; record
zero yields that result with chance `!rnl(2)` (about half at Luck 0). “Satisfied”
means alignment record 0–3, not proof of success or a positive record;
“pleased” covers 4–13 and “well-pleased” at least 14. The reviewed
[prayer/hunger card](../../nethack-agent/knowledge/prayer-hunger.md) records
the timeout and trouble thresholds. [INFERENCE] Combat may raise the hidden
alignment record and explain the difference between the 2/5 SEARCH-only and
11/11 combat observations, but the probes expose neither that record nor Luck;
the samples do not establish a reliable success probability. A stored count of
literal `You kill` messages is **only an observation proxy**, never a gate.

## Authorization and recorded evidence

The prayer skill runs only at Weak or worse (NLE hunger index >=3), only with
no recognized safe ration, no active prompt, and no observed altar under the
hero. Eating a known ration has priority; fighting a safe adjacent hostile has
priority over spending three helpless turns in prayer; a valid prayer can
precede ordinary stair navigation. The initial timeout is 300 and major
trouble requires timeout <201: by turn 100, the nominal estimate is 200, so
100 is the first allowed game turn (not the previously proposed 101). This is
a bound on **estimated** timeout, not an observation of hidden game state.

After any prayer, another is eligible only after at least 1,229 game turns,
provided the same Weak/ration/prompt/altar checks still hold. The reviewed
card's 1,229-turn upper bound covers only **95%** of pleased-god timeout
resets; the remaining ~5%, plus hidden Luck/alignment/anger, leave residual
risk. No outcome, including failure to restore hunger, bypasses the interval.
The model never receives PRAY or the ambiguous `y` key. The coordinator issues
a one-turn `PrayerPermit` only when the shared pure predicate accepts the
prior live observation and the tracked prayer history. The exact observed
`Are you sure you want to pray? [yn] (n) ` message receives `y` only while
that PRAY is pending, through a typed `PromptPermit(y, PRAYER_CONFIRMATION)`.
The evaluator reconstructs prayer count, last turn, and recorded kill-message
count from event order and replays the same predicate instead of trusting the
claimed skill or permit.

Prayer intent records the Weak-or-worse trigger, game turn, nominal safe bound,
observed kill-message count, and the outcome on the following live `y`
observation. Outcome is **fixed** when hunger falls below Weak or the exact
stomach-content message appears; **displeased/punished** for the two observed
bad-prayer messages; otherwise **not fixed** when a completed prayer leaves the
hero Weak or worse. NLE zeroes stats on terminal observations: a terminal or
truncated `y` step has no classified outcome; an ongoing live `y` step must
record one. Neither classification nor kill count is a claim about hidden
prayer timeout, Luck, alignment record, or divine anger.

A real-NLE regression on seed 1127 runs the coordinator to its first Weak
prayer, checks the skill-gated PRAY and prompt answer, typed outcome, and
evaluator audit. The production fresh-sample acceptance suite remains future
milestone work; these now-used development seeds cannot enter its fresh draw.
