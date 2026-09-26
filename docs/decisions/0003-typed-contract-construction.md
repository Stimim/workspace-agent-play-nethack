# ADR 0003: Retain typed contract construction instead of a runtime JSON Schema validator

- Status: accepted
- Date: 2026-09-27

## Context

`contracts.py` provides small primitives for exact object fields, arrays, strings, booleans, finite numbers, integers, enums, and duplicate-key-rejecting JSON parsing. Domain `from_json` methods in observations, decisions, events, evaluation reports, knowledge metadata, environment records, and storage compose those primitives while constructing immutable enums and dataclasses.

The repository has no direct JSON Schema validation dependency. FastAPI brings Pydantic transitively for HTTP models, but persisted events and model decisions are domain records rather than request models. The two JSON Schemas already in `decision.py` are sent to Ollama as generation constraints. The typed parsers remain authoritative because they additionally validate the current legal action set and cross-field rules.

A generic validator would cover primitive shapes but not the important invariants without custom code: action membership; intent/source consistency; map bounds; contiguous, non-revisiting paths ending at the correct destination; model decision consistency; and compatibility rules for legacy optional pet, intent, path, and inventory BUC evidence. It also does not replace duplicate-key rejection during JSON decoding or enum/dataclass construction. Validating a schema and then constructing the same nested domain values would traverse and allocate for each payload twice on event-read, API, replay, and evaluation paths. Migrating every caller to generated/Pydantic models would be a broad second contract system and would couple storage to a web dependency.

## Decision

Retain the small typed construction helpers and domain `from_json` methods. They must continue to:

- reject unknown fields and missing required fields;
- reject duplicate JSON keys and non-finite numbers before domain construction;
- return domain enums and immutable dataclasses, not untyped validated dictionaries;
- include field/domain context in errors;
- list legacy optional fields explicitly and map absence to an honest unknown or unrecorded value;
- enforce relational invariants in the owning domain type.

Continue sending JSON Schema to Ollama to constrain generated output, but do not treat that outbound schema as a substitute for parsing untrusted model text. Add a public runtime schema engine only if measurements show a concrete maintenance or interoperability benefit that outweighs a second validation pass and its dependency/package cost.

## Consequences

`contracts.py` remains deliberately small and dependency-free. Adding a field requires updating the owning dataclass, serializer, parser, compatibility rule, and behavior tests in one place rather than synchronizing a general schema with separate construction code. Error messages remain tailored to stored-event and model-decision context.

The trade-off is that the repository owns these primitives and cannot automatically export every persisted contract as JSON Schema. Existing malformed-payload tests cover exact fields, primitive bounds, duplicate keys, enums, legacy absence, and cross-field invariants; the Ollama schemas separately cover the model generation surface.
