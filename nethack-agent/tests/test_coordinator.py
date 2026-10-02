import threading
from dataclasses import replace
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
    LEVEL_CHANGE_ACTIONS,
    PRAYER_FIRST_SAFE_TURN,
    PRAYER_REPEAT_WAIT_TURNS,
    ActionCandidate,
    ActionDecision,
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DecisionMetrics,
    HungerPermit,
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
from nethack_agent.evaluation import _action_is_valid
from nethack_agent.events import StepPayload
from nethack_agent.model import (
    DecisionFailure,
    HierarchicalDecisionModel,
    ScriptedDevelopmentModel,
)
from nethack_agent.navigation import GOLD_GLYPH, ActionRecord, LevelMemory
from nethack_agent.observation import ObservationProjector, PromptState
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import STAIRCASE_TASK, ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    EnterDungeonLeg,
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
            (corpse_prompt, PromptKind.CORPSE_CONFIRMATION, Skill.HUNGER),
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


def test_real_survival_coordinator_prays_at_first_weak_and_audits_both_steps(
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
                seed=1127,
                artifact_directory=tmp_path,
                max_episode_steps=3000,
                task=task,
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    observed_kills = initial.message.count("You kill")
    agent.resume()
    try:
        for _ in range(3000):
            first = agent.advance()
            assert first is not None
            if first.action.name == "Command.PRAY":
                break
            assert first.outcome is None, "run ended before first Weak prayer"
            observed_kills += first.after.message.count("You kill")
        else:
            raise AssertionError("no Weak prayer before episode cap")
        assert first.before.player.hunger >= 3
        assert first.before.player.turn >= PRAYER_FIRST_SAFE_TURN
        assert first.after.message == "Are you sure you want to pray? [yn] (n) "
        assert first.selection.intent is not None
        evidence = first.selection.intent.prayer
        assert evidence is not None and evidence.kill_count == observed_kills
        first_payload = step_payload(first)
        assert StepPayload.from_json(first_payload.to_json()) == first_payload
        assert _action_is_valid(
            first_payload,
            agent.legal_actions,
            first.before,
            True,
            task.action_profile,
            kill_count=observed_kills,
        )
        confirmed = agent.advance()
        assert confirmed is not None and confirmed.action.command == ord("y")
        assert confirmed.selection.intent is not None
        result = confirmed.selection.intent.prayer
        assert result is not None and result.outcome is not None
        assert result.outcome.kind is PrayerOutcomeKind.FIXED
        assert result.outcome.turn == confirmed.after.player.turn
        assert result.outcome.hunger == confirmed.after.player.hunger
        assert result.outcome.message == confirmed.after.message
        confirmed_payload = step_payload(confirmed)
        assert StepPayload.from_json(confirmed_payload.to_json()) == confirmed_payload
        assert _action_is_valid(
            confirmed_payload,
            agent.legal_actions,
            confirmed.before,
            True,
            task.action_profile,
            prior_prayers=1,
            last_prayer_turn=first.before.player.turn,
            pending_prayer=evidence,
            kill_count=observed_kills + first.after.message.count("You kill"),
        )
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


def test_entering_the_mines_probes_both_downstairs_of_the_branch_level(
    tmp_path: Path,
) -> None:
    agent, records = run_to_end(
        tmp_path, 4, score_task(EnterDungeonLeg(2)), max_steps=600
    )

    assert traversals(records) == [
        (DOWN_ACTION, "traverse_stairs:down:main", (0, 1), (0, 2), "unknown", None),
        # Two unknown `>` on DL2: the nearer probe leads to DL3, the main one.
        (
            DOWN_ACTION,
            "traverse_stairs:down:branch:2",
            (0, 2),
            (0, 3),
            "unknown",
            None,
        ),
        (UP_ACTION, "traverse_stairs:up:main", (0, 3), (0, 2), "main", "arrival"),
        (
            DOWN_ACTION,
            "traverse_stairs:down:branch:2",
            (0, 2),
            (2, 1),
            "branch",
            "elimination",
        ),
    ]
    assert records[-1].outcome is RunOutcome.OBJECTIVE_COMPLETE
    assert agent.snapshot().level == LevelKey(2, 1)


def test_terminal_steps_keep_the_last_live_level(tmp_path: Path) -> None:
    # NLE zeroes the bottom-line statistics of a terminal observation.
    staircase, success = run_to_end(tmp_path / "staircase", 2, STAIRCASE_TASK, 100)
    assert success[-1].outcome is RunOutcome.TASK_SUCCESS
    assert success[-1].after.player.dungeon_level == 0
    assert staircase.snapshot().level == LevelKey(0, 1)
    assert staircase.snapshot().objective_leg == 0

    score, death = run_to_end(
        tmp_path / "score", 9, score_task(ReachLevelLeg(LevelKey(0, 12))), 600
    )
    assert death[-1].outcome is RunOutcome.DEATH
    assert death[-1].after.player.dungeon_level == 0
    assert score.snapshot().level == LevelKey(0, 5)
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
