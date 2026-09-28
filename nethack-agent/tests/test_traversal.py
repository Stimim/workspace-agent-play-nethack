import pytest

from nethack_agent.contracts import ContractError
from nethack_agent.traversal import (
    DUNGEON_EXIT,
    STAIRCASE_OBJECTIVE,
    STAND_ON_DOWNSTAIRS,
    UNKNOWN_STAIR,
    ApproachOracleGoal,
    EnterDungeonLeg,
    ExploreDungeonLeg,
    ExploreLevelGoal,
    FindOracleLeg,
    IdentityEvidence,
    LevelKey,
    Objective,
    ReachLevelLeg,
    StairConnection,
    StairDirection,
    StairIdentity,
    StairIdentityKind,
    StairTarget,
    StandOnStairsGoal,
    StandOnStairsLeg,
    TraverseStairsGoal,
    candidate_tier,
    goal_from_json,
)

DOWN = StairDirection.DOWN
MAIN_DOWN = StairTarget(DOWN, StairConnection.MAIN, None)
MINES_DOWN = StairTarget(DOWN, StairConnection.BRANCH, 2)


def test_legacy_goal_string_reads_as_standing_on_any_downstairs() -> None:
    goal = goal_from_json("stand_on_downstairs")

    assert goal == STAND_ON_DOWNSTAIRS
    assert goal == StandOnStairsGoal(StairTarget(DOWN, StairConnection.ANY, None))
    assert goal.to_json() == {
        "kind": "stand_on_stairs",
        "target": {"direction": "down", "connection": "any", "dungeon_number": None},
    }


GOALS = [
    STAND_ON_DOWNSTAIRS,
    TraverseStairsGoal(MAIN_DOWN),
    TraverseStairsGoal(StairTarget(StairDirection.UP, StairConnection.MAIN, None)),
    TraverseStairsGoal(MINES_DOWN),
    ExploreLevelGoal(LevelKey(0, 2)),
    ApproachOracleGoal(LevelKey(0, 2)),
]


@pytest.mark.parametrize("goal", GOALS)
def test_goals_round_trip_and_have_distinct_tokens(goal: object) -> None:
    assert goal_from_json(goal.to_json()) == goal  # type: ignore[attr-defined]
    assert goal.token.startswith(goal.kind.value)  # type: ignore[attr-defined]


def test_goal_tokens_are_unique_across_kinds_on_the_same_level() -> None:
    tokens = [goal.token for goal in GOALS]

    assert len(set(tokens)) == len(tokens)


def test_goal_tokens_name_direction_connection_and_branch() -> None:
    assert STAND_ON_DOWNSTAIRS.token == "stand_on_stairs:down:any"
    assert TraverseStairsGoal(MINES_DOWN).token == "traverse_stairs:down:branch:2"
    assert ExploreLevelGoal(LevelKey(2, 3)).token == "explore_level:2:3"
    assert ApproachOracleGoal(LevelKey(0, 7)).token == "approach_oracle:0:7"
    assert ExploreLevelGoal(LevelKey(0, 2)).to_json() == {
        "kind": "explore_level",
        "level": {"dungeon_number": 0, "dungeon_level": 2},
    }
    assert ApproachOracleGoal(LevelKey(0, 7)).to_json() == {
        "kind": "approach_oracle",
        "level": {"dungeon_number": 0, "dungeon_level": 7},
    }


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("stand_on_upstairs", "must be an object"),
        (
            {
                "kind": "traverse_stairs",
                "target": {
                    "direction": "down",
                    "connection": "any",
                    "dungeon_number": None,
                },
            },
            "main or branch",
        ),
        (
            {
                "kind": "traverse_stairs",
                "target": {
                    "direction": "down",
                    "connection": "branch",
                    "dungeon_number": None,
                },
            },
            "requires a dungeon_number",
        ),
        (
            {
                "kind": "stand_on_stairs",
                "target": {
                    "direction": "down",
                    "connection": "main",
                    "dungeon_number": 0,
                },
            },
            "only a branch",
        ),
        ({"kind": "walk", "target": {}}, "kind must be one of"),
        (
            {
                "kind": "explore_level",
                "target": {
                    "direction": "down",
                    "connection": "any",
                    "dungeon_number": None,
                },
            },
            "missing",
        ),
        (
            {
                "kind": "explore_level",
                "level": {"dungeon_number": 0, "dungeon_level": 1},
                "target": None,
            },
            "unexpected",
        ),
        (
            {"kind": "explore_level", "level": {"dungeon_number": 0}},
            "missing",
        ),
        (
            {
                "kind": "approach_oracle",
                "level": {"dungeon_number": 0, "dungeon_level": 7},
                "oracle": [5, 5],
            },
            "unexpected",
        ),
        ({"kind": "approach_oracle"}, "missing"),
        (
            {
                "kind": "stand_on_stairs",
                "target": {
                    "direction": "down",
                    "connection": "any",
                    "dungeon_number": None,
                },
                "extra": 1,
            },
            "unexpected",
        ),
    ],
)
def test_invalid_goals_are_rejected(value: object, match: str) -> None:
    with pytest.raises(ContractError, match=match):
        goal_from_json(value)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ({"dungeon_number": 0, "dungeon_level": 0}, "at least 1"),
        ({"dungeon_number": 16, "dungeon_level": 1}, "at most 15"),
        ({"dungeon_number": True, "dungeon_level": 1}, "must be an integer"),
        ({"dungeon_number": 0}, "missing"),
    ],
)
def test_level_keys_are_bounded_blstats_pairs(value: object, match: str) -> None:
    with pytest.raises(ContractError, match=match):
        LevelKey.from_json(value)


def test_objectives_round_trip_and_bound_their_legs() -> None:
    objective = Objective(
        (
            ReachLevelLeg(LevelKey(0, 3)),
            ReachLevelLeg(LevelKey(0, 1)),
            EnterDungeonLeg(2),
            StandOnStairsLeg(MAIN_DOWN),
        )
    )

    assert Objective.from_json(objective.to_json()) == objective
    assert objective.changes_level
    assert not STAIRCASE_OBJECTIVE.changes_level
    with pytest.raises(ContractError, match="1 to 8 legs"):
        Objective.from_json({"legs": []})
    with pytest.raises(ContractError, match="1 to 8 legs"):
        Objective((EnterDungeonLeg(2),) * 9)
    with pytest.raises(ContractError, match="kind must be one of"):
        Objective.from_json({"legs": [{"kind": "win"}]})


@pytest.mark.parametrize(
    "leg",
    [
        {"kind": "enter_dungeon", "dungeon_number": 3},
        {"kind": "reach_level", "level": {"dungeon_number": 5, "dungeon_level": 1}},
    ],
)
def test_objectives_name_only_dungeons_reachable_by_staircase(leg: object) -> None:
    # The Quest (3) and Fort Ludios (5) are entered by portal.
    with pytest.raises(ContractError, match="no known staircase branch"):
        Objective.from_json({"legs": [leg]})
    assert Objective((EnterDungeonLeg(2),)).legs == (EnterDungeonLeg(2),)
    assert Objective((ReachLevelLeg(LevelKey(4, 1)),)).changes_level


def test_explore_dungeon_legs_name_the_doom_levels_they_require() -> None:
    leg = ExploreDungeonLeg(3)

    assert leg.to_json() == {"kind": "explore_dungeon", "max_level": 3}
    assert Objective.from_json({"legs": [leg.to_json()]}).legs == (leg,)
    assert leg.levels == (LevelKey(0, 1), LevelKey(0, 2), LevelKey(0, 3))
    assert Objective((leg,)).changes_level
    assert ExploreDungeonLeg(32).levels[-1] == LevelKey(0, 32)


@pytest.mark.parametrize(
    ("leg", "match"),
    [
        ({"kind": "explore_dungeon", "max_level": 0}, "at least 1"),
        ({"kind": "explore_dungeon", "max_level": 33}, "at most 32"),
        ({"kind": "explore_dungeon", "max_level": True}, "must be an integer"),
        ({"kind": "explore_dungeon"}, "missing"),
        (
            {"kind": "explore_dungeon", "max_level": 3, "dungeon_number": 0},
            "unexpected",
        ),
    ],
)
def test_explore_dungeon_legs_are_strict(leg: object, match: str) -> None:
    with pytest.raises(ContractError, match=match):
        Objective.from_json({"legs": [leg]})


def test_find_oracle_legs_round_trip_strictly() -> None:
    leg = FindOracleLeg()

    assert leg.to_json() == {"kind": "find_oracle"}
    assert Objective.from_json({"legs": [leg.to_json()]}).legs == (leg,)
    with pytest.raises(ContractError, match="unexpected"):
        Objective.from_json({"legs": [{"kind": "find_oracle", "max_level": 9}]})


@pytest.mark.parametrize(
    ("identity", "match"),
    [
        (
            {"kind": "unknown", "dungeon_number": 0, "evidence": None},
            "no evidence or dungeon_number",
        ),
        (
            {"kind": "main", "dungeon_number": 0, "evidence": None},
            "requires evidence",
        ),
        (
            {"kind": "main", "dungeon_number": None, "evidence": "traversed"},
            "requires its dungeon_number",
        ),
        (
            {"kind": "exit", "dungeon_number": None, "evidence": "traversed"},
            "rule without",
        ),
    ],
)
def test_inconsistent_stair_identities_are_rejected(
    identity: object, match: str
) -> None:
    with pytest.raises(ContractError, match=match):
        StairIdentity.from_json(identity)


def identity(
    kind: StairIdentityKind, dungeon_number: int | None = None
) -> StairIdentity:
    return StairIdentity(kind, dungeon_number, IdentityEvidence.TRAVERSED)


def test_candidate_tiers_prefer_established_matches_and_probe_only_when_allowed() -> (
    None
):
    main = identity(StairIdentityKind.MAIN, 0)
    mines = identity(StairIdentityKind.BRANCH, 2)
    branch_unnumbered = StairIdentity(
        StairIdentityKind.BRANCH, None, IdentityEvidence.ELIMINATION
    )
    any_down = STAND_ON_DOWNSTAIRS.target

    # The staircase goal treats every non-exit staircase alike.
    for stair in (main, mines, UNKNOWN_STAIR):
        assert candidate_tier(any_down, stair, pair_known=False) == 0
    assert candidate_tier(any_down, DUNGEON_EXIT, pair_known=True) is None

    assert candidate_tier(MAIN_DOWN, main, pair_known=False) == 0
    assert candidate_tier(MAIN_DOWN, UNKNOWN_STAIR, pair_known=False) == 1
    assert candidate_tier(MAIN_DOWN, mines, pair_known=True) is None

    assert candidate_tier(MINES_DOWN, mines, pair_known=False) == 0
    assert candidate_tier(MINES_DOWN, branch_unnumbered, pair_known=False) == 1
    assert (
        candidate_tier(
            MINES_DOWN, identity(StairIdentityKind.BRANCH, 4), pair_known=True
        )
        is None
    )
    assert candidate_tier(MINES_DOWN, main, pair_known=True) is None
    # A lone unknown `>` is probably the main staircase; probe for a branch
    # only on a level proven to have two.
    assert candidate_tier(MINES_DOWN, UNKNOWN_STAIR, pair_known=False) is None
    assert candidate_tier(MINES_DOWN, UNKNOWN_STAIR, pair_known=True) == 1
