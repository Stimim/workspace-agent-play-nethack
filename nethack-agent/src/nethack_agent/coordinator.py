from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nethack_agent.decision import ModelDecision, RunOutcome, RunState
from nethack_agent.environment import LegalAction, NleEnvironment, StepTransition
from nethack_agent.model import DecisionFailure, DecisionModel
from nethack_agent.observation import ObservationProjector, ProjectedObservation


class CoordinatorError(RuntimeError):
    """Base class for coordinator failures."""


class CoordinatorLifecycleError(CoordinatorError):
    """A requested lifecycle transition is not currently valid."""


class CoordinatorBusyError(CoordinatorLifecycleError):
    """Another caller is already deciding or advancing."""


class ActionGateError(CoordinatorError):
    """The model selected an action that the deterministic gate rejected."""


class CoordinatorInvariantError(CoordinatorError):
    """An internal coordinator invariant was violated."""


@dataclass(frozen=True, slots=True)
class StepRecord:
    before: ProjectedObservation
    decision: ModelDecision
    action: LegalAction
    transition: StepTransition
    after: ProjectedObservation
    outcome: RunOutcome | None


@dataclass(frozen=True, slots=True)
class CoordinatorSnapshot:
    state: RunState
    outcome: RunOutcome | None
    observation: ProjectedObservation | None
    last_error: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "outcome": self.outcome.value if self.outcome else None,
            "observation": self.observation.to_json() if self.observation else None,
            "last_error": self.last_error,
        }


class AgentCoordinator:
    """Serializes advances without blocking pause or stop during inference."""

    def __init__(
        self,
        environment: NleEnvironment,
        projector: ObservationProjector,
        model: DecisionModel,
    ) -> None:
        self._environment = environment
        self._projector = projector
        self._model = model
        self._lock = threading.RLock()
        self._state = RunState.IDLE
        self._outcome: RunOutcome | None = None
        self._observation: ProjectedObservation | None = None
        self._last_error: str | None = None
        self._lifecycle_revision = 0
        self._advance_in_flight = False

    @property
    def legal_actions(self) -> tuple[LegalAction, ...]:
        return self._environment.legal_actions

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
            try:
                raw = self._environment.reset()
                self._observation = self._projector.project(raw, step_index=0)
            except Exception as error:
                self._mark_error_locked(error)
                raise
            self._state = RunState.PAUSED
            self._outcome = None
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
            self._advance_in_flight = True

        try:
            try:
                model_decision = self._model.decide(before, self.legal_actions)
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

            with self._lock:
                if self._advance_was_canceled_locked(revision, started_state):
                    return None
                action = self._gate_action(model_decision)
                try:
                    transition = self._environment.step(action.index)
                    after = self._projector.project(
                        transition.observation, step_index=transition.step_index
                    )
                    self._observation = after
                    outcome = self._terminal_outcome(transition)
                    if outcome is not None:
                        self._outcome = outcome
                        self._state = RunState.TERMINAL
                        self._lifecycle_revision += 1
                        self._environment.close()
                    record = StepRecord(
                        before=before,
                        decision=model_decision,
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

    def _gate_action(self, model_decision: ModelDecision) -> LegalAction:
        action_index = model_decision.decision.action_index
        if not 0 <= action_index < len(self.legal_actions):
            self._state = RunState.PAUSED
            self._last_error = f"model selected invalid action index {action_index}"
            self._lifecycle_revision += 1
            raise ActionGateError(self._last_error)
        action = self.legal_actions[action_index]
        if action.index != action_index:
            error = CoordinatorInvariantError(
                "legal action table is not indexed contiguously"
            )
            self._mark_error_locked(error)
            raise error
        return action

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
