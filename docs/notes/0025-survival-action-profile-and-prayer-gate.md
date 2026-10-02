# 0025: Survival action profile and prayer gate roles

Date: 2026-10-01

Milestone 2 item 6 adds `nle-survival-actions`: the ordered 58-member
`nle-hunger-actions` profile plus `Command.PRAY` (integer command 240), for 59
unique actions. `Command.EAT` retains its hunger role, added inventory letters
retain their item-prompt role, and PRAY has its own restricted role. The
`CompassDirection.NW` command already uses `y`; it remains a single action,
not a second confirmation-specific index. The old action profiles and the
current policy, knowledge bundle, skill arbiter, and task progression do not
change.

## Direct NLE 1.3.0 evidence

The real-environment tests call `NleEnvironment.step` directly to learn what
NLE offers, bypassing (not weakening) the policy gate. The projected raw
message strings include a trailing space:

```text
"Are you sure you want to pray? [yn] (n) "
"There is a lichen corpse here; eat it? [ynq] (n) "
```

Both observations have `PromptState(True, False, False)`. Seed 6 produces the
prayer prompt after one `Command.PRAY`. On seed 10, one southeast move kills an
adjacent lichen (`You kill the lichen!`); another southeast move reaches its
corpse (`You see here a lichen corpse.`); `Command.EAT` then produces the
floor-corpse confirmation. These are evidence of the *prompt contract*, not
approval to eat a lichen or to pray in the current agent policy.

## Authorization boundary

`ActionGate` does not offer PRAY, EAT, added prompt keys, or the ambiguous
`y`/northwest action to model fallback on this profile. The coordinator has no
prayer skill or prayer-permit issuer yet, so **every PRAY proposal is rejected**,
including one that claims to come from `Skill.PRAYER`; persisted PRAY steps are
also rejected by event validation. Item 7 owns safe prayer-permit issuance.
The existing hunger skill still uses a typed `HungerPermit` and selects only an
observed safe ration while Hungry or worse. No corpse-eating skill or permit is
issued in this item; the safe prompt handler still declines corpse and prayer
confirmations.

For `y` during a prompt, an exact prayer confirmation needs
`PromptPermit(y, PRAYER_CONFIRMATION)` from a deterministic prayer-prompt
selection; an exact floor-corpse confirmation needs
`PromptPermit(y, CORPSE_CONFIRMATION)` from a deterministic hunger-prompt
selection. A matching item-selection prompt can authorize inventory letter
`y` with the existing `PromptPermit(y, ITEM)` if it literally offers `y`.
Wrong text, wrong prompt kind, wrong skill, wrong letter, or absent permit fails
closed. Ordinary deterministic northwest movement outside prompts stays legal,
while model fallback never receives `y`. The gate and evaluator call the same
pure PRAY/confirmation predicates; the event contract checks structural
selection provenance and rejects prayer attempts without an issuer. The
evaluator additionally re-derives EAT and item-answer authorization from each
step's preceding projected observation, instead of trusting the claimed skill.

No prayer or corpse-eating outcome is asserted by these prompt-capture tests.
The milestone `descend-d5-v1` suite and its policy-pinned run remain future work.
