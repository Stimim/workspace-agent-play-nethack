# 0043: Single-rule low-HP prayer qualification

## Frozen protocol

Baseline is correction commit c374aeb, copied to `/tmp/single-rule-3a-baseline` before candidate edits. Candidate adds only the NetHack 3.6.7 major-trouble HP predicate to existing prayer selection and authorization. Initial turn 100 and repeat wait 1229 remain unchanged; no retreat, rest, disengagement, or hazard rule is included. Low-HP prayer takes priority over melee and food when timeout-safe, with existing prompt/altar exclusions unchanged.

Reserve fresh seeds 211-240 before either arm. Run both arms on the 67-seed unified development suite and this same fresh sample, Score/survival/reach-D5/cap3000, scripted development model, survival-reviewed-v2. Freeze product before candidate episodes. Note 0040 gates apply: objectives not lower, deaths not higher, fresh hunger deaths not higher, zero invalid actions/gate rejections/integrity problems, complete records; trace every lost success/new death, no unexplained or behavior-defect loss ships. All artifacts remain under `/tmp`. Explicit background timeouts avoid tooling cutoff. Any changed candidate requires a new frozen sample, never rerun failures as replacements.

## Candidate freeze

Before candidate episodes, prayer boundary tests passed (8 tests).
Product SHA-256:

- decision.py: `5650b430bbd8a76f5d0b4804c77dd305d4bb279a4dd27831226115a45b3062ac`
- skills.py: `4f258b08b6065da525868a2f88e1b3adc06299cd6387fcaed8e77519a309c734`
- coordinator.py: `fd256bf817cbb5de4fc8a69f431bbf46639ed37b7a2bb4771d4725bac4d0b5d8`
- evaluation.py: `a6c5804595bc13fd62f184f3137136a359a1d2f05f3d64a107706dd4d41b7976`

## Superseded first frozen sample: 211-240

All four arms completed without cutoff: dev 52→54 objectives, deaths 8→6;
fresh 24→24 objectives, deaths 3→3, zero gate rejections. No lost success
or new death occurred. Stored trace inspection exposed a priority defect:
the coordinator's pre-prayer adjacent-hostile defense returned before the
prayer skill could act (fresh 220 at 5 HP/turn888 and 232 at 1 HP/turn424).
The candidate therefore did not fully implement the requested low-HP rule.
It is superseded, not shipped despite passing aggregate gates. Move prayer
selection before that defense; hunger prayer still proposes its existing
defense action, so only eligible low-HP prayer gains priority.
Seeds 211-240 are consumed, never reused; corrected candidate reserves
241-270. Reports and traces remain in `/tmp/3a-{base,cand}-{dev,fresh}`.

Corrected freeze (before new episodes): decision.py
`dd478199c9b64269e1970aa4591c1da723c80fe8ec8605908c2404d3f8778818`;
coordinator.py `7f31287e5d144670da7694d93a563dd5515f6ef506b5c68755fb35e94aae6a51`.
skills.py/evaluation.py hashes unchanged. Coordinator arbitration smoke
with 5 HP, ration and adjacent jackal chooses authorized PRAY; at turn99
it retains melee. The prior incidental assertion about which skill labels
ordinary hunger-defense was removed; its actual attack-target assertion remains.
Full tests initially found five failures from pre-existing ledger notes
exceeding the schema's 300-character limit; notes were shortened with full
history retained in note 0042, and all five affected tests then passed.

## Final qualification and decision: SHIP 3a

Corrected candidate completed without cutoff. Dev baseline 52 objectives,
8 deaths, 7 truncations; candidate 54 objectives, 5 deaths, 8 truncations.
Fresh 241-270 baseline 25 objectives, 4 deaths, 1 truncation; candidate
29 objectives, 0 deaths, 1 truncation. Fresh hunger deaths 1→0 by last-live
hunger/starvation criterion. Both sets/arms have zero invalid actions,
gate rejections and integrity failures. No lost success or new death occurs
on either set: the required causal-loss table is empty.

| Fresh seeds | Baseline | Candidate |
| --- | --- | --- |
| 241-242, 244-246, 248-249, 251-254, 256-266, 268-270 | objective_complete | objective_complete |
| 243, 247, 250, 267 | death | objective_complete |
| 255 | truncated | truncated |

| Causal evidence | Public state immediately before first changed action |
| --- | --- |
| Fresh 243 | Step569, HP1/max25/XL2, turn575: candidate PRAY instead of baseline melee. |
| Fresh 247 | Step777, HP3/max18/XL1, turn774: candidate PRAY instead of baseline melee. |
| Fresh 250 | Step378, HP4/max18/XL1, turn377: candidate PRAY; eventual baseline death is absent in candidate. |
| Fresh 267 | Step223, HP4/max18/XL1, turn221: candidate PRAY instead of baseline melee. |
| Dev losses/new deaths | None; 900/1362 improve death→success, 1379 death→truncated. |

Reports: `/tmp/3a-base-dev/reports/unified-d5-regression-v1-development-20261004T082653Z.json`,
`/tmp/3a2-cand-dev/reports/unified-d5-regression-v1-development-20261004T085711Z.json`,
`/tmp/3a2-base-fresh/reports/prayer-3a-fresh-241-270-development-20261004T085727Z.json`,
`/tmp/3a2-cand-fresh/reports/prayer-3a-fresh-241-270-development-20261004T085719Z.json`.
Comparison exports: `/tmp/3a2-{dev,fresh}-comparison.json`. All SQLite events
and native ttyrecs stay with those data dirs. Full corrected tests: 614 pass,
three dependency warnings. This is scripted development qualification,
not real-model milestone acceptance.

Ship the exact qualified decision/skill/coordinator/evaluator behavior.
Metadata-only integration assigns policy `hierarchical-survival-hp-prayer-v1`
and new immutable `unified-d5-regression-v2`; qualification reports retain
their original old policy label and frozen file hashes, not relabeled evidence.
Knowledge remains survival-reviewed-v2. Existing prayer outcome classification
reports hunger, not HP healing; HP recovery evidence is the public trace.
No retreat, rest, disengagement, hazard gate or generic retry is included.
