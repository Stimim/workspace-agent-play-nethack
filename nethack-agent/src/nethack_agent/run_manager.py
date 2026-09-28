from __future__ import annotations

import importlib.metadata
import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from nethack_agent.coordinator import (
    AgentCoordinator,
    CoordinatorLifecycleError,
    StepRecord,
)
from nethack_agent.decision import RunOutcome, RunState
from nethack_agent.environment import (
    CHARACTER,
    NleEnvironment,
    ScenarioConfig,
)
from nethack_agent.events import (
    AgentErrorPayload,
    DecisionFailureTrace,
    ErrorPhase,
    RunPausedPayload,
    RunResumedPayload,
    RunStartedPayload,
    RunStoppedPayload,
    StepPayload,
)
from nethack_agent.knowledge import KnowledgeBundle, load_default_knowledge_bundle
from nethack_agent.model import (
    DecisionFailure,
    HierarchicalDecisionModel,
    OllamaDecisionModel,
)
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import OllamaClient, OllamaConfig
from nethack_agent.storage import (
    DEFAULT_EVENT_PAGE_LIMIT,
    EventPage,
    RunEvent,
    RunNotFoundError,
    RunRecord,
    RunStateConflictError,
    RunStore,
)
from nethack_agent.tasks import STAIRCASE_TASK, TaskSpec

# Task specialists add deterministic gold navigation on NetHackGold-v0 to
# hierarchical-task-progression-v1. Earlier suites and reports remain pinned to
# their original policies.
POLICY_VERSION: Final = "hierarchical-task-specialists-v1"
_ACTIVE_STATES: Final = frozenset({RunState.IDLE, RunState.RUNNING, RunState.PAUSED})


class RunControlError(RuntimeError):
    pass


ModelFactory = Callable[[OllamaClient], HierarchicalDecisionModel]


@dataclass(slots=True)
class ManagedRun:
    id: str
    coordinator: AgentCoordinator
    client: OllamaClient
    worker: threading.Thread | None = None
    run_enabled: threading.Event = field(default_factory=threading.Event)


class RunManager:
    def __init__(
        self,
        data_directory: Path,
        ollama_config: OllamaConfig,
        *,
        model_factory: ModelFactory | None = None,
        knowledge_bundle: KnowledgeBundle | None = None,
    ) -> None:
        self.knowledge_bundle = knowledge_bundle or load_default_knowledge_bundle()
        self.data_directory = data_directory.expanduser().resolve()
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.store = RunStore(self.data_directory / "runs.sqlite3")
        self._ollama_config = ollama_config
        self._model_factory = model_factory or (
            lambda client: OllamaDecisionModel(client, self.knowledge_bundle)
        )
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.RLock()
        self._closing = False
        self._closed = False

    def create_run(
        self,
        *,
        seed: int,
        max_episode_steps: int = 5_000,
        auto_start: bool = False,
        task: TaskSpec = STAIRCASE_TASK,
    ) -> RunRecord:
        with self._lock:
            self._require_open()
            self._require_capacity()
            run_id = str(uuid.uuid4())
            environment: NleEnvironment | None = None
            managed: ManagedRun | None = None
            durable = False
            try:
                config = ScenarioConfig(
                    seed=seed,
                    artifact_directory=self.data_directory / "runs" / run_id,
                    max_episode_steps=max_episode_steps,
                    task=task,
                )
                environment = NleEnvironment(config)
                client = OllamaClient(self._ollama_config)
                coordinator = AgentCoordinator(
                    environment,
                    ObservationProjector(),
                    self._model_factory(client),
                )
                self.store.create_run(
                    config,
                    environment.seed_set,
                    character=CHARACTER,
                    model=self._ollama_config.model,
                    policy_version=POLICY_VERSION,
                    knowledge_version=self.knowledge_bundle.version,
                    nle_version=importlib.metadata.version("nle"),
                    ollama_num_ctx=self._ollama_config.num_ctx,
                    run_id=run_id,
                )
                durable = True
                managed = ManagedRun(run_id, coordinator, client)
                self._runs[run_id] = managed
                observation = coordinator.start()
                snapshot = coordinator.snapshot()
                record, _ = self.store.update_run_and_append_event(
                    run_id,
                    state=RunState.PAUSED,
                    event=RunStartedPayload(
                        observation=observation,
                        legal_actions=coordinator.legal_actions,
                        goal=snapshot.current_goal,
                        skill=snapshot.current_skill,
                    ),
                    expected_states=frozenset({RunState.IDLE}),
                )
                if auto_start:
                    record = self._resume_locked(managed)
                return record
            except Exception as error:
                if managed is not None:
                    managed.run_enabled.clear()
                    managed.coordinator.fail(error)
                elif environment is not None:
                    with suppress(Exception):
                        environment.close()
                rollback_error: Exception | None = None
                if durable:
                    try:
                        self._persist_create_failure(run_id, managed, error)
                    except Exception as failure:
                        rollback_error = failure
                self._runs.pop(run_id, None)
                if rollback_error is not None:
                    raise RuntimeError(
                        f"create_run failed ({error}); durable rollback failed"
                    ) from rollback_error
                raise

    def status(self, run_id: str) -> dict[str, object]:
        record = self.store.get_run(run_id)
        with self._lock:
            managed = self._runs.get(run_id)
            snapshot = managed.coordinator.snapshot().to_json() if managed else None
            legal_actions = (
                [action.to_json() for action in managed.coordinator.legal_actions]
                if managed
                else None
            )
        return {
            "run": record.to_json(),
            "coordinator": snapshot,
            "legal_actions": legal_actions,
        }

    def pause(self, run_id: str) -> RunRecord:
        with self._lock:
            self._require_open()
            managed = self._managed(run_id)
            managed.run_enabled.clear()
            managed.coordinator.pause()
            try:
                record, _ = self.store.update_run_and_append_event(
                    run_id,
                    state=RunState.PAUSED,
                    event=RunPausedPayload(),
                    expected_states=frozenset({RunState.RUNNING}),
                )
            except Exception as error:
                managed.coordinator.fail(error)
                self._persist_failure(managed, error)
                raise
            return record

    def resume(self, run_id: str) -> RunRecord:
        with self._lock:
            self._require_open()
            managed = self._managed(run_id)
            return self._resume_locked(managed)

    def step(self, run_id: str) -> StepRecord:
        with self._lock:
            self._require_open()
            managed = self._managed(run_id)
        try:
            record = managed.coordinator.advance(
                single_step=True,
                on_step=lambda step: self._persist_step(
                    managed, step, expected_state=RunState.PAUSED
                ),
            )
        except CoordinatorLifecycleError:
            raise
        except Exception as error:
            self._persist_failure(managed, error)
            raise
        if record is None:
            raise RunControlError("single-step decision was canceled")
        return record

    def stop(self, run_id: str) -> RunRecord:
        with self._lock:
            managed = self._managed(run_id)
            managed.run_enabled.clear()
            before = managed.coordinator.snapshot().state
            worker = managed.worker
            if before in {
                RunState.STOPPED,
                RunState.TERMINAL,
                RunState.ERROR,
            }:
                record = self.store.get_run(run_id)
            else:
                managed.coordinator.stop()
                snapshot = managed.coordinator.snapshot()
                record, _ = self.store.update_run_and_append_event(
                    run_id,
                    state=RunState.STOPPED,
                    outcome=snapshot.outcome,
                    error=snapshot.last_error,
                    ollama_version=managed.client.version,
                    ttyrec_path=self._ttyrec_path(managed, RunState.STOPPED),
                    event=RunStoppedPayload(previous_state=before),
                    expected_states=frozenset({before}),
                )
        self._join_worker(worker, timeout=0.1)
        return record

    def events_after(
        self,
        run_id: str,
        sequence: int = -1,
        *,
        limit: int = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> tuple[RunEvent, ...]:
        return self.store.events_after(run_id, sequence, limit=limit)

    def event_page(
        self,
        run_id: str,
        sequence: int = -1,
        *,
        limit: int = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> EventPage:
        return self.store.event_page(run_id, sequence, limit=limit)

    def close(self) -> None:
        with self._lock:
            if self._closed or self._closing:
                return
            self._closing = True
            run_ids = tuple(self._runs)
        errors: list[Exception] = []
        for run_id in run_ids:
            try:
                self.stop(run_id)
            except Exception as error:
                errors.append(error)
        with self._lock:
            workers = tuple(
                managed.worker
                for managed in self._runs.values()
                if managed.worker is not None
            )
        for worker in workers:
            self._join_worker(worker)
        with self._lock:
            self._closed = True
            self._closing = False
        if errors:
            raise RuntimeError(f"failed to stop {len(errors)} run(s)") from errors[0]

    shutdown = close

    def _resume_locked(self, managed: ManagedRun) -> RunRecord:
        managed.coordinator.resume()
        try:
            record, _ = self.store.update_run_and_append_event(
                managed.id,
                state=RunState.RUNNING,
                error=None,
                event=RunResumedPayload(),
                expected_states=frozenset({RunState.PAUSED}),
            )
        except Exception as error:
            managed.coordinator.fail(error)
            self._persist_failure(managed, error)
            raise
        managed.run_enabled.set()
        self._ensure_worker_locked(managed)
        return record

    def _ensure_worker_locked(self, managed: ManagedRun) -> None:
        if managed.worker is not None and managed.worker.is_alive():
            return
        worker = threading.Thread(
            target=self._run_loop,
            args=(managed,),
            name=f"nethack-run-{managed.id[:8]}",
            daemon=True,
        )
        managed.worker = worker
        try:
            worker.start()
        except Exception as error:
            managed.worker = None
            managed.run_enabled.clear()
            managed.coordinator.fail(error)
            self._persist_failure(managed, error)
            raise

    def _run_loop(self, managed: ManagedRun) -> None:
        try:
            while (
                managed.run_enabled.is_set()
                and managed.coordinator.snapshot().state is RunState.RUNNING
            ):
                try:
                    record = managed.coordinator.advance(
                        on_step=lambda step: self._persist_step(
                            managed, step, expected_state=RunState.RUNNING
                        )
                    )
                except CoordinatorLifecycleError:
                    return
                except Exception as error:
                    self._persist_failure(managed, error)
                    return
                if record is None:
                    if (
                        managed.run_enabled.is_set()
                        and managed.coordinator.snapshot().state is RunState.RUNNING
                    ):
                        continue
                    return
                if record.outcome is not None:
                    return
        finally:
            with self._lock:
                if managed.worker is threading.current_thread():
                    managed.worker = None
                if (
                    not self._closing
                    and not self._closed
                    and managed.run_enabled.is_set()
                    and managed.coordinator.snapshot().state is RunState.RUNNING
                ):
                    with suppress(Exception):
                        self._ensure_worker_locked(managed)

    def _persist_step(
        self,
        managed: ManagedRun,
        record: StepRecord,
        *,
        expected_state: RunState,
    ) -> None:
        state = RunState.TERMINAL if record.outcome is not None else expected_state
        skill_model = record.skill_model_decision
        action_model = record.action_model_decision
        self.store.update_run_and_append_event(
            managed.id,
            state=state,
            outcome=record.outcome,
            error=None,
            ollama_version=managed.client.version,
            ttyrec_path=self._ttyrec_path(managed, state),
            event=StepPayload(
                selection=record.selection,
                skill_decision=skill_model.decision if skill_model else None,
                skill_metrics=skill_model.metrics if skill_model else None,
                action_decision=action_model.decision if action_model else None,
                action_metrics=action_model.metrics if action_model else None,
                action=record.action,
                reward=record.transition.reward,
                terminated=record.transition.terminated,
                truncated=record.transition.truncated,
                end_status=record.transition.end_status,
                is_ascended=record.transition.is_ascended,
                outcome=record.outcome,
                observation=record.after,
            ),
            expected_states=frozenset({expected_state}),
        )

    def _persist_failure(self, managed: ManagedRun, error: Exception) -> None:
        snapshot = managed.coordinator.snapshot()
        if snapshot.state in {RunState.STOPPED, RunState.TERMINAL}:
            return
        if snapshot.state is not RunState.RUNNING:
            managed.run_enabled.clear()
        decision_failure = (
            DecisionFailureTrace.from_error(error)
            if isinstance(error, DecisionFailure)
            else None
        )
        try:
            self.store.update_run_and_append_event(
                managed.id,
                state=snapshot.state,
                outcome=snapshot.outcome,
                error=snapshot.last_error or str(error),
                ollama_version=managed.client.version,
                ttyrec_path=self._ttyrec_path(managed, snapshot.state),
                event=AgentErrorPayload(
                    error=str(error),
                    state=snapshot.state,
                    phase=ErrorPhase.ADVANCE,
                    decision_failure=decision_failure,
                ),
                expected_states=frozenset({RunState.RUNNING, RunState.PAUSED}),
            )
        except RunStateConflictError:
            persisted = self.store.get_run(managed.id)
            if persisted.state not in {
                RunState.STOPPED,
                RunState.TERMINAL,
                RunState.ERROR,
            }:
                raise

    def _persist_create_failure(
        self,
        run_id: str,
        managed: ManagedRun | None,
        error: Exception,
    ) -> None:
        persisted = self.store.get_run(run_id)
        state = persisted.state
        if state not in _ACTIVE_STATES:
            return
        snapshot = managed.coordinator.snapshot() if managed else None
        self.store.update_run_and_append_event(
            run_id,
            state=RunState.ERROR,
            outcome=snapshot.outcome if snapshot else RunOutcome.ERROR,
            error=str(error),
            ollama_version=managed.client.version if managed else None,
            ttyrec_path=(
                self._ttyrec_path(managed, RunState.ERROR) if managed else None
            ),
            event=AgentErrorPayload(
                error=str(error),
                state=RunState.ERROR,
                phase=ErrorPhase.CREATE_RUN,
            ),
            expected_states=frozenset({state}),
        )

    @staticmethod
    def _ttyrec_path(managed: ManagedRun, state: RunState) -> str | None:
        if state not in {
            RunState.TERMINAL,
            RunState.STOPPED,
            RunState.ERROR,
        }:
            return None
        ttyrec_files = managed.coordinator.ttyrec_files
        return str(ttyrec_files[0]) if ttyrec_files else None

    @staticmethod
    def _join_worker(
        worker: threading.Thread | None, *, timeout: float | None = None
    ) -> None:
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)

    def _managed(self, run_id: str) -> ManagedRun:
        managed = self._runs.get(run_id)
        if managed is None:
            try:
                self.store.get_run(run_id)
            except RunNotFoundError:
                raise
            raise RunControlError("run is not active in this service process")
        return managed

    def _require_capacity(self) -> None:
        if any(
            managed.coordinator.snapshot().state in _ACTIVE_STATES
            for managed in self._runs.values()
        ):
            raise RunControlError("only one active run is supported")

    def _require_open(self) -> None:
        if self._closing or self._closed:
            raise RunControlError("run manager is shut down")
