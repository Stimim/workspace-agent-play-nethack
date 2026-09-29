# Coding-agent resources

This directory is for repository-specific procedures and tools used by online coding agents while developing the project. It is not loaded into the local NetHack player at runtime.

- `skills/nethack-wiki/`: inspect the ignored NetHackWiki XML dump without loading it into memory or a model context.
- `skills/omp-commit/`: run the repository format/lint checks and create a
  commit with a deterministically validated active OMP conversation trailer.
- `models/omp-coder-smol/Modelfile`: reproducible Ollama definition for the
  local OMP `tiny`/`smol` coding fallback. Coding-model recipes belong under
  `models/`; they are development tooling and are not loaded by the NetHack
  playing agent.
- `models/omp-coder/Modelfile` and `models/omp-coder-large/Modelfile`: the
  local OMP `fast` and `good` coding-worker models; `models/omp-local-worker.yml`
  is the OMP settings overlay they require (see `docs/development.md`).

Knowledge intended for the playing model belongs under `nethack-agent/knowledge/`. Promote facts there only after checking relevance, supported NetHack version, provenance, and licensing.
