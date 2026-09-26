from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError


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
    smoke_parser.add_argument("target", choices=("nle", "ollama"))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "smoke" and arguments.target == "nle":
        return 0 if _run_check("nle", smoke_nle) else 1

    try:
        config = OllamaConfig.from_environment()
    except OllamaError as error:
        print(f"FAIL configuration: {error}", file=sys.stderr)
        return 1

    if arguments.command == "smoke":
        checks = {
            "ollama": lambda: smoke_ollama(config),
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
