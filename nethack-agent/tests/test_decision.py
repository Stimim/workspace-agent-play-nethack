import json
from pathlib import Path

import pytest

from nethack_agent.decision import (
    MAX_CANDIDATE_REASON_LENGTH,
    MAX_FALLBACK_CANDIDATES,
    DecisionError,
    Skill,
    StuckReason,
    parse_action_decision,
    parse_skill_decision,
    skill_decision_schema,
)
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import DecisionFailure, OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import Generation, OllamaError
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    StairConnection,
    StairDirection,
    StairTarget,
    TraverseStairsGoal,
)


class ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def generate(self, *_: object, **__: object) -> Generation:
        response = self.responses[self.calls]
        self.calls += 1
        return Generation(response, 10, 5, 1_000_000)


def model(client):  # type: ignore[no-untyped-def]
    return OllamaDecisionModel(client, load_default_knowledge_bundle())


def valid_action_decision(action_index: int = 2) -> str:
    return json.dumps(
        {
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


def valid_skill_decision() -> str:
    return json.dumps(
        {
            "goal": STAND_ON_DOWNSTAIRS.token,
            "skill": Skill.STAIRCASE_NAVIGATION.value,
            "rationale": "Use deterministic routing when the staircase is visible.",
        }
    )


def projected_state(tmp_path: Path):  # type: ignore[no-untyped-def]
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    observation = environment.reset()
    projected = ObservationProjector().project(observation, step_index=0)
    return environment, projected


def test_action_decision_requires_selected_highest_scored_legal_candidate() -> None:
    payload = json.loads(valid_action_decision())
    payload["candidates"].append(
        {"action_index": 1, "score": 1.0, "reason": "higher score"}
    )

    with pytest.raises(DecisionError, match="highest"):
        parse_action_decision(json.dumps(payload), frozenset({1, 2}))


def test_decisions_reject_duplicate_keys_decimal_indices_and_unknown_skills() -> None:
    duplicate = (
        '{"candidates":[{"action_index":2,"score":1,"reason":"open"}],'
        '"action_index":2,"action_index":2,"rationale":"move"}'
    )
    with pytest.raises(DecisionError, match="duplicate"):
        parse_action_decision(duplicate, frozenset({2}))

    decimal = json.loads(valid_action_decision())
    decimal["action_index"] = 2.0
    with pytest.raises(DecisionError, match="integer"):
        parse_action_decision(json.dumps(decimal), frozenset({2}))

    bad_skill = json.loads(valid_skill_decision())
    bad_skill["skill"] = "teleport_to_stairs"
    with pytest.raises(DecisionError, match="one of"):
        parse_skill_decision(
            json.dumps(bad_skill),
            (STAND_ON_DOWNSTAIRS,),
            frozenset({Skill.STAIRCASE_NAVIGATION}),
        )

    unavailable = json.loads(valid_skill_decision())
    unavailable["skill"] = Skill.EXPLORE_LEVEL.value
    with pytest.raises(DecisionError, match="not available"):
        parse_skill_decision(
            json.dumps(unavailable),
            (STAND_ON_DOWNSTAIRS,),
            frozenset({Skill.STAIRCASE_NAVIGATION}),
        )


def test_model_names_one_offered_goal_by_token() -> None:
    descend = TraverseStairsGoal(
        StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
    )
    offered = (descend, STAND_ON_DOWNSTAIRS)
    schema = skill_decision_schema(offered)
    assert schema["properties"]["goal"]["enum"] == [  # type: ignore[index]
        "traverse_stairs:down:main",
        "stand_on_stairs:down:any",
    ]

    response = json.loads(valid_skill_decision())
    response["goal"] = descend.token
    decision = parse_skill_decision(
        json.dumps(response), offered, frozenset({Skill.STAIRCASE_NAVIGATION})
    )
    assert decision.goal == descend
    assert decision.to_json()["goal"] == descend.to_json()

    # A goal the coordinator did not offer, or the pre-token enum value, is
    # rejected rather than guessed.
    for token in (descend.token, "stand_on_downstairs"):
        response["goal"] = token
        with pytest.raises(DecisionError, match="not available"):
            parse_skill_decision(
                json.dumps(response),
                (STAND_ON_DOWNSTAIRS,),
                frozenset({Skill.STAIRCASE_NAVIGATION}),
            )


def test_fallback_decisions_are_bounded_to_three_short_candidates() -> None:
    too_many = json.loads(valid_action_decision(1))
    too_many["candidates"] = [
        {"action_index": index, "score": 0.5, "reason": "open floor"}
        for index in range(1, MAX_FALLBACK_CANDIDATES + 2)
    ]
    with pytest.raises(DecisionError, match="between one and"):
        parse_action_decision(json.dumps(too_many), frozenset(range(1, 10)))

    long_reason = json.loads(valid_action_decision())
    long_reason["candidates"][0]["reason"] = "x" * (MAX_CANDIDATE_REASON_LENGTH + 1)
    with pytest.raises(DecisionError, match="candidate reason"):
        parse_action_decision(json.dumps(long_reason), frozenset({2}))

    exact = json.loads(valid_action_decision(1))
    exact["candidates"] = [
        {"action_index": index, "score": 0.5, "reason": "r" * 100}
        for index in range(1, MAX_FALLBACK_CANDIDATES + 1)
    ]
    assert (
        len(
            parse_action_decision(json.dumps(exact), frozenset(range(1, 10))).candidates
        )
        == MAX_FALLBACK_CANDIDATES
    )


def test_model_repairs_one_invalid_action_response(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", valid_action_decision()])
    try:
        result = model(client).select_action(
            observation,
            environment.legal_actions,
            STAND_ON_DOWNSTAIRS,
            Skill.STAIRCASE_NAVIGATION,
        )
    finally:
        environment.close()

    assert result.decision.action_index == 2
    assert result.metrics.repair_attempted
    assert client.calls == 2


def test_model_parses_typed_goal_and_skill(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    try:
        result = model(ScriptedClient([valid_skill_decision()])).select_skill(
            observation,
            (STAND_ON_DOWNSTAIRS,),
            (Skill.STAIRCASE_NAVIGATION, Skill.EXPLORE_LEVEL),
            StuckReason.SEARCH_EXHAUSTED,
        )
    finally:
        environment.close()

    assert result.decision.goal == STAND_ON_DOWNSTAIRS
    assert result.decision.skill is Skill.STAIRCASE_NAVIGATION


def test_model_fails_after_exactly_one_repair(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", "{}"])
    try:
        with pytest.raises(DecisionFailure, match="after one repair"):
            model(client).select_skill(
                observation,
                (STAND_ON_DOWNSTAIRS,),
                (Skill.STAIRCASE_NAVIGATION,),
                None,
            )
    finally:
        environment.close()

    assert client.calls == 2


def test_failed_repair_preserves_both_attempt_diagnostics(tmp_path: Path) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient(["{}", '{"goal":"still invalid"}'])
    try:
        with pytest.raises(DecisionFailure) as raised:
            model(client).select_skill(
                observation,
                (STAND_ON_DOWNSTAIRS,),
                (Skill.STAIRCASE_NAVIGATION,),
                None,
            )
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
    assert failure.to_json()["attempts"][0]["raw_response"] == "{}"  # type: ignore[index]


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
            model(TransportFailureClient()).select_skill(
                observation,
                (STAND_ON_DOWNSTAIRS,),
                (Skill.STAIRCASE_NAVIGATION,),
                None,
            )
    finally:
        environment.close()

    failure = raised.value
    assert failure.metrics.latency_ms == 12.0
    assert [attempt.elapsed_ms for attempt in failure.attempts] == [5.0, 7.0]
    assert all(attempt.returned_duration_ms is None for attempt in failure.attempts)
