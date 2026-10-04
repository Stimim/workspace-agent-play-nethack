# Detached evaluation skill

Use this skill for every evaluation suite. Tool deadlines must never cut an evaluation short: launch every evaluation through `scripts/detached_eval.py`, then call `wait` with the tool timeout disabled (`timeout: 0`) or poll `status`.

From the repository root:

```bash
_agents/skills/detached-eval/scripts/detached_eval.py start --name RUN --cwd nethack-agent -- uv run nethack-agent eval run --suite evaluation/SUITE.json --data-dir /tmp/RUN --report-dir /tmp/RUN/reports --development-scripted-model
_agents/skills/detached-eval/scripts/detached_eval.py wait RUN
```

`start` creates a new session with stdin disconnected and combined output in `/tmp/detached-eval/RUN.log`; metadata (`RUN.json`) records command, working directory, start time, and Git HEAD. State defaults to `/tmp/detached-eval/`; override with `--state-dir`. `status RUN` reports running/finished state and the last 20 log lines, `list` lists runs, and `wait RUN` prints the completion exit code and log tail. A detached wrapper writes `RUN.done` with exit code and end time even when nobody is waiting. Names cannot be reused while their process is running.
