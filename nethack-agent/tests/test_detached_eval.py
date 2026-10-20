import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[2]
    / "_agents"
    / "skills"
    / "detached-eval"
    / "scripts"
    / "detached_eval.py"
)


def _run(state: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--state-dir", str(state), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_done(state: Path, name: str) -> dict[str, object]:
    done = state / f"{name}.done"
    deadline = time.monotonic() + 10
    while not done.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert done.exists()
    return json.loads(done.read_text(encoding="utf-8"))


def test_start_writes_done_marker_and_exit_code(tmp_path: Path) -> None:
    state = tmp_path / "state"
    result = _run(
        state,
        "start",
        "--name",
        "ok",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "print('complete')",
    )
    assert result.returncode == 0, result.stderr
    done = _wait_done(state, "ok")
    assert done["exit_code"] == 0
    assert done["ended_at"]
    assert "complete" in (state / "ok.log").read_text(encoding="utf-8")
    status = _run(state, "status", "ok")
    assert "finished (exit 0)" in status.stdout


def test_wait_returns_failing_command_exit_code(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = _run(
        state,
        "start",
        "--name",
        "fail",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "raise SystemExit(7)",
    )
    assert started.returncode == 0, started.stderr
    done = _wait_done(state, "fail")
    assert done["exit_code"] == 7
    waited = _run(state, "wait", "fail")
    assert waited.returncode == 7
    assert "exit 7" in waited.stdout


def test_refuses_duplicate_running_name(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = _run(
        state,
        "start",
        "--name",
        "busy",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(.4)",
    )
    assert started.returncode == 0, started.stderr
    duplicate = _run(
        state,
        "start",
        "--name",
        "busy",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "pass",
    )
    assert duplicate.returncode != 0
    assert "already running" in duplicate.stderr
    done = _wait_done(state, "busy")
    assert done["exit_code"] == 0


def test_detached_process_survives_starting_parent_exit(tmp_path: Path) -> None:
    state = tmp_path / "state"
    result = _run(
        state,
        "start",
        "--name",
        "orphan",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(.2); print('survived')",
    )
    assert result.returncode == 0, result.stderr
    done = _wait_done(state, "orphan")
    assert done["exit_code"] == 0
    assert "survived" in (state / "orphan.log").read_text(encoding="utf-8")


def test_exit_one_is_preserved_in_done_and_wait(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = _run(
        state,
        "start",
        "--name",
        "exit-one",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "raise SystemExit(1)",
    )
    assert started.returncode == 0, started.stderr

    done = _wait_done(state, "exit-one")
    assert done["exit_code"] == 1
    waited = _run(state, "wait", "exit-one")
    assert waited.returncode == 1
    assert "exit 1" in waited.stdout


def _start_tree(tmp_path: Path, *, ignore_term: bool = False) -> tuple[Path, int]:
    state = tmp_path / "state"
    children = tmp_path / "children.json"
    child_code = (
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(20)"
        if ignore_term
        else "import time; time.sleep(20)"
    )
    code = (
        "import json,subprocess,sys,time; from pathlib import Path; "
        f"children=[subprocess.Popen([sys.executable,'-c',{child_code!r}]) "
        "for _ in range(2)]; "
        # Give the children time to install their signal handlers before readiness.
        "time.sleep(.2); "
        f"Path({str(children)!r}).write_text(json.dumps([p.pid for p in children])); "
        "time.sleep(20)"
    )
    started = _run(
        state,
        "start",
        "--name",
        "tree",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        code,
    )
    assert started.returncode == 0, started.stderr
    info = json.loads((state / "tree.json").read_text())
    pgid = info["pgid"]
    assert pgid == info["pid"]
    deadline = time.monotonic() + 5
    while not children.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert children.exists()
    return state, pgid


def _kill_group(pgid: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] not in ("Z", "X")


def test_stop_kills_spawned_children_and_reports_stopped(tmp_path: Path) -> None:
    state, pgid = _start_tree(tmp_path)
    try:
        children = json.loads((tmp_path / "children.json").read_text())
        assert all(_alive(pid) for pid in children)
        stopped = _run(state, "stop", "tree", "--timeout", "2")
        assert stopped.returncode == 0, stopped.stderr
        assert all(not _alive(pid) for pid in [pgid, *children])
        done = _wait_done(state, "tree")
        assert done["stopped"] is True
        assert done["exit_code"] == -signal.SIGTERM
        assert done["ended_at"]
        assert "finished (stopped" in _run(state, "status", "tree").stdout
        assert "finished (stopped)" in _run(state, "list").stdout
        waited = _run(state, "wait", "tree")
        assert waited.returncode != 0
        assert "finished (stopped)" in waited.stdout
    finally:
        _kill_group(pgid)


def test_stop_finished_run_is_noop(tmp_path: Path) -> None:
    state = tmp_path / "state"
    started = _run(
        state,
        "start",
        "--name",
        "done",
        "--cwd",
        str(tmp_path),
        "--",
        sys.executable,
        "-c",
        "pass",
    )
    assert started.returncode == 0, started.stderr
    _wait_done(state, "done")
    before = (state / "done.done").read_bytes()
    stopped = _run(state, "stop", "done")
    assert stopped.returncode == 0, stopped.stderr
    assert "already finished" in stopped.stdout
    assert (state / "done.done").read_bytes() == before


def test_stop_unknown_run_fails(tmp_path: Path) -> None:
    stopped = _run(tmp_path, "stop", "missing")
    assert stopped.returncode != 0
    assert "not found" in stopped.stderr


def test_stop_refuses_pid_identity_mismatch(tmp_path: Path) -> None:
    state, pgid = _start_tree(tmp_path)
    try:
        info_file = state / "tree.json"
        info = json.loads(info_file.read_text())
        info["start_ticks"] += 1
        info_file.write_text(json.dumps(info))
        stopped = _run(state, "stop", "tree", "--force")
        assert stopped.returncode != 0
        assert "PID identity mismatch" in stopped.stderr
        assert _alive(pgid)
        assert not (state / "tree.done").exists()
    finally:
        _kill_group(pgid)


def test_stop_supports_legacy_metadata(tmp_path: Path) -> None:
    state, pgid = _start_tree(tmp_path)
    try:
        info_file = state / "tree.json"
        info = json.loads(info_file.read_text())
        for key in ("pid", "pgid", "start_ticks"):
            del info[key]
        info_file.write_text(json.dumps(info))
        stopped = _run(state, "stop", "tree", "--timeout", "2")
        assert stopped.returncode == 0, stopped.stderr
        assert not _alive(pgid)
    finally:
        _kill_group(pgid)


def test_stop_timeout_lists_survivors_without_killing(tmp_path: Path) -> None:
    state, pgid = _start_tree(tmp_path, ignore_term=True)
    try:
        children = json.loads((tmp_path / "children.json").read_text())
        stopped = _run(state, "stop", "tree", "--timeout", ".2")
        assert stopped.returncode != 0
        assert "surviving pids" in stopped.stderr
        assert all(str(pid) in stopped.stderr and _alive(pid) for pid in children)
        assert not (state / "tree.done").exists()
    finally:
        _kill_group(pgid)


def test_stop_force_kills_term_resistant_children(tmp_path: Path) -> None:
    state, pgid = _start_tree(tmp_path, ignore_term=True)
    try:
        children = json.loads((tmp_path / "children.json").read_text())
        stopped = _run(state, "stop", "tree", "--timeout", ".2", "--force")
        assert stopped.returncode == 0, stopped.stderr
        assert all(not _alive(pid) for pid in [pgid, *children])
        assert _wait_done(state, "tree")["exit_code"] == -signal.SIGKILL
    finally:
        _kill_group(pgid)
