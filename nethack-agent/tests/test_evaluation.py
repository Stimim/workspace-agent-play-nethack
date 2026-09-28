from __future__ import annotations

import json
import sqlite3
import stat
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent import evaluation, run_manager
from nethack_agent.contracts import ContractError
from nethack_agent.decision import (
    ActionSelection,
    ActionSelectionSource,
    DecisionMetrics,
    RunOutcome,
    RunState,
    Skill,
    SkillSelectionSource,
)
from nethack_agent.environment import LegalAction
from nethack_agent.evaluation import (
    SCHEMA_1_POLICY_VERSION,
    DecisionStats,
    EpisodeMetrics,
    EvaluationError,
    EvaluationOptions,
    EvaluationReport,
    EvaluationSuite,
    HungerState,
    MetricComparison,
    MetricName,
    MetricStatistic,
    ReportStatus,
    ReportWriter,
    RunConfiguration,
    SeedResult,
    SuiteValidationError,
    evaluate_acceptance,
    finalize_aborted_report,
    load_suite,
    nearest_rank_percentile,
    render_report_markdown,
    run_evaluation,
    summarize_run,
)
from nethack_agent.events import EventKind, RunEvent, RunStartedPayload, StepPayload
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.observation import (
    MapView,
    PlayerStats,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager
from nethack_agent.storage import RunRecord, RunStore
from nethack_agent.tasks import STAIRCASE_TASK, ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    EnterDungeonLeg,
    ExploreDungeonLeg,
    LevelKey,
    Objective,
)

SUITE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "staircase-v1.json"
STAIRCASE_V2_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "staircase-v2.json"
)
TRAVERSAL_V1_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "traversal-v1.json"
)
STAIRCASE_V3_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "staircase-v3.json"
)
TRAVERSAL_V2_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "traversal-v2.json"
)
REPORT_DIRECTORY = Path(__file__).resolve().parents[1] / "evaluation" / "reports"


@pytest.fixture
def bound_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as a checkout of the policy schema-1 suites are bound to.

    The harness mechanics under test do not depend on the policy; only the
    recorded policy id and the refusal check read it.
    """
    monkeypatch.setattr(run_manager, "POLICY_VERSION", SCHEMA_1_POLICY_VERSION)
    monkeypatch.setattr(evaluation, "POLICY_VERSION", SCHEMA_1_POLICY_VERSION)


def suite_payload() -> dict[str, object]:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def suite_2_payload() -> dict[str, object]:
    return json.loads(STAIRCASE_V2_PATH.read_text(encoding="utf-8"))


def write_suite(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def configuration(**changes: object) -> RunConfiguration:
    base = RunConfiguration(
        model="gemma4-nethack:latest",
        policy_version="policy",
        knowledge_version="knowledge",
        nle_version="1.3.0",
        environment="NetHackStaircase-v0",
        character="val-dwa-law",
        max_episode_steps=1000,
        ollama_num_ctx=8192,
    )
    return replace(base, **changes)


def result(
    seed: int,
    outcome: RunOutcome = RunOutcome.TRUNCATED,
    **changes: object,
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
            [DecisionMetrics(100, 10, float(seed), False)]
        ),
        selection_sources={
            "deterministic_skill": 1,
            "deterministic_prompt": 2,
            "model_fallback": 7,
        },
        gate_rejections=0,
        decision_failures=0,
        invalid_actions=0,
        error=None,
        ttyrec_path="runs/x/nle.ttyrec.bz2",
        ttyrec_exists=True,
        event_count=12,
        integrity_problems=(),
        configuration=configuration(),
        ollama_version="0.34.4",
    )
    return replace(base, **changes)


def passing_results() -> list[SeedResult]:
    return [
        result(seed, RunOutcome.TASK_SUCCESS if seed <= 6 else RunOutcome.DEATH)
        for seed in range(1, 11)
    ]


def test_committed_suite_is_valid_and_fixed() -> None:
    suite = load_suite(SUITE_PATH)

    assert suite.suite_id == "staircase-v1"
    assert suite.seeds == tuple(range(1, 11))
    assert suite.max_episode_steps == 1000
    assert suite.acceptance.min_task_successes == 6
    assert suite.acceptance.required_success_seeds == (6,)
    assert suite.acceptance.max_invalid_actions == 0
    assert suite.acceptance.max_gate_rejections == 0
    assert suite.acceptance.require_complete_records


def test_committed_schema_2_suite_pins_policy_knowledge_and_case_task() -> None:
    suite = load_suite(STAIRCASE_V2_PATH)

    assert suite.schema_version == 2
    assert suite.policy_version == "hierarchical-traversal-v1"
    assert suite.knowledge_bundle_id == "staircase-reviewed-v3"
    assert [case.case_id for case in suite.cases] == ["staircase"]
    assert suite.cases[0].task.environment is NleTask.STAIRCASE
    assert suite.cases[0].acceptance.min_successes == 6
    assert suite.cases[0].acceptance.required_success_seeds == (6,)


def test_committed_traversal_suite_fixes_cases_seeds_and_thresholds() -> None:
    suite = load_suite(TRAVERSAL_V1_PATH)

    assert [case.case_id for case in suite.cases] == [
        "descend-main-d3",
        "round-trip-d3-d1",
        "enter-mines",
    ]
    assert [case.seeds for case in suite.cases] == [tuple(range(700, 705))] * 3
    assert [case.max_episode_steps for case in suite.cases] == [1000, 1000, 1000]
    assert [case.acceptance.min_successes for case in suite.cases] == [3, 3, 2]
    assert all(case.task.environment is NleTask.SCORE for case in suite.cases)
    assert [
        [leg.kind.value for leg in case.task.objective.legs] for case in suite.cases
    ] == [["reach_level"], ["reach_level", "reach_level"], ["enter_dungeon"]]


@pytest.mark.parametrize("suite_path", [STAIRCASE_V2_PATH, TRAVERSAL_V1_PATH])
def test_committed_traversal_suites_refuse_under_the_current_policy_before_any_episode(
    tmp_path: Path, suite_path: Path
) -> None:
    # Their policy pin is immutable evidence; later policies use new suite ids.
    assert load_suite(suite_path).policy_version == "hierarchical-traversal-v1"
    assert run_manager.POLICY_VERSION != "hierarchical-traversal-v1"
    options = EvaluationOptions(
        suite=load_suite(suite_path),
        data_directory=tmp_path / "data",
        report_directory=tmp_path / "reports",
        development_scripted_model=True,
    )

    with pytest.raises(SuiteValidationError, match="bound to policy"):
        run_evaluation(options, progress=None)

    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize(
    ("regression", "original"),
    [
        (STAIRCASE_V3_PATH, STAIRCASE_V2_PATH),
        (TRAVERSAL_V2_PATH, TRAVERSAL_V1_PATH),
    ],
)
def test_regression_suites_reuse_their_predecessors_cases_under_the_current_policy(
    regression: Path, original: Path
) -> None:
    suite = load_suite(regression)
    previous = load_suite(original)

    assert suite.policy_version == run_manager.POLICY_VERSION
    assert suite.knowledge_bundle_id == previous.knowledge_bundle_id
    assert suite.suite_id != previous.suite_id
    assert [case.to_json() for case in suite.cases] == [
        case.to_json() for case in previous.cases
    ]
    assert suite.global_acceptance == previous.global_acceptance


@pytest.mark.parametrize("malformation", ["extra", "duplicate_case", "duplicate_seed"])
def test_schema_2_suite_contract_is_strict(tmp_path: Path, malformation: str) -> None:
    payload = suite_2_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    assert isinstance(case, dict)
    if malformation == "extra":
        case["unexpected"] = True
    elif malformation == "duplicate_case":
        cases.append(json.loads(json.dumps(case)))
    else:
        case["seeds"] = [1, 1]

    with pytest.raises(SuiteValidationError):
        load_suite(write_suite(tmp_path, payload))


@pytest.mark.parametrize(
    ("pin", "message"),
    [
        ("policy_version", "bound to policy"),
        ("knowledge_bundle_id", "bound to knowledge bundle"),
    ],
)
def test_schema_2_pin_mismatch_is_refused_before_writing(
    tmp_path: Path, pin: str, message: str
) -> None:
    payload = suite_2_payload()
    if pin != "policy_version":
        payload["policy_version"] = run_manager.POLICY_VERSION
    payload[pin] = "other-reviewed-v1"
    suite = load_suite(write_suite(tmp_path, payload))
    data_directory = tmp_path / "data"
    report_directory = tmp_path / "reports"

    with pytest.raises(SuiteValidationError, match=message):
        run_evaluation(
            EvaluationOptions(
                suite=suite,
                data_directory=data_directory,
                report_directory=report_directory,
                development_scripted_model=True,
            ),
            progress=None,
        )

    assert not data_directory.exists()
    assert not report_directory.exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"seeds": list(range(1, 10))}, "exactly 10"),
        ({"seeds": [1, 1, 2, 3, 4, 5, 6, 7, 8, 9]}, "unique"),
        ({"seeds": list(range(11, 21))}, "include seed 6"),
        ({"seeds": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}, "at least 1"),
        ({"environment": "NetHackScore-v0"}, "environment"),
        ({"character": "mon-hum-neu-mal"}, "character"),
        ({"max_episode_steps": 0}, "at least 1"),
        ({"schema_version": 2}, "schema_version"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_suite_validation_rejects_invalid_suites(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    payload = suite_payload()
    payload.update(change)

    with pytest.raises(SuiteValidationError, match=message):
        load_suite(write_suite(tmp_path, payload))


@pytest.mark.parametrize(
    ("acceptance_change", "message"),
    [
        ({"required_success_seeds": [11]}, "required_success_seeds"),
        ({"min_task_successes": 11}, "at most 10"),
        ({"max_gate_rejections": -1}, "at least 0"),
    ],
)
def test_suite_validation_rejects_invalid_acceptance(
    tmp_path: Path, acceptance_change: dict[str, object], message: str
) -> None:
    payload = suite_payload()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance.update(acceptance_change)

    with pytest.raises(SuiteValidationError, match=message):
        load_suite(write_suite(tmp_path, payload))


def test_nearest_rank_percentiles() -> None:
    values = [float(value) for value in range(20, 0, -1)]

    assert nearest_rank_percentile(values, 50) == 10.0
    assert nearest_rank_percentile(values, 95) == 19.0
    assert nearest_rank_percentile(values, 100) == 20.0
    assert nearest_rank_percentile([], 50) is None


def test_acceptance_passes_only_with_required_seed_and_threshold() -> None:
    suite = load_suite(SUITE_PATH)

    accepted = evaluate_acceptance(
        suite, passing_results(), development_model=False, inputs_unchanged=True
    )
    assert accepted.passed
    assert accepted.milestone_accepted

    without_seed_6 = [
        result(seed, RunOutcome.DEATH if seed == 6 else RunOutcome.TASK_SUCCESS)
        for seed in range(1, 11)
    ]
    rejected = evaluate_acceptance(
        suite, without_seed_6, development_model=False, inputs_unchanged=True
    )
    assert not rejected.passed
    assert not rejected.checks["required_success_seeds"]
    assert rejected.checks["min_task_successes"]

    five = [
        result(seed, RunOutcome.TASK_SUCCESS if seed in {2, 3, 4, 5, 6} else None)
        for seed in range(1, 11)
    ]
    assert not evaluate_acceptance(
        suite, five, development_model=False, inputs_unchanged=True
    ).checks["min_task_successes"]


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"gate_rejections": 1}, "gate_rejections"),
        ({"invalid_actions": 1}, "invalid_actions"),
        ({"integrity_problems": ("referenced ttyrec is missing",)}, "complete_records"),
        ({"configuration": configuration(model="other")}, "fixed_configuration"),
        (
            {"configuration": configuration(ollama_num_ctx=131072)},
            "fixed_configuration",
        ),
    ],
)
def test_any_integrity_or_policy_violation_fails_acceptance(
    change: dict[str, object], check: str
) -> None:
    suite = load_suite(SUITE_PATH)
    results = passing_results()
    results[9] = replace(results[9], **change)

    acceptance = evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    )

    assert not acceptance.passed
    assert not acceptance.checks[check]
    assert sum(not value for value in acceptance.checks.values()) == 1


def test_partial_interrupted_or_development_runs_are_not_milestone_evidence() -> None:
    suite = load_suite(SUITE_PATH)
    results = passing_results()

    partial = evaluate_acceptance(
        suite, results[:9], development_model=False, inputs_unchanged=True
    )
    assert not partial.checks["all_seeds_evaluated"]

    results[3] = replace(results[3], ended_by="interrupted")
    interrupted = evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    )
    assert not interrupted.checks["all_seeds_evaluated"]

    development = evaluate_acceptance(
        suite, passing_results(), development_model=True, inputs_unchanged=True
    )
    assert development.passed
    assert not development.milestone_accepted

    changed = evaluate_acceptance(
        suite, passing_results(), development_model=False, inputs_unchanged=False
    )
    assert not changed.milestone_accepted


def make_report(
    results: list[SeedResult], status: ReportStatus = ReportStatus.RUNNING
) -> EvaluationReport:
    return EvaluationReport(
        suite=load_suite(SUITE_PATH),
        model_mode="ollama",
        model="gemma4-nethack:latest",
        policy_version=SCHEMA_1_POLICY_VERSION,
        knowledge_version="staircase-reviewed-v2+sha256:" + "0" * 64,
        ollama_num_ctx=8192,
        requested_seeds=tuple(range(1, 11)),
        data_directory="data",
        started_at="2026-09-27T00:00:00+00:00",
        status=status,
        results=results,
    )


def written(tmp_path: Path, evaluation: EvaluationReport) -> ReportWriter:
    writer = ReportWriter(tmp_path, "suite-20260927T000000Z")
    writer.write(evaluation)
    return writer


def interrupted_report() -> EvaluationReport:
    evaluation = make_report(
        [
            result(1),
            result(
                2,
                RunOutcome.STOPPED,
                final_state=RunState.STOPPED,
                ended_by="interrupted",
                steps=4,
            ),
        ],
        ReportStatus.INTERRUPTED,
    )
    evaluation.finished_at = "2026-09-27T01:00:00+00:00"
    return evaluation


def test_report_aggregates_outcomes_sources_and_latency() -> None:
    evaluation = make_report(passing_results())

    aggregate = evaluation.aggregate_json()

    assert aggregate["task_successes"] == 6
    assert aggregate["outcomes"] == {"death": 4, "task_success": 6}
    assert aggregate["steps"] == 100
    assert aggregate["total_wall_seconds"] == 15.0
    assert aggregate["selection_sources"] == {
        "deterministic_skill": 10,
        "deterministic_prompt": 20,
        "model_fallback": 70,
    }
    decisions = aggregate["decisions"]
    assert isinstance(decisions, dict)
    assert decisions["model_decisions"] == 10
    assert decisions["latency_p50_ms"] == 5.0
    assert decisions["latency_p95_ms"] == 10.0
    assert decisions["prompt_tokens"] == 1000
    assert evaluation.to_json()["acceptance"]["milestone_accepted"]  # type: ignore[index]


def test_report_writer_never_replaces_existing_reports(tmp_path: Path) -> None:
    existing = tmp_path / "suite-20260927T000000Z.json"
    existing.write_text("previous", encoding="utf-8")

    writer = ReportWriter(tmp_path, "suite-20260927T000000Z")

    assert writer.paths.json.name == "suite-20260927T000000Z-2.json"
    assert writer.paths.markdown.name == "suite-20260927T000000Z-2.md"
    assert existing.read_text(encoding="utf-8") == "previous"


def test_report_writer_writes_world_readable_status_json(tmp_path: Path) -> None:
    writer = written(tmp_path, make_report([result(1), result(2, error="boom")]))

    stored = json.loads(writer.paths.json.read_text(encoding="utf-8"))
    assert stored["report_schema_version"] == 3
    assert stored["status"] == ReportStatus.RUNNING.value
    assert stored["status_reason"] is None
    assert render_report_markdown(stored) == writer.paths.markdown.read_text(
        encoding="utf-8"
    )
    for path in (writer.paths.json, writer.paths.markdown):
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize("malformation", ["missing", "extra"])
def test_schema_3_report_metrics_are_strict(malformation: str) -> None:
    payload = make_report([result(1)]).to_json()
    case_results = payload["case_results"]
    assert isinstance(case_results, list)
    case = case_results[0]
    assert isinstance(case, dict)
    results = case["results"]
    assert isinstance(results, list)
    seed_result = results[0]
    assert isinstance(seed_result, dict)
    metrics = seed_result["metrics"]
    assert isinstance(metrics, dict)
    if malformation == "missing":
        del metrics["game_turns"]
    else:
        metrics["unexpected"] = True

    with pytest.raises(ContractError, match="episode metrics fields are invalid"):
        render_report_markdown(payload)


def test_committed_schema_2_reports_still_render_byte_for_byte() -> None:
    reports = sorted(REPORT_DIRECTORY.glob("staircase-v1-*.json"))
    assert reports
    for path in reports:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["report_schema_version"] == 2
        assert render_report_markdown(payload) == path.with_suffix(".md").read_text(
            encoding="utf-8"
        )


def test_committed_schema_3_reports_render_and_retain_fixed_results() -> None:
    expected = {
        "staircase-v2-20260928T013844Z.json": (True, [10]),
        "traversal-v1-20260928T013929Z.json": (False, [3, 3, 1]),
    }
    for name, (accepted, successes) in expected.items():
        path = REPORT_DIRECTORY / name
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert payload["report_schema_version"] == 3
        assert payload["status"] == "complete"
        assert payload["acceptance"]["milestone_accepted"] is accepted
        assert [
            case["acceptance"]["successes"] for case in payload["case_results"]
        ] == successes
        assert payload["aggregate"]["invalid_actions"] == 0
        assert payload["aggregate"]["gate_rejections"] == 0
        assert payload["aggregate"]["integrity_failures"] == []
        assert render_report_markdown(payload) == path.with_suffix(".md").read_text(
            encoding="utf-8"
        )


def test_abort_finalizes_unfinished_report_and_keeps_evidence(tmp_path: Path) -> None:
    writer = written(tmp_path, interrupted_report())
    original = json.loads(writer.paths.json.read_text(encoding="utf-8"))
    writer.paths.json.chmod(0o600)
    writer.paths.markdown.chmod(0o600)

    paths = finalize_aborted_report(writer.paths.json, "  policy replaced  ")

    assert paths.json == writer.paths.json
    assert paths.markdown == writer.paths.markdown
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "suite-20260927T000000Z.json",
        "suite-20260927T000000Z.md",
    ]
    stored = json.loads(paths.json.read_text(encoding="utf-8"))
    assert stored["report_schema_version"] == 3
    assert stored["status"] == "aborted"
    assert stored["status_reason"] == "policy replaced"
    unchanged = {"status", "status_reason"}
    assert {k: v for k, v in stored.items() if k not in unchanged} == {
        k: v for k, v in original.items() if k not in unchanged
    }
    markdown = paths.markdown.read_text(encoding="utf-8")
    assert "- Status: aborted\n- Status reason: policy replaced\n" in markdown
    assert "- Finished: 2026-09-27T01:00:00+00:00" in markdown
    assert "## Acceptance: FAIL" in markdown
    assert "Milestone accepted: no." in markdown
    assert "## Case `staircase`" in markdown
    for path in (paths.json, paths.markdown):
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_aborted_report_is_never_accepted_even_if_recorded_acceptance_passed(
    tmp_path: Path,
) -> None:
    writer = written(tmp_path, make_report(passing_results()))
    assert "## Acceptance: PASS" in writer.paths.markdown.read_text(encoding="utf-8")

    paths = finalize_aborted_report(writer.paths.json, "policy replaced")

    stored = json.loads(paths.json.read_text(encoding="utf-8"))
    assert stored["acceptance"]["milestone_accepted"]
    markdown = paths.markdown.read_text(encoding="utf-8")
    assert "## Acceptance: FAIL" in markdown
    assert "Milestone accepted: no." in markdown
    assert "- report aborted (policy replaced); aborted reports are never" in markdown


@pytest.mark.parametrize(
    "status",
    [
        ReportStatus.COMPLETE,
        ReportStatus.PARTIAL,
        ReportStatus.FAILED,
        ReportStatus.ABORTED,
    ],
)
def test_abort_rejects_reports_with_a_final_status(
    tmp_path: Path, status: ReportStatus
) -> None:
    evaluation = interrupted_report()
    evaluation.status = status
    evaluation.status_reason = "earlier" if status is ReportStatus.ABORTED else None
    writer = written(tmp_path, evaluation)
    before = (writer.paths.json.read_bytes(), writer.paths.markdown.read_bytes())

    with pytest.raises(EvaluationError, match=f"is {status.value}"):
        finalize_aborted_report(writer.paths.json, "policy replaced")

    assert (writer.paths.json.read_bytes(), writer.paths.markdown.read_bytes()) == (
        before
    )


@pytest.mark.parametrize("reason", ["", "   ", "two\nlines", "x" * 501])
def test_abort_rejects_invalid_reasons(tmp_path: Path, reason: str) -> None:
    writer = written(tmp_path, interrupted_report())
    before = writer.paths.json.read_bytes()

    with pytest.raises(EvaluationError, match="abort reason"):
        finalize_aborted_report(writer.paths.json, reason)

    assert writer.paths.json.read_bytes() == before


def test_abort_rejects_malformed_reports_without_writing(tmp_path: Path) -> None:
    writer = written(tmp_path, interrupted_report())
    payload = json.loads(writer.paths.json.read_text(encoding="utf-8"))
    del payload["case_results"][0]["results"][0]["steps"]
    writer.paths.json.write_text(json.dumps(payload), encoding="utf-8")
    markdown = writer.paths.markdown.read_bytes()

    with pytest.raises(EvaluationError, match="invalid evaluation report"):
        finalize_aborted_report(writer.paths.json, "policy replaced")

    assert writer.paths.markdown.read_bytes() == markdown
    assert json.loads(writer.paths.json.read_text(encoding="utf-8")) == payload


def test_schema_1_suite_is_refused_under_another_policy_before_any_episode(
    tmp_path: Path,
) -> None:
    assert run_manager.POLICY_VERSION != SCHEMA_1_POLICY_VERSION
    options = EvaluationOptions(
        suite=load_suite(SUITE_PATH),
        data_directory=tmp_path / "data",
        report_directory=tmp_path / "reports",
        development_scripted_model=True,
    )

    with pytest.raises(SuiteValidationError, match="bound to policy"):
        run_evaluation(options, progress=None)

    # Nothing was created: no run store, no episode, and no report.
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.usefixtures("bound_policy")
def test_development_evaluator_runs_real_nle_and_audits_records(
    tmp_path: Path,
    to_milestone_1_shape: Callable[[Path], int],
    to_pathless_intent_shape: Callable[[Path], int],
) -> None:
    payload = suite_payload()
    payload["max_episode_steps"] = 2
    suite = load_suite(write_suite(tmp_path, payload))
    data_directory = tmp_path / "data"

    run = run_evaluation(
        EvaluationOptions(
            suite=suite,
            data_directory=data_directory,
            report_directory=tmp_path / "reports",
            development_scripted_model=True,
            poll_interval_seconds=0.01,
        ),
        progress=None,
    )

    report = run.report
    assert report.status is ReportStatus.COMPLETE
    assert [item.seed for item in report.results] == list(range(1, 11))
    for item in report.results:
        assert item.integrity_ok, item.integrity_problems
        assert item.steps <= 2
        assert item.outcome is not None
        assert item.ttyrec_exists
        assert item.invalid_actions == 0
        assert item.gate_rejections == 0
    acceptance = report.acceptance()
    assert acceptance.checks["all_seeds_evaluated"]
    assert acceptance.checks["fixed_configuration"]
    assert acceptance.checks["complete_records"]
    assert not acceptance.milestone_accepted
    stored = json.loads(run.paths.json.read_text(encoding="utf-8"))
    assert stored["status"] == "complete"
    assert stored["configuration"]["model_mode"] == "development_scripted"
    assert len(stored["case_results"][0]["results"]) == 10
    assert run.paths.markdown.is_file()

    first = report.results[0]
    assert first.run_id is not None
    store = RunStore(data_directory / "runs.sqlite3")
    record = store.get_run(first.run_id)
    events = store.events_after(first.run_id, limit=1000)

    gap = summarize_run(
        record,
        events[:1] + events[2:],
        suite=suite,
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=data_directory,
    )
    assert "event sequences are not contiguous from 0" in gap.integrity_problems

    assert any(
        isinstance(event.payload, StepPayload)
        and event.payload.selection.intent is not None
        and event.payload.selection.intent.path is not None
        for event in events
    )
    # Intents recorded before routes existed audit cleanly with no path.
    assert to_pathless_intent_shape(data_directory / "runs.sqlite3") > 0
    pathless_events = RunStore(data_directory / "runs.sqlite3").events_after(
        first.run_id, limit=1000
    )
    assert all(
        event.payload.selection.intent is None
        or event.payload.selection.intent.path is None
        for event in pathless_events
        if isinstance(event.payload, StepPayload)
    )
    pathless = summarize_run(
        record,
        pathless_events,
        suite=suite,
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=data_directory,
    )
    assert pathless.integrity_ok, pathless.integrity_problems

    # Milestone 1 records predate pet evidence and step intents; they must
    # still audit cleanly.
    assert to_milestone_1_shape(data_directory / "runs.sqlite3") > 0
    legacy_events = RunStore(data_directory / "runs.sqlite3").events_after(
        first.run_id, limit=1000
    )
    assert legacy_events[0].payload.observation.map.pet_rows is None
    assert all(
        event.payload.selection.intent is None
        for event in legacy_events
        if isinstance(event.payload, StepPayload)
    )
    legacy = summarize_run(
        record,
        legacy_events,
        suite=suite,
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=data_directory,
    )
    assert legacy.integrity_ok, legacy.integrity_problems
    assert legacy.steps == first.steps

    assert record.ttyrec_path is not None
    Path(record.ttyrec_path).unlink()
    missing = summarize_run(
        record,
        events,
        suite=suite,
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=data_directory,
    )
    assert not missing.ttyrec_exists
    assert not missing.integrity_ok


@pytest.mark.usefixtures("bound_policy")
def test_subset_runs_are_partial_and_follow_requested_order(tmp_path: Path) -> None:
    payload = suite_payload()
    payload["max_episode_steps"] = 1
    suite = load_suite(write_suite(tmp_path, payload))

    run = run_evaluation(
        EvaluationOptions(
            suite=suite,
            data_directory=tmp_path / "data",
            report_directory=tmp_path / "reports",
            seeds=(6, 2),
            development_scripted_model=True,
            poll_interval_seconds=0.01,
        ),
        progress=None,
    )

    assert run.report.status is ReportStatus.PARTIAL
    assert [item.seed for item in run.report.results] == [6, 2]
    assert not run.report.acceptance().checks["all_seeds_evaluated"]


def test_requested_seeds_must_belong_to_the_suite() -> None:
    with pytest.raises(ValueError, match="not in the suite"):
        EvaluationOptions(
            suite=load_suite(SUITE_PATH),
            data_directory=Path("data"),
            report_directory=Path("reports"),
            seeds=(11,),
        )


def test_audit_accepts_permitted_traversals_and_flags_unpermitted_ones(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    manager = RunManager(
        data_directory,
        OllamaConfig(model="scripted"),
        model_factory=lambda _client: ScriptedDevelopmentModel(),
    )
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_TASK_ACTIONS,
        Objective((EnterDungeonLeg(2),)),
    )
    try:
        run_id = manager.create_run(
            seed=4, max_episode_steps=600, auto_start=True, task=task
        ).id
        deadline = time.monotonic() + 120
        while manager.store.get_run(run_id).state is RunState.RUNNING:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        manager.close()
    store = RunStore(data_directory / "runs.sqlite3")
    base_suite = load_suite(SUITE_PATH)
    case = replace(
        base_suite.cases[0],
        task=task,
        max_episode_steps=600,
    )
    suite = replace(base_suite, cases=(case,))

    def audit(record: RunRecord) -> SeedResult:
        return summarize_run(
            record,
            store.events_after(run_id, limit=1000),
            suite=suite,
            seed=4,
            ended_by="terminal",
            wall_seconds=0.0,
            data_directory=data_directory,
            case=case,
        )

    record = store.get_run(run_id)
    assert record.outcome is RunOutcome.OBJECTIVE_COMPLETE
    result = audit(record)
    assert result.integrity_problems == ()
    assert result.invalid_actions == 0
    assert result.gate_rejections == 0
    assert result.metrics.objective_legs_completed == 1
    assert result.metrics.down_stair_traversals == 3
    assert result.metrics.up_stair_traversals == 1
    assert result.metrics.deepest_level == LevelKey(0, 3)
    assert result.metrics.final_hit_points > 0

    # The same stored level changes are invalid for a legacy run whose stored
    # task would have prohibited every level change.
    assert audit(replace(record, task=None)).invalid_actions > 0

    # Unknown branch stairs require the recorded evidence that two stairs of
    # that direction were known. Absence or false evidence never broadens the
    # audit permit, and a mismatched destination coordinate is also rejected.
    with sqlite3.connect(data_directory / "runs.sqlite3") as connection:
        rowid, payload = next(
            (rowid, payload)
            for rowid, text in connection.execute(
                "SELECT rowid, payload_json FROM events ORDER BY sequence"
            )
            if isinstance(payload := json.loads(text), dict)
            and isinstance(selection := payload.get("selection"), dict)
            and isinstance(intent := selection.get("intent"), dict)
            and isinstance(destination := intent.get("destination"), dict)
            and isinstance(stair := destination.get("stair"), dict)
            and stair.get("kind") == "unknown"
            and payload.get("action", {}).get("name") == "MiscDirection.DOWN"
            and destination.get("pair_known") is True
        )
        destination = payload["selection"]["intent"]["destination"]
        destination["pair_known"] = False
        connection.execute(
            "UPDATE events SET payload_json = ? WHERE rowid = ?",
            (json.dumps(payload), rowid),
        )
    assert audit(record).invalid_actions == 1

    destination["pair_known"] = True
    destination["x"] += 1
    with sqlite3.connect(data_directory / "runs.sqlite3") as connection:
        connection.execute(
            "UPDATE events SET payload_json = ? WHERE rowid = ?",
            (json.dumps(payload), rowid),
        )
    assert audit(record).invalid_actions == 1


_EAST = LegalAction(0, ord("l"), "CompassDirection.E")
_DISPLAYED = nethack.GLYPH_CMAP_OFF + 19


def synthetic_observation(
    step_index: int, level: LevelKey | None, displayed: int, hunger: int
) -> ProjectedObservation:
    """A 2x5 map showing `displayed` non-blank glyphs.

    `level` None is NLE's terminal observation, whose bottom line is zeroed.
    """
    width, height = 5, 2
    glyphs = [
        _DISPLAYED if index < displayed else nethack.GLYPH_CMAP_OFF
        for index in range(width * height)
    ]
    dungeon_number, dungeon_level = (
        (0, 0) if level is None else (level.dungeon_number, level.dungeon_level)
    )
    return ProjectedObservation(
        step_index=step_index,
        map=MapView(
            rows=(" " * width,) * height,
            glyph_rows=tuple(
                tuple(glyphs[row * width : (row + 1) * width]) for row in range(height)
            ),
            color_rows=(bytes(width),) * height,
            special_rows=(bytes(width),) * height,
            pet_rows=None,
        ),
        changed_cells=(),
        player=PlayerStats(
            x=0,
            y=0,
            strength_25=16,
            strength_125=16,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=10,
            score=0,
            hit_points=0 if level is None else 10,
            max_hit_points=0 if level is None else 10,
            depth=dungeon_level,
            gold=0,
            energy=0,
            max_energy=0,
            armor_class=6,
            hit_dice=0,
            experience_level=0 if level is None else 1,
            experience_points=0,
            turn=0 if level is None else step_index + 1,
            hunger=hunger,
            encumbrance=0,
            dungeon_number=dungeon_number,
            dungeon_level=dungeon_level,
            alignment=0,
            conditions=(),
        ),
        message="",
        prompt=PromptState(False, False, False),
        inventory=(),
    )


def synthetic_step(
    observation: ProjectedObservation, outcome: RunOutcome | None = None
) -> StepPayload:
    return StepPayload(
        selection=ActionSelection(
            ActionSelectionSource.DETERMINISTIC_SKILL,
            STAND_ON_DOWNSTAIRS,
            Skill.EXPLORE_LEVEL,
            SkillSelectionSource.ARBITER,
            None,
            _EAST.index,
            "Explore toward unexplored space.",
            None,
        ),
        skill_decision=None,
        skill_metrics=None,
        action_decision=None,
        action_metrics=None,
        action=_EAST,
        reward=0.0,
        terminated=outcome is not None,
        truncated=False,
        end_status=0 if outcome is None else 1,
        is_ascended=False,
        outcome=outcome,
        observation=observation,
    )


def test_episode_metrics_sum_each_levels_most_explored_cells_and_worst_hunger(
    tmp_path: Path,
) -> None:
    first, second = LevelKey(0, 1), LevelKey(0, 2)
    observations = [
        synthetic_observation(0, first, 3, hunger=1),
        synthetic_observation(1, first, 5, hunger=2),
        synthetic_observation(2, second, 4, hunger=0),
        # Fewer displayed cells on a revisit never lower a level's count.
        synthetic_observation(3, first, 2, hunger=1),
        # The zeroed terminal observation is no live level or hunger sample.
        synthetic_observation(4, None, 10, hunger=6),
    ]
    events = [
        RunEvent(
            0,
            "2026-09-28T00:00:00+00:00",
            EventKind.RUN_STARTED,
            RunStartedPayload(observations[0], (_EAST,), STAND_ON_DOWNSTAIRS, None),
        ),
        *(
            RunEvent(
                index,
                "2026-09-28T00:00:00+00:00",
                EventKind.STEP,
                synthetic_step(
                    observation,
                    RunOutcome.DEATH if index == len(observations) - 1 else None,
                ),
            )
            for index, observation in enumerate(observations[1:], start=1)
        ),
    ]
    record = RunRecord(
        id="run-1",
        created_at="2026-09-28T00:00:00+00:00",
        updated_at="2026-09-28T00:00:00+00:00",
        state=RunState.TERMINAL,
        outcome=RunOutcome.DEATH,
        environment=STAIRCASE_TASK.environment.value,
        character="val-dwa-law",
        suite_seed=1,
        core_seed=1,
        display_seed=1,
        level_seed=1,
        max_episode_steps=1000,
        model="scripted",
        policy_version="policy",
        knowledge_version="knowledge",
        nle_version="1.3.0",
        ollama_num_ctx=8192,
        ollama_version=None,
        ttyrec_path=None,
        error=None,
        task=STAIRCASE_TASK,
    )

    metrics = summarize_run(
        record,
        events,
        suite=load_suite(SUITE_PATH),
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=tmp_path,
    ).metrics

    assert metrics.explored_cells == 5 + 4
    assert metrics.worst_hunger_state is HungerState.HUNGRY
    stored = metrics.to_json()
    assert stored["explored_cells"] == 9
    assert stored["worst_hunger_state"] == "hungry"
    assert EpisodeMetrics.from_json(stored) == metrics


def test_empty_metrics_record_no_exploration_and_no_hunger_sample() -> None:
    stored = EpisodeMetrics.empty().to_json()

    assert stored["explored_cells"] == 0
    assert stored["worst_hunger_state"] is None
    assert EpisodeMetrics.from_json(stored) == EpisodeMetrics.empty()


def committed_schema_3_metrics() -> dict[str, object]:
    path = REPORT_DIRECTORY / "traversal-v1-20260928T013929Z.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload["case_results"][0]["results"][0]["metrics"]
    assert isinstance(metrics, dict)
    return metrics


def test_legacy_metrics_without_exploration_round_trip_unchanged() -> None:
    stored = committed_schema_3_metrics()
    assert "explored_cells" not in stored

    metrics = EpisodeMetrics.from_json(stored)

    assert metrics.explored_cells is None
    assert metrics.worst_hunger_state is None
    assert metrics.to_json() == stored


@pytest.mark.parametrize("present", ["explored_cells", "worst_hunger_state"])
def test_metrics_record_exploration_and_worst_hunger_together(present: str) -> None:
    stored = committed_schema_3_metrics()
    stored[present] = 3 if present == "explored_cells" else "hungry"

    with pytest.raises(ContractError, match="recorded together"):
        EpisodeMetrics.from_json(stored)


def metric_threshold(
    metric: str, statistic: str, comparison: str, value: object
) -> dict[str, object]:
    return {
        "metric": metric,
        "statistic": statistic,
        "bound": {"comparison": comparison, "value": value},
    }


def threshold_suite(
    tmp_path: Path, thresholds: list[dict[str, object]]
) -> EvaluationSuite:
    payload = suite_2_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    cases[0]["acceptance"]["metric_thresholds"] = thresholds
    return load_suite(write_suite(tmp_path, payload))


def test_suite_metric_thresholds_parse_and_serialize_in_order(tmp_path: Path) -> None:
    thresholds = [
        metric_threshold("explored_cells", "median", "at_least", 500),
        metric_threshold("task_return", "mean", "at_most", 2.5),
    ]

    suite = threshold_suite(tmp_path, thresholds)

    acceptance = suite.cases[0].acceptance
    assert [threshold.key for threshold in acceptance.metric_thresholds] == [
        (
            MetricName.EXPLORED_CELLS,
            MetricStatistic.MEDIAN,
            MetricComparison.AT_LEAST,
        ),
        (MetricName.TASK_RETURN, MetricStatistic.MEAN, MetricComparison.AT_MOST),
    ]
    assert acceptance.to_json()["metric_thresholds"] == thresholds
    # Cases without thresholds keep their pre-threshold JSON shape.
    assert (
        "metric_thresholds"
        not in load_suite(STAIRCASE_V2_PATH).to_json()["cases"][0]["acceptance"]
    )  # type: ignore[index]


@pytest.mark.parametrize(
    "thresholds",
    [
        [],
        [metric_threshold("explored_cells", "mode", "at_least", 500)],
        [metric_threshold("explored_cells", "median", "exactly", 500)],
        [metric_threshold("score", "median", "at_least", 500)],
        [metric_threshold("explored_cells", "median", "at_least", True)],
        [metric_threshold("explored_cells", "median", "at_least", "500")],
        [metric_threshold("explored_cells", "median", "at_least", float("inf"))],
        [
            metric_threshold("explored_cells", "median", "at_least", 500),
            metric_threshold("explored_cells", "median", "at_least", 600),
        ],
        [{**metric_threshold("death", "sum", "at_most", 0), "extra": 1}],
    ],
)
def test_suite_metric_thresholds_are_strict(
    tmp_path: Path, thresholds: list[dict[str, object]]
) -> None:
    with pytest.raises(SuiteValidationError):
        threshold_suite(tmp_path, thresholds)


def threshold_results(
    values: list[int | None], **metric_changes: object
) -> list[SeedResult]:
    return [
        result(
            seed,
            RunOutcome.TASK_SUCCESS,
            case_id="staircase",
            metrics=replace(
                EpisodeMetrics.empty(),
                steps=10,
                explored_cells=value,
                **metric_changes,
            ),
        )
        for seed, value in enumerate(values, start=1)
    ]


@pytest.mark.parametrize(
    ("threshold", "values", "reason"),
    [
        # Odd count: the middle value.
        (
            metric_threshold("explored_cells", "median", "at_least", 500),
            [100, 900, 500],
            None,
        ),
        # Even count: the mean of the two middle values.
        (
            metric_threshold("explored_cells", "median", "at_least", 450),
            [900, 100, 500, 400],
            None,
        ),
        (
            metric_threshold("explored_cells", "median", "at_least", 451),
            [900, 100, 500, 400],
            "case staircase: explored_cells median 450 is below at_least 451",
        ),
        (
            metric_threshold("explored_cells", "mean", "at_least", 3),
            [1, 2, 4],
            "case staircase: explored_cells mean 2.333 is below at_least 3",
        ),
        (
            metric_threshold("explored_cells", "maximum", "at_most", 4),
            [1, 2, 4],
            None,
        ),
        (
            metric_threshold("explored_cells", "sum", "at_most", 6),
            [1, 2, 4],
            "case staircase: explored_cells sum 7 is above at_most 6",
        ),
        (
            metric_threshold("explored_cells", "minimum", "at_least", 1),
            [3, None, 4],
            "case staircase: explored_cells minimum is unavailable; "
            "at_least 1 required",
        ),
        (
            metric_threshold("explored_cells", "minimum", "at_least", 0),
            [],
            "case staircase: explored_cells minimum is unavailable; "
            "at_least 0 required",
        ),
    ],
)
def test_acceptance_gates_on_case_metric_statistics(
    tmp_path: Path,
    threshold: dict[str, object],
    values: list[int | None],
    reason: str | None,
) -> None:
    suite = threshold_suite(tmp_path, [threshold])

    acceptance = evaluate_acceptance(
        suite,
        threshold_results(values),
        development_model=False,
        inputs_unchanged=True,
    )

    check = (
        f"staircase:explored_cells:{threshold['statistic']}:"
        f"{threshold['bound']['comparison']}"  # type: ignore[index]
    )
    assert acceptance.checks[check] is (reason is None)
    threshold_reasons = [
        item for item in acceptance.reasons if item.startswith("case staircase:")
    ]
    assert threshold_reasons == ([] if reason is None else [reason])


def test_death_worst_hunger_and_starvation_thresholds_use_episode_values(
    tmp_path: Path,
) -> None:
    suite = threshold_suite(
        tmp_path,
        [
            metric_threshold("death", "sum", "at_most", 1),
            metric_threshold("starvation_death", "sum", "at_most", 0),
            metric_threshold("worst_hunger_state", "maximum", "at_most", 2),
        ],
    )
    starved = replace(
        EpisodeMetrics.empty(),
        steps=10,
        death_cause="died of starvation",
        worst_hunger_state=HungerState.WEAK,
    )
    killed = replace(starved, death_cause="killed by a jackal")
    results = [
        result(1, RunOutcome.DEATH, metrics=starved),
        result(2, RunOutcome.DEATH, metrics=killed),
        # Starvation text without a death outcome is not a starvation death.
        result(3, RunOutcome.TRUNCATED, metrics=starved),
    ]

    checks = evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    ).checks

    assert checks["staircase:death:sum:at_most"] is False
    assert checks["staircase:starvation_death:sum:at_most"] is False
    assert checks["staircase:worst_hunger_state:maximum:at_most"] is False
    assert "case staircase: death sum 2 is above at_most 1" in (
        evaluate_acceptance(
            suite, results, development_model=False, inputs_unchanged=True
        ).reasons
    )


def threshold_report(
    suite: EvaluationSuite, results: list[SeedResult]
) -> EvaluationReport:
    return EvaluationReport(
        suite=suite,
        model_mode="ollama",
        model="gemma4-nethack:latest",
        policy_version=suite.policy_version,
        knowledge_version=f"{suite.knowledge_bundle_id}+sha256:" + "0" * 64,
        ollama_num_ctx=8192,
        requested_seeds=suite.seeds,
        data_directory="data",
        started_at="2026-09-28T00:00:00+00:00",
        results=results,
    )


def test_case_report_records_threshold_results_and_renders_them(
    tmp_path: Path,
) -> None:
    # No objective success is required, so only the thresholds gate the case.
    suite = load_suite(
        write_suite(
            tmp_path,
            zero_success_payload(
                [
                    metric_threshold("explored_cells", "median", "at_least", 500),
                    metric_threshold("task_return", "mean", "at_most", 0),
                ]
            ),
        )
    )
    results = threshold_results([400, 612, 700], worst_hunger_state=HungerState.HUNGRY)

    payload = threshold_report(suite, results).to_json()

    case = payload["case_results"][0]  # type: ignore[index]
    assert case["acceptance"]["metrics"] == [
        {
            **metric_threshold("explored_cells", "median", "at_least", 500),
            "value": 612,
            "passed": True,
        },
        {
            **metric_threshold("task_return", "mean", "at_most", 0),
            "value": 0,
            "passed": True,
        },
    ]
    assert case["acceptance"]["passed"]
    markdown = render_report_markdown(payload)
    assert (
        "| Metric | Statistic | Bound | Value | Result |\n"
        "| --- | --- | --- | ---: | --- |\n"
        "| explored_cells | median | at_least 500 | 612 | pass |\n"
        "| task_return | mean | at_most 0 | 0 | pass |\n"
    ) in markdown
    assert "| Hunger | Explored | Worst hunger | HP/XL |" in markdown
    assert "| - | 612 | hungry | 0/0 |" in markdown

    failing = threshold_report(suite, threshold_results([400, 450, 700])).to_json()
    failing_case = failing["case_results"][0]  # type: ignore[index]
    assert failing_case["acceptance"]["successes"] == 3
    assert failing_case["acceptance"]["passed"] is False
    assert "| explored_cells | median | at_least 500 | 450 | fail |" in (
        render_report_markdown(failing)
    )


def test_threshold_value_is_null_and_rendered_as_dash_when_unavailable(
    tmp_path: Path,
) -> None:
    suite = threshold_suite(
        tmp_path, [metric_threshold("explored_cells", "median", "at_least", 500)]
    )

    payload = threshold_report(suite, []).to_json()

    metrics = payload["case_results"][0]["acceptance"]["metrics"]  # type: ignore[index]
    assert metrics[0]["value"] is None
    assert metrics[0]["passed"] is False
    markdown = render_report_markdown(payload)
    assert "| explored_cells | median | at_least 500 | - | fail |" in markdown
    # A report without any result has no evidence of the new metrics.
    assert "| Explored |" not in markdown


@pytest.mark.parametrize("malformation", ["missing", "unrequested", "reordered"])
def test_report_threshold_results_must_match_suite_thresholds(
    tmp_path: Path, malformation: str
) -> None:
    suite = threshold_suite(
        tmp_path,
        [
            metric_threshold("explored_cells", "median", "at_least", 500),
            metric_threshold("death", "sum", "at_most", 0),
        ],
    )
    payload = threshold_report(suite, threshold_results([600])).to_json()
    acceptance = payload["case_results"][0]["acceptance"]  # type: ignore[index]
    if malformation == "missing":
        del acceptance["metrics"]
    elif malformation == "unrequested":
        plain = threshold_report(
            load_suite(STAIRCASE_V2_PATH), threshold_results([600])
        ).to_json()
        plain["case_results"][0]["acceptance"]["metrics"] = acceptance["metrics"]  # type: ignore[index]
        payload = plain
    else:
        acceptance["metrics"].reverse()

    with pytest.raises(ContractError, match="acceptance metrics"):
        render_report_markdown(payload)


def test_report_suite_thresholds_must_match_case_criteria(tmp_path: Path) -> None:
    suite = threshold_suite(
        tmp_path, [metric_threshold("explored_cells", "median", "at_least", 500)]
    )
    payload = threshold_report(suite, threshold_results([600])).to_json()
    criteria = payload["case_results"][0]["acceptance"]["criteria"]  # type: ignore[index]
    criteria["metric_thresholds"][0]["bound"]["value"] = 400

    with pytest.raises(ContractError, match="acceptance differs from the suite"):
        render_report_markdown(payload)


def test_report_mixing_recorded_and_legacy_exploration_metrics_is_rejected() -> None:
    payload = make_report([result(1), result(2)]).to_json()
    results = payload["case_results"][0]["results"]  # type: ignore[index]
    del results[1]["metrics"]["explored_cells"]
    del results[1]["metrics"]["worst_hunger_state"]

    with pytest.raises(ContractError, match="all record explored_cells"):
        render_report_markdown(payload)

    del results[0]["metrics"]["explored_cells"]
    del results[0]["metrics"]["worst_hunger_state"]
    assert "| Explored |" not in render_report_markdown(payload)


def zero_success_payload(thresholds: list[dict[str, object]]) -> dict[str, object]:
    payload = suite_2_payload()
    acceptance = payload["cases"][0]["acceptance"]  # type: ignore[index]
    acceptance["min_successes"] = 0
    acceptance["required_success_seeds"] = []
    if thresholds:
        acceptance["metric_thresholds"] = thresholds
    return payload


def test_metric_gated_case_may_require_no_objective_success(tmp_path: Path) -> None:
    suite = load_suite(
        write_suite(
            tmp_path,
            zero_success_payload(
                [metric_threshold("explored_cells", "median", "at_least", 500)]
            ),
        )
    )
    assert suite.cases[0].acceptance.min_successes == 0

    payload = threshold_report(suite, threshold_results([600])).to_json()
    case = payload["case_results"][0]  # type: ignore[index]
    assert case["acceptance"]["passed"] is True
    assert "- Successes: 1/10 (required 0, including [])." in render_report_markdown(
        payload
    )


def test_zero_required_successes_need_a_metric_threshold(tmp_path: Path) -> None:
    with pytest.raises(SuiteValidationError, match="min_successes must be at least 1"):
        load_suite(write_suite(tmp_path, zero_success_payload([])))

    payload = threshold_report(
        load_suite(STAIRCASE_V2_PATH), threshold_results([600])
    ).to_json()
    for acceptance in (
        payload["suite"]["cases"][0]["acceptance"],  # type: ignore[index]
        payload["case_results"][0]["acceptance"]["criteria"],  # type: ignore[index]
    ):
        acceptance["min_successes"] = 0
    with pytest.raises(ContractError, match="min_successes must be at least 1"):
        render_report_markdown(payload)


def test_explore_objectives_count_only_exhaustion_markers_the_replay_confirms(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    manager = RunManager(
        data_directory,
        OllamaConfig(model="scripted"),
        model_factory=lambda _client: ScriptedDevelopmentModel(),
    )
    task = TaskSpec(
        NleTask.SCOUT,
        ActionProfile.NLE_TASK_ACTIONS,
        Objective((ExploreDungeonLeg(1),)),
    )
    try:
        # Seed 53 exhausts its first level within the Scout's hunger horizon.
        run_id = manager.create_run(
            seed=53, max_episode_steps=400, auto_start=True, task=task
        ).id
        deadline = time.monotonic() + 120
        while manager.store.get_run(run_id).state is RunState.RUNNING:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        manager.close()
    store = RunStore(data_directory / "runs.sqlite3")
    base_suite = load_suite(SUITE_PATH)
    case = replace(base_suite.cases[0], task=task, max_episode_steps=400)
    suite = replace(base_suite, cases=(case,))
    record = store.get_run(run_id)

    def audit() -> SeedResult:
        return summarize_run(
            record,
            store.events_after(run_id, limit=1000),
            suite=suite,
            seed=53,
            ended_by="terminal",
            wall_seconds=0.0,
            data_directory=data_directory,
            case=case,
        )

    def rewrite(step_index: int, marker: dict[str, int] | None) -> None:
        with sqlite3.connect(data_directory / "runs.sqlite3") as connection:
            rowid, payload = next(
                (rowid, payload)
                for rowid, text in connection.execute(
                    "SELECT rowid, payload_json FROM events ORDER BY sequence"
                )
                if isinstance(payload := json.loads(text), dict)
                and payload.get("observation", {}).get("step_index") == step_index
                and "selection" in payload
            )
            payload["selection"]["exhausted_level"] = marker
            connection.execute(
                "UPDATE events SET payload_json = ? WHERE rowid = ?",
                (json.dumps(payload), rowid),
            )

    assert record.outcome is RunOutcome.OBJECTIVE_COMPLETE
    honest = audit()
    assert honest.integrity_problems == ()
    assert honest.metrics.objective_legs_completed == 1
    final_step = honest.steps

    # Without its marker the final step no longer supports the outcome.
    rewrite(final_step, None)
    unsupported = audit()
    assert unsupported.metrics.objective_legs_completed == 0
    assert unsupported.integrity_problems == (
        "objective_complete outcome is not supported by the stored observations",
    )

    # A marker forged where exploration still had work is rejected, and it
    # cannot complete the objective either.
    rewrite(final_step, None)
    rewrite(5, {"dungeon_number": 0, "dungeon_level": 1})
    forged = audit()
    assert forged.metrics.objective_legs_completed == 0
    assert (
        "step 5 exhausted_level marker is not supported: deterministic exploration "
        "still had an action"
    ) in forged.integrity_problems
