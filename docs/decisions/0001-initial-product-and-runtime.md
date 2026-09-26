# ADR 0001: Initial product and runtime architecture

- Status: accepted
- Date: 2026-09-26

## Context

The project must eventually beat NetHack autonomously on a workstation with an RTX 4070 Laptop GPU and Ollama. Online frontier models are affordable for development and debugging but not sustained gameplay. The repository must retain enough architecture, decisions, history, and workflow information for a newly launched coding agent to continue work.

The original `facebookresearch/nle` repository was archived in 2024. Its maintained successor, [`NetHack-LE/nle`](https://github.com/NetHack-LE/nle), publishes NLE 1.3.0 for modern Python and had active commits in 2026. It supplies Gymnasium environments, structured observations, task environments, deterministic seeding support, and ttyrec recording.

## Decision

- Autonomous ascension is the north star.
- The first capability milestone is `NetHackStaircase-v0`, not a full-game attempt.
- A fixed lawful dwarven Valkyrie reduces variance.
- Milestone acceptance is success on at least 6 of 10 committed deterministic seeds, including seed 6.
- Use a hierarchical hybrid: Gemma chooses goals or skills; deterministic code validates and executes low-level actions and prompt handling.
- Use the installed `gemma4-nethack:latest` through local Ollama. Runtime network access is loopback-only.
- Consume maintained NLE 1.3.0 from PyPI. Do not fork or vendor it without an evidenced requirement.
- Persist structured events in SQLite and native replay in ttyrec files.
- Expose one client-neutral loopback control/status API and WebSocket event stream to both the browser and coding-agent tools. It supports validated scenario start, pause, step, graceful stop, and observation; clients never call the coordinator directly.
- Model failures get one structured-output repair retry, then pause with diagnostics.
- Keep policy, prompts, and knowledge fixed during an evaluation suite. Human/coding-agent analysis between suites drives improvements.
- Separate coding-agent skills from compact, reviewed local-player knowledge.

## Consequences

The first milestone measures a real behavior while remaining small enough to inspect. Deterministic skills reduce token use and prevent invalid action execution. Fixed policy and seeds make comparisons meaningful. SQLite plus ttyrec costs storage but makes failures reconstructable.

The 9.6 GB model exceeds the GPU's 8 GB VRAM, so partial CPU offload may make per-turn inference too slow. Action cadence must be measured. Laya remains an option for later routine action ranking, but adding it before baseline measurements would create a second inference path without evidence.

Using NLE as a package keeps this repository small and avoids NetHack General Public License source-management obligations associated with modifying and distributing a fork. The adapter remains a domain boundary so a future fork can replace the package if required.
