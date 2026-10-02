from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from nethack_agent.decision import (
    EAT_ACTION_NAME,
    LEVEL_CHANGE_ACTIONS,
    PRAY_ACTION_NAME,
    YES_COMMAND,
    ActionSelection,
    ActionSelectionSource,
    HungerPermit,
    MapCell,
    ModelActionDecision,
    ModelSkillDecision,
    PrayerEvidence,
    PrayerOutcome,
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
    classify_prayer_outcome,
    confirmation_answer_error,
    confirmation_prompt_kind,
    hunger_action_error,
    level_change_error,
    model_selectable_skills,
    prayer_action_error,
    prompt_response_error,
)
from nethack_agent.environment import LegalAction, NleEnvironment, StepTransition
from nethack_agent.model import DecisionFailure, HierarchicalDecisionModel
from nethack_agent.navigation import (
    ActionKind,
    ActionRecord,
    DungeonMemory,
    ExhaustionState,
    LevelMemory,
)
from nethack_agent.observation import ObservationProjector, ProjectedObservation
from nethack_agent.planner import ObjectivePlanner, leg_complete
from nethack_agent.replay import routine_actions, stair_target
from nethack_agent.skills import (
    ExploreLevelSkill,
    GoldNavigationSkill,
    HungerSkill,
    PrayerSkill,
    SafePromptHandler,
    SkillAction,
    StaircaseNavigationSkill,
    item_selection_commands,
    safe_food_rations,
)
from nethack_agent.tasks import ActionProfile, ActionRole, NleTask
from nethack_agent.traversal import (
    STAIR_GOAL_TYPES,
    STAND_ON_DOWNSTAIRS,
    ExploreLevelGoal,
    Goal,
    LevelKey,
    StairDirection,
    TraverseStairsGoal,
)

# While exploration stays stuck after a stuck consultation, the model chooses
# fallback actions and is asked to reselect a skill at most this often.
STUCK_RECONSULT_STEPS: Final = 20
# Tasks whose NLE success state ends the episode; a completed objective does
# not end them early.
_NLE_SUCCESS_TASKS: Final = frozenset({NleTask.STAIRCASE, NleTask.ORACLE})


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
    """Resolve legal actions, requiring typed permits for restricted roles."""

    def __init__(
        self,
        legal_actions: tuple[LegalAction, ...],
        action_profile: ActionProfile = ActionProfile.NLE_TASK_ACTIONS,
    ) -> None:
        indices = tuple(action.index for action in legal_actions)
        if not legal_actions or indices != tuple(range(len(legal_actions))):
            raise CoordinatorInvariantError(
                "legal action table is not indexed contiguously"
            )
        profile_actions = action_profile.actions
        if len(legal_actions) != len(profile_actions):
            raise CoordinatorInvariantError(
                "legal action table does not match its action profile"
            )
        roles = tuple(action_profile.role(action) for action in profile_actions)
        self._legal_actions = legal_actions
        self._roles = roles
        self._profile = action_profile
        self._allowed_actions = tuple(
            action
            for action, role in zip(legal_actions, roles, strict=True)
            if action.name not in LEVEL_CHANGE_ACTIONS
            and role
            not in {
                ActionRole.HUNGER,
                ActionRole.PROMPT_KEY,
                ActionRole.PRAYER,
            }
            and not (
                action_profile is ActionProfile.NLE_SURVIVAL_ACTIONS
                and action.command == YES_COMMAND
            )
        )
        self.actions_by_name = routine_actions(legal_actions)
        self.actions_by_command = {
            action.command: action for action in self.actions_by_name.values()
        }
        self.level_change_actions: dict[StairDirection, LegalAction] = {
            LEVEL_CHANGE_ACTIONS[action.name]: action
            for action in legal_actions
            if action.name in LEVEL_CHANGE_ACTIONS
        }

    @property
    def allowed_actions(self) -> tuple[LegalAction, ...]:
        """Routine actions offered to the model without a contextual permit."""
        return self._allowed_actions

    def is_prompt_key(self, action: LegalAction) -> bool:
        return self._roles[action.index] is ActionRole.PROMPT_KEY

    def resolve(
        self,
        action_index: int,
        permit: TraversalPermit | None = None,
        *,
        hunger_permit: HungerPermit | None = None,
        prompt_permit: PromptPermit | None = None,
        prayer_permit: PrayerPermit | None = None,
        prior_prayers: int = 0,
        last_prayer_turn: int | None = None,
        on_altar: bool = False,
        before: ProjectedObservation | None = None,
        selection: ActionSelection | None = None,
    ) -> LegalAction:
        if isinstance(action_index, bool) or not isinstance(action_index, int):
            raise ActionGateError("action index must be an integer")
        if not 0 <= action_index < len(self._legal_actions):
            raise ActionGateError(f"action index {action_index} is not legal")
        action = self._legal_actions[action_index]
        direction = LEVEL_CHANGE_ACTIONS.get(action.name)
        if direction is not None and (
            permit is None or permit.direction is not direction
        ):
            raise ActionGateError(
                f"{action.name} is forbidden: changing dungeon level requires a "
                "coordinator traversal permit in that direction"
            )
        role = self._roles[action.index]
        if role is ActionRole.HUNGER and hunger_permit is None:
            raise ActionGateError(
                f"{action.name} is forbidden: EAT requires a hunger permit"
            )
        if role is ActionRole.PRAYER:
            if selection is None:
                raise ActionGateError("PRAY requires a deterministic prayer skill")
            error = prayer_action_error(
                action.name,
                selection,
                permit=prayer_permit,
                turn=None if before is None else before.player.turn,
                hunger=None if before is None else before.player.hunger,
                prompt_active=False if before is None else before.prompt.active,
                ration_available=False
                if before is None
                else bool(safe_food_rations(before)),
                prior_prayers=prior_prayers,
                last_prayer_turn=last_prayer_turn,
                on_altar=on_altar,
            )
            if error is not None:
                raise ActionGateError(error)
        if role is ActionRole.PROMPT_KEY and (
            prompt_permit is None
            or prompt_permit.command != action.command
            or prompt_permit.kind is not PromptKind.ITEM
        ):
            raise ActionGateError(
                f"{action.name} is forbidden: prompt keys require a matching "
                "active item-selection prompt permit"
            )
        if (
            self._profile is ActionProfile.NLE_SURVIVAL_ACTIONS
            and action.command == YES_COMMAND
        ):
            if selection is None or before is None:
                raise ActionGateError(
                    "yes requires a decided-on observation and selection"
                )
            error = confirmation_answer_error(
                action.command,
                selection,
                prompt_active=before.prompt.active,
                prompt_kind=confirmation_prompt_kind(
                    before.message,
                    single_choice=before.prompt.single_character_choice,
                    offered_item_commands=item_selection_commands(before),
                ),
                permit=prompt_permit,
            )
            if error is not None:
                raise ActionGateError(error)
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
    # The objective leg being pursued; equal to the leg count once all are met.
    objective_leg: int
    # The level of the last live observation, None before the first.
    level: LevelKey | None

    def to_json(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "outcome": self.outcome.value if self.outcome else None,
            "observation": self.observation.to_json() if self.observation else None,
            "current_goal": self.current_goal.to_json(),
            "current_skill": self.current_skill.value if self.current_skill else None,
            "last_error": self.last_error,
            "objective_leg": self.objective_leg,
            "level": self.level.to_json() if self.level else None,
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
        task = environment.task
        self._gate = ActionGate(environment.legal_actions, task.action_profile)
        self._planner = ObjectivePlanner(task.objective)
        # Only an objective with a leg beyond standing on stairs may change level.
        self._level_changes_allowed = task.objective.changes_level
        # NLE's own success state ends these tasks; otherwise completing the
        # last objective leg ends the run.
        self._objective_ends_run = task.environment not in _NLE_SUCCESS_TASKS
        self._leg = 0
        self._navigation = StaircaseNavigationSkill()
        self._exploration = ExploreLevelSkill()
        self._prompt_handler = SafePromptHandler()
        # Only NetHackGold-v0 rewards gold, and only its options pick it up.
        self._gold = GoldNavigationSkill() if task.environment is NleTask.GOLD else None
        self._hunger = (
            HungerSkill()
            if task.action_profile
            in (
                ActionProfile.NLE_HUNGER_ACTIONS,
                ActionProfile.NLE_SURVIVAL_ACTIONS,
            )
            else None
        )
        self._prayer = (
            PrayerSkill()
            if task.action_profile is ActionProfile.NLE_SURVIVAL_ACTIONS
            else None
        )
        self._prayer_count = 0
        self._last_prayer_turn: int | None = None
        self._prayer_kill_count = 0
        self._pending_prayer: PrayerEvidence | None = None
        self._pending_prayer_step: int | None = None
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
        # The exhaustion an in-flight decision marked, undone unless its step
        # is committed, so every recorded marker matches memory.
        self._exhaustion_undo: tuple[LevelMemory, ExhaustionState] | None = None

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
            if self._hunger is not None:
                self._hunger.reset()
            self._prayer_count = 0
            self._last_prayer_turn = None
            self._prayer_kill_count = 0
            self._pending_prayer = None
            self._pending_prayer_step = None
            try:
                raw = self._environment.reset()
                self._observation = self._projector.project(raw, step_index=0)
                self._prayer_kill_count += self._observation.message.count("You kill")
                self._dungeon.observe(self._observation)
                self._leg = 0
                self._goal = self._planner.plan(0, self._dungeon).goal
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
            leg = self._leg
            self._advance_in_flight = True

        def canceled() -> bool:
            with self._lock:
                return self._advance_was_canceled_locked(revision, started_state)

        try:
            try:
                plan = self._decide(before, model_skill, canceled, leg)
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
                    traversal_permit = self._traversal_permit(selection, before)
                    hunger_permit = self._hunger_permit(selection, before)
                    prayer_permit = self._prayer_permit(selection, before)
                    prompt_permit = self._prompt_permit(selection, before)
                    action = self._gate.resolve(
                        selection.action_index,
                        traversal_permit,
                        hunger_permit=hunger_permit,
                        prompt_permit=prompt_permit,
                        prayer_permit=prayer_permit,
                        prior_prayers=self._prayer_count,
                        last_prayer_turn=self._last_prayer_turn,
                        on_altar=self._on_altar(before),
                        before=before,
                        selection=selection,
                    )
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
                    selection = self._commit_prayer_locked(
                        selection, action, before, after, transition
                    )
                    self._commit_plan_locked(plan, before)
                    outcome = self._terminal_outcome(transition)
                    if outcome is None:
                        outcome = self._advance_objective_locked(after)
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
                if self._exhaustion_undo is not None:
                    memory, state = self._exhaustion_undo
                    memory.restore_exhaustion(state)
                    self._exhaustion_undo = None
                self._advance_in_flight = False

    def _advance_objective_locked(
        self, after: ProjectedObservation
    ) -> RunOutcome | None:
        """Fold a live observation into memory and advance completed legs.

        Only called while NLE's episode continues: NLE zeroes the bottom-line
        statistics of a terminal observation, so those carry no level.
        """
        self._dungeon.observe(after)
        self._leg = self._planner.advance(self._leg, self._dungeon)
        if self._leg == len(self._planner.legs) and self._objective_ends_run:
            return RunOutcome.OBJECTIVE_COMPLETE
        return None

    def _decide(
        self,
        before: ProjectedObservation,
        model_skill: SkillDecision | None,
        canceled: Callable[[], bool],
        leg: int,
    ) -> _Plan | None:
        """Choose one action; return None when a lifecycle change canceled it.

        The objective planner sets the step's goal. Verified ration and its
        pending item answer precede a pending exploration kick. Then an exact
        pending prayer prompt, safe adjacent defense, and a guarded first prayer
        precede safe prompt handling and ordinary navigation/exploration.
        Exhausted exploration may consult the model for a fallback.
        """
        memory = self._dungeon.observe(before)
        goal = self._plan_goal(leg, memory)
        skill_model_decision: ModelSkillDecision | None = None
        if model_skill is None:
            skill_model_decision = self._select_skill(before, None, goal)
            model_skill = skill_model_decision.decision
            if canceled():
                return None
        actions = self._gate.actions_by_name
        arbiter = SkillSelectionSource.ARBITER

        if self._hunger is not None:
            hunger = self._hunger.select_action(
                before, actions, self._gate.actions_by_command
            )
            if hunger is not None:
                source = (
                    ActionSelectionSource.DETERMINISTIC_PROMPT
                    if before.prompt.active
                    else ActionSelectionSource.DETERMINISTIC_SKILL
                )
                return self._skill_plan(
                    hunger,
                    goal,
                    Skill.HUNGER,
                    arbiter,
                    None,
                    skill_model_decision,
                    source=source,
                )

        kick = self._exploration.continue_kick(before, memory, actions)
        if kick is not None:
            return self._skill_plan(
                kick, goal, Skill.EXPLORE_LEVEL, arbiter, None, skill_model_decision
            )

        if self._prayer is not None:
            pending = (
                self._pending_prayer
                if self._pending_prayer_step == before.step_index - 1
                else None
            )
            prayer = self._prayer.select_action(
                before,
                memory,
                actions,
                self._gate.actions_by_command,
                prior_prayers=self._prayer_count,
                last_prayer_turn=self._last_prayer_turn,
                kill_count=self._prayer_kill_count,
                pending=pending,
            )
            if prayer is not None:
                source = (
                    ActionSelectionSource.DETERMINISTIC_PROMPT
                    if pending is not None
                    else ActionSelectionSource.DETERMINISTIC_SKILL
                )
                return self._skill_plan(
                    prayer,
                    goal,
                    Skill.PRAYER,
                    arbiter,
                    None,
                    skill_model_decision,
                    source=source,
                )
        prompt = self._prompt_handler.select_action(
            before, actions, self._gate.actions_by_command
        )
        navigation = None if before.prompt.active else self._navigate(memory, goal)
        arbiter_skill = (
            Skill.STAIRCASE_NAVIGATION
            if navigation is not None
            else Skill.EXPLORE_LEVEL
        )
        if prompt is not None:
            return self._skill_plan(
                prompt,
                goal,
                arbiter_skill,
                arbiter,
                None,
                skill_model_decision,
                source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            )
        if before.prompt.active:
            return self._fallback_plan(
                before,
                goal,
                arbiter_skill,
                arbiter,
                None,
                skill_model_decision,
                canceled,
            )
        if navigation is not None:
            return self._skill_plan(
                navigation, goal, arbiter_skill, arbiter, None, skill_model_decision
            )

        if self._gold is not None and isinstance(goal, ExploreLevelGoal):
            gold = self._gold.select_action(memory, actions)
            if gold is not None:
                return self._skill_plan(
                    gold,
                    goal,
                    Skill.GOLD_NAVIGATION,
                    arbiter,
                    None,
                    skill_model_decision,
                )

        explored = self._exploration.select_action(memory, actions, stair_target(goal))
        if explored.action is not None:
            return self._skill_plan(
                explored.action,
                goal,
                Skill.EXPLORE_LEVEL,
                arbiter,
                None,
                skill_model_decision,
            )
        stuck = explored.stuck
        assert stuck is not None
        exhausted: LevelKey | None = None
        if stuck is StuckReason.SEARCH_EXHAUSTED and not memory.exhausted:
            # The level is exhausted: the step records the marker, and the
            # objective may now be complete or want another staircase or
            # level. The staircase objective keeps its goal.
            self._exhaustion_undo = (memory, memory.mark_exhausted())
            exhausted = memory.level
            if self._leg_complete(leg):
                return self._confirm_exhaustion(memory, goal, skill_model_decision)
            replanned = self._plan_goal(leg, memory)
            if replanned != goal:
                goal = replanned
                navigation = self._navigate(memory, goal)
                if navigation is not None:
                    return self._skill_plan(
                        navigation,
                        goal,
                        Skill.STAIRCASE_NAVIGATION,
                        arbiter,
                        None,
                        skill_model_decision,
                        exhausted_level=exhausted,
                    )
                explored = self._exploration.select_action(
                    memory, actions, stair_target(goal)
                )
                if explored.action is not None:
                    return self._skill_plan(
                        explored.action,
                        goal,
                        Skill.EXPLORE_LEVEL,
                        arbiter,
                        None,
                        skill_model_decision,
                        exhausted_level=exhausted,
                    )
                assert explored.stuck is not None
                stuck = explored.stuck
        consulted = skill_model_decision is None and (
            memory.stuck_consult_step is None
            or before.step_index - memory.stuck_consult_step >= STUCK_RECONSULT_STEPS
        )
        if consulted:
            skill_model_decision = self._select_skill(before, stuck, goal)
            model_skill = skill_model_decision.decision
            if canceled():
                return None
            if model_skill.skill is Skill.EXPLORE_LEVEL:
                # The re-arm is kept even if a later pause discards this step;
                # it only widens the deterministic search budget.
                memory.rearm()
                rearmed = self._exploration.select_action(
                    memory, actions, stair_target(goal)
                )
                if rearmed.action is not None:
                    return self._skill_plan(
                        rearmed.action,
                        goal,
                        Skill.EXPLORE_LEVEL,
                        SkillSelectionSource.MODEL,
                        stuck,
                        skill_model_decision,
                        stuck_consulted=True,
                        exhausted_level=exhausted,
                    )
        return self._fallback_plan(
            before,
            goal,
            model_skill.skill,
            SkillSelectionSource.MODEL,
            stuck,
            skill_model_decision,
            canceled,
            stuck_consulted=consulted,
            exhausted_level=exhausted,
        )

    def _leg_complete(self, leg: int) -> bool:
        legs = self._planner.legs
        return leg < len(legs) and leg_complete(legs[leg], self._dungeon)

    def _confirm_exhaustion(
        self,
        memory: LevelMemory,
        goal: Goal,
        skill_model_decision: ModelSkillDecision | None,
    ) -> _Plan:
        """Record the exhaustion that completes the current leg by waiting.

        The leg then completes on the next observation without a model
        consultation, because nothing is left for exploration to do.
        """
        level = memory.level
        assert level is not None
        wait = self._gate.actions_by_name["MiscDirection.WAIT"]
        return self._skill_plan(
            SkillAction(
                wait.index,
                f"Confirm level ({level.dungeon_number}, {level.dungeon_level}) "
                "exhausted: exploration found no unexplored space, locked door, or "
                "search spot left, which completes the objective leg.",
                ActionRecord(ActionKind.OTHER, memory.position),
                None,
            ),
            goal,
            Skill.EXPLORE_LEVEL,
            SkillSelectionSource.ARBITER,
            None,
            skill_model_decision,
            exhausted_level=level,
        )

    def _plan_goal(self, leg: int, memory: LevelMemory) -> Goal:
        """The planner's goal for this step, applying a requested branch re-arm.

        The re-arm is kept even if a later pause discards this step; it only
        widens the deterministic search budget of an exhausted level.
        """
        planned = self._planner.plan(leg, self._dungeon)
        if planned.rearm:
            memory.rearm_for_branch()
        return planned.goal

    def _navigate(self, memory: LevelMemory, goal: Goal) -> SkillAction | None:
        if not isinstance(goal, STAIR_GOAL_TYPES):
            return None
        level_change = (
            self._gate.level_change_actions.get(goal.target.direction)
            if isinstance(goal, TraverseStairsGoal)
            else None
        )
        return self._navigation.select_action(
            memory, self._gate.actions_by_name, goal, level_change
        )

    def _traversal_permit(
        self, selection: ActionSelection, before: ProjectedObservation
    ) -> TraversalPermit | None:
        """Authorize a proposed level change, or raise why it is refused.

        The shared `level_change_error` predicate judges the recorded
        selection; the level memory must also hold a staircase of that
        direction under the hero with the identity and staircase-pair
        evidence the intent recorded.
        Actions that do not change level need no permit.
        """
        legal = self._environment.legal_actions
        index = selection.action_index
        if not 0 <= index < len(legal):
            return None
        name = legal[index].name
        direction = LEVEL_CHANGE_ACTIONS.get(name)
        if direction is None:
            return None
        memory = self._dungeon.current
        level = memory.level
        assert level is not None
        position = memory.position
        error = level_change_error(
            name,
            selection,
            level_changes_allowed=self._level_changes_allowed,
            level=level,
            position=position,
            prompt_active=before.prompt.active,
            pair_known=memory.pair_known(direction),
        )
        if error is None:
            intent = selection.intent
            assert intent is not None and intent.destination is not None
            if memory.stair_direction(position) is not direction:
                error = f"no remembered {direction.value} staircase under the hero"
            elif intent.destination.stair != memory.identity(position):
                error = "the intent's stair identity is not the remembered one"
            elif intent.destination.pair_known != memory.pair_known(direction):
                error = "the intent's staircase-pair evidence is not the remembered one"
        if error is not None:
            raise ActionGateError(error)
        return TraversalPermit(direction, level, MapCell(*position))

    def _hunger_permit(
        self, selection: ActionSelection, before: ProjectedObservation
    ) -> HungerPermit | None:
        legal = self._environment.legal_actions
        index = selection.action_index
        if not 0 <= index < len(legal) or legal[index].name != EAT_ACTION_NAME:
            return None
        rations = safe_food_rations(before)
        error = hunger_action_error(
            legal[index].name,
            selection,
            hunger=before.player.hunger,
            prompt_active=before.prompt.active,
            safe_ration_available=bool(rations),
        )
        if error is not None:
            raise ActionGateError(error)
        return HungerPermit(rations[0].letter)

    def _on_altar(self, observation: ProjectedObservation) -> bool:
        # NLE overlays the hero on the current square. Remembered S_altar and
        # the look-here text both prevent prayer on an obscured altar.
        return (
            self._dungeon.current.cmap(self._dungeon.current.position) == 27
            or "altar" in observation.message.lower()
        )

    def _prayer_permit(
        self, selection: ActionSelection, before: ProjectedObservation
    ) -> PrayerPermit | None:
        legal = self._environment.legal_actions
        index = selection.action_index
        if not 0 <= index < len(legal) or legal[index].name != PRAY_ACTION_NAME:
            return None
        permit = PrayerPermit(before.player.turn)
        error = prayer_action_error(
            PRAY_ACTION_NAME,
            selection,
            permit=permit,
            turn=before.player.turn,
            hunger=before.player.hunger,
            prompt_active=before.prompt.active,
            ration_available=bool(safe_food_rations(before)),
            prior_prayers=self._prayer_count,
            last_prayer_turn=self._last_prayer_turn,
            on_altar=self._on_altar(before),
        )
        if error is not None:
            raise ActionGateError(error)
        return permit

    def _prompt_permit(
        self, selection: ActionSelection, before: ProjectedObservation
    ) -> PromptPermit | None:
        legal = self._environment.legal_actions
        index = selection.action_index
        if not 0 <= index < len(legal):
            return None
        action = legal[index]
        if (
            selection.skill is Skill.PRAYER
            and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        ):
            pending = self._pending_prayer
            if (
                pending is None
                or self._pending_prayer_step != before.step_index - 1
                or self._prayer_count < 1
                or selection.intent is None
                or selection.intent.prayer != pending
            ):
                raise ActionGateError("yes requires the preceding prayer evidence")
            permit = PromptPermit(YES_COMMAND, PromptKind.PRAYER_CONFIRMATION)
            error = confirmation_answer_error(
                action.command,
                selection,
                prompt_active=before.prompt.active,
                prompt_kind=confirmation_prompt_kind(
                    before.message,
                    single_choice=before.prompt.single_character_choice,
                ),
                permit=permit,
            )
            if error is not None:
                raise ActionGateError(error)
            return permit
        if not self._gate.is_prompt_key(action) and not (
            selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and selection.skill is Skill.HUNGER
        ):
            return None
        offered = item_selection_commands(before)
        error = prompt_response_error(
            action.name,
            action.command,
            selection,
            prompt_active=before.prompt.active,
            item_selection=offered is not None,
            offered_commands=offered or frozenset(),
        )
        if error is not None:
            raise ActionGateError(error)
        return PromptPermit(action.command)

    def _commit_prayer_locked(
        self,
        selection: ActionSelection,
        action: LegalAction,
        before: ProjectedObservation,
        after: ProjectedObservation,
        transition: StepTransition,
    ) -> ActionSelection:
        if action.name == PRAY_ACTION_NAME:
            intent = selection.intent
            assert intent is not None and intent.prayer is not None
            self._prayer_count += 1
            self._last_prayer_turn = before.player.turn
            self._pending_prayer = intent.prayer
            self._pending_prayer_step = before.step_index
        elif (
            selection.skill is Skill.PRAYER
            and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and action.command == YES_COMMAND
        ):
            self._pending_prayer = None
            self._pending_prayer_step = None
            if not transition.terminated and not transition.truncated:
                intent = selection.intent
                assert intent is not None and intent.prayer is not None
                kind = classify_prayer_outcome(after.player.hunger, after.message)
                if kind is None:
                    raise CoordinatorInvariantError(
                        "live prayer confirmation returned no recognized outcome"
                    )
                evidence = replace(
                    intent.prayer,
                    outcome=PrayerOutcome(
                        after.player.turn,
                        after.player.hunger,
                        after.message,
                        kind,
                    ),
                )
                selection = replace(selection, intent=replace(intent, prayer=evidence))
        else:
            self._pending_prayer = None
            self._pending_prayer_step = None
        self._prayer_kill_count += after.message.count("You kill")
        return selection

    def _select_skill(
        self, before: ProjectedObservation, stuck: StuckReason | None, goal: Goal
    ) -> ModelSkillDecision:
        decision = self._model.select_skill(
            before, (goal,), model_selectable_skills(goal), stuck
        )
        if decision.decision.goal != goal:
            raise CoordinatorInvariantError(
                f"model selected unavailable goal {decision.decision.goal.token}"
            )
        return decision

    def _skill_plan(
        self,
        proposal: SkillAction,
        goal: Goal,
        skill: Skill,
        skill_selection: SkillSelectionSource,
        stuck: StuckReason | None,
        skill_model_decision: ModelSkillDecision | None,
        *,
        source: ActionSelectionSource = ActionSelectionSource.DETERMINISTIC_SKILL,
        stuck_consulted: bool = False,
        exhausted_level: LevelKey | None = None,
    ) -> _Plan:
        return _Plan(
            selection=ActionSelection(
                source=source,
                goal=goal,
                skill=skill,
                skill_selection=skill_selection,
                stuck_reason=stuck,
                action_index=proposal.action_index,
                rationale=proposal.rationale,
                intent=(
                    None
                    if proposal.intent is None
                    else replace(proposal.intent, level=self._dungeon.current.level)
                ),
                exhausted_level=exhausted_level,
            ),
            skill_model_decision=skill_model_decision,
            action_model_decision=None,
            record=proposal.record,
            stuck_consulted=stuck_consulted,
        )

    def _fallback_plan(
        self,
        before: ProjectedObservation,
        goal: Goal,
        skill: Skill,
        skill_selection: SkillSelectionSource,
        stuck: StuckReason | None,
        skill_model_decision: ModelSkillDecision | None,
        canceled: Callable[[], bool],
        *,
        stuck_consulted: bool = False,
        exhausted_level: LevelKey | None = None,
    ) -> _Plan | None:
        action_model_decision = self._model.select_action(
            before, self.allowed_actions, goal, skill
        )
        if canceled():
            return None
        decision = action_model_decision.decision
        return _Plan(
            selection=ActionSelection(
                source=ActionSelectionSource.MODEL_FALLBACK,
                goal=goal,
                skill=skill,
                skill_selection=skill_selection,
                stuck_reason=stuck,
                action_index=decision.action_index,
                rationale=decision.rationale,
                intent=None,
                exhausted_level=exhausted_level,
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
        self._goal = selection.goal
        memory = self._dungeon.current
        if plan.stuck_consulted:
            memory.stuck_consult_step = before.step_index
        elif (
            selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
            and selection.stuck_reason is None
        ):
            memory.stuck_consult_step = None
        memory.record(plan.record)
        # The committed step records this decision's exhaustion marker.
        self._exhaustion_undo = None

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
        current = self._dungeon.current if self._dungeon.levels else None
        return CoordinatorSnapshot(
            state=self._state,
            outcome=self._outcome,
            observation=self._observation,
            current_goal=self._goal,
            current_skill=self._current_skill,
            last_error=self._last_error,
            objective_leg=self._leg,
            level=None if current is None else current.level,
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
