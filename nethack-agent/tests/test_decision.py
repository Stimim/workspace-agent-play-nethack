import json
from pathlib import Path

import pytest

from nethack_agent.decision import DecisionError, parse_action_decision
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.model import DecisionFailure, OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import Generation, OllamaError


class ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def generate(self, *_: object, **__: object) -> Generation:
        response = self.responses[self.calls]
        self.calls += 1
        return Generation(response, 10, 5, 1_000_000)


def valid_decision(action_index: int = 2) -> str:
    return json.dumps(
        {
            "goal": "explore east",
            "candidates": [
                {
                    "action_index": action_index,
                    "score": 0.9,
                    "reason": "open floor is visible",
                }
            ],
            "action_index": action_index,
            "rationale": "Move into visible unexplored floor.",
        }
    )


def projected_state(tmp_path: Path):
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    observation = environment.reset()
    projected = ObservationProjector().project(observation, step_index=0)
    return environment, projected


def test_decision_requires_selected_highest_scored_legal_candidate() -> None:
    payload = json.loads(valid_decision())
    payload["candidates"].append(
        {"action_index": 1, "score": 1.0, "reason": "higher score"}
    )

    with pytest.raises(DecisionError, match="highest"):
        parse_action_decision(json.dumps(payload), frozenset({1, 2}))


def test_decision_rejects_duplicate_keys_and_decimal_action_indices() -> None:
    duplicate = (
        '{"goal":"explore","goal":"repeat","candidates":'
        '[{"action_index":2,"score":1,"reason":"open"}],'
        '"action_index":2,"rationale":"move"}'
    )
    with pytest.raises(DecisionError, match="duplicate"):
        parse_action_decision(duplicate, frozenset({2}))

    decimal = json.loads(valid_decision())
    decimal["action_index"] = 2.0
    with pytest.raises(DecisionError, match="integer"):
        parse_action_decision(json.dumps(decimal), frozenset({2}))


def test_model_repairs_one_invalid_response(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", valid_decision()])
    try:
        result = OllamaDecisionModel(client).decide(
            observation, environment.legal_actions
        )
    finally:
        environment.close()

    assert result.decision.action_index == 2
    assert result.metrics.repair_attempted
    assert client.calls == 2


def test_model_fails_after_exactly_one_repair(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", "{}"])
    try:
        with pytest.raises(DecisionFailure, match="after one repair"):
            OllamaDecisionModel(client).decide(observation, environment.legal_actions)
    finally:
        environment.close()

    assert client.calls == 2


def test_failed_repair_preserves_both_attempt_diagnostics(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", '{"goal":"still invalid"}'])
    try:
        with pytest.raises(DecisionFailure) as raised:
            OllamaDecisionModel(client).decide(observation, environment.legal_actions)
    finally:
        environment.close()

    failure = raised.value
    assert len(failure.attempts) == 2
    assert [attempt.raw_response for attempt in failure.attempts] == [
        "{}",
        '{"goal":"still invalid"}',
    ]
    assert all("DecisionError" in attempt.error for attempt in failure.attempts)
    assert failure.metrics.prompt_tokens == 20
    assert failure.metrics.output_tokens == 10
    assert failure.metrics.latency_ms == 2.0
    assert failure.to_json()["attempts"][0]["raw_response"] == "{}"


class TransportFailureClient:
    def generate(self, *_: object, **__: object) -> Generation:
        raise OllamaError("transport unavailable")


def test_transport_failure_uses_wall_clock_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timestamps = iter((0, 5_000_000, 5_000_000, 12_000_000))
    monkeypatch.setattr(
        "nethack_agent.model.time.perf_counter_ns", lambda: next(timestamps)
    )
    environment, observation = projected_state(tmp_path)
    try:
        with pytest.raises(DecisionFailure) as raised:
            OllamaDecisionModel(TransportFailureClient()).decide(
                observation, environment.legal_actions
            )
    finally:
        environment.close()

    failure = raised.value
    assert failure.metrics.latency_ms == 12.0
    assert [attempt.elapsed_ms for attempt in failure.attempts] == [5.0, 7.0]
    assert all(attempt.returned_duration_ms is None for attempt in failure.attempts)
