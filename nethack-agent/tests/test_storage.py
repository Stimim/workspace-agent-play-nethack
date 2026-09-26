from pathlib import Path

import pytest

from nethack_agent.decision import RunOutcome, RunState
from nethack_agent.environment import ScenarioConfig, SeedSet
from nethack_agent.storage import RunStateConflictError, RunStore


def test_run_and_ordered_events_survive_store_reopen(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = RunStore(database)
    config = ScenarioConfig(seed=6, artifact_directory=tmp_path / "artifacts")
    seeds = SeedSet.derive(config.seed)
    run = store.create_run(
        config,
        seeds,
        environment="NetHackStaircase-v0",
        character="val-dwa-law",
        model="test-model",
        policy_version="test-policy",
        knowledge_version="test-knowledge",
        nle_version="1.3.0",
    )

    first = store.append_event(run.id, "run_started", {"step": 0})
    second = store.append_event(run.id, "step", {"step": 1})
    store.update_run(
        run.id,
        state=RunState.TERMINAL,
        outcome=RunOutcome.TASK_SUCCESS,
        ttyrec_path="episode.ttyrec3.bz2",
    )

    reopened = RunStore(database)
    persisted = reopened.get_run(run.id)
    events = reopened.events_after(run.id)

    assert persisted.state == "terminal"
    assert persisted.outcome == "task_success"
    assert persisted.ttyrec_path == "episode.ttyrec3.bz2"
    assert [event.sequence for event in events] == [0, 1]
    assert [event.kind for event in events] == ["run_started", "step"]
    assert reopened.events_after(run.id, first.sequence) == (second,)


def test_atomic_event_update_rejects_a_step_after_stop(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    config = ScenarioConfig(seed=6, artifact_directory=tmp_path / "artifacts")
    run = store.create_run(
        config,
        SeedSet.derive(config.seed),
        environment="NetHackStaircase-v0",
        character="val-dwa-law",
        model="test-model",
        policy_version="test-policy",
        knowledge_version="test-knowledge",
        nle_version="1.3.0",
    )
    store.update_run_and_append_event(
        run.id,
        state=RunState.STOPPED,
        outcome=RunOutcome.STOPPED,
        kind="run_stopped",
        payload={},
        expected_states=frozenset({RunState.IDLE}),
    )

    with pytest.raises(RunStateConflictError):
        store.update_run_and_append_event(
            run.id,
            state=RunState.RUNNING,
            kind="step",
            payload={},
            expected_states=frozenset({RunState.RUNNING}),
        )

    assert store.get_run(run.id).state == "stopped"
    assert [event.kind for event in store.events_after(run.id)] == ["run_stopped"]


def test_event_replay_uses_stable_bounded_cursor_pages(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    config = ScenarioConfig(seed=6, artifact_directory=tmp_path / "artifacts")
    run = store.create_run(
        config,
        SeedSet.derive(config.seed),
        environment="NetHackStaircase-v0",
        character="val-dwa-law",
        model="test-model",
        policy_version="test-policy",
        knowledge_version="test-knowledge",
        nle_version="1.3.0",
    )
    for value in range(5):
        store.append_event(run.id, "event", {"value": value})

    first = store.event_page(run.id, limit=2)
    second = store.event_page(run.id, first.next_after, limit=2)
    third = store.event_page(run.id, second.next_after, limit=2)

    assert [event.sequence for event in first.events] == [0, 1]
    assert [event.sequence for event in second.events] == [2, 3]
    assert [event.sequence for event in third.events] == [4]
    assert first.has_more and second.has_more and not third.has_more
    assert third.next_after == 4
