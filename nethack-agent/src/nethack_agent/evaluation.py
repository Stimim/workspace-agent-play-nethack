from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import secrets
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from nle import nethack

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
from nethack_agent.corpse import CorpseKill, eligible_corpse, observed_corpse_kill
from nethack_agent.decision import (
    ESC_COMMAND,
    LEVEL_CHANGE_ACTIONS,
    PRAY_ACTION_NAME,
    YES_COMMAND,
    ActionSelectionSource,
    CorpseEvidence,
    CorpseOutcome,
    CorpseOutcomeKind,
    DecisionMetrics,
    DestinationKind,
    PrayerEvidence,
    PrayerOutcome,
    PrayerPermit,
    PromptKind,
    PromptPermit,
    RunOutcome,
    RunState,
    Skill,
    classify_corpse_outcome,
    classify_prayer_outcome,
    confirmation_answer_error,
    confirmation_prompt_kind,
    corpse_confirmation_error,
    hunger_action_error,
    level_change_error,
    parse_floor_corpse_prompt,
    prayer_action_error,
    prompt_response_error,
)
from nethack_agent.environment import CHARACTER, LegalAction
from nethack_agent.events import (
    AgentErrorPayload,
    EventKind,
    RunEvent,
    RunStartedPayload,
    StepPayload,
)
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.navigation import (
    GOLD_GLYPH,
    MOVE_ACTION_NAMES,
    DungeonMemory,
    route_tree,
)
from nethack_agent.observation import ProjectedObservation
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError
from nethack_agent.replay import ExplorationReplay
from nethack_agent.run_manager import POLICY_VERSION, ModelFactory, RunManager
from nethack_agent.skills import item_selection_commands, safe_food_rations
from nethack_agent.storage import MAX_EVENT_PAGE_LIMIT, RunRecord, RunStore
from nethack_agent.tasks import (
    STAIRCASE_TASK,
    ActionProfile,
    ActionRole,
    NleTask,
    TaskSpec,
)
from nethack_agent.traversal import (
    EnterDungeonLeg,
    ExploreDungeonLeg,
    FindOracleLeg,
    LevelKey,
    ObjectiveLeg,
    ReachLevelLeg,
    StairConnection,
    StairDirection,
    StairIdentityKind,
)

if TYPE_CHECKING:
    from nethack_agent.seed_catalog import CatalogEntry


SUITE_SCHEMA_VERSION: Final = 2
FRESH_SUITE_SCHEMA_VERSION: Final = 3
LEGACY_SUITE_SCHEMA_VERSION: Final = 1
# Schema-1 suites (staircase-v1) were fixed for this policy. Later policies
# change prompts and the model output contract (ADR 0004), so only a checkout
# with this policy can reproduce them; others are refused before any episode.
SCHEMA_1_POLICY_VERSION: Final = "hierarchical-explore-v1"
REPORT_SCHEMA_VERSION: Final = 3
LEGACY_REPORT_SCHEMA_VERSION: Final = 2
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
    """One case's success gate plus the suite-wide integrity gate.

    Schema 1 stored all five values in one object. Schema 2 splits the first
    two into each case and the last three into the suite. Keeping this typed
    value as the common view avoids a parallel acceptance implementation for
    legacy reports.
    """

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


class MetricName(Enum):
    """Per-episode values a suite case may gate on."""

    TASK_RETURN = "task_return"
    EXPLORED_CELLS = "explored_cells"
    MAX_DEPTH = "max_depth"
    FINAL_GOLD = "final_gold"
    # The NLE hunger index (satiated 0 .. starved 6) of the worst live state.
    WORST_HUNGER_STATE = "worst_hunger_state"
    # 1 for an episode that ended in death, else 0.
    DEATH = "death"
    # 1 for an episode whose recorded death cause is starvation, else 0.
    STARVATION_DEATH = "starvation_death"
    # NLE hunger index at the last live observation preceding death; non-deaths
    # contribute 0 to allow a maximum at_most 2 gate. Missing evidence fails.
    HUNGER_AT_DEATH = "hunger_at_death"


class MetricStatistic(Enum):
    MINIMUM = "minimum"
    MEDIAN = "median"
    MEAN = "mean"
    MAXIMUM = "maximum"
    SUM = "sum"


class MetricComparison(Enum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"


@dataclass(frozen=True, slots=True)
class MetricThreshold:
    """A bound on one statistic of a per-episode metric over a case's results."""

    metric: MetricName
    statistic: MetricStatistic
    comparison: MetricComparison
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.metric, MetricName):
            raise TypeError("metric threshold metric must be a MetricName")
        if not isinstance(self.statistic, MetricStatistic):
            raise TypeError("metric threshold statistic must be a MetricStatistic")
        if not isinstance(self.comparison, MetricComparison):
            raise TypeError("metric threshold comparison must be a MetricComparison")
        object.__setattr__(
            self, "value", number_value(self.value, "metric threshold value")
        )

    @property
    def key(self) -> tuple[MetricName, MetricStatistic, MetricComparison]:
        return self.metric, self.statistic, self.comparison

    @property
    def check_name(self) -> str:
        return f"{self.metric.value}:{self.statistic.value}:{self.comparison.value}"

    @property
    def bound_text(self) -> str:
        return f"{self.comparison.value} {_compact_number(self.value)}"

    def passes(self, observed: float | None) -> bool:
        if observed is None:
            return False
        if self.comparison is MetricComparison.AT_LEAST:
            return observed >= self.value
        return observed <= self.value

    def to_json(self) -> dict[str, object]:
        return {
            "metric": self.metric.value,
            "statistic": self.statistic.value,
            "bound": {
                "comparison": self.comparison.value,
                "value": _json_number(self.value),
            },
        }

    @classmethod
    def from_json(cls, value: object, name: str) -> MetricThreshold:
        payload = object_value(value, name, {"metric", "statistic", "bound"})
        bound = object_value(payload["bound"], f"{name} bound", {"comparison", "value"})
        return cls(
            metric=enum_value(payload["metric"], f"{name} metric", MetricName),
            statistic=enum_value(
                payload["statistic"], f"{name} statistic", MetricStatistic
            ),
            comparison=enum_value(
                bound["comparison"], f"{name} bound comparison", MetricComparison
            ),
            value=number_value(bound["value"], f"{name} bound value"),
        )


def _metric_thresholds(value: object, name: str) -> tuple[MetricThreshold, ...]:
    items = array_value(value, f"{name} metric_thresholds")
    if not items:
        raise ContractError(f"{name} metric_thresholds must not be empty")
    thresholds = tuple(
        MetricThreshold.from_json(item, f"{name} metric threshold {index}")
        for index, item in enumerate(items)
    )
    if len({threshold.key for threshold in thresholds}) != len(thresholds):
        raise ContractError(
            f"{name} metric_thresholds must not repeat a metric, statistic, "
            "and comparison"
        )
    return thresholds


def _json_number(value: float) -> int | float:
    """Write an integral bound as a JSON integer, as suites state it."""
    return int(value) if value.is_integer() else value


def _compact_number(value: float) -> str:
    return f"{int(value)}" if value.is_integer() else f"{value:.3f}"


@dataclass(frozen=True, slots=True)
class CaseAcceptance:
    min_successes: int
    required_success_seeds: tuple[int, ...]
    metric_thresholds: tuple[MetricThreshold, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            isinstance(threshold, MetricThreshold)
            for threshold in self.metric_thresholds
        ):
            raise TypeError("case metric_thresholds must contain MetricThreshold")
        keys = [threshold.key for threshold in self.metric_thresholds]
        if len(keys) != len(set(keys)):
            raise ContractError("case metric_thresholds must be unique")

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "min_successes": self.min_successes,
            "required_success_seeds": list(self.required_success_seeds),
        }
        # Absent, not empty, so suites without thresholds keep their shape.
        if self.metric_thresholds:
            payload["metric_thresholds"] = [
                threshold.to_json() for threshold in self.metric_thresholds
            ]
        return payload


@dataclass(frozen=True, slots=True)
class GlobalAcceptance:
    max_invalid_actions: int
    max_gate_rejections: int
    require_complete_records: bool

    def to_json(self) -> dict[str, object]:
        return {
            "max_invalid_actions": self.max_invalid_actions,
            "max_gate_rejections": self.max_gate_rejections,
            "require_complete_records": self.require_complete_records,
        }


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    task: TaskSpec
    seeds: tuple[int, ...]
    max_episode_steps: int
    acceptance: CaseAcceptance

    def to_json(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "task": self.task.to_json(),
            "seeds": list(self.seeds),
            "max_episode_steps": self.max_episode_steps,
            "acceptance": self.acceptance.to_json(),
        }


@dataclass(frozen=True, slots=True)
class FreshAcceptance:
    min_success_rate: float
    metric_thresholds: tuple[MetricThreshold, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_success_rate, bool)
            or not isinstance(self.min_success_rate, (int, float))
            or not math.isfinite(self.min_success_rate)
            or not 0 <= self.min_success_rate <= 1
        ):
            raise ContractError(
                "fresh min_success_rate must be a finite number in [0, 1]"
            )
        if not isinstance(self.metric_thresholds, tuple) or not all(
            isinstance(threshold, MetricThreshold)
            for threshold in self.metric_thresholds
        ):
            raise ContractError("fresh metric_thresholds must contain MetricThreshold")
        keys = [threshold.key for threshold in self.metric_thresholds]
        if len(keys) != len(set(keys)):
            raise ContractError("fresh metric_thresholds must be unique")

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {"min_success_rate": self.min_success_rate}
        if self.metric_thresholds:
            payload["metric_thresholds"] = [
                threshold.to_json() for threshold in self.metric_thresholds
            ]
        return payload


@dataclass(frozen=True, slots=True)
class FreshSample:
    case_id: str
    task: TaskSpec
    max_episode_steps: int
    count: int
    seed_range: tuple[int, int]
    acceptance: FreshAcceptance

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not _IDENTIFIER.fullmatch(self.case_id):
            raise ContractError("fresh case_id must be a kebab-case identifier")
        if not isinstance(self.task, TaskSpec):
            raise ContractError("fresh task must be a TaskSpec")
        if (
            type(self.max_episode_steps) is not int
            or not 1 <= self.max_episode_steps <= 100_000
        ):
            raise ContractError("fresh max_episode_steps must be in [1, 100000]")
        if type(self.count) is not int or self.count < 1:
            raise ContractError("fresh count must be positive")
        if (
            not isinstance(self.seed_range, tuple)
            or len(self.seed_range) != 2
            or any(type(bound) is not int for bound in self.seed_range)
            or not 1 <= self.seed_range[0] <= self.seed_range[1] <= 2**31 - 1
        ):
            raise ContractError("fresh range must contain ordered positive seed bounds")
        if self.count > self.seed_range[1] - self.seed_range[0] + 1:
            raise ContractError("fresh count exceeds available range")
        if not isinstance(self.acceptance, FreshAcceptance):
            raise ContractError("fresh acceptance must be FreshAcceptance")

    def to_json(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "task": self.task.to_json(),
            "max_episode_steps": self.max_episode_steps,
            "count": self.count,
            "range": list(self.seed_range),
            "acceptance": self.acceptance.to_json(),
        }


@dataclass(frozen=True, slots=True)
class DrawProvenance:
    draw_seed: int
    seed_range: tuple[int, int]
    excluded_seeds: tuple[int, ...]
    drawn_seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.draw_seed) is not int or self.draw_seed < 0:
            raise ContractError("draw_seed must be a nonnegative integer")
        if (
            not isinstance(self.seed_range, tuple)
            or len(self.seed_range) != 2
            or any(type(bound) is not int for bound in self.seed_range)
            or not 1 <= self.seed_range[0] <= self.seed_range[1] <= 2**31 - 1
        ):
            raise ContractError("draw range must contain ordered positive seed bounds")
        if (
            not isinstance(self.excluded_seeds, tuple)
            or (tuple(sorted(set(self.excluded_seeds))) != self.excluded_seeds)
            or not all(
                self.seed_range[0] <= seed <= self.seed_range[1] and type(seed) is int
                for seed in self.excluded_seeds
            )
        ):
            raise ContractError(
                "draw excluded_seeds must be sorted unique in-range seeds"
            )
        if (
            not isinstance(self.drawn_seeds, tuple)
            or any(type(seed) is not int for seed in self.drawn_seeds)
            or tuple(self.drawn_seeds)
            != _draw_available_seeds(
                self.seed_range,
                self.excluded_seeds,
                self.draw_seed,
                len(self.drawn_seeds),
            )
        ):
            raise ContractError(
                "drawn_seeds do not reproduce from draw_seed and exclusions"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "draw_seed": self.draw_seed,
            "range": list(self.seed_range),
            "exclusion_count": len(self.excluded_seeds),
            "excluded_seeds": list(self.excluded_seeds),
            "drawn_seeds": list(self.drawn_seeds),
        }

    @classmethod
    def from_json(cls, value: object) -> DrawProvenance:
        payload = object_value(value, "draw provenance", _DRAW_FIELDS)
        bounds = array_value(payload["range"], "draw range")
        excluded = array_value(payload["excluded_seeds"], "draw excluded_seeds")
        drawn = array_value(payload["drawn_seeds"], "draw drawn_seeds")
        provenance = cls(
            draw_seed=integer_value(payload["draw_seed"], "draw_seed", minimum=0),
            seed_range=tuple(
                integer_value(bound, "draw range bound", minimum=1, maximum=2**31 - 1)
                for bound in bounds
            ),
            excluded_seeds=tuple(
                integer_value(seed, "draw excluded seed", minimum=1, maximum=2**31 - 1)
                for seed in excluded
            ),
            drawn_seeds=tuple(
                integer_value(seed, "draw seed", minimum=1, maximum=2**31 - 1)
                for seed in drawn
            ),
        )
        if integer_value(
            payload["exclusion_count"], "draw exclusion_count", minimum=0
        ) != len(excluded):
            raise ContractError("draw exclusion_count differs from excluded_seeds")
        return provenance


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    schema_version: int
    suite_id: str
    character: str
    policy_version: str
    knowledge_bundle_id: str | None
    seed_selection: str
    step_cap_rationale: str
    cases: tuple[EvaluationCase, ...]
    global_acceptance: GlobalAcceptance
    path: Path
    sha256: str
    baseline: tuple[CatalogEntry, ...] = ()
    fresh_sample: FreshSample | None = None
    catalog_path: Path | None = None
    catalog_sha256: str | None = None

    @property
    def legacy(self) -> bool:
        return self.schema_version == LEGACY_SUITE_SCHEMA_VERSION

    @property
    def seeds(self) -> tuple[int, ...]:
        """Distinct seed values in first-declared order, for CLI filtering."""
        return tuple(dict.fromkeys(seed for case in self.cases for seed in case.seeds))

    @property
    def environment(self) -> str:
        """The sole environment of a schema-1 suite."""
        return self.cases[0].task.environment.value

    @property
    def max_episode_steps(self) -> int:
        """The sole step cap of a schema-1 suite."""
        return self.cases[0].max_episode_steps

    @property
    def acceptance(self) -> AcceptanceCriteria:
        """The combined schema-1 acceptance view used by old callers."""
        case = self.cases[0]
        return AcceptanceCriteria(
            min_task_successes=case.acceptance.min_successes,
            required_success_seeds=case.acceptance.required_success_seeds,
            max_invalid_actions=self.global_acceptance.max_invalid_actions,
            max_gate_rejections=self.global_acceptance.max_gate_rejections,
            require_complete_records=self.global_acceptance.require_complete_records,
        )

    def case(self, case_id: str) -> EvaluationCase:
        return next(case for case in self.cases if case.case_id == case_id)

    def to_json(self) -> dict[str, object]:
        if self.legacy:
            case = self.cases[0]
            return {
                "suite_id": self.suite_id,
                "path": str(self.path),
                "sha256": self.sha256,
                "environment": case.task.environment.value,
                "character": self.character,
                "seeds": list(case.seeds),
                "seed_selection": self.seed_selection,
                "max_episode_steps": case.max_episode_steps,
                "step_cap_rationale": self.step_cap_rationale,
                "acceptance": self.acceptance.to_json(),
            }
        assert self.knowledge_bundle_id is not None
        excluded_case_ids = (
            {entry.entry_id for entry in self.baseline}
            | ({self.fresh_sample.case_id} if self.fresh_sample is not None else set())
            if self.schema_version == FRESH_SUITE_SCHEMA_VERSION
            else set()
        )
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "path": str(self.path),
            "sha256": self.sha256,
            "character": self.character,
            "policy_version": self.policy_version,
            "knowledge_bundle_id": self.knowledge_bundle_id,
            "seed_selection": self.seed_selection,
            "step_cap_rationale": self.step_cap_rationale,
            "cases": [
                case.to_json()
                for case in self.cases
                if case.case_id not in excluded_case_ids
            ],
            "acceptance": self.global_acceptance.to_json(),
        }
        if self.schema_version == FRESH_SUITE_SCHEMA_VERSION:
            if self.baseline:
                payload["baseline"] = {
                    "entry_ids": [entry.entry_id for entry in self.baseline]
                }
            if self.fresh_sample is not None:
                payload["fresh_sample"] = self.fresh_sample.to_json()
        return payload


def load_suite(path: Path) -> EvaluationSuite:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise SuiteValidationError(
            f"evaluation suite cannot be read: {error}"
        ) from error
    try:
        payload = load_json_object(content.decode("utf-8"), "evaluation suite")
        schema_version = integer_value(
            payload.get("schema_version"), "suite schema_version"
        )
        digest = hashlib.sha256(content).hexdigest()
        if schema_version == LEGACY_SUITE_SCHEMA_VERSION:
            return _parse_schema_1_suite(payload, path, digest)
        if schema_version in (SUITE_SCHEMA_VERSION, FRESH_SUITE_SCHEMA_VERSION):
            if "environment" in payload or "seeds" in payload:
                raise ContractError(
                    f"suite schema_version {schema_version} requires cases rather than "
                    "schema-1 environment and seeds"
                )
            if schema_version == SUITE_SCHEMA_VERSION:
                return _parse_schema_2_suite(payload, path, digest)
            return _parse_schema_3_suite(payload, path, digest)
        raise ContractError(
            "suite schema_version must be "
            f"{LEGACY_SUITE_SCHEMA_VERSION}, {SUITE_SCHEMA_VERSION}, "
            f"or {FRESH_SUITE_SCHEMA_VERSION}"
        )
    except (ContractError, UnicodeDecodeError) as error:
        raise SuiteValidationError(
            f"invalid evaluation suite {path}: {error}"
        ) from error


def _suite_identifier(value: object, name: str) -> str:
    identifier = string_value(value, name, minimum=1, maximum=80)
    if not _IDENTIFIER.fullmatch(identifier):
        raise ContractError(f"{name} must be a lowercase hyphenated identifier")
    return identifier


def _parse_schema_1_suite(value: object, path: Path, digest: str) -> EvaluationSuite:
    payload = object_value(
        value,
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
    if integer_value(payload["schema_version"], "suite schema_version") != 1:
        raise ContractError("suite schema_version must be 1")
    suite_id = _suite_identifier(payload["suite_id"], "suite_id")
    environment = string_value(payload["environment"], "suite environment")
    if environment != STAIRCASE_TASK.environment.value:
        raise ContractError(
            f"suite environment must be {STAIRCASE_TASK.environment.value}"
        )
    character = string_value(payload["character"], "suite character")
    if character != CHARACTER:
        raise ContractError(f"suite character must be {CHARACTER}")
    seeds = _suite_seeds(payload["seeds"], "suite", exact_count=SUITE_SEED_COUNT)
    if MILESTONE_REFERENCE_SEED not in seeds:
        raise ContractError(f"suite seeds must include seed {MILESTONE_REFERENCE_SEED}")
    max_steps = _step_cap(payload["max_episode_steps"], "suite")
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
    case_acceptance = _case_acceptance(
        {
            "min_successes": acceptance_payload["min_task_successes"],
            "required_success_seeds": acceptance_payload["required_success_seeds"],
        },
        seeds,
        "suite acceptance",
    )
    global_acceptance = _global_acceptance(
        {
            "max_invalid_actions": acceptance_payload["max_invalid_actions"],
            "max_gate_rejections": acceptance_payload["max_gate_rejections"],
            "require_complete_records": acceptance_payload["require_complete_records"],
        },
        "suite acceptance",
    )
    case = EvaluationCase(
        case_id="staircase",
        task=STAIRCASE_TASK,
        seeds=seeds,
        max_episode_steps=max_steps,
        acceptance=case_acceptance,
    )
    return EvaluationSuite(
        schema_version=LEGACY_SUITE_SCHEMA_VERSION,
        suite_id=suite_id,
        character=character,
        policy_version=SCHEMA_1_POLICY_VERSION,
        knowledge_bundle_id=None,
        seed_selection=_suite_text(payload["seed_selection"], "suite seed_selection"),
        step_cap_rationale=_suite_text(
            payload["step_cap_rationale"], "suite step_cap_rationale"
        ),
        cases=(case,),
        global_acceptance=global_acceptance,
        path=path,
        sha256=digest,
    )


def _parse_schema_2_suite(value: object, path: Path, digest: str) -> EvaluationSuite:
    payload = object_value(
        value,
        "evaluation suite",
        {
            "schema_version",
            "suite_id",
            "character",
            "policy_version",
            "knowledge_bundle_id",
            "seed_selection",
            "step_cap_rationale",
            "cases",
            "acceptance",
        },
    )
    cases_payload = array_value(payload["cases"], "suite cases")
    if not cases_payload:
        raise ContractError("suite cases must not be empty")
    cases = tuple(_parse_case(item, index) for index, item in enumerate(cases_payload))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("suite case_id values must be unique")
    character = string_value(payload["character"], "suite character")
    if character != CHARACTER:
        raise ContractError(f"suite character must be {CHARACTER}")
    return EvaluationSuite(
        schema_version=SUITE_SCHEMA_VERSION,
        suite_id=_suite_identifier(payload["suite_id"], "suite_id"),
        character=character,
        policy_version=_suite_identifier(
            payload["policy_version"], "suite policy_version"
        ),
        knowledge_bundle_id=_suite_identifier(
            payload["knowledge_bundle_id"], "suite knowledge_bundle_id"
        ),
        seed_selection=_suite_text(payload["seed_selection"], "suite seed_selection"),
        step_cap_rationale=_suite_text(
            payload["step_cap_rationale"], "suite step_cap_rationale"
        ),
        cases=cases,
        global_acceptance=_global_acceptance(payload["acceptance"], "suite acceptance"),
        path=path,
        sha256=digest,
    )


def _parse_schema_3_suite(value: object, path: Path, digest: str) -> EvaluationSuite:
    from nethack_agent.seed_catalog import (
        CATALOG_FILE_NAME,
        MAX_SEED,
        CatalogError,
        load_catalog,
    )

    payload = object_value(
        value,
        "evaluation suite",
        {
            "schema_version",
            "suite_id",
            "character",
            "policy_version",
            "knowledge_bundle_id",
            "seed_selection",
            "step_cap_rationale",
            "acceptance",
        },
        optional={"cases", "baseline", "fresh_sample"},
    )
    policy_version = _suite_identifier(
        payload["policy_version"], "suite policy_version"
    )
    cases_payload = array_value(payload.get("cases", []), "suite cases")
    if "cases" in payload and not cases_payload:
        raise ContractError("suite cases must not be empty")
    ordinary = tuple(
        _parse_case(item, index) for index, item in enumerate(cases_payload)
    )
    baseline: tuple[CatalogEntry, ...] = ()
    catalog_path: Path | None = None
    catalog_sha256: str | None = None
    if "baseline" in payload:
        entry_payload = object_value(
            payload["baseline"], "suite baseline", {"entry_ids"}
        )
        entry_ids = tuple(
            _suite_identifier(item, "suite baseline entry_id")
            for item in array_value(
                entry_payload["entry_ids"], "suite baseline entry_ids"
            )
        )
        if not entry_ids:
            raise ContractError("suite baseline entry_ids must not be empty")
        if len(entry_ids) != len(set(entry_ids)):
            raise ContractError("suite baseline entry_ids must be unique")
        catalog_path = path.parent / CATALOG_FILE_NAME
        try:
            content = catalog_path.read_bytes()
            catalog = load_catalog(catalog_path, content=content)
        except OSError as error:
            raise ContractError(
                f"seed catalog {catalog_path} cannot be read: {error}"
            ) from error
        except CatalogError as error:
            raise ContractError(str(error)) from error
        if catalog.policy_version != policy_version:
            raise ContractError(
                f"suite baseline catalog policy_version {catalog.policy_version} "
                f"does not match suite policy_version {policy_version}"
            )
        catalog_sha256 = hashlib.sha256(content).hexdigest()
        by_id = {entry.entry_id: entry for entry in catalog.entries}
        unknown = sorted(set(entry_ids) - by_id.keys())
        if unknown:
            raise ContractError(f"suite baseline unknown catalog entry_id: {unknown}")
        baseline = tuple(by_id[entry_id] for entry_id in entry_ids)
    fresh: FreshSample | None = None
    if "fresh_sample" in payload:
        value = object_value(
            payload["fresh_sample"],
            "suite fresh_sample",
            {"case_id", "task", "max_episode_steps", "count", "range", "acceptance"},
        )
        bounds = array_value(value["range"], "suite fresh_sample range")
        if len(bounds) != 2:
            raise ContractError("suite fresh_sample range must contain two bounds")
        first, last = (
            integer_value(
                bound, "suite fresh_sample range bound", minimum=1, maximum=MAX_SEED
            )
            for bound in bounds
        )
        if first > last:
            raise ContractError("suite fresh_sample range must not be reversed")
        count = integer_value(value["count"], "suite fresh_sample count", minimum=1)
        if count > last - first + 1:
            raise ContractError("suite fresh_sample count exceeds available range")
        acceptance_payload = object_value(
            value["acceptance"],
            "suite fresh_sample acceptance",
            {"min_success_rate"},
            optional={"metric_thresholds"},
        )
        rate = number_value(
            acceptance_payload["min_success_rate"],
            "suite fresh_sample min_success_rate",
        )
        if not 0 <= rate <= 1:
            raise ContractError("suite fresh_sample min_success_rate must be in [0, 1]")
        fresh = FreshSample(
            case_id=_suite_identifier(value["case_id"], "suite fresh_sample case_id"),
            task=TaskSpec.from_json(value["task"], "suite fresh_sample task"),
            max_episode_steps=_step_cap(
                value["max_episode_steps"], "suite fresh_sample"
            ),
            count=count,
            seed_range=(first, last),
            acceptance=FreshAcceptance(
                min_success_rate=rate,
                metric_thresholds=(
                    _metric_thresholds(
                        acceptance_payload["metric_thresholds"], "suite fresh_sample"
                    )
                    if "metric_thresholds" in acceptance_payload
                    else ()
                ),
            ),
        )
    if not ordinary and not baseline and fresh is None:
        raise ContractError("suite requires cases, baseline, or fresh_sample")
    all_ids = [case.case_id for case in ordinary]
    all_ids.extend(entry.entry_id for entry in baseline)
    if fresh is not None:
        all_ids.append(fresh.case_id)
    if len(all_ids) != len(set(all_ids)):
        raise ContractError("suite case_id values must be unique across sections")
    character = string_value(payload["character"], "suite character")
    if character != CHARACTER:
        raise ContractError(f"suite character must be {CHARACTER}")
    return EvaluationSuite(
        schema_version=FRESH_SUITE_SCHEMA_VERSION,
        suite_id=_suite_identifier(payload["suite_id"], "suite_id"),
        character=character,
        policy_version=policy_version,
        knowledge_bundle_id=_suite_identifier(
            payload["knowledge_bundle_id"], "suite knowledge_bundle_id"
        ),
        seed_selection=_suite_text(payload["seed_selection"], "suite seed_selection"),
        step_cap_rationale=_suite_text(
            payload["step_cap_rationale"], "suite step_cap_rationale"
        ),
        cases=ordinary
        + tuple(
            EvaluationCase(
                entry.entry_id,
                entry.task,
                (entry.seed,),
                entry.max_episode_steps,
                CaseAcceptance(0, ()),
            )
            for entry in baseline
        ),
        global_acceptance=_global_acceptance(payload["acceptance"], "suite acceptance"),
        path=path,
        sha256=digest,
        baseline=baseline,
        fresh_sample=fresh,
        catalog_path=catalog_path,
        catalog_sha256=catalog_sha256,
    )


def _parse_case(value: object, index: int) -> EvaluationCase:
    name = f"suite case {index}"
    payload = object_value(
        value,
        name,
        {"case_id", "task", "seeds", "max_episode_steps", "acceptance"},
    )
    seeds = _suite_seeds(payload["seeds"], name)
    return EvaluationCase(
        case_id=_suite_identifier(payload["case_id"], f"{name} case_id"),
        task=TaskSpec.from_json(payload["task"], f"{name} task"),
        seeds=seeds,
        max_episode_steps=_step_cap(payload["max_episode_steps"], name),
        acceptance=_case_acceptance(payload["acceptance"], seeds, f"{name} acceptance"),
    )


def _suite_seeds(
    value: object, name: str, *, exact_count: int | None = None
) -> tuple[int, ...]:
    seeds = tuple(
        integer_value(seed, f"{name} seed", minimum=1, maximum=sys.maxsize)
        for seed in array_value(value, f"{name} seeds")
    )
    if exact_count is not None and len(seeds) != exact_count:
        raise ContractError(f"{name} must contain exactly {exact_count} seeds")
    if not seeds:
        raise ContractError(f"{name} seeds must not be empty")
    if len(seeds) != len(set(seeds)):
        raise ContractError(f"{name} seeds must be unique")
    return seeds


def _step_cap(value: object, name: str) -> int:
    return integer_value(value, f"{name} max_episode_steps", minimum=1, maximum=100_000)


def _suite_text(value: object, name: str) -> str:
    return string_value(value, name, minimum=1, maximum=2000, strip=True)


def _case_acceptance(
    value: object, seeds: tuple[int, ...], name: str
) -> CaseAcceptance:
    payload = object_value(
        value,
        name,
        _CASE_ACCEPTANCE_FIELDS,
        optional=_CASE_ACCEPTANCE_OPTIONAL_FIELDS,
    )
    required = tuple(
        integer_value(seed, f"{name} required success seed", minimum=1)
        for seed in array_value(
            payload["required_success_seeds"], f"{name} required_success_seeds"
        )
    )
    if len(required) != len(set(required)) or not set(required) <= set(seeds):
        raise ContractError(f"{name} required_success_seeds must be unique case seeds")
    thresholds = (
        _metric_thresholds(payload["metric_thresholds"], name)
        if "metric_thresholds" in payload
        else ()
    )
    return CaseAcceptance(
        min_successes=integer_value(
            payload["min_successes"],
            f"{name} min_successes",
            minimum=_minimum_successes(thresholds),
            maximum=len(seeds),
        ),
        required_success_seeds=required,
        metric_thresholds=thresholds,
    )


def _minimum_successes(thresholds: tuple[MetricThreshold, ...]) -> int:
    """A case gated by metric thresholds may require no objective success."""
    return 0 if thresholds else 1


def _global_acceptance(value: object, name: str) -> GlobalAcceptance:
    payload = object_value(
        value,
        name,
        {
            "max_invalid_actions",
            "max_gate_rejections",
            "require_complete_records",
        },
    )
    return GlobalAcceptance(
        max_invalid_actions=integer_value(
            payload["max_invalid_actions"], f"{name} max_invalid_actions", minimum=0
        ),
        max_gate_rejections=integer_value(
            payload["max_gate_rejections"],
            f"{name} max_gate_rejections",
            minimum=0,
        ),
        require_complete_records=boolean_value(
            payload["require_complete_records"], f"{name} require_complete_records"
        ),
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

    @property
    def shared(self) -> tuple[object, ...]:
        """Configuration that schema-2 requires to stay fixed across cases."""
        return (
            self.model,
            self.policy_version,
            self.knowledge_version,
            self.nle_version,
            self.character,
            self.ollama_num_ctx,
        )


class HungerState(Enum):
    SATIATED = "satiated"
    NOT_HUNGRY = "not_hungry"
    HUNGRY = "hungry"
    WEAK = "weak"
    FAINTING = "fainting"
    FAINTED = "fainted"
    STARVED = "starved"


_HUNGER_STATES: Final = tuple(HungerState)
_HUNGRY_ORDINAL: Final = _HUNGER_STATES.index(HungerState.HUNGRY)
_EXPLORATION_METRIC_FIELDS: Final = frozenset({"explored_cells", "worst_hunger_state"})
_FAILURE_DIAGNOSTIC_FIELDS: Final = frozenset(
    {"steps_by_skill", "search_steps", "first_hungry_turn", "hunger_at_death"}
)


@dataclass(frozen=True, slots=True)
class EpisodeMetrics:
    steps: int
    game_turns: int
    max_depth: int
    deepest_level: LevelKey | None
    levels_visited: tuple[LevelKey, ...]
    up_stair_traversals: int
    down_stair_traversals: int
    unknown_stair_probes: int
    probe_misses: int
    level_changes_without_stair_action: int
    objective_legs_completed: int
    final_gold: int
    final_score: int
    task_return: float
    hunger_states: tuple[HungerState, ...]
    final_hit_points: int
    final_experience_level: int
    death_cause: str
    # Sum over levels of the most map cells seen on each (NLE Scout's public
    # count). None only when read from a report written before this metric
    # existed: not recorded, which then also leaves worst_hunger_state None
    # and makes to_json omit both keys, so such JSON round-trips exactly.
    explored_cells: int | None
    # The worst live hunger state in NLE hunger order; for recorded metrics
    # None means the episode had no live observation.
    worst_hunger_state: HungerState | None
    # None for reports predating these diagnostics; a recorded empty map and
    # zero search steps are distinct from missing historical evidence.
    steps_by_skill: tuple[tuple[Skill, int], ...] | None = None
    search_steps: int | None = None
    first_hungry_turn: int | None = None
    # The last *live* hunger observation before death, not a zeroed terminal
    # observation or an unobservable claim about the exact death instant.
    hunger_at_death: HungerState | None = None

    def __post_init__(self) -> None:
        for name in (
            "steps",
            "game_turns",
            "max_depth",
            "up_stair_traversals",
            "down_stair_traversals",
            "unknown_stair_probes",
            "probe_misses",
            "level_changes_without_stair_action",
            "objective_legs_completed",
            "final_gold",
            "final_score",
            "final_hit_points",
            "final_experience_level",
        ):
            integer_value(getattr(self, name), f"episode metrics {name}", minimum=0)
        if self.deepest_level is not None and not isinstance(
            self.deepest_level, LevelKey
        ):
            raise TypeError("episode metrics deepest_level must be a LevelKey or None")
        if not all(isinstance(level, LevelKey) for level in self.levels_visited):
            raise TypeError(
                "episode metrics levels_visited must contain LevelKey values"
            )
        if len(self.levels_visited) != len(set(self.levels_visited)):
            raise ContractError("episode metrics levels_visited must be unique")
        if not all(isinstance(state, HungerState) for state in self.hunger_states):
            raise TypeError(
                "episode metrics hunger_states must contain HungerState values"
            )
        if len(self.hunger_states) != len(set(self.hunger_states)):
            raise ContractError("episode metrics hunger_states must be unique")
        object.__setattr__(
            self, "task_return", number_value(self.task_return, "episode task_return")
        )
        string_value(
            self.death_cause,
            "episode metrics death_cause",
            minimum=1,
            maximum=1000,
        )
        if self.explored_cells is None:
            if self.worst_hunger_state is not None:
                raise ContractError(
                    "episode metrics worst_hunger_state requires explored_cells"
                )
        else:
            integer_value(
                self.explored_cells, "episode metrics explored_cells", minimum=0
            )
        if self.worst_hunger_state is not None and not isinstance(
            self.worst_hunger_state, HungerState
        ):
            raise TypeError(
                "episode metrics worst_hunger_state must be a HungerState or None"
            )
        if (self.steps_by_skill is None) != (self.search_steps is None):
            raise ContractError(
                "episode metrics steps_by_skill and search_steps must appear together"
            )
        if self.steps_by_skill is None:
            if self.first_hungry_turn is not None or self.hunger_at_death is not None:
                raise ContractError("legacy episode metrics cannot record diagnostics")
        else:
            if not isinstance(self.steps_by_skill, tuple) or any(
                not isinstance(skill, Skill) or type(count) is not int or count < 0
                for skill, count in self.steps_by_skill
            ):
                raise ContractError(
                    "episode metrics steps_by_skill must count typed skills"
                )
            skills = [skill for skill, _ in self.steps_by_skill]
            if (
                len(skills) != len(set(skills))
                or sum(count for _, count in self.steps_by_skill) != self.steps
            ):
                raise ContractError(
                    "episode metrics skill counts must uniquely total steps"
                )
            integer_value(
                self.search_steps,
                "episode metrics search_steps",
                minimum=0,
                maximum=self.steps,
            )
            if self.first_hungry_turn is not None:
                integer_value(
                    self.first_hungry_turn,
                    "episode metrics first_hungry_turn",
                    minimum=0,
                )
            if self.hunger_at_death is not None and not isinstance(
                self.hunger_at_death, HungerState
            ):
                raise ContractError(
                    "episode metrics hunger_at_death must be a HungerState or None"
                )

    @classmethod
    def empty(cls) -> EpisodeMetrics:
        return cls(
            steps=0,
            game_turns=0,
            max_depth=0,
            deepest_level=None,
            levels_visited=(),
            up_stair_traversals=0,
            down_stair_traversals=0,
            unknown_stair_probes=0,
            probe_misses=0,
            level_changes_without_stair_action=0,
            objective_legs_completed=0,
            final_gold=0,
            final_score=0,
            task_return=0.0,
            hunger_states=(),
            final_hit_points=0,
            final_experience_level=0,
            death_cause="unknown",
            explored_cells=0,
            worst_hunger_state=None,
        )

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "steps": self.steps,
            "game_turns": self.game_turns,
            "max_depth": self.max_depth,
            "deepest_level": (
                None if self.deepest_level is None else self.deepest_level.to_json()
            ),
            "levels_visited": [level.to_json() for level in self.levels_visited],
            "up_stair_traversals": self.up_stair_traversals,
            "down_stair_traversals": self.down_stair_traversals,
            "unknown_stair_probes": self.unknown_stair_probes,
            "probe_misses": self.probe_misses,
            "level_changes_without_stair_action": (
                self.level_changes_without_stair_action
            ),
            "objective_legs_completed": self.objective_legs_completed,
            "final_gold": self.final_gold,
            "final_score": self.final_score,
            "task_return": round(self.task_return, 6),
            "hunger_states": [state.value for state in self.hunger_states],
            "final_hit_points": self.final_hit_points,
            "final_experience_level": self.final_experience_level,
            "death_cause": self.death_cause,
        }
        if self.explored_cells is not None:
            payload["explored_cells"] = self.explored_cells
            payload["worst_hunger_state"] = (
                None
                if self.worst_hunger_state is None
                else self.worst_hunger_state.value
            )
        if self.steps_by_skill is not None:
            payload["steps_by_skill"] = {
                skill.value: count for skill, count in self.steps_by_skill
            }
            payload["search_steps"] = self.search_steps
            payload["first_hungry_turn"] = self.first_hungry_turn
            payload["hunger_at_death"] = (
                None if self.hunger_at_death is None else self.hunger_at_death.value
            )
        return payload

    @classmethod
    def from_json(cls, value: object) -> EpisodeMetrics:
        fields = {
            "steps",
            "game_turns",
            "max_depth",
            "deepest_level",
            "levels_visited",
            "up_stair_traversals",
            "down_stair_traversals",
            "unknown_stair_probes",
            "probe_misses",
            "level_changes_without_stair_action",
            "objective_legs_completed",
            "final_gold",
            "final_score",
            "task_return",
            "hunger_states",
            "final_hit_points",
            "final_experience_level",
            "death_cause",
        }
        # Reports written before exploration and worst hunger were recorded
        # lack both keys; one without the other is malformed.
        payload = object_value(
            value,
            "episode metrics",
            fields,
            optional=_EXPLORATION_METRIC_FIELDS | _FAILURE_DIAGNOSTIC_FIELDS,
        )
        recorded = _EXPLORATION_METRIC_FIELDS & payload.keys()
        if recorded and recorded != _EXPLORATION_METRIC_FIELDS:
            raise ContractError(
                "episode metrics explored_cells and worst_hunger_state must be "
                "recorded together"
            )
        diagnostics = _FAILURE_DIAGNOSTIC_FIELDS & payload.keys()
        if diagnostics and diagnostics != _FAILURE_DIAGNOSTIC_FIELDS:
            raise ContractError(
                "episode metrics failure diagnostics must be recorded together"
            )
        deepest = payload["deepest_level"]
        worst = payload.get("worst_hunger_state")
        return cls(
            steps=integer_value(payload["steps"], "episode metrics steps", minimum=0),
            game_turns=integer_value(
                payload["game_turns"], "episode metrics game_turns", minimum=0
            ),
            max_depth=integer_value(
                payload["max_depth"], "episode metrics max_depth", minimum=0
            ),
            deepest_level=(
                None
                if deepest is None
                else LevelKey.from_json(deepest, "episode metrics deepest_level")
            ),
            levels_visited=tuple(
                LevelKey.from_json(item, "episode metrics visited level")
                for item in array_value(
                    payload["levels_visited"], "episode metrics levels_visited"
                )
            ),
            up_stair_traversals=integer_value(
                payload["up_stair_traversals"],
                "episode metrics up_stair_traversals",
                minimum=0,
            ),
            down_stair_traversals=integer_value(
                payload["down_stair_traversals"],
                "episode metrics down_stair_traversals",
                minimum=0,
            ),
            unknown_stair_probes=integer_value(
                payload["unknown_stair_probes"],
                "episode metrics unknown_stair_probes",
                minimum=0,
            ),
            probe_misses=integer_value(
                payload["probe_misses"], "episode metrics probe_misses", minimum=0
            ),
            level_changes_without_stair_action=integer_value(
                payload["level_changes_without_stair_action"],
                "episode metrics level_changes_without_stair_action",
                minimum=0,
            ),
            objective_legs_completed=integer_value(
                payload["objective_legs_completed"],
                "episode metrics objective_legs_completed",
                minimum=0,
            ),
            final_gold=integer_value(
                payload["final_gold"], "episode metrics final_gold", minimum=0
            ),
            final_score=integer_value(
                payload["final_score"], "episode metrics final_score", minimum=0
            ),
            task_return=number_value(
                payload["task_return"], "episode metrics task_return"
            ),
            hunger_states=tuple(
                enum_value(item, "episode metrics hunger state", HungerState)
                for item in array_value(
                    payload["hunger_states"], "episode metrics hunger_states"
                )
            ),
            final_hit_points=integer_value(
                payload["final_hit_points"],
                "episode metrics final_hit_points",
                minimum=0,
            ),
            final_experience_level=integer_value(
                payload["final_experience_level"],
                "episode metrics final_experience_level",
                minimum=0,
            ),
            death_cause=string_value(
                payload["death_cause"],
                "episode metrics death_cause",
                minimum=1,
                maximum=1000,
            ),
            explored_cells=(
                integer_value(
                    payload["explored_cells"],
                    "episode metrics explored_cells",
                    minimum=0,
                )
                if recorded
                else None
            ),
            worst_hunger_state=(
                None
                if worst is None
                else enum_value(
                    worst, "episode metrics worst_hunger_state", HungerState
                )
            ),
            steps_by_skill=(
                tuple(
                    (
                        enum_value(name, "episode metrics skill", Skill),
                        integer_value(count, "episode metrics skill steps", minimum=0),
                    )
                    for name, count in object_value(
                        payload["steps_by_skill"],
                        "episode metrics steps_by_skill",
                        set(),
                        optional={skill.value for skill in Skill},
                    ).items()
                )
                if diagnostics
                else None
            ),
            search_steps=(
                integer_value(
                    payload["search_steps"], "episode metrics search_steps", minimum=0
                )
                if diagnostics
                else None
            ),
            first_hungry_turn=(
                None
                if not diagnostics or payload["first_hungry_turn"] is None
                else integer_value(
                    payload["first_hungry_turn"],
                    "episode metrics first_hungry_turn",
                    minimum=0,
                )
            ),
            hunger_at_death=(
                None
                if not diagnostics or payload["hunger_at_death"] is None
                else enum_value(
                    payload["hunger_at_death"],
                    "episode metrics hunger_at_death",
                    HungerState,
                )
            ),
        )


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
    case_id: str = "staircase"
    metrics: EpisodeMetrics = field(default_factory=EpisodeMetrics.empty)

    @property
    def integrity_ok(self) -> bool:
        return not self.integrity_problems

    @property
    def task_success(self) -> bool:
        return self.outcome is RunOutcome.TASK_SUCCESS

    def successful_for(self, case: EvaluationCase) -> bool:
        if case.task.environment is NleTask.STAIRCASE:
            return self.task_success
        return self.metrics.objective_legs_completed == len(case.task.objective.legs)

    def to_json(self) -> dict[str, object]:
        metrics = self.metrics
        if metrics.steps == 0 and self.steps:
            # Source-compatible construction for callers that predate schema 3;
            # evaluator-created results always supply complete metrics.
            metrics = replace(metrics, steps=self.steps)
        return {
            "case_id": self.case_id,
            "seed": self.seed,
            "run_id": self.run_id,
            "outcome": self.outcome.value if self.outcome else None,
            "final_state": self.final_state.value if self.final_state else None,
            "ended_by": self.ended_by,
            "steps": self.steps,
            "metrics": metrics.to_json(),
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
    case: EvaluationCase | None = None,
) -> SeedResult:
    case = case or suite.cases[0]
    problems: list[str] = []
    step_payloads: list[StepPayload] = []
    successful: list[DecisionMetrics] = []
    failed: list[DecisionMetrics] = []
    sources = Counter({source.value: 0 for source in ActionSelectionSource})
    gate_rejections = 0
    decision_failures = 0
    invalid_actions = 0
    legal_actions = None
    task = record.task or STAIRCASE_TASK
    level_changes_allowed = task.objective.changes_level
    decided_on: ProjectedObservation | None = None
    initial_observation: ProjectedObservation | None = None
    prior_prayers = 0
    last_prayer_turn: int | None = None
    kill_count = 0
    pending_prayer: PrayerEvidence | None = None
    prayer_memory = DungeonMemory()
    corpse_kills: dict[tuple[LevelKey, int, int], CorpseKill] = {}
    consumed_corpses: set[tuple[LevelKey, int, int, int]] = set()
    pending_corpse: CorpseEvidence | None = None
    pending_meal: CorpseEvidence | None = None

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
        decided_on = started[0].payload.observation
        initial_observation = decided_on
        kill_count = decided_on.message.count("You kill")
        if _observation_is_live(decided_on):
            prayer_memory.observe(decided_on)

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
            valid = _action_is_valid(
                payload,
                legal_actions,
                decided_on,
                level_changes_allowed,
                task.action_profile,
                prior_prayers=prior_prayers,
                last_prayer_turn=last_prayer_turn,
                kill_count=kill_count,
                pending_prayer=pending_prayer,
                corpse_kills=corpse_kills,
                consumed_corpses=consumed_corpses,
                pending_corpse=pending_corpse,
                pending_meal=pending_meal,
                dungeon_memory=prayer_memory,
                on_altar=(
                    prayer_memory.current.cmap(prayer_memory.current.position) == 27
                    or (
                        decided_on is not None and "altar" in decided_on.message.lower()
                    )
                )
                if decided_on is not None and _observation_is_live(decided_on)
                else False,
            )
            if not valid:
                invalid_actions += 1
            pending_prayer = (
                payload.selection.intent.prayer
                if valid
                and payload.action.name == PRAY_ACTION_NAME
                and payload.selection.intent is not None
                else None
            )
            if (
                valid
                and payload.action.name == "Command.EAT"
                and payload.selection.skill is Skill.CORPSE
                and payload.selection.intent is not None
            ):
                evidence = payload.selection.intent.corpse
                if payload.observation.prompt.active:
                    pending_corpse = evidence
                else:
                    consumed_corpses.add(
                        (
                            _observation_level(decided_on),
                            evidence.cell.x,
                            evidence.cell.y,
                            evidence.kill_turn,
                        )
                    )
                    if (
                        "You start eating" in payload.observation.message
                        or "You begin eating" in payload.observation.message
                    ) and classify_corpse_outcome(
                        evidence.name, payload.observation.message
                    ) is None:
                        pending_meal = evidence
            elif pending_corpse is not None:
                evidence = pending_corpse
                if payload.action.command in (YES_COMMAND, ord("n"), ESC_COMMAND):
                    consumed_corpses.add(
                        (
                            _observation_level(decided_on),
                            evidence.cell.x,
                            evidence.cell.y,
                            evidence.kill_turn,
                        )
                    )
                    if (
                        valid
                        and payload.action.command == YES_COMMAND
                        and not payload.terminated
                        and not payload.truncated
                        and classify_corpse_outcome(
                            evidence.name, payload.observation.message
                        )
                        is None
                    ):
                        pending_meal = evidence
                pending_corpse = None
            if pending_meal is not None and (
                classify_corpse_outcome(pending_meal.name, payload.observation.message)
                is not None
                or payload.terminated
                or payload.truncated
            ):
                pending_meal = None
            if decided_on is not None:
                kill = observed_corpse_kill(
                    decided_on, payload.action, payload.observation
                )
                if kill is not None:
                    corpse_kills[(kill.level, kill.cell.x, kill.cell.y)] = kill
            if payload.action.name == PRAY_ACTION_NAME:
                prior_prayers += 1
                if decided_on is not None:
                    last_prayer_turn = decided_on.player.turn
            kill_count += payload.observation.message.count("You kill")
            gold_error = _gold_intent_error(payload, decided_on)
            if gold_error is not None:
                problems.append(f"step {len(step_payloads)} {gold_error}")
            decided_on = payload.observation
            if _observation_is_live(decided_on):
                prayer_memory.observe(decided_on)
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
    if (
        record.environment != case.task.environment.value
        or record.character != suite.character
        or task != case.task
    ):
        problems.append("run record task or character differs from the suite case")
    if record.max_episode_steps != case.max_episode_steps:
        problems.append("run record step cap differs from the suite case")
    if len(step_payloads) > case.max_episode_steps:
        problems.append("run exceeded the suite case step cap")

    ttyrec_path, ttyrec_exists = _ttyrec(record.ttyrec_path, data_directory)
    if record.ttyrec_path is None:
        problems.append("run record has no ttyrec reference")
    elif not ttyrec_exists:
        problems.append("referenced ttyrec is missing or empty")

    explored, replay_problems = _replay_exhaustion(
        task, legal_actions, initial_observation, step_payloads
    )
    problems.extend(replay_problems)
    metrics = _episode_metrics(
        initial_observation,
        step_payloads,
        case.task,
        record.outcome,
        record.ttyrec_path,
        explored,
    )
    if metrics.steps != len(step_payloads):
        problems.append("episode metrics step count differs from the event log")
    completed = metrics.objective_legs_completed
    objective_size = len(case.task.objective.legs)
    if (
        case.task.environment is not NleTask.STAIRCASE
        and record.outcome is RunOutcome.OBJECTIVE_COMPLETE
        and completed != objective_size
    ):
        problems.append(
            "objective_complete outcome is not supported by the stored observations"
        )
    if (
        case.task.environment is not NleTask.STAIRCASE
        and completed == objective_size
        and record.outcome is not RunOutcome.OBJECTIVE_COMPLETE
    ):
        problems.append(
            "stored observations complete the objective without objective_complete"
        )

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
        case_id=case.case_id,
        metrics=metrics,
    )


def _replay_exhaustion(
    task: TaskSpec,
    legal_actions: tuple[LegalAction, ...] | None,
    initial: ProjectedObservation | None,
    steps: Sequence[StepPayload],
) -> tuple[tuple[frozenset[LevelKey], ...], list[str]]:
    """Re-derive exhaustion markers; return the confirmed levels after each step.

    A marker counts only when replaying the coordinator's memory shows that
    deterministic exploration was exhausted on the observation the step was
    decided on. Runs without markers or explore_dungeon legs need no replay.
    """
    none: tuple[frozenset[LevelKey], ...] = (frozenset(),) * len(steps)
    needed = any(
        isinstance(leg, ExploreDungeonLeg) for leg in task.objective.legs
    ) or any(payload.selection.exhausted_level is not None for payload in steps)
    if not needed:
        return none, []
    if legal_actions is None or initial is None:
        return none, ["exhaustion markers cannot be replayed without run_started"]
    replay = ExplorationReplay(task, legal_actions, initial)
    explored: list[frozenset[LevelKey]] = []
    problems: list[str] = []
    for number, payload in enumerate(steps, start=1):
        try:
            problem = replay.step(payload)
        except ValueError as error:
            problems.append(f"exploration replay failed at step {number}: {error}")
            explored.extend([frozenset(replay.explored)] * (len(steps) - len(explored)))
            break
        if problem is not None:
            problems.append(
                f"step {number} exhausted_level marker is not supported: {problem}"
            )
        explored.append(frozenset(replay.explored))
    return tuple(explored), problems


def _episode_metrics(
    initial: ProjectedObservation | None,
    steps: Sequence[StepPayload],
    task: TaskSpec,
    outcome: RunOutcome | None,
    ttyrec_path: str | None,
    explored: Sequence[frozenset[LevelKey]] | None = None,
) -> EpisodeMetrics:
    """Derive episode facts only from persisted public evidence.

    NLE zeroes bottom-line statistics in a terminal observation. Such an
    observation still proves that a step happened, but it is not a live level,
    turn, HP, hunger, or objective sample. The preceding live observation stays
    authoritative for those metrics. `explored` holds the levels whose
    exhaustion markers were confirmed after each step.
    """
    confirmed = explored or (frozenset(),) * len(steps)
    live: list[ProjectedObservation] = []
    samples: list[tuple[ProjectedObservation, frozenset[LevelKey]]] = []
    if initial is not None and _observation_is_live(initial):
        live.append(initial)
        samples.append((initial, frozenset()))
    previous = live[-1] if live else None
    up = 0
    down = 0
    probes = 0
    misses = 0
    changes_without_stairs = 0
    skill_counts: Counter[Skill] = Counter()
    search_steps = 0
    first_hungry_turn = next(
        (
            observation.player.turn
            for observation in live
            if observation.player.hunger >= _HUNGRY_ORDINAL
        ),
        None,
    )
    for payload, levels_explored in zip(steps, confirmed, strict=True):
        skill_counts[payload.selection.skill] += 1
        search_steps += payload.action.name == "Command.SEARCH"
        direction = LEVEL_CHANGE_ACTIONS.get(payload.action.name)
        intent = payload.selection.intent
        destination = None if intent is None else intent.destination
        unknown_probe = (
            direction is not None
            and destination is not None
            and destination.stair is not None
            and destination.stair.kind is StairIdentityKind.UNKNOWN
        )
        if unknown_probe:
            probes += 1
        after = payload.observation
        if not _observation_is_live(after):
            continue
        live.append(after)
        samples.append((after, levels_explored))
        if first_hungry_turn is None and after.player.hunger >= _HUNGRY_ORDINAL:
            first_hungry_turn = after.player.turn
        if previous is not None:
            changed = _observation_level(previous) != _observation_level(after)
            if changed and direction is StairDirection.UP:
                up += 1
            elif changed and direction is StairDirection.DOWN:
                down += 1
            elif changed:
                changes_without_stairs += 1
            elif unknown_probe:
                misses += 1
        previous = after

    levels = tuple(
        dict.fromkeys(_observation_level(observation) for observation in live)
    )
    max_depth = max((observation.player.depth for observation in live), default=0)
    deepest_level = next(
        (
            _observation_level(observation)
            for observation in live
            if observation.player.depth == max_depth
        ),
        None,
    )
    final = live[-1].player if live else None
    hunger = tuple(
        dict.fromkeys(
            _HUNGER_STATES[observation.player.hunger]
            for observation in live
            if 0 <= observation.player.hunger < len(_HUNGER_STATES)
        )
    )
    worst_hunger = max(hunger, key=_HUNGER_STATES.index, default=None)
    legs_completed = _objective_legs_completed(task, samples)
    # Staircase's successful end state is NLE-owned and its terminal observation
    # has no live player cell. That task result is the direct evidence for its
    # equivalent single stand-on-downstairs objective.
    if task.environment is NleTask.STAIRCASE and outcome is RunOutcome.TASK_SUCCESS:
        legs_completed = len(task.objective.legs)
    return EpisodeMetrics(
        steps=len(steps),
        game_turns=max((observation.player.turn for observation in live), default=0),
        max_depth=max_depth,
        deepest_level=deepest_level,
        levels_visited=levels,
        up_stair_traversals=up,
        down_stair_traversals=down,
        unknown_stair_probes=probes,
        probe_misses=misses,
        level_changes_without_stair_action=changes_without_stairs,
        objective_legs_completed=legs_completed,
        final_gold=0 if final is None else final.gold,
        final_score=0 if final is None else final.score,
        task_return=sum(payload.reward for payload in steps),
        hunger_states=hunger,
        final_hit_points=0 if final is None else final.hit_points,
        final_experience_level=0 if final is None else final.experience_level,
        death_cause=_death_cause(outcome, ttyrec_path),
        explored_cells=_explored_cells(live),
        worst_hunger_state=worst_hunger,
        steps_by_skill=tuple(
            (skill, skill_counts[skill]) for skill in Skill if skill_counts[skill]
        ),
        search_steps=search_steps,
        first_hungry_turn=first_hungry_turn,
        hunger_at_death=(
            _HUNGER_STATES[final.hunger]
            if outcome is RunOutcome.DEATH
            and final is not None
            and 0 <= final.hunger < len(_HUNGER_STATES)
            else None
        ),
    )


def _observation_is_live(observation: ProjectedObservation) -> bool:
    return observation.player.dungeon_level >= 1


def _explored_cells(live: Sequence[ProjectedObservation]) -> int:
    """Sum each level's most seen map cells, as NLE Scout counts exploration.

    Scout rewards changes in the count of glyphs other than GLYPH_CMAP_OFF per
    (dungeon, level); that count is public in every observation's glyph map.
    """
    seen: dict[LevelKey, int] = {}
    for observation in live:
        level = _observation_level(observation)
        cells = sum(
            glyph != nethack.GLYPH_CMAP_OFF
            for row in observation.map.glyph_rows
            for glyph in row
        )
        seen[level] = max(seen.get(level, 0), cells)
    return sum(seen.values())


def _observation_level(observation: ProjectedObservation) -> LevelKey:
    player = observation.player
    return LevelKey(player.dungeon_number, player.dungeon_level)


def _objective_legs_completed(
    task: TaskSpec,
    samples: Sequence[tuple[ProjectedObservation, frozenset[LevelKey]]],
) -> int:
    index = 0
    legs = task.objective.legs
    for observation, explored in samples:
        while index < len(legs) and _observation_completes_leg(
            observation, legs[index], explored
        ):
            index += 1
    return index


def _observation_completes_leg(
    observation: ProjectedObservation,
    leg: ObjectiveLeg,
    explored: frozenset[LevelKey],
) -> bool:
    """Whether a live observation, with the confirmed explored levels, meets `leg`."""
    level = _observation_level(observation)
    if isinstance(leg, ReachLevelLeg):
        return level == leg.level
    if isinstance(leg, EnterDungeonLeg):
        return level.dungeon_number == leg.dungeon_number
    if isinstance(leg, ExploreDungeonLeg):
        return set(leg.levels) <= explored
    if isinstance(leg, FindOracleLeg):
        raise ValueError(f"{leg.kind.value} legs have no evaluation yet")
    player = observation.player
    glyph = observation.map.glyph_rows[player.y][player.x]
    cmap = nethack.glyph_to_cmap(glyph) if nethack.glyph_is_cmap(glyph) else None
    message = observation.message.lower()
    direction = (
        StairDirection.UP
        if cmap == 23 or "staircase up here" in message
        else StairDirection.DOWN
        if cmap == 24 or "staircase down here" in message
        else None
    )
    # Public observations prove direction but not a main/branch identity while
    # the hero covers a staircase. Current committed stand goals use `any`.
    return (
        direction is leg.target.direction
        and leg.target.connection is StairConnection.ANY
    )


def _death_cause(outcome: RunOutcome | None, ttyrec_path: str | None) -> str:
    if outcome is not RunOutcome.DEATH or ttyrec_path is None:
        return "unknown"
    ttyrec = Path(ttyrec_path)
    try:
        xlogs = sorted(ttyrec.parent.glob("*.xlogfile"))
    except OSError:
        return "unknown"
    for path in xlogs:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            fields = {}
            for item in line.split("\t"):
                key, separator, value = item.partition("=")
                if separator:
                    fields[key] = value
            if fields.get("ttyrecname") == ttyrec.name:
                cause = fields.get("death", "").strip()
                return cause[:1000] if cause else "unknown"
    return "unknown"


def _observed_corpse_outcome(name: str, payload: StepPayload) -> CorpseOutcome | None:
    if (
        payload.terminated
        or payload.truncated
        or not _observation_is_live(payload.observation)
    ):
        return None
    kind = classify_corpse_outcome(name, payload.observation.message)
    if kind is None:
        return None
    return CorpseOutcome(
        kind,
        payload.observation.player.turn,
        payload.observation.player.hunger,
        payload.observation.message,
    )


def _action_is_valid(
    payload: StepPayload,
    legal_actions: object,
    decided_on: ProjectedObservation | None,
    level_changes_allowed: bool,
    action_profile: ActionProfile,
    *,
    prior_prayers: int = 0,
    last_prayer_turn: int | None = None,
    kill_count: int = 0,
    pending_prayer: PrayerEvidence | None = None,
    on_altar: bool = False,
    corpse_kills: dict[tuple[LevelKey, int, int], CorpseKill] | None = None,
    consumed_corpses: set[tuple[LevelKey, int, int, int]] | None = None,
    pending_corpse: CorpseEvidence | None = None,
    pending_meal: CorpseEvidence | None = None,
    dungeon_memory: DungeonMemory | None = None,
) -> bool:
    if not isinstance(legal_actions, tuple):
        return False
    action = payload.action
    if not (
        0 <= action.index < len(legal_actions)
        and legal_actions[action.index] == action
        and payload.selection.action_index == action.index
    ):
        return False
    selection = payload.selection
    if action.name == PRAY_ACTION_NAME and (
        action_profile is not ActionProfile.NLE_SURVIVAL_ACTIONS
        or decided_on is None
        or not _observation_is_live(decided_on)
        or prayer_action_error(
            action.name,
            selection,
            permit=PrayerPermit(decided_on.player.turn),
            turn=decided_on.player.turn,
            hunger=decided_on.player.hunger,
            prompt_active=decided_on.prompt.active,
            ration_available=bool(safe_food_rations(decided_on)),
            prior_prayers=prior_prayers,
            last_prayer_turn=last_prayer_turn,
            on_altar=on_altar,
        )
        is not None
        or selection.intent is None
        or selection.intent.prayer is None
        or selection.intent.prayer.kill_count != kill_count
    ):
        return False
    if (
        selection.skill is Skill.CORPSE
        and selection.intent is not None
        and selection.intent.destination is not None
        and selection.intent.destination.kind is DestinationKind.CORPSE
        and _corpse_route_error(
            payload, decided_on, corpse_kills, consumed_corpses, dungeon_memory
        )
        is not None
    ):
        return False
    if action.name == "Command.EAT":
        if (
            decided_on is None
            or pending_meal is not None
            or (
                selection.skill is Skill.CORPSE
                and action_profile is not ActionProfile.NLE_SURVIVAL_ACTIONS
            )
        ):
            return False
        corpse = selection.intent.corpse if selection.intent is not None else None
        observed = None
        if (
            corpse is not None
            and corpse_kills is not None
            and consumed_corpses is not None
        ):
            level = _observation_level(decided_on)
            kill = corpse_kills.get((level, corpse.cell.x, corpse.cell.y))
            if (
                kill is not None
                and (level, corpse.cell.x, corpse.cell.y, kill.turn)
                not in consumed_corpses
            ):
                observed = eligible_corpse(kill, decided_on)
        if (
            hunger_action_error(
                action.name,
                selection,
                hunger=decided_on.player.hunger,
                prompt_active=decided_on.prompt.active,
                safe_ration_available=bool(safe_food_rations(decided_on)),
                corpse_evidence=corpse,
                observed_corpse=observed,
                observation=decided_on,
            )
            is not None
        ):
            return False
    if selection.skill is Skill.CORPSE and action.name == "MiscDirection.WAIT":
        intent = selection.intent
        if (
            action_profile is not ActionProfile.NLE_SURVIVAL_ACTIONS
            or pending_meal is None
            or intent is None
            or intent.corpse is None
            or intent.destination is not None
            or intent.attack_target is not None
            or intent.path is not None
            or decided_on is None
            or decided_on.prompt.active
            or intent.corpse
            != replace(
                pending_meal,
                outcome=_observed_corpse_outcome(pending_meal.name, payload),
            )
        ):
            return False
    if (
        action_profile is ActionProfile.NLE_SURVIVAL_ACTIONS
        and action.command == ord("n")
        and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        and selection.skill is Skill.HUNGER
        and (
            decided_on is None
            or not decided_on.prompt.single_character_choice
            or parse_floor_corpse_prompt(decided_on.message) is None
        )
    ):
        return False
    if (
        selection.skill is Skill.CORPSE
        and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        and action.command in (ord("n"), ESC_COMMAND)
    ):
        intent = selection.intent
        if (
            action_profile is not ActionProfile.NLE_SURVIVAL_ACTIONS
            or pending_corpse is None
            or intent is None
            or intent.corpse is None
            or decided_on is None
            or corpse_kills is None
            or consumed_corpses is None
            or not decided_on.prompt.active
            or (decided_on.player.x, decided_on.player.y)
            != (pending_corpse.cell.x, pending_corpse.cell.y)
            or not 0 <= decided_on.player.turn - pending_corpse.kill_turn <= 19
        ):
            return False
        level = _observation_level(decided_on)
        kill = corpse_kills.get((level, pending_corpse.cell.x, pending_corpse.cell.y))
        if (
            kill is None
            or kill.name != pending_corpse.name
            or kill.turn != pending_corpse.kill_turn
            or (level, kill.cell.x, kill.cell.y, kill.turn) in consumed_corpses
            or (
                action.command == ord("n")
                and (
                    not decided_on.prompt.single_character_choice
                    or parse_floor_corpse_prompt(decided_on.message) is None
                )
            )
            or (
                action.command == ESC_COMMAND
                and prompt_response_error(
                    action.name,
                    action.command,
                    selection,
                    prompt_active=decided_on.prompt.active,
                    item_selection=item_selection_commands(decided_on) is not None,
                    offered_commands=item_selection_commands(decided_on) or frozenset(),
                )
                is not None
            )
        ):
            return False
        expected = (
            None
            if payload.terminated or payload.truncated
            else CorpseOutcome(
                CorpseOutcomeKind.DECLINED,
                payload.observation.player.turn,
                payload.observation.player.hunger,
                payload.observation.message,
            )
        )
        if intent.corpse != replace(pending_corpse, outcome=expected):
            return False
    if pending_meal is not None and (
        (action.name == "MiscDirection.WAIT" and selection.skill is not Skill.CORPSE)
        or (
            action.name != "MiscDirection.WAIT"
            and (selection.intent is None or selection.intent.attack_target is None)
        )
    ):
        return False
    if (
        action_profile is ActionProfile.NLE_SURVIVAL_ACTIONS
        and action.command == YES_COMMAND
    ):
        if decided_on is None:
            return False
        offered = item_selection_commands(decided_on)
        prompt_kind = confirmation_prompt_kind(
            decided_on.message,
            single_choice=decided_on.prompt.single_character_choice,
            offered_item_commands=offered,
        )
        outcome_kind = (
            None
            if payload.terminated
            or payload.truncated
            or not _observation_is_live(payload.observation)
            else classify_prayer_outcome(
                payload.observation.player.hunger,
                payload.observation.message,
            )
        )
        prayer_outcome = (
            PrayerOutcome(
                payload.observation.player.turn,
                payload.observation.player.hunger,
                payload.observation.message,
                outcome_kind,
            )
            if outcome_kind is not None
            else None
        )
        prayer_permit = (
            PromptPermit(YES_COMMAND, PromptKind.PRAYER_CONFIRMATION)
            if _observation_is_live(decided_on)
            and prompt_kind is PromptKind.PRAYER_CONFIRMATION
            and pending_prayer is not None
            and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and selection.skill is Skill.PRAYER
            and selection.intent is not None
            and (payload.terminated or payload.truncated or prayer_outcome is not None)
            and selection.intent.prayer
            == replace(
                pending_prayer,
                outcome=prayer_outcome,
            )
            else None
        )
        corpse_permit = None
        if (
            prompt_kind is PromptKind.CORPSE_CONFIRMATION
            and selection.skill is Skill.CORPSE
            and pending_corpse is not None
            and corpse_kills is not None
            and consumed_corpses is not None
        ):
            level = _observation_level(decided_on)
            kill = corpse_kills.get(
                (level, pending_corpse.cell.x, pending_corpse.cell.y)
            )
            observed = (
                pending_corpse
                if kill is not None
                and kill.name == pending_corpse.name
                and kill.turn == pending_corpse.kill_turn
                and (level, kill.cell.x, kill.cell.y, kill.turn) not in consumed_corpses
                else None
            )
            intent_corpse = (
                selection.intent.corpse if selection.intent is not None else None
            )
            expected_outcome = _observed_corpse_outcome(pending_corpse.name, payload)
            if (
                intent_corpse is not None
                and intent_corpse.outcome == expected_outcome
                and corpse_confirmation_error(
                    action.command,
                    selection,
                    prompt_active=decided_on.prompt.single_character_choice,
                    prompt_message=decided_on.message,
                    corpse_evidence=pending_corpse,
                    observed_corpse=observed,
                    observation=decided_on,
                )
                is None
            ):
                corpse_permit = PromptPermit(
                    YES_COMMAND, PromptKind.CORPSE_CONFIRMATION
                )
        item_permit = (
            PromptPermit(YES_COMMAND, PromptKind.ITEM)
            if prompt_kind is PromptKind.ITEM
            and prompt_response_error(
                action.name,
                action.command,
                selection,
                prompt_active=decided_on.prompt.active,
                item_selection=True,
                offered_commands=offered or frozenset(),
            )
            is None
            else None
        )
        if (
            confirmation_answer_error(
                action.command,
                selection,
                prompt_active=decided_on.prompt.active,
                prompt_kind=prompt_kind,
                permit=prayer_permit or corpse_permit or item_permit,
            )
            is not None
        ):
            return False
    if (
        action_profile is not ActionProfile.NLE_TASK_ACTIONS
        and action.index < len(action_profile.actions)
        and action_profile.role(action_profile.actions[action.index])
        is ActionRole.PROMPT_KEY
    ):
        if decided_on is None:
            return False
        offered = item_selection_commands(decided_on)
        if (
            prompt_response_error(
                action.name,
                action.command,
                selection,
                prompt_active=decided_on.prompt.active,
                item_selection=offered is not None,
                offered_commands=offered or frozenset(),
            )
            is not None
        ):
            return False
    if action.name not in LEVEL_CHANGE_ACTIONS:
        return True
    return decided_on is not None and _level_change_allowed(
        payload, decided_on, level_changes_allowed
    )


def _level_change_allowed(
    payload: StepPayload,
    decided_on: ProjectedObservation,
    level_changes_allowed: bool,
) -> bool:
    """Audit a level change with the coordinator's permit predicate.

    The previous live observation is the state on which the action was
    selected. An unknown branch staircase is permitted only when the recorded
    intent explicitly preserves the coordinator's two-stair evidence; absence
    in a legacy event is unknown, never permission.
    """
    player = decided_on.player
    if player.dungeon_level < 1:
        return False
    return (
        level_change_error(
            payload.action.name,
            payload.selection,
            level_changes_allowed=level_changes_allowed,
            level=LevelKey(player.dungeon_number, player.dungeon_level),
            position=(player.x, player.y),
            prompt_active=decided_on.prompt.active,
            pair_known=(
                payload.selection.intent is not None
                and payload.selection.intent.destination is not None
                and getattr(payload.selection.intent.destination, "pair_known", None)
                is True
            ),
        )
        is None
    )


def _corpse_route_error(
    payload: StepPayload,
    decided_on: ProjectedObservation | None,
    kills: dict[tuple[LevelKey, int, int], CorpseKill] | None,
    consumed: set[tuple[LevelKey, int, int, int]] | None,
    memory: DungeonMemory | None,
) -> str | None:
    """Re-derive the kill, visible generic corpse, and bounded reachable route."""
    intent = payload.selection.intent
    assert intent is not None and intent.corpse is not None
    destination = intent.destination
    assert destination is not None
    evidence = intent.corpse
    if decided_on is None or kills is None or consumed is None:
        return "corpse route lacks observed kill history"
    level = _observation_level(decided_on)
    kill = kills.get((level, evidence.cell.x, evidence.cell.y))
    path = intent.path
    if (
        intent.level != level
        or kill is None
        or (level, evidence.cell.x, evidence.cell.y, kill.turn) in consumed
        or eligible_corpse(kill, decided_on) != evidence
        or destination.x != evidence.cell.x
        or destination.y != evidence.cell.y
        or path is None
        or not 1 <= len(path) <= 5
        or (decided_on.player.x, decided_on.player.y)
        == (evidence.cell.x, evidence.cell.y)
    ):
        return "corpse route requires a fresh observed kill on its destination"
    x, y = evidence.cell.x, evidence.cell.y
    if decided_on.map.rows[y][x] != "%" or not nethack.glyph_is_body(
        decided_on.map.glyph_rows[y][x]
    ):
        return "corpse route requires a visible generic corpse glyph"
    origin = decided_on.player
    first = path[0]
    expected_action = MOVE_ACTION_NAMES.get((first.x - origin.x, first.y - origin.y))
    if payload.action.name != expected_action:
        return "corpse route action does not follow its recorded first step"
    if memory is not None:
        route = route_tree(memory.current).route((x, y))
        if route is None or route != tuple((cell.x, cell.y) for cell in path):
            return "corpse route is not reachable along the recorded path"
    return None


def _gold_intent_error(
    payload: StepPayload, decided_on: ProjectedObservation | None
) -> str | None:
    """Why a gold intent is unsupported by the observation it was decided on.

    Gold navigation routes only onto a cell that displays exactly the gold
    glyph on the level the hero was on; None for steps without a gold intent.
    """
    intent = payload.selection.intent
    destination = None if intent is None else intent.destination
    if destination is None or destination.kind is not DestinationKind.GOLD:
        return None
    assert intent is not None
    cell = f"({destination.x}, {destination.y})"
    if decided_on is None:
        return f"gold intent {cell} has no decided-on observation"
    player = decided_on.player
    if intent.level != LevelKey(player.dungeon_number, player.dungeon_level):
        return f"gold intent {cell} names another level than the decided-on one"
    rows = decided_on.map.glyph_rows
    if (
        destination.y >= len(rows)
        or destination.x >= len(rows[destination.y])
        or rows[destination.y][destination.x] != GOLD_GLYPH
    ):
        return f"gold intent {cell} does not show gold on the decided-on observation"
    return None


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


def _episode_metric_value(metric: MetricName, result: SeedResult) -> float | None:
    """One episode's value of a threshold metric; None if it was not recorded."""
    metrics = result.metrics
    died = result.outcome is RunOutcome.DEATH
    match metric:
        case MetricName.TASK_RETURN:
            return metrics.task_return
        case MetricName.EXPLORED_CELLS:
            return metrics.explored_cells
        case MetricName.MAX_DEPTH:
            return metrics.max_depth
        case MetricName.FINAL_GOLD:
            return metrics.final_gold
        case MetricName.WORST_HUNGER_STATE:
            worst = metrics.worst_hunger_state
            return None if worst is None else _HUNGER_STATES.index(worst)
        case MetricName.DEATH:
            return 1 if died else 0
        case MetricName.STARVATION_DEATH:
            # NetHack's xlog death text for starving is "died of starvation".
            return 1 if died and "starvation" in metrics.death_cause else 0
        case MetricName.HUNGER_AT_DEATH:
            if metrics.steps_by_skill is None:
                return None
            if not died:
                return 0
            hunger = metrics.hunger_at_death
            return None if hunger is None else _HUNGER_STATES.index(hunger)


def _metric_statistic(
    statistic: MetricStatistic, values: Sequence[float]
) -> float | None:
    """A statistic over episode values; None when there are no values."""
    if not values:
        return None
    ordered = sorted(values)
    match statistic:
        case MetricStatistic.MINIMUM:
            return ordered[0]
        case MetricStatistic.MAXIMUM:
            return ordered[-1]
        case MetricStatistic.SUM:
            return math.fsum(ordered)
        case MetricStatistic.MEAN:
            return math.fsum(ordered) / len(ordered)
        case MetricStatistic.MEDIAN:
            middle = len(ordered) // 2
            if len(ordered) % 2:
                return ordered[middle]
            return (ordered[middle - 1] + ordered[middle]) / 2


def _threshold_statistics(
    case: EvaluationCase, results: Sequence[SeedResult]
) -> list[tuple[MetricThreshold, float | None]]:
    """Each case threshold with its statistic over the case's results.

    The statistic is unavailable (None, failing the threshold) when the case
    has no results or any result did not record the metric.
    """
    statistics: list[tuple[MetricThreshold, float | None]] = []
    for threshold in case.acceptance.metric_thresholds:
        values = [_episode_metric_value(threshold.metric, result) for result in results]
        present = [value for value in values if value is not None]
        statistics.append(
            (
                threshold,
                None
                if len(present) != len(values)
                else _metric_statistic(threshold.statistic, present),
            )
        )
    return statistics


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


def _wilson_95(successes: int, total: int) -> tuple[float, float]:
    """Wilson score interval for a binomial success rate (z = 1.96)."""
    if total == 0:
        return (0.0, 1.0)
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def _schema_four_acceptance(
    suite: EvaluationSuite,
    results: Sequence[SeedResult],
    *,
    development_model: bool,
    inputs_unchanged: bool,
) -> AcceptanceResult:
    """Evaluate ordinary, catalog-baseline, and sampled cases independently."""
    from nethack_agent.seed_catalog import (
        CatalogCheckStatus,
        SeedCatalog,
        check_catalog,
    )

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    expected = {(case.case_id, seed) for case in suite.cases for seed in case.seeds}
    evaluated = [(result.case_id, result.seed) for result in results]
    complete = (
        len(evaluated) == len(set(evaluated))
        and set(evaluated) == expected
        and all(result.ended_by != "interrupted" for result in results)
    )
    checks["all_seeds_evaluated"] = complete
    if not complete:
        reasons.append(
            "suite incomplete; missing or interrupted case/seeds "
            f"{sorted(expected - set(evaluated))}"
        )

    baseline_ids = {entry.entry_id for entry in suite.baseline}
    fresh_id = suite.fresh_sample.case_id if suite.fresh_sample else None
    for case in suite.cases:
        if case.case_id in baseline_ids or case.case_id == fresh_id:
            continue
        case_results = [result for result in results if result.case_id == case.case_id]
        succeeded = {
            result.seed for result in case_results if result.successful_for(case)
        }
        enough = len(succeeded) >= case.acceptance.min_successes
        checks[f"{case.case_id}:min_successes"] = enough
        if not enough:
            reasons.append(
                f"case {case.case_id} has {len(succeeded)} successes; at least "
                f"{case.acceptance.min_successes} required"
            )
        missing = [
            seed
            for seed in case.acceptance.required_success_seeds
            if seed not in succeeded
        ]
        checks[f"{case.case_id}:required_success_seeds"] = not missing
        if missing:
            reasons.append(
                f"case {case.case_id} required seeds did not succeed: {missing}"
            )
        for threshold, observed in _threshold_statistics(case, case_results):
            passed = threshold.passes(observed)
            checks[f"{case.case_id}:{threshold.check_name}"] = passed
            if not passed:
                observed_text = (
                    "unavailable" if observed is None else _compact_number(observed)
                )
                reasons.append(
                    f"case {case.case_id}: {threshold.metric.value} "
                    f"{threshold.statistic.value} is "
                    f"{observed_text}; "
                    f"{threshold.bound_text} required"
                )

    if suite.baseline:
        catalog = SeedCatalog(
            policy_version=suite.policy_version, entries=suite.baseline
        )
        for check in check_catalog(catalog, suite, results):
            passed = check.status is not CatalogCheckStatus.FAIL
            checks[f"baseline:{check.entry_id}"] = passed
            if not passed:
                reasons.append(f"baseline {check.entry_id}: {check.detail}")
    if suite.fresh_sample is not None:
        fresh = suite.case(suite.fresh_sample.case_id)
        sampled = [result for result in results if result.case_id == fresh.case_id]
        successes = sum(result.successful_for(fresh) for result in sampled)
        rate = successes / suite.fresh_sample.count
        minimum = suite.fresh_sample.acceptance.min_success_rate
        checks["fresh:min_success_rate"] = (
            rate >= minimum
            and len(sampled) == len(fresh.seeds)
            and {result.seed for result in sampled} == set(fresh.seeds)
        )
        if not checks["fresh:min_success_rate"]:
            reasons.append(
                f"fresh sample success rate {rate:.6f} is below required {minimum:.6f}"
            )
        for threshold, observed in _threshold_statistics(fresh, sampled):
            passed = threshold.passes(observed)
            checks[f"fresh:{threshold.check_name}"] = passed
            if not passed:
                observed_text = (
                    "unavailable" if observed is None else _compact_number(observed)
                )
                reasons.append(
                    f"fresh sample: {threshold.metric.value} "
                    f"{threshold.statistic.value} is "
                    f"{observed_text}; "
                    f"{threshold.bound_text} required"
                )

    criteria = suite.global_acceptance
    invalid = sum(result.invalid_actions for result in results)
    rejections = sum(result.gate_rejections for result in results)
    incomplete = [
        (result.case_id, result.seed) for result in results if not result.integrity_ok
    ]
    configurations = [result.configuration for result in results]
    fixed = (
        bool(configurations)
        and all(configuration is not None for configuration in configurations)
        and len(
            {
                configuration.shared
                for configuration in configurations
                if configuration is not None
            }
        )
        == 1
    )
    checks.update(
        {
            "invalid_actions": invalid <= criteria.max_invalid_actions,
            "gate_rejections": rejections <= criteria.max_gate_rejections,
            "complete_records": not criteria.require_complete_records or not incomplete,
            "fixed_configuration": fixed,
            "inputs_unchanged": inputs_unchanged,
        }
    )
    if not checks["invalid_actions"]:
        reasons.append(f"{invalid} invalid NLE actions recorded")
    if not checks["gate_rejections"]:
        reasons.append(f"{rejections} action-gate rejections recorded")
    if not checks["complete_records"]:
        reasons.append(
            f"incomplete SQLite or ttyrec records for case/seeds {incomplete}"
        )
    if not fixed:
        reasons.append(
            "run configuration was not identical across evaluated episodes "
            "apart from suite case task and cap"
        )
    if not inputs_unchanged:
        reasons.append("suite or knowledge files changed during evaluation")
    if development_model:
        reasons.append(
            "development scripted model runs are never valid milestone evidence"
        )
    return AcceptanceResult(checks, tuple(reasons), development_model)


def evaluate_acceptance(
    suite: EvaluationSuite,
    results: Sequence[SeedResult],
    *,
    development_model: bool,
    inputs_unchanged: bool,
) -> AcceptanceResult:
    if suite.schema_version == 3:
        return _schema_four_acceptance(
            suite,
            results,
            development_model=development_model,
            inputs_unchanged=inputs_unchanged,
        )
    reasons: list[str] = []
    expected = {(case.case_id, seed) for case in suite.cases for seed in case.seeds}
    evaluated = [(result.case_id, result.seed) for result in results]
    all_evaluated = (
        len(evaluated) == len(set(evaluated))
        and set(evaluated) == expected
        and not any(result.ended_by == "interrupted" for result in results)
    )
    if not all_evaluated:
        missing = sorted(expected - set(evaluated))
        if suite.legacy:
            reasons.append(
                "suite incomplete; missing or interrupted seeds "
                f"{[seed for _, seed in missing]}"
            )
        else:
            reasons.append(
                f"suite incomplete; missing or interrupted case/seeds {missing}"
            )

    checks: dict[str, bool] = {"all_seeds_evaluated": all_evaluated}
    for case in suite.cases:
        case_results = [result for result in results if result.case_id == case.case_id]
        succeeded = {
            result.seed for result in case_results if result.successful_for(case)
        }
        successes = len(succeeded)
        enough = successes >= case.acceptance.min_successes
        missing_required = [
            seed
            for seed in case.acceptance.required_success_seeds
            if seed not in succeeded
        ]
        if suite.legacy:
            checks["min_task_successes"] = enough
            checks["required_success_seeds"] = not missing_required
            if not enough:
                reasons.append(
                    f"{successes} task successes; at least "
                    f"{case.acceptance.min_successes} required"
                )
            if missing_required:
                reasons.append(f"required seeds did not succeed: {missing_required}")
        else:
            checks[f"{case.case_id}:min_successes"] = enough
            checks[f"{case.case_id}:required_success_seeds"] = not missing_required
            if not enough:
                reasons.append(
                    f"case {case.case_id} has {successes} successes; at least "
                    f"{case.acceptance.min_successes} required"
                )
            if missing_required:
                reasons.append(
                    f"case {case.case_id} required seeds did not succeed: "
                    f"{missing_required}"
                )
            for threshold, observed in _threshold_statistics(case, case_results):
                passed = threshold.passes(observed)
                checks[f"{case.case_id}:{threshold.check_name}"] = passed
                if passed:
                    continue
                label = (
                    f"case {case.case_id}: {threshold.metric.value} "
                    f"{threshold.statistic.value}"
                )
                if observed is None:
                    reasons.append(
                        f"{label} is unavailable; {threshold.bound_text} required"
                    )
                else:
                    relation = (
                        "below"
                        if threshold.comparison is MetricComparison.AT_LEAST
                        else "above"
                    )
                    reasons.append(
                        f"{label} {_compact_number(observed)} is {relation} "
                        f"{threshold.bound_text}"
                    )

    criteria = suite.global_acceptance
    invalid = sum(result.invalid_actions for result in results)
    if invalid > criteria.max_invalid_actions:
        reasons.append(f"{invalid} invalid NLE actions recorded")
    rejections = sum(result.gate_rejections for result in results)
    if rejections > criteria.max_gate_rejections:
        reasons.append(f"{rejections} action-gate rejections recorded")
    incomplete = [
        (result.case_id, result.seed) for result in results if not result.integrity_ok
    ]
    records_complete = not criteria.require_complete_records or not incomplete
    if not records_complete:
        if suite.legacy:
            reasons.append(
                "incomplete SQLite or ttyrec records for seeds "
                f"{[seed for _, seed in incomplete]}"
            )
        else:
            reasons.append(
                f"incomplete SQLite or ttyrec records for case/seeds {incomplete}"
            )
    configurations = [result.configuration for result in results]
    fixed = (
        bool(configurations)
        and all(configuration is not None for configuration in configurations)
        and len(
            {
                configuration.shared
                for configuration in configurations
                if configuration is not None
            }
        )
        == 1
    )
    if not fixed:
        reasons.append(
            "run configuration was not identical across evaluated episodes "
            "apart from suite case task and cap"
        )
    if not inputs_unchanged:
        reasons.append("suite or knowledge files changed during evaluation")
    if development_model:
        reasons.append(
            "development scripted model runs are never valid milestone evidence"
        )
    checks.update(
        {
            "invalid_actions": invalid <= criteria.max_invalid_actions,
            "gate_rejections": rejections <= criteria.max_gate_rejections,
            "complete_records": records_complete,
            "fixed_configuration": fixed,
            "inputs_unchanged": inputs_unchanged,
        }
    )
    return AcceptanceResult(
        checks=checks,
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
    draw_provenance: DrawProvenance | None = None
    comparison_source: dict[str, object] | None = None

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

    def _case_results(self, case: EvaluationCase) -> list[SeedResult]:
        return [result for result in self.results if result.case_id == case.case_id]

    def _requested_for_case(self, case: EvaluationCase) -> tuple[int, ...]:
        return tuple(seed for seed in self.requested_seeds if seed in case.seeds)

    def aggregate_json(
        self, results: Sequence[SeedResult] | None = None
    ) -> dict[str, object]:
        selected = list(self.results if results is None else results)
        outcomes = Counter(
            result.outcome.value if result.outcome else "none" for result in selected
        )
        sources = Counter({source.value: 0 for source in ActionSelectionSource})
        for result in selected:
            sources.update(result.selection_sources)
        return {
            "evaluated_seeds": len(selected),
            "task_successes": sum(
                result.successful_for(self.suite.case(result.case_id))
                for result in selected
            ),
            "outcomes": dict(sorted(outcomes.items())),
            "steps": sum(result.steps for result in selected),
            "total_wall_seconds": round(
                sum(result.wall_seconds for result in selected), 3
            ),
            "decisions": DecisionStats.combine(
                [result.decision_stats for result in selected]
            ).to_json(),
            "selection_sources": dict(sources),
            "gate_rejections": sum(r.gate_rejections for r in selected),
            "decision_failures": sum(r.decision_failures for r in selected),
            "invalid_actions": sum(r.invalid_actions for r in selected),
            "integrity_failures": [
                (
                    result.seed
                    if self.suite.legacy
                    else f"{result.case_id}/{result.seed}"
                )
                for result in selected
                if not result.integrity_ok
            ],
        }

    def _case_report_json(self, case: EvaluationCase) -> dict[str, object]:
        results = self._case_results(case)
        successes = sum(result.successful_for(case) for result in results)
        succeeded = {result.seed for result in results if result.successful_for(case)}
        required = case.acceptance.required_success_seeds
        statistics = _threshold_statistics(case, results)
        acceptance: dict[str, object] = {
            "criteria": case.acceptance.to_json(),
            "successes": successes,
            "passed": (
                successes >= case.acceptance.min_successes
                and all(seed in succeeded for seed in required)
                and all(threshold.passes(value) for threshold, value in statistics)
            ),
        }
        # Absent for cases without thresholds so their report shape is unchanged.
        if statistics:
            acceptance["metrics"] = [
                {
                    **threshold.to_json(),
                    "value": None if value is None else _json_number(round(value, 6)),
                    "passed": threshold.passes(value),
                }
                for threshold, value in statistics
            ]
        return {
            "case_id": case.case_id,
            "task": case.task.to_json(),
            "max_episode_steps": case.max_episode_steps,
            "requested_seeds": list(self._requested_for_case(case)),
            "results": [result.to_json() for result in results],
            "aggregate": self.aggregate_json(results),
            "acceptance": acceptance,
        }

    def _schema_four_json(self, payload: dict[str, object]) -> dict[str, object]:
        from nethack_agent.seed_catalog import (
            CatalogCheckStatus,
            SeedCatalog,
            check_catalog,
        )

        checks = (
            check_catalog(
                SeedCatalog(self.suite.policy_version, self.suite.baseline),
                self.suite,
                self.results,
            )
            if self.suite.baseline
            else ()
        )
        payload["report_schema_version"] = 4
        payload["draw_provenance"] = (
            self.draw_provenance.to_json() if self.draw_provenance is not None else None
        )
        payload["baseline"] = {
            "catalog": (
                {
                    "path": str(self.suite.catalog_path),
                    "sha256": self.suite.catalog_sha256,
                }
                if self.suite.baseline
                else None
            ),
            "entries": [
                {"entry": entry.to_json(), "check": check.to_json()}
                for entry, check in zip(self.suite.baseline, checks, strict=True)
            ],
            "passed": all(
                check.status is not CatalogCheckStatus.FAIL for check in checks
            ),
        }
        fresh = self.suite.fresh_sample
        if fresh is None:
            payload["fresh"] = None
        else:
            case = self.suite.case(fresh.case_id)
            sampled = self._case_results(case)
            successes = sum(result.successful_for(case) for result in sampled)
            statistics = _threshold_statistics(case, sampled)
            payload["fresh"] = {
                "case_id": case.case_id,
                "successes": successes,
                "sample_size": fresh.count,
                "success_rate": round(successes / fresh.count, 6),
                "wilson_95": [
                    round(bound, 6) for bound in _wilson_95(successes, fresh.count)
                ],
                "acceptance": {
                    "criteria": fresh.acceptance.to_json(),
                    "passed": (
                        len(sampled) == fresh.count
                        and {result.seed for result in sampled} == set(case.seeds)
                        and successes / fresh.count >= fresh.acceptance.min_success_rate
                        and all(
                            threshold.passes(value) for threshold, value in statistics
                        )
                    ),
                    "metrics": [
                        {
                            **threshold.to_json(),
                            "value": None
                            if value is None
                            else _json_number(round(value, 6)),
                            "passed": threshold.passes(value),
                        }
                        for threshold, value in statistics
                    ],
                },
            }
        payload["comparison"] = self._comparison_json()
        return payload

    def _comparison_json(self) -> dict[str, object] | None:
        prior = self.comparison_source
        if prior is None:
            return None
        version = integer_value(
            prior.get("report_schema_version"), "prior report schema"
        )
        if version != 4:
            raise ContractError("comparison requires a report schema 4")
        prior_suite = object_value(
            prior.get("suite"),
            "prior suite",
            prior["suite"].keys() if isinstance(prior.get("suite"), dict) else (),
        )
        if prior_suite.get("suite_id") != self.suite.suite_id:
            raise ContractError("comparison report suite_id does not match")
        if prior_suite.get("sha256") != self.suite.sha256:
            raise ContractError("comparison report suite sha256 does not match")
        prior_cases: dict[str, dict[str, object]] = {}
        for item in array_value(prior.get("case_results"), "prior case_results"):
            if not isinstance(item, dict):
                raise ContractError("prior case result must be an object")
            case_id = string_value(item.get("case_id"), "prior case_id")
            if case_id in prior_cases:
                raise ContractError("prior case ids must be unique")
            prior_cases[case_id] = item
        entries: list[dict[str, object]] = []
        for entry in self.suite.baseline:
            current = next(
                (
                    result
                    for result in self.results
                    if result.case_id == entry.entry_id and result.seed == entry.seed
                ),
                None,
            )
            old_case = prior_cases.get(entry.entry_id)
            old = None
            if old_case is not None and old_case.get("task") != entry.task.to_json():
                raise ContractError("prior baseline task does not match current suite")
            if old_case is not None:
                for item in array_value(
                    old_case.get("results"), "prior baseline results"
                ):
                    if not isinstance(item, dict):
                        raise ContractError("prior baseline result must be an object")
                    if (
                        item.get("seed") == entry.seed
                        and item.get("case_id") == entry.entry_id
                    ):
                        if old is not None:
                            raise ContractError("duplicate prior baseline entry result")
                        old = item
            prior_outcome = (
                None
                if old is None
                else _optional_text(old.get("outcome"), "prior outcome")
            )
            if old is not None and prior_outcome is not None:
                enum_value(prior_outcome, "prior outcome", RunOutcome)
            prior_success = None
            if old is not None:
                metrics = EpisodeMetrics.from_json(old.get("metrics"))
                prior_success = (
                    prior_outcome == RunOutcome.TASK_SUCCESS.value
                    if entry.task.environment is NleTask.STAIRCASE
                    else metrics.objective_legs_completed
                    == len(entry.task.objective.legs)
                )
            current_success = (
                None
                if current is None
                else current.successful_for(self.suite.case(entry.entry_id))
            )
            if current_success is None or prior_success is None:
                change = "unavailable"
            elif current_success != prior_success:
                change = "improved" if current_success else "regressed"
            elif prior_outcome != (current.outcome.value if current.outcome else None):
                change = "outcome_changed"
            else:
                change = "unchanged"
            entries.append(
                {
                    "entry_id": entry.entry_id,
                    "seed": entry.seed,
                    "prior_outcome": prior_outcome,
                    "prior_successful": prior_success,
                    "current_outcome": (
                        None
                        if current is None or current.outcome is None
                        else current.outcome.value
                    ),
                    "current_successful": current_success,
                    "change": change,
                }
            )
        return {
            "prior_report": {
                "report_schema_version": version,
                "suite_id": self.suite.suite_id,
                "sha256": string_value(prior_suite.get("sha256"), "prior suite sha256"),
                "started_at": string_value(prior.get("started_at"), "prior started_at"),
            },
            "entries": entries,
        }

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
            "requested_cases": [
                {
                    "case_id": case.case_id,
                    "seeds": list(self._requested_for_case(case)),
                }
                for case in self.suite.cases
            ],
            "case_results": [self._case_report_json(case) for case in self.suite.cases],
            "aggregate": self.aggregate_json(),
            "acceptance": self.acceptance().to_json(),
        }
        return (
            self._schema_four_json(payload)
            if self.suite.schema_version == 3
            else payload
        )

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
_RESULT_FIELDS_V2: Final = frozenset(
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
_SUITE_FIELDS_V2: Final = frozenset(
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
_REPORT_FIELDS_V2: Final = _REPORT_FIELDS_V1 | {"status_reason"}
_RESULT_FIELDS_V3: Final = _RESULT_FIELDS_V2 | {"case_id", "metrics"}
_SUITE_FIELDS_V3: Final = frozenset(
    {
        "schema_version",
        "suite_id",
        "path",
        "sha256",
        "character",
        "policy_version",
        "knowledge_bundle_id",
        "seed_selection",
        "step_cap_rationale",
        "cases",
        "acceptance",
    }
)
_SUITE_CASE_FIELDS: Final = frozenset(
    {"case_id", "task", "seeds", "max_episode_steps", "acceptance"}
)
_CASE_ACCEPTANCE_FIELDS: Final = frozenset({"min_successes", "required_success_seeds"})
_CASE_ACCEPTANCE_OPTIONAL_FIELDS: Final = frozenset({"metric_thresholds"})
_GLOBAL_ACCEPTANCE_FIELDS: Final = frozenset(
    {"max_invalid_actions", "max_gate_rejections", "require_complete_records"}
)
_CASE_REPORT_FIELDS: Final = frozenset(
    {
        "case_id",
        "task",
        "max_episode_steps",
        "requested_seeds",
        "results",
        "aggregate",
        "acceptance",
    }
)
_CASE_REPORT_ACCEPTANCE_FIELDS: Final = frozenset({"criteria", "successes", "passed"})
_CASE_REPORT_ACCEPTANCE_OPTIONAL_FIELDS: Final = frozenset({"metrics"})
_CASE_REPORT_METRIC_FIELDS: Final = frozenset(
    {"metric", "statistic", "bound", "value", "passed"}
)
_REQUESTED_CASE_FIELDS: Final = frozenset({"case_id", "seeds"})
_REPORT_FIELDS_V3: Final = frozenset(
    {
        "report_schema_version",
        "status",
        "status_reason",
        "started_at",
        "finished_at",
        "suite",
        "configuration",
        "requested_cases",
        "case_results",
        "aggregate",
        "acceptance",
    }
)
_REPORT_FIELDS_V4: Final = _REPORT_FIELDS_V3 | {
    "draw_provenance",
    "baseline",
    "fresh",
    "comparison",
}
_SUITE_FIELDS_V4: Final = _SUITE_FIELDS_V3
_DRAW_FIELDS: Final = frozenset(
    {"draw_seed", "range", "exclusion_count", "excluded_seeds", "drawn_seeds"}
)
_COMPARISON_FIELDS: Final = frozenset({"prior_report", "entries"})
_COMPARISON_PRIOR_FIELDS: Final = frozenset(
    {"report_schema_version", "suite_id", "sha256", "started_at"}
)
_COMPARISON_ENTRY_FIELDS: Final = frozenset(
    {
        "entry_id",
        "seed",
        "prior_outcome",
        "prior_successful",
        "current_outcome",
        "current_successful",
        "change",
    }
)
_RUN_CONFIGURATION_FIELDS: Final = frozenset(
    {
        "model",
        "policy_version",
        "knowledge_version",
        "nle_version",
        "environment",
        "character",
        "max_episode_steps",
        "ollama_num_ctx",
    }
)


def render_report_markdown(payload: dict[str, object]) -> str:
    """Strictly render report schema 2, 3, or 4 from its JSON source of truth."""
    version = integer_value(
        payload.get("report_schema_version"), "report_schema_version"
    )
    if version == LEGACY_REPORT_SCHEMA_VERSION:
        return _render_report_markdown_v2(payload)
    if version == REPORT_SCHEMA_VERSION:
        return _render_report_markdown_v3(payload)
    if version == 4:
        return _render_report_markdown_v4(payload)
    raise ContractError(
        "report_schema_version must be "
        f"{LEGACY_REPORT_SCHEMA_VERSION}, {REPORT_SCHEMA_VERSION}, or 4"
    )


def _render_report_markdown_v2(payload: dict[str, object]) -> str:
    """Render schema 2 exactly as before report schema 3 was introduced."""
    report = object_value(payload, "evaluation report", _REPORT_FIELDS_V2)
    version = integer_value(report["report_schema_version"], "report_schema_version")
    if version != LEGACY_REPORT_SCHEMA_VERSION:
        raise ContractError(
            f"report_schema_version must be {LEGACY_REPORT_SCHEMA_VERSION}"
        )
    status = enum_value(report["status"], "report status", ReportStatus)
    reason = _optional_text(report["status_reason"], "report status_reason")
    if status is ReportStatus.ABORTED and reason is None:
        raise ContractError("an aborted report requires a status_reason")
    suite = object_value(report["suite"], "report suite", _SUITE_FIELDS_V2)
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
        result = object_value(item, "report result", _RESULT_FIELDS_V2)
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


def _render_report_markdown_v4(payload: dict[str, object]) -> str:
    """Render all schema-four sections from the persisted JSON, not the suite file."""
    from nethack_agent.seed_catalog import CatalogCheckStatus, CatalogEntry

    report = object_value(payload, "evaluation report", _REPORT_FIELDS_V4)
    suite = object_value(
        report["suite"],
        "report suite",
        _SUITE_FIELDS_V4,
        optional={"baseline", "fresh_sample"},
    )
    if integer_value(suite["schema_version"], "suite schema_version") != 3:
        raise ContractError("report schema 4 requires suite schema 3")
    ordinary = array_value(suite["cases"], "suite cases")
    baseline = object_value(
        report["baseline"], "report baseline", {"catalog", "entries", "passed"}
    )
    baseline_rows = array_value(baseline["entries"], "report baseline entries")
    expected_ids: list[str] = []
    if "baseline" in suite:
        definition = object_value(suite["baseline"], "suite baseline", {"entry_ids"})
        expected_ids = [
            _suite_identifier(item, "baseline entry id")
            for item in array_value(definition["entry_ids"], "baseline entry ids")
        ]
        if not expected_ids or len(set(expected_ids)) != len(expected_ids):
            raise ContractError("suite baseline entry ids must be unique and nonempty")
    if len(baseline_rows) != len(expected_ids):
        raise ContractError("report baseline entries must match suite baseline")
    catalog = baseline["catalog"]
    if expected_ids:
        catalog_record = object_value(
            catalog, "report baseline catalog", {"path", "sha256"}
        )
        catalog_path = string_value(
            catalog_record["path"], "report baseline catalog path", minimum=1
        )
        catalog_digest = string_value(
            catalog_record["sha256"],
            "report baseline catalog sha256",
            minimum=64,
            maximum=64,
        )
    elif catalog is not None:
        raise ContractError("report without a baseline must not record a catalog")
    catalog_cases: list[dict[str, object]] = []
    section = [
        "",
        "## Baseline: "
        + ("PASS" if boolean_value(baseline["passed"], "baseline passed") else "FAIL"),
        "",
    ]
    if expected_ids:
        section.extend(
            [
                f"- Catalog: `{catalog_path}` (sha256 `{catalog_digest}`)",
                "",
            ]
        )
    if baseline_rows:
        section.extend(
            [
                "| Entry | Seed | Expectation | Expected | Observed "
                "| Success | Status | Detail |",
                "| --- | ---: | --- | --- | --- | --- | --- | --- |",
            ]
        )
    statuses: list[CatalogCheckStatus] = []
    for index, item in enumerate(baseline_rows):
        row = object_value(item, "baseline row", {"entry", "check"})
        entry = CatalogEntry.from_json(row["entry"], "report baseline entry")
        if entry.entry_id != expected_ids[index]:
            raise ContractError("baseline entries must match suite entry ids in order")
        check = object_value(
            row["check"],
            "baseline check",
            {
                "entry_id",
                "seed",
                "expectation",
                "expected_outcome",
                "observed_outcome",
                "successful",
                "invariants_ok",
                "status",
                "detail",
            },
        )
        if (
            check["entry_id"] != entry.entry_id
            or check["seed"] != entry.seed
            or check["expectation"] != entry.expectation.value
            or check["expected_outcome"] != entry.outcome.value
        ):
            raise ContractError("baseline check does not match its catalog entry")
        observed = _optional_text(
            check["observed_outcome"], "baseline observed outcome"
        )
        if observed is not None:
            enum_value(observed, "baseline observed outcome", RunOutcome)
        successful = boolean_value(check["successful"], "baseline successful")
        boolean_value(check["invariants_ok"], "baseline invariants_ok")
        status = enum_value(check["status"], "baseline status", CatalogCheckStatus)
        statuses.append(status)
        detail = string_value(check["detail"], "baseline detail")
        section.append(
            f"| `{entry.entry_id}` | {entry.seed} | {entry.expectation.value} "
            f"| {entry.outcome.value} | {observed or '-'} "
            f"| {'yes' if successful else 'no'} | {status.value} | {_md_cell(detail)} |"
        )
        catalog_cases.append(
            {
                "case_id": entry.entry_id,
                "task": entry.task.to_json(),
                "seeds": [entry.seed],
                "max_episode_steps": entry.max_episode_steps,
                "acceptance": {"min_successes": 0, "required_success_seeds": []},
            }
        )
    if boolean_value(baseline["passed"], "baseline passed") != all(
        status is not CatalogCheckStatus.FAIL for status in statuses
    ):
        raise ContractError("baseline passed differs from its check statuses")

    sampled = report["fresh"]
    provenance = report["draw_provenance"]
    fresh_cases: list[dict[str, object]] = []
    if "fresh_sample" not in suite:
        if sampled is not None or provenance is not None:
            raise ContractError("fresh sample and draw require suite fresh_sample")
    else:
        specification = object_value(
            suite["fresh_sample"],
            "suite fresh_sample",
            {"case_id", "task", "max_episode_steps", "count", "range", "acceptance"},
        )
        fresh = object_value(
            sampled,
            "report fresh",
            {
                "case_id",
                "successes",
                "sample_size",
                "success_rate",
                "wilson_95",
                "acceptance",
            },
        )
        draw_record = DrawProvenance.from_json(provenance)
        draw = draw_record.to_json()
        case_id = _suite_identifier(specification["case_id"], "fresh case_id")
        if fresh["case_id"] != case_id:
            raise ContractError("fresh result case_id differs from suite")
        count = integer_value(specification["count"], "fresh count", minimum=1)
        if integer_value(fresh["sample_size"], "fresh sample_size") != count:
            raise ContractError("fresh sample_size differs from suite count")
        bounds = _integers(specification["range"], "fresh range")
        if len(bounds) != 2 or bounds[0] > bounds[1]:
            raise ContractError("fresh range must have ordered bounds")
        if _integers(draw["range"], "draw range") != bounds:
            raise ContractError("draw range differs from suite fresh range")
        integer_value(draw["draw_seed"], "draw seed")
        integer_value(draw["exclusion_count"], "draw exclusion_count", minimum=0)
        seeds = _integers(draw["drawn_seeds"], "drawn seeds")
        if (
            len(seeds) != count
            or len(set(seeds)) != count
            or not all(bounds[0] <= seed <= bounds[1] for seed in seeds)
        ):
            raise ContractError("drawn seeds must be unique seeds in fresh range")
        fresh_criteria = object_value(
            specification["acceptance"],
            "suite fresh acceptance",
            {"min_success_rate"},
            optional={"metric_thresholds"},
        )
        rate_minimum = number_value(
            fresh_criteria["min_success_rate"], "fresh minimum rate"
        )
        if not 0 <= rate_minimum <= 1:
            raise ContractError("fresh minimum rate must be in [0, 1]")
        fresh_acceptance = object_value(
            fresh["acceptance"],
            "fresh acceptance",
            {"criteria", "passed", "metrics"},
        )
        if fresh_acceptance["criteria"] != fresh_criteria:
            raise ContractError("fresh acceptance criteria differ from suite")
        thresholds = (
            _metric_thresholds(fresh_criteria["metric_thresholds"], "fresh")
            if "metric_thresholds" in fresh_criteria
            else ()
        )
        metric_rows = (
            _validated_case_metrics(
                {"metrics": fresh_acceptance["metrics"]}, thresholds, case_id
            )
            if thresholds
            else []
        )
        if not thresholds and array_value(fresh_acceptance["metrics"], "fresh metrics"):
            raise ContractError("fresh metrics recorded without suite thresholds")
        successes = integer_value(
            fresh["successes"], "fresh successes", minimum=0, maximum=count
        )
        observed_rate = number_value(fresh["success_rate"], "fresh success_rate")
        interval = [
            number_value(value, "fresh Wilson bound")
            for value in array_value(fresh["wilson_95"], "fresh wilson_95")
        ]
        if round(successes / count, 6) != observed_rate or interval != [
            round(bound, 6) for bound in _wilson_95(successes, count)
        ]:
            raise ContractError(
                "fresh success rate or Wilson interval differs from count"
            )
        passed = boolean_value(fresh_acceptance["passed"], "fresh acceptance passed")
        if passed and (
            successes / count < rate_minimum
            or not all(metric_passed for _, _, metric_passed in metric_rows)
        ):
            raise ContractError("fresh acceptance passed contradicts its criteria")
        task = TaskSpec.from_json(specification["task"], "suite fresh task")
        cap = integer_value(
            specification["max_episode_steps"], "fresh max_episode_steps", minimum=1
        )
        fresh_cases.append(
            {
                "case_id": case_id,
                "task": task.to_json(),
                "seeds": seeds,
                "max_episode_steps": cap,
                "acceptance": {
                    "min_successes": 0,
                    "required_success_seeds": [],
                    **(
                        {"metric_thresholds": fresh_criteria["metric_thresholds"]}
                        if thresholds
                        else {}
                    ),
                },
            }
        )
        section.extend(
            [
                "",
                f"## Fresh sample `{case_id}`: {'PASS' if passed else 'FAIL'}",
                "",
                f"- Draw seed: {integer_value(draw['draw_seed'], 'draw seed')}",
                f"- Draw range: {bounds}; excluded: {draw['exclusion_count']}",
                f"- Drawn seed order: {seeds}",
                f"- Successes: {successes}/{count}; rate: {observed_rate:.6f} "
                f"(required {rate_minimum:.6f}).",
                f"- Wilson 95% interval: [{interval[0]:.6f}, {interval[1]:.6f}]",
            ]
        )
        for threshold, value, metric_passed in metric_rows:
            section.append(
                f"- {threshold.metric.value} {threshold.statistic.value} "
                f"{threshold.bound_text}: "
                f"{'-' if value is None else _compact_number(value)} "
                f"({'pass' if metric_passed else 'fail'})"
            )

    comparison = report["comparison"]
    if comparison is not None:
        prior = object_value(comparison, "report comparison", _COMPARISON_FIELDS)
        source = object_value(
            prior["prior_report"], "prior report identity", _COMPARISON_PRIOR_FIELDS
        )
        version = integer_value(source["report_schema_version"], "prior report schema")
        if version != 4 or source["suite_id"] != suite["suite_id"]:
            raise ContractError("comparison requires report schema 4 of this suite")
        if source["sha256"] != suite["sha256"]:
            raise ContractError("comparison suite sha256 differs from current suite")
        string_value(source["started_at"], "prior started_at")
        comparison_rows = array_value(prior["entries"], "comparison entries")
        if len(comparison_rows) != len(expected_ids):
            raise ContractError("comparison entries must pair every baseline entry")
        section.extend(
            [
                "",
                "## Paired baseline comparison",
                "",
                f"- Prior suite sha256: `{source['sha256']}`; "
                f"started: {source['started_at']}",
                "",
                "| Entry | Seed | Prior outcome | Prior success "
                "| Current outcome | Current success | Change |",
                "| --- | ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for index, item in enumerate(comparison_rows):
            row = object_value(item, "comparison entry", _COMPARISON_ENTRY_FIELDS)
            seed = integer_value(row["seed"], "comparison seed", minimum=1)
            baseline_entry = CatalogEntry.from_json(
                object_value(baseline_rows[index], "baseline row", {"entry", "check"})[
                    "entry"
                ],
                "baseline entry",
            )
            if row["entry_id"] != expected_ids[index] or seed != baseline_entry.seed:
                raise ContractError("comparison entries must match baseline in order")
            values = []
            for prefix in ("prior", "current"):
                outcome = _optional_text(row[f"{prefix}_outcome"], f"{prefix} outcome")
                if outcome is not None:
                    enum_value(outcome, f"{prefix} outcome", RunOutcome)
                success = row[f"{prefix}_successful"]
                if success is not None:
                    boolean_value(success, f"{prefix} successful")
                values.append((outcome, success))
            change = string_value(row["change"], "comparison change")
            if change not in {
                "unavailable",
                "improved",
                "regressed",
                "outcome_changed",
                "unchanged",
            }:
                raise ContractError("unknown comparison change")
            section.append(
                f"| `{expected_ids[index]}` | {seed} "
                f"| {values[0][0] or '-'} | {_success_cell(values[0][1])} "
                f"| {values[1][0] or '-'} | {_success_cell(values[1][1])} "
                f"| {change} |"
            )

    case_reports = array_value(report["case_results"], "case_results")
    by_id: dict[str, dict[str, object]] = {}
    for item in case_reports:
        case = object_value(item, "report case", _CASE_REPORT_FIELDS)
        case_id = string_value(case["case_id"], "report case_id")
        if case_id in by_id:
            raise ContractError("report case ids must be unique")
        by_id[case_id] = case
    normalized_cases: list[dict[str, object]] = []
    for case in [*ordinary, *catalog_cases, *fresh_cases]:
        definition = object_value(case, "suite case", _SUITE_CASE_FIELDS)
        case_id = string_value(definition["case_id"], "suite case_id")
        row = by_id.get(case_id)
        if (
            row is None
            or row["task"] != definition["task"]
            or row["max_episode_steps"] != definition["max_episode_steps"]
        ):
            raise ContractError("report case must match its suite case")
        request = _integers(row["requested_seeds"], "report requested_seeds")
        if request != definition["seeds"]:
            raise ContractError("report requested seeds differ from suite/draw")
        criteria = object_value(
            row["acceptance"],
            "case acceptance",
            _CASE_REPORT_ACCEPTANCE_FIELDS,
            optional=_CASE_REPORT_ACCEPTANCE_OPTIONAL_FIELDS,
        )
        if criteria["criteria"] != definition["acceptance"]:
            raise ContractError("report case acceptance differs from suite")
        if case_id in expected_ids:
            index = expected_ids.index(case_id)
            row = {
                **row,
                "acceptance": {
                    **criteria,
                    "passed": statuses[index] is not CatalogCheckStatus.FAIL,
                },
            }
        if fresh_cases and case_id == fresh_cases[0]["case_id"]:
            assert isinstance(sampled, dict)
            fresh_info = object_value(
                sampled["acceptance"],
                "fresh acceptance",
                {"criteria", "passed", "metrics"},
            )
            row = {**row, "acceptance": {**criteria, "passed": fresh_info["passed"]}}
        normalized_cases.append(row)
    if len(normalized_cases) != len(case_reports):
        raise ContractError("report case_results must contain every suite case once")
    normalized_suite = {
        key: value
        for key, value in suite.items()
        if key not in ("baseline", "fresh_sample")
    }
    normalized_suite["schema_version"] = 2
    normalized_suite["cases"] = [*ordinary, *catalog_cases, *fresh_cases]
    normalized = {
        key: value for key, value in report.items() if key in _REPORT_FIELDS_V3
    }
    normalized["report_schema_version"] = REPORT_SCHEMA_VERSION
    normalized["suite"] = normalized_suite
    normalized["case_results"] = normalized_cases
    markdown = _render_report_markdown_v3(normalized, allow_zero_min_successes=True)
    before, separator, after = markdown.partition("\n## Case ")
    if not separator:
        raise ContractError("schema-four report contains no suite cases")
    combined = before + "\n".join(section) + "\n" + separator + after
    return _append_schema_four_diagnostics(combined, normalized_cases)


def _append_schema_four_diagnostics(
    markdown: str, case_reports: Sequence[dict[str, object]]
) -> str:
    """Only reports with newly recorded diagnostics gain a case-by-case table."""
    rows: list[tuple[str, list[tuple[int, EpisodeMetrics]]]] = []
    recorded: set[bool] = set()
    for case in case_reports:
        case_id = string_value(case["case_id"], "diagnostics case_id")
        episodes = []
        for item in array_value(case["results"], "diagnostics results"):
            result = object_value(item, "diagnostics result", _RESULT_FIELDS_V3)
            metrics = EpisodeMetrics.from_json(result["metrics"])
            recorded.add(metrics.steps_by_skill is not None)
            episodes.append(
                (integer_value(result["seed"], "diagnostics seed"), metrics)
            )
        rows.append((case_id, episodes))
    if len(recorded) > 1:
        raise ContractError(
            "report results must all record failure diagnostics or all omit them"
        )
    if recorded != {True}:
        return markdown
    lines = [
        "## Failure diagnostics",
        "",
        "Hunger at death is the last live observation before the terminal step; "
        "NLE zeroes terminal statistics.",
    ]
    for case_id, episodes in rows:
        if not episodes:
            continue
        lines.extend(
            [
                "",
                f"### `{case_id}`",
                "",
                "| Seed | Skill steps | SEARCH steps | First Hungry turn "
                "| Hunger before death |",
                "| ---: | --- | ---: | ---: | --- |",
            ]
        )
        for seed, metrics in episodes:
            assert metrics.steps_by_skill is not None
            skills = (
                ", ".join(
                    f"{skill.value}: {count}" for skill, count in metrics.steps_by_skill
                )
                or "-"
            )
            hungry = (
                "-"
                if metrics.first_hungry_turn is None
                else str(metrics.first_hungry_turn)
            )
            hunger = (
                "-"
                if metrics.hunger_at_death is None
                else metrics.hunger_at_death.value
            )
            lines.append(
                f"| {seed} | {skills} | {metrics.search_steps} | {hungry} | {hunger} |"
            )
    before, separator, after = markdown.partition("\n## Aggregate\n")
    if not separator:
        raise ContractError("schema-four report contains no aggregate")
    return before + "\n\n" + "\n".join(lines) + "\n" + separator + after


def _success_cell(success: object) -> str:
    return "-" if success is None else ("yes" if success else "no")


def _render_report_markdown_v3(
    payload: dict[str, object], *, allow_zero_min_successes: bool = False
) -> str:
    report = object_value(payload, "evaluation report", _REPORT_FIELDS_V3)
    if (
        integer_value(report["report_schema_version"], "report_schema_version")
        != REPORT_SCHEMA_VERSION
    ):
        raise ContractError(f"report_schema_version must be {REPORT_SCHEMA_VERSION}")
    status = enum_value(report["status"], "report status", ReportStatus)
    reason = _optional_text(report["status_reason"], "report status_reason")
    if status is ReportStatus.ABORTED and reason is None:
        raise ContractError("an aborted report requires a status_reason")
    suite, suite_id, policy, knowledge_id, suite_cases = _validated_report_suite_v3(
        report["suite"], allow_zero_min_successes=allow_zero_min_successes
    )

    configuration = object_value(
        report["configuration"], "report configuration", _REPORT_CONFIGURATION_FIELDS
    )
    model_mode = string_value(configuration["model_mode"], "model_mode")
    model = string_value(configuration["model"], "model")
    configured_policy = string_value(configuration["policy_version"], "policy_version")
    knowledge = string_value(configuration["knowledge_version"], "knowledge")
    num_ctx = integer_value(
        configuration["ollama_num_ctx"], "ollama_num_ctx", minimum=1
    )
    string_value(configuration["data_directory"], "data_directory", minimum=1)
    if configured_policy != policy:
        raise ContractError("report policy does not match its suite pin")
    if knowledge_id is not None and knowledge.split("+sha256:", 1)[0] != knowledge_id:
        raise ContractError("report knowledge does not match its suite pin")

    requested: dict[str, list[int]] = {}
    for item in array_value(report["requested_cases"], "report requested_cases"):
        request = object_value(item, "report requested case", _REQUESTED_CASE_FIELDS)
        case_id = string_value(request["case_id"], "requested case_id")
        if case_id not in suite_cases or case_id in requested:
            raise ContractError("requested case ids must name each suite case once")
        seeds = _integers(request["seeds"], f"requested case {case_id} seeds")
        if not seeds or len(seeds) != len(set(seeds)):
            raise ContractError("requested case seeds must be unique and nonempty")
        if not set(seeds) <= set(suite_cases[case_id][1]):
            raise ContractError("requested case seeds must belong to the suite case")
        requested[case_id] = seeds
    if set(requested) != set(suite_cases):
        raise ContractError("requested_cases must contain every suite case")

    acceptance = object_value(
        report["acceptance"], "report acceptance", _ACCEPTANCE_FIELDS
    )
    checks = _boolean_map(acceptance["checks"], "acceptance checks")
    reasons = [
        string_value(item, "acceptance reason")
        for item in array_value(acceptance["reasons"], "acceptance reasons")
    ]
    boolean_value(acceptance["development_model"], "acceptance development_model")
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
    aggregate = _validated_aggregate(report["aggregate"], "report aggregate")
    finished_at = _optional_text(report["finished_at"], "report finished_at")
    lines = [
        f"# Evaluation report: {suite_id}",
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
            f"- Model mode: {model_mode}; model `{model}`",
            f"- Policy pin: `{policy}`",
            "- Knowledge pin: "
            f"`{knowledge_id or knowledge.split('+sha256:', 1)[0]}`; "
            f"loaded `{knowledge}`",
            f"- Ollama num_ctx: {num_ctx}",
            "",
            f"## Acceptance: {'PASS' if passed else 'FAIL'}",
            "",
            f"Milestone accepted: {'yes' if accepted else 'no'}.",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
    )
    lines.extend(
        f"| {_md_cell(name)} | {'pass' if value else 'fail'} |"
        for name, value in sorted(checks.items())
    )
    if reasons:
        lines.extend(["", *[f"- {_md_cell(item)}" for item in reasons]])

    seen_case_reports: set[str] = set()
    all_problems: list[tuple[str, int, str]] = []
    all_errors: list[tuple[str, int, str]] = []
    case_reports = array_value(report["case_results"], "report case_results")
    records_exploration = _results_record_exploration(case_reports)
    for item in case_reports:
        case_report = object_value(item, "report case", _CASE_REPORT_FIELDS)
        case_id = string_value(case_report["case_id"], "report case_id")
        if case_id not in suite_cases or case_id in seen_case_reports:
            raise ContractError("case_results must name every suite case once")
        seen_case_reports.add(case_id)
        task, seeds, cap, suite_criteria, thresholds = suite_cases[case_id]
        if (
            TaskSpec.from_json(case_report["task"], f"report case {case_id} task")
            != task
        ):
            raise ContractError(f"report case {case_id} task differs from the suite")
        if (
            integer_value(
                case_report["max_episode_steps"],
                f"report case {case_id} max_episode_steps",
            )
            != cap
        ):
            raise ContractError(
                f"report case {case_id} step cap differs from the suite"
            )
        requested_seeds = _integers(
            case_report["requested_seeds"],
            f"report case {case_id} requested_seeds",
        )
        if requested_seeds != requested[case_id]:
            raise ContractError(
                f"report case {case_id} requested seeds differ from requested_cases"
            )
        case_acceptance = object_value(
            case_report["acceptance"],
            f"report case {case_id} acceptance",
            _CASE_REPORT_ACCEPTANCE_FIELDS,
            optional=_CASE_REPORT_ACCEPTANCE_OPTIONAL_FIELDS,
        )
        criteria = object_value(
            case_acceptance["criteria"],
            f"report case {case_id} acceptance criteria",
            _CASE_ACCEPTANCE_FIELDS,
            optional=_CASE_ACCEPTANCE_OPTIONAL_FIELDS,
        )
        if criteria != suite_criteria:
            raise ContractError(
                f"report case {case_id} acceptance differs from the suite"
            )
        threshold_rows = _validated_case_metrics(case_acceptance, thresholds, case_id)
        successes = integer_value(
            case_acceptance["successes"],
            f"report case {case_id} successes",
            minimum=0,
        )
        case_passed = boolean_value(
            case_acceptance["passed"], f"report case {case_id} passed"
        )
        case_aggregate = _validated_aggregate(
            case_report["aggregate"], f"report case {case_id} aggregate"
        )
        results = [
            _validated_result_v3(result, case_id)
            for result in array_value(
                case_report["results"], f"report case {case_id} results"
            )
        ]
        result_seeds = [
            integer_value(result["seed"], "result seed") for result in results
        ]
        if len(result_seeds) != len(set(result_seeds)) or not set(result_seeds) <= set(
            seeds
        ):
            raise ContractError(
                f"report case {case_id} result seeds must be unique suite seeds"
            )
        task_json = json.dumps(task.to_json(), sort_keys=True, separators=(",", ":"))
        lines.extend(
            [
                "",
                f"## Case `{case_id}`: {'PASS' if case_passed else 'FAIL'}",
                "",
                f"- Task: `{task_json}`",
                f"- Step cap: {cap}",
                f"- Requested seed order: {requested_seeds}",
                f"- Successes: {successes}/{len(seeds)} (required "
                f"{suite_criteria['min_successes']}, including "
                f"{suite_criteria['required_success_seeds']}).",
            ]
        )
        if threshold_rows:
            lines.extend(
                [
                    "",
                    "| Metric | Statistic | Bound | Value | Result |",
                    "| --- | --- | --- | ---: | --- |",
                ]
            )
            lines.extend(
                f"| {threshold.metric.value} | {threshold.statistic.value} "
                f"| {threshold.bound_text} "
                f"| {'-' if value is None else _compact_number(value)} "
                f"| {'pass' if passed else 'fail'} |"
                for threshold, value, passed in threshold_rows
            )
        if records_exploration:
            lines.extend(
                [
                    "",
                    "| Seed | Outcome | Success | Steps/turns | Depth/level | "
                    "Levels | Down/up | Probes/misses | Other changes | Legs | "
                    "Gold/score/return | Hunger | Explored | Worst hunger | HP/XL | "
                    "Death | Integrity |",
                    "| ---: | --- | --- | ---: | --- | ---: | --- | --- | ---: | "
                    "---: | --- | --- | ---: | --- | --- | --- | --- |",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "| Seed | Outcome | Success | Steps/turns | Depth/level | "
                    "Levels | Down/up | Probes/misses | Other changes | Legs | "
                    "Gold/score/return | Hunger | HP/XL | Death | Integrity |",
                    "| ---: | --- | --- | ---: | --- | ---: | --- | --- | ---: | "
                    "---: | --- | --- | --- | --- | --- |",
                ]
            )
        for result in results:
            seed = integer_value(result["seed"], "result seed")
            outcome = _optional_text(result["outcome"], "result outcome")
            metrics = EpisodeMetrics.from_json(result["metrics"])
            success = (
                outcome == RunOutcome.TASK_SUCCESS.value
                if task.environment is NleTask.STAIRCASE
                else metrics.objective_legs_completed == len(task.objective.legs)
            )
            deepest = (
                "-"
                if metrics.deepest_level is None
                else (
                    f"{metrics.deepest_level.dungeon_number}/"
                    f"{metrics.deepest_level.dungeon_level}"
                )
            )
            hunger = ",".join(state.value for state in metrics.hunger_states) or "-"
            integrity = boolean_value(result["integrity_ok"], "integrity_ok")
            lines.append(
                f"| {seed} | {outcome or '-'} | {'yes' if success else 'no'} "
                f"| {metrics.steps}/{metrics.game_turns} "
                f"| {metrics.max_depth}/{deepest} "
                f"| {len(metrics.levels_visited)} "
                f"| {metrics.down_stair_traversals}/{metrics.up_stair_traversals} "
                f"| {metrics.unknown_stair_probes}/{metrics.probe_misses} "
                f"| {metrics.level_changes_without_stair_action} "
                f"| {metrics.objective_legs_completed}/{len(task.objective.legs)} "
                f"| {metrics.final_gold}/{metrics.final_score}/"
                f"{metrics.task_return:.3f} "
                f"| {_md_cell(hunger)} "
                f"{_exploration_cells(metrics) if records_exploration else ''}"
                f"| {metrics.final_hit_points}/{metrics.final_experience_level} "
                f"| {_md_cell(metrics.death_cause)} "
                f"| {'ok' if integrity else 'FAIL'} |"
            )
            all_problems.extend(
                (case_id, seed, string_value(problem, "integrity problem"))
                for problem in array_value(
                    result["integrity_problems"], "result integrity_problems"
                )
            )
            error = _optional_text(result["error"], "result error")
            if error is not None:
                all_errors.append((case_id, seed, error))
        case_wall = number_value(case_aggregate["total_wall_seconds"], "case wall time")
        lines.extend(
            [
                "",
                f"- Case steps: {integer_value(case_aggregate['steps'], 'case steps')}",
                f"- Case wall time: {case_wall} s",
            ]
        )
    if seen_case_reports != set(suite_cases):
        raise ContractError("case_results must contain every suite case")

    decisions = object_value(
        aggregate["decisions"], "aggregate decisions", _DECISION_FIELDS
    )
    evaluated_episodes = integer_value(
        aggregate["evaluated_seeds"], "evaluated episodes"
    )
    successful_episodes = integer_value(
        aggregate["task_successes"], "successful episodes"
    )
    failed_decisions = integer_value(decisions["failed_decisions"], "failed decisions")
    repaired_decisions = integer_value(
        decisions["repaired_decisions"], "repaired decisions"
    )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Evaluated episodes: {evaluated_episodes}",
            f"- Successful episodes: {successful_episodes}",
            f"- Total steps: {integer_value(aggregate['steps'], 'aggregate steps')}",
            "- Total wall time: "
            f"{number_value(aggregate['total_wall_seconds'], 'aggregate wall time')} s",
            "- Model decisions: "
            f"{integer_value(decisions['model_decisions'], 'model decisions')} "
            f"(failed {failed_decisions}, "
            f"repaired {repaired_decisions})",
            "- Decision latency p50/p95/max: "
            f"{_optional_number(decisions['latency_p50_ms'], 'p50')}/"
            f"{_optional_number(decisions['latency_p95_ms'], 'p95')}/"
            f"{_optional_number(decisions['latency_max_ms'], 'max')} ms",
            "- Tokens prompt/output: "
            f"{integer_value(decisions['prompt_tokens'], 'prompt tokens')}/"
            f"{integer_value(decisions['output_tokens'], 'output tokens')}",
        ]
    )
    if all_problems or all_errors:
        lines.extend(["", "## Problems", ""])
        lines.extend(
            f"- {case_id} seed {seed}: {_md_cell(problem)}"
            for case_id, seed, problem in all_problems
        )
        lines.extend(
            f"- {case_id} seed {seed} error: {_md_cell(error)}"
            for case_id, seed, error in all_errors
        )
    return "\n".join(lines) + "\n"


# A report suite case: task, seeds, step cap, criteria JSON as the case report
# must repeat it, and the typed metric thresholds among those criteria.
type _ReportSuiteCase = tuple[
    TaskSpec, tuple[int, ...], int, dict[str, object], tuple[MetricThreshold, ...]
]


def _validated_report_suite_v3(
    value: object, *, allow_zero_min_successes: bool = False
) -> tuple[
    dict[str, object],
    str,
    str,
    str | None,
    dict[str, _ReportSuiteCase],
]:
    if not isinstance(value, dict):
        raise ContractError("report suite must be an object")
    legacy = "schema_version" not in value
    suite = object_value(
        value,
        "report suite",
        _SUITE_FIELDS_V2 if legacy else _SUITE_FIELDS_V3,
    )
    suite_id = _suite_identifier(suite["suite_id"], "report suite_id")
    string_value(suite["path"], "report suite path", minimum=1)
    string_value(suite["sha256"], "report suite sha256", minimum=64, maximum=64)
    character = string_value(suite["character"], "report suite character")
    if character != CHARACTER:
        raise ContractError(f"report suite character must be {CHARACTER}")
    _suite_text(suite["seed_selection"], "report suite seed_selection")
    _suite_text(suite["step_cap_rationale"], "report suite step_cap_rationale")
    suite_cases: dict[str, _ReportSuiteCase] = {}
    if legacy:
        if (
            string_value(suite["environment"], "report suite environment")
            != STAIRCASE_TASK.environment.value
        ):
            raise ContractError("legacy report suite must use NetHackStaircase-v0")
        seeds = tuple(_integers(suite["seeds"], "report suite seeds"))
        if not seeds or len(seeds) != len(set(seeds)):
            raise ContractError("report suite seeds must be unique and nonempty")
        cap = integer_value(
            suite["max_episode_steps"],
            "report suite max_episode_steps",
            minimum=1,
            maximum=100_000,
        )
        old = object_value(
            suite["acceptance"],
            "report suite acceptance",
            _ACCEPTANCE_CRITERIA_FIELDS,
        )
        minimum = integer_value(
            old["min_task_successes"],
            "report suite min_task_successes",
            minimum=1,
            maximum=len(seeds),
        )
        required = _integers(
            old["required_success_seeds"],
            "report suite required_success_seeds",
        )
        if len(required) != len(set(required)) or not set(required) <= set(seeds):
            raise ContractError(
                "report suite required seeds must be unique suite seeds"
            )
        integer_value(
            old["max_invalid_actions"],
            "report suite max_invalid_actions",
            minimum=0,
        )
        integer_value(
            old["max_gate_rejections"],
            "report suite max_gate_rejections",
            minimum=0,
        )
        boolean_value(
            old["require_complete_records"],
            "report suite require_complete_records",
        )
        suite_cases["staircase"] = (
            STAIRCASE_TASK,
            seeds,
            cap,
            {
                "min_successes": minimum,
                "required_success_seeds": required,
            },
            (),
        )
        return suite, suite_id, SCHEMA_1_POLICY_VERSION, None, suite_cases

    if integer_value(suite["schema_version"], "suite schema_version") != 2:
        raise ContractError("schema-3 reports require suite schema version 2")
    policy = _suite_identifier(suite["policy_version"], "report suite policy_version")
    knowledge_id = _suite_identifier(
        suite["knowledge_bundle_id"], "report suite knowledge_bundle_id"
    )
    global_criteria = object_value(
        suite["acceptance"], "report suite acceptance", _GLOBAL_ACCEPTANCE_FIELDS
    )
    integer_value(
        global_criteria["max_invalid_actions"],
        "report suite max_invalid_actions",
        minimum=0,
    )
    integer_value(
        global_criteria["max_gate_rejections"],
        "report suite max_gate_rejections",
        minimum=0,
    )
    boolean_value(
        global_criteria["require_complete_records"],
        "report suite require_complete_records",
    )
    for index, item in enumerate(array_value(suite["cases"], "report suite cases")):
        case = object_value(item, f"report suite case {index}", _SUITE_CASE_FIELDS)
        case_id = _suite_identifier(case["case_id"], f"report suite case {index} id")
        if case_id in suite_cases:
            raise ContractError("report suite case_id values must be unique")
        task = TaskSpec.from_json(case["task"], f"report suite case {case_id} task")
        seeds = tuple(_integers(case["seeds"], f"report suite case {case_id} seeds"))
        if not seeds or len(seeds) != len(set(seeds)):
            raise ContractError(
                f"report suite case {case_id} seeds must be unique and nonempty"
            )
        cap = integer_value(
            case["max_episode_steps"],
            f"report suite case {case_id} max_episode_steps",
            minimum=1,
            maximum=100_000,
        )
        criteria = object_value(
            case["acceptance"],
            f"report suite case {case_id} acceptance",
            _CASE_ACCEPTANCE_FIELDS,
            optional=_CASE_ACCEPTANCE_OPTIONAL_FIELDS,
        )
        thresholds = (
            _metric_thresholds(
                criteria["metric_thresholds"], f"report suite case {case_id}"
            )
            if "metric_thresholds" in criteria
            else ()
        )
        minimum = integer_value(
            criteria["min_successes"],
            f"report suite case {case_id} min_successes",
            minimum=0 if allow_zero_min_successes else _minimum_successes(thresholds),
            maximum=len(seeds),
        )
        required = _integers(
            criteria["required_success_seeds"],
            f"report suite case {case_id} required_success_seeds",
        )
        if len(required) != len(set(required)) or not set(required) <= set(seeds):
            raise ContractError(
                f"report suite case {case_id} required seeds must be unique case seeds"
            )
        suite_criteria: dict[str, object] = {
            "min_successes": minimum,
            "required_success_seeds": required,
        }
        if thresholds:
            suite_criteria["metric_thresholds"] = [
                threshold.to_json() for threshold in thresholds
            ]
        suite_cases[case_id] = (task, seeds, cap, suite_criteria, thresholds)
    if not suite_cases:
        raise ContractError("report suite cases must not be empty")
    return suite, suite_id, policy, knowledge_id, suite_cases


def _validated_aggregate(value: object, name: str) -> dict[str, object]:
    aggregate = object_value(value, name, _AGGREGATE_FIELDS)
    for field_name in (
        "evaluated_seeds",
        "task_successes",
        "steps",
        "gate_rejections",
        "decision_failures",
        "invalid_actions",
    ):
        integer_value(aggregate[field_name], f"{name} {field_name}", minimum=0)
    number_value(aggregate["total_wall_seconds"], f"{name} total_wall_seconds")
    decisions = object_value(
        aggregate["decisions"], f"{name} decisions", _DECISION_FIELDS
    )
    for field_name in (
        "model_decisions",
        "failed_decisions",
        "repaired_decisions",
        "latency_samples",
        "prompt_tokens",
        "output_tokens",
    ):
        integer_value(
            decisions[field_name], f"{name} decisions {field_name}", minimum=0
        )
    for field_name in ("latency_p50_ms", "latency_p95_ms", "latency_max_ms"):
        _optional_number(decisions[field_name], f"{name} decisions {field_name}")
    _integer_map(aggregate["outcomes"], f"{name} outcomes")
    _integer_map(aggregate["selection_sources"], f"{name} selection_sources")
    array_value(aggregate["integrity_failures"], f"{name} integrity_failures")
    return aggregate


def _results_record_exploration(case_reports: Sequence[object]) -> bool:
    """Whether the report's results record explored cells and worst hunger.

    Reports written before those metrics existed record them for no result;
    a report recording them for only some results is malformed.
    """
    recorded = {
        EpisodeMetrics.from_json(
            object_value(result, "report result", _RESULT_FIELDS_V3)["metrics"]
        ).explored_cells
        is not None
        for case in case_reports
        for result in array_value(
            object_value(case, "report case", _CASE_REPORT_FIELDS)["results"],
            "report case results",
        )
    }
    if len(recorded) > 1:
        raise ContractError(
            "report results must all record explored_cells and worst_hunger_state "
            "or all omit them"
        )
    return recorded == {True}


def _validated_case_metrics(
    case_acceptance: dict[str, object],
    thresholds: tuple[MetricThreshold, ...],
    case_id: str,
) -> list[tuple[MetricThreshold, float | None, bool]]:
    """The case's recorded threshold results, in suite threshold order."""
    name = f"report case {case_id} acceptance metrics"
    if "metrics" not in case_acceptance:
        if thresholds:
            raise ContractError(f"{name} are missing for the suite thresholds")
        return []
    if not thresholds:
        raise ContractError(f"{name} are recorded without suite thresholds")
    items = array_value(case_acceptance["metrics"], name)
    if len(items) != len(thresholds):
        raise ContractError(f"{name} must match the suite thresholds")
    rows: list[tuple[MetricThreshold, float | None, bool]] = []
    for threshold, item in zip(thresholds, items, strict=True):
        entry = object_value(item, f"{name} entry", _CASE_REPORT_METRIC_FIELDS)
        recorded = MetricThreshold.from_json(
            {key: entry[key] for key in ("metric", "statistic", "bound")},
            f"{name} entry",
        )
        if recorded != threshold:
            raise ContractError(f"{name} must match the suite thresholds")
        rows.append(
            (
                threshold,
                _optional_number(entry["value"], f"{name} value"),
                boolean_value(entry["passed"], f"{name} passed"),
            )
        )
    return rows


def _exploration_cells(metrics: EpisodeMetrics) -> str:
    worst = metrics.worst_hunger_state
    return f"| {metrics.explored_cells} | {'-' if worst is None else worst.value} "


def _validated_result_v3(value: object, case_id: str) -> dict[str, object]:
    result = object_value(value, "report result", _RESULT_FIELDS_V3)
    if string_value(result["case_id"], "result case_id") != case_id:
        raise ContractError("report result case_id differs from its case")
    integer_value(result["seed"], "result seed", minimum=1)
    _optional_text(result["run_id"], "result run_id")
    if result["outcome"] is not None:
        enum_value(result["outcome"], "result outcome", RunOutcome)
    if result["final_state"] is not None:
        enum_value(result["final_state"], "result final_state", RunState)
    string_value(result["ended_by"], "result ended_by", minimum=1)
    steps = integer_value(result["steps"], "result steps", minimum=0)
    metrics = EpisodeMetrics.from_json(result["metrics"])
    if steps != metrics.steps:
        raise ContractError("result steps must equal episode metrics steps")
    number_value(result["wall_seconds"], "result wall_seconds")
    object_value(result["decisions"], "result decisions", _DECISION_FIELDS)
    _integer_map(result["selection_sources"], "result selection_sources")
    for field_name in (
        "gate_rejections",
        "decision_failures",
        "invalid_actions",
        "event_count",
    ):
        integer_value(result[field_name], f"result {field_name}", minimum=0)
    _optional_text(result["error"], "result error")
    _optional_text(result["ttyrec_path"], "result ttyrec_path")
    boolean_value(result["ttyrec_exists"], "result ttyrec_exists")
    boolean_value(result["integrity_ok"], "result integrity_ok")
    [
        string_value(item, "result integrity problem")
        for item in array_value(
            result["integrity_problems"], "result integrity_problems"
        )
    ]
    configuration = result["configuration"]
    if configuration is not None:
        object_value(configuration, "result configuration", _RUN_CONFIGURATION_FIELDS)
    _optional_text(result["ollama_version"], "result ollama_version")
    return result


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


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
    timestamps) is kept verbatim; results are never re-audited. Only the status
    and status reason change (schema 1 gains schema 2's reason field), and both
    the JSON and its sibling Markdown are rewritten atomically.
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
        if version not in (1, LEGACY_REPORT_SCHEMA_VERSION, REPORT_SCHEMA_VERSION, 4):
            raise ContractError(
                "report_schema_version must be 1, "
                f"{LEGACY_REPORT_SCHEMA_VERSION}, {REPORT_SCHEMA_VERSION}, or 4"
            )
        fields = (
            _REPORT_FIELDS_V1
            if version == 1
            else _REPORT_FIELDS_V2
            if version == LEGACY_REPORT_SCHEMA_VERSION
            else _REPORT_FIELDS_V3
            if version == REPORT_SCHEMA_VERSION
            else _REPORT_FIELDS_V4
        )
        object_value(payload, "evaluation report", fields)
        status = enum_value(payload["status"], "report status", ReportStatus)
        if status not in _ABORTABLE_STATUSES:
            raise EvaluationError(
                f"only running or interrupted reports can be aborted; "
                f"{paths.json} is {status.value}"
            )
        finalized = {
            **payload,
            "report_schema_version": (
                LEGACY_REPORT_SCHEMA_VERSION if version == 1 else version
            ),
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
    draw_seed: int | None = None
    compare_report: Path | None = None
    development_scripted_model: bool = False
    progress_interval_seconds: float = 30.0
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.suite.fresh_sample is not None and self.seeds is not None:
            raise ValueError("--seeds cannot be combined with a fresh_sample")
        if self.draw_seed is not None and (
            type(self.draw_seed) is not int or self.draw_seed < 0
        ):
            raise ValueError("draw_seed must be a nonnegative integer")
        if self.draw_seed is not None and self.suite.fresh_sample is None:
            raise ValueError("--draw-seed requires a fresh_sample")
        if self.compare_report is not None and self.suite.schema_version != 3:
            raise ValueError("--compare-report requires a schema-3 suite")
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


def require_suite_policy(suite: EvaluationSuite, policy_version: str) -> None:
    """Refuse to evaluate a suite under a policy it was not fixed for."""
    if policy_version == suite.policy_version:
        return
    reproduction = (
        f"; check out a commit with policy {SCHEMA_1_POLICY_VERSION} to reproduce it"
        if suite.legacy
        else ""
    )
    raise SuiteValidationError(
        f"suite {suite.suite_id} (schema {suite.schema_version}) is bound to "
        f"policy {suite.policy_version}, but this checkout runs policy "
        f"{policy_version}{reproduction}"
    )


def require_suite_configuration(
    suite: EvaluationSuite, policy_version: str, knowledge_bundle_id: str
) -> None:
    require_suite_policy(suite, policy_version)
    if not suite.legacy and suite.knowledge_bundle_id != knowledge_bundle_id:
        raise SuiteValidationError(
            f"suite {suite.suite_id} (schema {suite.schema_version}) is bound to "
            f"knowledge bundle {suite.knowledge_bundle_id}, but this checkout "
            f"loads {knowledge_bundle_id}"
        )


def _prior_drawn_seeds(directory: Path) -> frozenset[int]:
    seen: set[int] = set()
    for path in sorted(directory.glob("*.json")):
        try:
            payload = load_json_object(
                path.read_text(encoding="utf-8"), "evaluation report"
            )
            if payload.get("report_schema_version") != 4:
                continue
            provenance = payload.get("draw_provenance")
            if provenance is not None:
                seen.update(DrawProvenance.from_json(provenance).drawn_seeds)
        except (OSError, UnicodeDecodeError, ContractError, ValueError) as error:
            raise EvaluationError(
                f"cannot read previous seed draw {path}: {error}"
            ) from error
    return frozenset(seen)


def _draw_available_seeds(
    seed_range: tuple[int, int],
    excluded: tuple[int, ...],
    draw_seed: int,
    count: int,
) -> tuple[int, ...]:
    """Map sampled ranks to seed values without materializing the full range."""
    from bisect import bisect_right

    first, last = seed_range
    available = last - first + 1 - len(excluded)
    if available < count:
        raise EvaluationError(
            f"fresh_sample needs {count} seeds but only {available} remain "
            f"in range {first}-{last} after {len(excluded)} exclusions"
        )
    ranks = random.Random(draw_seed).sample(range(available), count)
    drawn: list[int] = []
    for rank in ranks:
        low, high = first, last
        while low < high:
            mid = (low + high) // 2
            allowed = mid - first + 1 - bisect_right(excluded, mid)
            if allowed <= rank:
                low = mid + 1
            else:
                high = mid
        drawn.append(low)
    return tuple(drawn)


def _fresh_draw(
    suite: EvaluationSuite, draw_seed: int, report_directory: Path | None = None
) -> DrawProvenance:
    from nethack_agent.seed_catalog import used_seeds

    fresh = suite.fresh_sample
    if fresh is None:
        raise ValueError("suite has no fresh_sample")
    if type(draw_seed) is not int or draw_seed < 0:
        raise ValueError("draw_seed must be a nonnegative integer")
    directories = {suite.path.parent / "reports"}
    if report_directory is not None:
        directories.add(report_directory)
    prior = set().union(*(_prior_drawn_seeds(directory) for directory in directories))
    first, last = fresh.seed_range
    excluded = tuple(
        sorted(
            seed
            for seed in used_seeds(suite.path.parent) | prior
            if first <= seed <= last
        )
    )
    seeds = _draw_available_seeds(fresh.seed_range, excluded, draw_seed, fresh.count)
    return DrawProvenance(draw_seed, fresh.seed_range, excluded, seeds)


def draw_fresh_seeds(
    suite: EvaluationSuite, draw_seed: int
) -> tuple[tuple[int, ...], int]:
    """Draw reproducible unused seeds and return the exclusion count."""
    provenance = _fresh_draw(suite, draw_seed)
    return provenance.drawn_seeds, len(provenance.excluded_seeds)


def _load_comparison_report(path: Path, suite: EvaluationSuite) -> dict[str, object]:
    try:
        payload = load_json_object(
            path.read_text(encoding="utf-8"), "comparison report"
        )
        prior = object_value(
            payload.get("suite"),
            "comparison suite",
            payload["suite"].keys() if isinstance(payload.get("suite"), dict) else (),
        )
        if prior.get("suite_id") != suite.suite_id:
            raise EvaluationError(
                f"comparison report suite_id does not match {suite.suite_id}"
            )
        if payload.get("report_schema_version") != 4:
            raise EvaluationError("comparison report must have report schema 4")
        if prior.get("sha256") != suite.sha256:
            raise EvaluationError("comparison report suite sha256 does not match")
        render_report_markdown(payload)
        return payload
    except (OSError, UnicodeDecodeError, ContractError) as error:
        raise EvaluationError(
            f"cannot read comparison report {path}: {error}"
        ) from error


def run_evaluation(
    options: EvaluationOptions,
    *,
    ollama_config: OllamaConfig | None = None,
    progress: TextIO | None = sys.stderr,
) -> EvaluationRun:
    suite = options.suite
    knowledge_bundle = load_default_knowledge_bundle()
    require_suite_configuration(suite, POLICY_VERSION, knowledge_bundle.bundle_id)
    comparison_source = (
        _load_comparison_report(options.compare_report, suite)
        if options.compare_report is not None
        else None
    )
    draw_provenance: DrawProvenance | None = None
    if suite.fresh_sample is not None:
        fresh = suite.fresh_sample
        draw_seed = (
            options.draw_seed if options.draw_seed is not None else secrets.randbits(32)
        )
        draw_provenance = _fresh_draw(suite, draw_seed, options.report_directory)
        seeds = draw_provenance.drawn_seeds
        suite = replace(
            suite,
            cases=suite.cases
            + (
                EvaluationCase(
                    fresh.case_id,
                    fresh.task,
                    seeds,
                    fresh.max_episode_steps,
                    CaseAcceptance(0, (), fresh.acceptance.metric_thresholds),
                ),
            ),
        )
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

    manager = RunManager(
        options.data_directory,
        config,
        model_factory=model_factory,
        knowledge_bundle=knowledge_bundle,
    )
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
        draw_provenance=draw_provenance,
        comparison_source=comparison_source,
    )
    mode_suffix = "-development" if report.development_model else ""
    stem = f"{suite.suite_id}{mode_suffix}-{_compact_timestamp(started_at)}"
    writer = ReportWriter(options.report_directory, stem)
    log = _Progress(progress)
    interrupted = False
    episodes = [
        (case, seed)
        for case in suite.cases
        for seed in report.requested_seeds
        if seed in case.seeds
    ]
    try:
        writer.write(report)
        for position, (case, seed) in enumerate(episodes, start=1):
            label = f"{case.case_id} seed {seed}"
            log(f"{label} ({position}/{len(episodes)}) starting")
            result, interrupted = _evaluate_seed(manager, options, case, seed, log)
            report.results.append(result)
            writer.write(report)
            stats = result.decision_stats
            log(
                f"{label} ({position}/{len(episodes)}) "
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
                if len(report.results) != len(episodes)
                else ReportStatus.COMPLETE
                if all(
                    set(report._requested_for_case(case)) == set(case.seeds)
                    for case in suite.cases
                )
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
    case: EvaluationCase,
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
            seed=seed,
            max_episode_steps=case.max_episode_steps,
            auto_start=True,
            task=case.task,
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
                    case.case_id,
                    seed,
                    str(error),
                    time.monotonic() - started,
                    "create_failed",
                ),
                False,
            )
        raise
    if run_id is None:
        return (
            _creation_failure(
                case.case_id,
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
            case=case,
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
    case_id: str, seed: int, error: str, wall_seconds: float, ended_by: str
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
        case_id=case_id,
    )


def _inputs_unchanged(report: EvaluationReport) -> bool:
    try:
        suite_digest = hashlib.sha256(report.suite.path.read_bytes()).hexdigest()
        knowledge_version = load_default_knowledge_bundle().version
        catalog_unchanged = True
        if report.suite.baseline:
            catalog_path = report.suite.catalog_path
            if catalog_path is None:
                return False
            catalog_digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
            catalog_unchanged = catalog_digest == report.suite.catalog_sha256
    except Exception:
        return False
    return (
        suite_digest == report.suite.sha256
        and knowledge_version == report.knowledge_version
        and catalog_unchanged
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
