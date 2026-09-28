from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Final, TextIO

from nethack_agent.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    load_json_object,
    number_value,
    object_value,
    string_value,
)
from nethack_agent.decision import (
    FORBIDDEN_ACTION_NAMES,
    ActionSelectionSource,
    DecisionMetrics,
    RunOutcome,
    RunState,
)
from nethack_agent.environment import STAIRCASE_CHARACTER
from nethack_agent.events import (
    AgentErrorPayload,
    EventKind,
    RunEvent,
    RunStartedPayload,
    StepPayload,
)
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError
from nethack_agent.run_manager import POLICY_VERSION, ModelFactory, RunManager
from nethack_agent.storage import MAX_EVENT_PAGE_LIMIT, RunRecord, RunStore
from nethack_agent.tasks import STAIRCASE_TASK

SUITE_SCHEMA_VERSION: Final = 1
REPORT_SCHEMA_VERSION: Final = 2
SUITE_SEED_COUNT: Final = 10
MILESTONE_REFERENCE_SEED: Final = 6
MAX_STATUS_REASON_LENGTH: Final = 500
DEVELOPMENT_MODEL_NAME: Final = "scripted-development"
_IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_FINAL_STATES: Final = frozenset({RunState.TERMINAL, RunState.STOPPED, RunState.ERROR})


class ReportStatus(Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    ABORTED = "aborted"


# Only a suite that never reached a final status can be marked operator-aborted.
_ABORTABLE_STATUSES: Final = frozenset({ReportStatus.RUNNING, ReportStatus.INTERRUPTED})


class EvaluationError(RuntimeError):
    pass


class SuiteValidationError(EvaluationError):
    pass


@dataclass(frozen=True, slots=True)
class AcceptanceCriteria:
    min_task_successes: int
    required_success_seeds: tuple[int, ...]
    max_invalid_actions: int
    max_gate_rejections: int
    require_complete_records: bool

    def to_json(self) -> dict[str, object]:
        return {
            "min_task_successes": self.min_task_successes,
            "required_success_seeds": list(self.required_success_seeds),
            "max_invalid_actions": self.max_invalid_actions,
            "max_gate_rejections": self.max_gate_rejections,
            "require_complete_records": self.require_complete_records,
        }


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    suite_id: str
    environment: str
    character: str
    seeds: tuple[int, ...]
    seed_selection: str
    max_episode_steps: int
    step_cap_rationale: str
    acceptance: AcceptanceCriteria
    path: Path
    sha256: str

    def to_json(self) -> dict[str, object]:
        return {
            "suite_id": self.suite_id,
            "path": str(self.path),
            "sha256": self.sha256,
            "environment": self.environment,
            "character": self.character,
            "seeds": list(self.seeds),
            "seed_selection": self.seed_selection,
            "max_episode_steps": self.max_episode_steps,
            "step_cap_rationale": self.step_cap_rationale,
            "acceptance": self.acceptance.to_json(),
        }


def load_suite(path: Path) -> EvaluationSuite:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise SuiteValidationError(
            f"evaluation suite cannot be read: {error}"
        ) from error
    try:
        text = content.decode("utf-8")
        payload = object_value(
            load_json_object(text, "evaluation suite"),
            "evaluation suite",
            {
                "schema_version",
                "suite_id",
                "environment",
                "character",
                "seeds",
                "seed_selection",
                "max_episode_steps",
                "step_cap_rationale",
                "acceptance",
            },
        )
        return _parse_suite(payload, path, hashlib.sha256(content).hexdigest())
    except (ContractError, UnicodeDecodeError) as error:
        raise SuiteValidationError(
            f"invalid evaluation suite {path}: {error}"
        ) from error


def _parse_suite(
    payload: dict[str, object], path: Path, digest: str
) -> EvaluationSuite:
    schema_version = integer_value(payload["schema_version"], "suite schema_version")
    if schema_version != SUITE_SCHEMA_VERSION:
        raise ContractError(f"suite schema_version must be {SUITE_SCHEMA_VERSION}")
    suite_id = string_value(payload["suite_id"], "suite_id", minimum=1, maximum=80)
    if not _IDENTIFIER.fullmatch(suite_id):
        raise ContractError("suite_id must be a lowercase hyphenated identifier")
    environment = string_value(payload["environment"], "suite environment")
    if environment != STAIRCASE_TASK.environment.value:
        raise ContractError(
            f"suite environment must be {STAIRCASE_TASK.environment.value}"
        )
    character = string_value(payload["character"], "suite character")
    if character != STAIRCASE_CHARACTER:
        raise ContractError(f"suite character must be {STAIRCASE_CHARACTER}")
    seeds = tuple(
        integer_value(seed, "suite seed", minimum=1, maximum=sys.maxsize)
        for seed in array_value(payload["seeds"], "suite seeds")
    )
    if len(seeds) != SUITE_SEED_COUNT:
        raise ContractError(f"suite must contain exactly {SUITE_SEED_COUNT} seeds")
    if len(set(seeds)) != len(seeds):
        raise ContractError("suite seeds must be unique")
    if MILESTONE_REFERENCE_SEED not in seeds:
        raise ContractError(f"suite seeds must include seed {MILESTONE_REFERENCE_SEED}")
    seed_selection = string_value(
        payload["seed_selection"], "suite seed_selection", minimum=1, maximum=1000
    )
    max_episode_steps = integer_value(
        payload["max_episode_steps"],
        "suite max_episode_steps",
        minimum=1,
        maximum=100_000,
    )
    step_cap_rationale = string_value(
        payload["step_cap_rationale"],
        "suite step_cap_rationale",
        minimum=1,
        maximum=1000,
    )
    acceptance_payload = object_value(
        payload["acceptance"],
        "suite acceptance",
        {
            "min_task_successes",
            "required_success_seeds",
            "max_invalid_actions",
            "max_gate_rejections",
            "require_complete_records",
        },
    )
    required = tuple(
        integer_value(seed, "required success seed", minimum=1)
        for seed in array_value(
            acceptance_payload["required_success_seeds"],
            "acceptance required_success_seeds",
        )
    )
    if len(set(required)) != len(required) or not set(required) <= set(seeds):
        raise ContractError(
            "acceptance required_success_seeds must be unique suite seeds"
        )
    acceptance = AcceptanceCriteria(
        min_task_successes=integer_value(
            acceptance_payload["min_task_successes"],
            "acceptance min_task_successes",
            minimum=1,
            maximum=len(seeds),
        ),
        required_success_seeds=required,
        max_invalid_actions=integer_value(
            acceptance_payload["max_invalid_actions"],
            "acceptance max_invalid_actions",
            minimum=0,
        ),
        max_gate_rejections=integer_value(
            acceptance_payload["max_gate_rejections"],
            "acceptance max_gate_rejections",
            minimum=0,
        ),
        require_complete_records=boolean_value(
            acceptance_payload["require_complete_records"],
            "acceptance require_complete_records",
        ),
    )
    return EvaluationSuite(
        suite_id=suite_id,
        environment=environment,
        character=character,
        seeds=seeds,
        seed_selection=seed_selection,
        max_episode_steps=max_episode_steps,
        step_cap_rationale=step_cap_rationale,
        acceptance=acceptance,
        path=path,
        sha256=digest,
    )


@dataclass(frozen=True, slots=True)
class DecisionStats:
    decisions: int
    failed_decisions: int
    repaired_decisions: int
    prompt_tokens: int
    output_tokens: int
    latencies_ms: tuple[float, ...]

    @classmethod
    def from_metrics(
        cls,
        successful: Sequence[DecisionMetrics],
        failed: Sequence[DecisionMetrics] = (),
    ) -> DecisionStats:
        every = (*successful, *failed)
        return cls(
            decisions=len(successful),
            failed_decisions=len(failed),
            repaired_decisions=sum(item.repair_attempted for item in successful),
            prompt_tokens=sum(item.prompt_tokens for item in every),
            output_tokens=sum(item.output_tokens for item in every),
            latencies_ms=tuple(item.latency_ms for item in every),
        )

    @classmethod
    def combine(cls, stats: Sequence[DecisionStats]) -> DecisionStats:
        return cls(
            decisions=sum(item.decisions for item in stats),
            failed_decisions=sum(item.failed_decisions for item in stats),
            repaired_decisions=sum(item.repaired_decisions for item in stats),
            prompt_tokens=sum(item.prompt_tokens for item in stats),
            output_tokens=sum(item.output_tokens for item in stats),
            latencies_ms=tuple(
                latency for item in stats for latency in item.latencies_ms
            ),
        )

    @property
    def p50_ms(self) -> float | None:
        return nearest_rank_percentile(self.latencies_ms, 50)

    @property
    def p95_ms(self) -> float | None:
        return nearest_rank_percentile(self.latencies_ms, 95)

    @property
    def max_ms(self) -> float | None:
        return max(self.latencies_ms) if self.latencies_ms else None

    def to_json(self) -> dict[str, object]:
        return {
            "model_decisions": self.decisions,
            "failed_decisions": self.failed_decisions,
            "repaired_decisions": self.repaired_decisions,
            "latency_samples": len(self.latencies_ms),
            "latency_p50_ms": _rounded(self.p50_ms),
            "latency_p95_ms": _rounded(self.p95_ms),
            "latency_max_ms": _rounded(self.max_ms),
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
        }


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(percentile / 100 * len(ordered))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    model: str
    policy_version: str
    knowledge_version: str
    nle_version: str
    environment: str
    character: str
    max_episode_steps: int
    ollama_num_ctx: int | None

    @classmethod
    def from_record(cls, record: RunRecord) -> RunConfiguration:
        return cls(
            model=record.model,
            policy_version=record.policy_version,
            knowledge_version=record.knowledge_version,
            nle_version=record.nle_version,
            environment=record.environment,
            character=record.character,
            max_episode_steps=record.max_episode_steps,
            ollama_num_ctx=record.ollama_num_ctx,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "model": self.model,
            "policy_version": self.policy_version,
            "knowledge_version": self.knowledge_version,
            "nle_version": self.nle_version,
            "environment": self.environment,
            "character": self.character,
            "max_episode_steps": self.max_episode_steps,
            "ollama_num_ctx": self.ollama_num_ctx,
        }


@dataclass(frozen=True, slots=True)
class SeedResult:
    seed: int
    run_id: str | None
    outcome: RunOutcome | None
    final_state: RunState | None
    ended_by: str
    steps: int
    wall_seconds: float
    decision_stats: DecisionStats
    selection_sources: dict[str, int]
    gate_rejections: int
    decision_failures: int
    invalid_actions: int
    error: str | None
    ttyrec_path: str | None
    ttyrec_exists: bool
    event_count: int
    integrity_problems: tuple[str, ...]
    configuration: RunConfiguration | None
    ollama_version: str | None

    @property
    def integrity_ok(self) -> bool:
        return not self.integrity_problems

    @property
    def task_success(self) -> bool:
        return self.outcome is RunOutcome.TASK_SUCCESS

    def to_json(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "run_id": self.run_id,
            "outcome": self.outcome.value if self.outcome else None,
            "final_state": self.final_state.value if self.final_state else None,
            "ended_by": self.ended_by,
            "steps": self.steps,
            "wall_seconds": round(self.wall_seconds, 3),
            "decisions": self.decision_stats.to_json(),
            "selection_sources": dict(self.selection_sources),
            "gate_rejections": self.gate_rejections,
            "decision_failures": self.decision_failures,
            "invalid_actions": self.invalid_actions,
            "error": self.error,
            "ttyrec_path": self.ttyrec_path,
            "ttyrec_exists": self.ttyrec_exists,
            "event_count": self.event_count,
            "integrity_ok": self.integrity_ok,
            "integrity_problems": list(self.integrity_problems),
            "configuration": (
                self.configuration.to_json() if self.configuration else None
            ),
            "ollama_version": self.ollama_version,
        }


def summarize_run(
    record: RunRecord,
    events: Sequence[RunEvent],
    *,
    suite: EvaluationSuite,
    seed: int,
    ended_by: str,
    wall_seconds: float,
    data_directory: Path,
) -> SeedResult:
    problems: list[str] = []
    step_payloads: list[StepPayload] = []
    successful: list[DecisionMetrics] = []
    failed: list[DecisionMetrics] = []
    sources = Counter({source.value: 0 for source in ActionSelectionSource})
    gate_rejections = 0
    decision_failures = 0
    invalid_actions = 0
    legal_actions = None

    sequences = [event.sequence for event in events]
    if sequences != list(range(len(events))):
        problems.append("event sequences are not contiguous from 0")
    if not events or events[0].kind is not EventKind.RUN_STARTED:
        problems.append("first event is not run_started")
    started = [event for event in events if event.kind is EventKind.RUN_STARTED]
    if len(started) != 1:
        problems.append(f"expected one run_started event, found {len(started)}")
    elif isinstance(started[0].payload, RunStartedPayload):
        legal_actions = started[0].payload.legal_actions

    terminal_step_index: int | None = None
    for position, event in enumerate(events):
        payload = event.payload
        if isinstance(payload, StepPayload):
            step_payloads.append(payload)
            sources[payload.selection.source.value] += 1
            if payload.skill_metrics is not None:
                successful.append(payload.skill_metrics)
            if payload.action_metrics is not None:
                successful.append(payload.action_metrics)
            if not _action_is_valid(payload, legal_actions):
                invalid_actions += 1
            if payload.observation.step_index != len(step_payloads):
                problems.append(
                    f"step event {event.sequence} has step_index "
                    f"{payload.observation.step_index}, expected {len(step_payloads)}"
                )
            if payload.outcome is not None and terminal_step_index is None:
                terminal_step_index = position
        elif isinstance(payload, AgentErrorPayload):
            if payload.decision_failure is not None:
                decision_failures += 1
                failed.append(payload.decision_failure.metrics)
            elif payload.state is RunState.PAUSED:
                gate_rejections += 1
    if terminal_step_index is not None and terminal_step_index != len(events) - 1:
        problems.append("events follow the terminal step")

    last = events[-1] if events else None
    if record.state is RunState.TERMINAL:
        if not (
            last is not None
            and isinstance(last.payload, StepPayload)
            and last.payload.outcome is record.outcome
        ):
            problems.append("terminal run does not end with its outcome step")
    elif record.state is RunState.STOPPED:
        if last is None or last.kind is not EventKind.RUN_STOPPED:
            problems.append("stopped run does not end with run_stopped")
    elif record.state is RunState.ERROR:
        if not (
            last is not None
            and isinstance(last.payload, AgentErrorPayload)
            and last.payload.state is RunState.ERROR
        ):
            problems.append("error run does not end with an error event")
    else:
        problems.append(f"run did not reach a final state ({record.state.value})")
    if record.outcome is None:
        problems.append("run record has no outcome")
    if record.suite_seed != seed:
        problems.append("run record seed does not match the suite seed")
    if record.environment != suite.environment or record.character != suite.character:
        problems.append("run record environment or character differs from the suite")
    if record.max_episode_steps != suite.max_episode_steps:
        problems.append("run record step cap differs from the suite")
    if len(step_payloads) > suite.max_episode_steps:
        problems.append("run exceeded the suite step cap")

    ttyrec_path, ttyrec_exists = _ttyrec(record.ttyrec_path, data_directory)
    if record.ttyrec_path is None:
        problems.append("run record has no ttyrec reference")
    elif not ttyrec_exists:
        problems.append("referenced ttyrec is missing or empty")

    return SeedResult(
        seed=seed,
        run_id=record.id,
        outcome=record.outcome,
        final_state=record.state,
        ended_by=ended_by,
        steps=len(step_payloads),
        wall_seconds=wall_seconds,
        decision_stats=DecisionStats.from_metrics(successful, failed),
        selection_sources=dict(sources),
        gate_rejections=gate_rejections,
        decision_failures=decision_failures,
        invalid_actions=invalid_actions,
        error=record.error,
        ttyrec_path=ttyrec_path,
        ttyrec_exists=ttyrec_exists,
        event_count=len(events),
        integrity_problems=tuple(problems),
        configuration=RunConfiguration.from_record(record),
        ollama_version=record.ollama_version,
    )


def _action_is_valid(payload: StepPayload, legal_actions: object) -> bool:
    if not isinstance(legal_actions, tuple):
        return False
    action = payload.action
    return (
        0 <= action.index < len(legal_actions)
        and legal_actions[action.index] == action
        and action.name not in FORBIDDEN_ACTION_NAMES
        and payload.selection.action_index == action.index
    )


def _ttyrec(reference: str | None, data_directory: Path) -> tuple[str | None, bool]:
    if reference is None:
        return None, False
    path = Path(reference)
    exists = path.is_file() and path.stat().st_size > 0
    try:
        display = str(path.resolve().relative_to(data_directory.resolve()))
    except ValueError:
        display = str(path)
    return display, exists


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    checks: dict[str, bool]
    reasons: tuple[str, ...]
    development_model: bool

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def milestone_accepted(self) -> bool:
        return self.passed and not self.development_model

    def to_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "milestone_accepted": self.milestone_accepted,
            "development_model": self.development_model,
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
        }


def evaluate_acceptance(
    suite: EvaluationSuite,
    results: Sequence[SeedResult],
    *,
    development_model: bool,
    inputs_unchanged: bool,
) -> AcceptanceResult:
    criteria = suite.acceptance
    reasons: list[str] = []
    evaluated = [result.seed for result in results]
    all_evaluated = sorted(evaluated) == sorted(suite.seeds) and not any(
        result.ended_by == "interrupted" for result in results
    )
    if not all_evaluated:
        missing = sorted(set(suite.seeds) - set(evaluated))
        reasons.append(f"suite incomplete; missing or interrupted seeds {missing}")
    successes = sum(result.task_success for result in results)
    if successes < criteria.min_task_successes:
        reasons.append(
            f"{successes} task successes; at least {criteria.min_task_successes} "
            "required"
        )
    succeeded = {result.seed for result in results if result.task_success}
    missing_required = [
        seed for seed in criteria.required_success_seeds if seed not in succeeded
    ]
    if missing_required:
        reasons.append(f"required seeds did not succeed: {missing_required}")
    invalid = sum(result.invalid_actions for result in results)
    if invalid > criteria.max_invalid_actions:
        reasons.append(f"{invalid} invalid NLE actions recorded")
    rejections = sum(result.gate_rejections for result in results)
    if rejections > criteria.max_gate_rejections:
        reasons.append(f"{rejections} action-gate rejections recorded")
    incomplete = [result.seed for result in results if not result.integrity_ok]
    records_complete = not criteria.require_complete_records or not incomplete
    if not records_complete:
        reasons.append(f"incomplete SQLite or ttyrec records for seeds {incomplete}")
    configurations = {result.configuration for result in results}
    fixed = len(configurations) == 1 and None not in configurations
    if not fixed:
        reasons.append("run configuration was not identical across evaluated seeds")
    if not inputs_unchanged:
        reasons.append("suite or knowledge files changed during evaluation")
    if development_model:
        reasons.append(
            "development scripted model runs are never valid milestone evidence"
        )
    return AcceptanceResult(
        checks={
            "all_seeds_evaluated": all_evaluated,
            "min_task_successes": successes >= criteria.min_task_successes,
            "required_success_seeds": not missing_required,
            "invalid_actions": invalid <= criteria.max_invalid_actions,
            "gate_rejections": rejections <= criteria.max_gate_rejections,
            "complete_records": records_complete,
            "fixed_configuration": fixed,
            "inputs_unchanged": inputs_unchanged,
        },
        reasons=tuple(reasons),
        development_model=development_model,
    )


@dataclass(slots=True)
class EvaluationReport:
    suite: EvaluationSuite
    model_mode: str
    model: str
    policy_version: str
    knowledge_version: str
    ollama_num_ctx: int
    requested_seeds: tuple[int, ...]
    data_directory: str
    started_at: str
    finished_at: str | None = None
    status: ReportStatus = ReportStatus.RUNNING
    status_reason: str | None = None
    inputs_unchanged: bool = True
    results: list[SeedResult] = field(default_factory=list)

    @property
    def development_model(self) -> bool:
        return self.model_mode == "development_scripted"

    def acceptance(self) -> AcceptanceResult:
        return evaluate_acceptance(
            self.suite,
            self.results,
            development_model=self.development_model,
            inputs_unchanged=self.inputs_unchanged,
        )

    def aggregate_json(self) -> dict[str, object]:
        outcomes = Counter(
            result.outcome.value if result.outcome else "none"
            for result in self.results
        )
        sources = Counter({source.value: 0 for source in ActionSelectionSource})
        for result in self.results:
            sources.update(result.selection_sources)
        return {
            "evaluated_seeds": len(self.results),
            "task_successes": sum(result.task_success for result in self.results),
            "outcomes": dict(sorted(outcomes.items())),
            "steps": sum(result.steps for result in self.results),
            "total_wall_seconds": round(
                sum(result.wall_seconds for result in self.results), 3
            ),
            "decisions": DecisionStats.combine(
                [result.decision_stats for result in self.results]
            ).to_json(),
            "selection_sources": dict(sources),
            "gate_rejections": sum(r.gate_rejections for r in self.results),
            "decision_failures": sum(r.decision_failures for r in self.results),
            "invalid_actions": sum(r.invalid_actions for r in self.results),
            "integrity_failures": [
                result.seed for result in self.results if not result.integrity_ok
            ],
        }

    def to_json(self) -> dict[str, object]:
        return {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "status": self.status.value,
            "status_reason": self.status_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "suite": self.suite.to_json(),
            "configuration": {
                "model_mode": self.model_mode,
                "model": self.model,
                "policy_version": self.policy_version,
                "knowledge_version": self.knowledge_version,
                "ollama_num_ctx": self.ollama_num_ctx,
                "data_directory": self.data_directory,
            },
            "requested_seeds": list(self.requested_seeds),
            "results": [result.to_json() for result in self.results],
            "aggregate": self.aggregate_json(),
            "acceptance": self.acceptance().to_json(),
        }

    def to_markdown(self) -> str:
        return render_report_markdown(self.to_json())


_DECISION_FIELDS: Final = frozenset(
    {
        "model_decisions",
        "failed_decisions",
        "repaired_decisions",
        "latency_samples",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_max_ms",
        "prompt_tokens",
        "output_tokens",
    }
)
_RESULT_FIELDS: Final = frozenset(
    {
        "seed",
        "run_id",
        "outcome",
        "final_state",
        "ended_by",
        "steps",
        "wall_seconds",
        "decisions",
        "selection_sources",
        "gate_rejections",
        "decision_failures",
        "invalid_actions",
        "error",
        "ttyrec_path",
        "ttyrec_exists",
        "event_count",
        "integrity_ok",
        "integrity_problems",
        "configuration",
        "ollama_version",
    }
)
_AGGREGATE_FIELDS: Final = frozenset(
    {
        "evaluated_seeds",
        "task_successes",
        "outcomes",
        "steps",
        "total_wall_seconds",
        "decisions",
        "selection_sources",
        "gate_rejections",
        "decision_failures",
        "invalid_actions",
        "integrity_failures",
    }
)
_ACCEPTANCE_FIELDS: Final = frozenset(
    {"passed", "milestone_accepted", "development_model", "checks", "reasons"}
)
_ACCEPTANCE_CRITERIA_FIELDS: Final = frozenset(
    {
        "min_task_successes",
        "required_success_seeds",
        "max_invalid_actions",
        "max_gate_rejections",
        "require_complete_records",
    }
)
_SUITE_FIELDS: Final = frozenset(
    {
        "suite_id",
        "path",
        "sha256",
        "environment",
        "character",
        "seeds",
        "seed_selection",
        "max_episode_steps",
        "step_cap_rationale",
        "acceptance",
    }
)
_REPORT_CONFIGURATION_FIELDS: Final = frozenset(
    {
        "model_mode",
        "model",
        "policy_version",
        "knowledge_version",
        "ollama_num_ctx",
        "data_directory",
    }
)
_REPORT_FIELDS_V1: Final = frozenset(
    {
        "report_schema_version",
        "status",
        "started_at",
        "finished_at",
        "suite",
        "configuration",
        "requested_seeds",
        "results",
        "aggregate",
        "acceptance",
    }
)
_REPORT_FIELDS: Final = _REPORT_FIELDS_V1 | {"status_reason"}


def render_report_markdown(payload: dict[str, object]) -> str:
    """Render a current-schema report JSON payload, the single source of truth.

    Reads the payload strictly, so a persisted report can be re-rendered without
    the raw latency samples that only exist in memory during a run. An aborted
    report is never shown as accepted, whatever its recorded acceptance says.
    """
    report = object_value(payload, "evaluation report", _REPORT_FIELDS)
    version = integer_value(report["report_schema_version"], "report_schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise ContractError(f"report_schema_version must be {REPORT_SCHEMA_VERSION}")
    status = enum_value(report["status"], "report status", ReportStatus)
    reason = _optional_text(report["status_reason"], "report status_reason")
    if status is ReportStatus.ABORTED and reason is None:
        raise ContractError("an aborted report requires a status_reason")
    suite = object_value(report["suite"], "report suite", _SUITE_FIELDS)
    criteria = object_value(
        suite["acceptance"], "suite acceptance", _ACCEPTANCE_CRITERIA_FIELDS
    )
    configuration = object_value(
        report["configuration"], "report configuration", _REPORT_CONFIGURATION_FIELDS
    )
    acceptance = object_value(
        report["acceptance"], "report acceptance", _ACCEPTANCE_FIELDS
    )
    aggregate = object_value(report["aggregate"], "report aggregate", _AGGREGATE_FIELDS)
    decisions = object_value(
        aggregate["decisions"], "aggregate decisions", _DECISION_FIELDS
    )
    checks = _boolean_map(acceptance["checks"], "acceptance checks")
    reasons = [
        string_value(item, "acceptance reason")
        for item in array_value(acceptance["reasons"], "acceptance reasons")
    ]
    aborted = status is ReportStatus.ABORTED
    passed = boolean_value(acceptance["passed"], "acceptance passed") and not aborted
    accepted = (
        boolean_value(acceptance["milestone_accepted"], "milestone_accepted")
        and not aborted
    )
    if aborted:
        reasons.insert(
            0, f"report aborted ({reason}); aborted reports are never accepted"
        )
    finished_at = _optional_text(report["finished_at"], "report finished_at")
    seeds = _integers(suite["seeds"], "suite seeds")
    lines = [
        f"# Evaluation report: {string_value(suite['suite_id'], 'suite_id')}",
        "",
        f"- Status: {status.value}",
    ]
    if reason is not None:
        lines.append(f"- Status reason: {reason}")
    lines.extend(
        [
            f"- Started: {string_value(report['started_at'], 'report started_at')}",
            f"- Finished: {finished_at or 'not finished'}",
            f"- Suite: `{string_value(suite['path'], 'suite path')}` "
            f"(sha256 `{string_value(suite['sha256'], 'suite sha256')}`)",
            f"- Model mode: {string_value(configuration['model_mode'], 'model_mode')}; "
            f"model `{string_value(configuration['model'], 'model')}`",
            "- Policy: "
            f"`{string_value(configuration['policy_version'], 'policy_version')}`",
            "- Knowledge: "
            f"`{string_value(configuration['knowledge_version'], 'knowledge')}`",
            "- Ollama num_ctx: "
            f"{integer_value(configuration['ollama_num_ctx'], 'ollama_num_ctx')}",
            "- Step cap: "
            f"{integer_value(suite['max_episode_steps'], 'suite max_episode_steps')}",
            "- Requested seed order: "
            f"{_integers(report['requested_seeds'], 'requested_seeds')}",
            "",
            f"## Acceptance: {'PASS' if passed else 'FAIL'}",
            "",
            f"Milestone accepted: {'yes' if accepted else 'no'}.",
            "Task successes: "
            f"{integer_value(aggregate['task_successes'], 'task_successes')}/"
            f"{len(seeds)} (required "
            f"{integer_value(criteria['min_task_successes'], 'min_task_successes')}"
            ", including seeds "
            f"{_integers(criteria['required_success_seeds'], 'required seeds')}).",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
    )
    # Sorted like the persisted JSON so fresh and re-rendered reports agree.
    lines.extend(
        f"| {name} | {'pass' if value else 'fail'} |"
        for name, value in sorted(checks.items())
    )
    if reasons:
        lines.extend(["", *[f"- {item}" for item in reasons]])
    lines.extend(
        [
            "",
            "## Per-seed results",
            "",
            "| Seed | Outcome | Ended by | Steps | Wall s | Model decisions "
            "| p50 ms | p95 ms | Max ms | Prompt/output tokens "
            "| Skill/prompt/model | Gate rej. | Invalid | Integrity |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: "
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    problems: list[tuple[int, str]] = []
    errors: list[tuple[int, str]] = []
    for item in array_value(report["results"], "report results"):
        result = object_value(item, "report result", _RESULT_FIELDS)
        seed = integer_value(result["seed"], "result seed")
        stats = object_value(result["decisions"], "result decisions", _DECISION_FIELDS)
        sources = _integer_map(result["selection_sources"], "result selection_sources")
        outcome = _optional_text(result["outcome"], "result outcome")
        integrity_ok = boolean_value(result["integrity_ok"], "result integrity_ok")
        lines.append(
            f"| {seed} | {outcome or '-'} "
            f"| {string_value(result['ended_by'], 'result ended_by')} "
            f"| {integer_value(result['steps'], 'result steps')} "
            f"| {number_value(result['wall_seconds'], 'result wall_seconds'):.1f} "
            f"| {integer_value(stats['model_decisions'], 'model_decisions')} "
            f"| {_cell(_optional_number(stats['latency_p50_ms'], 'p50'))} "
            f"| {_cell(_optional_number(stats['latency_p95_ms'], 'p95'))} "
            f"| {_cell(_optional_number(stats['latency_max_ms'], 'max'))} "
            f"| {integer_value(stats['prompt_tokens'], 'prompt_tokens')}/"
            f"{integer_value(stats['output_tokens'], 'output_tokens')} "
            f"| {sources.get('deterministic_skill', 0)}/"
            f"{sources.get('deterministic_prompt', 0)}/"
            f"{sources.get('model_fallback', 0)} "
            f"| {integer_value(result['gate_rejections'], 'gate_rejections')} "
            f"| {integer_value(result['invalid_actions'], 'invalid_actions')} "
            f"| {'ok' if integrity_ok else 'FAIL'} |"
        )
        problems.extend(
            (seed, string_value(problem, "integrity problem"))
            for problem in array_value(
                result["integrity_problems"], "result integrity_problems"
            )
        )
        error = _optional_text(result["error"], "result error")
        if error:
            errors.append((seed, error))
    outcomes = _integer_map(aggregate["outcomes"], "aggregate outcomes")
    selection = _integer_map(aggregate["selection_sources"], "aggregate sources")
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "- Evaluated seeds: "
            f"{integer_value(aggregate['evaluated_seeds'], 'evaluated_seeds')}",
            f"- Outcomes: {dict(sorted(outcomes.items()))}",
            f"- Total steps: {integer_value(aggregate['steps'], 'aggregate steps')}",
            "- Total wall time: "
            f"{number_value(aggregate['total_wall_seconds'], 'total_wall_seconds')} s",
            "- Model decisions: "
            f"{integer_value(decisions['model_decisions'], 'model_decisions')} "
            f"(failed {integer_value(decisions['failed_decisions'], 'failed')}, "
            "repaired "
            f"{integer_value(decisions['repaired_decisions'], 'repaired')})",
            "- Decision latency p50/p95/max: "
            f"{_optional_number(decisions['latency_p50_ms'], 'p50')}/"
            f"{_optional_number(decisions['latency_p95_ms'], 'p95')}/"
            f"{_optional_number(decisions['latency_max_ms'], 'max')} ms",
            "- Tokens prompt/output: "
            f"{integer_value(decisions['prompt_tokens'], 'prompt_tokens')}/"
            f"{integer_value(decisions['output_tokens'], 'output_tokens')}",
            f"- Selection sources: {dict(sorted(selection.items()))}",
        ]
    )
    if problems or errors:
        lines.extend(["", "## Problems", ""])
        lines.extend(f"- Seed {seed}: {problem}" for seed, problem in problems)
        lines.extend(f"- Seed {seed} error: {error}" for seed, error in errors)
    return "\n".join(lines) + "\n"


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else string_value(value, name)


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else number_value(value, name)


def _integers(value: object, name: str) -> list[int]:
    return [integer_value(item, name) for item in array_value(value, name)]


def _boolean_map(value: object, name: str) -> dict[str, bool]:
    mapping = object_value(value, name, value.keys() if isinstance(value, dict) else ())
    return {key: boolean_value(item, name) for key, item in mapping.items()}


def _integer_map(value: object, name: str) -> dict[str, int]:
    mapping = object_value(value, name, value.keys() if isinstance(value, dict) else ())
    return {key: integer_value(item, name) for key, item in mapping.items()}


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


@dataclass(frozen=True, slots=True)
class ReportPaths:
    json: Path
    markdown: Path


class ReportWriter:
    """Reserve a new timestamped report pair and rewrite only that pair."""

    def __init__(self, directory: Path, stem: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 1000):
            suffix = "" if attempt == 1 else f"-{attempt}"
            json_path = directory / f"{stem}{suffix}.json"
            markdown_path = directory / f"{stem}{suffix}.md"
            try:
                with json_path.open("x", encoding="utf-8"):
                    pass
            except FileExistsError:
                continue
            try:
                with markdown_path.open("x", encoding="utf-8"):
                    pass
            except FileExistsError:
                json_path.unlink()
                continue
            self.paths = ReportPaths(json_path, markdown_path)
            return
        raise EvaluationError(f"could not reserve a unique report name for {stem}")

    def write(self, report: EvaluationReport) -> None:
        _replace_text(
            self.paths.json,
            json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n",
        )
        _replace_text(self.paths.markdown, report.to_markdown())


def _replace_text(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def finalize_aborted_report(json_path: Path, reason: str) -> ReportPaths:
    """Mark an existing unfinished report pair operator-aborted in place.

    Every recorded value (results, aggregate, acceptance, configuration and
    timestamps) is kept verbatim; results are never re-audited. Only the status,
    the status reason and the schema version change, and both the JSON and its
    sibling Markdown are rewritten atomically. No file is created or deleted.
    """
    status_reason = reason.strip()
    if not 1 <= len(status_reason) <= MAX_STATUS_REASON_LENGTH:
        raise EvaluationError(
            f"abort reason must be 1 to {MAX_STATUS_REASON_LENGTH} characters"
        )
    if not status_reason.isprintable():
        raise EvaluationError("abort reason must be a single line of printable text")
    if json_path.suffix != ".json":
        raise EvaluationError(f"report path must be a .json file: {json_path}")
    paths = ReportPaths(json_path, json_path.with_suffix(".md"))
    for path in (paths.json, paths.markdown):
        if not path.is_file():
            raise EvaluationError(f"report file does not exist: {path}")
    try:
        text = paths.json.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EvaluationError(f"report cannot be read: {error}") from error
    try:
        payload = load_json_object(text, "evaluation report")
        version = integer_value(
            payload.get("report_schema_version"), "report_schema_version"
        )
        if version not in (1, REPORT_SCHEMA_VERSION):
            raise ContractError(
                f"report_schema_version must be 1 or {REPORT_SCHEMA_VERSION}"
            )
        object_value(
            payload,
            "evaluation report",
            _REPORT_FIELDS_V1 if version == 1 else _REPORT_FIELDS,
        )
        status = enum_value(payload["status"], "report status", ReportStatus)
        if status not in _ABORTABLE_STATUSES:
            raise EvaluationError(
                f"only running or interrupted reports can be aborted; "
                f"{paths.json} is {status.value}"
            )
        finalized = {
            **payload,
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "status": ReportStatus.ABORTED.value,
            "status_reason": status_reason,
        }
        markdown = render_report_markdown(finalized)
    except ContractError as error:
        raise EvaluationError(
            f"invalid evaluation report {paths.json}: {error}"
        ) from error
    # The JSON is the source of truth, so it is replaced last: a failure between
    # the two writes leaves an abortable JSON and the command can be rerun.
    _replace_text(paths.markdown, markdown)
    _replace_text(paths.json, json.dumps(finalized, indent=2, sort_keys=True) + "\n")
    return paths


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    suite: EvaluationSuite
    data_directory: Path
    report_directory: Path
    seeds: tuple[int, ...] | None = None
    development_scripted_model: bool = False
    progress_interval_seconds: float = 30.0
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.seeds is not None:
            if not self.seeds or len(set(self.seeds)) != len(self.seeds):
                raise ValueError("requested seeds must be unique and nonempty")
            unknown = sorted(set(self.seeds) - set(self.suite.seeds))
            if unknown:
                raise ValueError(f"requested seeds are not in the suite: {unknown}")
        for name in ("progress_interval_seconds", "poll_interval_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite number greater than zero")


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    report: EvaluationReport
    paths: ReportPaths
    interrupted: bool


def _development_model(_client: OllamaClient) -> ScriptedDevelopmentModel:
    return ScriptedDevelopmentModel()


def run_evaluation(
    options: EvaluationOptions,
    *,
    ollama_config: OllamaConfig | None = None,
    progress: TextIO | None = sys.stderr,
) -> EvaluationRun:
    suite = options.suite
    if options.development_scripted_model:
        config = OllamaConfig(model=DEVELOPMENT_MODEL_NAME)
        model_factory: ModelFactory | None = _development_model
        mode = "development_scripted"
    else:
        config = ollama_config or OllamaConfig.from_environment()
        try:
            OllamaClient(config).ensure_ready()
        except OllamaError as error:
            raise EvaluationError(f"local Ollama is not ready: {error}") from error
        model_factory = None
        mode = "ollama"

    manager = RunManager(options.data_directory, config, model_factory=model_factory)
    started_at = _utc_now()
    report = EvaluationReport(
        suite=suite,
        model_mode=mode,
        model=config.model,
        policy_version=POLICY_VERSION,
        knowledge_version=manager.knowledge_bundle.version,
        ollama_num_ctx=config.num_ctx,
        requested_seeds=options.seeds or suite.seeds,
        data_directory=str(options.data_directory),
        started_at=started_at,
    )
    mode_suffix = "-development" if report.development_model else ""
    stem = f"{suite.suite_id}{mode_suffix}-{_compact_timestamp(started_at)}"
    writer = ReportWriter(options.report_directory, stem)
    log = _Progress(progress)
    interrupted = False
    try:
        writer.write(report)
        order = report.requested_seeds
        for position, seed in enumerate(order, start=1):
            log(f"seed {seed} ({position}/{len(order)}) starting")
            result, interrupted = _evaluate_seed(manager, options, seed, log)
            report.results.append(result)
            writer.write(report)
            stats = result.decision_stats
            log(
                f"seed {seed} ({position}/{len(order)}) "
                f"{result.outcome.value if result.outcome else 'no outcome'} "
                f"after {result.steps} steps in {result.wall_seconds:.1f}s; "
                f"{stats.decisions} model decisions, p50 "
                f"{_cell(stats.p50_ms)} ms; integrity "
                f"{'ok' if result.integrity_ok else 'FAILED'}"
            )
            if interrupted:
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        try:
            manager.close()
        finally:
            report.inputs_unchanged = _inputs_unchanged(report)
            report.finished_at = _utc_now()
            report.status = (
                ReportStatus.INTERRUPTED
                if interrupted
                else ReportStatus.FAILED
                if len(report.results) != len(report.requested_seeds)
                else ReportStatus.COMPLETE
                if set(report.requested_seeds) == set(suite.seeds)
                else ReportStatus.PARTIAL
            )
            writer.write(report)
    log(
        f"report {report.status.value}: {writer.paths.json} and {writer.paths.markdown}"
    )
    return EvaluationRun(report, writer.paths, interrupted)


def _evaluate_seed(
    manager: RunManager,
    options: EvaluationOptions,
    seed: int,
    log: Callable[[str], None],
) -> tuple[SeedResult, bool]:
    suite = options.suite
    started = time.monotonic()
    run_id: str | None = None
    interrupted = False
    ended_by = "episode_end"
    try:
        created = manager.create_run(
            seed=seed, max_episode_steps=suite.max_episode_steps, auto_start=True
        )
        run_id = created.id
        settled = _wait_until_settled(manager.store, run_id, seed, options, log)
        if settled.state is RunState.PAUSED:
            ended_by = _pause_reason(manager.store, run_id)
            manager.stop(run_id)
        elif settled.state is RunState.ERROR:
            ended_by = "agent_error"
    except KeyboardInterrupt:
        interrupted = True
        ended_by = "interrupted"
        if run_id is not None:
            manager.stop(run_id)
    except Exception as error:
        if run_id is None:
            return (
                _creation_failure(
                    seed, str(error), time.monotonic() - started, "create_failed"
                ),
                False,
            )
        raise
    if run_id is None:
        return (
            _creation_failure(
                seed,
                "interrupted before run creation",
                time.monotonic() - started,
                "interrupted",
            ),
            interrupted,
        )
    wall_seconds = time.monotonic() - started
    record = manager.store.get_run(run_id)
    events = _all_events(manager.store, run_id)
    return (
        summarize_run(
            record,
            events,
            suite=suite,
            seed=seed,
            ended_by=ended_by,
            wall_seconds=wall_seconds,
            data_directory=options.data_directory,
        ),
        interrupted,
    )


def _wait_until_settled(
    store: RunStore,
    run_id: str,
    seed: int,
    options: EvaluationOptions,
    log: Callable[[str], None],
) -> RunRecord:
    started = time.monotonic()
    next_report = started + options.progress_interval_seconds
    cursor = -1
    steps = 0
    fallbacks = 0
    while True:
        record = store.get_run(run_id)
        if record.state is not RunState.RUNNING:
            return record
        now = time.monotonic()
        if now >= next_report:
            while True:
                page = store.event_page(run_id, cursor, limit=MAX_EVENT_PAGE_LIMIT)
                for event in page.events:
                    if isinstance(event.payload, StepPayload):
                        steps += 1
                        fallbacks += event.payload.action_metrics is not None
                cursor = page.next_after
                if not page.has_more:
                    break
            log(
                f"seed {seed} running: {steps} steps, {fallbacks} model fallbacks, "
                f"{now - started:.0f}s elapsed"
            )
            next_report = now + options.progress_interval_seconds
        time.sleep(options.poll_interval_seconds)


def _pause_reason(store: RunStore, run_id: str) -> str:
    errors = [
        event.payload
        for event in _all_events(store, run_id)
        if isinstance(event.payload, AgentErrorPayload)
    ]
    if errors and errors[-1].decision_failure is not None:
        return "paused_after_decision_failure"
    if errors:
        return "paused_after_gate_rejection"
    return "paused_without_error"


def _all_events(store: RunStore, run_id: str) -> tuple[RunEvent, ...]:
    events: list[RunEvent] = []
    cursor = -1
    while True:
        page = store.event_page(run_id, cursor, limit=MAX_EVENT_PAGE_LIMIT)
        events.extend(page.events)
        cursor = page.next_after
        if not page.has_more:
            return tuple(events)


def _creation_failure(
    seed: int, error: str, wall_seconds: float, ended_by: str
) -> SeedResult:
    return SeedResult(
        seed=seed,
        run_id=None,
        outcome=None,
        final_state=None,
        ended_by=ended_by,
        steps=0,
        wall_seconds=wall_seconds,
        decision_stats=DecisionStats.from_metrics(()),
        selection_sources={source.value: 0 for source in ActionSelectionSource},
        gate_rejections=0,
        decision_failures=0,
        invalid_actions=0,
        error=error,
        ttyrec_path=None,
        ttyrec_exists=False,
        event_count=0,
        integrity_problems=(f"run was not created: {error}",),
        configuration=None,
        ollama_version=None,
    )


def _inputs_unchanged(report: EvaluationReport) -> bool:
    try:
        suite_digest = hashlib.sha256(report.suite.path.read_bytes()).hexdigest()
        knowledge_version = load_default_knowledge_bundle().version
    except Exception:
        return False
    return (
        suite_digest == report.suite.sha256
        and knowledge_version == report.knowledge_version
    )


class _Progress:
    def __init__(self, stream: TextIO | None) -> None:
        self._stream = stream

    def __call__(self, message: str) -> None:
        if self._stream is None:
            return
        print(f"[eval {_utc_now()}] {message}", file=self._stream, flush=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _compact_timestamp(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%SZ")
