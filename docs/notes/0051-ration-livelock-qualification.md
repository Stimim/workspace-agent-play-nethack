# 0051: Ration-selection live-lock qualification

Phase 4's first item: fix the hunger-skill `EAT`/`ESC` live-lock found by the
note 0050 baselines (Minetown seed 1362, Oracle seed 6). One rule, qualified
under the note 0040 protocol on both milestone-3 targets plus
`unified-d5-regression-v4`.

## Defect

When `HungerSkill` opens `EAT`, it remembers the ration it verified and, on
the item prompt, answers with that ration's current inventory letter. It
answered only when exactly one inventory item matched the remembered ration
(`_same_ration`). Two stacks with the same description, for example two
`a partly eaten food ration` items in slots `o` and `p`, made the match
ambiguous, so the skill cancelled with `ESC` ("Never mind."). Hunger was
unchanged, so the next decision opened `EAT` again. Each pair costs two
action steps and no game turn: the stored events of Oracle seed 6 show
`EAT`/`ESC` from step 4269 to the 10,000-step cap with the game turn fixed at
4285.

## Change

`skills.py`: with one or more matching rations, prefer the match whose letter
equals the remembered one, else the first match. Every match is the same
reviewed safe ration, so either choice is correct. The answer must still be an
offered letter; changed or missing ration evidence still cancels. Regression
`test_hunger_skill_with_multiple_identical_rations_resolves_prompt` builds two
identical partly eaten rations and asserts the prompt is answered with a
ration letter; it fails without the change and passes with it.

### Frozen SHA-256

- skills.py: `2bfda75a3e67642ce16d138148f03f1fadabf37aade638c2e3d877dcf2cb1124`
- test_skills.py: `a8283b85a74fe73dc318df651a2d5fade9bf4d804c009347adee3c78d24f7d78`
- minetown-fresh-v1.json: `6dff1fce1c6e71da914fd97985e48ff42dbf8ccd03e7ddcafc8db3a24b056e06`
- oracle-fresh-v1.json: `c11ce10dd642be9b3fe2be9c01eac35921f09f7d31455985223c340b1389ccf3`

## Protocol

Baseline is HEAD `a35ad1d` in an isolated checkout
(`~/nethack-evidence/0051/baseline`); the candidate is `a35ad1d` plus the
change above. Fresh seeds 511-540 were reserved in the ledger before either
arm and run as the frozen development suites `minetown-fresh-v1` and
`oracle-fresh-v1` (Score, survival profile, 10,000-step cap, scripted
development model, `survival-reviewed-v2`). Gates: objectives must not
decrease and deaths must not increase on any set, Weak-or-worse deaths must
not increase, zero invalid actions, gate rejections and integrity failures,
complete records, and every lost success or new death traced.

A first launch on 2026-10-06 was cut short by a host restart: the two
regression arms stopped at 62-63/67 and the other runs never started, since
the ledger entry and the fresh suites did not load. Those four partial reports
are marked `aborted` and are not evidence. The fresh suites were corrected to
the loadable schema-2 form before any fresh episode ran, so 511-540 was not
spoiled. All ten arms then ran to completion through the detached runner,
2 workers each, on 2026-10-12.

## Decision: QUALIFIED and shipped

| Set | Baseline | Candidate | Changes |
| --- | --- | --- | --- |
| unified-d5-regression-v4, 67 | 54 objective, 5 death, 8 truncated | identical | 0 |
| minetown-regression-v1, 67 | 19 objective, 42 death, 6 truncated | identical | 0 |
| oracle-regression-v1, 67 | 9 objective, 52 death, 6 truncated | 9 objective, 53 death, 5 truncated | seed 6 |
| minetown-fresh-v1, 511-540 | 6 objective, 20 death, 4 truncated | identical | 0 |
| oracle-fresh-v1, 511-540 | 6 objective, 23 death, 1 truncated | identical | 0 |

Weak-or-worse deaths by set (baseline/candidate) are unchanged:
unified-d5-regression-v4 0/0, minetown-regression-v1 20/20,
oracle-regression-v1 19/19, minetown-fresh-v1 7/7, oracle-fresh-v1 3/3.
Every arm has zero invalid actions, gate rejections and integrity failures,
and complete records.

Oracle seed 6, traced from stored public events: the arms diverge at step
4269, the first ration prompt. The baseline live-locks there until the cap.
The candidate answers `o`, keeps exploring Dlvl 5, finishes both rations,
and handles Weak hunger by prayer at turn 5620. At turn 5974 "You are
blinded by a blast of light!" (the message of an exploding yellow light)
leaves the hero blind for the remaining 81 steps; `explore_level` keeps
searching while an unseen iguana (the recorded death cause) bites it from
HP 38 to 0 at turn 6054, Not Hungry. No prayer followed: the last one was
434 turns earlier. This is an existing failure class
(Phase 3: status effects, escape when prayer is unavailable) reached after
trajectory divergence, not a ration-selection defect.

Minetown seed 1362 also leaves the live-lock (4,346 to 11,085 game turns at
the cap) but stays truncated on Dlvl 2: after finishing its meal it spends
4,538 steps of `staircase_navigation` searching for an unknown exit, the
Phase 2 stall class.

Shipped as policy `hierarchical-survival-hp-prayer-burden-look-ration-v1`
with knowledge `survival-reviewed-v2`, pinning new immutable
`unified-d5-regression-v5`, `minetown-regression-v2` and
`oracle-regression-v2` (copies changing only `suite_id` and
`policy_version`). The qualification suites, `*-fresh-v1` and the earlier
pinned suites, keep their original policy labels and are refused under the
new policy. Seeds 511-540 are consumed.

## Evidence

Compact per-seed records, `docs/notes/evidence/0051/` (`base-` and `cand-`
prefixes per arm; commit `a35ad1d`; the candidate adds the frozen
`skills.py` above). Raw databases, reports and run logs:
`~/nethack-evidence/0051/run2/`.

## Lessons

- The ration-identity check guarded against the wrong item, but treated
  "more than one correct item" like "no correct item". Ambiguity between
  equivalent choices should pick one, not cancel.
- A cancelled prompt that leaves its trigger unchanged loops at zero game
  turns; such loops hide every failure that would follow. Removing one
  exposed blindness handling and a Dlvl 2 stall.
- Suite files and the ledger must load before launching runs: four runs of
  the first launch failed in seconds on schema errors.
