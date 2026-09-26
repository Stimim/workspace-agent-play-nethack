from __future__ import annotations

import json
from pathlib import Path

import pytest

from nethack_agent.decision import Goal, Skill
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import DecisionFailure, OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import (
    DEFAULT_NUM_CTX,
    MAX_NUM_CTX,
    OllamaClient,
    OllamaConfig,
    OllamaContextLimitError,
    OllamaError,
)


class RecordingClient(OllamaClient):
    def __init__(self, config: OllamaConfig, prompt_tokens: int) -> None:
        super().__init__(config)
        self.prompt_tokens = prompt_tokens
        self.payloads: list[dict[str, object]] = []

    def ensure_ready(self) -> str:
        return "test"

    def _request_json(
        self, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        assert path == "/api/generate"
        assert payload is not None
        self.payloads.append(payload)
        return {
            "response": json.dumps(
                {
                    "goal": Goal.STAND_ON_DOWNSTAIRS.value,
                    "skill": Skill.STAIRCASE_NAVIGATION.value,
                    "rationale": "route to stairs",
                }
            ),
            "prompt_eval_count": self.prompt_tokens,
            "eval_count": 7,
            "total_duration": 3_000_000,
        }


@pytest.mark.parametrize("num_ctx", [0, -1, True, 1.5, MAX_NUM_CTX + 1])
def test_num_ctx_must_be_a_bounded_positive_integer(num_ctx: object) -> None:
    with pytest.raises(OllamaError, match="num_ctx"):
        OllamaConfig(num_ctx=num_ctx)  # type: ignore[arg-type]


def test_num_ctx_environment_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETHACK_AGENT_OLLAMA_NUM_CTX", raising=False)
    assert OllamaConfig.from_environment().num_ctx == DEFAULT_NUM_CTX == 8192

    monkeypatch.setenv("NETHACK_AGENT_OLLAMA_NUM_CTX", "4096")
    assert OllamaConfig.from_environment().num_ctx == 4096

    for value in ("", "abc", "0", "-5", "8192.0", " 8192", "8_192", "1e4"):
        monkeypatch.setenv("NETHACK_AGENT_OLLAMA_NUM_CTX", value)
        with pytest.raises(OllamaError, match="NUM_CTX"):
            OllamaConfig.from_environment()
    monkeypatch.setenv("NETHACK_AGENT_OLLAMA_NUM_CTX", str(MAX_NUM_CTX + 1))
    with pytest.raises(OllamaError, match="num_ctx"):
        OllamaConfig.from_environment()


def test_generation_requests_configured_context_and_accepts_headroom() -> None:
    client = RecordingClient(OllamaConfig(num_ctx=1024), prompt_tokens=512)

    generation = client.generate("prompt", max_tokens=512)

    assert generation.prompt_tokens == 512
    options = client.payloads[0]["options"]
    assert isinstance(options, dict)
    assert options["num_ctx"] == 1024
    assert options["num_predict"] == 512


@pytest.mark.parametrize("prompt_tokens", [513, 1024, 2048])
def test_generation_without_output_headroom_is_rejected(prompt_tokens: int) -> None:
    client = RecordingClient(OllamaConfig(num_ctx=1024), prompt_tokens=prompt_tokens)

    with pytest.raises(OllamaContextLimitError, match="num_ctx 1024") as raised:
        client.generate("prompt", max_tokens=512)

    assert raised.value.generation.prompt_tokens == prompt_tokens


def test_context_overflow_counts_as_failed_attempts(tmp_path: Path) -> None:
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=5)
    )
    try:
        observation = ObservationProjector().project(environment.reset(), step_index=0)
    finally:
        environment.close()
    client = RecordingClient(OllamaConfig(num_ctx=1024), prompt_tokens=900)

    with pytest.raises(DecisionFailure) as raised:
        OllamaDecisionModel(client, load_default_knowledge_bundle()).select_skill(
            observation,
            (Goal.STAND_ON_DOWNSTAIRS,),
            (Skill.STAIRCASE_NAVIGATION,),
            None,
        )

    failure = raised.value
    assert len(client.payloads) == 2
    assert len(failure.attempts) == 2
    assert all("OllamaContextLimitError" in item.error for item in failure.attempts)
    assert [item.prompt_tokens for item in failure.attempts] == [900, 900]
    assert failure.metrics.prompt_tokens == 1800
    assert failure.metrics.latency_ms == 6.0
