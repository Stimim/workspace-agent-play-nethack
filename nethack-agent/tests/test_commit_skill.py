import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / "_agents"
    / "skills"
    / "omp-commit"
    / "scripts"
    / "omp_commit.py"
)
CONVERSATION = "01a0dd35-4ec8-76dd-9c86-bcac1fdb25c5"
OTHER_CONVERSATION = "12345678-1234-4123-8123-123456789abc"


def _add_client(
    omp_root: Path,
    proc_root: Path,
    repository: Path,
    *,
    pid: int,
    conversation: str | None,
    duplicate_session: bool = False,
) -> None:
    clients = omp_root / "run" / "daemons" / f"daemon-{pid}" / "clients"
    clients.mkdir(parents=True)
    (clients / f"{pid}.json").write_text(
        json.dumps({"pid": pid, "projectDir": str(repository)}), encoding="utf-8"
    )
    process = proc_root / str(pid)
    process.mkdir(parents=True)
    command = ["/usr/local/bin/omp"]
    if conversation is not None:
        command.extend(["--resume", conversation])
    (process / "cmdline").write_bytes(
        b"\0".join(part.encode() for part in command) + b"\0"
    )
    if conversation is None:
        return
    for suffix in range(2 if duplicate_session else 1):
        session = (
            omp_root
            / "agent"
            / "sessions"
            / f"project-{suffix}"
            / f"2026-09-27T00-00-0{suffix}Z_{conversation}.jsonl"
        )
        session.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"type": "title", "title": "test"},
            {
                "type": "session",
                "version": 3,
                "id": conversation,
                "cwd": str(repository),
            },
        ]
        session.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )


def _skill(
    repository: Path,
    omp_root: Path,
    proc_root: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repository),
            "--omp-root",
            str(omp_root),
            "--proc-root",
            str(proc_root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _scratch_repository(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repository = tmp_path / "repository with spaces"
    product = repository / "nethack-agent"
    product.mkdir(parents=True)
    (product / "pyproject.toml").write_text(
        "[project]\nname='test'\n", encoding="utf-8"
    )
    (repository / "tracked file.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test Agent"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "agent@example.test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)

    binary_directory = tmp_path / "fake tools with spaces"
    binary_directory.mkdir()
    check_log = tmp_path / "check invocations.jsonl"
    fake_uv = binary_directory / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "with pathlib.Path(os.environ['CHECK_LOG']).open('a') as f:\n"
        "    f.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
        "raise SystemExit(int(os.environ.get('CHECK_EXIT', '0')))\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_directory}{os.pathsep}{environment['PATH']}"
    environment["CHECK_LOG"] = str(check_log)
    return repository, check_log, environment


def test_resolve_uses_one_live_client_and_validated_session(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    omp_root = tmp_path / "omp"
    proc_root = tmp_path / "proc"
    _add_client(
        omp_root,
        proc_root,
        repository,
        pid=101,
        conversation=CONVERSATION,
    )

    completed = _skill(repository, omp_root, proc_root, "resolve")

    assert completed.returncode == 0
    assert completed.stdout.strip() == CONVERSATION


@pytest.mark.parametrize(
    "failure", ["ambiguous", "no-match", "missing-uuid", "session-ambiguous"]
)
def test_resolve_hard_fails_without_unique_explicit_evidence(
    tmp_path: Path, failure: str
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    omp_root = tmp_path / "omp"
    proc_root = tmp_path / "proc"
    if failure != "no-match":
        _add_client(
            omp_root,
            proc_root,
            repository,
            pid=201,
            conversation=None if failure == "missing-uuid" else CONVERSATION,
            duplicate_session=failure == "session-ambiguous",
        )
    if failure == "ambiguous":
        _add_client(
            omp_root,
            proc_root,
            repository,
            pid=202,
            conversation=OTHER_CONVERSATION,
        )

    completed = _skill(repository, omp_root, proc_root, "resolve")

    assert completed.returncode == 2
    expected = {
        "ambiguous": "ambiguous active OMP clients",
        "no-match": "no active OMP client matches",
        "missing-uuid": "does not expose exactly one valid --resume UUID",
        "session-ambiguous": "ambiguous OMP session evidence",
    }
    assert expected[failure] in completed.stderr


def test_commit_replaces_duplicate_trailers_after_checks_and_handles_spaces(
    tmp_path: Path,
) -> None:
    repository, check_log, environment = _scratch_repository(tmp_path)
    omp_root = tmp_path / "omp"
    proc_root = tmp_path / "proc"
    _add_client(
        omp_root,
        proc_root,
        repository,
        pid=301,
        conversation=CONVERSATION,
    )
    message = tmp_path / "message with spaces.txt"
    original = (
        "Explain the change\n\n"
        "OMP-Conversation: 00000000-0000-4000-8000-000000000000\n"
        "OMP-Conversation: 11111111-1111-4111-8111-111111111111\n"
    )
    message.write_text(original, encoding="utf-8")

    completed = _skill(
        repository,
        omp_root,
        proc_root,
        "commit",
        "--message-file",
        str(message),
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert message.read_text(encoding="utf-8") == original
    commit_message = subprocess.run(
        ["git", "-C", str(repository), "log", "-1", "--format=%B"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert commit_message.count("OMP-Conversation:") == 1
    assert f"OMP-Conversation: {CONVERSATION}" in commit_message
    checks = [json.loads(line) for line in check_log.read_text().splitlines()]
    assert [entry["argv"] for entry in checks] == [
        ["run", "ruff", "check", "."],
        ["run", "ruff", "format", "--check", "."],
    ]
    assert all(entry["cwd"] == str(repository / "nethack-agent") for entry in checks)


def test_check_failure_does_not_create_commit(tmp_path: Path) -> None:
    repository, _, environment = _scratch_repository(tmp_path)
    environment["CHECK_EXIT"] = "7"
    omp_root = tmp_path / "omp"
    proc_root = tmp_path / "proc"
    _add_client(
        omp_root,
        proc_root,
        repository,
        pid=401,
        conversation=CONVERSATION,
    )
    message = tmp_path / "message.txt"
    message.write_text("Must not commit\n", encoding="utf-8")

    completed = _skill(
        repository,
        omp_root,
        proc_root,
        "commit",
        "--message-file",
        str(message),
        env=environment,
    )

    assert completed.returncode == 2
    assert "check failed (7)" in completed.stderr
    assert (
        subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )


def test_dry_run_prints_trailer_without_creating_commit(tmp_path: Path) -> None:
    repository, _, environment = _scratch_repository(tmp_path)
    omp_root = tmp_path / "omp"
    proc_root = tmp_path / "proc"
    _add_client(
        omp_root,
        proc_root,
        repository,
        pid=501,
        conversation=CONVERSATION,
    )
    message = tmp_path / "message.txt"
    message.write_text("Dry run\n", encoding="utf-8")

    completed = _skill(
        repository,
        omp_root,
        proc_root,
        "commit",
        "--message-file",
        str(message),
        "--dry-run",
        env=environment,
    )

    assert completed.returncode == 0
    assert completed.stdout == f"Dry run\n\nOMP-Conversation: {CONVERSATION}\n"
    assert (
        subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )
