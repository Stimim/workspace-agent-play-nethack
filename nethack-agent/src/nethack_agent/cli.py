from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from nethack_agent.api import create_app
from nethack_agent.control_client import ControlClient, ControlClientError
from nethack_agent.coordinator import AgentCoordinator
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.model import DecisionFailure, OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError
from nethack_agent.run_manager import RunManager


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
                OllamaDecisionModel(OllamaClient(config)),
            )
            coordinator.start()
            record = coordinator.advance(single_step=True)
            if record is None:
                raise CheckFailure("coordinator discarded the model decision")
            coordinator.stop()
            if len(coordinator.ttyrec_files) != 1:
                raise CheckFailure("agent smoke did not finalize exactly one ttyrec")
            decision = record.decision
            return (
                f"model chose {record.action.index} ({record.action.name}) for "
                f"goal {decision.decision.goal!r}; "
                f"{decision.metrics.prompt_tokens} prompt tokens, "
                f"{decision.metrics.output_tokens} output tokens, "
                f"{decision.metrics.latency_ms:.0f} ms"
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
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--data-dir", type=Path, default=Path("data"))

    run_parser = subparsers.add_parser("run", help="control a running local service")
    run_commands = run_parser.add_subparsers(dest="run_command", required=True)
    start_parser = run_commands.add_parser("start")
    start_parser.add_argument("--seed", type=int, required=True)
    start_parser.add_argument("--max-steps", type=int, default=5_000)
    start_parser.add_argument("--auto", action="store_true")
    for operation in ("status", "pause", "resume", "step", "stop", "events"):
        operation_parser = run_commands.add_parser(operation)
        operation_parser.add_argument("run_id")
        if operation == "events":
            operation_parser.add_argument("--after", type=int, default=-1)
            operation_parser.add_argument("--limit", type=int, default=100)
    return parser


def _run_control_command(arguments: argparse.Namespace) -> int:
    try:
        client = ControlClient.from_environment()
        if arguments.run_command == "start":
            response = client.create_run(
                seed=arguments.seed,
                max_episode_steps=arguments.max_steps,
                auto_start=arguments.auto,
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


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "run":
        return _run_control_command(arguments)
    if arguments.command == "smoke" and arguments.target == "nle":
        return 0 if _run_check("nle", smoke_nle) else 1

    try:
        config = OllamaConfig.from_environment()
    except OllamaError as error:
        print(f"FAIL configuration: {error}", file=sys.stderr)
        return 1

    if arguments.command == "serve":
        import uvicorn

        manager = RunManager(arguments.data_dir, config)
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
