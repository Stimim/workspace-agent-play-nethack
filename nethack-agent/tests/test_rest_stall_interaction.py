"""Candidate 0059: interactions of Elbereth rest (0057) and the stall budget (0054).

Decisions under test (ARCHITECTURE.md, "Isolated candidate 0059"):

1. A protected rest is `.` (MiscDirection.WAIT): it neither searches nor
   waits on a blocker, so it adds no search coverage and no blocker waits.
   Otherwise eight rests would spend MONSTER_WAIT_LIMIT and twenty would
   fake SEARCH_CANDIDATE_CAP coverage, authorizing local-recovery departure
   (even from a protected target level) without a single real search.
2. Rest turns are residence turns: the no-progress clock keeps running while
   the hero rests, so resting cannot extend a stall's total food cost.
3. Navigation, local-recovery and disengage evidence are mutually exclusive
   on one ActionIntent.
4. A deterministic rest step ends a stuck spell in the coordinator and in
   replay alike, so the next stuck report may consult the model at once.
"""

from dataclasses import replace

import pytest
from test_disengage_integration import combat as combat_fixture
from test_disengage_integration import selection as recovery_selection
from test_navigation_budget_contracts import context as context_fixture
from test_navigation_budget_contracts import payload
from test_skills import remembered, sketch
from test_skills import template as template_fixture

from nethack_agent.contracts import ContractError
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DestinationKind,
    DisengageEvidence,
    IntentDestination,
    LocalRecoveryEvidence,
    MapCell,
    NavigationEvidence,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    StuckReason,
)
from nethack_agent.events import DecisionMetrics
from nethack_agent.navigation import ActionKind, DungeonMemory
from nethack_agent.navigation_budget import (
    MONSTER_WAIT_LIMIT,
    SEARCH_CANDIDATE_CAP,
    local_recovery_evidence,
)
from nethack_agent.observation import PromptState
from nethack_agent.planner import ObjectivePlanner
from nethack_agent.replay import (
    STUCK_RECONSULT_STEPS,
    ExplorationReplay,
    derive_action_record,
)
from nethack_agent.tasks import STAIRCASE_TASK
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    FindOracleLeg,
    LevelKey,
    Objective,
)

combat = combat_fixture
context = context_fixture
template = template_fixture

ROOM = ("       ", " ----- ", " |@..| ", " ----- ", "       ")
RESTS = SEARCH_CANDIDATE_CAP + MONSTER_WAIT_LIMIT


def rest_evidence() -> DisengageEvidence:
    return DisengageEvidence("wait", ord("."), 1, 50, 2, 2, 8, 0, 14, 3, 0)


def rest_selection() -> ActionSelection:
    return ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.DISENGAGE,
        SkillSelectionSource.ARBITER,
        None,
        0,
        "Owned recovery rest.",
        ActionIntent(None, None, None, disengage=rest_evidence()),
    )


def protect(agent, before):
    """Drive the scripted engraving transaction until protection is verified."""
    recovery = agent._disengage
    memory = agent._dungeon.current
    responses = [
        ("What do you want to write with? [- ab or ?*] ", (1, 0, 0), 0),
        ("You write in the dust with your fingertip.", (0, 1, 1), 0),
        ("What do you want to write in the dust here? ", (0, 1, 0), 0),
        *(
            (
                "What do you want to write in the dust here? " + "Elbereth"[:i],
                (0, 1, 0),
                0,
            )
            for i in range(1, 9)
        ),
        ("", (0, 0, 0), 1),
        ("Something is written here in the dust.", (0, 0, 1), 0),
        ('You read: "Elbereth".', (0, 0, 0), 0),
    ]
    for message, flags, turn_delta in responses:
        recovery.observe(before, memory, prayer_available=False)
        evidence = recovery.expected(before)
        after = replace(
            before,
            step_index=before.step_index + 1,
            message=message,
            prompt=PromptState(*(bool(f) for f in flags)),
            player=replace(before.player, turn=before.player.turn + turn_delta),
        )
        recovery.advance(evidence, after)
        before = after
    recovery.observe(before, memory, prayer_available=False)
    assert recovery.protected(before)
    return before


def test_coordinator_rest_record_spends_no_search_or_wait_allowance(combat):
    agent, before, _ = combat
    before = protect(agent, before)
    proposal = agent._disengage.select_action(before, agent._gate.actions_by_command)
    assert proposal is not None
    assert proposal.intent.disengage.phase == "wait"
    assert agent.legal_actions[proposal.action_index].name == "MiscDirection.WAIT"
    assert proposal.record.kind is ActionKind.OTHER
    # The replay derivation of the same committed step agrees.
    chosen = recovery_selection(agent, before, proposal.intent.disengage)
    memory = agent._dungeon.current
    assert (
        derive_action_record(chosen, "MiscDirection.WAIT", memory).kind
        is ActionKind.OTHER
    )
    coverage = dict(memory.search_coverage)
    waits = memory.monster_waits
    for _ in range(RESTS):
        memory.record(proposal.record)
    assert memory.search_coverage == coverage
    assert memory.monster_waits == waits


def test_rests_cannot_authorize_local_recovery_departure(template):
    """Without decision 1, RESTS rests would make this level count as spent."""
    dungeon = DungeonMemory()
    memory = dungeon.observe(sketch(template, ROOM, dungeon_level=3))
    ObjectivePlanner(Objective((FindOracleLeg(),))).plan(0, dungeon)
    assert local_recovery_evidence(memory, "find_oracle") is None
    chosen = rest_selection()
    origin = sketch(template, ROOM, dungeon_level=3)
    for step in range(1, RESTS + 1):
        memory.record(derive_action_record(chosen, "MiscDirection.WAIT", memory))
        memory.observe(
            replace(
                origin,
                step_index=step,
                player=replace(origin.player, turn=origin.player.turn + step),
            )
        )
    assert memory.monster_waits == 0
    assert not memory.search_coverage
    assert local_recovery_evidence(memory, "find_oracle") is None


def test_rest_turns_spend_the_no_progress_clock(template):
    """Decision 2: resting is residence time, never a paused or refilled clock."""
    memory = remembered(template, ROOM)
    origin = sketch(template, ROOM)
    chosen_record = derive_action_record(rest_selection(), "MiscDirection.WAIT", memory)
    elapsed = memory.navigation_elapsed
    for step in range(1, 51):
        memory.record(chosen_record)
        memory.observe(
            replace(
                origin,
                step_index=step,
                player=replace(origin.player, turn=origin.player.turn + step),
            )
        )
    assert memory.navigation_elapsed == elapsed + 50


def test_intent_keeps_navigation_recovery_and_disengage_exclusive():
    disengage = rest_evidence()
    navigation = NavigationEvidence("search", MapCell(1, 1), (MapCell(0, 1),), 3, 9, 0)
    recovery = LocalRecoveryEvidence(
        "find_oracle", LevelKey(0, 3), 3, 401, False, False
    )
    stairs = IntentDestination(DestinationKind.DOWNSTAIRS, 4, 1)
    with pytest.raises(ContractError):
        ActionIntent(None, None, None, navigation=navigation, disengage=disengage)
    with pytest.raises(ContractError):
        ActionIntent(stairs, None, None, local_recovery=recovery, disengage=disengage)
    for intent in (
        ActionIntent(None, None, None, disengage=disengage),
        ActionIntent(None, None, None, navigation=navigation),
        ActionIntent(stairs, None, None, local_recovery=recovery),
    ):
        assert ActionIntent.from_json(intent.to_json()) == intent


def test_replay_rest_step_ends_stuck_spell_like_the_coordinator(context):
    observation, actions, _, selection, _ = context
    wait = next(action for action in actions if action.name == "MiscDirection.WAIT")
    stuck = replace(
        selection,
        action_index=wait.index,
        skill_selection=SkillSelectionSource.MODEL,
        stuck_reason=StuckReason.NAVIGATION_BUDGET_EXHAUSTED,
    )
    rest = replace(
        selection,
        skill=Skill.DISENGAGE,
        action_index=wait.index,
        rationale="Combat recovery: wait.",
        intent=ActionIntent(None, None, None, disengage=rest_evidence()),
    )
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)

    def event(step, chosen, consult=False):
        result = payload(replace(observation, step_index=step), wait, chosen)
        return replace(
            result,
            skill_decision=SkillDecision(
                chosen.goal, Skill.EXPLORE_LEVEL, "Consult the scripted model."
            )
            if consult
            else None,
            skill_metrics=DecisionMetrics(1, 1, 0.0, False) if consult else None,
        )

    assert replay.step(event(1, stuck, True)) is None
    assert replay.step(event(2, stuck, True)) is None
    memory = replay._dungeon.current
    assert memory.stuck_consult_step == 1
    rests = 3
    for step in range(3, 3 + rests):
        assert replay.step(event(step, rest)) is None, step
    assert memory.stuck_consult_step is None
    assert memory.monster_waits == 0
    assert not memory.search_coverage
    # Well inside the interval after the last consultation (decided on step
    # index 1), but the rest ended the stuck spell, exactly as the
    # coordinator's commit does.
    assert (3 + rests - 1) - 1 < STUCK_RECONSULT_STEPS
    assert replay.step(event(3 + rests, stuck, True)) is None
