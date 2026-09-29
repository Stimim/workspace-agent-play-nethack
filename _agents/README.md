# Coding-agent resources

This directory is for repository-specific procedures and tools used by online coding agents while developing the project. It is not loaded into the local NetHack player at runtime.

- `skills/nethack-wiki/`: inspect the ignored NetHackWiki XML dump without loading it into memory or a model context.
- `skills/omp-commit/`: run the repository format/lint checks and create a
  commit with a deterministically validated active OMP conversation trailer.
- `models/omp-coder/Modelfile`: the single local OMP model (gemma4:26b, 64k
  context) used by the `fast`/`good` coding workers and the `smol`, `tiny`, and
  `commit` roles (see `docs/development.md`). Coding-model recipes belong under
  `models/`; they are development tooling and are not loaded by the NetHack
  playing agent.
- `models/omp-coder-smol/Modelfile`: legacy gemma4:e4b model, kept only as the
  target of the old OMP fallback chains until those are removed.

Knowledge intended for the playing model belongs under `nethack-agent/knowledge/`. Promote facts there only after checking relevance, supported NetHack version, provenance, and licensing.
