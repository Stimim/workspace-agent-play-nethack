import threading
import uuid
from pathlib import Path

import pytest

from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    DecisionMetrics,
    Goal,
    ModelActionDecision,
    ModelSkillDecision,
    RunState,
    Skill,
    SkillDecision,
)
from nethack_agent.events import AgentErrorPayload, EventKind, RunStartedPayload
from nethack_agent.model import DecisionAttemptDiagnostic, DecisionFailure
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager

_METRICS = DecisionMetrics(1, 1, 1.0, False)


def skill_decision() -> ModelSkillDecision:
    return ModelSkillDecision(
        SkillDecision(
            Goal.STAND_ON_DOWNSTAIRS,
            Skill.STAIRCASE_NAVIGATION,
            "Use staircase navigation.",
        ),
        _METRICS,
        "{}",
    )


def east_decision() -> ModelActionDecision:
    return ModelActionDecision(
        ActionDecision(
            candidates=(ActionCandidate(2, 1.0, "open floor"),),
            action_index=2,
            rationale="Move east.",
        ),
        _METRICS,
        "{}",
    )


class EastModel:
    def select_skill(self, *_: object) -> ModelSkillDecision:
        return skill_decision()

    def select_action(self, *_: object) -> ModelActionDecision:
        return east_decision()


class HandoffModel(EastModel):
    def __init__(self) -> None:
        self.entered = (threading.Event(), threading.Event())
        self.release = (threading.Event(), threading.Event())
        self._lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.maximum_active = 0

    def select_skill(self, *_: object) -> ModelSkillDecision:
        with self._lock:
            call = self.calls
            self.calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        assert call < 2
        self.entered[call].set()
        try:
            assert self.release[call].wait(timeout=3)
            return skill_decision()
        finally:
            with self._lock:
                self.active -= 1


class ExplodingModel(EastModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        raise RuntimeError("model implementation crashed")


class BlockingDecisionFailureModel(EastModel):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def select_skill(self, *_: object) -> ModelSkillDecision:
        self.entered.set()
        assert self.release.wait(timeout=3)
        raise DecisionFailure("invalid after repair")


class StructuredFailureModel(EastModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        attempts = (
            DecisionAttemptDiagnostic(
                "DecisionError: first",
                "{}",
                3,
                2,
                4.0,
                3.0,
            ),
            DecisionAttemptDiagnostic(
                "DecisionError: second",
                '{"bad":true}',
                5,
                4,
                6.0,
                5.0,
            ),
        )
        raise DecisionFailure(
            "invalid after repair",
            attempts=attempts,
            metrics=DecisionMetrics(8, 6, 8.0, True),
        )


def manager(tmp_path: Path, model: object) -> RunManager:
    return RunManager(
        tmp_path,
        OllamaConfig(model="test-model"),
        model_factory=lambda _client: model,  # type: ignore[return-value]
    )


def test_pause_resume_handoff_keeps_exactly_one_worker_and_stop_drains(
    tmp_path: Path,
) -> None:
    model = HandoffModel()
    runs = manager(tmp_path, model)
    run = runs.create_run(seed=6)
    runs.resume(run.id)
    assert model.entered[0].wait(timeout=2)

    runs.pause(run.id)
    runs.resume(run.id)
    model.release[0].set()
    assert model.entered[1].wait(timeout=2)
    assert runs.status(run.id)["run"]["state"] == "running"  # type: ignore[index]

    stopped: list[object] = []
    stop_thread = threading.Thread(target=lambda: stopped.append(runs.stop(run.id)))
    stop_thread.start()
    for _ in range(100):
        if runs.store.get_run(run.id).state is RunState.STOPPED:
            break
        threading.Event().wait(0.01)
    assert runs.store.get_run(run.id).state is RunState.STOPPED
    stop_thread.join(timeout=1)
    assert not stop_thread.is_alive()
    assert stopped
    model.release[1].set()
    runs.close()
    assert model.maximum_active == 1
    kinds = [event.kind for event in runs.events_after(run.id)]
    assert kinds == [
        EventKind.RUN_STARTED,
        EventKind.RUN_RESUMED,
        EventKind.RUN_PAUSED,
        EventKind.RUN_RESUMED,
        EventKind.RUN_STOPPED,
    ]
    runs.stop(run.id)
    assert [event.kind for event in runs.events_after(run.id)] == kinds


def test_stop_during_decision_failure_does_not_persist_agent_error(
    tmp_path: Path,
) -> None:
    model = BlockingDecisionFailureModel()
    runs = manager(tmp_path, model)
    run = runs.create_run(seed=6, auto_start=True)
    assert model.entered.wait(timeout=2)

    stop_thread = threading.Thread(target=lambda: runs.stop(run.id))
    stop_thread.start()
    for _ in range(100):
        if runs.store.get_run(run.id).state is RunState.STOPPED:
            break
        threading.Event().wait(0.01)
    stop_thread.join(timeout=1)
    assert not stop_thread.is_alive()
    model.release.set()
    runs.close()

    kinds = [event.kind for event in runs.events_after(run.id)]
    assert kinds[-1] is EventKind.RUN_STOPPED
    assert EventKind.AGENT_ERROR not in kinds


def test_unexpected_model_exception_persists_error_artifact_and_frees_capacity(
    tmp_path: Path,
) -> None:
    runs = manager(tmp_path, ExplodingModel())
    run = runs.create_run(seed=6)

    with pytest.raises(RuntimeError, match="model implementation crashed"):
        runs.step(run.id)

    persisted = runs.store.get_run(run.id)
    assert persisted.state is RunState.ERROR
    assert persisted.error == "model implementation crashed"
    assert persisted.ttyrec_path is not None
    assert Path(persisted.ttyrec_path).is_file()
    kinds = [event.kind for event in runs.events_after(run.id)]
    assert kinds[-1] is EventKind.AGENT_ERROR
    runs.stop(run.id)
    assert [event.kind for event in runs.events_after(run.id)] == kinds

    replacement = runs.create_run(seed=7)
    runs.stop(replacement.id)


def test_stop_on_terminal_run_does_not_append_stopped_event(tmp_path: Path) -> None:
    runs = manager(tmp_path, EastModel())
    run = runs.create_run(seed=6, max_episode_steps=1)

    runs.step(run.id)
    before_stop = [event.kind for event in runs.events_after(run.id)]
    runs.stop(run.id)

    assert runs.store.get_run(run.id).state is RunState.TERMINAL
    assert [event.kind for event in runs.events_after(run.id)] == before_stop
    assert before_stop == [EventKind.RUN_STARTED, EventKind.STEP]


def test_decision_failure_diagnostics_are_persisted(tmp_path: Path) -> None:
    runs = manager(tmp_path, StructuredFailureModel())
    run = runs.create_run(seed=6)

    with pytest.raises(DecisionFailure):
        runs.step(run.id)

    persisted = runs.store.get_run(run.id)
    assert persisted.state is RunState.PAUSED
    payload = runs.events_after(run.id)[-1].payload
    assert isinstance(payload, AgentErrorPayload)
    assert payload.decision_failure is not None
    assert payload.decision_failure.metrics == DecisionMetrics(8, 6, 8.0, True)
    assert [attempt.raw_response for attempt in payload.decision_failure.attempts] == [
        "{}",
        '{"bad":true}',
    ]
    runs.stop(run.id)


def test_create_run_rolls_back_after_started_event_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = manager(tmp_path, HandoffModel())
    run_uuid = uuid.UUID("00000000-0000-0000-0000-000000000006")
    monkeypatch.setattr("nethack_agent.run_manager.uuid.uuid4", lambda: run_uuid)
    original = runs.store.update_run_and_append_event
    failed = False

    def fail_started_event(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal failed
        if isinstance(kwargs.get("event"), RunStartedPayload) and not failed:
            failed = True
            raise OSError("event persistence failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(runs.store, "update_run_and_append_event", fail_started_event)

    with pytest.raises(OSError, match="event persistence failed"):
        runs.create_run(seed=6)

    persisted = runs.store.get_run(str(run_uuid))
    assert persisted.state is RunState.ERROR
    assert persisted.ttyrec_path is not None
    assert Path(persisted.ttyrec_path).is_file()
    assert str(run_uuid) not in runs._runs


def test_create_run_rolls_back_when_worker_thread_cannot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = manager(tmp_path, HandoffModel())
    run_uuid = uuid.UUID("00000000-0000-0000-0000-000000000007")
    monkeypatch.setattr("nethack_agent.run_manager.uuid.uuid4", lambda: run_uuid)
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("thread start failed")),
    )

    with pytest.raises(RuntimeError, match="thread start failed"):
        runs.create_run(seed=7, auto_start=True)

    persisted = runs.store.get_run(str(run_uuid))
    assert persisted.state is RunState.ERROR
    assert persisted.ttyrec_path is not None
    assert [event.kind for event in runs.events_after(str(run_uuid))] == [
        EventKind.RUN_STARTED,
        EventKind.RUN_RESUMED,
        EventKind.AGENT_ERROR,
    ]
    assert str(run_uuid) not in runs._runs
