import json
import subprocess
import sys
import time
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
