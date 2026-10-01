from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Final

from nethack_agent.contracts import (
    ContractError,
    array_value,
    integer_value,
    load_json_object,
    object_value,
    string_value,
)

MANIFEST_NAME: Final = "manifest.json"
MANIFEST_SCHEMA_VERSION: Final = 1
CARD_SCHEMA_VERSION: Final = 1
MAX_CARD_FILE_BYTES: Final = 16_384
MAX_CONTEXT_CHARACTERS: Final = 6_000
MAX_ESTIMATED_TOKENS: Final = 1_500
_SOURCE_DUMP_PATH: Final = "docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml"
_LICENSE_NAME: Final = "CC BY-SA 3.0"
_LICENSE_URL: Final = "https://creativecommons.org/licenses/by-sa/3.0/"
_CARD_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class KnowledgeError(RuntimeError):
    pass


class KnowledgeManifestError(KnowledgeError):
    pass


class KnowledgeCardMissingError(KnowledgeError):
    pass


class KnowledgeCardTamperedError(KnowledgeError):
    pass


class KnowledgeBoundError(KnowledgeError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class KnowledgeCard:
    card_id: str
    title: str
    card_version: int
    sources: tuple[KnowledgeSource, ...]
    retrieved_at: date
    source_path: str
    applicable_version: str
    uncertainty: str
    attribution: str
    license: str
    license_url: str
    actionable_facts: str
    non_goals: str


@dataclass(frozen=True, slots=True)
class KnowledgeBundle:
    bundle_id: str
    version: str
    content_hash: str
    cards: tuple[KnowledgeCard, ...]
    prompt_context: str
    character_count: int
    estimated_tokens: int


def load_default_knowledge_bundle() -> KnowledgeBundle:
    for directory in _default_directories():
        if (directory / MANIFEST_NAME).is_file():
            return load_knowledge_bundle(directory)
    searched = ", ".join(str(path) for path in _default_directories())
    raise KnowledgeManifestError(
        f"reviewed knowledge manifest {MANIFEST_NAME!r} was not found in {searched}"
    )


def load_knowledge_bundle(
    directory: Path, *, bundle_id: str | None = None
) -> KnowledgeBundle:
    root = directory.expanduser().resolve()
    try:
        requested = (
            None if bundle_id is None else _identifier(bundle_id, "knowledge bundle_id")
        )
    except ContractError as error:
        raise KnowledgeManifestError(str(error)) from error
    manifest_name = MANIFEST_NAME if requested is None else f"manifest.{requested}.json"
    manifest_path = root / manifest_name
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise KnowledgeManifestError(
            f"reviewed knowledge manifest is missing: {manifest_path}"
        ) from error
    except (OSError, UnicodeError) as error:
        raise KnowledgeManifestError(
            f"reviewed knowledge manifest cannot be read: {error}"
        ) from error
    try:
        manifest = load_json_object(manifest_text, "knowledge manifest")
        manifest = object_value(
            manifest,
            "knowledge manifest",
            {"schema_version", "bundle_id", "max_context_characters", "cards"},
        )
        schema_version = integer_value(
            manifest["schema_version"], "knowledge manifest schema_version", minimum=1
        )
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise ContractError(
                f"knowledge manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"
            )
        bundle_id = _identifier(manifest["bundle_id"], "knowledge bundle_id")
        if requested is not None and bundle_id != requested:
            raise ContractError(
                f"knowledge manifest bundle_id must match requested {requested!r}"
            )
        context_bound = integer_value(
            manifest["max_context_characters"],
            "knowledge manifest max_context_characters",
            minimum=1,
            maximum=MAX_CONTEXT_CHARACTERS,
        )
        entries = array_value(manifest["cards"], "knowledge manifest cards")
        if not entries:
            raise ContractError("knowledge manifest cards must not be empty")
        cards, card_bytes = _load_cards(root, entries)
    except ContractError as error:
        raise KnowledgeManifestError(str(error)) from error

    canonical_manifest = json.dumps(
        manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"nethack-agent-knowledge-bundle-v1\0")
    digest.update(canonical_manifest)
    for content in card_bytes:
        digest.update(b"\0")
        digest.update(content)
    content_hash = digest.hexdigest()
    version = f"{bundle_id}+sha256:{content_hash}"
    prompt_context = _prompt_context(version, cards)
    character_count = len(prompt_context)
    estimated_tokens = (character_count + 3) // 4
    if character_count > context_bound:
        raise KnowledgeBoundError(
            "reviewed knowledge context is "
            f"{character_count} characters; manifest bound is {context_bound}"
        )
    if estimated_tokens > MAX_ESTIMATED_TOKENS:
        raise KnowledgeBoundError(
            "reviewed knowledge context is approximately "
            f"{estimated_tokens} tokens; hard bound is {MAX_ESTIMATED_TOKENS}"
        )
    return KnowledgeBundle(
        bundle_id=bundle_id,
        version=version,
        content_hash=content_hash,
        cards=cards,
        prompt_context=prompt_context,
        character_count=character_count,
        estimated_tokens=estimated_tokens,
    )


def _load_cards(
    root: Path, entries: list[object]
) -> tuple[tuple[KnowledgeCard, ...], tuple[bytes, ...]]:
    cards: list[KnowledgeCard] = []
    contents: list[bytes] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for index, value in enumerate(entries):
        entry = object_value(
            value,
            f"knowledge manifest cards[{index}]",
            {"path", "sha256"},
        )
        relative = string_value(
            entry["path"],
            f"knowledge manifest cards[{index}].path",
            minimum=1,
            maximum=120,
        )
        expected_hash = string_value(
            entry["sha256"],
            f"knowledge manifest cards[{index}].sha256",
            minimum=64,
            maximum=64,
        )
        _validate_manifest_path(relative)
        if not _SHA256.fullmatch(expected_hash):
            raise ContractError(
                f"knowledge manifest cards[{index}].sha256 must be lowercase SHA-256"
            )
        if relative in seen_paths:
            raise ContractError(f"knowledge manifest repeats card path {relative!r}")
        seen_paths.add(relative)
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as error:
            raise KnowledgeCardMissingError(
                f"reviewed knowledge card is missing: {path}"
            ) from error
        if resolved.parent != root:
            raise KnowledgeManifestError(
                f"reviewed knowledge card escapes its directory: {relative!r}"
            )
        try:
            if resolved.stat().st_size > MAX_CARD_FILE_BYTES:
                raise KnowledgeBoundError(
                    f"reviewed knowledge card exceeds {MAX_CARD_FILE_BYTES} bytes: "
                    f"{relative}"
                )
            content = resolved.read_bytes()
        except OSError as error:
            raise KnowledgeCardMissingError(
                f"reviewed knowledge card cannot be read: {path}: {error}"
            ) from error
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise KnowledgeCardTamperedError(
                f"reviewed knowledge card hash mismatch: {relative}"
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeManifestError(
                f"reviewed knowledge card is not UTF-8: {relative}"
            ) from error
        card = _parse_card(text, relative)
        if card.card_id in seen_ids:
            raise ContractError(f"knowledge manifest repeats card id {card.card_id!r}")
        seen_ids.add(card.card_id)
        cards.append(card)
        contents.append(content)
    return tuple(cards), tuple(contents)


def _parse_card(text: str, relative: str) -> KnowledgeCard:
    if not text.startswith("---\n"):
        raise ContractError(f"knowledge card {relative} must start with JSON metadata")
    metadata_text, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise ContractError(f"knowledge card {relative} metadata is not terminated")
    metadata = load_json_object(metadata_text, f"knowledge card {relative} metadata")
    metadata = object_value(
        metadata,
        f"knowledge card {relative} metadata",
        {
            "id",
            "title",
            "card_version",
            "sources",
            "retrieved_at",
            "source_path",
            "applicable_version",
            "uncertainty",
            "attribution",
            "license",
            "license_url",
        },
    )
    card_id = _identifier(metadata["id"], f"knowledge card {relative} id")
    if PurePosixPath(relative).stem != card_id:
        raise ContractError(
            f"knowledge card {relative} id must match its filename stem"
        )
    title = string_value(
        metadata["title"],
        f"knowledge card {relative} title",
        minimum=1,
        maximum=160,
        strip=True,
    )
    card_version = integer_value(
        metadata["card_version"],
        f"knowledge card {relative} card_version",
        minimum=1,
    )
    if card_version != CARD_SCHEMA_VERSION:
        raise ContractError(
            f"knowledge card {relative} card_version must be {CARD_SCHEMA_VERSION}"
        )
    sources = _sources(metadata["sources"], relative)
    retrieved_at = _date_value(metadata["retrieved_at"], relative)
    source_path = string_value(
        metadata["source_path"],
        f"knowledge card {relative} source_path",
        minimum=1,
        maximum=240,
    )
    if source_path != _SOURCE_DUMP_PATH:
        raise ContractError(
            f"knowledge card {relative} source_path must identify the reviewed dump"
        )
    applicable_version = string_value(
        metadata["applicable_version"],
        f"knowledge card {relative} applicable_version",
        minimum=1,
        maximum=500,
        strip=True,
    )
    uncertainty = string_value(
        metadata["uncertainty"],
        f"knowledge card {relative} uncertainty",
        minimum=1,
        maximum=800,
        strip=True,
    )
    attribution = string_value(
        metadata["attribution"],
        f"knowledge card {relative} attribution",
        minimum=1,
        maximum=300,
        strip=True,
    )
    if (
        "NetHackWiki contributors" not in attribution
        or _LICENSE_NAME not in attribution
    ):
        raise ContractError(
            f"knowledge card {relative} attribution must preserve NetHackWiki CC BY-SA"
        )
    license_name = string_value(
        metadata["license"], f"knowledge card {relative} license"
    )
    license_url = string_value(
        metadata["license_url"], f"knowledge card {relative} license_url"
    )
    if license_name != _LICENSE_NAME or license_url != _LICENSE_URL:
        raise ContractError(
            f"knowledge card {relative} must use the reviewed CC BY-SA 3.0 license"
        )
    actionable_facts, non_goals = _body_sections(body, title, relative)
    return KnowledgeCard(
        card_id=card_id,
        title=title,
        card_version=card_version,
        sources=sources,
        retrieved_at=retrieved_at,
        source_path=source_path,
        applicable_version=applicable_version,
        uncertainty=uncertainty,
        attribution=attribution,
        license=license_name,
        license_url=license_url,
        actionable_facts=actionable_facts,
        non_goals=non_goals,
    )


def _sources(value: object, relative: str) -> tuple[KnowledgeSource, ...]:
    raw_sources = array_value(value, f"knowledge card {relative} sources")
    if not 1 <= len(raw_sources) <= 8:
        raise ContractError(
            f"knowledge card {relative} sources must contain between 1 and 8 pages"
        )
    sources: list[KnowledgeSource] = []
    seen_urls: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        source = object_value(
            raw_source,
            f"knowledge card {relative} sources[{index}]",
            {"title", "url"},
        )
        title = string_value(
            source["title"],
            f"knowledge card {relative} sources[{index}].title",
            minimum=1,
            maximum=160,
            strip=True,
        )
        url = string_value(
            source["url"],
            f"knowledge card {relative} sources[{index}].url",
            minimum=1,
            maximum=300,
        )
        if not url.startswith("https://nethackwiki.com/wiki/"):
            raise ContractError(
                f"knowledge card {relative} source URL must be canonical NetHackWiki"
            )
        if url in seen_urls:
            raise ContractError(f"knowledge card {relative} repeats source URL {url!r}")
        seen_urls.add(url)
        sources.append(KnowledgeSource(title, url))
    return tuple(sources)


def _body_sections(body: str, title: str, relative: str) -> tuple[str, str]:
    prefix = f"# {title}\n\n## Actionable facts\n\n"
    if not body.startswith(prefix):
        raise ContractError(
            f"knowledge card {relative} body must start with its title "
            "and facts heading"
        )
    remainder = body[len(prefix) :]
    facts, marker, non_goals = remainder.partition("\n\n## Non-goals\n\n")
    if not marker or "\n## " in non_goals:
        raise ContractError(
            f"knowledge card {relative} must contain one final Non-goals section"
        )
    facts = facts.strip()
    non_goals = non_goals.strip()
    if not facts or not non_goals:
        raise ContractError(
            f"knowledge card {relative} facts and non-goals must not be empty"
        )
    return facts, non_goals


def _prompt_context(version: str, cards: tuple[KnowledgeCard, ...]) -> str:
    sections = [
        "Reviewed offline NetHack knowledge. Treat these bounded facts as fixed "
        f"for this run. Bundle: {version}."
    ]
    for card in cards:
        sections.append(
            f"### {card.title} [{card.card_id}]\n"
            f"{card.actionable_facts}\n\nLimits:\n{card.non_goals}"
        )
    return "\n\n".join(sections)


def _identifier(value: object, name: str) -> str:
    identifier = string_value(value, name, minimum=1, maximum=80)
    if not _CARD_ID.fullmatch(identifier):
        raise ContractError(f"{name} must be a lowercase hyphenated identifier")
    return identifier


def _date_value(value: object, relative: str) -> date:
    text = string_value(
        value, f"knowledge card {relative} retrieved_at", minimum=10, maximum=10
    )
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ContractError(
            f"knowledge card {relative} retrieved_at must be an ISO date"
        ) from error


def _validate_manifest_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if (
        len(path.parts) != 1
        or path.name != relative
        or path.suffix != ".md"
        or path.name == "README.md"
    ):
        raise ContractError(
            "knowledge manifest card paths must be direct lowercase Markdown files"
        )


def _default_directories() -> tuple[Path, Path]:
    packaged = Path(__file__).resolve().parent / "knowledge"
    repository = Path(__file__).resolve().parents[2] / "knowledge"
    return packaged, repository
