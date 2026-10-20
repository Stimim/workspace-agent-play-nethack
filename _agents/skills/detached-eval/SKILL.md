# Detached evaluation skill

Use this skill for every evaluation suite. Tool deadlines must never cut an evaluation short: launch every evaluation through `scripts/detached_eval.py`, then call `wait` with the tool timeout disabled (`timeout: 0`) or poll `status`.

From the repository root:

```bash
_agents/skills/detached-eval/scripts/detached_eval.py start --name RUN --cwd nethack-agent -- uv run nethack-agent eval run --suite evaluation/SUITE.json --data-dir /tmp/RUN --report-dir /tmp/RUN/reports --workers 10 --development-scripted-model
_agents/skills/detached-eval/scripts/detached_eval.py wait RUN
```

`start` creates a new session with stdin disconnected and combined output in `/tmp/detached-eval/RUN.log`; metadata (`RUN.json`) records command, working directory, start time, and Git HEAD. State defaults to `/tmp/detached-eval/`; override with `--state-dir`. `status RUN` reports running/finished state and the last 20 log lines, `list` lists runs, and `wait RUN` prints the completion exit code and log tail. A detached wrapper writes `RUN.done` with exit code and end time even when nobody is waiting. Names cannot be reused while their process is running.

Stop a run and all workers in its detached process group:

```bash
_agents/skills/detached-eval/scripts/detached_eval.py [--state-dir DIR] stop RUN [--timeout SECONDS] [--force]
```

`stop` verifies the recorded launch identity before sending SIGTERM, then waits
up to 30 seconds (override with `--timeout`) for every live process in the group
to exit. With `--force`, survivors receive SIGKILL; without it, survivors are
listed and the command exits nonzero. Decide whether to force termination on the
initial call: if SIGTERM kills the wrapper but leaves resistant workers, a later
call cannot safely authenticate the dead wrapper and refuses to signal.
Launch metadata records the PID, process group, and Linux `/proc` start ticks;
older runs are authenticated against the detached wrapper's command line.
The caller's own group and unsafe groups are never signalled. Exited zombies
are not live survivors; their parent is responsible for reaping them.

Successful stopping ensures `RUN.done` records `stopped: true`, an exit code
(negative signal number if the wrapper did not write one), and end time.
`status`, `list`, and `wait` identify it as finished (stopped); `wait` still
returns the recorded exit code. Stopping an already finished run is a successful
no-op; an unknown name or mismatched PID identity fails without signalling.
