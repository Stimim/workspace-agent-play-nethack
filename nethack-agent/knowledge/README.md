# Local-player knowledge

This directory will hold concise, reviewed knowledge cards retrieved into the local playing model's context. It is deliberately separate from `_agents/skills/`, which serves coding agents.

## Card requirements

Each card must state:

- the gameplay question it answers;
- facts or rules in compact, action-oriented form;
- applicable NetHack version and variants excluded;
- source page titles and canonical URLs;
- extraction or source revision date when available;
- reviewer date;
- uncertainty or conflicting evidence.

Cards must be small enough to retrieve selectively. Do not commit bulk wiki conversion, raw XML, copied article collections, model-generated claims without review, or episode-specific memories.

## Evaluation rule

The knowledge set is versioned and fixed for an entire evaluation suite. Changes are made between suites after a coding agent reviews run evidence; the playing model does not rewrite this directory.
