#!/usr/bin/env python3
"""Create a checked Git commit with the active OMP conversation trailer."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TRAILER = re.compile(r"^OMP-Conversation\s*:", re.IGNORECASE)
_MESSAGE_OPTIONS = (
    "-m",
    "--message",
    "-F",
    "--file",
    "-C",
    "-c",
    "--reuse-message",
    "--reedit-message",
    "--fixup",
    "--squash",
    "--trailer",
)


class CommitSkillError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CommitSkillError(
            f"cannot read OMP client evidence {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise CommitSkillError(f"OMP client evidence is not an object: {path}")
    return value


def _command_line(proc_root: Path, pid: int) -> list[str] | None:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise CommitSkillError(f"cannot read active process {pid}: {error}") from error
    try:
        return [part.decode("utf-8") for part in raw.split(b"\0") if part]
    except UnicodeDecodeError as error:
        raise CommitSkillError(
            f"active process {pid} has a non-UTF-8 command line"
        ) from error


def _resume_uuid(command: list[str]) -> str:
    values: list[str] = []
    for index, argument in enumerate(command):
        if argument == "--resume":
            if index + 1 >= len(command):
                raise CommitSkillError("active OMP process has --resume without a UUID")
            values.append(command[index + 1])
        elif argument.startswith("--resume="):
            values.append(argument.partition("=")[2])
    if len(values) != 1 or not _UUID.fullmatch(values[0]):
        raise CommitSkillError(
            "active OMP process does not expose exactly one valid --resume UUID"
        )
    return values[0].lower()


def _validate_session_file(omp_root: Path, repository: Path, conversation: str) -> Path:
    sessions_root = omp_root / "agent" / "sessions"
    matches = sorted(sessions_root.rglob(f"*_{conversation}.jsonl"))
    valid: list[Path] = []
    for path in matches:
        try:
            with path.open(encoding="utf-8") as source:
                session_records = []
                for line_number, line in enumerate(source, start=1):
                    if line_number > 100:
                        break
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get("type") == "session":
                        session_records.append(record)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CommitSkillError(
                f"cannot validate OMP session evidence {path}: {error}"
            ) from error
        if len(session_records) != 1:
            continue
        record = session_records[0]
        try:
            session_cwd = Path(str(record["cwd"])).resolve(strict=True)
        except (KeyError, OSError) as error:
            raise CommitSkillError(f"invalid OMP session cwd in {path}") from error
        if record.get("id") == conversation and session_cwd == repository:
            valid.append(path)
    if not valid:
        raise CommitSkillError(
            "no session file validates active OMP conversation "
            f"{conversation} for {repository}"
        )
    if len(valid) != 1:
        raise CommitSkillError(
            f"ambiguous OMP session evidence for {conversation}: {len(valid)} files"
        )
    return valid[0]


def active_conversation_uuid(repository: Path, omp_root: Path, proc_root: Path) -> str:
    try:
        repository = repository.resolve(strict=True)
    except OSError as error:
        raise CommitSkillError(f"repository does not exist: {repository}") from error
    client_root = omp_root / "run" / "daemons"
    candidates: list[tuple[Path, list[str]]] = []
    for client_file in sorted(client_root.glob("*/clients/*.json")):
        record = _read_json(client_file)
        pid = record.get("pid")
        project_dir = record.get("projectDir")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or not isinstance(project_dir, str)
        ):
            raise CommitSkillError(f"invalid OMP client evidence fields: {client_file}")
        try:
            matches_repository = Path(project_dir).resolve(strict=True) == repository
        except OSError:
            matches_repository = False
        if not matches_repository:
            continue
        command = _command_line(proc_root, pid)
        if command is None or not command or Path(command[0]).name != "omp":
            continue
        candidates.append((client_file, command))
    if not candidates:
        raise CommitSkillError(f"no active OMP client matches repository {repository}")
    if len(candidates) != 1:
        raise CommitSkillError(
            f"ambiguous active OMP clients for {repository}: {len(candidates)} matches"
        )
    conversation = _resume_uuid(candidates[0][1])
    _validate_session_file(omp_root, repository, conversation)
    return conversation


def _run_checks(repository: Path) -> None:
    product = repository / "nethack-agent"
    if not (product / "pyproject.toml").is_file():
        raise CommitSkillError(
            f"missing nethack-agent/pyproject.toml under {repository}"
        )
    uv = shutil.which("uv")
    if uv is None:
        raise CommitSkillError("uv is required for repository checks")
    for command in (
        [uv, "run", "ruff", "check", "."],
        [uv, "run", "ruff", "format", "--check", "."],
    ):
        completed = subprocess.run(command, cwd=product, check=False)
        if completed.returncode:
            raise CommitSkillError(
                f"check failed ({completed.returncode}): {' '.join(command[1:])}"
            )


def _message_with_trailer(message: str, conversation: str) -> str:
    kept = [line for line in message.splitlines() if not _TRAILER.match(line)]
    body = "\n".join(kept).rstrip()
    normalized = (
        f"{body}\n\nOMP-Conversation: {conversation}\n"
        if body
        else (f"OMP-Conversation: {conversation}\n")
    )
    trailers = [line for line in normalized.splitlines() if _TRAILER.match(line)]
    if trailers != [f"OMP-Conversation: {conversation}"]:
        raise CommitSkillError("failed to produce exactly one OMP-Conversation trailer")
    return normalized


def _validate_commit_args(arguments: list[str]) -> list[str]:
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    for argument in arguments:
        if any(
            argument == option or argument.startswith(f"{option}=")
            for option in _MESSAGE_OPTIONS
        ):
            raise CommitSkillError(
                f"message option {argument!r} is not allowed; use --message-file"
            )
    return arguments


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--omp-root", type=Path, default=Path.home() / ".omp")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("resolve")
    subparsers.add_parser("checks")
    commit = subparsers.add_parser("commit")
    commit.add_argument("--message-file", required=True, type=Path)
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("git_arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        repository = arguments.repo.resolve(strict=True)
        if arguments.command == "checks":
            _run_checks(repository)
            return 0
        conversation = active_conversation_uuid(
            repository, arguments.omp_root, arguments.proc_root
        )
        if arguments.command == "resolve":
            print(conversation)
            return 0

        message = arguments.message_file.read_text(encoding="utf-8")
        normalized = _message_with_trailer(message, conversation)
        commit_arguments = _validate_commit_args(arguments.git_arguments)
        _run_checks(repository)
        if arguments.dry_run:
            sys.stdout.write(normalized)
            return 0
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="omp-commit-", delete=False
        ) as message_file:
            message_file.write(normalized)
            temporary_message = Path(message_file.name)
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "commit",
                    *commit_arguments,
                    "-F",
                    str(temporary_message),
                ],
                check=False,
            )
        finally:
            temporary_message.unlink(missing_ok=True)
        if completed.returncode:
            raise CommitSkillError(
                f"git commit failed with status {completed.returncode}"
            )
        return 0
    except (CommitSkillError, OSError, UnicodeError) as error:
        print(f"omp-commit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
