import threading
from pathlib import Path

import pytest

from nethack_agent.coordinator import (
    ActionGate,
    ActionGateError,
    AgentCoordinator,
    CoordinatorBusyError,
    StepRecord,
)
from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    ActionSelectionSource,
    DecisionMetrics,
    MapCell,
    ModelActionDecision,
    ModelSkillDecision,
    RunOutcome,
    RunState,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    StuckReason,
    TraversalPermit,
)
from nethack_agent.environment import LegalAction, NleEnvironment, ScenarioConfig
from nethack_agent.model import DecisionFailure, HierarchicalDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS, Goal, LevelKey, StairDirection

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
        assert set(skills) == set(Skill)
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
    assert following is not None
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
