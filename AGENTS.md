# Coding-agent guide

The ultimate goal is an autonomous NetHack ascension using a local playing
agent. Online models are development tools, not gameplay dependencies.

## Required orientation

Before changing behavior, read:

1. `README.md` for repository layout and current status.
2. `ARCHITECTURE.md` for component boundaries and invariants.
3. `TODO_LIST.md` for the active milestone and acceptance criteria.
4. `docs/handover.md` for work in flight, open decisions, and operating
   limits.
5. `docs/README.md`, the relevant decision records, and the latest applicable
   development notes.

## Repository rules

1. Documentation is part of the implementation. Keep current architecture,
   decisions, roadmap, developer workflow, history, and lessons accurate in the
   same change that alters them.
2. Keep the top level minimal. Product code belongs in `nethack-agent/`.
   Introduce another top-level directory only for an independently extractable
   domain.
3. Use Python 3.12 and `uv` in `nethack-agent/`. Keep `uv.lock` current and run
   commands through `uv run`.
4. Consume the maintained `NetHack-LE/nle` package. Do not vendor or fork NLE
   without a documented engine-level requirement.
5. Gameplay is offline. Runtime code must not call non-loopback services.
   Ollama URLs must resolve only to loopback addresses.
6. Do not expose hidden chain-of-thought. Persist and display structured
   decisions: state summary, goal, candidates/scores, action, concise rationale,
   timing, and token usage.
7. Keep evaluation reproducible. Prompts, policy, model identity, knowledge,
   and seed suite stay fixed during a suite.
8. Every behavioral change requires an exercised smoke path. Record only
   verification that actually ran.
9. Commits created by a coding agent must follow
   [`_agents/skills/omp-commit/SKILL.md`](_agents/skills/omp-commit/SKILL.md).
   - OMP sessions commit with `omp_commit.py commit`, which runs the checks
     and writes exactly one `OMP-Conversation: <conversation-uuid>` trailer
     from process/session evidence.
   - Claude Code sessions commit with `omp_commit.py claude-commit`, which
     runs the same checks and writes exactly one `Claude-Session:
     <session-uuid>` trailer from `CLAUDE_CODE_SESSION_ID` and its
     transcript, beside Claude Code's required `Co-Authored-By:` trailer.
     `omp_commit.py commit` refuses to run inside Claude Code (it would
     attribute the commit to whatever OMP session is open).
   Never invent or manually substitute an identifier.
10. Only the orchestrating session commits. Subagents and worker sessions
    hand over a branch or patch file and never commit. Before committing,
    re-check every number or claim a worker reports against the actual
    report, database, or diff.
11. Raw evaluation data (`runs.sqlite3`, ttyrecs, full reports) stays
    outside the tree. A note that cites an evaluation commits a compact
    per-seed record of it, with the commit, suite, model, and command needed
    to rerun any seed.

## Knowledge boundaries

- `_agents/skills/` is for online coding-agent procedures and source-inspection
  tools.
- `nethack-agent/knowledge/` is compact, reviewed, cited material supplied to
  the local playing model.
- `docs/external/` describes large external sources. The ignored wiki XML dump
  is evidence, not model context and not automatically trusted knowledge.

After an episode or evaluation suite, a coding agent may inspect persisted
evidence and improve versioned code or knowledge. The playing agent must not
self-modify during a run or evaluation suite.
