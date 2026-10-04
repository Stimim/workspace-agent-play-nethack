import json
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from nle import nethack

from nethack_agent.coordinator import (
    ActionGate,
    ActionGateError,
    AgentCoordinator,
    CoordinatorBusyError,
    StepRecord,
)
from nethack_agent.corpse import CorpseKill, observed_corpse_kill
from nethack_agent.decision import (
    LEVEL_CHANGE_ACTIONS,
    PRAYER_FIRST_SAFE_TURN,
    PRAYER_REPEAT_WAIT_TURNS,
    ActionCandidate,
    ActionDecision,
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    CorpseEvidence,
    CorpseOutcomeKind,
    DecisionMetrics,
    DestinationKind,
    DropEvidence,
    HungerPermit,
    IntentDestination,
    MapCell,
    ModelActionDecision,
    ModelSkillDecision,
    PrayerEvidence,
    PrayerOutcome,
    PrayerOutcomeKind,
    PrayerPermit,
    PromptKind,
    PromptPermit,
    RunOutcome,
    RunState,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    StuckReason,
    TraversalPermit,
)
from nethack_agent.environment import LegalAction, NleEnvironment, ScenarioConfig
from nethack_agent.evaluation import load_suite, summarize_run
from nethack_agent.events import EventKind, RunEvent, RunStartedPayload, StepPayload
from nethack_agent.model import (
    DecisionFailure,
    HierarchicalDecisionModel,
    ScriptedDevelopmentModel,
)
from nethack_agent.navigation import GOLD_GLYPH, ActionRecord, LevelMemory, Monster
from nethack_agent.observation import (
    BucStatus,
    InventoryItem,
    ObservationProjector,
    PromptState,
)
from nethack_agent.replay import ExplorationReplay
from nethack_agent.storage import RunRecord
from nethack_agent.tasks import STAIRCASE_TASK, ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    ExploreDungeonLeg,
    ExploreLevelGoal,
    Goal,
    LevelKey,
    Objective,
    ObjectiveLeg,
    ReachLevelLeg,
    StairDirection,
)

_METRICS = DecisionMetrics(1, 1, 1.0, False)


def skill_decision() -> ModelSkillDecision:
    return ModelSkillDecision(
        SkillDecision(
            STAND_ON_DOWNSTAIRS,
            Skill.STAIRCASE_NAVIGATION,
            "Use safe deterministic staircase routing.",
        ),
        _METRICS,
        "{}",
    )


def action_decision(action_index: int) -> ModelActionDecision:
    return ModelActionDecision(
        ActionDecision(
            candidates=(ActionCandidate(action_index, 1.0, "scripted fallback"),),
            action_index=action_index,
            rationale="Use the scripted ambiguous-state fallback.",
        ),
        _METRICS,
        "{}",
    )


class FixedModel:
    def __init__(self, action_index: int) -> None:
        self.action_index = action_index
        self.skill_calls = 0
        self.action_calls = 0

    def select_skill(self, *_: object) -> ModelSkillDecision:
        self.skill_calls += 1
        return skill_decision()

    def select_action(self, *_: object) -> ModelActionDecision:
        self.action_calls += 1
        return action_decision(self.action_index)


class FailingModel(FixedModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        raise DecisionFailure("malformed after repair")


class BlockingModel(FixedModel):
    def __init__(self) -> None:
        super().__init__(2)
        self.entered = threading.Event()
        self.release = threading.Event()

    def select_skill(self, *_: object) -> ModelSkillDecision:
        self.entered.set()
        assert self.release.wait(timeout=2)
        return super().select_skill()


class ExplodingModel(FixedModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        raise RuntimeError("unexpected model failure")


class ConsultingModel:
    """Record skill consultations; pick `stuck_skill` whenever exploration is stuck.

    Fallback actions propose `fallback_index` (any index, even a forbidden one)
    or else the offered wait action.
    """

    def __init__(self, stuck_skill: Skill) -> None:
        self.stuck_skill = stuck_skill
        self.fallback_index: int | None = None
        self.consultations: list[StuckReason | None] = []
        self.fallback_skills: list[Skill] = []
        self.action_calls = 0

    def select_skill(
        self,
        observation: object,
        goals: tuple[Goal, ...],
        skills: tuple[Skill, ...],
        stuck: StuckReason | None,
    ) -> ModelSkillDecision:
        del observation, goals
        assert set(skills) == {
            Skill.STAIRCASE_NAVIGATION,
            Skill.EXPLORE_LEVEL,
        }
        self.consultations.append(stuck)
        skill = Skill.EXPLORE_LEVEL if stuck is None else self.stuck_skill
        return ModelSkillDecision(
            SkillDecision(STAND_ON_DOWNSTAIRS, skill, "Scripted consultation."),
            _METRICS,
            "{}",
        )

    def select_action(
        self,
        observation: object,
        legal_actions: tuple[LegalAction, ...],
        goal: Goal,
        skill: Skill,
    ) -> ModelActionDecision:
        del observation, goal
        self.action_calls += 1
        self.fallback_skills.append(skill)
        if self.fallback_index is not None:
            return action_decision(self.fallback_index)
        wait = next(
            action for action in legal_actions if action.name == "MiscDirection.WAIT"
        )
        return action_decision(wait.index)


def coordinator(
    directory: Path,
    model: HierarchicalDecisionModel,
    *,
    seed: int = 6,
    max_steps: int = 20,
) -> AgentCoordinator:
    return AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=seed,
                artifact_directory=directory,
                max_episode_steps=max_steps,
            )
        ),
        ObservationProjector(),
        model,
    )


def test_hierarchy_consults_model_at_start_then_explores_deterministically(
    tmp_path: Path,
) -> None:
    model = FixedModel(2)
    agent = coordinator(tmp_path, model)
    initial = agent.start()

    first = agent.advance(single_step=True)
    second = agent.advance(single_step=True)

    assert first is not None and second is not None
    assert first.before == initial
    assert first.skill_model_decision is not None
    assert second.skill_model_decision is None
    for record in (first, second):
        assert record.selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
        assert record.selection.skill is Skill.EXPLORE_LEVEL
        assert record.selection.skill_selection is SkillSelectionSource.ARBITER
        assert record.action_model_decision is None
    assert model.skill_calls == 1
    assert model.action_calls == 0
    snapshot = agent.snapshot()
    assert snapshot.current_goal == STAND_ON_DOWNSTAIRS
    assert snapshot.current_skill is Skill.EXPLORE_LEVEL
    assert snapshot.state is RunState.PAUSED
    agent.stop()


def test_model_failure_pauses_with_diagnostic(tmp_path: Path) -> None:
    agent = coordinator(tmp_path, FailingModel(2))
    agent.start()
    agent.resume()

    with pytest.raises(DecisionFailure, match="malformed"):
        agent.advance()

    snapshot = agent.snapshot()
    assert snapshot.state is RunState.PAUSED
    assert snapshot.last_error == "malformed after repair"
    agent.stop()


def test_step_cap_finishes_run_and_finalizes_ttyrec(tmp_path: Path) -> None:
    agent = coordinator(tmp_path, FixedModel(0), max_steps=1)
    agent.start()

    record = agent.advance(single_step=True)

    assert record is not None
    assert record.outcome is RunOutcome.TRUNCATED
    assert agent.snapshot().state is RunState.TERMINAL
    assert len(agent.ttyrec_files) == 1
    agent.stop()
    assert agent.snapshot().state is RunState.TERMINAL


def test_concurrent_advance_is_rejected_while_pause_remains_responsive(
    tmp_path: Path,
) -> None:
    model = BlockingModel()
    agent = coordinator(tmp_path, model)
    agent.start()
    agent.resume()
    results: list[object] = []

    worker = threading.Thread(target=lambda: results.append(agent.advance()))
    worker.start()
    assert model.entered.wait(timeout=2)

    with pytest.raises(CoordinatorBusyError, match="already in progress"):
        agent.advance()
    agent.pause()
    model.release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert results == [None]
    assert agent.snapshot().current_skill is None
    assert agent.snapshot().state is RunState.PAUSED
    agent.stop()


@pytest.mark.parametrize(
    ("name", "direction"),
    [
        ("MiscDirection.DOWN", StairDirection.DOWN),
        ("MiscDirection.UP", StairDirection.UP),
    ],
)
def test_action_gate_passes_level_changes_only_with_a_matching_permit(
    tmp_path: Path, name: str, direction: StairDirection
) -> None:
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    try:
        environment.reset()
        gate = ActionGate(environment.legal_actions)
        level_change = next(
            action for action in environment.legal_actions if action.name == name
        )
        wrong = TraversalPermit(direction.opposite, LevelKey(0, 2), MapCell(3, 4))

        for permit in (None, wrong):
            with pytest.raises(ActionGateError, match=f"{name} is forbidden"):
                gate.resolve(level_change.index, permit)

        permit = TraversalPermit(direction, LevelKey(0, 2), MapCell(3, 4))
        assert gate.resolve(level_change.index, permit) == level_change
        assert gate.level_change_actions[direction] == level_change
        # Resolving never steps NLE, and the model is never offered the action.
        assert environment.step_index == 0
        assert level_change not in gate.allowed_actions
        assert name not in gate.actions_by_name
    finally:
        environment.close()


def test_action_gate_keeps_hunger_commands_out_of_model_fallbacks(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_HUNGER_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    environment = NleEnvironment(
        ScenarioConfig(
            seed=6,
            artifact_directory=tmp_path,
            max_episode_steps=20,
            task=task,
        )
    )
    try:
        environment.reset()
        gate = ActionGate(environment.legal_actions, task.action_profile)
        by_command = {action.command: action for action in environment.legal_actions}
        eat = by_command[ord("e")]
        prompt_d = by_command[ord("d")]
        movement_h = by_command[ord("h")]

        with pytest.raises(ActionGateError, match="hunger permit"):
            gate.resolve(eat.index)
        assert gate.resolve(eat.index, hunger_permit=HungerPermit("d")) == eat

        with pytest.raises(ActionGateError, match="active item-selection"):
            gate.resolve(prompt_d.index)
        with pytest.raises(ActionGateError, match="active item-selection"):
            gate.resolve(prompt_d.index, prompt_permit=PromptPermit(ord("z")))
        assert (
            gate.resolve(prompt_d.index, prompt_permit=PromptPermit(ord("d")))
            == prompt_d
        )

        # The movement collision keeps its ordinary role outside prompts.
        assert gate.resolve(movement_h.index) == movement_h
        assert movement_h in gate.allowed_actions
        assert eat not in gate.allowed_actions
        assert prompt_d not in gate.allowed_actions
    finally:
        environment.close()


def test_survival_gate_requires_prayer_permit_and_exact_yes_prompt(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    environment = NleEnvironment(
        ScenarioConfig(
            seed=6,
            artifact_directory=tmp_path,
            max_episode_steps=20,
            task=task,
        )
    )
    try:
        before = ObservationProjector().project(environment.reset(), step_index=0)
        gate = ActionGate(environment.legal_actions, task.action_profile)
        pray = next(
            action
            for action in environment.legal_actions
            if action.name == "Command.PRAY"
        )
        yes = next(
            action for action in environment.legal_actions if action.command == ord("y")
        )
        assert pray not in gate.allowed_actions
        assert yes not in gate.allowed_actions
        before = replace(
            before,
            player=replace(before.player, hunger=3, turn=PRAYER_FIRST_SAFE_TURN),
            inventory=(),
        )
        evidence = PrayerEvidence(3, PRAYER_FIRST_SAFE_TURN, PRAYER_FIRST_SAFE_TURN)
        prayer = ActionSelection(
            ActionSelectionSource.DETERMINISTIC_SKILL,
            STAND_ON_DOWNSTAIRS,
            Skill.PRAYER,
            SkillSelectionSource.ARBITER,
            None,
            pray.index,
            "Pray only with authorization.",
            ActionIntent(None, None, None, prayer=evidence),
        )
        with pytest.raises(ActionGateError, match="prayer permit"):
            gate.resolve(pray.index, before=before, selection=prayer)
        assert (
            gate.resolve(
                pray.index,
                before=before,
                selection=prayer,
                prayer_permit=PrayerPermit(PRAYER_FIRST_SAFE_TURN),
            )
            == pray
        )
        with pytest.raises(ActionGateError, match="deterministic prayer skill"):
            gate.resolve(
                pray.index,
                before=before,
                selection=replace(
                    prayer,
                    source=ActionSelectionSource.MODEL_FALLBACK,
                    skill=Skill.STAIRCASE_NAVIGATION,
                    intent=None,
                ),
            )
        with pytest.raises(ActionGateError, match="deterministic prayer skill"):
            gate.resolve(
                pray.index,
                before=before,
                selection=replace(prayer, skill=Skill.HUNGER),
            )
        for kwargs in (
            {"prior_prayers": 1},
            {"on_altar": True},
            {"before": replace(before, prompt=PromptState(True, False, False))},
            {"before": replace(before, player=replace(before.player, hunger=2))},
            {
                "before": replace(
                    before,
                    player=replace(before.player, turn=PRAYER_FIRST_SAFE_TURN - 1),
                )
            },
        ):
            with pytest.raises(ActionGateError):
                gate.resolve(
                    pray.index,
                    selection=prayer,
                    prayer_permit=PrayerPermit(PRAYER_FIRST_SAFE_TURN),
                    **({"before": before} | kwargs),
                )

        choice = PromptState(True, False, False)
        prayer_prompt = replace(
            before,
            prompt=choice,
            message="Are you sure you want to pray? [yn] (n) ",
        )
        corpse_prompt = replace(
            before,
            prompt=choice,
            message="There is a lichen corpse here; eat it? [ynq] (n) ",
        )
        for prompted, kind, skill in (
            (prayer_prompt, PromptKind.PRAYER_CONFIRMATION, Skill.PRAYER),
        ):
            answer = replace(
                prayer,
                source=ActionSelectionSource.DETERMINISTIC_PROMPT,
                skill=skill,
                action_index=yes.index,
                intent=prayer.intent if skill is Skill.PRAYER else None,
            )
            with pytest.raises(ActionGateError, match="confirmation prompt permit"):
                gate.resolve(yes.index, before=prompted, selection=answer)
            with pytest.raises(ActionGateError, match="confirmation prompt permit"):
                gate.resolve(
                    yes.index,
                    before=prompted,
                    selection=answer,
                    prompt_permit=PromptPermit(ord("y")),
                )
            assert (
                gate.resolve(
                    yes.index,
                    before=prompted,
                    selection=answer,
                    prompt_permit=PromptPermit(ord("y"), kind),
                )
                == yes
            )
            with pytest.raises(ActionGateError, match="exact recognized"):
                gate.resolve(
                    yes.index,
                    before=replace(prompted, message=prompted.message + "unexpected"),
                    selection=answer,
                    prompt_permit=PromptPermit(ord("y"), kind),
                )
        forged_corpse_answer = replace(
            prayer,
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            skill=Skill.HUNGER,
            action_index=yes.index,
            intent=None,
        )
        with pytest.raises(ActionGateError, match="matching deterministic prompt"):
            gate.resolve(
                yes.index,
                before=corpse_prompt,
                selection=forged_corpse_answer,
                prompt_permit=PromptPermit(ord("y"), PromptKind.CORPSE_CONFIRMATION),
            )

        item_prompt = replace(
            before,
            prompt=choice,
            message="What do you want to eat? [y or ?*]",
        )
        item_answer = replace(
            prayer,
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            skill=Skill.HUNGER,
            action_index=yes.index,
            intent=None,
        )
        assert (
            gate.resolve(
                yes.index,
                before=item_prompt,
                selection=item_answer,
                prompt_permit=PromptPermit(ord("y")),
            )
            == yes
        )
        with pytest.raises(ActionGateError, match="confirmation prompt permit"):
            gate.resolve(
                yes.index,
                before=item_prompt,
                selection=item_answer,
                prompt_permit=PromptPermit(ord("y"), PromptKind.CORPSE_CONFIRMATION),
            )

        northwest = replace(
            prayer, skill=Skill.EXPLORE_LEVEL, action_index=yes.index, intent=None
        )
        assert gate.resolve(yes.index, before=before, selection=northwest) == yes
        with pytest.raises(ActionGateError, match="ambiguous yes"):
            gate.resolve(
                yes.index,
                before=before,
                selection=replace(
                    northwest,
                    source=ActionSelectionSource.MODEL_FALLBACK,
                ),
            )
    finally:
        environment.close()


def test_real_nle_pray_confirmation_y_exposes_outcome_on_y_step(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    environment = NleEnvironment(
        ScenarioConfig(
            seed=6, artifact_directory=tmp_path, max_episode_steps=20, task=task
        )
    )
    projector = ObservationProjector()
    try:
        initial = projector.project(environment.reset(), step_index=0)
        pray = next(
            action
            for action in environment.legal_actions
            if action.name == "Command.PRAY"
        )
        yes = next(
            action for action in environment.legal_actions if action.command == ord("y")
        )
        first = environment.step(pray.index)
        prompt = projector.project(first.observation, step_index=first.step_index)
        assert prompt.message == "Are you sure you want to pray? [yn] (n) "
        assert prompt.prompt.single_character_choice
        assert prompt.player.turn == initial.player.turn
        second = environment.step(yes.index)
        after = projector.project(second.observation, step_index=second.step_index)
        assert not second.is_terminal
        assert after.player.turn > prompt.player.turn
        assert after.message == '"Thou must relearn thy lessons!"  You feel foolish!'
    finally:
        environment.close()


def test_prayer_prompt_permit_requires_exact_pending_previous_step(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    environment = NleEnvironment(
        ScenarioConfig(
            seed=6, artifact_directory=tmp_path, max_episode_steps=20, task=task
        )
    )
    agent = AgentCoordinator(environment, ObservationProjector(), FixedModel(2))
    try:
        before = agent.start()
        prompt = replace(
            before,
            step_index=1,
            prompt=PromptState(True, False, False),
            message="Are you sure you want to pray? [yn] (n) ",
        )
        yes = next(
            action for action in agent.legal_actions if action.command == ord("y")
        )
        evidence = PrayerEvidence(3, 101, PRAYER_FIRST_SAFE_TURN)
        answer = ActionSelection(
            ActionSelectionSource.DETERMINISTIC_PROMPT,
            STAND_ON_DOWNSTAIRS,
            Skill.PRAYER,
            SkillSelectionSource.ARBITER,
            None,
            yes.index,
            "Confirm pending prayer.",
            ActionIntent(None, None, None, prayer=evidence),
        )
        with pytest.raises(ActionGateError, match="preceding prayer evidence"):
            agent._prompt_permit(answer, prompt)
        agent._pending_prayer = evidence
        agent._pending_prayer_step = 0
        agent._prayer_count = 1
        permit = agent._prompt_permit(answer, prompt)
        assert permit == PromptPermit(ord("y"), PromptKind.PRAYER_CONFIRMATION)
        with pytest.raises(ActionGateError, match="preceding prayer evidence"):
            agent._prompt_permit(
                replace(
                    answer,
                    intent=ActionIntent(
                        None, None, None, prayer=replace(evidence, prayer_turn=102)
                    ),
                ),
                prompt,
            )
        with pytest.raises(ActionGateError, match="exact recognized"):
            agent._prompt_permit(answer, replace(prompt, message=prompt.message + " "))
        with pytest.raises(ActionGateError, match="preceding prayer evidence"):
            agent._prompt_permit(answer, replace(prompt, step_index=3))
    finally:
        agent.stop()


def test_coordinator_prayer_records_outcome_and_enforces_repeat_wait(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=6, artifact_directory=tmp_path, max_episode_steps=20, task=task
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    try:
        initial = agent.start()
        # Isolate the coordinator's observed threshold and ration guards while
        # still exercising actual NLE PRAY and confirmation transitions.
        agent._observation = replace(
            initial,
            player=replace(initial.player, hunger=3, turn=PRAYER_FIRST_SAFE_TURN),
            inventory=(),
        )
        first = agent.advance(single_step=True)
        assert first is not None and first.action.name == "Command.PRAY"
        assert first.selection.intent is not None
        evidence = first.selection.intent.prayer
        assert evidence == PrayerEvidence(
            3, PRAYER_FIRST_SAFE_TURN, PRAYER_FIRST_SAFE_TURN
        )
        assert first.after.message == "Are you sure you want to pray? [yn] (n) "
        assert agent._prayer_count == 1
        assert agent._last_prayer_turn == PRAYER_FIRST_SAFE_TURN

        confirmed = agent.advance(single_step=True)
        assert confirmed is not None and confirmed.action.command == ord("y")
        assert confirmed.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        assert confirmed.selection.intent is not None
        assert confirmed.selection.intent.prayer == replace(
            evidence,
            outcome=PrayerOutcome(
                confirmed.after.player.turn,
                confirmed.after.player.hunger,
                confirmed.after.message,
                PrayerOutcomeKind.DISPLEASED_OR_PUNISHED,
            ),
        )
        assert agent._pending_prayer is None
        assert agent._prayer_count == 1
        safe_turn = PRAYER_FIRST_SAFE_TURN + PRAYER_REPEAT_WAIT_TURNS
        too_early = replace(
            confirmed.after,
            player=replace(confirmed.after.player, hunger=3, turn=safe_turn - 1),
            inventory=(),
        )
        early_selection = replace(
            first.selection,
            intent=ActionIntent(
                None, None, None, prayer=PrayerEvidence(3, safe_turn - 1, safe_turn)
            ),
        )
        with pytest.raises(ActionGateError, match="safe turn"):
            agent._prayer_permit(early_selection, too_early)
        ready = replace(too_early, player=replace(too_early.player, turn=safe_turn))
        selection = replace(
            early_selection,
            intent=ActionIntent(
                None, None, None, prayer=PrayerEvidence(3, safe_turn, safe_turn)
            ),
        )
        assert agent._prayer_permit(selection, ready) == PrayerPermit(safe_turn)
        assert (
            agent._gate.resolve(
                selection.action_index,
                before=ready,
                selection=selection,
                prayer_permit=PrayerPermit(safe_turn),
                prior_prayers=1,
                last_prayer_turn=PRAYER_FIRST_SAFE_TURN,
            ).name
            == "Command.PRAY"
        )
    finally:
        agent.stop()


def test_stale_prayer_prompt_is_declined_not_confirmed(tmp_path: Path) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 2)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=6, artifact_directory=tmp_path, max_episode_steps=20, task=task
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    try:
        initial = agent.start()
        agent._observation = replace(
            initial,
            player=replace(initial.player, turn=PRAYER_FIRST_SAFE_TURN, hunger=3),
            inventory=(),
        )
        prayer = agent.advance(single_step=True)
        assert prayer is not None and prayer.action.name == "Command.PRAY"
        agent._observation = replace(
            prayer.after, message=prayer.after.message + "unexpected"
        )
        declined = agent.advance(single_step=True)
        assert declined is not None and declined.action.command == ord("n")
        assert declined.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        assert declined.selection.skill is not Skill.PRAYER
        assert agent._pending_prayer is None
        assert agent._prayer_count == 1
    finally:
        agent.stop()


def advance_until_stuck(agent: AgentCoordinator, limit: int) -> StepRecord:
    for _ in range(limit):
        record = agent.advance()
        assert record is not None and record.outcome is None
        if record.selection.stuck_reason is not None:
            return record
    raise AssertionError(f"exploration never reported stuck within {limit} steps")


def test_stuck_exploration_consults_model_and_rearms_search(tmp_path: Path) -> None:
    # Seed 16 walls the hero into two rooms whose exits are hidden, so
    # exploration exhausts its first search round after a few hundred steps.
    model = ConsultingModel(Skill.EXPLORE_LEVEL)
    agent = coordinator(tmp_path, model, seed=16, max_steps=600)
    agent.start()
    agent.resume()

    stuck = advance_until_stuck(agent, 590)
    following = agent.advance()

    assert model.consultations == [None, StuckReason.SEARCH_EXHAUSTED]
    assert model.action_calls == 0
    assert stuck.skill_model_decision is not None
    assert stuck.skill_model_decision.decision.skill is Skill.EXPLORE_LEVEL
    assert stuck.selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
    assert stuck.selection.skill is Skill.EXPLORE_LEVEL
    assert stuck.selection.skill_selection is SkillSelectionSource.MODEL
    assert stuck.selection.stuck_reason is StuckReason.SEARCH_EXHAUSTED
    # The step whose decision found the level exhausted records the marker.
    assert stuck.selection.exhausted_level == LevelKey(0, 1)
    assert following is not None
    assert following.selection.exhausted_level is None
    assert following.selection.skill_selection is SkillSelectionSource.ARBITER
    assert following.selection.stuck_reason is None
    agent.stop()


def test_model_fallback_after_stuck_cannot_leave_the_level(tmp_path: Path) -> None:
    model = ConsultingModel(Skill.STAIRCASE_NAVIGATION)
    agent = coordinator(tmp_path, model, seed=16, max_steps=600)
    model.fallback_index = next(
        action.index
        for action in agent.legal_actions
        if action.name == "MiscDirection.UP"
    )
    agent.start()
    agent.resume()

    with pytest.raises(ActionGateError, match="MiscDirection.UP is forbidden"):
        for _ in range(590):
            agent.advance()

    snapshot = agent.snapshot()
    assert model.consultations == [None, StuckReason.SEARCH_EXHAUSTED]
    assert model.fallback_skills == [Skill.STAIRCASE_NAVIGATION]
    assert snapshot.state is RunState.PAUSED
    assert snapshot.outcome is None
    assert snapshot.last_error is not None and "forbidden" in snapshot.last_error
    assert snapshot.observation is not None
    assert snapshot.observation.player.dungeon_level == 1
    agent.stop()


def test_unexpected_model_exception_closes_environment_and_enters_error(
    tmp_path: Path,
) -> None:
    agent = coordinator(tmp_path, ExplodingModel(2))
    agent.start()
    agent.resume()

    with pytest.raises(RuntimeError, match="unexpected model failure"):
        agent.advance()

    snapshot = agent.snapshot()
    assert snapshot.state is RunState.ERROR
    assert snapshot.outcome is RunOutcome.ERROR
    assert snapshot.last_error == "unexpected model failure"
    assert len(agent.ttyrec_files) == 1


def score_task(*legs: ObjectiveLeg) -> TaskSpec:
    return TaskSpec(NleTask.SCORE, ActionProfile.NLE_TASK_ACTIONS, Objective(legs))


def run_to_end(
    directory: Path, seed: int, task: TaskSpec, max_steps: int
) -> tuple[AgentCoordinator, list[StepRecord]]:
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=seed,
                artifact_directory=directory,
                max_episode_steps=max_steps,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    agent.start()
    agent.resume()
    records: list[StepRecord] = []
    while not records or records[-1].outcome is None:
        record = agent.advance()
        assert record is not None
        records.append(record)
    return agent, records


def traversals(records: list[StepRecord]) -> list[tuple[object, ...]]:
    """Each level change: action, goal token, levels, and the stair belief."""
    used = []
    for record in records:
        if record.action.name not in LEVEL_CHANGE_ACTIONS:
            continue
        intent = record.selection.intent
        assert intent is not None and intent.destination is not None
        stair = intent.destination.stair
        assert stair is not None
        before, after = record.before.player, record.after.player
        used.append(
            (
                record.action.name,
                record.selection.goal.token,
                (before.dungeon_number, before.dungeon_level),
                (after.dungeon_number, after.dungeon_level),
                stair.kind.value,
                stair.evidence.value if stair.evidence else None,
            )
        )
    return used


DOWN_ACTION = "MiscDirection.DOWN"
UP_ACTION = "MiscDirection.UP"


def test_round_trip_descends_by_probes_and_climbs_by_arrival_stairs(
    tmp_path: Path,
) -> None:
    agent, records = run_to_end(
        tmp_path,
        6,
        score_task(ReachLevelLeg(LevelKey(0, 3)), ReachLevelLeg(LevelKey(0, 1))),
        max_steps=600,
    )

    assert traversals(records) == [
        (DOWN_ACTION, "traverse_stairs:down:main", (0, 1), (0, 2), "unknown", None),
        (DOWN_ACTION, "traverse_stairs:down:main", (0, 2), (0, 3), "unknown", None),
        (UP_ACTION, "traverse_stairs:up:main", (0, 3), (0, 2), "main", "arrival"),
        (UP_ACTION, "traverse_stairs:up:main", (0, 2), (0, 1), "main", "arrival"),
    ]
    last = records[-1]
    # NetHack continues; the coordinator ends the run once every leg is met.
    assert last.outcome is RunOutcome.OBJECTIVE_COMPLETE
    assert not last.transition.terminated and not last.transition.truncated
    snapshot = agent.snapshot()
    assert snapshot.state is RunState.TERMINAL
    assert snapshot.objective_leg == 2
    assert snapshot.level == LevelKey(0, 1)
    assert len(agent.ttyrec_files) == 1
    # Level changes happen only through deterministic staircase navigation.
    assert {
        record.selection.skill
        for record in records
        if record.action.name in LEVEL_CHANGE_ACTIONS
    } == {Skill.STAIRCASE_NAVIGATION}


def test_a_mines_probe_is_retraced_and_the_main_stair_found_by_elimination(
    tmp_path: Path,
) -> None:
    _, records = run_to_end(
        tmp_path, 4, score_task(ReachLevelLeg(LevelKey(0, 3))), max_steps=600
    )

    assert traversals(records) == [
        (DOWN_ACTION, "traverse_stairs:down:main", (0, 1), (0, 2), "unknown", None),
        # The nearer unknown `>` on DL2 is the Gnomish Mines branch.
        (DOWN_ACTION, "traverse_stairs:down:main", (0, 2), (2, 1), "unknown", None),
        (UP_ACTION, "traverse_stairs:up:branch:0", (2, 1), (0, 2), "branch", "arrival"),
        (
            DOWN_ACTION,
            "traverse_stairs:down:main",
            (0, 2),
            (0, 3),
            "main",
            "elimination",
        ),
    ]
    assert records[-1].outcome is RunOutcome.OBJECTIVE_COMPLETE


def test_terminal_steps_keep_the_last_live_level(tmp_path: Path) -> None:
    # NLE zeroes the bottom-line statistics of a terminal observation.
    staircase, success = run_to_end(tmp_path / "staircase", 2, STAIRCASE_TASK, 100)
    assert success[-1].outcome is RunOutcome.TASK_SUCCESS
    assert success[-1].after.player.dungeon_level == 0
    assert staircase.snapshot().level == LevelKey(
        success[-1].before.player.dungeon_number,
        success[-1].before.player.dungeon_level,
    )
    assert staircase.snapshot().objective_leg == 0

    score, death = run_to_end(
        tmp_path / "score", 9, score_task(ReachLevelLeg(LevelKey(0, 12))), 600
    )
    assert death[-1].outcome is RunOutcome.DEATH
    assert death[-1].after.player.dungeon_level == 0
    assert score.snapshot().level == LevelKey(
        death[-1].before.player.dungeon_number,
        death[-1].before.player.dungeon_level,
    )
    assert score.snapshot().state is RunState.TERMINAL


class FailOnceWhenStuckModel(ConsultingModel):
    """Fail the first stuck consultation, as a malformed model reply would."""

    def __init__(self) -> None:
        super().__init__(Skill.EXPLORE_LEVEL)
        self.failed = False

    def select_skill(
        self,
        observation: object,
        goals: tuple[Goal, ...],
        skills: tuple[Skill, ...],
        stuck: StuckReason | None,
    ) -> ModelSkillDecision:
        if stuck is not None and not self.failed:
            self.failed = True
            raise DecisionFailure("malformed after repair")
        return super().select_skill(observation, goals, skills, stuck)


def test_a_discarded_decision_does_not_keep_its_exhaustion_mark(
    tmp_path: Path,
) -> None:
    # Seed 16 exhausts its first search round; the stuck consultation that
    # follows the new exhaustion mark fails and pauses the run unrecorded.
    model = FailOnceWhenStuckModel()
    agent = coordinator(tmp_path, model, seed=16, max_steps=600)
    agent.start()
    agent.resume()
    with pytest.raises(DecisionFailure):
        for _ in range(590):
            record = agent.advance()
            assert record is not None and record.selection.exhausted_level is None

    assert agent.snapshot().state is RunState.PAUSED
    agent.resume()
    retried = agent.advance()

    # The retried decision marks the level again, so the recorded step carries
    # the marker that memory now reflects.
    assert retried is not None
    assert retried.selection.exhausted_level == LevelKey(0, 1)
    assert retried.selection.stuck_reason is StuckReason.SEARCH_EXHAUSTED
    assert model.consultations == [None, StuckReason.SEARCH_EXHAUSTED]
    agent.stop()


def step_payload(record: StepRecord) -> StepPayload:
    skill = record.skill_model_decision
    action = record.action_model_decision
    return StepPayload(
        selection=record.selection,
        skill_decision=skill.decision if skill else None,
        skill_metrics=skill.metrics if skill else None,
        action_decision=action.decision if action else None,
        action_metrics=action.metrics if action else None,
        action=record.action,
        reward=record.transition.reward,
        terminated=record.transition.terminated,
        truncated=record.transition.truncated,
        end_status=record.transition.end_status,
        is_ascended=record.transition.is_ascended,
        outcome=record.outcome,
        observation=record.after,
    )


def test_exploring_the_last_required_level_ends_without_a_model_consultation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed: list[ActionRecord] = []
    record_action = LevelMemory.record

    def capture(memory: LevelMemory, action: ActionRecord) -> None:
        committed.append(action)
        record_action(memory, action)

    monkeypatch.setattr(LevelMemory, "record", capture)
    task = TaskSpec(
        NleTask.SCOUT,
        ActionProfile.NLE_TASK_ACTIONS,
        Objective((ExploreDungeonLeg(1),)),
    )
    # Seed 53 exhausts its first level quickly enough for the starving Scout.
    agent, records = run_to_end(tmp_path, 53, task, 400)

    final = records[-1]
    assert final.outcome is RunOutcome.OBJECTIVE_COMPLETE
    assert final.action.name == "MiscDirection.WAIT"
    assert final.selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
    assert final.selection.skill is Skill.EXPLORE_LEVEL
    assert final.selection.stuck_reason is None
    assert [
        (index, record.selection.exhausted_level)
        for index, record in enumerate(records)
        if record.selection.exhausted_level is not None
    ] == [(len(records) - 1, LevelKey(0, 1))]
    assert {record.goal for record in records} == {ExploreLevelGoal(LevelKey(0, 1))}
    # Only the start of the episode consulted the model.
    assert [
        index for index, record in enumerate(records) if record.skill_model_decision
    ] == [0]
    assert not any(record.action_model_decision for record in records)
    assert agent.snapshot().objective_leg == 1

    # Replaying the persisted steps re-derives every memory record the
    # coordinator committed and confirms the marker.
    replay_committed = len(committed)
    replay = ExplorationReplay(task, agent.legal_actions, records[0].before)
    assert [replay.step(step_payload(record)) for record in records] == [None] * len(
        records
    )
    assert committed[replay_committed:] == committed[:replay_committed]
    assert replay.explored == {LevelKey(0, 1)}


def test_gold_task_routes_onto_visible_gold_and_other_tasks_never_do(
    tmp_path: Path,
) -> None:
    explore = Objective((ExploreDungeonLeg(3),))
    gold_task = TaskSpec(NleTask.GOLD, ActionProfile.NLE_TASK_ACTIONS, explore)
    # Seed 4 shows gold at the start: gold navigation acts on step 1 and NLE's
    # pickup_types:$ picks the gold up on step 3.
    _, records = run_to_end(tmp_path / "gold", 4, gold_task, max_steps=40)

    first = next(
        index
        for index, record in enumerate(records)
        if record.selection.skill is Skill.GOLD_NAVIGATION
    )
    assert first == 0
    start_gold = records[first].before.player.gold
    assert any(
        record.after.player.gold > start_gold for record in records[first : first + 10]
    )
    for record in records:
        if record.selection.skill is not Skill.GOLD_NAVIGATION:
            continue
        assert record.selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
        intent = record.selection.intent
        assert intent is not None and intent.destination is not None
        glyphs = record.before.map.glyph_rows
        assert glyphs[intent.destination.y][intent.destination.x] == GOLD_GLYPH

    scout_task = TaskSpec(NleTask.SCOUT, ActionProfile.NLE_TASK_ACTIONS, explore)
    _, scout = run_to_end(tmp_path / "scout", 4, scout_task, max_steps=40)
    assert all(record.selection.skill is not Skill.GOLD_NAVIGATION for record in scout)


def test_survival_arbitration_defense_then_prayer_ration_corpse(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 12)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=1131,
                artifact_directory=tmp_path,
                max_episode_steps=20,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        hero = MapCell(initial.player.x, initial.player.y)
        level = LevelKey(initial.player.dungeon_number, initial.player.dungeon_level)
        kill = CorpseKill("lichen", 90, level, hero)
        agent._corpse_kills[(level, hero)] = kill
        observation = replace(
            initial,
            message="You see here a lichen corpse.",
            inventory=(),
            player=replace(initial.player, hunger=3, turn=100),
        )
        memory = agent._dungeon.current
        memory.monsters.clear()
        neighbor = next(
            point
            for point in memory.neighbors((hero.x, hero.y))
            if point[0] == hero.x + 1
        )
        memory.monsters[neighbor] = Monster(nethack.GLYPH_MON_OFF, "jackal", False)
        defense = agent._decide(observation, None, lambda: False, 0)
        assert defense is not None
        assert defense.selection.intent is not None
        assert defense.selection.intent.attack_target == MapCell(*neighbor)
        hurt = replace(
            observation,
            inventory=initial.inventory,
            player=replace(observation.player, hit_points=5, hunger=0),
        )
        rescue = agent._decide(hurt, None, lambda: False, 0)
        assert rescue is not None
        assert agent.legal_actions[rescue.selection.action_index].name == "Command.PRAY"
        assert agent._prayer_permit(rescue.selection, hurt) == PrayerPermit(100)
        unsafe = replace(hurt, player=replace(hurt.player, turn=99))
        still_defend = agent._decide(unsafe, None, lambda: False, 0)
        assert still_defend is not None
        assert still_defend.selection.intent.attack_target == MapCell(*neighbor)
        memory.monsters.clear()
        prayer = agent._decide(observation, None, lambda: False, 0)
        assert prayer is not None
        assert prayer.selection.skill is Skill.PRAYER
        hungry = replace(observation, player=replace(observation.player, hunger=2))
        hungry_corpse = agent._decide(hungry, None, lambda: False, 0)
        assert hungry_corpse is not None
        assert hungry_corpse.selection.skill is Skill.CORPSE
        assert (
            agent.legal_actions[hungry_corpse.selection.action_index].name
            == "Command.EAT"
        )
        food = next(
            index
            for index in range(nethack.NUM_OBJECTS)
            if nethack.OBJ_NAME(nethack.objclass(index)) == "food ration"
        )
        ration = InventoryItem(
            "a",
            "a food ration",
            nethack.GLYPH_OBJ_OFF + food,
            int(nethack.FOOD_CLASS),
            BucStatus.UNKNOWN,
        )
        hungry_ration = agent._decide(
            replace(hungry, inventory=(ration,)), None, lambda: False, 0
        )
        assert hungry_ration is not None
        assert hungry_ration.selection.skill is Skill.HUNGER
        assert (
            agent.legal_actions[hungry_ration.selection.action_index].name
            == "Command.EAT"
        )
    finally:
        agent.stop()


def test_survival_declines_jackal_floor_and_cancels_inventory_prompt_after_corpse_eat(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 12)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=1131,
                artifact_directory=tmp_path,
                max_episode_steps=20,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        choice = PromptState(True, False, False)
        jackal = replace(
            initial,
            prompt=choice,
            message="There is a jackal corpse here; eat it? [ynq] (n) ",
        )
        plan = agent._decide(jackal, None, lambda: False, 0)
        assert plan is not None
        assert agent.legal_actions[plan.selection.action_index].command == ord("n")
        assert plan.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        corpse = CorpseEvidence(
            "lichen",
            initial.player.turn,
            0,
            MapCell(initial.player.x, initial.player.y),
        )
        agent._pending_corpse = corpse
        agent._pending_corpse_step = initial.step_index
        plan = agent._decide(replace(jackal, step_index=1), None, lambda: False, 0)
        assert plan is not None
        assert agent.legal_actions[plan.selection.action_index].command == ord("n")
        assert plan.selection.skill is Skill.CORPSE
        assert plan.selection.intent is not None
        assert plan.selection.intent.corpse == corpse
        declined_action = agent.legal_actions[plan.selection.action_index]
        declined = agent._commit_corpse_locked(
            plan.selection,
            declined_action,
            replace(jackal, step_index=1),
            replace(jackal, step_index=2, prompt=PromptState(False, False, False)),
            Mock(terminated=False, truncated=False),
        )
        assert declined.intent is not None
        assert declined.intent.corpse is not None
        assert declined.intent.corpse.outcome is not None
        assert declined.intent.corpse.outcome.kind is CorpseOutcomeKind.DECLINED
        agent._pending_corpse = corpse
        agent._pending_corpse_step = initial.step_index
        inventory_prompt = replace(
            initial,
            step_index=1,
            prompt=choice,
            message="What do you want to eat? [ab or ?*]",
        )
        plan = agent._decide(inventory_prompt, None, lambda: False, 0)
        assert plan is not None
        assert plan.selection.skill is Skill.CORPSE
        action = agent.legal_actions[plan.selection.action_index]
        assert action.name == "Command.ESC"
        permit = agent._prompt_permit(plan.selection, inventory_prompt)
        assert (
            agent._gate.resolve(
                action.index,
                prompt_permit=permit,
                before=inventory_prompt,
                selection=plan.selection,
            )
            == action
        )
        declined = agent._commit_corpse_locked(
            plan.selection,
            action,
            inventory_prompt,
            replace(
                inventory_prompt,
                step_index=2,
                prompt=PromptState(False, False, False),
                message="Never mind.",
            ),
            Mock(terminated=False, truncated=False),
        )
        assert declined.intent is not None
        assert declined.intent.corpse is not None
        assert declined.intent.corpse.outcome is not None
        assert declined.intent.corpse.outcome.kind is CorpseOutcomeKind.DECLINED
    finally:
        agent.stop()


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("Blecch!  Rotten food!", CorpseOutcomeKind.ENDED_UNRECOGNIZED),
        ("You feel a mild buzz.", CorpseOutcomeKind.ENDED_UNRECOGNIZED),
        ("You stop eating the lichen corpse.", CorpseOutcomeKind.INTERRUPTED),
    ],
)
@pytest.mark.parametrize("ration_available", [False, True])
def test_corpse_meal_end_never_preempts_prayer_or_ration(
    tmp_path: Path,
    message: str,
    kind: CorpseOutcomeKind,
    ration_available: bool,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 12)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=1131,
                artifact_directory=tmp_path,
                max_episode_steps=20,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        evidence = CorpseEvidence(
            "lichen", 100, 0, MapCell(initial.player.x, initial.player.y)
        )
        kill = CorpseKill("lichen", 100, LevelKey(0, 1), evidence.cell)
        agent._corpse_kills[(kill.level, kill.cell)] = kill
        agent._pending_corpse = evidence
        agent._pending_corpse_step = 0
        floor = replace(
            initial,
            step_index=1,
            message="There is a lichen corpse here; eat it? [ynq] (n) ",
            prompt=PromptState(True, False, False),
            player=replace(initial.player, turn=100, hunger=1),
        )
        plan = agent._decide(floor, None, lambda: False, 0)
        assert plan is not None
        yes = agent.legal_actions[plan.selection.action_index]
        assert yes.command == ord("y")
        ended = replace(
            floor,
            step_index=2,
            message=message,
            prompt=PromptState(False, False, False),
            player=replace(floor.player, turn=104, hunger=3),
            inventory=initial.inventory if ration_available else (),
        )
        confirmed = agent._commit_corpse_locked(
            plan.selection, yes, floor, ended, Mock(terminated=False, truncated=False)
        )
        assert confirmed.intent is not None
        assert confirmed.intent.corpse is not None
        assert confirmed.intent.corpse.outcome is not None
        assert confirmed.intent.corpse.outcome.kind is kind
        assert (kill in agent._consumed_corpses) is (
            kind is not CorpseOutcomeKind.INTERRUPTED
        )
        agent._dungeon.observe(ended)
        agent._dungeon.current.monsters.clear()
        # The next eligible decision recovers nutrition immediately, a zero-
        # decision preemption bound rather than even one continuation WAIT.
        next_plan = agent._decide(ended, None, lambda: False, 0)
        assert next_plan is not None
        assert next_plan.selection.skill is (
            Skill.HUNGER if ration_available else Skill.PRAYER
        )
        assert agent.legal_actions[next_plan.selection.action_index].name == (
            "Command.EAT" if ration_available else "Command.PRAY"
        )
    finally:
        agent.stop()


@pytest.mark.parametrize(
    ("seed", "end_message", "recovery_skill"),
    [
        (1194, "Blecch!  Rotten food!", Skill.HUNGER),
        (1204, "You feel a mild buzz.", Skill.PRAYER),
    ],
)
def test_real_corpse_end_allows_nutrition_recovery(
    tmp_path: Path, seed: int, end_message: str, recovery_skill: Skill
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    environment = NleEnvironment(ScenarioConfig(seed, tmp_path, 3000, task))
    projector = ObservationProjector()
    agent = AgentCoordinator(environment, projector, ScriptedDevelopmentModel())
    observation = agent.start()
    replay = next(
        case
        for case in json.loads(
            (
                Path(__file__).parent / "fixtures" / "corpse-meal-replays.json"
            ).read_text()
        )
        if case["seed"] == seed
    )
    observed_end = False
    try:
        for step, index in enumerate(replay["actions"], start=1):
            before = observation
            agent._dungeon.observe(before)
            if step == replay["confirmation_step"]:
                cell = MapCell(before.player.x, before.player.y)
                level = LevelKey(
                    before.player.dungeon_number, before.player.dungeon_level
                )
                kill = agent._corpse_kills[(level, cell)]
                evidence = CorpseEvidence(
                    kill.name, kill.turn, before.player.turn - kill.turn, cell
                )
                agent._pending_corpse = evidence
                agent._pending_corpse_step = before.step_index - 1
                plan = agent._decide(before, None, lambda: False, 0)
                assert plan is not None and plan.selection.action_index == index
            action = environment.legal_actions[index]
            transition = environment.step(index)
            observation = projector.project(transition.observation, step_index=step)
            kill = observed_corpse_kill(before, action, observation)
            if kill is not None:
                agent._corpse_kills[(kill.level, kill.cell)] = kill
            if step == replay["confirmation_step"]:
                committed = agent._commit_corpse_locked(
                    plan.selection, action, before, observation, transition
                )
                assert observation.message == end_message
                assert (
                    committed.intent.corpse.outcome.kind
                    is CorpseOutcomeKind.ENDED_UNRECOGNIZED
                )
                observed_end = True
        assert observed_end
        agent._observation = observation
        agent._dungeon.observe(observation)
        agent.resume()
        recovery = agent.advance()
        assert recovery is not None and recovery.selection.skill is recovery_skill
        completed = agent.advance()
        assert completed is not None
        assert completed.before.player.hunger >= 2
        assert completed.after.player.hunger == 1
    finally:
        agent.stop()


def test_real_seed_1131_eats_observed_lichen_and_evaluator_audits_cleanly(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 12)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=1131,
                artifact_directory=tmp_path,
                max_episode_steps=50,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    initial_goal = agent.snapshot().current_goal
    agent.resume()
    records: list[StepRecord] = []
    try:
        for _ in range(25):
            step = agent.advance()
            assert step is not None
            records.append(step)
            if step.selection.skill is Skill.CORPSE and step.action.command == ord("y"):
                break
            assert step.outcome is None
        else:
            raise AssertionError("seed 1131 never confirmed a lichen corpse")
        kill = next(
            step for step in records if step.after.message == "You kill the lichen!"
        )
        assert kill.before.player.hunger == 1  # Not Hungry, not Satiated.
        assert kill.after.player.turn == 3
        eat = next(step for step in records if step.action.name == "Command.EAT")
        assert eat.selection.skill is Skill.CORPSE
        assert eat.before.player.turn == 10
        assert eat.before.message == "You see here a lichen corpse."
        assert kill.selection.intent is not None
        assert kill.selection.intent.attack_target is not None
        assert eat.selection.intent is not None
        assert eat.selection.intent.corpse is not None
        # A pet dragged this lichen corpse off its kill cell before the hero
        # reached it; lichen alone is exempt from kill-cell/freshness
        # provenance, so the untracked-arrival path identifies it by the
        # exact look-here text at its new cell instead.
        assert eat.selection.intent.corpse.cell != kill.selection.intent.attack_target
        assert eat.selection.intent.corpse.kill_turn is None
        assert eat.after.message == "There is a lichen corpse here; eat it? [ynq] (n) "
        finished = records[-1]
        assert finished.after.player.turn == 14
        assert finished.after.player.hunger == 0
        assert "You finish eating the lichen corpse." in finished.after.message
        assert finished.selection.intent is not None
        assert finished.selection.intent.corpse is not None
        assert finished.selection.intent.corpse.outcome is not None
        assert finished.selection.intent.corpse.outcome.kind.value == "finished"
        with pytest.raises(
            ActionGateError, match="matching observed fresh floor corpse"
        ):
            agent._gate.resolve(
                finished.action.index,
                prompt_permit=PromptPermit(ord("y"), PromptKind.CORPSE_CONFIRMATION),
                before=replace(
                    finished.before,
                    message="There is a jackal corpse here; eat it? [ynq] (n) ",
                ),
                selection=replace(
                    finished.selection,
                    intent=replace(
                        finished.selection.intent,
                        corpse=replace(finished.selection.intent.corpse, outcome=None),
                    ),
                ),
            )
        # The eaten corpse was the pet-moved, kill-untracked lichen, so the
        # original observed kill at its own cell is never marked consumed.
        assert not any(kill.name == "lichen" for kill in agent._consumed_corpses)
        for _ in range(50 - len(records)):
            step = agent.advance()
            assert step is not None
            records.append(step)
            if step.outcome is not None:
                break
        assert records[-1].outcome is not None
        ttyrec = agent.ttyrec_files
        assert ttyrec

        suite = load_suite(
            Path(__file__).resolve().parents[1] / "evaluation" / "staircase-v1.json"
        )
        case = replace(suite.cases[0], task=task, max_episode_steps=50)
        timestamp = "2026-10-02T00:00:00+00:00"
        run = RunRecord(
            id="seed-1131-corpse",
            created_at=timestamp,
            updated_at=timestamp,
            state=RunState.TERMINAL,
            outcome=records[-1].outcome,
            environment=task.environment.value,
            character=suite.character,
            suite_seed=1131,
            core_seed=1131,
            display_seed=1131,
            level_seed=1131,
            max_episode_steps=50,
            model="scripted",
            policy_version="policy",
            knowledge_version="knowledge",
            nle_version="1.3.0",
            ollama_num_ctx=8192,
            ollama_version=None,
            ttyrec_path=str(ttyrec[0]),
            error=None,
            task=task,
        )
        events = [
            RunEvent(
                0,
                timestamp,
                EventKind.RUN_STARTED,
                RunStartedPayload(initial, agent.legal_actions, initial_goal, None),
            ),
            *(
                RunEvent(index, timestamp, EventKind.STEP, step_payload(step))
                for index, step in enumerate(records, start=1)
            ),
        ]
        result = summarize_run(
            run,
            events,
            suite=suite,
            case=case,
            seed=1131,
            ended_by="episode_end",
            wall_seconds=0.0,
            data_directory=tmp_path,
        )
        assert result.invalid_actions == 0
        assert result.gate_rejections == 0
        assert result.integrity_problems == ()
    finally:
        agent.stop()


def test_untracked_lichen_remains_edible_after_another_same_cell_kill(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path, task=task)),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        before = replace(
            initial,
            message="There is a doorway here.  You see here a lichen corpse.",
            player=replace(initial.player, turn=100, hunger=1),
        )
        cell = MapCell(before.player.x, before.player.y)
        level = LevelKey(before.player.dungeon_number, before.player.dungeon_level)
        agent._corpse_kills[(level, cell)] = CorpseKill("sewer rat", 99, level, cell)
        evidence = CorpseEvidence("lichen", None, None, cell)
        eat = agent._gate.actions_by_name["Command.EAT"]
        selection = ActionSelection(
            ActionSelectionSource.DETERMINISTIC_SKILL,
            agent.snapshot().current_goal,
            Skill.CORPSE,
            SkillSelectionSource.ARBITER,
            None,
            eat.index,
            "Eat the identified nonrotting lichen underfoot.",
            ActionIntent(None, None, None, corpse=evidence),
        )
        permit = agent._hunger_permit(selection, before)
        assert permit is not None and permit.corpse == evidence
        assert (
            agent._gate.resolve(
                eat.index, before=before, selection=selection, hunger_permit=permit
            )
            == eat
        )
    finally:
        agent.stop()


def test_hunger_permit_defers_a_burden_drop_answer_sharing_the_eat_letter(
    tmp_path: Path,
) -> None:
    """Letter 'e' is both Command.EAT and the only key for an 'e' inventory
    slot; a burden-drop answer selecting it must bypass the hunger/EAT permit
    entirely rather than being rejected as an invalid EAT during a prompt."""
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path, task=task)),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        before = replace(
            initial,
            message="What do you want to drop? [bd-j or ?*] ",
            prompt=PromptState(True, False, False),
            player=replace(initial.player, encumbrance=5),
        )
        eat = agent._gate.actions_by_name["Command.EAT"]
        evidence = DropEvidence("e", "4 food rations", 4, 10, ord("e"))
        selection = ActionSelection(
            ActionSelectionSource.DETERMINISTIC_PROMPT,
            agent.snapshot().current_goal,
            Skill.BURDEN,
            SkillSelectionSource.ARBITER,
            None,
            eat.index,
            "Answer the offered drop-menu letter that collides with EAT.",
            ActionIntent(None, None, None, drop=evidence),
        )
        assert agent._hunger_permit(selection, before) is None
    finally:
        agent.stop()


def test_adjacent_hostile_defense_preempts_opening_a_new_burden_drop(
    tmp_path: Path,
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path, task=task)),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        hero = (initial.player.x, initial.player.y)
        memory = agent._dungeon.current
        memory.monsters.clear()
        neighbor = next(
            point for point in memory.neighbors(hero) if point[0] == hero[0] + 1
        )
        memory.monsters[neighbor] = Monster(nethack.GLYPH_MON_OFF, "werejackal", False)
        refused = replace(
            initial,
            message="You can't even move a handspan with this load!",
            player=replace(initial.player, encumbrance=5),
        )
        plan = agent._decide(refused, None, lambda: False, 0)
        assert plan is not None
        assert plan.selection.skill is Skill.EXPLORE_LEVEL
        assert plan.selection.intent is not None
        assert plan.selection.intent.attack_target == MapCell(*neighbor)
        memory.monsters.clear()
        undefended = agent._decide(refused, None, lambda: False, 0)
        assert undefended is not None
        assert undefended.selection.skill is Skill.BURDEN
    finally:
        agent.stop()


@pytest.mark.parametrize(
    ("command", "cell", "action_name"),
    [
        ("y", MapCell(43, 4), "CompassDirection.NW"),
        ("n", MapCell(45, 6), "CompassDirection.SE"),
    ],
)
def test_corpse_route_command_is_not_a_floor_answer(
    tmp_path: Path, command: str, cell: MapCell, action_name: str
) -> None:
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(seed=1170, artifact_directory=tmp_path, task=task)
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    try:
        before = replace(
            initial,
            step_index=534,
            message="You kill the gecko!",
            prompt=PromptState(False, False, False),
            player=replace(initial.player, x=44, y=5, turn=530, hunger=1),
        )
        evidence = CorpseEvidence("gecko", 530, 0, cell)
        selection = ActionSelection(
            source=ActionSelectionSource.DETERMINISTIC_SKILL,
            goal=agent.snapshot().current_goal,
            skill=Skill.CORPSE,
            skill_selection=SkillSelectionSource.ARBITER,
            stuck_reason=None,
            action_index=agent._gate.actions_by_command[ord(command)].index,
            rationale="Approach the observed gecko kill cell.",
            intent=ActionIntent(
                IntentDestination(DestinationKind.CORPSE, cell.x, cell.y),
                None,
                (cell,),
                corpse=evidence,
            ),
        )
        action = agent._gate.resolve(
            selection.action_index, before=before, selection=selection
        )
        assert action.name == action_name
        after = replace(
            before,
            step_index=before.step_index + 1,
            player=replace(before.player, x=cell.x, y=cell.y, turn=531),
        )
        payload = StepPayload(
            selection,
            None,
            None,
            None,
            None,
            action,
            0.0,
            False,
            False,
            0,
            False,
            None,
            after,
        )
        assert payload.selection.intent.corpse.outcome is None
        prompt = replace(
            before,
            prompt=PromptState(True, False, False),
            message="There is a gecko corpse here; eat it? [ynq] (n) ",
        )
        if command == "y":
            with pytest.raises(ActionGateError):
                agent._gate.resolve(
                    selection.action_index, before=prompt, selection=selection
                )
    finally:
        agent.stop()


def test_look_discovers_a_covered_staircase_under_a_real_native_pile(
    tmp_path: Path,
) -> None:
    """Real NLE I/O, not a synthetic fixture: drop two items on the native
    starting upstairs, force the next decision to see the resulting
    ambiguous arrival message, and confirm the look skill presses a real
    ':' whose preserved multi-page native screen corrects the remembered
    terrain to the covered upstairs."""
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path, task=task)),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    before = agent.start()
    env = agent._environment
    by_name = {a.name: a for a in env.legal_actions}
    by_command = {a.command: a for a in env.legal_actions}

    def raw(index: int):
        transition = env.step(index)
        return agent._projector.project(
            transition.observation, step_index=env.step_index
        )

    try:
        position = (before.player.x, before.player.y)
        # The initial spawn never produced an arrival message, so the
        # covered upstairs is not yet remembered.
        assert agent._dungeon.current.cmap(position) == -1
        letters = [item.letter for item in before.inventory[:2]]
        drop = by_name["Command.DROP"]
        for letter in letters:
            before = raw(drop.index)
            before = raw(by_command[ord(letter)].index)
        # Clear the remembered upstairs so only a correct LOOK can restore it.
        agent._dungeon.current._cmap[position[1]][position[0]] = -1
        assert agent._dungeon.current.cmap(position) == -1
        forced = replace(before, message="There are several objects here.")
        agent._observation = forced
        agent._dungeon.observe(forced)
        agent._state = RunState.RUNNING

        look_record = agent.advance()
        assert look_record is not None
        assert look_record.action.name == "Command.LOOK"
        assert look_record.after.prompt.active
        assert agent._dungeon.current.cmap(position) == 23

        more_record = agent.advance()
        assert more_record is not None
        assert more_record.action.name == "MiscAction.MORE"
        assert not more_record.after.prompt.active
        assert agent._dungeon.current.cmap(position) == 23
    finally:
        agent.stop()
