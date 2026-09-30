"""Representative-seed catalog and used-seed ledger (ADR 0005 sections 2-3).

The catalog names reviewed seeds whose runs show one behavior or failure each;
its expectations are checked with the scripted development model. The ledger
records seeds that probes and development runs have already used, so fresh
samples can exclude every seen seed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, TextIO

from nethack_agent.contracts import (
    ContractError,
    array_value,
    enum_value,
    integer_value,
    load_json_object,
    object_value,
    string_value,
)
from nethack_agent.decision import RunOutcome
from nethack_agent.environment import CHARACTER
from nethack_agent.evaluation import (
    SUITE_SCHEMA_VERSION,
    EvaluationError,
    EvaluationOptions,
    EvaluationSuite,
    ReportPaths,
    SeedResult,
    _suite_identifier,
    load_suite,
    run_evaluation,
)
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.run_manager import POLICY_VERSION
from nethack_agent.tasks import TaskSpec
from nethack_agent.traversal import (
    EnterDungeonLeg,
    ExploreDungeonLeg,
    ObjectiveLeg,
    ReachLevelLeg,
    StandOnStairsLeg,
)

CATALOG_SCHEMA_VERSION: Final = 1
LEDGER_SCHEMA_VERSION: Final = 1
CATALOG_FILE_NAME: Final = "representative-seeds.json"
LEDGER_FILE_NAME: Final = "seed-ledger.json"
DEFAULT_CATALOG_PATH: Final = Path("evaluation") / CATALOG_FILE_NAME
CHECK_SUITE_ID: Final = "representative-seeds-check"
MAX_SEED: Final = 2**31 - 1
MAX_TEXT_LENGTH: Final = 300
_SUCCESS_OUTCOMES: Final = frozenset(
    {RunOutcome.TASK_SUCCESS, RunOutcome.OBJECTIVE_COMPLETE}
)
_ENTRY_FIELDS: Final = (
    "entry_id",
    "seed",
    "task",
    "max_episode_steps",
    "represents",
    "provenance",
    "expectation",
    "outcome",
    "test",
)


class CatalogError(EvaluationError):
    """A catalog or ledger file cannot be read or violates its contract."""


class CatalogExpectation(Enum):
    MUST_PASS = "must_pass"
    KNOWN_FAILURE = "known_failure"


class CatalogCheckStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    IMPROVED = "improved"
    CHANGED = "changed"


def _seed(value: object, name: str) -> int:
    return integer_value(value, name, minimum=1, maximum=MAX_SEED)


def _text(value: object, name: str) -> str:
    return string_value(value, name, minimum=1, maximum=MAX_TEXT_LENGTH, strip=True)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One reviewed seed, its task, and what the scripted model does with it."""

    entry_id: str
    seed: int
    task: TaskSpec
    max_episode_steps: int
    represents: str
    provenance: str
    expectation: CatalogExpectation
    # The outcome observed with the scripted development model when the
    # expectation was last established.
    outcome: RunOutcome
    test: str | None

    def __post_init__(self) -> None:
        succeeded = self.outcome in _SUCCESS_OUTCOMES
        if self.expectation is CatalogExpectation.MUST_PASS and not succeeded:
            raise ContractError(
                f"catalog entry {self.entry_id}: a must_pass outcome must be "
                "task_success or objective_complete"
            )
        if self.expectation is CatalogExpectation.KNOWN_FAILURE and succeeded:
            raise ContractError(
                f"catalog entry {self.entry_id}: a known_failure outcome must not "
                "be task_success or objective_complete"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "seed": self.seed,
            "task": self.task.to_json(),
            "max_episode_steps": self.max_episode_steps,
            "represents": self.represents,
            "provenance": self.provenance,
            "expectation": self.expectation.value,
            "outcome": self.outcome.value,
            "test": self.test,
        }

    @classmethod
    def from_json(cls, value: object, name: str) -> CatalogEntry:
        payload = object_value(value, name, _ENTRY_FIELDS)
        test = payload["test"]
        return cls(
            entry_id=_suite_identifier(payload["entry_id"], f"{name} entry_id"),
            seed=_seed(payload["seed"], f"{name} seed"),
            task=TaskSpec.from_json(payload["task"], f"{name} task"),
            max_episode_steps=integer_value(
                payload["max_episode_steps"],
                f"{name} max_episode_steps",
                minimum=1,
                maximum=100_000,
            ),
            represents=_text(payload["represents"], f"{name} represents"),
            provenance=_text(payload["provenance"], f"{name} provenance"),
            expectation=enum_value(
                payload["expectation"], f"{name} expectation", CatalogExpectation
            ),
            outcome=enum_value(payload["outcome"], f"{name} outcome", RunOutcome),
            test=None if test is None else _text(test, f"{name} test"),
        )


@dataclass(frozen=True, slots=True)
class SeedCatalog:
    # The policy under which the entries' expectations were last established.
    policy_version: str
    entries: tuple[CatalogEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise ContractError("catalog entries must not be empty")
        identifiers = [entry.entry_id for entry in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ContractError("catalog entry_id values must be unique")
        runs = [(entry.seed, entry.task.canonical_json()) for entry in self.entries]
        if len(runs) != len(set(runs)):
            raise ContractError("catalog entries must not repeat a seed and task")

    @property
    def seeds(self) -> frozenset[int]:
        return frozenset(entry.seed for entry in self.entries)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "policy_version": self.policy_version,
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, value: object, name: str = "seed catalog") -> SeedCatalog:
        payload = object_value(
            value, name, ("schema_version", "policy_version", "entries")
        )
        version = integer_value(payload["schema_version"], f"{name} schema_version")
        if version != CATALOG_SCHEMA_VERSION:
            raise ContractError(
                f"{name} schema_version must be {CATALOG_SCHEMA_VERSION}"
            )
        items = array_value(payload["entries"], f"{name} entries")
        return cls(
            policy_version=_suite_identifier(
                payload["policy_version"], f"{name} policy_version"
            ),
            entries=tuple(
                CatalogEntry.from_json(item, f"{name} entry {index}")
                for index, item in enumerate(items)
            ),
        )


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Seeds one probe or development activity used, with where it is recorded."""

    source: str
    seeds: tuple[int, ...]
    # Inclusive (first, last) seed ranges.
    ranges: tuple[tuple[int, int], ...]
    note: str

    def __post_init__(self) -> None:
        if not self.seeds and not self.ranges:
            raise ContractError(f"ledger entry {self.source} needs seeds or ranges")
        for first, last in self.ranges:
            if first > last:
                raise ContractError(
                    f"ledger entry {self.source} range {first}-{last} is reversed"
                )

    @property
    def seed_values(self) -> frozenset[int]:
        values = set(self.seeds)
        for first, last in self.ranges:
            values.update(range(first, last + 1))
        return frozenset(values)

    def to_json(self) -> dict[str, object]:
        return {
            "source": self.source,
            "seeds": list(self.seeds),
            "ranges": [[first, last] for first, last in self.ranges],
            "note": self.note,
        }

    @classmethod
    def from_json(cls, value: object, name: str) -> LedgerEntry:
        payload = object_value(value, name, ("source", "seeds", "ranges", "note"))
        ranges = []
        for item in array_value(payload["ranges"], f"{name} ranges"):
            bounds = array_value(item, f"{name} range")
            if len(bounds) != 2:
                raise ContractError(f"{name} range must be [first, last]")
            ranges.append(
                (_seed(bounds[0], f"{name} range"), _seed(bounds[1], f"{name} range"))
            )
        return cls(
            source=_suite_identifier(payload["source"], f"{name} source"),
            seeds=tuple(
                _seed(item, f"{name} seed")
                for item in array_value(payload["seeds"], f"{name} seeds")
            ),
            ranges=tuple(ranges),
            note=_text(payload["note"], f"{name} note"),
        )


@dataclass(frozen=True, slots=True)
class SeedLedger:
    entries: tuple[LedgerEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise ContractError("seed ledger entries must not be empty")

    @property
    def seeds(self) -> frozenset[int]:
        return frozenset().union(*(entry.seed_values for entry in self.entries))

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "entries": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, value: object, name: str = "seed ledger") -> SeedLedger:
        payload = object_value(value, name, ("schema_version", "entries"))
        version = integer_value(payload["schema_version"], f"{name} schema_version")
        if version != LEDGER_SCHEMA_VERSION:
            raise ContractError(
                f"{name} schema_version must be {LEDGER_SCHEMA_VERSION}"
            )
        items = array_value(payload["entries"], f"{name} entries")
        return cls(
            tuple(
                LedgerEntry.from_json(item, f"{name} entry {index}")
                for index, item in enumerate(items)
            )
        )


def _load_object(path: Path, name: str) -> dict[str, object]:
    try:
        return load_json_object(path.read_bytes().decode("utf-8"), name)
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogError(f"{name} {path} cannot be read: {error}") from error
    except ContractError as error:
        raise CatalogError(f"invalid {name} {path}: {error}") from error


def load_catalog(path: Path) -> SeedCatalog:
    payload = _load_object(path, "seed catalog")
    try:
        return SeedCatalog.from_json(payload)
    except ContractError as error:
        raise CatalogError(f"invalid seed catalog {path}: {error}") from error


def load_ledger(path: Path) -> SeedLedger:
    payload = _load_object(path, "seed ledger")
    try:
        return SeedLedger.from_json(payload)
    except ContractError as error:
        raise CatalogError(f"invalid seed ledger {path}: {error}") from error


def used_seeds(evaluation_directory: Path) -> frozenset[int]:
    """Every seed a committed suite, the catalog, or the ledger has used."""
    seeds: set[int] = set()
    for path in sorted(evaluation_directory.glob("*.json")):
        if path.name not in (CATALOG_FILE_NAME, LEDGER_FILE_NAME):
            seeds.update(load_suite(path).seeds)
    seeds.update(load_catalog(evaluation_directory / CATALOG_FILE_NAME).seeds)
    seeds.update(load_ledger(evaluation_directory / LEDGER_FILE_NAME).seeds)
    return frozenset(seeds)


def _leg_label(leg: ObjectiveLeg) -> str:
    if isinstance(leg, StandOnStairsLeg):
        target = leg.target
        arguments = [target.direction.value, target.connection.value]
        if target.dungeon_number is not None:
            arguments.append(str(target.dungeon_number))
    elif isinstance(leg, ReachLevelLeg):
        arguments = [str(leg.level.dungeon_number), str(leg.level.dungeon_level)]
    elif isinstance(leg, EnterDungeonLeg):
        arguments = [str(leg.dungeon_number)]
    elif isinstance(leg, ExploreDungeonLeg):
        arguments = [str(leg.max_level)]
    else:
        arguments = []
    return f"{leg.kind.value}({', '.join(arguments)})"


def _task_label(task: TaskSpec) -> str:
    legs = " then ".join(_leg_label(leg) for leg in task.objective.legs)
    return f"{task.environment.value} {legs}"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_catalog_markdown(catalog: SeedCatalog) -> str:
    """The human-readable catalog; generated, never edited by hand."""
    lines = [
        "# Representative seeds",
        "",
        f"Generated from `{CATALOG_FILE_NAME}` by "
        "`nethack-agent eval catalog render`; do not edit by hand.",
        "",
        "Expectations were established with the scripted development model "
        f"under policy `{catalog.policy_version}`.",
        "",
        "| Entry | Seed | Task | Cap | Expectation | Scripted outcome "
        "| Represents | Provenance | Test |",
        "| --- | ---: | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for entry in catalog.entries:
        cells = (
            f"`{entry.entry_id}`",
            str(entry.seed),
            _task_label(entry.task),
            str(entry.max_episode_steps),
            entry.expectation.value,
            entry.outcome.value,
            entry.represents,
            entry.provenance,
            "-" if entry.test is None else f"`{entry.test}`",
        )
        lines.append("| " + " | ".join(_md_cell(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def catalog_suite_payload(
    catalog: SeedCatalog, policy_version: str, knowledge_bundle_id: str
) -> dict[str, object]:
    """A schema-2 suite with one single-seed case per catalog entry."""
    return {
        "schema_version": SUITE_SCHEMA_VERSION,
        "suite_id": CHECK_SUITE_ID,
        "character": CHARACTER,
        "policy_version": policy_version,
        "knowledge_bundle_id": knowledge_bundle_id,
        "seed_selection": (
            "Generated from the representative-seed catalog: one case per "
            "entry, with that entry's seed."
        ),
        "step_cap_rationale": "Each case uses its catalog entry's step cap.",
        "cases": [
            {
                "case_id": entry.entry_id,
                "task": entry.task.to_json(),
                "seeds": [entry.seed],
                "max_episode_steps": entry.max_episode_steps,
                "acceptance": {"min_successes": 1, "required_success_seeds": []},
            }
            for entry in catalog.entries
        ],
        "acceptance": {
            "max_invalid_actions": 0,
            "max_gate_rejections": 0,
            "require_complete_records": True,
        },
    }


@dataclass(frozen=True, slots=True)
class CatalogCheck:
    entry_id: str
    seed: int
    expectation: CatalogExpectation
    expected_outcome: RunOutcome
    observed_outcome: RunOutcome | None
    successful: bool
    invariants_ok: bool
    status: CatalogCheckStatus
    detail: str

    def to_json(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "seed": self.seed,
            "expectation": self.expectation.value,
            "expected_outcome": self.expected_outcome.value,
            "observed_outcome": (
                None if self.observed_outcome is None else self.observed_outcome.value
            ),
            "successful": self.successful,
            "invariants_ok": self.invariants_ok,
            "status": self.status.value,
            "detail": self.detail,
        }


def check_catalog(
    catalog: SeedCatalog, suite: EvaluationSuite, results: Sequence[SeedResult]
) -> tuple[CatalogCheck, ...]:
    """Compare each entry's run with its expectation, in catalog order."""
    by_case = {result.case_id: result for result in results}
    return tuple(
        _check_entry(entry, suite, by_case.get(entry.entry_id))
        for entry in catalog.entries
    )


def _check_entry(
    entry: CatalogEntry, suite: EvaluationSuite, result: SeedResult | None
) -> CatalogCheck:
    if result is None:
        return CatalogCheck(
            entry.entry_id,
            entry.seed,
            entry.expectation,
            entry.outcome,
            None,
            False,
            False,
            CatalogCheckStatus.FAIL,
            "no result",
        )
    problems = list(result.integrity_problems)
    if result.invalid_actions:
        problems.append(f"{result.invalid_actions} invalid actions")
    if result.gate_rejections:
        problems.append(f"{result.gate_rejections} gate rejections")
    if result.error is not None:
        problems.append(f"error: {result.error}")
    successful = result.successful_for(suite.case(entry.entry_id))
    observed = result.outcome
    if problems:
        status, detail = CatalogCheckStatus.FAIL, "; ".join(problems)
    elif entry.expectation is CatalogExpectation.MUST_PASS:
        if successful and observed is entry.outcome:
            status, detail = CatalogCheckStatus.PASS, "succeeded as expected"
        else:
            status, detail = (
                CatalogCheckStatus.FAIL,
                "must_pass entry did not succeed with its expected outcome",
            )
    elif successful:
        status, detail = (
            CatalogCheckStatus.IMPROVED,
            "known failure now succeeds; update the catalog",
        )
    elif observed is not entry.outcome:
        status, detail = (
            CatalogCheckStatus.CHANGED,
            "known failure ended differently; update the catalog",
        )
    else:
        status, detail = CatalogCheckStatus.PASS, "failed as expected"
    return CatalogCheck(
        entry.entry_id,
        entry.seed,
        entry.expectation,
        entry.outcome,
        observed,
        successful,
        not problems,
        status,
        detail,
    )


def run_catalog_check(
    catalog: SeedCatalog,
    data_directory: Path,
    report_directory: Path,
    *,
    progress: TextIO | None = sys.stderr,
) -> tuple[tuple[CatalogCheck, ...], ReportPaths]:
    """Run every entry with the scripted development model and check it."""
    bundle = load_default_knowledge_bundle()
    report_directory.mkdir(parents=True, exist_ok=True)
    suite_path = report_directory / f"{CHECK_SUITE_ID}-suite.json"
    payload = catalog_suite_payload(catalog, POLICY_VERSION, bundle.bundle_id)
    suite_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    suite = load_suite(suite_path)
    run = run_evaluation(
        EvaluationOptions(
            suite=suite,
            data_directory=data_directory,
            report_directory=report_directory,
            development_scripted_model=True,
        ),
        progress=progress,
    )
    if run.interrupted:
        raise CatalogError("catalog check was interrupted")
    return check_catalog(catalog, suite, run.report.results), run.paths
