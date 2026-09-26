# ADR 0002: Deterministic skill arbiter for the staircase milestone

- Status: accepted
- Date: 2026-09-27
- Refines: [ADR 0001](0001-initial-product-and-runtime.md) ("Gemma chooses
  goals or skills; deterministic code validates and executes")

## Context

ADR 0001 planned for the local model to choose goals and skills while
deterministic code executed them. The first implementation had only one skill,
`staircase_navigation`, and it acted only while a downstairs was visible. Every
other action went to a model fallback. In the first real-model suite run, seed 1
spent all 1,000 actions on model fallbacks. Most were waits and repeated moves,
and 35 were `MiscDirection.UP`, which leaves the dungeon from level 1. Each
decision took about 6.4 s, so the run would have taken about 17 hours with
little chance of passing. It was aborted; see
[note 0007](../notes/0007-exploration-policy-and-staircase-acceptance.md).

When the model was asked to choose between `staircase_navigation` and the new
`explore_level` skill, it picked `staircase_navigation` for every seed, even
with no downstairs known. That skill cannot act in that state.

## Decision

- A deterministic arbiter owns skill switching on every step. It picks
  `staircase_navigation` whenever a remembered downstairs is reachable, and
  `explore_level` otherwise.
- The model is still consulted at the start of an episode, and its goal and
  skill decision is recorded, but it cannot override the arbiter.
- The model's skill choice binds only after exploration reports a typed stuck
  reason. Then `explore_level` re-arms a bounded search round, while
  `staircase_navigation` hands actions to model fallbacks. Such consultations
  happen at most once per 20 stuck steps.
- The model chooses the action for any prompt that the safe prompt handler and
  the exploration kick flow do not answer.
- Each step records who selected the skill (`arbiter` or `model`) and the stuck
  reason. A model-selected skill must match that step's model skill decision.
- The action gate rejects both level changes (`MiscDirection.UP` and
  `MiscDirection.DOWN`) whatever layer proposed them.
- In later milestones, the model should own high-level choices whose outcomes
  depend on context rather than fixed mechanics: whether to accept the risk of
  descending or gather levels/resources first, whether to pray or use another
  recovery, which visible threat to prioritize, and which branch goal to pursue.
  Deterministic skills still execute and gate the selected plan.
- The playing agent may use the model to handle an unfamiliar situation during
  a fixed episode. It does not rewrite policy, prompts, skills, or knowledge.
  After the episode or fixed suite, coding agents review the persisted
  observation/decision/outcome evidence. They may update reviewed knowledge for
  a nuanced recurring situation or add a tested deterministic skill when the
  recurring decision is simple. Those versioned changes apply only to a later
  run or suite.

## Consequences

- The milestone suite passed 10/10 with the real model in 34 s. Every one of
  its 1,868 actions was deterministic.
- **Risk: the local model contributes little to milestone-1 success.** Its start
  decision is overridden, and no suite seed reached a stuck state or an
  unhandled prompt. The result shows that the deterministic skills work. It
  does not show that model reasoning works. Held-out development seeds reach
  stuck consultations, where the model's choice does change behavior (see note
  0007).
- Evaluation cost and variance fall sharply. The trajectory no longer depends on
  temperature-0 GPU nondeterminism unless the model is consulted.
- Skill behavior can be tested without Ollama. The scripted development model
  reproduces a real run exactly until the first consultation.
- The goal/skill contracts, the prompts, and the one-repair policy remain in
  place, so later milestones can hand real choices back to the model.
- The model retains an explicit role despite contributing no action to the
  accepted suite: bounded unfamiliar-situation handling now, and
  risk/resource/recovery/threat/branch decisions once committed evaluations
  contain meaningful alternatives.
- The between-run improvement loop can turn observed failures into reviewed
  guidance or deterministic skills without contaminating a fixed episode or
  evaluation suite. There is no gameplay self-modification.

Revisit this decision when any of these holds:

- a later milestone offers several applicable skills or goals with real
  trade-offs, such as combat risk, hunger, items, or descending;
- held-out evaluation shows stuck consultations or unhandled prompts decide
  outcomes often enough to measure model quality;
- a candidate local model beats the arbiter on a committed suite.
