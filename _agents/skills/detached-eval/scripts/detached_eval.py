#!/usr/bin/env python3
"""Run evaluation commands in detached sessions and persist their outcomes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/detached-eval")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _paths(directory: Path, name: str) -> tuple[Path, Path, Path, Path]:
    return (
        directory / f"{name}.pid",
        directory / f"{name}.json",
        directory / f"{name}.log",
        directory / f"{name}.done",
    )


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tail(log: Path) -> str:
    try:
        return "\n".join(
            log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        )
    except FileNotFoundError:
        return ""


def _status(directory: Path, name: str) -> int:
    pid_file, info_file, log, done = _paths(directory, name)
    try:
        json.loads(info_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"{name}: not found", file=sys.stderr)
        return 2
    if done.exists():
        result = json.loads(done.read_text(encoding="utf-8"))
        print(f"{name}: finished (exit {result['exit_code']})")
    else:
        try:
            pid = int(pid_file.read_text(encoding="ascii"))
        except (FileNotFoundError, ValueError):
            pid = -1
        if pid > 0 and _running(pid):
            print(f"{name}: running (pid {pid})")
        else:
            print(f"{name}: finished (completion marker missing)")
    tail = _tail(log)
    if tail:
        print(tail)
    return 0


def _valid_name(name: str) -> bool:
    return bool(name) and all(char.isalnum() or char in "-_" for char in name)


def _start(args: argparse.Namespace) -> int:
    if not args.command:
        raise ValueError("start requires a command after --")
    if not _valid_name(args.name):
        raise ValueError(
            "name may contain only letters, digits, hyphens, and underscores"
        )
    directory = args.state_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    pid_file, info_file, log_file, done_file = _paths(directory, args.name)
    if pid_file.exists() and not done_file.exists():
        try:
            old_pid = int(pid_file.read_text(encoding="ascii"))
        except ValueError:
            old_pid = -1
        if old_pid > 0 and _running(old_pid):
            raise ValueError(f"name {args.name!r} is already running (pid {old_pid})")
    cwd = args.cwd.resolve(strict=True)
    head = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    git_head = head.stdout.strip() if head.returncode == 0 else None
    done_file.unlink(missing_ok=True)
    info_file.write_text(
        json.dumps(
            {
                "command": args.command,
                "cwd": str(cwd),
                "started_at": _now(),
                "git_head": git_head,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    wrapper = (
        "import json,subprocess,sys; from datetime import datetime,timezone; "
        "p=subprocess.run(sys.argv[2:],stdin=subprocess.DEVNULL); "
        "open(sys.argv[1],'w').write(json.dumps({'exit_code':p.returncode,"
        "'ended_at':datetime.now(timezone.utc).isoformat()})+'\\n'); "
        "sys.exit(p.returncode)"
    )
    with log_file.open("wb") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", wrapper, str(done_file), *args.command],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    pid_file.write_text(f"{process.pid}\n", encoding="ascii")
    print(f"{args.name}: started (pid {process.pid})")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start")
    start.add_argument("--name", required=True)
    start.add_argument("--cwd", type=Path, default=Path("nethack-agent"))
    start.add_argument("command", nargs=argparse.REMAINDER)
    status = sub.add_parser("status")
    status.add_argument("name")
    wait = sub.add_parser("wait")
    wait.add_argument("name")
    wait.add_argument("--poll", type=float, default=2.0)
    sub.add_parser("list")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            args.command = (
                args.command[1:] if args.command[:1] == ["--"] else args.command
            )
            return _start(args)
        directory = args.state_dir.expanduser().resolve()
        if args.action == "status":
            return _status(directory, args.name)
        if args.action == "wait":
            if args.poll <= 0:
                raise ValueError("--poll must be positive")
            while not _paths(directory, args.name)[3].exists():
                _status(directory, args.name)
                time.sleep(args.poll)
            result = json.loads(
                _paths(directory, args.name)[3].read_text(encoding="utf-8")
            )
            print(f"{args.name}: exit {result['exit_code']}")
            tail = _tail(_paths(directory, args.name)[2])
            if tail:
                print(tail)
            return int(result["exit_code"])
        directory.mkdir(parents=True, exist_ok=True)
        for info in sorted(directory.glob("*.json")):
            state = (
                "finished" if _paths(directory, info.stem)[3].exists() else "running"
            )
            print(f"{info.stem}: {state}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"detached-eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
