# OMP commit provenance skill

Use this skill whenever a coding agent creates a Git commit in this repository. The script obtains the conversation UUID from active OMP process and session evidence; never type, copy, or invent the trailer value yourself.

## Commit procedure

1. Write the intended commit message to a file outside the repository worktree.
2. From the repository root, run:

   ```bash
   _agents/skills/omp-commit/scripts/omp_commit.py commit \
     --message-file /path/to/message -- <other safe git commit options>
   ```

3. The script first walks its own process ancestry (from its parent through PID 1). The nearest matching OMP client—an `omp` process recorded for this repository—is authoritative: its explicit `--resume <uuid>` is validated against exactly one matching OMP session JSONL. If that ancestor's UUID or session evidence is missing, malformed, or ambiguous, resolution fails without trying other clients. If no matching OMP ancestor exists, the global live-client scan succeeds only when exactly one matching client exists; zero or multiple clients are hard failures. The error identifies whether ancestor or global resolution applied. The script never guesses a conversation UUID.
4. Before invoking `git commit`, the script runs `uv run ruff check .` and `uv run ruff format --check .` in `nethack-agent/`. A failed check leaves Git history unchanged.
5. The script removes any existing `OMP-Conversation` lines from the supplied message copy and writes exactly one final `OMP-Conversation: <active-uuid>` trailer. It never changes the caller's message file and passes Git arguments as an argv array without shell evaluation.

Use `resolve` to inspect the validated UUID without committing and `checks` to run only the fixed checks:

```bash
_agents/skills/omp-commit/scripts/omp_commit.py resolve
_agents/skills/omp-commit/scripts/omp_commit.py checks
```

Use `commit --dry-run` to run the checks and print the normalized message without changing Git history. The `--omp-root` and `--proc-root` options exist for deterministic tests with isolated evidence; normal use must retain their defaults.
