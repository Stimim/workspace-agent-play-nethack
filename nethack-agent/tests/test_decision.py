import json
from dataclasses import replace
from pathlib import Path

import pytest

from nethack_agent.contracts import ContractError
from nethack_agent.coordinator import ActionGate
from nethack_agent.decision import (
    MAX_CANDIDATE_REASON_LENGTH,
    MAX_FALLBACK_CANDIDATES,
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DecisionError,
    DestinationKind,
    IntentDestination,
    MapCell,
    PrayerPermit,
    PromptKind,
    PromptPermit,
    Skill,
    SkillSelectionSource,
    StuckReason,
    confirmation_answer_error,
    confirmation_prompt_kind,
    hunger_action_error,
    level_change_error,
    model_selectable_skills,
    parse_action_decision,
    parse_skill_decision,
    prayer_action_error,
    prompt_response_error,
    skill_decision_schema,
)
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.knowledge import load_default_knowledge_bundle
from nethack_agent.model import DecisionFailure, OllamaDecisionModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import Generation, OllamaError
from nethack_agent.traversal import (
    MAX_DUNGEON_NUMBER,
    STAND_ON_DOWNSTAIRS,
    UNKNOWN_STAIR,
    ExploreLevelGoal,
    Goal,
    IdentityEvidence,
    LevelKey,
    StairConnection,
    StairDirection,
    StairIdentity,
    StairIdentityKind,
    StairTarget,
    StandOnStairsGoal,
    TraverseStairsGoal,
)


class ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str, *_: object, **__: object) -> Generation:
        self.prompts.append(prompt)
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


def test_model_fallback_never_receives_eat_or_inventory_letters(
    tmp_path: Path,
) -> None:
    environment, observation = projected_state(tmp_path)
    client = ScriptedClient([valid_action_decision()])
    try:
        gate = ActionGate(environment.legal_actions)
        model(client).select_action(
            observation,
            gate.allowed_actions,
            STAND_ON_DOWNSTAIRS,
            Skill.STAIRCASE_NAVIGATION,
        )
    finally:
        environment.close()

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert '"letter"' not in prompt
    assert "Command.EAT" not in prompt
    assert observation.inventory[0].description in prompt


def test_survival_permit_predicates_require_hunger_and_matching_prompt_evidence() -> (
    None
):
    eat = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.HUNGER,
        SkillSelectionSource.ARBITER,
        None,
        21,
        "Eat a verified ration.",
        None,
    )
    prompt = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_PROMPT,
        STAND_ON_DOWNSTAIRS,
        Skill.HUNGER,
        SkillSelectionSource.ARBITER,
        None,
        24,
        "Select the verified ration.",
        None,
    )

    assert (
        hunger_action_error(
            "Command.EAT",
            eat,
            hunger=1,
            prompt_active=False,
            safe_ration_available=True,
        )
        == "EAT requires Hungry or worse"
    )
    assert (
        hunger_action_error(
            "Command.EAT",
            eat,
            hunger=2,
            prompt_active=False,
            safe_ration_available=True,
        )
        is None
    )
    assert (
        prompt_response_error(
            "Command.DROP",
            ord("d"),
            prompt,
            prompt_active=False,
            item_selection=True,
            offered_commands=frozenset({ord("d")}),
        )
        is not None
    )
    assert (
        prompt_response_error(
            "Command.DROP",
            ord("d"),
            prompt,
            prompt_active=True,
            item_selection=True,
            offered_commands=frozenset({ord("z")}),
        )
        == "the item prompt did not offer that inventory letter"
    )
    assert (
        prompt_response_error(
            "Command.DROP",
            ord("d"),
            prompt,
            prompt_active=True,
            item_selection=True,
            offered_commands=frozenset({ord("d")}),
        )
        is None
    )
    assert (
        prompt_response_error(
            "CompassDirection.W",
            ord("h"),
            prompt,
            prompt_active=True,
            item_selection=True,
            offered_commands=frozenset({ord("h")}),
        )
        is None
    )


def test_prayer_permit_and_confirmation_predicates_require_matching_evidence() -> None:
    prayer = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.PRAYER,
        SkillSelectionSource.ARBITER,
        None,
        58,
        "Authorized prayer.",
        None,
    )
    assert (
        prayer_action_error("Command.PRAY", prayer, permit=None, turn=101)
        == "PRAY requires a matching deterministic prayer permit"
    )
    assert (
        prayer_action_error("Command.PRAY", prayer, permit=PrayerPermit(100), turn=101)
        == "PRAY requires a matching deterministic prayer permit"
    )
    assert (
        prayer_action_error("Command.PRAY", prayer, permit=PrayerPermit(101), turn=101)
        is None
    )
    assert (
        prayer_action_error(
            "Command.PRAY",
            replace(prayer, source=ActionSelectionSource.MODEL_FALLBACK),
            permit=PrayerPermit(101),
            turn=101,
        )
        == "only the deterministic prayer skill may select PRAY"
    )

    answer = replace(
        prayer,
        source=ActionSelectionSource.DETERMINISTIC_PROMPT,
    )
    kind = confirmation_prompt_kind(
        "Are you sure you want to pray? [yn] (n) ",
        single_choice=True,
    )
    assert kind is PromptKind.PRAYER_CONFIRMATION
    assert (
        confirmation_prompt_kind(
            "Are you sure you want to pray? [yn] (n)",
            single_choice=True,
        )
        is None
    )
    assert (
        confirmation_prompt_kind(
            "There is a lichen corpse here; eat it? [ynq] (n) ",
            single_choice=True,
        )
        is PromptKind.CORPSE_CONFIRMATION
    )
    assert (
        confirmation_prompt_kind(
            "There is a lichen corpse here; eat it? [ynq] (n) extra",
            single_choice=True,
        )
        is None
    )
    assert (
        confirmation_answer_error(
            ord("y"),
            answer,
            prompt_active=True,
            prompt_kind=kind,
            permit=PromptPermit(ord("y"), kind),
        )
        is None
    )
    assert (
        confirmation_answer_error(
            ord("y"),
            answer,
            prompt_active=True,
            prompt_kind=kind,
            permit=PromptPermit(ord("y"), PromptKind.ITEM),
        )
        == "yes requires a matching active confirmation prompt permit"
    )


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


_MINES_DOWN = TraverseStairsGoal(
    StairTarget(StairDirection.DOWN, StairConnection.BRANCH, 2)
)
_MAIN_DOWN = TraverseStairsGoal(
    StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
)
_LEVEL_TWO = LevelKey(0, 2)


def descend(
    goal: object = _MAIN_DOWN,
    stair: StairIdentity = UNKNOWN_STAIR,
    **changes: object,
) -> ActionSelection:
    """A staircase-navigation selection to use the `>` at (5, 3) on (0, 2)."""
    fields: dict[str, object] = {
        "source": ActionSelectionSource.DETERMINISTIC_SKILL,
        "goal": goal,
        "skill": Skill.STAIRCASE_NAVIGATION,
        "skill_selection": SkillSelectionSource.ARBITER,
        "stuck_reason": None,
        "action_index": 18,
        "rationale": "Use the staircase.",
        "intent": ActionIntent(
            IntentDestination(DestinationKind.DOWNSTAIRS, 5, 3, stair),
            None,
            None,
            LevelKey(0, 2),
        ),
    }
    fields.update(changes)
    return ActionSelection(**fields)  # type: ignore[arg-type]


def refusal(
    selection: ActionSelection,
    *,
    action: str = "MiscDirection.DOWN",
    allowed: bool = True,
    level: LevelKey = _LEVEL_TWO,
    position: tuple[int, int] = (5, 3),
    prompt: bool = False,
    pair_known: bool = False,
) -> str | None:
    return level_change_error(
        action,
        selection,
        level_changes_allowed=allowed,
        level=level,
        position=position,
        prompt_active=prompt,
        pair_known=pair_known,
    )


def test_level_change_needs_a_matching_traversal_goal_skill_and_stair() -> None:
    assert refusal(descend()) is None
    # Actions that do not change level always pass.
    assert (
        refusal(descend(goal=STAND_ON_DOWNSTAIRS), action="MiscDirection.WAIT") is None
    )

    assert "never changes level" in refusal(descend(), allowed=False)  # type: ignore[operator]
    # Standing on `>` is not using it.
    assert "traverse_stairs goal" in refusal(descend(goal=STAND_ON_DOWNSTAIRS))  # type: ignore[operator]
    assert "traverse_stairs goal" in refusal(descend(), action="MiscDirection.UP")  # type: ignore[operator]
    assert "staircase navigation" in refusal(  # type: ignore[operator]
        descend(skill=Skill.EXPLORE_LEVEL)
    )
    assert "staircase navigation" in refusal(  # type: ignore[operator]
        descend(source=ActionSelectionSource.MODEL_FALLBACK, intent=None)
    )
    assert "in-place intent" in refusal(  # type: ignore[operator]
        descend(
            intent=ActionIntent(
                IntentDestination(DestinationKind.DOWNSTAIRS, 5, 3, UNKNOWN_STAIR),
                None,
                (MapCell(5, 3),),
                LevelKey(0, 2),
            )
        )
    )
    assert "active prompt" in refusal(descend(), prompt=True)  # type: ignore[operator]
    assert "not standing" in refusal(descend(), position=(4, 3))  # type: ignore[operator]
    assert "not standing" in refusal(descend(), level=LevelKey(0, 3))  # type: ignore[operator]


def test_level_change_needs_a_compatible_stair_identity() -> None:
    main = StairIdentity(StairIdentityKind.MAIN, 0, IdentityEvidence.TRAVERSED)
    mines = StairIdentity(StairIdentityKind.BRANCH, 2, IdentityEvidence.ELIMINATION)

    assert refusal(descend(stair=main)) is None
    assert "identity does not match" in refusal(descend(stair=mines))  # type: ignore[operator]
    assert refusal(descend(goal=_MINES_DOWN, stair=mines)) is None
    assert "identity does not match" in refusal(descend(goal=_MINES_DOWN, stair=main))  # type: ignore[operator]
    # An unknown `>` is a branch probe only on a level with two of them.
    assert "identity does not match" in refusal(descend(goal=_MINES_DOWN))  # type: ignore[operator]
    assert refusal(descend(goal=_MINES_DOWN), pair_known=True) is None


def test_climbing_out_of_the_dungeon_is_always_refused() -> None:
    climb = TraverseStairsGoal(
        StairTarget(StairDirection.UP, StairConnection.MAIN, None)
    )
    selection = descend(
        goal=climb,
        action_index=17,
        intent=ActionIntent(
            IntentDestination(DestinationKind.UPSTAIRS, 5, 3, UNKNOWN_STAIR),
            None,
            None,
            LevelKey(0, 1),
        ),
    )
    assert "leaves the dungeon" in refusal(  # type: ignore[operator]
        selection, action="MiscDirection.UP", level=LevelKey(0, 1)
    )


def every_goal() -> list[Goal]:
    targets = [
        StairTarget(direction, connection, dungeon)
        for direction in StairDirection
        for connection in StairConnection
        for dungeon in (
            range(MAX_DUNGEON_NUMBER + 1)
            if connection is StairConnection.BRANCH
            else (None,)
        )
    ]
    return [StandOnStairsGoal(target) for target in targets] + [
        TraverseStairsGoal(target)
        for target in targets
        if target.connection is not StairConnection.ANY
    ]


def test_every_goal_has_a_distinct_token_the_parser_maps_back() -> None:
    goals = tuple(every_goal())
    assert len({goal.token for goal in goals}) == len(goals)
    for goal in goals:
        response = json.loads(valid_skill_decision())
        response["goal"] = goal.token
        decision = parse_skill_decision(
            json.dumps(response), goals, frozenset({Skill.STAIRCASE_NAVIGATION})
        )
        assert decision.goal == goal


class RecordingClient(ScriptedClient):
    pass


def test_stuck_prompt_describes_every_offered_goal_and_its_staircase(
    tmp_path: Path,
) -> None:
    climb = TraverseStairsGoal(
        StairTarget(StairDirection.UP, StairConnection.MAIN, None)
    )
    offered = (climb, STAND_ON_DOWNSTAIRS)
    response = json.loads(valid_skill_decision())
    response["goal"] = climb.token
    client = RecordingClient([json.dumps(response)])
    environment, observation = projected_state(tmp_path)
    try:
        result = model(client).select_skill(
            observation,
            offered,
            (Skill.STAIRCASE_NAVIGATION, Skill.EXPLORE_LEVEL),
            StuckReason.SEARCH_EXHAUSTED,
        )
    finally:
        environment.close()

    assert result.decision.goal == climb
    (prompt,) = client.prompts
    # Each offered goal is listed with its own stand-or-use constraint, and the
    # stuck situation names the staircases those goals need.
    assert "- traverse_stairs:up:main: reach the upstairs" in prompt
    assert "- stand_on_stairs:down:any: stand on a downstairs tile" in prompt
    assert "without descending" in prompt
    assert "no upstairs or downstairs matching the goal" in prompt


def test_exhaustion_markers_are_strict_optional_level_evidence() -> None:
    marked = descend(exhausted_level=LevelKey(0, 2))

    assert ActionSelection.from_json(marked.to_json()) == marked
    assert marked.to_json()["exhausted_level"] == {
        "dungeon_number": 0,
        "dungeon_level": 2,
    }
    # New selections always write the key; legacy selections without it read
    # as not recorded.
    assert descend().to_json()["exhausted_level"] is None
    legacy = descend().to_json()
    del legacy["exhausted_level"]
    assert ActionSelection.from_json(legacy).exhausted_level is None
    with pytest.raises(ContractError, match="dungeon_level"):
        ActionSelection.from_json(
            {**marked.to_json(), "exhausted_level": {"dungeon_number": 0}}
        )
    with pytest.raises(ContractError, match="intent's level"):
        descend(exhausted_level=LevelKey(0, 3))
    with pytest.raises(ContractError, match="prompt answer"):
        descend(
            source=ActionSelectionSource.DETERMINISTIC_PROMPT,
            intent=None,
            exhausted_level=LevelKey(0, 2),
        )


def test_explore_goals_offer_only_exploration_and_describe_the_level(
    tmp_path: Path,
) -> None:
    goal = ExploreLevelGoal(LevelKey(0, 2))
    assert model_selectable_skills(goal) == (Skill.EXPLORE_LEVEL,)
    assert model_selectable_skills(STAND_ON_DOWNSTAIRS) == (
        Skill.STAIRCASE_NAVIGATION,
        Skill.EXPLORE_LEVEL,
    )
    response = json.loads(valid_skill_decision())
    response["goal"] = goal.token
    response["skill"] = "staircase_navigation"
    client = RecordingClient([json.dumps(response), json.dumps(response)])
    environment, observation = projected_state(tmp_path)
    try:
        with pytest.raises(DecisionFailure):
            model(client).select_skill(
                observation,
                (goal,),
                model_selectable_skills(goal),
                StuckReason.SEARCH_EXHAUSTED,
            )
    finally:
        environment.close()

    prompt = client.prompts[0]
    assert "- explore_level:0:2: explore level 2 of dungeon 0 until" in prompt
    assert 'Available skills: ["explore_level"]' in prompt
    assert "staircase_navigation cannot act now" not in prompt


@pytest.mark.parametrize(
    "goal", [ExploreLevelGoal(LevelKey(0, 2)), STAND_ON_DOWNSTAIRS, _MAIN_DOWN]
)
def test_gold_navigation_is_never_offered_to_the_model(goal: Goal) -> None:
    skills = model_selectable_skills(goal)
    schema = skill_decision_schema((goal,), skills)

    assert Skill.GOLD_NAVIGATION not in skills
    assert "gold_navigation" not in schema["properties"]["skill"]["enum"]  # type: ignore[index]
    response = json.loads(valid_skill_decision())
    response["goal"] = goal.token
    response["skill"] = "gold_navigation"
    with pytest.raises(DecisionError, match="not available"):
        parse_skill_decision(json.dumps(response), (goal,), frozenset(skills))


def gold_step(**changes: object) -> ActionSelection:
    """A gold-navigation step east toward the gold at (6, 3) on (0, 1)."""
    fields: dict[str, object] = {
        "source": ActionSelectionSource.DETERMINISTIC_SKILL,
        "goal": ExploreLevelGoal(LevelKey(0, 1)),
        "skill": Skill.GOLD_NAVIGATION,
        "skill_selection": SkillSelectionSource.ARBITER,
        "stuck_reason": None,
        "action_index": 1,
        "rationale": "Walk onto the gold.",
        "intent": ActionIntent(
            IntentDestination(DestinationKind.GOLD, 6, 3),
            None,
            (MapCell(5, 3), MapCell(6, 3)),
            LevelKey(0, 1),
        ),
    }
    fields.update(changes)
    return ActionSelection(**fields)  # type: ignore[arg-type]


def test_gold_intents_belong_only_to_gold_navigation_and_end_on_the_gold() -> None:
    step = gold_step()
    assert ActionSelection.from_json(step.to_json()) == step
    frontier = ActionIntent(
        IntentDestination(DestinationKind.FRONTIER, 6, 3),
        None,
        (MapCell(5, 3), MapCell(6, 3)),
    )

    with pytest.raises(ContractError, match="only gold navigation"):
        gold_step(skill=Skill.EXPLORE_LEVEL)
    with pytest.raises(ContractError, match="gold destination"):
        gold_step(intent=frontier)
    with pytest.raises(ContractError, match="gold destination"):
        gold_step(intent=None)
    with pytest.raises(ContractError, match="arbiter-selected"):
        gold_step(
            skill_selection=SkillSelectionSource.MODEL,
            stuck_reason=StuckReason.SEARCH_EXHAUSTED,
        )
    with pytest.raises(ContractError, match="must end at the destination"):
        ActionIntent(
            IntentDestination(DestinationKind.GOLD, 6, 3),
            None,
            (MapCell(5, 3), MapCell(5, 4)),
        )
