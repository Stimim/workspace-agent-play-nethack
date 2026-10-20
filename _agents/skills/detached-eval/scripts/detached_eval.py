#!/usr/bin/env python3
"""Run evaluation commands in detached sessions and persist their outcomes."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
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


def _proc(pid: int) -> tuple[str, int, int, int]:
    """Read state, process group, session, and start ticks from Linux procfs."""
    fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return fields[0], int(fields[2]), int(fields[3]), int(fields[19])


def _members(pgid: int) -> list[int]:
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            state, group, _, _ = _proc(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        # Zombies have exited and cannot receive signals; their parent reaps them.
        if group == pgid and state not in ("Z", "X"):
            members.append(int(entry.name))
    return sorted(members)


def _await_group(pgid: int, timeout: float) -> list[int]:
    deadline = time.monotonic() + timeout
    while True:
        survivors = _members(pgid)
        remaining = deadline - time.monotonic()
        if not survivors or remaining <= 0:
            return survivors
        time.sleep(min(0.05, remaining))


def _stop(args: argparse.Namespace) -> int:
    if not math.isfinite(args.timeout) or args.timeout < 0:
        raise ValueError("--timeout must be finite and nonnegative")
    directory = args.state_dir.expanduser().resolve()
    pid_file, info_file, _, done = _paths(directory, args.name)
    if not info_file.exists():
        raise ValueError(f"{args.name}: not found")
    if done.exists():
        print(f"{args.name}: already finished")
        return 0
    info = json.loads(info_file.read_text(encoding="utf-8"))
    pid = int(pid_file.read_text(encoding="ascii"))
    if pid <= 1:
        raise ValueError(f"{args.name}: refusing unsafe pid {pid}")
    try:
        state, proc_pgid, session, ticks = _proc(pid)
        pgid = os.getpgid(pid)
        if state in ("Z", "X"):
            raise ValueError(f"{args.name}: recorded pid is not alive")
        if "start_ticks" in info:
            matches = info["start_ticks"] == ticks and info.get("pid") == pid
        else:
            # Older metadata lacks start ticks. Its detached Python wrapper has
            # the unique absolute completion path followed by the exact command.
            cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
            command = [os.fsdecode(arg) for arg in cmdline.rstrip(b"\0").split(b"\0")]
            matches = (
                len(command) >= 4
                and command[1] == "-c"
                and "p=subprocess.run(sys.argv[2:]" in command[2]
                and command[3:] == [str(done), *info["command"]]
            )
        if not matches:
            raise ValueError(f"{args.name}: PID identity mismatch; refusing to signal")
        if (
            pgid <= 1
            or pgid == os.getpgrp()
            or pgid != pid
            or session != pid
            or proc_pgid != pgid
            or info.get("pgid", pgid) != pgid
        ):
            raise ValueError(f"{args.name}: refusing unsafe process group {pgid}")
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError as error:
        raise ValueError(f"{args.name}: recorded pid is not alive") from error
    survivors = _await_group(pgid, args.timeout)
    exit_code = -signal.SIGTERM
    if survivors and args.force:
        os.killpg(pgid, signal.SIGKILL)
        exit_code = -signal.SIGKILL
        survivors = _await_group(pgid, 5.0)
    if survivors:
        print(
            f"{args.name}: surviving pids in group {pgid}: "
            + ", ".join(map(str, survivors))
            + ("; use --force to SIGKILL" if not args.force else ""),
            file=sys.stderr,
        )
        return 1
    result = (
        json.loads(done.read_text(encoding="utf-8"))
        if done.exists()
        else {"exit_code": exit_code, "ended_at": _now()}
    )
    result["stopped"] = True
    done.write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(f"{args.name}: finished (stopped, exit {result['exit_code']})")
    return 0


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
        stopped = "stopped, " if result.get("stopped") else ""
        print(f"{name}: finished ({stopped}exit {result['exit_code']})")
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
    info = {
        "command": args.command,
        "cwd": str(cwd),
        "started_at": _now(),
        "git_head": git_head,
    }
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
    _, pgid, _, ticks = _proc(process.pid)
    info.update(pid=process.pid, pgid=pgid, start_ticks=ticks)
    info_file.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
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
    stop = sub.add_parser("stop")
    stop.add_argument("name")
    stop.add_argument("--timeout", type=float, default=30.0)
    stop.add_argument("--force", action="store_true")
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
        if args.action == "stop":
            return _stop(args)
        if args.action == "wait":
            if args.poll <= 0:
                raise ValueError("--poll must be positive")
            while not _paths(directory, args.name)[3].exists():
                _status(directory, args.name)
                time.sleep(args.poll)
            result = json.loads(
                _paths(directory, args.name)[3].read_text(encoding="utf-8")
            )
            stopped = "finished (stopped), " if result.get("stopped") else ""
            print(f"{args.name}: {stopped}exit {result['exit_code']}")
            tail = _tail(_paths(directory, args.name)[2])
            if tail:
                print(tail)
            return int(result["exit_code"])
        directory.mkdir(parents=True, exist_ok=True)
        for info in sorted(directory.glob("*.json")):
            done = _paths(directory, info.stem)[3]
            state = "running"
            if done.exists():
                result = json.loads(done.read_text(encoding="utf-8"))
                state = "finished (stopped)" if result.get("stopped") else "finished"
            print(f"{info.stem}: {state}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"detached-eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
