"""Typed task specifications: the NLE task, action profile, and objective of a run.

A run executes one `TaskSpec` (ADR 0004). The NLE task decides the reward,
NLE's own end states, and NLE's option choice; the action profile is the
code-defined action tuple handed to NLE's `actions=` argument; the objective
(`traversal.Objective`) is what the coordinator pursues.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Final, Self

from nle import nethack
from nle.env.tasks import TASK_ACTIONS

from nethack_agent.contracts import (
    ContractError,
    enum_value,
    load_json_object,
    object_value,
)
from nethack_agent.traversal import (
    STAIRCASE_OBJECTIVE,
    ExploreDungeonLeg,
    FindOracleLeg,
    Objective,
)


class NleTask(Enum):
    """NLE 1.3.0 Gymnasium task ids a run may execute."""

    STAIRCASE = "NetHackStaircase-v0"
    SCORE = "NetHackScore-v0"
    SCOUT = "NetHackScout-v0"
    GOLD = "NetHackGold-v0"
    EAT = "NetHackEat-v0"
    ORACLE = "NetHackOracle-v0"

    @property
    def options(self) -> tuple[str, ...]:
        """NLE's own option choice for this task, plus an explicit `autoopen`.

        NLE applies a task's option choice only when `options` is None, and the
        adapter always passes options, so the choice is reproduced here.
        `NetHackGold.__init__` swaps `pickup_types` to `$`. NLE's default tuple
        does not name `autoopen`, although vanilla NetHack defaults it on; it is
        pinned so navigation does not depend on an upstream default.
        """
        options = nethack.NETHACKOPTIONS
        if self is NleTask.GOLD:
            options = tuple(
                "pickup_types:$" if option.startswith("pickup_types") else option
                for option in options
            )
        return (*options, "autoopen")


class ActionRole(Enum):
    """Static policy role of one action in an action profile."""

    ROUTINE = "routine"
    HUNGER = "hunger"
    PROMPT_KEY = "prompt_key"


class ActionProfile(Enum):
    """A named, code-defined tuple of NLE action members."""

    # NLE's `TASK_ACTIONS`: the 23 actions every task except Challenge uses.
    NLE_TASK_ACTIONS = "nle-task-actions"
    # The task actions plus ESC and every a-z/A-Z inventory-selection key.
    NLE_HUNGER_ACTIONS = "nle-hunger-actions"

    @property
    def actions(self) -> tuple[IntEnum, ...]:
        return _PROFILE_ACTIONS[self]

    def role(self, action: IntEnum) -> ActionRole:
        command = int(action)
        if command in _PROFILE_PROMPT_KEY_COMMANDS[self]:
            return ActionRole.PROMPT_KEY
        if command == int(nethack.Command.EAT):
            return ActionRole.HUNGER
        return ActionRole.ROUTINE


_TASK_ACTIONS: Final = tuple(TASK_ACTIONS)
_TASK_COMMANDS: Final = frozenset(int(action) for action in _TASK_ACTIONS)
_COMMAND_BY_VALUE: Final = {int(action): action for action in nethack.Command}
_INVENTORY_LETTER_COMMANDS: Final = tuple(
    ord(letter) for letter in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_HUNGER_ADDITIONS: Final = (
    nethack.Command.ESC,
    *(
        _COMMAND_BY_VALUE[command]
        for command in _INVENTORY_LETTER_COMMANDS
        if command not in _TASK_COMMANDS
    ),
)
_HUNGER_ACTIONS: Final = (*_TASK_ACTIONS, *_HUNGER_ADDITIONS)

_PROFILE_ACTIONS: Final[dict[ActionProfile, tuple[IntEnum, ...]]] = {
    ActionProfile.NLE_TASK_ACTIONS: _TASK_ACTIONS,
    ActionProfile.NLE_HUNGER_ACTIONS: _HUNGER_ACTIONS,
}
_PROFILE_PROMPT_KEY_COMMANDS: Final[dict[ActionProfile, frozenset[int]]] = {
    ActionProfile.NLE_TASK_ACTIONS: frozenset(),
    ActionProfile.NLE_HUNGER_ACTIONS: frozenset(
        int(action) for action in _HUNGER_ADDITIONS
    ),
}
PROMPT_KEY_ACTION_NAMES: Final = frozenset(
    f"{type(action).__name__}.{action.name}" for action in _HUNGER_ADDITIONS
)

# Tasks whose objectives have behavior. Gold and Oracle legs are typed below
# but are rejected until the planner and coordinator pursue them.
_SUPPORTED_TASKS: Final = frozenset(
    {NleTask.STAIRCASE, NleTask.SCORE, NleTask.SCOUT, NleTask.EAT}
)
# Each task-progression task's single leg type and action profile (ADR 0004
# section 8). Eat needs the hunger profile to answer its item prompt, and
# Oracle's 5,000-step cap exceeds the hunger horizon; Scout and Gold need
# nothing beyond NLE's actions.
_TASK_PROGRESSION: Final[
    dict[NleTask, tuple[type[ExploreDungeonLeg] | type[FindOracleLeg], ActionProfile]]
] = {
    NleTask.SCOUT: (ExploreDungeonLeg, ActionProfile.NLE_TASK_ACTIONS),
    NleTask.GOLD: (ExploreDungeonLeg, ActionProfile.NLE_TASK_ACTIONS),
    NleTask.EAT: (ExploreDungeonLeg, ActionProfile.NLE_HUNGER_ACTIONS),
    NleTask.ORACLE: (FindOracleLeg, ActionProfile.NLE_HUNGER_ACTIONS),
}


@dataclass(frozen=True, slots=True)
class TaskSpec:
    environment: NleTask
    action_profile: ActionProfile
    objective: Objective

    def __post_init__(self) -> None:
        if not isinstance(self.environment, NleTask):
            raise TypeError("task environment must be an NleTask")
        if not isinstance(self.action_profile, ActionProfile):
            raise TypeError("task action_profile must be an ActionProfile")
        if not isinstance(self.objective, Objective):
            raise TypeError("task objective must be an Objective")
        if self.environment not in _SUPPORTED_TASKS:
            raise ContractError(
                f"{self.environment.value} objectives are not supported yet"
            )
        if (
            self.environment is NleTask.STAIRCASE
            and self.objective != STAIRCASE_OBJECTIVE
        ):
            raise ContractError(
                f"{NleTask.STAIRCASE.value} allows only the single objective leg "
                "stand_on_stairs(down, any)"
            )
        progression = _TASK_PROGRESSION.get(self.environment)
        if progression is None:
            for leg in self.objective.legs:
                if isinstance(leg, ExploreDungeonLeg | FindOracleLeg):
                    tasks = " and ".join(
                        task.value
                        for task, (leg_type, _) in _TASK_PROGRESSION.items()
                        if isinstance(leg, leg_type)
                    )
                    raise ContractError(
                        f"a {leg.kind.value} leg is valid only on {tasks}"
                    )
            return
        leg_type, profile = _TASK_PROGRESSION[self.environment]
        legs = self.objective.legs
        if len(legs) != 1 or not isinstance(legs[0], leg_type):
            raise ContractError(
                f"{self.environment.value} requires exactly one "
                f"{leg_type.kind.value} leg"
            )
        if self.action_profile is not profile:
            raise ContractError(
                f"{self.environment.value} requires action profile {profile.value}"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "environment": self.environment.value,
            "action_profile": self.action_profile.value,
            "objective": self.objective.to_json(),
        }

    def canonical_json(self) -> str:
        """The stored form: sorted keys, no insignificant whitespace."""
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: object, name: str = "task") -> Self:
        payload = object_value(
            value, name, {"environment", "action_profile", "objective"}
        )
        return cls(
            environment=enum_value(
                payload["environment"], f"{name} environment", NleTask
            ),
            action_profile=enum_value(
                payload["action_profile"], f"{name} action_profile", ActionProfile
            ),
            objective=Objective.from_json(payload["objective"], f"{name} objective"),
        )


# Milestone 1's task: stand on any `>` on NetHackStaircase-v0, never changing
# level.
STAIRCASE_TASK: Final = TaskSpec(
    NleTask.STAIRCASE, ActionProfile.NLE_TASK_ACTIONS, STAIRCASE_OBJECTIVE
)


def load_task_file(path: Path) -> TaskSpec:
    """Read one strict task-spec JSON object from `path`."""
    text = Path(path).read_text(encoding="utf-8")
    return TaskSpec.from_json(load_json_object(text, f"task file {path}"))
