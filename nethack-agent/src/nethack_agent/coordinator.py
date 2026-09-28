from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from nethack_agent.decision import (
    FORBIDDEN_ACTION_NAMES,
    ActionSelection,
    ActionSelectionSource,
    ModelActionDecision,
    ModelSkillDecision,
    RunOutcome,
    RunState,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    StuckReason,
)
from nethack_agent.environment import LegalAction, NleEnvironment, StepTransition
from nethack_agent.model import DecisionFailure, HierarchicalDecisionModel
from nethack_agent.navigation import ActionKind, ActionRecord, DungeonMemory
from nethack_agent.observation import ObservationProjector, ProjectedObservation
from nethack_agent.skills import (
    ExploreLevelSkill,
    SafePromptHandler,
    SkillAction,
    StaircaseNavigationSkill,
)
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS, Goal

# While exploration stays stuck after a stuck consultation, the model chooses
# fallback actions and is asked to reselect a skill at most this often.
STUCK_RECONSULT_STEPS: Final = 20


class CoordinatorError(RuntimeError):
    """Base class for coordinator failures."""


class CoordinatorLifecycleError(CoordinatorError):
    """A requested lifecycle transition is not currently valid."""


class CoordinatorBusyError(CoordinatorLifecycleError):
    """Another caller is already deciding or advancing."""


class ActionGateError(CoordinatorError):
    """An action proposal was rejected before it could reach NLE."""


class CoordinatorInvariantError(CoordinatorError):
    """An internal coordinator invariant was violated."""


class ActionGate:
    """Resolve only episode actions allowed by the fixed staircase policy."""

    def __init__(self, legal_actions: tuple[LegalAction, ...]) -> None:
        indices = tuple(action.index for action in legal_actions)
        if not legal_actions or indices != tuple(range(len(legal_actions))):
            raise CoordinatorInvariantError(
                "legal action table is not indexed contiguously"
            )
        self._legal_actions = legal_actions
        self._allowed_actions = tuple(
            action
            for action in legal_actions
            if action.name not in FORBIDDEN_ACTION_NAMES
        )
        self.actions_by_name = {action.name: action for action in self._allowed_actions}
        self.actions_by_command = {
            action.command: action for action in self._allowed_actions
        }

    @property
    def allowed_actions(self) -> tuple[LegalAction, ...]:
        return self._allowed_actions

    def resolve(self, action_index: int) -> LegalAction:
        if isinstance(action_index, bool) or not isinstance(action_index, int):
            raise ActionGateError("action index must be an integer")
        if not 0 <= action_index < len(self._legal_actions):
            raise ActionGateError(f"action index {action_index} is not legal")
        action = self._legal_actions[action_index]
        if action.name in FORBIDDEN_ACTION_NAMES:
            raise ActionGateError(
                f"{action.name} is forbidden: changing dungeon level is never part "
                "of the staircase task, which ends when standing on '>'"
            )
        return action


@dataclass(frozen=True, slots=True)
class StepRecord:
    before: ProjectedObservation
    goal: Goal
    skill: Skill
    selection: ActionSelection
    skill_model_decision: ModelSkillDecision | None
    action_model_decision: ModelActionDecision | None
    action: LegalAction
    transition: StepTransition
    after: ProjectedObservation
    outcome: RunOutcome | None


@dataclass(frozen=True, slots=True)
class CoordinatorSnapshot:
    state: RunState
    outcome: RunOutcome | None
    observation: ProjectedObservation | None
    current_goal: Goal
    current_skill: Skill | None
    last_error: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "outcome": self.outcome.value if self.outcome else None,
            "observation": self.observation.to_json() if self.observation else None,
            "current_goal": self.current_goal.to_json(),
            "current_skill": self.current_skill.value if self.current_skill else None,
            "last_error": self.last_error,
        }


@dataclass(frozen=True, slots=True)
class _Plan:
    selection: ActionSelection
    skill_model_decision: ModelSkillDecision | None
    action_model_decision: ModelActionDecision | None
    record: ActionRecord
    stuck_consulted: bool


class AgentCoordinator:
    """Run a goal/skill hierarchy with cancellable model decisions."""

    def __init__(
        self,
        environment: NleEnvironment,
        projector: ObservationProjector,
        model: HierarchicalDecisionModel,
    ) -> None:
        self._environment = environment
        self._projector = projector
        self._model = model
        self._gate = ActionGate(environment.legal_actions)
        self._navigation = StaircaseNavigationSkill()
        self._exploration = ExploreLevelSkill()
        self._prompt_handler = SafePromptHandler()
        self._dungeon = DungeonMemory()
        self._lock = threading.RLock()
        self._state = RunState.IDLE
        self._outcome: RunOutcome | None = None
        self._observation: ProjectedObservation | None = None
        self._goal: Goal = STAND_ON_DOWNSTAIRS
        self._skill_decision: SkillDecision | None = None
        self._current_skill: Skill | None = None
        self._last_error: str | None = None
        self._lifecycle_revision = 0
        self._advance_in_flight = False

    @property
    def legal_actions(self) -> tuple[LegalAction, ...]:
        return self._environment.legal_actions

    @property
    def allowed_actions(self) -> tuple[LegalAction, ...]:
        return self._gate.allowed_actions

    @property
    def ttyrec_files(self) -> tuple[Path, ...]:
        return self._environment.ttyrec_files

    def snapshot(self) -> CoordinatorSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def start(self) -> ProjectedObservation:
        with self._lock:
            if self._state is not RunState.IDLE:
                raise CoordinatorLifecycleError("coordinator can only start from idle")
            self._projector.reset()
            self._dungeon.reset()
            try:
                raw = self._environment.reset()
                self._observation = self._projector.project(raw, step_index=0)
            except Exception as error:
                self._mark_error_locked(error)
                raise
            self._state = RunState.PAUSED
            self._outcome = None
            self._skill_decision = None
            self._current_skill = None
            self._last_error = None
            self._lifecycle_revision += 1
            return self._observation

    def resume(self) -> None:
        with self._lock:
            if self._state is not RunState.PAUSED:
                raise CoordinatorLifecycleError(
                    "coordinator can only resume from paused"
                )
            self._last_error = None
            self._state = RunState.RUNNING
            self._lifecycle_revision += 1

    def pause(self) -> None:
        with self._lock:
            if self._state is not RunState.RUNNING:
                raise CoordinatorLifecycleError(
                    "coordinator can only pause from running"
                )
            self._state = RunState.PAUSED
            self._lifecycle_revision += 1

    def advance(
        self,
        *,
        single_step: bool = False,
        on_step: Callable[[StepRecord], None] | None = None,
    ) -> StepRecord | None:
        with self._lock:
            allowed = self._state is RunState.RUNNING or (
                single_step and self._state is RunState.PAUSED
            )
            if not allowed:
                raise CoordinatorLifecycleError("coordinator is not allowed to advance")
            if self._advance_in_flight:
                raise CoordinatorBusyError("an advance is already in progress")
            before = self._observation
            if before is None:
                raise CoordinatorInvariantError(
                    "coordinator has no current observation"
                )
            revision = self._lifecycle_revision
            started_state = self._state
            model_skill = self._skill_decision
            self._advance_in_flight = True

        def canceled() -> bool:
            with self._lock:
                return self._advance_was_canceled_locked(revision, started_state)

        try:
            try:
                plan = self._decide(before, model_skill, canceled)
                if plan is None:
                    return None
            except DecisionFailure as error:
                with self._lock:
                    if self._advance_was_canceled_locked(revision, started_state):
                        return None
                    self._state = RunState.PAUSED
                    self._last_error = str(error)
                    self._lifecycle_revision += 1
                raise
            except Exception as error:
                with self._lock:
                    if self._advance_was_canceled_locked(revision, started_state):
                        return None
                    self._mark_error_locked(error)
                raise

            selection = plan.selection
            with self._lock:
                if self._advance_was_canceled_locked(revision, started_state):
                    return None
                try:
                    action = self._gate.resolve(selection.action_index)
                except ActionGateError as error:
                    self._state = RunState.PAUSED
                    self._last_error = str(error)
                    self._lifecycle_revision += 1
                    raise
                try:
                    transition = self._environment.step(action.index)
                    after = self._projector.project(
                        transition.observation, step_index=transition.step_index
                    )
                    self._observation = after
                    self._commit_plan_locked(plan, before)
                    outcome = self._terminal_outcome(transition)
                    if outcome is not None:
                        self._outcome = outcome
                        self._state = RunState.TERMINAL
                        self._lifecycle_revision += 1
                        self._environment.close()
                    record = StepRecord(
                        before=before,
                        goal=selection.goal,
                        skill=selection.skill,
                        selection=selection,
                        skill_model_decision=plan.skill_model_decision,
                        action_model_decision=plan.action_model_decision,
                        action=action,
                        transition=transition,
                        after=after,
                        outcome=outcome,
                    )
                    if on_step is not None:
                        on_step(record)
                    return record
                except Exception as error:
                    self._mark_error_locked(error)
                    raise
        finally:
            with self._lock:
                self._advance_in_flight = False

    def _decide(
        self,
        before: ProjectedObservation,
        model_skill: SkillDecision | None,
        canceled: Callable[[], bool],
    ) -> _Plan | None:
        """Choose one action; return None when a lifecycle change canceled it.

        Priority: a pending exploration kick direction, safe prompt answers,
        the model for unhandled prompts, staircase navigation to a reachable
        remembered `>`, then level exploration. Exploration that reports stuck
        triggers a model skill consultation (rate-limited) and otherwise a
        model fallback action.
        """
        memory = self._dungeon.observe(before)
        skill_model_decision: ModelSkillDecision | None = None
        if model_skill is None:
            skill_model_decision = self._select_skill(before, None)
            model_skill = skill_model_decision.decision
            if canceled():
                return None
        actions = self._gate.actions_by_name
        arbiter = SkillSelectionSource.ARBITER

        kick = self._exploration.continue_kick(before, memory, actions)
        if kick is not None:
            return self._skill_plan(
                kick, Skill.EXPLORE_LEVEL, arbiter, None, skill_model_decision
            )

        prompt = self._prompt_handler.select_action(
            before, actions, self._gate.actions_by_command
        )
        navigation = (
            None
            if before.prompt.active
            else self._navigation.select_action(memory, actions)
        )
        arbiter_skill = (
            Skill.STAIRCASE_NAVIGATION
            if navigation is not None
            else Skill.EXPLORE_LEVEL
        )
        if prompt is not None:
            return self._skill_plan(
                prompt,
                arbiter_skill,
                arbiter,
                None,
                skill_model_decision,
                source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            )
        if before.prompt.active:
            return self._fallback_plan(
                before, arbiter_skill, arbiter, None, skill_model_decision, canceled
            )
        if navigation is not None:
            return self._skill_plan(
                navigation, arbiter_skill, arbiter, None, skill_model_decision
            )

        explored = self._exploration.select_action(memory, actions)
        if explored.action is not None:
            return self._skill_plan(
                explored.action,
                Skill.EXPLORE_LEVEL,
                arbiter,
                None,
                skill_model_decision,
            )
        stuck = explored.stuck
        assert stuck is not None
        consulted = skill_model_decision is None and (
            memory.stuck_consult_step is None
            or before.step_index - memory.stuck_consult_step >= STUCK_RECONSULT_STEPS
        )
        if consulted:
            skill_model_decision = self._select_skill(before, stuck)
            model_skill = skill_model_decision.decision
            if canceled():
                return None
            if model_skill.skill is Skill.EXPLORE_LEVEL:
                # The re-arm is kept even if a later pause discards this step;
                # it only widens the deterministic search budget.
                memory.rearm()
                rearmed = self._exploration.select_action(memory, actions)
                if rearmed.action is not None:
                    return self._skill_plan(
                        rearmed.action,
                        Skill.EXPLORE_LEVEL,
                        SkillSelectionSource.MODEL,
                        stuck,
                        skill_model_decision,
                        stuck_consulted=True,
                    )
        return self._fallback_plan(
            before,
            model_skill.skill,
            SkillSelectionSource.MODEL,
            stuck,
            skill_model_decision,
            canceled,
            stuck_consulted=consulted,
        )

    def _select_skill(
        self, before: ProjectedObservation, stuck: StuckReason | None
    ) -> ModelSkillDecision:
        decision = self._model.select_skill(before, (self._goal,), tuple(Skill), stuck)
        self._validate_skill_decision(decision.decision)
        return decision

    def _skill_plan(
        self,
        proposal: SkillAction,
        skill: Skill,
        skill_selection: SkillSelectionSource,
        stuck: StuckReason | None,
        skill_model_decision: ModelSkillDecision | None,
        *,
        source: ActionSelectionSource = ActionSelectionSource.DETERMINISTIC_SKILL,
        stuck_consulted: bool = False,
    ) -> _Plan:
        return _Plan(
            selection=ActionSelection(
                source=source,
                goal=self._goal,
                skill=skill,
                skill_selection=skill_selection,
                stuck_reason=stuck,
                action_index=proposal.action_index,
                rationale=proposal.rationale,
                intent=proposal.intent,
            ),
            skill_model_decision=skill_model_decision,
            action_model_decision=None,
            record=proposal.record,
            stuck_consulted=stuck_consulted,
        )

    def _fallback_plan(
        self,
        before: ProjectedObservation,
        skill: Skill,
        skill_selection: SkillSelectionSource,
        stuck: StuckReason | None,
        skill_model_decision: ModelSkillDecision | None,
        canceled: Callable[[], bool],
        *,
        stuck_consulted: bool = False,
    ) -> _Plan | None:
        action_model_decision = self._model.select_action(
            before, self.allowed_actions, self._goal, skill
        )
        if canceled():
            return None
        decision = action_model_decision.decision
        return _Plan(
            selection=ActionSelection(
                source=ActionSelectionSource.MODEL_FALLBACK,
                goal=self._goal,
                skill=skill,
                skill_selection=skill_selection,
                stuck_reason=stuck,
                action_index=decision.action_index,
                rationale=decision.rationale,
                intent=None,
            ),
            skill_model_decision=skill_model_decision,
            action_model_decision=action_model_decision,
            record=ActionRecord(ActionKind.OTHER, self._dungeon.current.position),
            stuck_consulted=stuck_consulted,
        )

    def _commit_plan_locked(self, plan: _Plan, before: ProjectedObservation) -> None:
        selection = plan.selection
        if plan.skill_model_decision is not None:
            self._skill_decision = plan.skill_model_decision.decision
        self._current_skill = selection.skill
        memory = self._dungeon.current
        if plan.stuck_consulted:
            memory.stuck_consult_step = before.step_index
        elif (
            selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
            and selection.stuck_reason is None
        ):
            memory.stuck_consult_step = None
        memory.record(plan.record)

    def stop(self) -> None:
        with self._lock:
            if self._state in {
                RunState.STOPPED,
                RunState.TERMINAL,
                RunState.ERROR,
            }:
                return
            self._state = RunState.STOPPED
            self._outcome = RunOutcome.STOPPED
            self._lifecycle_revision += 1
            self._environment.close()

    def fail(self, error: Exception) -> None:
        with self._lock:
            if self._state in {
                RunState.STOPPED,
                RunState.TERMINAL,
                RunState.ERROR,
            }:
                return
            self._mark_error_locked(error)

    def _snapshot_locked(self) -> CoordinatorSnapshot:
        return CoordinatorSnapshot(
            state=self._state,
            outcome=self._outcome,
            observation=self._observation,
            current_goal=self._goal,
            current_skill=self._current_skill,
            last_error=self._last_error,
        )

    def _advance_was_canceled_locked(
        self, revision: int, started_state: RunState
    ) -> bool:
        return self._lifecycle_revision != revision or self._state is not started_state

    def _mark_error_locked(self, error: Exception) -> None:
        self._last_error = str(error)
        self._outcome = RunOutcome.ERROR
        self._state = RunState.ERROR
        self._lifecycle_revision += 1
        try:
            self._environment.close()
        except Exception as close_error:
            self._last_error = f"{error}; environment close failed: {close_error}"

    def _validate_skill_decision(self, decision: SkillDecision) -> None:
        if decision.goal != self._goal:
            raise CoordinatorInvariantError(
                f"model selected unavailable goal {decision.goal.token}"
            )

    @staticmethod
    def _terminal_outcome(transition: StepTransition) -> RunOutcome | None:
        if transition.truncated:
            return RunOutcome.TRUNCATED
        if not transition.terminated:
            return None
        if transition.end_status == 2:
            return RunOutcome.TASK_SUCCESS
        if transition.end_status == 1:
            return RunOutcome.DEATH
        return RunOutcome.ERROR
