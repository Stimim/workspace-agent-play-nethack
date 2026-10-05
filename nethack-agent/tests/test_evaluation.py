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
from nethack_agent.corpse import (
    CorpseKill,
    eligible_corpse,
    observed_corpse_kill,
)
from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    CorpseEvidence,
    CorpseOutcome,
    CorpseOutcomeKind,
    DecisionMetrics,
    DestinationKind,
    IntentDestination,
    MapCell,
    PrayerEvidence,
    PrayerOutcome,
    PrayerOutcomeKind,
    RunOutcome,
    RunState,
    Skill,
    SkillSelectionSource,
    classify_corpse_outcome,
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
    BucStatus,
    InventoryItem,
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


_TASK_PROGRESSION_POLICY = "hierarchical-task-progression-v1"


@pytest.mark.parametrize(
    ("suite_path", "pin"),
    [
        (STAIRCASE_V2_PATH, "hierarchical-traversal-v1"),
        (TRAVERSAL_V1_PATH, "hierarchical-traversal-v1"),
        (STAIRCASE_V3_PATH, _TASK_PROGRESSION_POLICY),
        (TRAVERSAL_V2_PATH, _TASK_PROGRESSION_POLICY),
        (REPORT_DIRECTORY.parent / "scout-v1.json", _TASK_PROGRESSION_POLICY),
        (REPORT_DIRECTORY.parent / "eat-v1.json", _TASK_PROGRESSION_POLICY),
    ],
)
def test_committed_suites_refuse_under_a_later_policy_before_any_episode(
    tmp_path: Path, suite_path: Path, pin: str
) -> None:
    # Their policy pin is immutable evidence; later policies use new suite ids.
    assert load_suite(suite_path).policy_version == pin
    assert pin != run_manager.POLICY_VERSION
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
        ("knowledge_bundle_id", "pins unavailable knowledge bundle"),
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


@pytest.mark.usefixtures("bound_policy")
def test_pinned_survival_bundle_reaches_run_manager_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = suite_2_payload()
    payload["suite_id"] = "survival-bundle-smoke"
    payload["knowledge_bundle_id"] = "survival-reviewed-v2"
    payload["policy_version"] = run_manager.POLICY_VERSION
    payload["cases"][0]["task"] = {
        "environment": "NetHackScore-v0",
        "action_profile": "nle-survival-actions",
        "objective": {
            "legs": [
                {
                    "kind": "reach_level",
                    "level": {"dungeon_number": 0, "dungeon_level": 5},
                }
            ]
        },
    }  # type: ignore[index]
    payload["cases"][0]["seeds"] = [1150]  # type: ignore[index]
    payload["cases"][0]["max_episode_steps"] = 2  # type: ignore[index]
    payload["cases"][0]["acceptance"] = {
        "min_successes": 1,
        "required_success_seeds": [],
    }  # type: ignore[index]
    suite = load_suite(write_suite(tmp_path, payload))

    from nethack_agent.knowledge import KnowledgeBundle

    captured: list[KnowledgeBundle] = []
    original_init = RunManager.__init__

    def inspect_init(self: RunManager, *args: object, **kwargs: object) -> None:
        captured.append(kwargs["knowledge_bundle"])
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(
        evaluation,
        "RunManager",
        type("InspectRunManager", (RunManager,), {"__init__": inspect_init}),
    )
    run = run_evaluation(
        EvaluationOptions(
            suite=suite,
            data_directory=tmp_path / "data",
            report_directory=tmp_path / "reports",
            development_scripted_model=True,
            poll_interval_seconds=0.01,
        ),
        progress=None,
    )

    bundle = captured[0]
    assert bundle.bundle_id == "survival-reviewed-v2"
    assert {card.card_id for card in bundle.cards} >= {
        "prayer-hunger",
        "safe-corpses-v2",
    }
    assert "Plan food and prayer without claiming certainty" in bundle.prompt_context
    assert "Eat only identified fresh low-risk corpses" in bundle.prompt_context
    record = RunStore(tmp_path / "data" / "runs.sqlite3").get_run(
        run.report.results[0].run_id
    )
    assert run.report.acceptance().checks["inputs_unchanged"]
    assert record.knowledge_version == bundle.version


def test_missing_pinned_bundle_fails_before_episode(tmp_path: Path) -> None:
    payload = suite_2_payload()
    payload["policy_version"] = run_manager.POLICY_VERSION
    payload["knowledge_bundle_id"] = "missing-reviewed-v99"
    suite = load_suite(write_suite(tmp_path, payload))
    data_directory = tmp_path / "data"
    report_directory = tmp_path / "reports"

    with pytest.raises(SuiteValidationError, match="pins unavailable knowledge bundle"):
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


def test_corpse_replay_requires_observed_target_identity_and_fresh_look_here() -> None:
    level = LevelKey(0, 1)
    before = synthetic_observation(0, level, 1, hunger=1)
    lichen_index = next(
        index
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == "lichen"
    )
    glyphs = list(before.map.glyph_rows[0])
    glyphs[1] = nethack.GLYPH_MON_OFF + lichen_index
    before = replace(
        before,
        map=replace(
            before.map,
            glyph_rows=(tuple(glyphs), before.map.glyph_rows[1]),
            pet_rows=(bytes(5), bytes(5)),
        ),
    )
    killed = replace(
        synthetic_observation(1, level, 1, hunger=1),
        message="You kill the lichen!",
        player=replace(before.player, turn=2),
    )
    kill = observed_corpse_kill(before, _EAST, killed)
    assert kill == CorpseKill("lichen", 2, level, MapCell(1, 0))
    assert (
        observed_corpse_kill(
            before, _EAST, replace(killed, message="You kill the gecko!")
        )
        is None
    )
    assert (
        observed_corpse_kill(
            replace(before, map=replace(before.map, pet_rows=None)), _EAST, killed
        )
        is None
    )
    body = list(killed.map.glyph_rows[0])
    body[1] = nethack.GLYPH_BODY_OFF + lichen_index
    floor = replace(
        killed,
        map=replace(killed.map, glyph_rows=(tuple(body), killed.map.glyph_rows[1])),
    )
    evidence = eligible_corpse(kill, floor)
    assert evidence == CorpseEvidence("lichen", 2, 0, MapCell(1, 0))
    here = replace(
        floor,
        player=replace(floor.player, x=1, turn=3),
        message="You see here a lichen corpse.",
    )
    assert eligible_corpse(kill, here) == replace(evidence, age=1)
    assert (
        eligible_corpse(kill, replace(here, message="You see here a gecko corpse."))
        is None
    )
    # Lichen alone is exempt from the ordinary 19-turn freshness cap.
    assert eligible_corpse(
        kill, replace(floor, player=replace(floor.player, turn=22))
    ) == replace(evidence, age=20)
    assert (
        eligible_corpse(kill, replace(floor, player=replace(floor.player, hunger=0)))
        is None
    )
    assert (
        eligible_corpse(
            kill, replace(floor, player=replace(floor.player, dungeon_level=2))
        )
        is None
    )


def test_corpse_route_audit_requires_visible_reachable_kill_cell() -> None:
    level = LevelKey(0, 1)
    before = synthetic_observation(2, level, 1, hunger=1)
    body = list(before.map.glyph_rows[0])
    body[1] = nethack.GLYPH_BODY_OFF
    before = replace(
        before,
        map=replace(
            before.map,
            rows=(" %   ", "     "),
            glyph_rows=(tuple(body), before.map.glyph_rows[1]),
        ),
    )
    evidence = CorpseEvidence("lichen", 2, 1, MapCell(1, 0))
    kill = CorpseKill("lichen", 2, level, evidence.cell)
    history = {(level, 1, 0): kill}
    after = replace(
        synthetic_observation(3, level, 1, hunger=1),
        player=replace(before.player, x=1, turn=4),
        message="You see here a lichen corpse.",
    )
    base = synthetic_step(after)
    step = replace(
        base,
        selection=replace(
            base.selection,
            skill=Skill.CORPSE,
            intent=ActionIntent(
                IntentDestination(DestinationKind.CORPSE, 1, 0),
                None,
                (MapCell(1, 0),),
                level,
                corpse=evidence,
            ),
        ),
    )
    memory = evaluation.DungeonMemory()
    memory.observe(before)
    profile = ActionProfile.NLE_SURVIVAL_ACTIONS
    assert evaluation._action_is_valid(
        step,
        (_EAST,),
        before,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        dungeon_memory=memory,
    )
    for covered in (
        replace(before, map=replace(before.map, rows=("     ", "     "))),
        replace(
            before,
            map=replace(
                before.map,
                glyph_rows=synthetic_observation(2, level, 1, 1).map.glyph_rows,
            ),
        ),
    ):
        assert not evaluation._action_is_valid(
            step,
            (_EAST,),
            covered,
            True,
            profile,
            corpse_kills=history,
            consumed_corpses=set(),
        )
    assert not evaluation._action_is_valid(
        step,
        (_EAST,),
        before,
        True,
        profile,
        corpse_kills={},
        consumed_corpses=set(),
    )


def test_corpse_eat_and_yes_audit_requires_original_observed_kill() -> None:
    level = LevelKey(0, 1)
    after = synthetic_observation(2, level, 1, hunger=1)
    before = replace(
        after,
        player=replace(after.player, x=1, turn=3),
        message="You see here a lichen corpse.",
    )
    evidence = CorpseEvidence("lichen", 2, 1, MapCell(1, 0))
    kill = CorpseKill("lichen", 2, level, evidence.cell)
    history = {(level, 1, 0): kill}
    floor_prompt = replace(
        after,
        player=before.player,
        message="There is a lichen corpse here; eat it? [ynq] (n) ",
        prompt=PromptState(True, False, False),
    )
    eat = LegalAction(0, ord("e"), "Command.EAT")
    step = synthetic_step(floor_prompt)
    selection = replace(
        step.selection,
        skill=Skill.CORPSE,
        intent=ActionIntent(None, None, None, corpse=evidence),
    )
    eat_step = replace(step, action=eat, selection=selection)
    profile = ActionProfile.NLE_SURVIVAL_ACTIONS
    assert evaluation._action_is_valid(
        eat_step,
        (eat,),
        before,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
    )
    for forged in (
        replace(before, message="You see here a gecko corpse."),
        replace(before, player=replace(before.player, turn=22)),
        replace(before, player=replace(before.player, hunger=0)),
        replace(before, player=replace(before.player, x=0)),
    ):
        assert not evaluation._action_is_valid(
            eat_step,
            (eat,),
            forged,
            True,
            profile,
            corpse_kills=history,
            consumed_corpses=set(),
        )
    assert not evaluation._action_is_valid(
        eat_step,
        (eat,),
        before,
        True,
        profile,
        corpse_kills={},
        consumed_corpses=set(),
    )
    assert not evaluation._action_is_valid(
        eat_step,
        (eat,),
        before,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses={(level, 1, 0, 2)},
    )
    assert not evaluation._action_is_valid(
        eat_step,
        (eat,),
        before,
        True,
        profile,
        corpse_kills={(level, 1, 0): CorpseKill("gecko", 2, level, evidence.cell)},
        consumed_corpses=set(),
    )
    yes = LegalAction(0, ord("y"), "CompassDirection.NW")
    finished = replace(
        after,
        player=replace(before.player, turn=7, hunger=0),
        message="This lichen corpse tastes okay.  You finish eating the lichen corpse.",
    )
    answered = replace(
        synthetic_step(finished),
        action=yes,
        selection=replace(
            selection,
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            intent=ActionIntent(
                None,
                None,
                None,
                corpse=replace(
                    evidence,
                    outcome=CorpseOutcome(
                        CorpseOutcomeKind.FINISHED,
                        7,
                        0,
                        finished.message,
                    ),
                ),
            ),
        ),
    )
    assert evaluation._action_is_valid(
        answered,
        (yes,),
        floor_prompt,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    assert not evaluation._action_is_valid(
        answered,
        (yes,),
        floor_prompt,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
    )
    assert not evaluation._action_is_valid(
        answered,
        (yes,),
        replace(floor_prompt, message=floor_prompt.message.replace("lichen", "gecko")),
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    assert not evaluation._action_is_valid(
        answered,
        (yes,),
        floor_prompt,
        True,
        profile,
        corpse_kills={(level, 1, 0): CorpseKill("gecko", 3, level, evidence.cell)},
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    # Unexpected floor identity does not retroactively invalidate the EAT
    # decision; the only valid response to that new prompt is decline.
    mismatched = replace(
        floor_prompt,
        message=floor_prompt.message.replace("lichen", "gecko"),
    )
    assert evaluation._action_is_valid(
        replace(eat_step, observation=mismatched),
        (eat,),
        before,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
    )
    no = LegalAction(0, ord("n"), "CompassDirection.SE")
    declined = replace(
        after,
        player=before.player,
        message="Never mind.",
    )
    no_step = replace(
        synthetic_step(declined),
        action=no,
        selection=replace(
            selection,
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            intent=ActionIntent(
                None,
                None,
                None,
                corpse=replace(
                    evidence,
                    outcome=CorpseOutcome(
                        CorpseOutcomeKind.DECLINED,
                        3,
                        1,
                        declined.message,
                    ),
                ),
            ),
        ),
    )
    assert evaluation._action_is_valid(
        no_step,
        (no,),
        mismatched,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    assert not evaluation._action_is_valid(
        no_step,
        (no,),
        mismatched,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
    )
    esc = LegalAction(0, 27, "Command.ESC")
    inventory_prompt = replace(
        floor_prompt,
        message="What do you want to eat? [a or ?*]",
    )
    esc_step = replace(no_step, action=esc)
    assert evaluation._action_is_valid(
        esc_step,
        (esc,),
        inventory_prompt,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    assert not evaluation._action_is_valid(
        esc_step,
        (esc,),
        mismatched,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses=set(),
        pending_corpse=evidence,
    )
    for message, kind in (
        ("Blecch!  Rotten food!", CorpseOutcomeKind.ENDED_UNRECOGNIZED),
        ("You hear someone cursing shoplifters.", CorpseOutcomeKind.ENDED_UNRECOGNIZED),
        ("You stop eating the lichen corpse.", CorpseOutcomeKind.INTERRUPTED),
    ):
        ended = replace(
            finished, player=replace(before.player, turn=4), message=message
        )
        assert classify_corpse_outcome("lichen", ended.message) is kind
        ended_yes = replace(
            answered,
            observation=ended,
            selection=replace(
                answered.selection,
                intent=ActionIntent(
                    None,
                    None,
                    None,
                    corpse=replace(
                        evidence,
                        outcome=CorpseOutcome(kind, 4, ended.player.hunger, message),
                    ),
                ),
            ),
        )
        assert evaluation._action_is_valid(
            ended_yes,
            (yes,),
            floor_prompt,
            True,
            profile,
            corpse_kills=history,
            consumed_corpses=set(),
            pending_corpse=evidence,
        )
        missing = replace(
            ended_yes.selection, intent=ActionIntent(None, None, None, corpse=evidence)
        )
        with pytest.raises(ContractError, match="observed outcome"):
            replace(ended_yes, selection=missing)
    # Completion evidence is mandatory on live completion observations, but
    # terminal/truncated observations must not manufacture a meal outcome.
    for completed, decided_on, action, pending in (
        (answered, floor_prompt, yes, {"pending_corpse": evidence}),
    ):
        missing = replace(
            completed.selection,
            intent=ActionIntent(None, None, None, corpse=evidence),
        )
        with pytest.raises(ContractError, match="observed outcome"):
            replace(completed, selection=missing)
        for terminated, truncated, outcome in (
            (True, False, RunOutcome.DEATH),
            (False, True, RunOutcome.TRUNCATED),
        ):
            terminal = replace(
                completed,
                terminated=terminated,
                truncated=truncated,
                outcome=outcome,
                selection=missing,
                observation=synthetic_observation(3, None, 1, hunger=0),
            )
            assert evaluation._action_is_valid(
                terminal,
                (action,),
                decided_on,
                True,
                profile,
                corpse_kills=history,
                consumed_corpses=set(),
                **pending,
            )
            with pytest.raises(ContractError, match="observed outcome"):
                replace(terminal, selection=completed.selection)


def test_corpse_forgery_is_counted_as_invalid_action_in_event_replay(
    tmp_path: Path,
) -> None:
    suite = load_suite(SUITE_PATH)
    task = replace(STAIRCASE_TASK, action_profile=ActionProfile.NLE_SURVIVAL_ACTIONS)
    case = replace(suite.cases[0], task=task)
    initial = synthetic_observation(0, LevelKey(0, 1), 1, hunger=1)
    initial = replace(
        initial,
        player=replace(initial.player, x=1, turn=3),
        message="You see here a lichen corpse.",
    )
    evidence = CorpseEvidence("lichen", 2, 1, MapCell(1, 0))
    eat = LegalAction(0, ord("e"), "Command.EAT")
    prompt = replace(
        synthetic_observation(1, LevelKey(0, 1), 1, hunger=1),
        player=initial.player,
        message="There is a lichen corpse here; eat it? [ynq] (n) ",
        prompt=PromptState(True, False, False),
    )
    step = replace(
        synthetic_step(prompt, RunOutcome.DEATH),
        action=eat,
        selection=replace(
            synthetic_step(prompt).selection,
            skill=Skill.CORPSE,
            intent=ActionIntent(None, None, None, corpse=evidence),
        ),
    )
    record = RunRecord(
        id="corpse-forgery",
        created_at="2026-09-28T00:00:00+00:00",
        updated_at="2026-09-28T00:00:00+00:00",
        state=RunState.TERMINAL,
        outcome=RunOutcome.DEATH,
        environment=task.environment.value,
        character=suite.character,
        suite_seed=1,
        core_seed=1,
        display_seed=1,
        level_seed=1,
        max_episode_steps=case.max_episode_steps,
        model="scripted",
        policy_version="policy",
        knowledge_version="knowledge",
        nle_version="1.3.0",
        ollama_num_ctx=8192,
        ollama_version=None,
        ttyrec_path=None,
        error=None,
        task=task,
    )
    events = (
        RunEvent(
            0,
            record.created_at,
            EventKind.RUN_STARTED,
            RunStartedPayload(
                initial,
                (eat,),
                STAND_ON_DOWNSTAIRS,
                None,
            ),
        ),
        RunEvent(1, record.created_at, EventKind.STEP, step),
    )
    result = summarize_run(
        record,
        events,
        suite=suite,
        case=case,
        seed=1,
        ended_by="episode_end",
        wall_seconds=0.0,
        data_directory=tmp_path,
    )
    assert result.invalid_actions == 1


def test_survival_audit_rechecks_prayer_yes_and_ration_evidence() -> None:
    before = synthetic_observation(0, LevelKey(0, 1), 1, hunger=2)
    after = synthetic_observation(1, LevelKey(0, 1), 1, hunger=2)
    step = synthetic_step(after)
    profile = ActionProfile.NLE_SURVIVAL_ACTIONS

    pray = LegalAction(0, 240, "Command.PRAY")
    prayer = replace(step.selection, skill=Skill.PRAYER)
    with pytest.raises(ContractError, match="pending prayer evidence"):
        replace(step, action=pray, selection=prayer)
    with pytest.raises(ContractError, match="only the deterministic prayer skill"):
        replace(step, action=pray)

    yes = LegalAction(0, ord("y"), "CompassDirection.NW")
    with pytest.raises(ContractError):
        replace(
            step,
            action=yes,
            selection=replace(
                step.selection,
                source=ActionSelectionSource.DETERMINISTIC_PROMPT,
                skill=Skill.PRAYER,
            ),
        )
    corpse_choice = replace(
        before,
        prompt=PromptState(True, False, False),
        message="There is a lichen corpse here; eat it? [ynq] (n) ",
    )
    corpse_answer = replace(
        step.selection,
        source=ActionSelectionSource.DETERMINISTIC_PROMPT,
        skill=Skill.HUNGER,
    )
    yes_step = replace(step, action=yes, selection=corpse_answer)
    assert not evaluation._action_is_valid(
        yes_step, (yes,), corpse_choice, True, profile
    )
    no = LegalAction(0, ord("n"), "CompassDirection.SE")
    no_step = replace(step, action=no, selection=corpse_answer)
    non_allowed = replace(
        corpse_choice,
        message="There is a jackal corpse here; eat it? [ynq] (n) ",
    )
    assert evaluation._action_is_valid(
        no_step,
        (no,),
        non_allowed,
        True,
        profile,
    )
    assert not evaluation._action_is_valid(no_step, (no,), before, True, profile)
    item_choice = replace(
        corpse_choice,
        message="What do you want to eat? [y or ?*]",
    )
    assert evaluation._action_is_valid(yes_step, (yes,), item_choice, True, profile)
    assert evaluation._action_is_valid(
        replace(step, action=yes), (yes,), before, True, profile
    )  # Out-of-prompt northwest movement remains legal.

    eat = LegalAction(0, ord("e"), "Command.EAT")
    eat_step = replace(
        step,
        action=eat,
        selection=replace(step.selection, skill=Skill.HUNGER),
    )
    assert not evaluation._action_is_valid(eat_step, (eat,), before, True, profile)
    ration_index = next(
        index
        for index in range(nethack.NUM_OBJECTS)
        if nethack.OBJ_NAME(nethack.objclass(index)) == "food ration"
    )
    ration = InventoryItem(
        "d",
        "a food ration",
        nethack.GLYPH_OBJ_OFF + ration_index,
        int(nethack.FOOD_CLASS),
        BucStatus.UNKNOWN,
    )
    with_ration = replace(before, inventory=(ration,))
    assert evaluation._action_is_valid(eat_step, (eat,), with_ration, True, profile)
    assert not evaluation._action_is_valid(
        eat_step,
        (eat,),
        replace(with_ration, player=replace(before.player, hunger=1)),
        True,
        profile,
    )


def test_prayer_replay_requires_original_prompt_and_matching_observed_outcome(
    tmp_path: Path,
) -> None:
    level = LevelKey(0, 1)
    initial = synthetic_observation(0, level, 1, hunger=3)
    initial = replace(initial, player=replace(initial.player, turn=100))
    prompt = replace(
        synthetic_observation(1, level, 1, hunger=3),
        player=initial.player,
        message="Are you sure you want to pray? [yn] (n) ",
        prompt=PromptState(True, False, False),
    )
    after = replace(
        synthetic_observation(2, level, 1, hunger=0),
        player=replace(initial.player, turn=103, hunger=0),
        message="Your stomach feels content.",
    )
    evidence = PrayerEvidence(3, 100, 100)
    intent = ActionIntent(None, None, None, prayer=evidence)
    pray = LegalAction(0, 240, "Command.PRAY")
    yes = LegalAction(1, ord("y"), "CompassDirection.NW")
    prayer = replace(
        synthetic_step(prompt),
        action=pray,
        selection=replace(
            synthetic_step(prompt).selection, skill=Skill.PRAYER, intent=intent
        ),
    )
    answer = replace(
        synthetic_step(after),
        action=yes,
        selection=replace(
            prayer.selection,
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            action_index=1,
            intent=replace(
                intent,
                prayer=replace(
                    evidence,
                    outcome=PrayerOutcome(
                        103, 0, after.message, PrayerOutcomeKind.FIXED
                    ),
                ),
            ),
        ),
    )
    legal = (pray, yes, LegalAction(2, _EAST.command, _EAST.name))
    profile = ActionProfile.NLE_SURVIVAL_ACTIONS
    assert evaluation._action_is_valid(prayer, legal, initial, True, profile)
    with pytest.raises(ContractError, match="exact confirmation prompt"):
        replace(prayer, observation=replace(prompt, message=prompt.message.rstrip()))
    assert not evaluation._action_is_valid(
        prayer,
        legal,
        initial,
        True,
        profile,
        prior_prayers=1,
        last_prayer_turn=99,
    )
    early = replace(
        prayer,
        selection=replace(
            prayer.selection,
            intent=replace(
                intent,
                prayer=PrayerEvidence(3, 99, 100),
            ),
        ),
    )
    assert not evaluation._action_is_valid(
        early,
        legal,
        replace(initial, player=replace(initial.player, turn=99)),
        True,
        profile,
    )
    assert evaluation._action_is_valid(
        answer,
        legal,
        prompt,
        True,
        profile,
        pending_prayer=evidence,
    )
    assert not evaluation._action_is_valid(answer, legal, prompt, True, profile)
    assert not evaluation._action_is_valid(
        answer,
        legal,
        replace(prompt, message="Are you sure you want to pray? [yn] (n)"),
        True,
        profile,
        pending_prayer=evidence,
    )
    with pytest.raises(ContractError, match="matching observed outcome"):
        replace(
            answer,
            selection=replace(
                answer.selection,
                intent=replace(
                    intent,
                    prayer=replace(
                        evidence,
                        outcome=PrayerOutcome(
                            103, 1, after.message, PrayerOutcomeKind.FIXED
                        ),
                    ),
                ),
            ),
        )
    forged_prior = replace(
        answer,
        selection=replace(
            answer.selection,
            intent=replace(
                intent,
                prayer=replace(
                    evidence,
                    prayer_turn=99,
                    outcome=PrayerOutcome(
                        103, 0, after.message, PrayerOutcomeKind.FIXED
                    ),
                ),
            ),
        ),
    )
    assert not evaluation._action_is_valid(
        forged_prior,
        legal,
        prompt,
        True,
        profile,
        pending_prayer=evidence,
    )
    assert not evaluation._action_is_valid(
        prayer,
        legal,
        initial,
        True,
        profile,
        kill_count=2,
    )
    with pytest.raises(ContractError, match="matching observed outcome"):
        replace(
            answer,
            observation=replace(
                after,
                player=replace(after.player, hunger=3),
                message="The lichen bites!",
            ),
        )
    terminal_observation = synthetic_observation(2, None, 1, hunger=0)
    terminal_answer = replace(
        synthetic_step(terminal_observation, RunOutcome.DEATH),
        action=yes,
        selection=replace(answer.selection, intent=intent),
    )
    assert evaluation._action_is_valid(
        terminal_answer,
        legal,
        prompt,
        True,
        profile,
        pending_prayer=evidence,
    )
    with pytest.raises(ContractError, match="cannot claim an observed outcome"):
        replace(terminal_answer, selection=answer.selection)
    truncated_answer = replace(
        terminal_answer,
        terminated=False,
        truncated=True,
        outcome=RunOutcome.TRUNCATED,
    )
    assert evaluation._action_is_valid(
        truncated_answer,
        legal,
        prompt,
        True,
        profile,
        pending_prayer=evidence,
    )
    with pytest.raises(ContractError, match="cannot claim an observed outcome"):
        replace(truncated_answer, selection=answer.selection)
    not_fixed = replace(
        after,
        player=replace(after.player, hunger=3),
        message="You finish your prayer.  You feel that Tyr is satisfied.",
    )
    not_fixed_answer = replace(
        answer,
        observation=not_fixed,
        selection=replace(
            answer.selection,
            intent=replace(
                intent,
                prayer=replace(
                    evidence,
                    outcome=PrayerOutcome(
                        103,
                        3,
                        not_fixed.message,
                        PrayerOutcomeKind.NOT_FIXED,
                    ),
                ),
            ),
        ),
    )
    assert evaluation._action_is_valid(
        not_fixed_answer,
        legal,
        prompt,
        True,
        profile,
        pending_prayer=evidence,
    )

    # Audit folds sequential persisted events, not per-row minted permits.
    suite = load_suite(SUITE_PATH)
    task = replace(STAIRCASE_TASK, action_profile=profile)
    case = replace(suite.cases[0], task=task)
    record = RunRecord(
        id="prayer-replay",
        created_at="2026-09-28T00:00:00+00:00",
        updated_at="2026-09-28T00:00:00+00:00",
        state=RunState.TERMINAL,
        outcome=RunOutcome.DEATH,
        environment=task.environment.value,
        character=suite.character,
        suite_seed=1,
        core_seed=1,
        display_seed=1,
        level_seed=1,
        max_episode_steps=case.max_episode_steps,
        model="scripted",
        policy_version="policy",
        knowledge_version="knowledge",
        nle_version="1.3.0",
        ollama_num_ctx=8192,
        ollama_version=None,
        ttyrec_path=None,
        error=None,
        task=task,
    )

    def audited(rows: list[StepPayload]) -> int:
        events = [
            RunEvent(
                0,
                "2026-09-28T00:00:00+00:00",
                EventKind.RUN_STARTED,
                RunStartedPayload(initial, legal, STAND_ON_DOWNSTAIRS, None),
            ),
            *(
                RunEvent(index, "2026-09-28T00:00:00+00:00", EventKind.STEP, row)
                for index, row in enumerate(rows, start=1)
            ),
        ]
        return summarize_run(
            record,
            events,
            suite=suite,
            case=case,
            seed=1,
            ended_by="episode_end",
            wall_seconds=0.0,
            data_directory=tmp_path,
        ).invalid_actions

    assert audited([prayer, answer]) == 0
    assert audited([prayer, terminal_answer]) == 0
    assert audited([prayer, not_fixed_answer]) == 0
    assert audited([answer]) == 1
    assert audited([prayer, forged_prior]) == 1
    duplicate = replace(prayer, observation=replace(prompt, step_index=3))
    assert audited([prayer, answer, duplicate]) == 1
    next_turn = 100 + 1229
    waited = replace(
        synthetic_observation(3, level, 1, hunger=3),
        player=replace(initial.player, turn=next_turn),
        message="You kill the lichen!",
    )
    wait_step = replace(
        synthetic_step(waited),
        action=legal[2],
        selection=replace(synthetic_step(waited).selection, action_index=2),
    )
    repeat_evidence = PrayerEvidence(3, next_turn, next_turn, kill_count=1)
    repeat_prompt = replace(
        prompt,
        step_index=4,
        player=waited.player,
    )
    repeat_prayer = replace(
        prayer,
        observation=repeat_prompt,
        selection=replace(
            prayer.selection,
            intent=ActionIntent(None, None, None, prayer=repeat_evidence),
        ),
    )
    repeat_after = replace(
        after,
        step_index=5,
        player=replace(after.player, turn=next_turn + 3),
    )
    repeat_answer = replace(
        answer,
        observation=repeat_after,
        selection=replace(
            answer.selection,
            intent=ActionIntent(
                None,
                None,
                None,
                prayer=replace(
                    repeat_evidence,
                    outcome=PrayerOutcome(
                        next_turn + 3,
                        0,
                        repeat_after.message,
                        PrayerOutcomeKind.FIXED,
                    ),
                ),
            ),
        ),
    )
    assert audited([prayer, answer, wait_step, repeat_prayer, repeat_answer]) == 0
    forged_kills = replace(
        repeat_prayer,
        selection=replace(
            repeat_prayer.selection,
            intent=ActionIntent(
                None,
                None,
                None,
                prayer=replace(repeat_evidence, kill_count=0),
            ),
        ),
    )
    assert audited([prayer, answer, wait_step, forged_kills, repeat_answer]) == 2


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


def test_audit_flags_a_gold_intent_on_a_cell_that_showed_no_gold(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    manager = RunManager(
        data_directory,
        OllamaConfig(model="scripted"),
        model_factory=lambda _client: ScriptedDevelopmentModel(),
    )
    task = TaskSpec(
        NleTask.GOLD,
        ActionProfile.NLE_TASK_ACTIONS,
        Objective((ExploreDungeonLeg(3),)),
    )
    try:
        # Seed 4 routes to gold on its first step and picks it up at step 3.
        run_id = manager.create_run(
            seed=4, max_episode_steps=40, auto_start=True, task=task
        ).id
        deadline = time.monotonic() + 120
        while manager.store.get_run(run_id).state is RunState.RUNNING:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        manager.close()
    store = RunStore(data_directory / "runs.sqlite3")
    base_suite = load_suite(SUITE_PATH)
    case = replace(base_suite.cases[0], task=task, max_episode_steps=40)
    suite = replace(base_suite, cases=(case,))
    record = store.get_run(run_id)

    def audit() -> SeedResult:
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

    honest = audit()
    assert honest.integrity_problems == ()
    assert honest.metrics.final_gold > 0

    # Relabel an exploration route as gold navigation: its frontier cell
    # never displayed gold on the observation the step was decided on.
    with sqlite3.connect(data_directory / "runs.sqlite3") as connection:
        rowid, payload = next(
            (rowid, payload)
            for rowid, text in connection.execute(
                "SELECT rowid, payload_json FROM events ORDER BY sequence"
            )
            if isinstance(payload := json.loads(text), dict)
            and isinstance(selection := payload.get("selection"), dict)
            and isinstance(intent := selection.get("intent"), dict)
            and intent.get("path") is not None
            and intent["destination"]["kind"] == "frontier"
        )
        selection = payload["selection"]
        selection["skill"] = "gold_navigation"
        selection["intent"]["destination"]["kind"] = "gold"
        destination = selection["intent"]["destination"]
        connection.execute(
            "UPDATE events SET payload_json = ? WHERE rowid = ?",
            (json.dumps(payload), rowid),
        )
    step = payload["observation"]["step_index"]

    assert audit().integrity_problems == (
        f"step {step} gold intent ({destination['x']}, {destination['y']}) does "
        "not show gold on the decided-on observation",
    )


def schema_3_suite(tmp_path: Path) -> EvaluationSuite:
    catalog_directory = REPORT_DIRECTORY.parent
    for name in ("representative-seeds.json", "seed-ledger.json"):
        (tmp_path / name).write_bytes((catalog_directory / name).read_bytes())
    catalog_path = tmp_path / "representative-seeds.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["policy_version"] = run_manager.POLICY_VERSION
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    payload = suite_2_payload()
    payload["schema_version"] = 3
    payload["policy_version"] = run_manager.POLICY_VERSION
    payload["knowledge_bundle_id"] = "staircase-reviewed-v3"
    payload.pop("cases")
    payload["baseline"] = {
        "entry_ids": ["staircase-anchor-6", "descend-d3-hidden-downstairs-701"]
    }
    payload["fresh_sample"] = {
        "case_id": "fresh-staircase",
        "task": STAIRCASE_TASK.to_json(),
        "max_episode_steps": 300,
        "count": 3,
        "range": [1_000_000, 1_000_999],
        "acceptance": {"min_success_rate": 0.5},
    }
    return load_suite(write_suite(tmp_path, payload))


def test_schema_3_baseline_requires_catalog_policy_pin(tmp_path: Path) -> None:
    suite = schema_3_suite(tmp_path)
    assert suite.catalog_path is not None
    catalog = json.loads(suite.catalog_path.read_text(encoding="utf-8"))
    catalog["policy_version"] = "different-policy"
    suite.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(
        SuiteValidationError, match="catalog policy_version.*does not match"
    ):
        load_suite(suite.path)


def test_changed_baseline_catalog_fails_input_integrity_and_acceptance(
    tmp_path: Path,
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload.pop("fresh_sample")
    suite = load_suite(write_suite(tmp_path, payload))
    assert suite.catalog_path is not None
    report = EvaluationReport(
        suite=suite,
        model_mode="ollama",
        model="gemma4-nethack:latest",
        policy_version=suite.policy_version,
        knowledge_version=evaluation.load_default_knowledge_bundle().version,
        ollama_num_ctx=8192,
        requested_seeds=(6, 701),
        data_directory=str(tmp_path),
        started_at="2026-09-30T00:00:00+00:00",
        status=ReportStatus.COMPLETE,
        results=[
            result(6, RunOutcome.TASK_SUCCESS, case_id="staircase-anchor-6"),
            result(701, RunOutcome.DEATH, case_id="descend-d3-hidden-downstairs-701"),
        ],
    )
    assert evaluation._inputs_unchanged(report)
    assert report.acceptance().passed
    catalog_record = report.to_json()["baseline"]["catalog"]
    assert catalog_record["path"] == str(suite.catalog_path)
    assert catalog_record["sha256"] == suite.catalog_sha256

    catalog = json.loads(suite.catalog_path.read_text(encoding="utf-8"))
    catalog["entries"][0]["represents"] = "Changed during the evaluation run."
    suite.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    report.inputs_unchanged = evaluation._inputs_unchanged(report)

    assert report.inputs_unchanged is False
    assert report.acceptance().checks["inputs_unchanged"] is False
    assert not report.acceptance().passed
    assert "catalog" in render_report_markdown(report.to_json()).lower()


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("suite", "unexpected", True, "unexpected"),
        ("baseline", "unknown", True, "unknown"),
        ("fresh_sample", "unknown", True, "unknown"),
        ("fresh_sample", "range", [8, 7], "reversed"),
        ("fresh_sample", "range", [1, 2, 3], "two bounds"),
        ("fresh_sample", "count", 1001, "available range"),
        ("fresh_sample", "count", 0, "at least 1"),
        ("fresh_sample", "count", True, "integer"),
        ("fresh_sample", "range", [1, True], "integer"),
        ("fresh_acceptance", "min_success_rate", 1.01, r"\[0, 1\]"),
        ("fresh_acceptance", "min_success_rate", -0.01, r"\[0, 1\]"),
        ("fresh_acceptance", "min_success_rate", True, "number"),
        ("fresh_acceptance", "metric_thresholds", [], "must not be empty"),
        ("baseline", "entry_ids", ["missing-entry"], "unknown catalog entry_id"),
        (
            "baseline",
            "entry_ids",
            ["staircase-anchor-6", "staircase-anchor-6"],
            "unique",
        ),
        ("fresh_sample", "case_id", "staircase-anchor-6", "unique across"),
    ],
)
def test_schema_3_rejects_invalid_blocks(
    tmp_path: Path, section: str, key: str, value: object, message: str
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    target = (
        payload["fresh_sample"]["acceptance"]
        if section == "fresh_acceptance"
        else payload[section]
        if section != "suite"
        else payload
    )
    target[key] = value
    with pytest.raises(SuiteValidationError, match=message):
        load_suite(write_suite(tmp_path, payload))


def test_schema_3_cases_are_optional_but_all_case_ids_are_unique(
    tmp_path: Path,
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload["cases"] = [
        {
            "case_id": "regression",
            "task": STAIRCASE_TASK.to_json(),
            "seeds": [3],
            "max_episode_steps": 300,
            "acceptance": {"min_successes": 1, "required_success_seeds": []},
        }
    ]
    parsed = load_suite(write_suite(tmp_path, payload))
    assert [case.case_id for case in parsed.cases] == [
        "regression",
        "staircase-anchor-6",
        "descend-d3-hidden-downstairs-701",
    ]
    payload["cases"][0]["case_id"] = "staircase-anchor-6"
    with pytest.raises(SuiteValidationError, match="unique across"):
        load_suite(write_suite(tmp_path, payload))
    payload.pop("cases")
    payload.pop("baseline")
    payload.pop("fresh_sample")
    with pytest.raises(
        SuiteValidationError, match="requires cases, baseline, or fresh_sample"
    ):
        load_suite(write_suite(tmp_path, payload))


def test_fresh_draw_is_deterministic_and_excludes_ledger_and_prior_reports(
    tmp_path: Path,
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload["fresh_sample"]["range"] = [1, 1000]
    suite = load_suite(write_suite(tmp_path, payload))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "earlier.json").write_text(
        json.dumps(
            {
                "report_schema_version": 4,
                "draw_provenance": evaluation.DrawProvenance(
                    1,
                    (997, 1000),
                    (),
                    evaluation._draw_available_seeds((997, 1000), (), 1, 4),
                ).to_json(),
            }
        ),
        encoding="utf-8",
    )
    first, excluded = evaluation.draw_fresh_seeds(suite, 7)
    second, _ = evaluation.draw_fresh_seeds(suite, 7)
    assert first == second
    assert excluded > 4
    assert not set(first) & {6, 701, 997, 998, 999, 1000}
    payload["fresh_sample"]["range"] = [997, 1000]
    suite = load_suite(write_suite(tmp_path, payload))
    with pytest.raises(EvaluationError, match="only 0 remain"):
        evaluation.draw_fresh_seeds(suite, 7)


def test_schema_3_rejects_explicit_seeds_and_mismatched_comparison_before_run(
    tmp_path: Path,
) -> None:
    suite = schema_3_suite(tmp_path)
    with pytest.raises(ValueError, match="--seeds cannot"):
        EvaluationOptions(suite, tmp_path / "data", tmp_path / "out", seeds=(6,))
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps({"report_schema_version": 4, "suite": {"suite_id": "another"}}),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="suite_id does not match"):
        run_evaluation(
            EvaluationOptions(
                suite,
                tmp_path / "data",
                tmp_path / "out",
                development_scripted_model=True,
                compare_report=previous,
            ),
            progress=None,
        )
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    ("must_outcome", "known_outcome", "known_changes", "problem", "passes", "status"),
    [
        (RunOutcome.TASK_SUCCESS, RunOutcome.DEATH, {}, {}, True, "pass"),
        (RunOutcome.DEATH, RunOutcome.DEATH, {}, {}, False, "pass"),
        (RunOutcome.TASK_SUCCESS, RunOutcome.TRUNCATED, {}, {}, True, "changed"),
        (
            RunOutcome.TASK_SUCCESS,
            RunOutcome.OBJECTIVE_COMPLETE,
            {"metrics": replace(EpisodeMetrics.empty(), objective_legs_completed=1)},
            {},
            True,
            "improved",
        ),
        (
            RunOutcome.TASK_SUCCESS,
            RunOutcome.DEATH,
            {},
            {"integrity_problems": ("missing ttyrec",)},
            False,
            "fail",
        ),
        (
            RunOutcome.TASK_SUCCESS,
            RunOutcome.DEATH,
            {},
            {"invalid_actions": 1},
            False,
            "fail",
        ),
    ],
)
def test_schema_3_baseline_gate_reports_catalog_statuses(
    tmp_path: Path,
    must_outcome: RunOutcome,
    known_outcome: RunOutcome,
    known_changes: dict[str, object],
    problem: dict[str, object],
    passes: bool,
    status: str,
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload.pop("fresh_sample")
    suite = load_suite(write_suite(tmp_path, payload))
    results = [
        result(6, must_outcome, case_id="staircase-anchor-6"),
        result(
            701,
            known_outcome,
            case_id="descend-d3-hidden-downstairs-701",
            **(known_changes | problem),
        ),
    ]
    report = EvaluationReport(
        suite,
        "ollama",
        "gemma4-nethack:latest",
        suite.policy_version,
        "staircase-reviewed-v3+sha256:test",
        8192,
        (6, 701),
        str(tmp_path),
        "2026-09-30T00:00:00+00:00",
        status=ReportStatus.COMPLETE,
        results=results,
    )
    assert report.acceptance().checks["baseline:staircase-anchor-6"] is (
        must_outcome is RunOutcome.TASK_SUCCESS
    )
    assert report.acceptance().checks["baseline:descend-d3-hidden-downstairs-701"] is (
        status != "fail"
    )
    assert report.to_json()["baseline"]["entries"][1]["check"]["status"] == status
    assert report.acceptance().passed is passes


@pytest.mark.parametrize(
    ("successes", "total", "bounds"),
    [(5, 10, (23.7, 76.3)), (10, 20, (29.9, 70.1))],
)
def test_wilson_interval_for_fresh_sample(
    successes: int, total: int, bounds: tuple[float, float]
) -> None:
    assert (
        tuple(
            round(percent * 100, 1)
            for percent in evaluation._wilson_95(successes, total)
        )
        == bounds
    )


def test_schema_4_report_round_trips_with_paired_baseline_diff(tmp_path: Path) -> None:
    suite = schema_3_suite(tmp_path)
    fresh = suite.fresh_sample
    assert fresh is not None
    provenance_record = evaluation._fresh_draw(suite, 7)
    seeds = provenance_record.drawn_seeds
    fresh_case = evaluation.EvaluationCase(
        fresh.case_id,
        fresh.task,
        seeds,
        fresh.max_episode_steps,
        evaluation.CaseAcceptance(0, (), fresh.acceptance.metric_thresholds),
    )
    suite = replace(suite, cases=suite.cases + (fresh_case,))
    baseline = [
        result(6, RunOutcome.TASK_SUCCESS, case_id="staircase-anchor-6"),
        result(701, RunOutcome.DEATH, case_id="descend-d3-hidden-downstairs-701"),
    ]
    provenance = provenance_record
    common = {
        "suite": suite,
        "model_mode": "ollama",
        "model": "gemma4-nethack:latest",
        "policy_version": suite.policy_version,
        "knowledge_version": "staircase-reviewed-v3+sha256:test",
        "ollama_num_ctx": 8192,
        "requested_seeds": (6, 701, *seeds),
        "data_directory": str(tmp_path),
        "started_at": "2026-09-30T00:00:00+00:00",
        "finished_at": "2026-09-30T00:01:00+00:00",
        "status": ReportStatus.COMPLETE,
        "draw_provenance": provenance,
    }
    previous = EvaluationReport(
        **common,
        results=[
            *baseline,
            *(result(seed, RunOutcome.DEATH, case_id=fresh.case_id) for seed in seeds),
        ],
    )
    current = EvaluationReport(
        **common,
        results=[
            baseline[0],
            result(
                701,
                RunOutcome.OBJECTIVE_COMPLETE,
                case_id="descend-d3-hidden-downstairs-701",
                metrics=replace(EpisodeMetrics.empty(), objective_legs_completed=1),
            ),
            result(seeds[0], RunOutcome.TASK_SUCCESS, case_id=fresh.case_id),
            result(seeds[1], RunOutcome.TASK_SUCCESS, case_id=fresh.case_id),
            result(seeds[2], RunOutcome.DEATH, case_id=fresh.case_id),
        ],
        comparison_source=previous.to_json(),
    )
    stored = current.to_json()
    assert stored["report_schema_version"] == 4
    assert stored["fresh"]["successes"] == 2
    assert stored["baseline"]["passed"] is True
    assert stored["baseline"]["entries"][1]["check"]["status"] == "improved"
    comparison = stored["comparison"]["entries"][1]
    assert comparison["prior_outcome"] == "death"
    assert comparison["current_outcome"] == "objective_complete"
    markdown = current.to_markdown()
    assert markdown == render_report_markdown(json.loads(json.dumps(stored)))
    assert "## Paired baseline comparison" in markdown
    assert "## Fresh sample `fresh-staircase`" in markdown


def test_fresh_metric_gate_can_fail_despite_success_rate(tmp_path: Path) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload.pop("baseline")
    payload["fresh_sample"]["acceptance"]["metric_thresholds"] = [
        {
            "metric": "death",
            "statistic": "sum",
            "bound": {"comparison": "at_most", "value": 0},
        }
    ]
    suite = load_suite(write_suite(tmp_path, payload))
    fresh = suite.fresh_sample
    assert fresh is not None
    sample = replace(
        suite,
        cases=(
            evaluation.EvaluationCase(
                fresh.case_id,
                fresh.task,
                (1_000_101, 1_000_102, 1_000_103),
                fresh.max_episode_steps,
                evaluation.CaseAcceptance(0, (), fresh.acceptance.metric_thresholds),
            ),
        ),
    )
    results = [
        result(1_000_101, RunOutcome.TASK_SUCCESS, case_id=fresh.case_id),
        result(1_000_102, RunOutcome.TASK_SUCCESS, case_id=fresh.case_id),
        result(1_000_103, RunOutcome.DEATH, case_id=fresh.case_id),
    ]
    acceptance = evaluate_acceptance(
        sample, results, development_model=False, inputs_unchanged=True
    )
    assert acceptance.checks["fresh:min_success_rate"]
    assert not acceptance.checks["fresh:death:sum:at_most"]
    assert not acceptance.passed


def test_draw_snapshot_reproduces_after_ledger_changes(tmp_path: Path) -> None:
    from nethack_agent.seed_catalog import used_seeds

    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload["fresh_sample"]["range"] = [1, 1000]
    suite = load_suite(write_suite(tmp_path, payload))
    draw = evaluation._fresh_draw(suite, 19)
    assert set(draw.excluded_seeds) == used_seeds(tmp_path) & set(range(1, 1001))
    assert not set(draw.drawn_seeds) & used_seeds(tmp_path)
    ledger_path = tmp_path / "seed-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"].append(
        {
            "source": "later-probe",
            "seeds": [draw.drawn_seeds[0]],
            "ranges": [],
            "note": "Recorded after the first draw.",
        }
    )
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert evaluation.DrawProvenance.from_json(draw.to_json()) == draw
    assert draw.drawn_seeds[0] not in evaluation._fresh_draw(suite, 19).drawn_seeds
    changed = draw.to_json()
    changed["drawn_seeds"][0] = draw.excluded_seeds[0]
    with pytest.raises(ContractError, match="do not reproduce"):
        evaluation.DrawProvenance.from_json(changed)


def test_fresh_draw_is_persisted_before_first_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload.pop("baseline")
    payload["fresh_sample"]["count"] = 2
    suite = load_suite(write_suite(tmp_path, payload))
    report_directory = tmp_path / "out"
    observed: list[int] = []

    def inspect_creation(self: RunManager, *, seed: int, **_kwargs: object) -> None:
        paths = list(report_directory.glob("*.json"))
        assert len(paths) == 1
        recorded = json.loads(paths[0].read_text(encoding="utf-8"))
        provenance = evaluation.DrawProvenance.from_json(recorded["draw_provenance"])
        assert recorded["case_results"][0]["results"] or not observed
        assert seed == provenance.drawn_seeds[len(observed)]
        assert recorded["requested_cases"] == [
            {
                "case_id": suite.fresh_sample.case_id,
                "seeds": list(provenance.drawn_seeds),
            }
        ]
        observed.append(seed)
        raise RuntimeError("stop before NLE reset")

    monkeypatch.setattr(RunManager, "create_run", inspect_creation)
    run = run_evaluation(
        EvaluationOptions(
            suite,
            tmp_path / "data",
            report_directory,
            draw_seed=29,
            development_scripted_model=True,
        ),
        progress=None,
    )
    assert tuple(observed) == run.report.draw_provenance.drawn_seeds
    assert len(observed) == 2


def test_baseline_regression_fails_while_fresh_sample_passes(tmp_path: Path) -> None:
    suite = schema_3_suite(tmp_path)
    draw = evaluation._fresh_draw(suite, 13)
    fresh = suite.fresh_sample
    assert fresh is not None
    suite = replace(
        suite,
        cases=suite.cases
        + (
            evaluation.EvaluationCase(
                fresh.case_id,
                fresh.task,
                draw.drawn_seeds,
                fresh.max_episode_steps,
                evaluation.CaseAcceptance(0, ()),
            ),
        ),
    )
    results = [
        result(6, RunOutcome.DEATH, case_id="staircase-anchor-6"),
        result(701, RunOutcome.TRUNCATED, case_id="descend-d3-hidden-downstairs-701"),
        *(
            result(seed, RunOutcome.TASK_SUCCESS, case_id=fresh.case_id)
            for seed in draw.drawn_seeds
        ),
    ]
    previous = EvaluationReport(
        suite,
        "ollama",
        "gemma4-nethack:latest",
        suite.policy_version,
        "staircase-reviewed-v3+sha256:test",
        8192,
        (6, 701, *draw.drawn_seeds),
        str(tmp_path),
        "2026-09-30T00:00:00+00:00",
        results=[
            result(6, RunOutcome.TASK_SUCCESS, case_id="staircase-anchor-6"),
            result(701, RunOutcome.DEATH, case_id="descend-d3-hidden-downstairs-701"),
        ],
        draw_provenance=draw,
    )
    report = replace(previous, results=results, comparison_source=previous.to_json())
    acceptance = report.acceptance()
    assert not acceptance.checks["baseline:staircase-anchor-6"]
    assert acceptance.checks["baseline:descend-d3-hidden-downstairs-701"]
    assert acceptance.checks["fresh:min_success_rate"]
    assert not acceptance.passed
    comparison = report.to_json()["comparison"]["entries"]
    assert comparison[0]["change"] == "regressed"
    assert comparison[1]["change"] == "outcome_changed"


def test_baseline_does_not_accept_another_seed_under_its_case_id(
    tmp_path: Path,
) -> None:
    suite = schema_3_suite(tmp_path)
    payload = json.loads(suite.path.read_text(encoding="utf-8"))
    payload.pop("fresh_sample")
    suite = load_suite(write_suite(tmp_path, payload))
    observed = [
        result(7, RunOutcome.TASK_SUCCESS, case_id="staircase-anchor-6"),
        result(701, RunOutcome.DEATH, case_id="descend-d3-hidden-downstairs-701"),
    ]
    report = EvaluationReport(
        suite,
        "ollama",
        "gemma4-nethack:latest",
        suite.policy_version,
        "staircase-reviewed-v3+sha256:test",
        8192,
        (6, 701),
        str(tmp_path),
        "2026-09-30T00:00:00+00:00",
        results=observed,
    )
    assert not report.acceptance().checks["baseline:staircase-anchor-6"]
    assert not report.to_json()["baseline"]["passed"]


def test_all_committed_reports_render_without_changes() -> None:
    reports = sorted(REPORT_DIRECTORY.glob("*.json"))
    assert reports
    for path in reports:
        original = path.with_suffix(".md").read_bytes()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert render_report_markdown(payload).encode("utf-8") == original, path


def diagnostic_metrics(
    *,
    hunger: HungerState | None = HungerState.FAINTING,
    search_steps: int = 1,
) -> EpisodeMetrics:
    return replace(
        EpisodeMetrics.empty(),
        steps=2,
        steps_by_skill=((Skill.EXPLORE_LEVEL, 2),),
        search_steps=search_steps,
        first_hungry_turn=12,
        hunger_at_death=hunger,
    )


def test_failure_diagnostics_use_executed_actions_and_last_live_hunger() -> None:
    level = LevelKey(0, 1)
    initial = synthetic_observation(0, level, 2, hunger=1)
    hungry = synthetic_observation(1, level, 3, hunger=2)
    weak = synthetic_observation(2, level, 4, hunger=3)
    terminal = synthetic_observation(3, None, 0, hunger=6)
    search = LegalAction(0, ord("s"), "Command.SEARCH")
    steps = (
        replace(synthetic_step(hungry), action=search),
        replace(
            synthetic_step(weak),
            selection=replace(
                synthetic_step(weak).selection,
                skill=Skill.STAIRCASE_NAVIGATION,
                source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            ),
        ),
        replace(
            synthetic_step(terminal, RunOutcome.DEATH),
            action=search,
            selection=replace(
                synthetic_step(terminal, RunOutcome.DEATH).selection,
                skill=Skill.HUNGER,
                source=ActionSelectionSource.MODEL_FALLBACK,
            ),
            action_decision=ActionDecision(
                (ActionCandidate(0, 1.0, "Search"),), 0, "Search for stairs"
            ),
            action_metrics=DecisionMetrics(100, 10, 1.0, False),
        ),
    )
    metrics = evaluation._episode_metrics(
        initial, steps, STAIRCASE_TASK, RunOutcome.DEATH, None
    )
    assert metrics.steps_by_skill == (
        (Skill.STAIRCASE_NAVIGATION, 1),
        (Skill.EXPLORE_LEVEL, 1),
        (Skill.HUNGER, 1),
    )
    assert metrics.search_steps == 2
    assert metrics.first_hungry_turn == hungry.player.turn
    assert metrics.hunger_at_death is HungerState.WEAK
    assert EpisodeMetrics.from_json(metrics.to_json()) == metrics

    truncated = evaluation._episode_metrics(
        initial, steps, STAIRCASE_TASK, RunOutcome.TRUNCATED, None
    )
    assert truncated.hunger_at_death is None
    no_live = evaluation._episode_metrics(
        None, (steps[-1],), STAIRCASE_TASK, RunOutcome.DEATH, None
    )
    assert no_live.first_hungry_turn is None
    assert no_live.hunger_at_death is None
    assert no_live.steps_by_skill == ((Skill.HUNGER, 1),)
    starts_weak = evaluation._episode_metrics(
        replace(initial, player=replace(initial.player, hunger=3)),
        (),
        STAIRCASE_TASK,
        RunOutcome.TRUNCATED,
        None,
    )
    assert starts_weak.first_hungry_turn == initial.player.turn
    assert starts_weak.steps_by_skill == ()
    assert starts_weak.search_steps == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps_by_skill", {"unrecognized": 2}),
        ("steps_by_skill", {"explore_level": -1}),
        ("steps_by_skill", {"explore_level": 1}),
        ("search_steps", 3),
        ("first_hungry_turn", True),
        ("hunger_at_death", "unrecognized"),
    ],
)
def test_failure_diagnostic_contract_rejects_invalid_values(
    field: str, value: object
) -> None:
    stored = diagnostic_metrics().to_json()
    stored[field] = value
    with pytest.raises(ContractError):
        EpisodeMetrics.from_json(stored)


@pytest.mark.parametrize(
    "field", ["steps_by_skill", "search_steps", "first_hungry_turn", "hunger_at_death"]
)
def test_failure_diagnostic_fields_must_appear_together(field: str) -> None:
    stored = diagnostic_metrics().to_json()
    del stored[field]
    with pytest.raises(ContractError, match="recorded together"):
        EpisodeMetrics.from_json(stored)


def test_hunger_at_death_threshold_gates_weak_deaths_and_missing_evidence(
    tmp_path: Path,
) -> None:
    suite = threshold_suite(
        tmp_path, [metric_threshold("hunger_at_death", "maximum", "at_most", 2)]
    )
    results = [
        result(
            1, RunOutcome.DEATH, metrics=diagnostic_metrics(hunger=HungerState.HUNGRY)
        ),
        result(2, RunOutcome.TRUNCATED, metrics=diagnostic_metrics(hunger=None)),
    ]
    check = "staircase:hunger_at_death:maximum:at_most"
    assert evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    ).checks[check]
    results[0] = replace(
        results[0], metrics=diagnostic_metrics(hunger=HungerState.FAINTING)
    )
    assert not evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    ).checks[check]
    results[0] = replace(results[0], metrics=diagnostic_metrics(hunger=None))
    assert not evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    ).checks[check]
    results[0] = replace(results[0], metrics=EpisodeMetrics.empty())
    assert not evaluate_acceptance(
        suite, results, development_model=False, inputs_unchanged=True
    ).checks[check]


def test_schema_four_failure_diagnostics_render_without_changing_old_reports(
    tmp_path: Path,
) -> None:
    payload = suite_2_payload()
    payload["schema_version"] = 3
    payload["policy_version"] = run_manager.POLICY_VERSION
    payload["knowledge_bundle_id"] = "staircase-reviewed-v3"
    suite = load_suite(write_suite(tmp_path, payload))
    case = suite.cases[0]
    recorded = diagnostic_metrics()
    report = EvaluationReport(
        suite,
        "ollama",
        "gemma4-nethack:latest",
        suite.policy_version,
        "staircase-reviewed-v3+sha256:test",
        8192,
        suite.seeds,
        str(tmp_path),
        "2026-10-02T00:00:00+00:00",
        results=[
            result(
                case.seeds[0],
                RunOutcome.DEATH,
                case_id=case.case_id,
                steps=2,
                metrics=recorded,
            )
        ],
    )
    markdown = report.to_markdown()
    assert markdown == render_report_markdown(json.loads(json.dumps(report.to_json())))
    assert "## Failure diagnostics" in markdown
    assert "| 1 | explore_level: 2 | 1 | 12 | fainting |" in markdown
    report.results[0] = replace(
        report.results[0], steps=0, metrics=EpisodeMetrics.empty()
    )
    assert "## Failure diagnostics" not in report.to_markdown()
    report.results.append(
        result(
            case.seeds[1],
            RunOutcome.DEATH,
            case_id=case.case_id,
            steps=2,
            metrics=recorded,
        )
    )
    with pytest.raises(ContractError, match="all record failure diagnostics"):
        report.to_markdown()


def test_location_metrics_sum_turns_across_revisits_and_preserve_missing_evidence() -> (
    None
):
    first, second = LevelKey(0, 1), LevelKey(2, 1)
    initial = replace(synthetic_observation(0, first, 3, 1), cell_descriptions=())
    observations = [
        replace(
            synthetic_observation(1, first, 3, 1),
            player=replace(initial.player, turn=10),
        ),
        replace(
            synthetic_observation(2, second, 3, 1),
            player=replace(
                initial.player, dungeon_number=2, dungeon_level=1, depth=3, turn=14
            ),
        ),
        replace(
            synthetic_observation(3, first, 3, 1),
            player=replace(initial.player, turn=20),
        ),
        replace(
            synthetic_observation(4, first, 3, 1),
            player=replace(initial.player, turn=23),
        ),
    ]
    wait = LegalAction(0, ord("."), "MiscDirection.WAIT")
    steps = tuple(
        replace(synthetic_step(observation), action=wait)
        for observation in observations
    )
    metrics = evaluation._episode_metrics(
        initial, steps, STAIRCASE_TASK, RunOutcome.TRUNCATED, None
    )
    assert dict(metrics.turns_per_level) == {first: 17 - initial.player.turn, second: 6}
    assert metrics.max_depth_by_branch == ((0, 1, initial.player.depth), (2, 1, 3))
    assert metrics.oracle_attacks == 0
    legacy = evaluation._episode_metrics(
        replace(initial, cell_descriptions=None),
        steps,
        STAIRCASE_TASK,
        RunOutcome.TRUNCATED,
        None,
    )
    assert legacy.oracle_attacks is None
    assert "oracle_attacks" not in legacy.to_json()


def test_corpse_route_accepts_untracked_lichen_despite_consumed_kill_same_cell() -> (
    None
):
    """A lichen needs no kill turn; a stale consumed kill on its cell must not block it."""
    level = LevelKey(0, 1)
    before = synthetic_observation(2, level, 1, hunger=1)
    lichen_index = next(
        i for i in range(nethack.NUMMONS) if nethack.permonst(i).mname == "lichen"
    )
    body = list(before.map.glyph_rows[0])
    body[1] = nethack.GLYPH_BODY_OFF + lichen_index
    before = replace(
        before,
        map=replace(
            before.map,
            rows=(" %   ", "     "),
            glyph_rows=(tuple(body), before.map.glyph_rows[1]),
        ),
    )
    evidence = CorpseEvidence("lichen", None, None, MapCell(1, 0))
    # An earlier, unrelated goblin kill on this exact cell was already eaten
    # and consumed; the untracked lichen route must not be rejected because
    # of it.
    stale_kill = CorpseKill("goblin", 2, level, evidence.cell)
    history = {(level, 1, 0): stale_kill}
    after = replace(
        synthetic_observation(3, level, 1, hunger=1),
        player=replace(before.player, x=1, turn=4),
        message="You see here a lichen corpse.",
    )
    base = synthetic_step(after)
    step = replace(
        base,
        selection=replace(
            base.selection,
            skill=Skill.CORPSE,
            intent=ActionIntent(
                IntentDestination(DestinationKind.CORPSE, 1, 0),
                None,
                (MapCell(1, 0),),
                level,
                corpse=evidence,
            ),
        ),
    )
    memory = evaluation.DungeonMemory()
    memory.observe(before)
    profile = ActionProfile.NLE_SURVIVAL_ACTIONS
    assert evaluation._action_is_valid(
        step,
        (_EAST,),
        before,
        True,
        profile,
        corpse_kills=history,
        consumed_corpses={(level, 1, 0, 2)},
        dungeon_memory=memory,
    )
