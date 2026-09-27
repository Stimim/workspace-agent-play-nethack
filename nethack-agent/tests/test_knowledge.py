from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from nethack_agent.decision import Skill, StuckReason
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.knowledge import (
    KnowledgeBoundError,
    KnowledgeCardMissingError,
    KnowledgeCardTamperedError,
    KnowledgeManifestError,
    load_default_knowledge_bundle,
    load_knowledge_bundle,
)
from nethack_agent.model import OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import Generation, OllamaConfig
from nethack_agent.run_manager import RunManager
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

KNOWLEDGE_DIRECTORY = Path(__file__).resolve().parents[1] / "knowledge"


class RecordingClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str, **_kwargs: object) -> Generation:
        self.prompts.append(prompt)
        return Generation(self.response, 10, 5, 1_000_000)


def copy_knowledge(tmp_path: Path) -> Path:
    directory = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIRECTORY, directory)
    return directory


def read_manifest(directory: Path) -> dict[str, object]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def write_manifest(directory: Path, manifest: dict[str, object]) -> None:
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def rehash_card(directory: Path, card_path: str) -> None:
    manifest = read_manifest(directory)
    cards = manifest["cards"]
    assert isinstance(cards, list)
    digest = hashlib.sha256((directory / card_path).read_bytes()).hexdigest()
    for card in cards:
        assert isinstance(card, dict)
        if card["path"] == card_path:
            card["sha256"] = digest
    write_manifest(directory, manifest)


def test_reviewed_bundle_is_deterministic_and_manifest_ordered() -> None:
    first = load_default_knowledge_bundle()
    second = load_knowledge_bundle(KNOWLEDGE_DIRECTORY)
    manifest = read_manifest(KNOWLEDGE_DIRECTORY)
    cards = manifest["cards"]
    assert isinstance(cards, list)

    assert first == second
    assert first.version == f"staircase-reviewed-v2+sha256:{first.content_hash}"
    assert [card.card_id for card in first.cards] == [
        Path(str(card["path"])).stem for card in cards if isinstance(card, dict)
    ]
    assert first.character_count <= 6_000
    assert first.estimated_tokens <= 1_500
    assert all(card.license == "CC BY-SA 3.0" for card in first.cards)
    assert all(
        source.url.startswith("https://nethackwiki.com/wiki/")
        for card in first.cards
        for source in card.sources
    )


def test_manifest_order_changes_version_and_prompt_order(tmp_path: Path) -> None:
    directory = copy_knowledge(tmp_path)
    original = load_knowledge_bundle(directory)
    manifest = read_manifest(directory)
    cards = manifest["cards"]
    assert isinstance(cards, list)
    cards.reverse()
    write_manifest(directory, manifest)

    reordered = load_knowledge_bundle(directory)

    assert [card.card_id for card in reordered.cards] == [
        card.card_id for card in reversed(original.cards)
    ]
    assert reordered.version != original.version


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.update({"extra": True}), "unexpected"),
        (lambda manifest: manifest.update({"cards": []}), "must not be empty"),
        (
            lambda manifest: manifest["cards"].append(dict(manifest["cards"][0])),
            "repeats card path",
        ),
        (
            lambda manifest: manifest["cards"][0].update({"path": "../escape.md"}),
            "direct lowercase Markdown",
        ),
        (
            lambda manifest: manifest["cards"][0].update({"sha256": "A" * 64}),
            "lowercase SHA-256",
        ),
        (
            lambda manifest: manifest.update({"max_context_characters": 6_001}),
            "at most 6000",
        ),
    ],
)
def test_manifest_validation_rejects_unreviewed_shapes(
    tmp_path: Path, mutation, message: str
) -> None:  # type: ignore[no-untyped-def]
    directory = copy_knowledge(tmp_path)
    manifest = read_manifest(directory)
    mutation(manifest)
    write_manifest(directory, manifest)

    with pytest.raises(KnowledgeManifestError, match=message):
        load_knowledge_bundle(directory)


def test_missing_and_tampered_allowlisted_cards_fail(tmp_path: Path) -> None:
    directory = copy_knowledge(tmp_path)
    card = directory / "staircase-goal.md"
    card.write_text(card.read_text(encoding="utf-8") + "\nUnreviewed fact.\n")
    with pytest.raises(KnowledgeCardTamperedError, match="hash mismatch"):
        load_knowledge_bundle(directory)

    card.unlink()
    with pytest.raises(KnowledgeCardMissingError, match="missing"):
        load_knowledge_bundle(directory)


def test_unlisted_cards_do_not_enter_prompt(tmp_path: Path) -> None:
    directory = copy_knowledge(tmp_path)
    original = load_knowledge_bundle(directory)
    (directory / "unlisted.md").write_text("UNREVIEWED STAIR TELEPORT RULE")

    loaded = load_knowledge_bundle(directory)

    assert loaded == original
    assert "UNREVIEWED STAIR TELEPORT RULE" not in loaded.prompt_context


def test_bound_is_enforced_on_rendered_context(tmp_path: Path) -> None:
    directory = copy_knowledge(tmp_path)
    manifest = read_manifest(directory)
    manifest["max_context_characters"] = 100
    write_manifest(directory, manifest)

    with pytest.raises(KnowledgeBoundError, match="characters"):
        load_knowledge_bundle(directory)


def test_card_metadata_requires_attribution_after_review(tmp_path: Path) -> None:
    directory = copy_knowledge(tmp_path)
    card = directory / "exploration-map.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "Adapted from NetHackWiki contributors under CC BY-SA 3.0.",
            "Adapted from a wiki.",
        ),
        encoding="utf-8",
    )
    rehash_card(directory, "exploration-map.md")

    with pytest.raises(KnowledgeManifestError, match="attribution"):
        load_knowledge_bundle(directory)


def test_ollama_prompts_include_bounded_cards_without_source_leakage(
    tmp_path: Path,
) -> None:
    bundle = load_default_knowledge_bundle()
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    try:
        observation = ObservationProjector().project(environment.reset(), step_index=0)
        skill_client = RecordingClient(
            json.dumps(
                {
                    "goal": STAND_ON_DOWNSTAIRS.token,
                    "skill": Skill.STAIRCASE_NAVIGATION.value,
                    "rationale": "Use reviewed staircase facts.",
                }
            )
        )
        OllamaDecisionModel(skill_client, bundle).select_skill(
            observation,
            (STAND_ON_DOWNSTAIRS,),
            (Skill.STAIRCASE_NAVIGATION, Skill.EXPLORE_LEVEL),
            StuckReason.SEARCH_EXHAUSTED,
        )
        action_index = environment.legal_actions[1].index
        action_client = RecordingClient(
            json.dumps(
                {
                    "candidates": [
                        {
                            "action_index": action_index,
                            "score": 1.0,
                            "reason": "legal",
                        }
                    ],
                    "action_index": action_index,
                    "rationale": "Use a legal fallback.",
                }
            )
        )
        OllamaDecisionModel(action_client, bundle).select_action(
            observation,
            environment.legal_actions,
            STAND_ON_DOWNSTAIRS,
            Skill.STAIRCASE_NAVIGATION,
        )
    finally:
        environment.close()

    prompts = skill_client.prompts + action_client.prompts
    assert len(prompts) == 2
    for prompt in prompts:
        assert bundle.prompt_context in prompt
        assert "<mediawiki" not in prompt
        assert "{{" not in prompt
        assert "[[" not in prompt
        assert "nethackwiki_current.xml" not in prompt


def test_run_metadata_records_the_reviewed_bundle_version(tmp_path: Path) -> None:
    class ScriptedModel:
        def select_skill(self, *_args: object):  # type: ignore[no-untyped-def]
            raise AssertionError("run creation must not request a decision")

        def select_action(self, *_args: object):  # type: ignore[no-untyped-def]
            raise AssertionError("run creation must not request a decision")

    bundle = load_default_knowledge_bundle()
    manager = RunManager(
        tmp_path,
        OllamaConfig(model="test-model"),
        model_factory=lambda _client: ScriptedModel(),  # type: ignore[return-value]
        knowledge_bundle=bundle,
    )
    try:
        run = manager.create_run(seed=6, max_episode_steps=2)
        assert run.knowledge_version == bundle.version
        manager.stop(run.id)
    finally:
        manager.close()
