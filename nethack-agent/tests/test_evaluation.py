from __future__ import annotations

import json
import stat
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from nethack_agent import evaluation, run_manager
from nethack_agent.decision import DecisionMetrics, RunOutcome, RunState
from nethack_agent.evaluation import (
    SCHEMA_1_POLICY_VERSION,
    DecisionStats,
    EvaluationError,
    EvaluationOptions,
    EvaluationReport,
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
from nethack_agent.events import StepPayload
from nethack_agent.storage import RunStore

SUITE_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "staircase-v1.json"


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
        policy_version="policy",
        knowledge_version="knowledge",
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
    assert stored["report_schema_version"] == 2
    assert stored["status"] == ReportStatus.RUNNING.value
    assert stored["status_reason"] is None
    assert render_report_markdown(stored) == writer.paths.markdown.read_text(
        encoding="utf-8"
    )
    for path in (writer.paths.json, writer.paths.markdown):
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize("schema_version", [1, 2])
def test_abort_finalizes_unfinished_report_and_keeps_evidence(
    tmp_path: Path, schema_version: int
) -> None:
    writer = written(tmp_path, interrupted_report())
    original = json.loads(writer.paths.json.read_text(encoding="utf-8"))
    if schema_version == 1:
        del original["status_reason"]
        original["report_schema_version"] = 1
        writer.paths.json.write_text(json.dumps(original), encoding="utf-8")
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
    assert stored["report_schema_version"] == 2
    assert stored["status"] == "aborted"
    assert stored["status_reason"] == "policy replaced"
    unchanged = {"status", "status_reason", "report_schema_version"}
    assert {k: v for k, v in stored.items() if k not in unchanged} == {
        k: v for k, v in original.items() if k not in unchanged
    }
    markdown = paths.markdown.read_text(encoding="utf-8")
    assert "- Status: aborted\n- Status reason: policy replaced\n" in markdown
    assert "- Finished: 2026-09-27T01:00:00+00:00" in markdown
    assert "## Acceptance: FAIL" in markdown
    assert "Milestone accepted: no." in markdown
    assert "| 2 | stopped | interrupted | 4 |" in markdown
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
    del payload["results"][0]["steps"]
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
    assert len(stored["results"]) == 10
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
