import json
from pathlib import Path

import pytest

from nethack_agent.contracts import ContractError
from nethack_agent.tasks import (
    STAIRCASE_TASK,
    ActionProfile,
    NleTask,
    TaskSpec,
    load_task_file,
)
from nethack_agent.traversal import (
    STAIRCASE_OBJECTIVE,
    EnterDungeonLeg,
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
    "task", [NleTask.SCOUT, NleTask.GOLD, NleTask.EAT, NleTask.ORACLE]
)
def test_tasks_without_defined_objectives_are_rejected(task: NleTask) -> None:
    with pytest.raises(ContractError, match="not supported yet"):
        TaskSpec.from_json(
            spec_json(
                environment=task.value,
                objective=Objective((EnterDungeonLeg(2),)).to_json(),
            )
        )


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
