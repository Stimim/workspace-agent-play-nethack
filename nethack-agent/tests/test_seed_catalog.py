from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nethack_agent.decision import DecisionMetrics, RunOutcome, RunState
from nethack_agent.evaluation import DecisionStats, SeedResult, load_suite
from nethack_agent.seed_catalog import (
    CatalogCheckStatus,
    CatalogEntry,
    CatalogError,
    CatalogExpectation,
    SeedCatalog,
    catalog_suite_payload,
    check_catalog,
    load_catalog,
    load_ledger,
    render_catalog_markdown,
    used_seeds,
)
from nethack_agent.tasks import STAIRCASE_TASK

EVALUATION_DIRECTORY = Path(__file__).resolve().parents[1] / "evaluation"
CATALOG_PATH = EVALUATION_DIRECTORY / "representative-seeds.json"
LEDGER_PATH = EVALUATION_DIRECTORY / "seed-ledger.json"
SUITE_PATH = EVALUATION_DIRECTORY / "staircase-v1.json"


def payload_of(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def first_entry(payload: dict[str, object]) -> tuple[list[object], dict[str, object]]:
    entries = payload["entries"]
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    return entries, entry


def staircase_entry(
    entry_id: str, seed: int, expectation: CatalogExpectation, outcome: RunOutcome
) -> CatalogEntry:
    return CatalogEntry(
        entry_id=entry_id,
        seed=seed,
        task=STAIRCASE_TASK,
        max_episode_steps=1000,
        represents="A behavior under test.",
        provenance="A test fixture.",
        expectation=expectation,
        outcome=outcome,
        test=None,
    )


def seed_result(
    case_id: str, seed: int, outcome: RunOutcome, **changes: object
) -> SeedResult:
    base = SeedResult(
        seed=seed,
        run_id=f"run-{seed}",
        outcome=outcome,
        final_state=RunState.TERMINAL,
        ended_by="episode_end",
        steps=10,
        wall_seconds=1.5,
        decision_stats=DecisionStats.from_metrics(
            [DecisionMetrics(100, 10, 1.0, False)]
        ),
        selection_sources={"deterministic_skill": 10},
        gate_rejections=0,
        decision_failures=0,
        invalid_actions=0,
        error=None,
        ttyrec_path="runs/x/nle.ttyrec.bz2",
        ttyrec_exists=True,
        event_count=12,
        integrity_problems=(),
        configuration=None,
        ollama_version=None,
        case_id=case_id,
    )
    return replace(base, **changes)


def test_committed_catalog_markdown_is_rendered_from_its_json() -> None:
    catalog = load_catalog(CATALOG_PATH)

    rendered = render_catalog_markdown(catalog)

    assert CATALOG_PATH.with_suffix(".md").read_text(encoding="utf-8") == rendered


@pytest.mark.parametrize(
    "malformation",
    [
        "unknown_field",
        "duplicate_id",
        "duplicate_run",
        "must_pass_death",
        "known_failure_success",
        "seed_too_large",
    ],
)
def test_catalog_contract_is_strict(tmp_path: Path, malformation: str) -> None:
    payload = payload_of(CATALOG_PATH)
    entries, entry = first_entry(payload)
    copy = json.loads(json.dumps(entry))
    if malformation == "unknown_field":
        entry["unexpected"] = True
    elif malformation == "duplicate_id":
        copy["seed"] = 999_999
        entries.append(copy)
    elif malformation == "duplicate_run":
        copy["entry_id"] = "duplicate-run"
        entries.append(copy)
    elif malformation == "must_pass_death":
        entry["expectation"] = "must_pass"
        entry["outcome"] = "death"
    elif malformation == "known_failure_success":
        entry["expectation"] = "known_failure"
        entry["outcome"] = "task_success"
    else:
        entry["seed"] = 2**31

    with pytest.raises(CatalogError):
        load_catalog(write_json(tmp_path / "catalog.json", payload))


@pytest.mark.parametrize("malformation", ["reversed_range", "no_seeds"])
def test_ledger_contract_is_strict(tmp_path: Path, malformation: str) -> None:
    payload = payload_of(LEDGER_PATH)
    _, entry = first_entry(payload)
    if malformation == "reversed_range":
        entry["ranges"] = [[5, 4]]
    else:
        entry["seeds"] = []
        entry["ranges"] = []

    with pytest.raises(CatalogError):
        load_ledger(write_json(tmp_path / "ledger.json", payload))


def test_check_suite_runs_each_catalog_entry_as_its_own_case(tmp_path: Path) -> None:
    catalog = load_catalog(CATALOG_PATH)
    payload = catalog_suite_payload(
        catalog, "policy-under-test", "knowledge-under-test"
    )

    suite = load_suite(write_json(tmp_path / "suite.json", payload))

    assert suite.policy_version == "policy-under-test"
    assert [
        (case.case_id, case.seeds, case.task, case.max_episode_steps)
        for case in suite.cases
    ] == [
        (entry.entry_id, (entry.seed,), entry.task, entry.max_episode_steps)
        for entry in catalog.entries
    ]


MUST = CatalogExpectation.MUST_PASS
KNOWN = CatalogExpectation.KNOWN_FAILURE


@pytest.mark.parametrize(
    ("expectation", "expected", "observed", "changes", "status"),
    [
        (MUST, RunOutcome.TASK_SUCCESS, RunOutcome.TASK_SUCCESS, {}, "pass"),
        (MUST, RunOutcome.TASK_SUCCESS, RunOutcome.DEATH, {}, "fail"),
        (
            MUST,
            RunOutcome.TASK_SUCCESS,
            RunOutcome.TASK_SUCCESS,
            {"integrity_problems": ("ttyrec is missing",)},
            "fail",
        ),
        (
            MUST,
            RunOutcome.TASK_SUCCESS,
            RunOutcome.TASK_SUCCESS,
            {"gate_rejections": 1},
            "fail",
        ),
        (KNOWN, RunOutcome.DEATH, RunOutcome.TASK_SUCCESS, {}, "improved"),
        (KNOWN, RunOutcome.DEATH, RunOutcome.TRUNCATED, {}, "changed"),
        (KNOWN, RunOutcome.DEATH, RunOutcome.DEATH, {}, "pass"),
        (KNOWN, RunOutcome.DEATH, RunOutcome.DEATH, {"invalid_actions": 2}, "fail"),
    ],
)
def test_check_status_compares_the_run_with_the_entry_expectation(
    tmp_path: Path,
    expectation: CatalogExpectation,
    expected: RunOutcome,
    observed: RunOutcome,
    changes: dict[str, object],
    status: str,
) -> None:
    entry = staircase_entry("probe", 7, expectation, expected)
    catalog = SeedCatalog("policy", (entry,))
    payload = catalog_suite_payload(catalog, "policy", "knowledge")
    suite = load_suite(write_json(tmp_path / "suite.json", payload))
    result = seed_result("probe", 7, observed, **changes)

    checks = check_catalog(catalog, suite, [result])

    assert [check.status for check in checks] == [CatalogCheckStatus(status)]


def test_check_fails_an_entry_without_a_result(tmp_path: Path) -> None:
    entry = staircase_entry("probe", 7, MUST, RunOutcome.TASK_SUCCESS)
    catalog = SeedCatalog("policy", (entry,))
    payload = catalog_suite_payload(catalog, "policy", "knowledge")
    suite = load_suite(write_json(tmp_path / "suite.json", payload))

    checks = check_catalog(catalog, suite, [])

    assert [check.status for check in checks] == [CatalogCheckStatus.FAIL]


def test_used_seeds_join_suites_catalog_and_ledger(tmp_path: Path) -> None:
    (tmp_path / "staircase-v1.json").write_bytes(SUITE_PATH.read_bytes())
    entry = staircase_entry("probe", 777_777, MUST, RunOutcome.TASK_SUCCESS)
    catalog = SeedCatalog("policy", (entry,))
    write_json(tmp_path / "representative-seeds.json", catalog.to_json())
    ledger_entry = {
        "source": "probe",
        "seeds": [42],
        "ranges": [[5000, 5002]],
        "note": "A test fixture.",
    }
    ledger = {"schema_version": 1, "entries": [ledger_entry]}
    write_json(tmp_path / "seed-ledger.json", ledger)

    seeds = used_seeds(tmp_path)

    assert seeds == frozenset({*range(1, 11), 777_777, 42, 5000, 5001, 5002})


def test_used_seeds_require_the_ledger(tmp_path: Path) -> None:
    entry = staircase_entry("probe", 7, MUST, RunOutcome.TASK_SUCCESS)
    catalog = SeedCatalog("policy", (entry,))
    write_json(tmp_path / "representative-seeds.json", catalog.to_json())

    with pytest.raises(CatalogError):
        used_seeds(tmp_path)
