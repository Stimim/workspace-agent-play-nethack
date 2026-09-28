import json
from pathlib import Path

import pytest
from nle import nethack
from nle.env.tasks import TASK_ACTIONS

from nethack_agent.contracts import ContractError
from nethack_agent.tasks import (
    STAIRCASE_TASK,
    ActionProfile,
    ActionRole,
    NleTask,
    TaskSpec,
    load_task_file,
)
from nethack_agent.traversal import (
    STAIRCASE_OBJECTIVE,
    EnterDungeonLeg,
    ExploreDungeonLeg,
    FindOracleLeg,
    LevelKey,
    Objective,
    ReachLevelLeg,
)

ROUND_TRIP = Objective((ReachLevelLeg(LevelKey(0, 3)), ReachLevelLeg(LevelKey(0, 1))))


def spec_json(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "environment": "NetHackScore-v0",
        "action_profile": "nle-task-actions",
        "objective": ROUND_TRIP.to_json(),
    }
    payload.update(changes)
    return payload


def test_staircase_task_round_trips_through_its_canonical_json() -> None:
    stored = STAIRCASE_TASK.canonical_json()

    assert TaskSpec.from_json(json.loads(stored)) == STAIRCASE_TASK
    assert json.loads(stored) == {
        "environment": "NetHackStaircase-v0",
        "action_profile": "nle-task-actions",
        "objective": {
            "legs": [
                {
                    "kind": "stand_on_stairs",
                    "target": {
                        "direction": "down",
                        "connection": "any",
                        "dungeon_number": None,
                    },
                }
            ]
        },
    }


def test_hunger_profile_adds_only_esc_and_deduplicated_inventory_keys() -> None:
    profile = ActionProfile.NLE_HUNGER_ACTIONS
    commands = tuple(int(action) for action in profile.actions)
    task_commands = tuple(int(action) for action in TASK_ACTIONS)

    assert commands[: len(task_commands)] == task_commands
    assert len(commands) == len(set(commands))
    assert int(nethack.Command.ESC) in commands
    assert set(map(ord, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")) <= set(
        commands
    )
    assert all(
        profile.role(action) is ActionRole.PROMPT_KEY
        for action in profile.actions[len(task_commands) :]
    )
    movement = next(action for action in profile.actions if int(action) == ord("h"))
    assert profile.role(movement) is ActionRole.ROUTINE
    eat = next(action for action in profile.actions if int(action) == ord("e"))
    assert profile.role(eat) is ActionRole.HUNGER


def test_score_task_accepts_any_objective_legs() -> None:
    task = TaskSpec.from_json(spec_json())

    assert task.environment is NleTask.SCORE
    assert task.objective == ROUND_TRIP
    assert TaskSpec.from_json(task.to_json()) == task


@pytest.mark.parametrize(
    "objective",
    [
        Objective((ReachLevelLeg(LevelKey(0, 3)),)),
        Objective((*STAIRCASE_OBJECTIVE.legs, *STAIRCASE_OBJECTIVE.legs)),
    ],
)
def test_staircase_task_rejects_every_other_objective(objective: Objective) -> None:
    with pytest.raises(ContractError, match="allows only"):
        TaskSpec(NleTask.STAIRCASE, ActionProfile.NLE_TASK_ACTIONS, objective)


@pytest.mark.parametrize(
    ("task", "profile", "objective"),
    [
        (
            NleTask.GOLD,
            ActionProfile.NLE_TASK_ACTIONS,
            Objective((ExploreDungeonLeg(3),)),
        ),
        (
            NleTask.ORACLE,
            ActionProfile.NLE_HUNGER_ACTIONS,
            Objective((FindOracleLeg(),)),
        ),
        (
            NleTask.GOLD,
            ActionProfile.NLE_TASK_ACTIONS,
            Objective((EnterDungeonLeg(2),)),
        ),
    ],
)
def test_tasks_without_behavior_are_rejected(
    task: NleTask, profile: ActionProfile, objective: Objective
) -> None:
    with pytest.raises(ContractError, match=f"{task.value} .*not supported yet"):
        TaskSpec.from_json(
            {
                "environment": task.value,
                "action_profile": profile.value,
                "objective": objective.to_json(),
            }
        )


EXPLORE_THREE = Objective((ExploreDungeonLeg(3),))


@pytest.mark.parametrize(
    ("task", "profile"),
    [
        (NleTask.SCOUT, ActionProfile.NLE_TASK_ACTIONS),
        (NleTask.EAT, ActionProfile.NLE_HUNGER_ACTIONS),
    ],
)
def test_exploration_tasks_take_one_explore_dungeon_leg_and_their_profile(
    task: NleTask, profile: ActionProfile
) -> None:
    spec = TaskSpec(task, profile, EXPLORE_THREE)

    assert TaskSpec.from_json(json.loads(spec.canonical_json())) == spec
    other = next(item for item in ActionProfile if item is not profile)
    with pytest.raises(ContractError, match=f"requires action profile {profile.value}"):
        TaskSpec(task, other, EXPLORE_THREE)
    for objective in (
        ROUND_TRIP,
        Objective((ExploreDungeonLeg(3), ExploreDungeonLeg(4))),
        Objective((ExploreDungeonLeg(3), ReachLevelLeg(LevelKey(0, 1)))),
    ):
        with pytest.raises(ContractError, match="exactly one explore_dungeon leg"):
            TaskSpec(task, profile, objective)


@pytest.mark.parametrize("task", [NleTask.SCORE, NleTask.STAIRCASE])
def test_explore_dungeon_legs_are_rejected_on_other_tasks(task: NleTask) -> None:
    with pytest.raises(ContractError, match="explore_dungeon|allows only"):
        TaskSpec(task, ActionProfile.NLE_TASK_ACTIONS, EXPLORE_THREE)


@pytest.mark.parametrize("task", [NleTask.SCORE, NleTask.SCOUT, NleTask.EAT])
def test_find_oracle_legs_are_rejected_on_other_tasks(task: NleTask) -> None:
    with pytest.raises(ContractError, match="find_oracle|explore_dungeon"):
        TaskSpec(task, ActionProfile.NLE_TASK_ACTIONS, Objective((FindOracleLeg(),)))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (spec_json(environment="NetHackChallenge-v0"), "environment must be one of"),
        (spec_json(action_profile="full-keyboard"), "action_profile must be one of"),
        (spec_json(objective={"legs": []}), "1 to 8 legs"),
        (spec_json(character="val-dwa-law"), "unexpected"),
        ({"environment": "NetHackScore-v0"}, "missing"),
        (["NetHackScore-v0"], "must be an object"),
    ],
)
def test_malformed_task_specs_are_rejected(payload: object, message: str) -> None:
    with pytest.raises(ContractError, match=message):
        TaskSpec.from_json(payload)


def test_task_file_rejects_duplicate_keys(tmp_path: Path) -> None:
    good = tmp_path / "task.json"
    good.write_text(json.dumps(spec_json()), encoding="utf-8")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"environment": "NetHackScore-v0", "environment": "NetHackStaircase-v0",'
        ' "action_profile": "nle-task-actions",'
        f' "objective": {json.dumps(ROUND_TRIP.to_json())}}}',
        encoding="utf-8",
    )

    assert load_task_file(good) == TaskSpec.from_json(spec_json())
    with pytest.raises(ContractError, match="duplicate object key"):
        load_task_file(duplicate)
