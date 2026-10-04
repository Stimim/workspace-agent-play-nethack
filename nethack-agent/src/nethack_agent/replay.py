"""Deterministic replay of the coordinator's dungeon memory from a stored run.

An `exhausted_level` marker claims that deterministic exploration had nothing
left to do on a level. The evaluator does not trust the claim: it rebuilds the
coordinator's memory from the persisted run and asks the same exploration skill
whether it was exhausted on the observation the step was decided on.

Memory depends on public observations and on what each executed action
attempted. That attempt is re-derived from the step's recorded action, source,
and intent by `derive_action_record`, the same interpretation the skills make
when they propose an action. The objective planner and model re-arms are
replayed in the coordinator's order. Replay assumes every decision that
mutated memory was recorded: evaluation never discards a step mid-decision.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from nethack_agent.decision import (
    LEVEL_CHANGE_ACTIONS,
    ActionSelection,
    ActionSelectionSource,
    DestinationKind,
    Skill,
    StuckReason,
)
from nethack_agent.environment import LegalAction
from nethack_agent.events import StepPayload
from nethack_agent.navigation import (
    MOVE_ACTION_NAMES,
    ActionKind,
    ActionRecord,
    CellKind,
    DungeonMemory,
    LevelMemory,
    locked_door_kick_error,
)
from nethack_agent.observation import ProjectedObservation
from nethack_agent.planner import ObjectivePlanner, leg_complete
from nethack_agent.skills import ExploreLevelSkill
from nethack_agent.tasks import TaskSpec
from nethack_agent.traversal import STAIR_GOAL_TYPES, Goal, LevelKey, StairTarget

_KICK_ACTION_NAME: Final = "Command.KICK"
_SEARCH_ACTION_NAME: Final = "Command.SEARCH"


class ReplayError(ValueError):
    """A stored run cannot be replayed into dungeon memory."""


def stair_target(goal: Goal) -> StairTarget | None:
    """The staircase a goal biases exploration toward; None for explore goals."""
    return goal.target if isinstance(goal, STAIR_GOAL_TYPES) else None


def routine_actions(legal_actions: Iterable[LegalAction]) -> dict[str, LegalAction]:
    """Actions by name as the skills see them: everything but level changes."""
    return {
        action.name: action
        for action in legal_actions
        if action.name not in LEVEL_CHANGE_ACTIONS
    }


def exhaustion_error(
    memory: LevelMemory,
    actions_by_name: dict[str, LegalAction],
    target: StairTarget | None,
    *,
    prompt_active: bool,
) -> str | None:
    """Why exploration was not newly exhausted on `memory`; None when it was.

    The coordinator marks a level exhausted exactly when this holds: no prompt
    is active, the level is not already exhausted at its current knowledge,
    and the exploration skill reports `search_exhausted`.
    """
    if prompt_active:
        return "exploration does not run while a prompt is active"
    if memory.exhausted:
        return "the level was already exhausted and nothing new is known"
    result = ExploreLevelSkill().select_action(memory, actions_by_name, target)
    if result.action is not None:
        return "deterministic exploration still had an action"
    if result.stuck is not StuckReason.SEARCH_EXHAUSTED:
        assert result.stuck is not None
        return f"exploration was stuck for another reason ({result.stuck.value})"
    return None


def derive_action_record(
    selection: ActionSelection, action_name: str, memory: LevelMemory
) -> ActionRecord:
    """What an executed action attempted, from its recorded selection.

    `memory` holds the observation the action was decided on. The result is
    the record the proposing skill made: a stair use traverses; a route step
    moves toward its path's last cell (opening a closed door in the way); an
    in-place attack moves into its target; kicks and searches act on their
    destination; everything without a skill intent is `other`.
    """
    origin = memory.position
    if action_name in LEVEL_CHANGE_ACTIONS:
        return ActionRecord(ActionKind.TRAVERSE, origin)
    intent = selection.intent
    if selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL or (
        intent is None
    ):
        return ActionRecord(ActionKind.OTHER, origin)
    destination = intent.destination
    if intent.path is not None:
        assert destination is not None
        step = (intent.path[0].x, intent.path[0].y)
        goal = (intent.path[-1].x, intent.path[-1].y)
        search_spot = (
            (destination.x, destination.y)
            if destination.kind is DestinationKind.SEARCH_SPOT
            else None
        )
        if memory.kind(step) is CellKind.CLOSED_DOOR:
            return ActionRecord(
                ActionKind.OPEN_DOOR, origin, step, None, goal, search_spot
            )
        monster = memory.monsters.get(step)
        return ActionRecord(
            ActionKind.MOVE,
            origin,
            step,
            None if monster is None else monster.glyph,
            goal,
            search_spot,
        )
    if intent.attack_target is not None:
        point = (intent.attack_target.x, intent.attack_target.y)
        monster = memory.monsters.get(point)
        return ActionRecord(
            ActionKind.MOVE, origin, point, None if monster is None else monster.glyph
        )
    if destination is None:
        return ActionRecord(ActionKind.OTHER, origin)
    cell = (destination.x, destination.y)
    if action_name == _KICK_ACTION_NAME:
        return ActionRecord(ActionKind.KICK, origin, cell)
    if destination.kind is DestinationKind.LOCKED_DOOR:
        return ActionRecord(ActionKind.KICK_DIRECTION, origin, cell)
    if action_name == _SEARCH_ACTION_NAME:
        if destination.kind is DestinationKind.SEARCH_SPOT:
            return ActionRecord(ActionKind.SEARCH, origin, search_spot=cell)
        return ActionRecord(ActionKind.WAIT, origin)
    if action_name == "MiscDirection.WAIT" and destination.kind is DestinationKind.REST:
        return ActionRecord(ActionKind.REST, origin)
    return ActionRecord(ActionKind.OTHER, origin)


def kick_action_error(
    action_name: str, selection: ActionSelection, memory: LevelMemory | None
) -> str | None:
    """Audit exactly the safety predicate used by deterministic door forcing."""
    destination = None if selection.intent is None else selection.intent.destination
    directed = (
        destination is not None and destination.kind is DestinationKind.LOCKED_DOOR
    )
    if action_name != _KICK_ACTION_NAME:
        if memory is None or memory.pending_kick is None:
            return None
        if action_name not in MOVE_ACTION_NAMES.values():
            return None
    if (
        memory is None
        or not directed
        or selection.skill is not Skill.EXPLORE_LEVEL
        or selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
    ):
        return "kicking requires deterministic locked-gate evidence"
    door = (destination.x, destination.y)
    error = locked_door_kick_error(
        memory, door, memory.position, stair_target(selection.goal)
    )
    if error is not None:
        return error
    if action_name != _KICK_ACTION_NAME and (
        memory.pending_kick != door
        or MOVE_ACTION_NAMES.get(
            (door[0] - memory.position[0], door[1] - memory.position[1])
        )
        != action_name
    ):
        return "kick direction does not match the pending gate"
    return None


class ExplorationReplay:
    """Rebuild dungeon memory step by step and validate exhaustion markers.

    `explored` holds the levels whose markers the replay confirmed, the
    evidence an explore_dungeon objective is judged by.
    """

    def __init__(
        self,
        task: TaskSpec,
        legal_actions: tuple[LegalAction, ...],
        initial: ProjectedObservation,
    ) -> None:
        self._planner = ObjectivePlanner(task.objective)
        self._actions = routine_actions(legal_actions)
        self._dungeon = DungeonMemory()
        self._dungeon.observe(initial)
        self._decided_on = initial
        # The coordinator starts on leg 0 and advances only after a step.
        self._leg = 0
        self._first_step = True
        self._ended = False
        self.explored: set[LevelKey] = set()

    def step(self, payload: StepPayload) -> str | None:
        """Fold one recorded step; return why its marker is invalid, if it is."""
        if self._ended:
            raise ReplayError("a step follows the episode's terminal step")
        memory = self._dungeon.current
        goal = self._plan(memory)
        problem = None
        marker = payload.selection.exhausted_level
        if marker is not None:
            problem = (
                f"it names {marker} but the step was decided on {memory.level}"
                if marker != memory.level
                else exhaustion_error(
                    memory,
                    self._actions,
                    stair_target(goal),
                    prompt_active=self._decided_on.prompt.active,
                )
            )
            if problem is None:
                memory.mark_exhausted()
                self.explored.add(marker)
                if not self._leg_complete():
                    self._plan(memory)
        decision = payload.skill_decision
        # Only the first step consults the model at the start; any later skill
        # decision is a stuck consultation, whose explore_level choice re-arms.
        if (
            not self._first_step
            and decision is not None
            and decision.skill is Skill.EXPLORE_LEVEL
        ):
            memory.rearm()
        self._first_step = False
        if problem is None:
            problem = kick_action_error(payload.action.name, payload.selection, memory)
        memory.record(
            derive_action_record(payload.selection, payload.action.name, memory)
        )
        if payload.terminated or payload.truncated:
            self._ended = True
            return problem
        self._dungeon.observe(payload.observation)
        self._decided_on = payload.observation
        self._leg = self._planner.advance(self._leg, self._dungeon)
        return problem

    def _plan(self, memory: LevelMemory) -> Goal:
        planned = self._planner.plan(self._leg, self._dungeon)
        if planned.rearm:
            memory.rearm_for_branch()
        return planned.goal

    def _leg_complete(self) -> bool:
        legs = self._planner.legs
        return self._leg < len(legs) and leg_complete(legs[self._leg], self._dungeon)
