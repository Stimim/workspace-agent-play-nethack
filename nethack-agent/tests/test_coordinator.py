import threading
from pathlib import Path

import pytest

from nethack_agent.coordinator import AgentCoordinator, CoordinatorBusyError
from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    DecisionMetrics,
    ModelDecision,
    RunOutcome,
    RunState,
)
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.model import DecisionFailure, DecisionModel
from nethack_agent.observation import ObservationProjector


class FixedModel:
    def __init__(self, action_index: int) -> None:
        self.action_index = action_index

    def decide(self, *_: object) -> ModelDecision:
        return ModelDecision(
            decision=ActionDecision(
                goal="test one action",
                candidates=(ActionCandidate(self.action_index, 1.0, "test"),),
                action_index=self.action_index,
                rationale="Exercise the coordinator action path.",
            ),
            metrics=DecisionMetrics(1, 1, 1.0, False),
            raw_response="{}",
        )


class FailingModel:
    def decide(self, *_: object) -> ModelDecision:
        raise DecisionFailure("malformed after repair")


class BlockingModel:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def decide(self, *_: object) -> ModelDecision:
        self.entered.set()
        assert self.release.wait(timeout=2)
        return FixedModel(2).decide()


class ExplodingModel:
    def decide(self, *_: object) -> ModelDecision:
        raise RuntimeError("unexpected model failure")


def coordinator(
    directory: Path, model: DecisionModel, *, max_steps: int = 20
) -> AgentCoordinator:
    return AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=6,
                artifact_directory=directory,
                max_episode_steps=max_steps,
            )
        ),
        ObservationProjector(),
        model,
    )


def test_single_step_keeps_coordinator_paused(tmp_path: Path) -> None:
    agent = coordinator(tmp_path, FixedModel(2))  # CompassDirection.E
    initial = agent.start()

    record = agent.advance(single_step=True)

    assert record is not None
    assert record.before == initial
    assert record.after.player.x == initial.player.x + 1
    assert agent.snapshot().state is RunState.PAUSED
    agent.stop()


def test_model_failure_pauses_with_diagnostic(tmp_path: Path) -> None:
    agent = coordinator(tmp_path, FailingModel())
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
    assert agent.snapshot().state is RunState.PAUSED
    agent.stop()


def test_unexpected_model_exception_closes_environment_and_enters_error(
    tmp_path: Path,
) -> None:
    agent = coordinator(tmp_path, ExplodingModel())
    agent.start()
    agent.resume()

    with pytest.raises(RuntimeError, match="unexpected model failure"):
        agent.advance()

    snapshot = agent.snapshot()
    assert snapshot.state is RunState.ERROR
    assert snapshot.outcome is RunOutcome.ERROR
    assert snapshot.last_error == "unexpected model failure"
    assert len(agent.ttyrec_files) == 1
