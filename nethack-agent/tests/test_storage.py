import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nethack_agent.contracts import ContractError
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DecisionMetrics,
    DestinationKind,
    IntentDestination,
    MapCell,
    RunOutcome,
    RunState,
    Skill,
    SkillDecision,
    SkillSelectionSource,
)
from nethack_agent.environment import (
    LegalAction,
    NleEnvironment,
    ScenarioConfig,
    SeedSet,
)
from nethack_agent.events import (
    AgentErrorPayload,
    DecisionFailureTrace,
    ErrorPhase,
    EventKind,
    RunPausedPayload,
    RunResumedPayload,
    RunStartedPayload,
    RunStoppedPayload,
    StepPayload,
)
from nethack_agent.model import DecisionAttemptDiagnostic
from nethack_agent.observation import ObservationProjector
from nethack_agent.storage import (
    RunStateConflictError,
    RunStore,
    StoredEventError,
)
from nethack_agent.tasks import STAIRCASE_TASK, ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    UNKNOWN_STAIR,
    IdentityEvidence,
    LevelKey,
    Objective,
    ReachLevelLeg,
    StairConnection,
    StairDirection,
    StairIdentity,
    StairIdentityKind,
    StairTarget,
    TraverseStairsGoal,
)


def create_stored_run(  # type: ignore[no-untyped-def]
    store: RunStore, tmp_path: Path, task: TaskSpec = STAIRCASE_TASK
):
    config = ScenarioConfig(
        seed=6, artifact_directory=tmp_path / "artifacts", task=task
    )
    return store.create_run(
        config,
        SeedSet.derive(config.seed),
        character="val-dwa-law",
        model="test-model",
        policy_version="test-policy",
        knowledge_version="test-knowledge",
        nle_version="1.3.0",
        ollama_num_ctx=8192,
    )


def event_fixtures(tmp_path: Path):  # type: ignore[no-untyped-def]
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path / "episode")
    )
    try:
        observation = ObservationProjector().project(environment.reset(), step_index=0)
        action = environment.legal_actions[2]
        metrics = DecisionMetrics(3, 2, 4.0, False)
        selection = ActionSelection(
            ActionSelectionSource.DETERMINISTIC_SKILL,
            STAND_ON_DOWNSTAIRS,
            Skill.EXPLORE_LEVEL,
            SkillSelectionSource.ARBITER,
            None,
            action.index,
            "Explore toward unexplored space.",
            # Attacking the monster that blocks a route further ahead.
            ActionIntent(
                IntentDestination(DestinationKind.FRONTIER, 7, 4),
                MapCell(4, 2),
                (MapCell(4, 2), MapCell(5, 3), MapCell(6, 4), MapCell(7, 4)),
            ),
        )
        return (
            RunStartedPayload(
                observation,
                environment.legal_actions,
                STAND_ON_DOWNSTAIRS,
                None,
            ),
            RunResumedPayload(),
            RunPausedPayload(),
            StepPayload(
                selection=selection,
                skill_decision=SkillDecision(
                    STAND_ON_DOWNSTAIRS,
                    Skill.STAIRCASE_NAVIGATION,
                    "Use deterministic navigation.",
                ),
                skill_metrics=metrics,
                action_decision=None,
                action_metrics=None,
                action=action,
                reward=0.0,
                terminated=False,
                truncated=False,
                end_status=0,
                is_ascended=False,
                outcome=None,
                observation=observation,
            ),
            AgentErrorPayload(
                error="invalid after repair",
                state=RunState.PAUSED,
                phase=ErrorPhase.ADVANCE,
                decision_failure=DecisionFailureTrace(
                    "invalid after repair",
                    (
                        DecisionAttemptDiagnostic(
                            "DecisionError: bad payload",
                            "{}",
                            3,
                            2,
                            4.0,
                            None,
                        ),
                    ),
                    metrics,
                ),
            ),
            RunStoppedPayload(RunState.PAUSED),
        )
    finally:
        environment.close()


def test_every_event_variant_round_trips_semantically_after_store_reopen(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runs.sqlite3"
    store = RunStore(database)
    run = create_stored_run(store, tmp_path)
    payloads = event_fixtures(tmp_path)

    written = tuple(store.append_event(run.id, payload) for payload in payloads)
    store.update_run(
        run.id,
        state=RunState.TERMINAL,
        outcome=RunOutcome.TASK_SUCCESS,
        ttyrec_path="episode.ttyrec3.bz2",
    )

    reopened = RunStore(database)
    persisted = reopened.get_run(run.id)
    events = reopened.events_after(run.id)

    assert persisted.state is RunState.TERMINAL
    assert persisted.outcome is RunOutcome.TASK_SUCCESS
    assert persisted.ttyrec_path == "episode.ttyrec3.bz2"
    assert [event.sequence for event in events] == list(range(len(payloads)))
    assert [event.kind for event in events] == list(EventKind)
    assert [event.payload for event in events] == list(payloads)
    assert reopened.events_after(run.id, written[0].sequence) == written[1:]
    assert [event.to_json()["kind"] for event in events] == [
        kind.value for kind in EventKind
    ]


def test_typed_event_payload_rejects_semantically_inconsistent_data(
    tmp_path: Path,
) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    serialized = step.to_json()
    serialized["terminated"] = True

    with pytest.raises(ContractError, match="terminal step must include an outcome"):
        StepPayload.from_json(serialized)

    # Only an objective completed while NLE's episode continues is an outcome
    # without termination; a terminal NLE step keeps NLE's outcome.
    completed = step.to_json()
    completed["outcome"] = "objective_complete"
    assert StepPayload.from_json(completed).outcome is RunOutcome.OBJECTIVE_COMPLETE
    completed["truncated"] = True
    with pytest.raises(ContractError, match="only while NLE's episode continues"):
        StepPayload.from_json(completed)
    success = step.to_json()
    success["outcome"] = "task_success"
    with pytest.raises(ContractError, match="nonterminal step must not"):
        StepPayload.from_json(success)

    # The arbiter may override the model's skill; a model-selected step may not.
    model_selected = step.to_json()
    model_selected["selection"]["skill_selection"] = "model"  # type: ignore[index]
    model_selected["selection"]["stuck_reason"] = "search_exhausted"  # type: ignore[index]
    with pytest.raises(ContractError, match="skill decision does not match"):
        StepPayload.from_json(model_selected)

    unexplained = step.to_json()
    unexplained["selection"]["skill_selection"] = "model"  # type: ignore[index]
    with pytest.raises(ContractError, match="only after exploration is stuck"):
        StepPayload.from_json(unexplained)


def test_a_recorded_level_change_must_be_a_staircase_traversal(
    tmp_path: Path,
) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    down = LegalAction(18, ord(">"), "MiscDirection.DOWN")
    main_down = TraverseStairsGoal(
        StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
    )
    intent = ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 7, 4, UNKNOWN_STAIR),
        None,
        None,
        LevelKey(0, 1),
    )
    selection = replace(
        step.selection,
        action_index=18,
        goal=main_down,
        skill=Skill.STAIRCASE_NAVIGATION,
        intent=intent,
    )
    traversal = replace(
        step, selection=selection, action=down, skill_decision=None, skill_metrics=None
    )
    assert StepPayload.from_json(traversal.to_json()) == traversal

    # The legacy staircase goal never changes level.
    standing = traversal.to_json()
    standing["selection"]["goal"] = "stand_on_downstairs"  # type: ignore[index]
    with pytest.raises(ContractError, match="step level change is invalid"):
        StepPayload.from_json(standing)
    # Nor does a routed step or a step without the staircase's identity.
    routed = traversal.to_json()
    routed["selection"]["intent"]["path"] = [{"x": 7, "y": 4}]  # type: ignore[index]
    with pytest.raises(ContractError, match="in-place intent"):
        StepPayload.from_json(routed)
    unidentified = traversal.to_json()
    del unidentified["selection"]["intent"]["destination"]["stair"]  # type: ignore[index]
    with pytest.raises(ContractError, match="in-place intent"):
        StepPayload.from_json(unidentified)


def test_step_intent_and_path_are_optional_for_legacy_steps(tmp_path: Path) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    serialized = step.to_json()
    assert serialized["selection"]["intent"] == {  # type: ignore[index]
        "destination": {"kind": "frontier", "x": 7, "y": 4},
        "attack_target": {"x": 4, "y": 2},
        "path": [
            {"x": 4, "y": 2},
            {"x": 5, "y": 3},
            {"x": 6, "y": 4},
            {"x": 7, "y": 4},
        ],
        "level": None,
    }
    assert StepPayload.from_json(json.loads(json.dumps(serialized))) == step

    # Steps persisted before intents existed have no field: no intent is known
    # and none is invented. Absent and null read the same way.
    legacy = step.to_json()
    del legacy["selection"]["intent"]  # type: ignore[attr-defined]
    restored = StepPayload.from_json(legacy)
    assert restored.selection.intent is None
    assert restored.to_json()["selection"]["intent"] is None  # type: ignore[index]
    assert StepPayload.from_json(restored.to_json()) == restored

    # Intents persisted before routes were recorded keep their targets; the
    # route is unknown, not empty.
    pathless = step.to_json()
    del pathless["selection"]["intent"]["path"]  # type: ignore[index]
    restored = StepPayload.from_json(pathless)
    assert restored.selection.intent == ActionIntent(
        IntentDestination(DestinationKind.FRONTIER, 7, 4), MapCell(4, 2), None
    )
    assert restored.to_json()["selection"]["intent"]["path"] is None  # type: ignore[index]
    assert StepPayload.from_json(restored.to_json()) == restored

    # Intents persisted before levels were recorded read with an unknown level.
    levelless = step.to_json()
    del levelless["selection"]["intent"]["level"]  # type: ignore[index]
    assert StepPayload.from_json(levelless) == step


def test_stair_intents_record_identity_and_level(tmp_path: Path) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    stair = StairIdentity(StairIdentityKind.MAIN, 0, IdentityEvidence.ARRIVAL)
    intent = ActionIntent(
        IntentDestination(DestinationKind.UPSTAIRS, 7, 4, stair, False),
        None,
        None,
        LevelKey(0, 2),
    )
    recorded = replace(step, selection=replace(step.selection, intent=intent))
    serialized = recorded.to_json()
    assert serialized["selection"]["intent"] == {  # type: ignore[index]
        "destination": {
            "kind": "upstairs",
            "x": 7,
            "y": 4,
            "stair": {"kind": "main", "dungeon_number": 0, "evidence": "arrival"},
            "pair_known": False,
        },
        "attack_target": None,
        "path": None,
        "level": {"dungeon_number": 0, "dungeon_level": 2},
    }
    assert StepPayload.from_json(json.loads(json.dumps(serialized))) == recorded

    # Stair intents stored before identities or pair evidence were recorded
    # read as unknown (null), never as an inferred identity or pair.
    legacy = recorded.to_json()
    del legacy["selection"]["intent"]["destination"]["stair"]  # type: ignore[index]
    del legacy["selection"]["intent"]["destination"]["pair_known"]  # type: ignore[index]
    restored = StepPayload.from_json(legacy)
    assert restored.selection.intent is not None
    assert restored.selection.intent.destination == IntentDestination(
        DestinationKind.UPSTAIRS, 7, 4
    )
    destination = restored.to_json()["selection"]["intent"]["destination"]  # type: ignore[index]
    assert destination["stair"] is None  # type: ignore[index]
    assert destination["pair_known"] is None  # type: ignore[index]


_DESTINATION = {"kind": "frontier", "x": 3, "y": 1}


def _destination(**changes: object) -> dict[str, object]:
    return {"destination": {**_DESTINATION, **changes}, "attack_target": None}


def _attack(x: object, y: object) -> dict[str, object]:
    return {"destination": None, "attack_target": {"x": x, "y": y}}


def _routed(
    *cells: tuple[object, object], attack: object = None, **changes: object
) -> dict[str, object]:
    return {
        **_destination(**changes),
        "attack_target": attack,
        "path": [{"x": x, "y": y} for x, y in cells],
    }


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        (
            "intent",
            {"destination": None, "attack_target": None},
            "requires a destination or an attack target",
        ),
        ("intent", {"destination": _DESTINATION}, r"missing \['attack_target'\]"),
        ("intent", {**_destination(), "x": 1}, r"unexpected \['x'\]"),
        ("intent", _destination(kind="stairs"), "destination kind must be one of"),
        (
            "intent",
            {"destination": {"x": 3, "y": 1}, "attack_target": None},
            r"missing \['kind'\]",
        ),
        ("intent", _attack(-1, 1), "attack_target x must be at least 0"),
        ("intent", _attack(True, 1), "attack_target x must be an integer"),
        ("intent", _destination(y="1"), "destination y must be an integer"),
        ("intent", [3, 1], "intent must be an object"),
        ("intent", _destination(x=79), "outside the observation map"),
        ("intent", _attack(0, 21), "outside the observation map"),
        ("intent", _routed((1, 1), (3, 1)), "must be adjacent in order"),
        ("intent", _routed((1, 1), (2, 1)), "must end at the destination"),
        ("intent", _routed((3, 21), (3, 20), y=20), "outside the observation map"),
        (
            "intent",
            {**_routed((4, 2)), "destination": None, "attack_target": {"x": 4, "y": 2}},
            "path requires a destination",
        ),
        (
            "intent",
            {**_routed((3, 1)), "path": [{"x": 3, "y": 1, "z": 0}]},
            r"unexpected \['z'\]",
        ),
        ("intent", _routed(), "must have 1 to 1659 cells"),
        ("intent", {**_routed(), "path": {"x": 3, "y": 1}}, "path must be an array"),
        ("intent", _routed(*[(3, 1)] * 1660), "at most 1659 cells"),
        ("intent", _routed((3, 1), (2, 1), (3, 1)), "must not revisit a cell"),
        ("intent", _routed((True, 1), (3, 1)), "path cell x must be an integer"),
        (
            "intent",
            _routed((1, 3), (2, 2), kind="locked_door"),
            "end orthogonally beside the door",
        ),
        (
            "intent",
            _routed((2, 1), (3, 1), kind="locked_door"),
            "end orthogonally beside the door",
        ),
        (
            "intent",
            _routed((2, 1), (3, 1), attack={"x": 2, "y": 2}),
            "must start at the attack target",
        ),
        (
            "intent",
            _destination(
                stair={"kind": "main", "dungeon_number": 0, "evidence": "arrival"}
            ),
            "only a stair destination",
        ),
        (
            "intent",
            _destination(
                kind="downstairs",
                stair={"kind": "unknown", "dungeon_number": 0, "evidence": None},
            ),
            "no evidence or dungeon_number",
        ),
        (
            "intent",
            _destination(pair_known=True),
            "only a stair destination records pair_known",
        ),
        (
            "intent",
            _destination(kind="upstairs", pair_known=1),
            "pair_known must be a boolean",
        ),
        (
            "intent",
            {**_destination(), "level": {"dungeon_number": 0, "dungeon_level": 0}},
            "intent level dungeon_level must be at least 1",
        ),
        ("target", _DESTINATION, r"unexpected \['target'\]"),
        ("source", "deterministic_prompt", "only deterministic skill selections"),
    ],
)
def test_malformed_step_intent_is_rejected(
    tmp_path: Path, key: str, value: object, match: str
) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    serialized = step.to_json()
    serialized["selection"][key] = value  # type: ignore[index]

    with pytest.raises(ContractError, match=match):
        StepPayload.from_json(serialized)


def test_locked_door_route_ends_beside_the_door(tmp_path: Path) -> None:
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    serialized = step.to_json()
    serialized["selection"]["intent"] = _routed(  # type: ignore[index]
        (1, 1), (2, 1), kind="locked_door"
    )

    intent = StepPayload.from_json(serialized).selection.intent

    assert intent is not None
    assert intent.path == (MapCell(1, 1), MapCell(2, 1))


def test_unknown_and_corrupt_stored_events_fail_clearly(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = RunStore(database)
    run = create_stored_run(store, tmp_path)
    store.append_event(run.id, RunPausedPayload())

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE events SET kind = 'future_event'")
    with pytest.raises(StoredEventError, match="unknown kind 'future_event'"):
        store.events_after(run.id)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE events SET kind = ?, payload_json = ?",
            (EventKind.RUN_STARTED.value, json.dumps({})),
        )
    with pytest.raises(StoredEventError, match="run_started event 0 is corrupt"):
        store.events_after(run.id)


def test_atomic_event_update_rejects_a_step_after_stop(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    run = create_stored_run(store, tmp_path)
    step = event_fixtures(tmp_path)[3]
    assert isinstance(step, StepPayload)
    store.update_run_and_append_event(
        run.id,
        state=RunState.STOPPED,
        outcome=RunOutcome.STOPPED,
        event=RunStoppedPayload(RunState.IDLE),
        expected_states=frozenset({RunState.IDLE}),
    )

    with pytest.raises(RunStateConflictError):
        store.update_run_and_append_event(
            run.id,
            state=RunState.RUNNING,
            event=step,
            expected_states=frozenset({RunState.RUNNING}),
        )

    assert store.get_run(run.id).state is RunState.STOPPED
    assert [event.kind for event in store.events_after(run.id)] == [
        EventKind.RUN_STOPPED
    ]


def test_event_replay_uses_stable_bounded_cursor_pages(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    run = create_stored_run(store, tmp_path)
    payloads = (
        RunPausedPayload(),
        RunResumedPayload(),
        RunPausedPayload(),
        RunResumedPayload(),
        RunPausedPayload(),
    )
    for payload in payloads:
        store.append_event(run.id, payload)

    first = store.event_page(run.id, limit=2)
    second = store.event_page(run.id, first.next_after, limit=2)
    third = store.event_page(run.id, second.next_after, limit=2)

    assert [event.sequence for event in first.events] == [0, 1]
    assert [event.sequence for event in second.events] == [2, 3]
    assert [event.sequence for event in third.events] == [4]
    assert first.has_more and second.has_more and not third.has_more
    assert third.next_after == 4


def test_existing_store_gains_num_ctx_metadata_without_losing_runs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runs.sqlite3"
    legacy = RunStore(database)
    old_run = create_stored_run(legacy, tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE runs DROP COLUMN ollama_num_ctx")

    reopened = RunStore(database)
    new_run = create_stored_run(reopened, tmp_path)

    assert reopened.get_run(old_run.id).ollama_num_ctx is None
    assert reopened.get_run(old_run.id).model == "test-model"
    assert reopened.get_run(new_run.id).ollama_num_ctx == 8192


def test_existing_store_gains_task_column_and_legacy_runs_read_no_task(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runs.sqlite3"
    legacy = RunStore(database)
    old_run = create_stored_run(legacy, tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE runs DROP COLUMN task")

    reopened = RunStore(database)
    descend = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_TASK_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 3)),)),
    )
    new_run = create_stored_run(reopened, tmp_path, descend)

    # A run stored before tasks existed recorded none; it is not assumed to be
    # the staircase task.
    old = reopened.get_run(old_run.id)
    assert old.task is None
    assert old.to_json()["task"] is None
    stored = reopened.get_run(new_run.id)
    assert stored.task == descend
    assert stored.environment == "NetHackScore-v0"
    assert stored.to_json()["task"] == descend.to_json()


def test_stored_task_must_match_the_run_environment(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = RunStore(database)
    run = create_stored_run(store, tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET environment = 'NetHackScore-v0' WHERE id = ?", (run.id,)
        )

    with pytest.raises(ContractError, match="does not match the run environment"):
        store.get_run(run.id)
