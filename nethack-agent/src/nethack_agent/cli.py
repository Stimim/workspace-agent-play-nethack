from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

from nethack_agent.api import create_app
from nethack_agent.contracts import ContractError
from nethack_agent.control_client import ControlClient, ControlClientError
from nethack_agent.coordinator import AgentCoordinator
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.evaluation import (
    EvaluationOptions,
    finalize_aborted_report,
    load_suite,
    run_evaluation,
)
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import (
    DecisionFailure,
    OllamaDecisionModel,
    ScriptedDevelopmentModel,
)
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError
from nethack_agent.run_manager import RunManager
from nethack_agent.scenario import ScenarioRunConfig, run_scenario
from nethack_agent.seed_catalog import (
    DEFAULT_CATALOG_PATH,
    CatalogCheckStatus,
    load_catalog,
    render_catalog_markdown,
    run_catalog_check,
)
from nethack_agent.tasks import TaskSpec, load_task_file
from nethack_agent.verification import verify_network_boundary


class CheckFailure(RuntimeError):
    """A diagnostic check could not prove its runtime path works."""


def smoke_ollama(config: OllamaConfig) -> str:
    try:
        client = OllamaClient(config)
        generation = client.generate(
            "Reply with the single word OK.",
            max_tokens=16,
        )
    except OllamaError as error:
        raise CheckFailure(str(error)) from error
    return (
        f"Ollama {client.version}; model {config.model}; "
        f"local generation completed ({generation.output_tokens} output tokens)"
    )


def smoke_nle() -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="nethack-agent-smoke-") as directory:
            environment = NleEnvironment(
                ScenarioConfig(
                    seed=6,
                    artifact_directory=Path(directory),
                    max_episode_steps=10,
                )
            )
            with environment:
                observation = environment.reset()
                transition = environment.step(0)
                rows, columns = observation.chars.shape
                action_count = len(environment.legal_actions)
                seed_set = environment.seed_set
                if transition.step_index != 1:
                    raise CheckFailure("NLE adapter did not advance one step")
            ttyrec_count = len(environment.ttyrec_files)
            if ttyrec_count != 1:
                raise CheckFailure(
                    f"NLE adapter produced {ttyrec_count} ttyrecs instead of one"
                )
    except CheckFailure:
        raise
    except Exception as error:
        raise CheckFailure(f"NLE environment smoke failed: {error}") from error
    return (
        "NLE Staircase reset and step completed; "
        f"map {columns}x{rows}; {action_count} legal action indices; "
        f"RNG seeds {seed_set.core}/{seed_set.display}/{seed_set.level}; "
        "one ttyrec finalized"
    )


def smoke_agent(config: OllamaConfig) -> str:
    coordinator: AgentCoordinator | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="nethack-agent-model-") as directory:
            environment = NleEnvironment(
                ScenarioConfig(
                    seed=6,
                    artifact_directory=Path(directory),
                    max_episode_steps=10,
                )
            )
            coordinator = AgentCoordinator(
                environment,
                ObservationProjector(),
                OllamaDecisionModel(
                    OllamaClient(config), load_default_knowledge_bundle()
                ),
            )
            coordinator.start()
            record = coordinator.advance(single_step=True)
            if record is None:
                raise CheckFailure("coordinator discarded the model decision")
            coordinator.stop()
            if len(coordinator.ttyrec_files) != 1:
                raise CheckFailure("agent smoke did not finalize exactly one ttyrec")
            decisions = [
                item
                for item in (
                    record.skill_model_decision,
                    record.action_model_decision,
                )
                if item is not None
            ]
            prompt_tokens = sum(item.metrics.prompt_tokens for item in decisions)
            output_tokens = sum(item.metrics.output_tokens for item in decisions)
            latency_ms = sum(item.metrics.latency_ms for item in decisions)
            return (
                f"{record.selection.source.value} chose {record.action.index} "
                f"({record.action.name}) for goal {record.goal.token!r} with "
                f"skill {record.skill.value!r}; {prompt_tokens} prompt tokens, "
                f"{output_tokens} output tokens, {latency_ms:.0f} ms"
            )
    except (DecisionFailure, OllamaError) as error:
        raise CheckFailure(str(error)) from error
    except CheckFailure:
        raise
    except Exception as error:
        raise CheckFailure(f"agent smoke failed: {error}") from error
    finally:
        if coordinator is not None:
            coordinator.stop()


def _run_check(name: str, check: Any) -> bool:
    try:
        detail = check()
    except CheckFailure as error:
        print(f"FAIL {name}: {error}", file=sys.stderr)
        return False
    print(f"OK   {name}: {detail}")
    return True


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65_535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _seed_list(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be comma-separated integers") from error
    if not seeds or any(seed <= 0 for seed in seeds):
        raise argparse.ArgumentTypeError("seeds must be positive integers")
    return seeds


def _task_file(value: str) -> TaskSpec:
    try:
        return load_task_file(Path(value))
    except (OSError, ContractError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nethack-agent", description="NetHack agent developer diagnostics"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="check NLE and local Ollama end to end")
    smoke_parser = subparsers.add_parser("smoke", help="run one integration check")
    smoke_parser.add_argument("target", choices=("nle", "ollama", "agent"))

    serve_parser = subparsers.add_parser("serve", help="run the loopback control API")
    serve_parser.add_argument(
        "--host", choices=(("127.0.0.1", "localhost", "::1")), default="127.0.0.1"
    )
    serve_parser.add_argument("--port", type=_port, default=8000)
    serve_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    serve_parser.add_argument(
        "--development-scripted-model",
        action="store_true",
        help="use the deterministic no-Ollama model for explicit development",
    )

    run_parser = subparsers.add_parser("run", help="control a running local service")
    run_commands = run_parser.add_subparsers(dest="run_command", required=True)
    start_parser = run_commands.add_parser("start")
    start_parser.add_argument("--seed", type=int, required=True)
    start_parser.add_argument("--max-steps", type=int, default=5_000)
    start_parser.add_argument("--auto", action="store_true")
    start_parser.add_argument(
        "--task",
        type=_task_file,
        help="TaskSpec JSON file (default: the staircase task)",
    )
    for operation in ("status", "pause", "resume", "step", "stop", "events"):
        operation_parser = run_commands.add_parser(operation)
        operation_parser.add_argument("run_id")
        if operation == "events":
            operation_parser.add_argument("--after", type=int, default=-1)
            operation_parser.add_argument("--limit", type=int, default=100)

    scenario_parser = subparsers.add_parser(
        "scenario", help="run a scenario in a managed local service"
    )
    scenario_commands = scenario_parser.add_subparsers(
        dest="scenario_command", required=True
    )
    scenario_run_parser = scenario_commands.add_parser(
        "run", help="launch, drive, and reap a local scenario service"
    )
    scenario_run_parser.add_argument("--seed", type=_positive_int, required=True)
    scenario_run_parser.add_argument("--max-steps", type=_positive_int, default=5_000)
    scenario_run_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    scenario_run_parser.add_argument(
        "--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1"
    )
    scenario_run_parser.add_argument("--port", type=_port, default=8000)
    scenario_run_parser.add_argument("--timeout", type=_positive_float, default=300.0)
    scenario_mode = scenario_run_parser.add_mutually_exclusive_group(required=True)
    scenario_mode.add_argument("--auto", action="store_true")
    scenario_mode.add_argument("--steps", type=_positive_int)
    scenario_run_parser.add_argument("--json", action="store_true")
    scenario_run_parser.add_argument(
        "--task",
        type=_task_file,
        help="TaskSpec JSON file (default: the staircase task)",
    )
    scenario_run_parser.add_argument(
        "--development-scripted-model",
        action="store_true",
        help="use the deterministic no-Ollama model for explicit development",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="run executable boundary verification"
    )
    verify_commands = verify_parser.add_subparsers(dest="verify_command", required=True)
    network_parser = verify_commands.add_parser(
        "network", help="prove runtime socket destinations stay on loopback"
    )
    network_parser.add_argument("--data-dir", type=Path)
    network_parser.add_argument("--timeout", type=_positive_float, default=10.0)
    network_parser.add_argument("--json", action="store_true")

    eval_parser = subparsers.add_parser(
        "eval", help="run or finalize a committed evaluation suite"
    )
    eval_commands = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_commands.add_parser(
        "run", help="run suite seeds through the run manager and write a report"
    )
    eval_run_parser.add_argument("--suite", type=Path, required=True)
    eval_run_parser.add_argument("--data-dir", type=Path, required=True)
    eval_run_parser.add_argument(
        "--report-dir", type=Path, help="report directory (default: DATA_DIR/reports)"
    )
    eval_run_parser.add_argument(
        "--seeds",
        type=_seed_list,
        help="comma-separated execution order; a subset yields a partial report",
    )
    eval_run_parser.add_argument(
        "--draw-seed",
        type=_nonnegative_int,
        help="reproduce a fresh_sample seed draw (default: random at run start)",
    )
    eval_run_parser.add_argument(
        "--compare-report",
        type=Path,
        help="prior report of the same suite for a paired baseline comparison",
    )
    eval_run_parser.add_argument(
        "--progress-interval", type=_positive_float, default=30.0
    )
    eval_run_parser.add_argument("--json", action="store_true")
    eval_run_parser.add_argument(
        "--development-scripted-model",
        action="store_true",
        help="use the deterministic no-Ollama model; never valid milestone evidence",
    )
    eval_abort_parser = eval_commands.add_parser(
        "abort",
        help="mark an unfinished report pair operator-aborted, keeping its results",
    )
    eval_abort_parser.add_argument(
        "--report", type=Path, required=True, help="report JSON path"
    )
    eval_abort_parser.add_argument("--reason", required=True)
    catalog_parser = eval_commands.add_parser(
        "catalog", help="render or check the representative-seed catalog"
    )
    catalog_commands = catalog_parser.add_subparsers(
        dest="catalog_command", required=True
    )
    for name, text in (
        ("render", "write the catalog Markdown from its JSON"),
        ("check", "run every entry with the scripted development model"),
    ):
        command_parser = catalog_commands.add_parser(name, help=text)
        command_parser.add_argument(
            "--catalog", type=Path, default=DEFAULT_CATALOG_PATH
        )
        if name == "check":
            command_parser.add_argument("--data-dir", type=Path, required=True)
            command_parser.add_argument(
                "--report-dir",
                type=Path,
                help="report directory (default: DATA_DIR/reports)",
            )
            command_parser.add_argument("--json", action="store_true")
    return parser


def _run_control_command(arguments: argparse.Namespace) -> int:
    try:
        client = ControlClient.from_environment()
        if arguments.run_command == "start":
            response = client.create_run(
                seed=arguments.seed,
                max_episode_steps=arguments.max_steps,
                auto_start=arguments.auto,
                task=arguments.task,
            )
        elif arguments.run_command == "status":
            response = client.status(arguments.run_id)
        elif arguments.run_command == "events":
            response = client.events(
                arguments.run_id, after=arguments.after, limit=arguments.limit
            )
        else:
            response = client.control(arguments.run_id, arguments.run_command)
    except (ControlClientError, ValueError) as error:
        print(f"FAIL control API: {error}", file=sys.stderr)
        return 1
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


def _run_scenario_command(arguments: argparse.Namespace) -> int:
    try:
        result = run_scenario(
            ScenarioRunConfig(
                seed=arguments.seed,
                max_episode_steps=arguments.max_steps,
                data_directory=arguments.data_dir,
                host=arguments.host,
                port=arguments.port,
                timeout_seconds=arguments.timeout,
                auto_run=arguments.auto,
                steps=arguments.steps,
                development_scripted_model=arguments.development_scripted_model,
                task=arguments.task,
            )
        )
    except KeyboardInterrupt:
        if arguments.json:
            print(json.dumps({"error": "scenario interrupted", "status": "error"}))
        else:
            print("FAIL scenario: interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "status": "error",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"FAIL scenario: {error}", file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        print(
            f"OK scenario {result.run_id}: execution "
            f"{result.execution_state.value}; final "
            f"{ControlClient.status_state(result.final_status).value}; "
            f"{len(result.events)} events; service {result.service_pid} reaped "
            f"with code {result.service_return_code}"
        )
    return 0


def _run_network_verification(arguments: argparse.Namespace) -> int:
    try:
        result = verify_network_boundary(
            data_directory=arguments.data_dir,
            timeout_seconds=arguments.timeout,
        )
    except Exception as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "status": "error",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"FAIL network verification: {error}", file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        print(
            f"OK network: {len(result.destinations)} loopback destinations; "
            f"proxy bypass verified; run {result.run_id} stopped"
        )
    return 0


def _run_evaluation_command(arguments: argparse.Namespace) -> int:
    try:
        suite = load_suite(arguments.suite)
        options = EvaluationOptions(
            suite=suite,
            data_directory=arguments.data_dir,
            report_directory=arguments.report_dir or arguments.data_dir / "reports",
            seeds=arguments.seeds,
            draw_seed=arguments.draw_seed,
            compare_report=arguments.compare_report,
            development_scripted_model=arguments.development_scripted_model,
            progress_interval_seconds=arguments.progress_interval,
        )
        run = run_evaluation(options)
    except KeyboardInterrupt:
        print(
            "FAIL evaluation: interrupted before a report was written", file=sys.stderr
        )
        return 130
    except Exception as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "status": "error",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"FAIL evaluation: {error}", file=sys.stderr)
        return 1
    report = run.report.to_json()
    if arguments.json:
        print(
            json.dumps(
                {
                    "report": report,
                    "report_paths": {
                        "json": str(run.paths.json),
                        "markdown": str(run.paths.markdown),
                    },
                },
                sort_keys=True,
            )
        )
    else:
        acceptance = run.report.acceptance()
        aggregate = run.report.aggregate_json()
        episode_count = sum(len(case.seeds) for case in run.report.suite.cases)
        print(
            f"{'PASS' if acceptance.passed else 'FAIL'} evaluation "
            f"{run.report.suite.suite_id} ({run.report.status.value}): "
            f"{aggregate['task_successes']}/{episode_count} task "
            f"successes; report {run.paths.json}"
        )
        for reason in acceptance.reasons:
            print(f"  - {reason}")
        if suite.schema_version == 3:
            baseline = report["baseline"]
            fresh = report["fresh"]
            print(f"  baseline: {'PASS' if baseline['passed'] else 'FAIL'}")
            if fresh is not None:
                fresh_status = "PASS" if fresh["acceptance"]["passed"] else "FAIL"
                print(
                    f"  fresh sample: {fresh_status} "
                    f"({fresh['successes']}/{fresh['sample_size']})"
                )
            comparison = report["comparison"]
            if comparison is not None:
                print("  paired baseline diff:")
                for entry in comparison["entries"]:
                    print(
                        f"    {entry['entry_id']} seed {entry['seed']}: "
                        f"{entry['prior_outcome'] or '-'} "
                        f"({'yes' if entry['prior_successful'] else 'no'}) -> "
                        f"{entry['current_outcome'] or '-'} "
                        f"({'yes' if entry['current_successful'] else 'no'}); "
                        f"{entry['change']}"
                    )
    return 130 if run.interrupted else 0


def _abort_evaluation_command(arguments: argparse.Namespace) -> int:
    try:
        paths = finalize_aborted_report(arguments.report, arguments.reason)
    except Exception as error:
        print(f"FAIL evaluation abort: {error}", file=sys.stderr)
        return 1
    print(f"OK evaluation report aborted: {paths.json} and {paths.markdown}")
    return 0


def _run_catalog_command(arguments: argparse.Namespace) -> int:
    try:
        catalog = load_catalog(arguments.catalog)
        if arguments.catalog_command == "render":
            markdown_path = arguments.catalog.with_suffix(".md")
            markdown = render_catalog_markdown(catalog)
            markdown_path.write_text(markdown, encoding="utf-8")
            print(f"OK catalog rendered: {markdown_path}")
            return 0
        report_directory = arguments.report_dir or arguments.data_dir / "reports"
        checks, paths = run_catalog_check(catalog, arguments.data_dir, report_directory)
    except KeyboardInterrupt:
        print("FAIL catalog: interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"FAIL catalog: {error}", file=sys.stderr)
        return 1
    failed = sum(check.status is CatalogCheckStatus.FAIL for check in checks)
    changed = (CatalogCheckStatus.IMPROVED, CatalogCheckStatus.CHANGED)
    notices = sum(check.status in changed for check in checks)
    if arguments.json:
        payload = {
            "checks": [check.to_json() for check in checks],
            "failed": failed,
            "to_update": notices,
            "report_paths": {"json": str(paths.json), "markdown": str(paths.markdown)},
        }
        print(json.dumps(payload, sort_keys=True))
        return 1 if failed else 0
    for check in checks:
        observed = check.observed_outcome
        observed_text = "none" if observed is None else observed.value
        print(
            f"{check.status.value.upper()} {check.entry_id} seed {check.seed}: "
            f"expected {check.expectation.value}/{check.expected_outcome.value}, "
            f"observed {observed_text}; {check.detail}"
        )
    verdict = "FAIL" if failed else "PASS"
    print(
        f"{verdict} catalog check: {len(checks)} entries, {failed} failed, "
        f"{notices} to update in the catalog; report {paths.json}"
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "run":
        return _run_control_command(arguments)
    if arguments.command == "scenario":
        return _run_scenario_command(arguments)
    if arguments.command == "verify":
        return _run_network_verification(arguments)
    if arguments.command == "eval" and arguments.eval_command == "catalog":
        return _run_catalog_command(arguments)
    if arguments.command == "eval" and arguments.eval_command == "abort":
        return _abort_evaluation_command(arguments)
    if arguments.command == "eval":
        return _run_evaluation_command(arguments)
    if arguments.command == "smoke" and arguments.target == "nle":
        return 0 if _run_check("nle", smoke_nle) else 1

    if arguments.command == "serve" and arguments.development_scripted_model:
        config = OllamaConfig(model="scripted-development")
    else:
        try:
            config = OllamaConfig.from_environment()
        except OllamaError as error:
            print(f"FAIL configuration: {error}", file=sys.stderr)
            return 1

    if arguments.command == "serve":
        import uvicorn

        model_factory = (
            (lambda _client: ScriptedDevelopmentModel())
            if arguments.development_scripted_model
            else None
        )
        manager = RunManager(arguments.data_dir, config, model_factory=model_factory)
        uvicorn.run(create_app(manager), host=arguments.host, port=arguments.port)
        return 0
    if arguments.command == "smoke":
        checks = {
            "ollama": lambda: smoke_ollama(config),
            "agent": lambda: smoke_agent(config),
        }
        return 0 if _run_check(arguments.target, checks[arguments.target]) else 1

    checks = {
        "nle": smoke_nle,
        "ollama": lambda: smoke_ollama(config),
    }
    successful = True
    for name, check in checks.items():
        successful = _run_check(name, check) and successful
    return 0 if successful else 1
