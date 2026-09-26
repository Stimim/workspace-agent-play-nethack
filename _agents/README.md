# Coding-agent resources

This directory is for repository-specific procedures and tools used by online coding agents while developing the project. It is not loaded into the local NetHack player at runtime.

- `skills/nethack-wiki/`: inspect the ignored NetHackWiki XML dump without loading it into memory or a model context.

Knowledge intended for the playing model belongs under `nethack-agent/knowledge/`. Promote facts there only after checking relevance, supported NetHack version, provenance, and licensing.
