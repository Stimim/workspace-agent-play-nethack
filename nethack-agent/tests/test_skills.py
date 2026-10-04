from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.burden import BurdenRecovery, drop_candidate
from nethack_agent.coordinator import AgentCoordinator
from nethack_agent.corpse import CorpseKill
from nethack_agent.decision import (
    LEVEL_CHANGE_ACTIONS,
    PRAYER_FIRST_SAFE_TURN,
    PRAYER_REPEAT_WAIT_TURNS,
    ActionIntent,
    ActionSelectionSource,
    DestinationKind,
    IntentDestination,
    MapCell,
    PrayerEvidence,
    RunOutcome,
    Skill,
    StuckReason,
)
from nethack_agent.environment import LegalAction, NleEnvironment, ScenarioConfig
from nethack_agent.foraging import FoodSkill
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.navigation import (
    GOLD_GLYPH,
    MOVE_ACTION_NAMES,
    OSCILLATION_WINDOW,
    ActionKind,
    ActionRecord,
    CellKind,
    DungeonMemory,
    LevelMemory,
    StairLink,
    route_tree,
)
from nethack_agent.observation import (
    BucStatus,
    InventoryItem,
    MapView,
    ObservationProjector,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.skills import (
    SEARCHES_PER_ROUND,
    CorpseSkill,
    ExploreLevelSkill,
    GoldNavigationSkill,
    HungerSkill,
    PrayerSkill,
    SafePromptHandler,
    SkillAction,
    StaircaseNavigationSkill,
    _past_monster,
    is_safe_food_ration,
)
from nethack_agent.traversal import (
    DUNGEON_EXIT,
    UNKNOWN_STAIR,
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

_CMAP = nethack.GLYPH_CMAP_OFF
_MONSTERS = {nethack.permonst(index).mname: index for index in range(nethack.NUMMONS)}
_BOULDER = next(
    index
    for index in range(nethack.NUM_OBJECTS)
    if nethack.OBJ_NAME(nethack.objclass(index)) == "boulder"
)
_FOOD = next(
    index
    for index in range(nethack.NUM_OBJECTS)
    if nethack.OBJ_NAME(nethack.objclass(index)) == "food ration"
)
_GLYPHS = {
    " ": _CMAP,
    "|": _CMAP + 1,
    "-": _CMAP + 2,
    "D": _CMAP + 12,  # doorless doorway
    "O": _CMAP + 13,  # open door
    "+": _CMAP + 15,  # closed door
    ".": _CMAP + 19,
    "#": _CMAP + 21,
    "<": _CMAP + 23,
    ">": _CMAP + 24,
    "_": _CMAP + 27,
    "0": nethack.GLYPH_OBJ_OFF + _BOULDER,
    "%": nethack.GLYPH_OBJ_OFF + _FOOD,
    "$": GOLD_GLYPH,
    "j": nethack.GLYPH_MON_OFF + _MONSTERS["jackal"],
    "e": nethack.GLYPH_MON_OFF + _MONSTERS["floating eye"],
    "f": nethack.GLYPH_PET_OFF + _MONSTERS["kitten"],
    "Q": nethack.GLYPH_MON_OFF + _MONSTERS["Oracle"],
    "@": nethack.GLYPH_MON_OFF + _MONSTERS["valkyrie"],
}


@pytest.fixture
def template(tmp_path: Path) -> ProjectedObservation:
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    try:
        return ObservationProjector().project(environment.reset(), step_index=0)
    finally:
        environment.close()


@pytest.fixture
def actions(tmp_path: Path) -> dict[str, LegalAction]:
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path / "actions")
    )
    try:
        return {
            action.name: action
            for action in environment.legal_actions
            if action.name not in LEVEL_CHANGE_ACTIONS
        }
    finally:
        environment.close()


def sketch(
    template: ProjectedObservation,
    lines: tuple[str, ...],
    *,
    step: int = 0,
    message: str = "",
    prompt: PromptState | None = None,
    dungeon_level: int = 1,
    dungeon_number: int = 0,
) -> ProjectedObservation:
    """Build an observation from an ASCII map; `@` marks the hero."""
    width = max(len(line) for line in lines)
    rows = [line.ljust(width) for line in lines]
    hero = next(
        (x, y)
        for y, row in enumerate(rows)
        for x, char in enumerate(row)
        if char == "@"
    )
    return ProjectedObservation(
        step_index=step,
        map=MapView(
            rows=tuple(rows),
            glyph_rows=tuple(tuple(_GLYPHS[char] for char in row) for row in rows),
            color_rows=tuple(bytes(width) for _ in rows),
            special_rows=tuple(bytes(width) for _ in rows),
            pet_rows=tuple(
                bytes(int(bool(nethack.glyph_is_pet(_GLYPHS[char]))) for char in row)
                for row in rows
            ),
        ),
        changed_cells=(),
        player=replace(
            template.player,
            x=hero[0],
            y=hero[1],
            dungeon_number=dungeon_number,
            dungeon_level=dungeon_level,
        ),
        message=message,
        prompt=prompt or PromptState(False, False, False),
        inventory=template.inventory,
    )


def remembered(template: ProjectedObservation, *frames: tuple[str, ...]) -> LevelMemory:
    memory = LevelMemory()
    for step, lines in enumerate(frames):
        memory.observe(sketch(template, lines, step=step))
    return memory


def action_name(actions: dict[str, LegalAction], index: int | None) -> str | None:
    return next(
        (name for name, action in actions.items() if action.index == index), None
    )


def cells(*points: tuple[int, int]) -> tuple[MapCell, ...]:
    return tuple(MapCell(*point) for point in points)


def assert_followed_route(action: SkillAction, hero: tuple[int, int]) -> None:
    """The recorded route starts with the cell the action moves into."""
    assert action.intent is not None
    path = action.intent.path
    assert path is not None
    first = path[0]
    assert max(abs(first.x - hero[0]), abs(first.y - hero[1])) == 1
    assert (first.x, first.y) == action.record.target
    assert (path[-1].x, path[-1].y) == action.record.goal


def test_staircase_skill_routes_multiple_steps_then_waits_on_target(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = StaircaseNavigationSkill()
    downstairs = IntentDestination(
        DestinationKind.DOWNSTAIRS, 5, 1, UNKNOWN_STAIR, False
    )
    names = []
    for hero, row in ((2, "|.@..>|"), (3, "|..@.>|"), (4, "|...@>|")):
        memory = remembered(template, ("-------", row, "-------"))
        proposal = skill.select_action(memory, actions)
        assert proposal is not None
        names.append(action_name(actions, proposal.action_index))
        # The intent names the remembered `>`, not the cell stepped into, and
        # the remaining route to it.
        assert proposal.intent == ActionIntent(
            downstairs, None, cells(*((x, 1) for x in range(hero + 1, 6)))
        )
        assert_followed_route(proposal, (hero, 1))
    # Memory keeps the `>` the hero now hides.
    memory = remembered(
        template,
        ("-------", "|...@>|", "-------"),
        ("-------", "|....@|", "-------"),
    )
    on_stairs = skill.select_action(memory, actions)

    assert names == [
        "CompassDirection.E",
        "CompassDirection.E",
        "CompassDirection.E",
    ]
    assert on_stairs is not None
    assert action_name(actions, on_stairs.action_index) == "MiscDirection.WAIT"
    # Waiting follows no route.
    assert on_stairs.intent == ActionIntent(downstairs, None, None)


def test_staircase_skill_uses_route_distance_then_row_and_column_for_multiple_stairs(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(
        template,
        (
            "---------",
            "|>.....>|",
            "|...@...|",
            "|>......|",
            "---------",
        ),
    )

    proposal = StaircaseNavigationSkill().select_action(memory, actions)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.W"
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 1, 1, UNKNOWN_STAIR, True),
        None,
        cells((3, 2), (2, 2), (1, 1)),
    )


_DOWN_ACTION = LegalAction(18, ord(">"), "MiscDirection.DOWN")
_MAIN_DOWN = TraverseStairsGoal(
    StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
)
_MINES_DOWN = TraverseStairsGoal(
    StairTarget(StairDirection.DOWN, StairConnection.BRANCH, 2)
)


def test_traversal_goal_uses_the_matching_staircase_under_the_hero(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("|.>...|", "|.@...|"))
    memory.observe(sketch(template, ("|.@...|", "|.....|"), step=1))
    skill = StaircaseNavigationSkill()

    proposal = skill.select_action(memory, actions, _MAIN_DOWN, _DOWN_ACTION)

    assert proposal is not None
    assert proposal.action_index == _DOWN_ACTION.index
    assert proposal.record == ActionRecord(ActionKind.TRAVERSE, (2, 0))
    # The use happens in place: the intent names the staircase and its
    # believed identity, with no route.
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 2, 0, UNKNOWN_STAIR, False),
        None,
        None,
    )
    # Without the level-change action there is nothing to propose, and a
    # standing goal waits instead.
    assert skill.select_action(memory, actions, _MAIN_DOWN, None) is None
    wait = skill.select_action(memory, actions)
    assert wait is not None
    assert action_name(actions, wait.action_index) == "MiscDirection.WAIT"


def test_traversal_ranks_established_stairs_before_probes_and_skips_mismatches(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("|>.@....>|",))
    skill = StaircaseNavigationSkill()
    # Two `>` are known and neither is established: the nearer one is probed
    # for the main staircase.
    probe = skill.select_action(memory, actions, _MAIN_DOWN, _DOWN_ACTION)
    assert probe is not None and probe.intent is not None
    # The intent records that both `>` were known: the evidence that lets an
    # unknown staircase be probed as a branch.
    assert probe.intent.destination == IntentDestination(
        DestinationKind.DOWNSTAIRS, 1, 0, UNKNOWN_STAIR, True
    )

    # Once the far `>` is known to be the Mines branch, the near one is main
    # by elimination; each goal takes its own staircase.
    memory.stair_identities[(8, 0)] = StairIdentity(
        StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED
    )
    main = skill.select_action(memory, actions, _MAIN_DOWN, _DOWN_ACTION)
    mines = skill.select_action(memory, actions, _MINES_DOWN, _DOWN_ACTION)
    assert main is not None and main.intent is not None
    assert mines is not None and mines.intent is not None
    assert main.intent.destination == IntentDestination(
        DestinationKind.DOWNSTAIRS,
        1,
        0,
        StairIdentity(StairIdentityKind.MAIN, 0, IdentityEvidence.ELIMINATION),
        True,
    )
    assert mines.intent.destination == IntentDestination(
        DestinationKind.DOWNSTAIRS,
        8,
        0,
        StairIdentity(StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED),
        True,
    )

    # A lone unknown `>` is never probed for a branch.
    lone = remembered(template, ("|.@....>|",))
    assert skill.select_action(lone, actions, _MINES_DOWN, _DOWN_ACTION) is None


def test_upstairs_goals_route_to_and_wait_on_the_upstairs(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    up = StandOnStairsGoal(StairTarget(StairDirection.UP, StairConnection.ANY, None))
    skill = StaircaseNavigationSkill()
    # On (0, 1) the only `<` is the dungeon exit, which no goal may target.
    top = remembered(template, ("|<..@.>|",))
    assert skill.select_action(top, actions, up) is None
    memory = LevelMemory()
    memory.observe(sketch(template, ("|<..@.>|",), dungeon_level=2))

    proposal = skill.select_action(memory, actions, up)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.W"
    assert proposal.intent is not None and proposal.intent.destination is not None
    assert proposal.intent.destination.kind is DestinationKind.UPSTAIRS
    assert (proposal.intent.destination.x, proposal.intent.destination.y) == (1, 0)


def test_staircase_defense_keeps_the_chosen_downstairs_as_destination(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("-------", "|.j...|", "|@...>|", "-------"))

    proposal = StaircaseNavigationSkill().select_action(memory, actions)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.NE"
    # The attack leaves the route, so no path is recorded for this step.
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 5, 2, UNKNOWN_STAIR, False),
        MapCell(2, 1),
        None,
    )


@pytest.mark.parametrize(
    ("goal", "level_change"),
    [
        (
            StandOnStairsGoal(
                StairTarget(StairDirection.DOWN, StairConnection.ANY, None)
            ),
            None,
        ),
        (_MAIN_DOWN, _DOWN_ACTION),
    ],
)
def test_staircase_skill_fights_before_waiting_or_traversing_from_stairs(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    goal: StandOnStairsGoal | TraverseStairsGoal,
    level_change: LegalAction | None,
) -> None:
    memory = remembered(
        template,
        ("|>j@|",),
        ("|@j.|",),
    )

    proposal = StaircaseNavigationSkill().select_action(
        memory, actions, goal, level_change
    )

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.E"
    assert proposal.record.kind is ActionKind.MOVE
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 1, 0, UNKNOWN_STAIR, False),
        MapCell(2, 0),
        None,
    )


def test_exploration_intent_names_the_frontier_route_goal(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, (" --------- ", " |@......D ", " --------- "))

    result = ExploreLevelSkill().select_action(memory, actions)

    assert result.action is not None
    assert action_name(actions, result.action.action_index) == "CompassDirection.E"
    assert result.action.record.target == (3, 1)
    # Seven steps away: the doorway facing never-observed space.
    assert result.action.intent == ActionIntent(
        IntentDestination(DestinationKind.FRONTIER, 9, 1),
        None,
        cells(*((x, 1) for x in range(3, 10))),
    )
    assert_followed_route(result.action, (2, 1))


def test_route_bends_around_a_boulder_and_through_an_open_door(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(
        template,
        (
            "------ ",
            "|@0..| ",
            "|....| ",
            "---O-- ",
            "   #   ",
            "   #>  ",
        ),
    )

    proposal = StaircaseNavigationSkill().select_action(memory, actions)

    assert proposal is not None
    assert proposal.intent is not None
    # The door is passed orthogonally; the first step bends diagonally past
    # the boulder.
    assert proposal.intent.path == cells((2, 2), (3, 2), (3, 3), (3, 4), (4, 5))
    assert_followed_route(proposal, (1, 1))


def test_monster_blocked_route_is_recorded_while_approaching_not_waiting(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = StaircaseNavigationSkill()
    downstairs = IntentDestination(
        DestinationKind.DOWNSTAIRS, 5, 1, UNKNOWN_STAIR, False
    )

    # Memory keeps the floor a monster later stands on.
    seen = ("-------", "|@...>|", "-------")
    far = remembered(template, seen, ("-------", "|@.e.>|", "-------"))
    approach = skill.select_action(far, actions)
    near = remembered(template, seen, ("-------", "|.@e.>|", "-------"))
    wait = skill.select_action(near, actions)

    assert approach is not None
    assert "monster currently blocks" in approach.rationale
    # The route runs through the floating eye that blocks it further ahead.
    assert approach.intent == ActionIntent(
        downstairs, None, cells((2, 1), (3, 1), (4, 1), (5, 1))
    )
    assert_followed_route(approach, (1, 1))
    assert wait is not None
    assert action_name(actions, wait.action_index) == "Command.SEARCH"
    assert wait.intent == ActionIntent(downstairs, None, None)

    # Attacking a hostile blocker steps into the route's first cell. Adjacent-
    # hostile defense normally runs first, so call the route branch directly.
    hostile = remembered(template, seen, ("-------", "|.@j.>|", "-------"))
    attack = _past_monster(
        hostile,
        route_tree(hostile, through_monsters=True),
        actions,
        (5, 1),
        "downstairs",
        downstairs,
    )
    assert attack is not None
    assert attack.intent == ActionIntent(
        downstairs, MapCell(3, 1), cells((3, 1), (4, 1), (5, 1))
    )


def test_staircase_skill_routes_around_monsters_and_boulders(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    for blocker in ("0", "e"):
        memory = remembered(
            template,
            (
                "-------",
                "|.....|",
                f"|@{blocker}..>|",
                "|.....|",
                "-------",
            ),
        )

        proposal = StaircaseNavigationSkill().select_action(memory, actions)

        assert proposal is not None
        # Diagonal steps past a monster or boulder are legal NetHack moves.
        assert action_name(actions, proposal.action_index) in {
            "CompassDirection.NE",
            "CompassDirection.SE",
        }


def test_doorway_diagonal_rules_follow_nethack_test_move(
    template: ProjectedObservation,
) -> None:
    # NetHack 3.6 test_move: no diagonal move into or out of a doorway unless
    # it is doorless (no door or a broken door). Closed doors open orthogonally.
    for door, diagonal_allowed in (("D", True), ("O", False), ("+", False)):
        memory = remembered(
            template,
            (
                "  #   ",
                f"--{door}---",
                "|@...|",
                "------",
            ),
        )
        into = memory.step_allowed((1, 2), (2, 1))
        out_of = memory.step_allowed((2, 1), (1, 0))
        assert into is diagonal_allowed, door
        assert out_of is diagonal_allowed, door
        assert memory.step_allowed((2, 2), (2, 1)), door

    # A dwarven Valkyrie may squeeze diagonally between two rock cells.
    squeeze = remembered(template, ("@  ", " # ", "  #"))
    assert squeeze.step_allowed((0, 0), (1, 1))
    assert (2, 2) in route_tree(squeeze).distances


def test_route_through_open_door_uses_only_orthogonal_steps(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    lines = (
        "------",
        "|@...|",
        "|....|",
        "---O--",
        "   #  ",
        "   #>",
    )
    memory = remembered(template, lines)
    tree = route_tree(memory)
    path = [(4, 5)]
    while tree.parents[path[-1]] is not None:
        path.append(tree.parents[path[-1]])  # type: ignore[arg-type]
    path.reverse()

    door = path.index((3, 3))
    for before, after in ((path[door - 1], (3, 3)), ((3, 3), path[door + 1])):
        assert before[0] == after[0] or before[1] == after[1]
    assert StaircaseNavigationSkill().select_action(memory, actions) is not None


def test_exploration_targets_nearest_frontier_and_opens_closed_doors(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = ExploreLevelSkill()
    memory = remembered(
        template,
        (
            "           ",
            " --------- ",
            " |.......| ",
            " |......@+ ",
            " |.......| ",
            " ----D---- ",
            "           ",
        ),
    )

    opened = skill.select_action(memory, actions)

    assert opened.action is not None
    assert action_name(actions, opened.action.action_index) == "CompassDirection.E"
    assert opened.action.record.kind is ActionKind.OPEN_DOOR
    assert opened.action.record.target == (9, 3)


def test_locked_door_is_avoided_then_kicked_when_it_is_the_only_way(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = ExploreLevelSkill()

    def room(door: str) -> tuple[str, ...]:
        return ("        ", " -----  ", f" |..@{door}  ", " -----  ", "        ")

    memory = LevelMemory()
    memory.observe(sketch(template, room("+"), step=0))
    tried = skill.select_action(memory, actions)
    assert tried.action is not None
    assert tried.action.record.kind is ActionKind.OPEN_DOOR
    memory.record(tried.action.record)
    memory.observe(sketch(template, room("+"), step=1, message="This door is locked."))

    kick = skill.select_action(memory, actions)

    # Kicking happens in place, so neither the kick nor its direction follows
    # a route.
    door = ActionIntent(
        IntentDestination(DestinationKind.LOCKED_DOOR, 5, 2), None, None
    )
    assert (5, 2) in memory.locked_doors
    assert kick.action is not None
    assert action_name(actions, kick.action.action_index) == "Command.KICK"
    assert kick.action.intent == door
    memory.record(kick.action.record)
    prompt = sketch(
        template,
        room("+"),
        step=2,
        message="In what direction?",
        prompt=PromptState(True, False, False),
    )
    memory.observe(prompt)
    direction = skill.continue_kick(prompt, memory, actions)
    assert direction is not None
    assert action_name(actions, direction.action_index) == "CompassDirection.E"
    assert direction.intent == door
    memory.record(direction.record)
    memory.observe(
        sketch(
            template,
            room("f"),
            step=3,
            message="As you kick the door, it crashes open!",
        )
    )
    # The pet now hides the broken door; memory still knows it is doorless.
    assert memory.kind((5, 2)) is CellKind.DOORWAY
    assert (5, 2) not in memory.locked_doors


def test_route_to_a_locked_door_ends_beside_it(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(
        template, ("        ", " -----  ", " |@..+  ", " -----  ", "        ")
    )
    memory.locked_doors.add((5, 2))

    result = ExploreLevelSkill().select_action(memory, actions)

    assert result.action is not None
    # The destination is the door; the route ends where the hero kicks it.
    assert result.action.intent == ActionIntent(
        IntentDestination(DestinationKind.LOCKED_DOOR, 5, 2),
        None,
        cells((3, 2), (4, 2)),
    )
    assert_followed_route(result.action, (2, 2))


def test_exploration_attacks_adjacent_hostiles_but_not_passive_or_pets(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = ExploreLevelSkill()

    def frame(east: str) -> tuple[str, ...]:
        return (
            "       ",
            " ----- ",
            f" |.@{east}# ",
            " |.e.| ",
            " |.f.| ",
            " ----- ",
            "       ",
        )

    hostile = skill.select_action(remembered(template, frame("j")), actions)
    quiet = skill.select_action(remembered(template, frame(".")), actions)

    assert hostile.action is not None
    assert action_name(actions, hostile.action.action_index) == "CompassDirection.E"
    assert hostile.action.record.target_glyph == _GLYPHS["j"]
    # Exploration fights before choosing a frontier, so there is no destination.
    assert hostile.action.intent == ActionIntent(None, MapCell(4, 2), None)
    # The floating eye and the kitten are left alone; exploration continues.
    assert quiet.action is not None
    assert quiet.action.record.target_glyph is None
    assert quiet.action.record.goal == (5, 2)
    assert quiet.action.intent == ActionIntent(
        IntentDestination(DestinationKind.FRONTIER, 5, 2), None, cells((4, 2), (5, 2))
    )


def test_oracle_is_never_treated_as_an_adjacent_hostile(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("|@Q.>|",))

    proposal = StaircaseNavigationSkill().select_action(memory, actions)

    assert memory.hostile_blocker((2, 0)) is None
    if proposal is not None:
        assert action_name(actions, proposal.action_index) != "CompassDirection.E"
        assert proposal.intent is not None
        assert proposal.intent.attack_target is None


def test_gold_glyph_is_the_gold_piece_object() -> None:
    assert GOLD_GLYPH == nethack.GLYPH_OBJ_OFF + 410
    assert nethack.glyph_is_object(GOLD_GLYPH)
    assert nethack.glyph_to_obj(GOLD_GLYPH) == 410
    assert nethack.OBJ_NAME(nethack.objclass(410)) == "gold piece"


def test_gold_cells_are_rederived_from_every_observation(
    template: ProjectedObservation,
) -> None:
    memory = remembered(template, ("|@.$%.$|",))
    assert memory.gold == frozenset({(3, 0), (6, 0)})
    # Food is an object but not gold.
    assert (4, 0) in memory.objects

    # Gold that stops being displayed is forgotten at once, even when the
    # hero never saw it picked up.
    memory.observe(sketch(template, ("|.@.%.$|",), step=1))
    memory.observe(sketch(template, ("|..@%..|",), step=2))
    assert memory.gold == frozenset()


def test_gold_skill_routes_to_nearest_gold_breaking_ties_by_row_then_column(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = GoldNavigationSkill()
    # Gold at (1, 1), (5, 1), (1, 3), and (5, 3) is two steps away; the lowest
    # row wins, then the lowest column. (7, 2) is four steps away.
    memory = remembered(
        template,
        (
            "---------",
            "|$...$..|",
            "|..@...$|",
            "|$...$..|",
            "---------",
        ),
    )

    proposal = skill.select_action(memory, actions)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.W"
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.GOLD, 1, 1), None, cells((2, 2), (1, 1))
    )
    assert_followed_route(proposal, (3, 2))
    # A strictly nearer gold wins over row and column.
    near = remembered(template, ("|$..@.$|",))
    nearest = skill.select_action(near, actions)
    assert nearest is not None
    assert nearest.intent is not None
    assert nearest.intent.destination == IntentDestination(DestinationKind.GOLD, 6, 0)


def test_gold_skill_needs_reachable_displayed_gold(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = GoldNavigationSkill()

    assert skill.select_action(remembered(template, ("|@...|",)), actions) is None
    # Gold behind a wall is not reachable.
    walled = remembered(template, ("|@.|$|",))
    assert walled.gold == frozenset({(4, 0)})
    assert skill.select_action(walled, actions) is None


def test_gold_skill_fights_an_adjacent_hostile_first(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("|j@..$|",))

    proposal = GoldNavigationSkill().select_action(memory, actions)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.W"
    assert proposal.record.target_glyph == _GLYPHS["j"]
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.GOLD, 5, 0), MapCell(1, 0), None
    )


def test_object_in_dark_corridor_is_passable_and_door_under_hero_is_open(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    # A monster hid this corridor square; after it died only its corpse shows.
    memory = remembered(template, ("@#%  ",))
    assert memory.kind((2, 0)) is CellKind.FLOOR
    result = ExploreLevelSkill().select_action(memory, actions)
    assert result.action is not None
    assert result.action.record.goal == (2, 0)

    door = remembered(
        template,
        ("|.+.", "|@.."),
        ("|.@.", "|..."),
    )
    assert door.kind((2, 0)) is CellKind.OPEN_DOOR


def test_search_rotates_spots_then_reports_exhaustion(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    skill = ExploreLevelSkill()
    lines = ("       ", "  ---- ", "  |@.| ", "  ---- ", "       ")
    memory = LevelMemory()
    step = 0
    memory.observe(sketch(template, lines, step=step))
    searches = 0
    spots: set[tuple[int, int]] = set()
    while True:
        result = skill.select_action(memory, actions)
        if result.action is None:
            break
        record = result.action.record
        assert record.search_spot is not None
        spot = IntentDestination(DestinationKind.SEARCH_SPOT, *record.search_spot)
        if record.kind is ActionKind.SEARCH:
            assert result.action.intent == ActionIntent(spot, None, None)
        else:
            assert result.action.intent == ActionIntent(
                spot, None, cells(record.search_spot)
            )
            assert_followed_route(result.action, record.origin)
        if record.kind is ActionKind.SEARCH:
            searches += 1
            spots.add(record.origin)
        else:
            hero = record.target
            assert hero is not None
            lines = tuple(
                line.replace("@", ".") if index == 2 else line
                for index, line in enumerate(lines)
            )
            row = list(lines[2])
            row[hero[0]] = "@"
            lines = (*lines[:2], "".join(row), *lines[3:])
        memory.record(record)
        step += 1
        memory.observe(sketch(template, lines, step=step))
        assert step < 200

    assert result.stuck is StuckReason.SEARCH_EXHAUSTED
    # Each floor cell faces walls the other cannot cover, so both are used.
    assert spots == {(3, 2), (4, 2)}
    assert searches == 2 * SEARCHES_PER_ROUND

    memory.rearm()
    again = skill.select_action(memory, actions)
    assert again.action is not None
    assert again.action.record.kind is ActionKind.SEARCH


def test_learned_edges_and_oscillation_abandon_goals(
    template: ProjectedObservation,
) -> None:
    lines = ("-----", "|@..|", "-----")
    memory = LevelMemory()
    memory.observe(sketch(template, lines, step=0))
    memory.record(ActionRecord(ActionKind.MOVE, (1, 1), (2, 1), goal=(3, 1)))
    memory.observe(sketch(template, lines, step=1, message="It's a wall."))
    assert not memory.step_allowed((1, 1), (2, 1))

    generic = LevelMemory()
    generic.observe(sketch(template, lines, step=0))
    for step in range(1, 4):
        generic.record(ActionRecord(ActionKind.MOVE, (1, 1), (2, 1)))
        generic.observe(sketch(template, lines, step=step))
    assert not generic.step_allowed((1, 1), (2, 1))
    generic.rearm()
    assert generic.step_allowed((1, 1), (2, 1))

    wobble = LevelMemory()
    frames = (("-----", "|@..|", "-----"), ("-----", "|.@.|", "-----"))
    wobble.observe(sketch(template, frames[0], step=0))
    for step in range(1, OSCILLATION_WINDOW + 3):
        origin = (1, 1) if step % 2 else (2, 1)
        target = (2, 1) if step % 2 else (1, 1)
        wobble.record(ActionRecord(ActionKind.MOVE, origin, target, goal=(3, 1)))
        wobble.observe(sketch(template, frames[step % 2], step=step))
        if (3, 1) in wobble.abandoned_goals:
            break
    assert (3, 1) in wobble.abandoned_goals
    assert step == OSCILLATION_WINDOW


def test_dungeon_memory_restores_levels_and_clears_only_the_previous_visit(
    template: ProjectedObservation,
) -> None:
    dungeon = DungeonMemory()
    first = dungeon.observe(sketch(template, ("|@..|",), step=0))
    first.record(ActionRecord(ActionKind.SEARCH, (1, 0)))
    first.blocked_edges.add(((1, 0), (2, 0)))
    first.suspect_edges.add(((2, 0), (3, 0)))
    first.abandoned_goals.add((3, 0))
    first.stuck_consult_step = 0

    # A level change with no stair action (a trap door, hole, or teleport)
    # gets its own memory and records no link.
    second = dungeon.observe(sketch(template, ("|.@|",), step=1, dungeon_level=2))
    assert second is not first
    assert second.level == LevelKey(0, 2)
    assert second.visited == {(2, 0)}
    assert not second.search_coverage
    assert not first.links and not second.links

    back = dungeon.observe(sketch(template, ("|.@.|",), step=2))
    assert back is first
    assert dungeon.levels.keys() == {LevelKey(0, 1), LevelKey(0, 2)}
    # Persistent level knowledge survives the visit to another level...
    assert back.search_coverage
    assert back.visited == {(1, 0), (2, 0)}
    assert ((1, 0), (2, 0)) in back.blocked_edges
    # ...while the previous visit's routing state is gone.
    assert not back.suspect_edges
    assert not back.abandoned_goals
    assert back.stuck_consult_step is None
    assert back.position == (2, 0)


def test_stair_traversal_links_both_levels_and_establishes_identities(
    template: ProjectedObservation,
) -> None:
    dungeon = DungeonMemory()
    doom = dungeon.observe(sketch(template, ("|.>.@>|",), step=0, dungeon_level=2))
    down = doom.stairs(StairDirection.DOWN)
    assert down == ((2, 0), (5, 0))
    assert doom.pair_known(StairDirection.DOWN)
    assert {doom.identity(stair) for stair in down} == {UNKNOWN_STAIR}

    doom = dungeon.observe(sketch(template, ("|.>..@|",), step=1, dungeon_level=2))
    doom.record(ActionRecord(ActionKind.TRAVERSE, (5, 0)))
    # NLE shows the hero on the arrival staircase, never the staircase itself.
    mines = dungeon.observe(
        sketch(template, ("|..@.|",), step=2, dungeon_number=2, dungeon_level=1)
    )

    assert mines.level == LevelKey(2, 1)
    assert mines.stairs(StairDirection.UP) == ((3, 0),)
    assert mines.identity((3, 0)) == StairIdentity(
        StairIdentityKind.BRANCH, 0, IdentityEvidence.ARRIVAL
    )
    assert mines.links[(3, 0)] == StairLink(LevelKey(0, 2), (5, 0))
    assert doom.identity((5, 0)) == StairIdentity(
        StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED
    )
    assert doom.links[(5, 0)] == StairLink(LevelKey(2, 1), (3, 0))
    # The other `>` on this Mines-entrance level is the main staircase.
    assert doom.identity((2, 0)) == StairIdentity(
        StairIdentityKind.MAIN, 0, IdentityEvidence.ELIMINATION
    )

    mines.record(ActionRecord(ActionKind.TRAVERSE, (3, 0)))
    doom = dungeon.observe(sketch(template, ("|.>..@|",), step=3, dungeon_level=2))
    assert doom.position == (5, 0)
    assert dungeon.current is doom
    # Returning keeps the stronger traversal evidence on both staircases.
    assert doom.identity((5, 0)) == StairIdentity(
        StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED
    )
    assert mines.identity((3, 0)) == StairIdentity(
        StairIdentityKind.BRANCH, 0, IdentityEvidence.TRAVERSED
    )


def test_main_traversal_and_rules_identify_the_remaining_stairs(
    template: ProjectedObservation,
) -> None:
    dungeon = DungeonMemory()
    top = dungeon.observe(sketch(template, ("|<.@>.|",), step=0))
    # `dungeon.def` places the one-way exit branch on `<` of (0, 1).
    assert top.identity((1, 0)) == DUNGEON_EXIT
    assert top.identity((4, 0)) == UNKNOWN_STAIR

    top = dungeon.observe(sketch(template, ("|<..@.|",), step=1))
    top.record(ActionRecord(ActionKind.TRAVERSE, (4, 0)))
    level_two = dungeon.observe(sketch(template, ("|>.@>|",), step=2, dungeon_level=2))
    assert top.identity((4, 0)) == StairIdentity(
        StairIdentityKind.MAIN, 0, IdentityEvidence.TRAVERSED
    )
    assert level_two.identity((3, 0)) == StairIdentity(
        StairIdentityKind.MAIN, 0, IdentityEvidence.ARRIVAL
    )
    # Two unknown `>` on DL2: neither is established until one is used.
    assert level_two.identity((1, 0)) == UNKNOWN_STAIR
    assert level_two.identity((4, 0)) == UNKNOWN_STAIR

    # A non-stair action followed by a level change links nothing.
    level_two.record(ActionRecord(ActionKind.WAIT, (3, 0)))
    fallen = dungeon.observe(sketch(template, ("|.@|",), step=3, dungeon_level=3))
    assert not fallen.links
    assert fallen.stairs(StairDirection.UP) == ()


def test_look_here_message_reveals_a_staircase_under_an_object(
    template: ProjectedObservation,
) -> None:
    memory = LevelMemory()
    memory.observe(sketch(template, ("|@%.|",), step=0))
    assert memory.stairs(StairDirection.DOWN) == ()
    memory.observe(
        sketch(
            template,
            ("|.@.|",),
            step=1,
            message="There is a staircase down here.  You see here 2 food rations.",
        )
    )
    assert memory.stairs(StairDirection.DOWN) == ((2, 0),)
    assert memory.kind((2, 0)) is CellKind.DOWNSTAIRS

    memory.observe(
        sketch(template, ("|@..|",), step=2, message="There is a staircase up here.")
    )
    assert memory.stairs(StairDirection.UP) == ((1, 0),)
    assert memory.stair_direction((1, 0)) is StairDirection.UP


def test_level_memory_observes_only_its_own_level(
    template: ProjectedObservation,
) -> None:
    memory = LevelMemory()
    memory.observe(sketch(template, ("|@.|",), step=0))
    with pytest.raises(ValueError, match="cannot observe level"):
        memory.observe(sketch(template, ("|.@|",), step=1, dungeon_level=2))


@pytest.mark.parametrize("seed", [2, 4, 58])
def test_development_policy_explores_real_levels_to_the_downstairs(
    tmp_path: Path, seed: int
) -> None:
    agent = AgentCoordinator(
        NleEnvironment(
            ScenarioConfig(
                seed=seed, artifact_directory=tmp_path, max_episode_steps=300
            )
        ),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    agent.start()
    agent.resume()
    records = []
    while not records or records[-1].outcome is None:
        record = agent.advance()
        assert record is not None
        records.append(record)

    assert records[-1].outcome is RunOutcome.TASK_SUCCESS
    assert len(records) > 20
    assert all(
        record.selection.source is not ActionSelectionSource.MODEL_FALLBACK
        and record.action.name not in LEVEL_CHANGE_ACTIONS
        for record in records
    )
    assert {record.selection.skill for record in records} == {
        Skill.STAIRCASE_NAVIGATION,
        Skill.EXPLORE_LEVEL,
    }
    routed = 0
    for record in records:
        intent = record.selection.intent
        if intent is None or intent.path is None:
            continue
        routed += 1
        # The recorded route starts with the move this step actually made.
        first = intent.path[0]
        hero = (record.before.player.x, record.before.player.y)
        delta = (first.x - hero[0], first.y - hero[1])
        assert MOVE_ACTION_NAMES.get(delta) == record.action.name
        after = (record.after.player.x, record.after.player.y)
        if record.outcome is None and after != hero:
            assert after == (first.x, first.y)
    assert routed > len(records) // 2
    if seed == 58:
        # Seed 58 starts in a closed room whose only door is locked.
        assert any("crashes open" in record.after.message for record in records)
        assert any(record.action.name == "Command.KICK" for record in records)


def test_safe_prompt_handler_acknowledges_or_declines_only_known_prompts(
    template: ProjectedObservation, tmp_path: Path
) -> None:
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path / "prompt")
    )
    try:
        by_name = {action.name: action for action in environment.legal_actions}
        by_command = {action.command: action for action in environment.legal_actions}

        wait = SafePromptHandler.select_action(
            replace(template, prompt=PromptState(False, False, True)),
            by_name,
            by_command,
        )
        text = SafePromptHandler.select_action(
            replace(template, prompt=PromptState(False, True, False)),
            by_name,
            by_command,
        )
        decline = SafePromptHandler.select_action(
            replace(
                template,
                prompt=PromptState(True, False, False),
                message="Really attack the peaceful dwarf? [yn]",
            ),
            by_name,
            by_command,
        )
        ambiguous = SafePromptHandler.select_action(
            replace(
                template,
                prompt=PromptState(True, False, False),
                message="In what direction?",
            ),
            by_name,
            by_command,
        )
    finally:
        environment.close()

    assert wait is not None
    assert by_name["MiscAction.MORE"].index == wait.action_index
    assert text is not None
    assert by_name["MiscAction.MORE"].index == text.action_index
    assert decline is not None
    assert by_command[ord("n")].index == decline.action_index
    assert ambiguous is None


_HUNGER_ACTION_TABLE = (
    LegalAction(0, ord("e"), "Command.EAT"),
    LegalAction(1, 27, "Command.ESC"),
    LegalAction(2, ord("d"), "Command.DROP"),
    LegalAction(3, ord("h"), "CompassDirection.W"),
    LegalAction(4, ord("n"), "CompassDirection.SE"),
    LegalAction(5, ord("q"), "Command.QUAFF"),
    LegalAction(6, ord("z"), "Command.ZAP"),
)
_HUNGER_BY_NAME = {action.name: action for action in _HUNGER_ACTION_TABLE}
_HUNGER_BY_COMMAND = {action.command: action for action in _HUNGER_ACTION_TABLE}


def _ration(
    template: ProjectedObservation,
    *,
    letter: str = "d",
    description: str = "an uncursed food ration",
    buc: BucStatus = BucStatus.UNCURSED,
) -> InventoryItem:
    return replace(
        template.inventory[0],
        letter=letter,
        description=description,
        glyph=nethack.GLYPH_OBJ_OFF + _FOOD,
        object_class=int(nethack.FOOD_CLASS),
        buc=buc,
    )


@pytest.mark.parametrize(
    ("hunger", "acts"), [(0, False), (1, False), (2, True), (4, True)]
)
def test_hunger_skill_starts_only_at_hungry_or_worse(
    template: ProjectedObservation, hunger: int, acts: bool
) -> None:
    observation = replace(
        template,
        player=replace(template.player, hunger=hunger),
        inventory=(_ration(template),),
    )

    proposal = HungerSkill().select_action(
        observation, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND
    )

    assert (proposal is not None) is acts
    if proposal is not None:
        assert proposal.action_index == _HUNGER_BY_NAME["Command.EAT"].index


@pytest.mark.parametrize(
    ("description", "buc", "safe"),
    [
        ("a food ration", BucStatus.UNKNOWN, True),
        ("an uncursed food ration", BucStatus.UNCURSED, True),
        ("2 blessed +0 food rations", BucStatus.BLESSED, True),
        ("the cursed -1 food ration", BucStatus.CURSED, True),
        ("food ration", BucStatus.UNKNOWN, False),
        ("a partly eaten food ration", BucStatus.UNKNOWN, True),
        ("a lichen corpse", BucStatus.UNKNOWN, False),
        ("an uncursed food ration", BucStatus.UNKNOWN, False),
    ],
)
def test_safe_ration_recognition_is_exact_and_uses_buc_evidence(
    template: ProjectedObservation,
    description: str,
    buc: BucStatus,
    safe: bool,
) -> None:
    assert (
        is_safe_food_ration(_ration(template, description=description, buc=buc)) is safe
    )


@pytest.mark.parametrize(
    ("current_letter", "action_name"),
    [("q", "Command.QUAFF"), ("h", "CompassDirection.W")],
)
def test_hunger_skill_answers_with_the_rations_current_offered_letter(
    template: ProjectedObservation, current_letter: str, action_name: str
) -> None:
    skill = HungerSkill()
    initial = replace(
        template,
        player=replace(template.player, hunger=2),
        inventory=(_ration(template),),
    )
    eat = skill.select_action(initial, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND)
    prompt = replace(
        initial,
        step_index=1,
        message=f"What do you want to eat? [{current_letter} or ?*]",
        prompt=PromptState(True, False, False),
        inventory=(_ration(template, letter=current_letter),),
    )

    answer = skill.select_action(prompt, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND)

    assert eat is not None
    assert eat.action_index == _HUNGER_BY_NAME["Command.EAT"].index
    assert answer is not None
    assert answer.action_index == _HUNGER_BY_NAME[action_name].index


def test_hunger_skill_cancels_mismatched_item_prompt_and_clears_sequence(
    template: ProjectedObservation,
) -> None:
    skill = HungerSkill()
    hungry = replace(
        template,
        player=replace(template.player, hunger=2),
        inventory=(_ration(template),),
    )
    assert skill.select_action(hungry, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND) is not None
    mismatch = replace(
        hungry,
        step_index=1,
        message="What do you want to eat? [z or ?*]",
        prompt=PromptState(True, False, False),
    )

    canceled = skill.select_action(mismatch, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND)
    restarted = skill.select_action(hungry, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND)

    assert canceled is not None
    assert canceled.action_index == _HUNGER_BY_NAME["Command.ESC"].index
    assert restarted is not None
    assert restarted.action_index == _HUNGER_BY_NAME["Command.EAT"].index


def test_unknown_food_is_not_eaten_and_floor_corpse_prompt_is_declined(
    template: ProjectedObservation,
) -> None:
    corpse = _ration(
        template,
        description="a newt corpse",
        buc=BucStatus.UNKNOWN,
    )
    hungry = replace(
        template,
        player=replace(template.player, hunger=4),
        inventory=(corpse,),
    )
    floor_prompt = replace(
        hungry,
        message="There is a newt corpse here; eat it? [ynq] (n)",
        prompt=PromptState(True, False, False),
    )

    assert (
        HungerSkill().select_action(hungry, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND) is None
    )
    declined = SafePromptHandler.select_action(
        floor_prompt, _HUNGER_BY_NAME, _HUNGER_BY_COMMAND
    )
    assert declined is not None
    assert declined.action_index == _HUNGER_BY_COMMAND[ord("n")].index


@pytest.mark.parametrize(
    ("hp", "maximum", "level", "turn", "expected"),
    [
        (5, 20, 1, 100, True),
        (6, 20, 1, 100, False),
        (6, 60, 2, 100, True),
        (7, 60, 2, 100, False),
        (5, 20, 1, 99, False),
    ],
)
def test_low_hp_prayer_overrides_food_but_preserves_timeout(
    template: ProjectedObservation,
    hp: int,
    maximum: int,
    level: int,
    turn: int,
    expected: bool,
) -> None:
    base = sketch(template, ("|.@j.|",))
    observation = replace(
        base,
        player=replace(
            base.player,
            hit_points=hp,
            max_hit_points=maximum,
            experience_level=level,
            hunger=0,
            turn=turn,
        ),
        inventory=(_ration(template),),
    )
    memory = LevelMemory()
    memory.observe(observation)
    pray = LegalAction(0, int(nethack.Command.PRAY), "Command.PRAY")
    result = PrayerSkill().select_action(
        observation,
        memory,
        {pray.name: pray},
        {},
        prior_prayers=0,
        pending=None,
    )
    assert (result is not None and result.action_index == pray.index) is expected


def test_prayer_skill_requires_weak_safe_turn_no_ration_or_altar(
    template: ProjectedObservation,
) -> None:
    skill = PrayerSkill()
    pray = LegalAction(0, int(nethack.Command.PRAY), "Command.PRAY")
    yes = LegalAction(1, ord("y"), "CompassDirection.NW")
    actions = {pray.name: pray}
    commands = {yes.command: yes}
    base = sketch(template, ("|.@..|",))
    memory = LevelMemory()
    memory.observe(base)
    weak = replace(
        base,
        player=replace(base.player, hunger=3, turn=PRAYER_FIRST_SAFE_TURN),
        inventory=(),
    )
    selected = skill.select_action(
        weak, memory, actions, commands, prior_prayers=0, pending=None
    )
    assert selected is not None and selected.action_index == pray.index
    assert selected.intent == ActionIntent(
        None,
        None,
        None,
        prayer=PrayerEvidence(3, PRAYER_FIRST_SAFE_TURN, PRAYER_FIRST_SAFE_TURN),
    )
    for blocked in (
        replace(weak, player=replace(weak.player, hunger=2)),
        replace(weak, player=replace(weak.player, turn=PRAYER_FIRST_SAFE_TURN - 1)),
        replace(weak, inventory=(_ration(template),)),
        replace(weak, prompt=PromptState(True, False, False)),
        replace(weak, message="There is an altar here."),
    ):
        assert (
            skill.select_action(
                blocked, memory, actions, commands, prior_prayers=0, pending=None
            )
            is None
        )
    assert (
        skill.select_action(
            weak, memory, actions, commands, prior_prayers=1, pending=None
        )
        is None
    )
    memory.observe(sketch(template, ("|_@..|",), step=1))
    on_altar = sketch(template, ("|@...|",), step=2)
    memory.observe(on_altar)
    assert memory.cmap(memory.position) == 27
    assert (
        skill.select_action(
            replace(
                on_altar,
                player=replace(on_altar.player, hunger=3, turn=PRAYER_FIRST_SAFE_TURN),
                inventory=(),
            ),
            memory,
            actions,
            commands,
            prior_prayers=0,
            pending=None,
        )
        is None
    )


def test_prayer_skill_repeat_wait_boundary_preserves_observed_kill_count(
    template: ProjectedObservation,
) -> None:
    skill = PrayerSkill()
    pray = LegalAction(0, int(nethack.Command.PRAY), "Command.PRAY")
    base = sketch(template, ("|.@..|",))
    memory = LevelMemory()
    memory.observe(base)
    last = 101
    safe = last + PRAYER_REPEAT_WAIT_TURNS
    weak = replace(
        base,
        player=replace(base.player, hunger=3, turn=safe - 1),
        inventory=(),
    )
    args = (memory, {pray.name: pray}, {})
    assert (
        skill.select_action(
            weak,
            *args,
            prior_prayers=1,
            last_prayer_turn=last,
            kill_count=7,
            pending=None,
        )
        is None
    )
    ready = replace(weak, player=replace(weak.player, turn=safe))
    selected = skill.select_action(
        ready, *args, prior_prayers=1, last_prayer_turn=last, kill_count=7, pending=None
    )
    assert selected is not None and selected.action_index == pray.index
    assert selected.intent == ActionIntent(
        None, None, None, prayer=PrayerEvidence(3, safe, safe, 7)
    )


def test_prayer_skill_defends_and_confirms_only_exact_pending_prompt(
    template: ProjectedObservation,
) -> None:
    skill = PrayerSkill()
    pray = LegalAction(0, int(nethack.Command.PRAY), "Command.PRAY")
    yes = LegalAction(1, ord("y"), "CompassDirection.NW")
    east = LegalAction(2, ord("l"), "CompassDirection.E")
    base = sketch(template, ("|@j..|",))
    weak = replace(base, player=replace(base.player, hunger=3, turn=101), inventory=())
    memory = LevelMemory()
    memory.observe(weak)
    actions = {item.name: item for item in (pray, yes, east)}
    commands = {item.command: item for item in (pray, yes, east)}
    defend = skill.select_action(
        weak, memory, actions, commands, prior_prayers=0, pending=None
    )
    assert defend is not None and defend.action_index == east.index
    assert defend.intent is not None and defend.intent.attack_target == MapCell(2, 0)

    evidence = PrayerEvidence(3, 101, PRAYER_FIRST_SAFE_TURN)
    confirmed = replace(
        weak,
        step_index=1,
        prompt=PromptState(True, False, False),
        message="Are you sure you want to pray? [yn] (n) ",
    )
    answer = skill.select_action(
        confirmed, memory, actions, commands, prior_prayers=1, pending=evidence
    )
    assert answer is not None and answer.action_index == yes.index
    assert answer.intent == ActionIntent(None, None, None, prayer=evidence)
    assert (
        skill.select_action(
            replace(confirmed, message=confirmed.message + " "),
            memory,
            actions,
            commands,
            prior_prayers=1,
            pending=evidence,
        )
        is None
    )


def test_corpse_skill_routes_at_most_five_real_steps_to_visible_kill_cell(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    body = nethack.GLYPH_BODY_OFF + _MONSTERS["lichen"]
    skill = CorpseSkill()
    for length in (5, 6):
        observation = sketch(template, ("@" + "." * (length - 1) + "%",), step=3)
        observation = replace(
            observation,
            player=replace(observation.player, turn=5, hunger=1),
            map=replace(
                observation.map,
                glyph_rows=(observation.map.glyph_rows[0][:-1] + (body,),),
            ),
        )
        memory = LevelMemory()
        memory.observe(observation)
        kill = CorpseKill("lichen", 2, LevelKey(0, 1), MapCell(length, 0))
        proposal = skill.select_action(
            observation, memory, actions, {(kill.level, kill.cell): kill}, set()
        )
        if length == 5:
            assert proposal is not None
            assert action_name(actions, proposal.action_index) == "CompassDirection.E"
            assert proposal.intent is not None
            assert proposal.intent.destination == IntentDestination(
                DestinationKind.CORPSE, length, 0
            )
            assert len(proposal.intent.path or ()) == 5
            assert_followed_route(proposal, (0, 0))
            disguised_ration = replace(
                observation,
                map=replace(
                    observation.map,
                    glyph_rows=(observation.map.glyph_rows[0][:-1] + (_GLYPHS["%"],),),
                ),
            )
            assert (
                skill.select_action(
                    disguised_ration,
                    memory,
                    actions,
                    {(kill.level, kill.cell): kill},
                    set(),
                )
                is None
            )
        else:
            assert proposal is None


@pytest.mark.parametrize(
    ("underfoot", "floor_question"),
    [
        (
            "You see here a lichen corpse.",
            "There is a lichen corpse here; eat it? [ynq] (n) ",
        ),
        (
            "There is an open door here.  You see here a lichen corpse.",
            "There is a lichen corpse here; eat it? [ynq] (n) ",
        ),
        (
            "You see here a partly eaten lichen corpse.",
            "There is a partly eaten lichen corpse here; eat it? [ynq] (n) ",
        ),
    ],
)
def test_corpse_skill_requires_fresh_identity_underfoot_and_exact_confirmation(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    underfoot: str,
    floor_question: str,
) -> None:
    observation = sketch(template, ("@.",), message=underfoot, step=4)
    observation = replace(
        observation, player=replace(observation.player, turn=21, hunger=1)
    )
    memory = LevelMemory()
    memory.observe(observation)
    kill = CorpseKill("lichen", 2, LevelKey(0, 1), MapCell(0, 0))
    kills = {(kill.level, kill.cell): kill}
    skill = CorpseSkill()
    proposal = skill.select_action(observation, memory, actions, kills, set())
    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "Command.EAT"
    assert proposal.intent is not None and proposal.intent.corpse is not None
    evidence = proposal.intent.corpse
    assert evidence.age == 19
    assert (
        skill.select_action(
            replace(observation, player=replace(observation.player, hunger=0)),
            memory,
            actions,
            kills,
            set(),
        )
        is None
    )
    old_lichen = skill.select_action(
        replace(observation, player=replace(observation.player, turn=400)),
        memory,
        actions,
        kills,
        set(),
    )
    assert old_lichen is not None and old_lichen.intent.corpse.age == 398
    assert (
        skill.select_action(
            replace(observation, message="You see here a jackal corpse."),
            memory,
            actions,
            kills,
            set(),
        )
        is None
    )
    assert skill.select_action(observation, memory, actions, kills, {kill}) is None
    by_command = {action.command: action for action in actions.values()}
    prompt = replace(
        observation,
        message=floor_question,
        prompt=PromptState(True, False, False),
    )
    confirmation = skill.confirm(prompt, by_command, evidence)
    assert confirmation is not None
    assert confirmation.action_index == by_command[ord("y")].index
    for player in (
        replace(prompt.player, hunger=0),
        replace(prompt.player, x=1),
    ):
        unverified = replace(prompt, player=player)
        assert skill.confirm(unverified, by_command, evidence) is None
        declined = skill.decline(unverified, by_command, evidence)
        assert declined is not None
        assert declined.action_index == by_command[ord("n")].index
    assert (
        skill.confirm(
            replace(
                prompt, message="There is a jackal corpse here; eat it? [ynq] (n) "
            ),
            by_command,
            evidence,
        )
        is None
    )
    assert (
        skill.confirm(
            replace(prompt, message=prompt.message.rstrip()), by_command, evidence
        )
        is None
    )


@pytest.mark.parametrize(
    ("scenario", "allowed"),
    [
        ("healthy", True),
        ("hungry", True),
        ("low_hp", False),
        ("weak", False),
        ("fainting", False),
        ("branch", False),
        ("inventory_closed", False),
        ("shopkeeper", False),
        ("known_shop", False),
        ("downstairs_known", False),
        ("spent", False),
        ("experience_welcome", True),
    ],
)
def test_exit_route_gate_selection_and_audit_agree(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    scenario: str,
    allowed: bool,
) -> None:
    from nethack_agent.coordinator import ActionGate, ActionGateError
    from nethack_agent.decision import ActionSelection, SkillSelectionSource
    from nethack_agent.evaluation import _action_is_valid
    from nethack_agent.events import StepPayload
    from nethack_agent.tasks import ActionProfile
    from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

    _GLYPHS["s"] = nethack.GLYPH_MON_OFF + _MONSTERS["shopkeeper"]
    lines = ("        ", " -----  ", " |..@+  ", " -----  ", "        ")
    if scenario == "shopkeeper":
        lines = ("        ", " ----s  ", " |..@+  ", " -----  ", "        ")
    before = sketch(
        template,
        lines,
        dungeon_level=3,
        dungeon_number=2 if scenario == "branch" else 0,
        message='You read: "Closed for inventory".'
        if scenario == "inventory_closed"
        else "Welcome to Izchak's lighting store!"
        if scenario == "known_shop"
        else "Welcome to experience level 2."
        if scenario == "experience_welcome"
        else "",
    )
    before = replace(
        before,
        player=replace(
            before.player,
            hit_points=9 if scenario == "low_hp" else 10,
            hunger={"weak": 3, "fainting": 4, "hungry": 2}.get(scenario, 1),
        ),
    )
    dungeon = DungeonMemory()
    memory = dungeon.observe(before)
    memory.locked_doors.add((5, 2))
    if scenario == "downstairs_known":
        memory.set_stair((2, 2), StairDirection.DOWN)
    if scenario == "spent":
        memory.kicks[(5, 2)] = 8
    result = ExploreLevelSkill().select_action(memory, actions)
    assert (
        result.action is not None
        and action_name(actions, result.action.action_index) == "Command.KICK"
    ) is allowed
    kick = actions["Command.KICK"]
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.EXPLORE_LEVEL,
        SkillSelectionSource.ARBITER,
        None,
        kick.index,
        "Force the route gate.",
        ActionIntent(IntentDestination(DestinationKind.LOCKED_DOOR, 5, 2), None, None),
    )
    profile = ActionProfile.NLE_TASK_ACTIONS
    legal = tuple(
        LegalAction(i, int(a), f"{type(a).__name__}.{a.name}")
        for i, a in enumerate(profile.actions)
    )
    payload = StepPayload(
        selection,
        None,
        None,
        None,
        None,
        kick,
        0.0,
        False,
        False,
        0,
        False,
        None,
        replace(before, step_index=1),
    )
    assert (
        _action_is_valid(
            payload,
            legal,
            before,
            True,
            profile,
            dungeon_memory=dungeon,
        )
        is allowed
    )
    gate = ActionGate(legal, profile)
    if allowed:
        assert (
            gate.resolve(kick.index, selection=selection, before=before, memory=memory)
            == kick
        )
    else:
        with pytest.raises(ActionGateError):
            gate.resolve(kick.index, selection=selection, before=before, memory=memory)


@pytest.mark.parametrize("door", ("O", "D"))
def test_open_door_search_reaches_outward_blank_extension(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    door: str,
) -> None:
    memory = remembered(
        template,
        (
            "            ",
            " ----       ",
            f" |..@{door}      ",
            " ----       ",
            "            ",
            "            ",
            "            ",
        ),
        (
            "            ",
            " ----       ",
            " |...@      ",
            " ----       ",
            "            ",
            "            ",
            "            ",
        ),
    )
    # Observing the hero next to blank terrain marks it observed, but does not
    # make a concealed passage known. Search must still face that blank.
    memory.search_coverage = {
        (x, y): 10 for y in range(memory.height) for x in range(memory.width)
    }
    memory.search_coverage[(6, 2)] = 0
    action = ExploreLevelSkill().select_action(memory, actions).action
    assert action is not None
    assert action_name(actions, action.action_index) == "Command.SEARCH"
    assert action.record.search_spot == (5, 2)


def test_object_covered_cell_is_visited_before_hidden_search(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
) -> None:
    memory = remembered(
        template, ("         ", " ------  ", " |@..%|  ", " ------  ", "         ")
    )
    action = ExploreLevelSkill().select_action(memory, actions).action
    assert action is not None
    assert action_name(actions, action.action_index) == "CompassDirection.E"
    assert action.intent.destination == IntentDestination(
        DestinationKind.FRONTIER, 5, 2
    )
    memory.visited.add((5, 2))
    next_action = ExploreLevelSkill().select_action(memory, actions).action
    assert next_action is not None
    assert next_action.record.search_spot is not None


def test_kick_injury_and_whamm_outcomes_bound_further_attempts(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
) -> None:
    lines = ("        ", " -----  ", " |..@+  ", " -----  ", "        ")
    before = sketch(template, lines, dungeon_level=3)
    memory = LevelMemory()
    memory.observe(replace(before, player=replace(before.player, hit_points=10)))
    memory.locked_doors.add((5, 2))
    memory.record(ActionRecord(ActionKind.KICK_DIRECTION, (4, 2), (5, 2)))
    after = replace(
        sketch(template, lines, step=1, dungeon_level=3, message="Ouch! That hurts!"),
        player=replace(before.player, hit_points=7),
    )
    memory.observe(after)
    assert memory.kick_outcomes[(5, 2)] == ["ouch"]
    assert memory.kicks[(5, 2)] == 1
    action = ExploreLevelSkill().select_action(memory, actions).action
    assert action is None or action_name(actions, action.action_index) != "Command.KICK"
    for step in range(2, 9):
        memory.record(ActionRecord(ActionKind.KICK_DIRECTION, (4, 2), (5, 2)))
        memory.observe(
            replace(
                sketch(
                    template, lines, step=step, dungeon_level=3, message="WHAMMM!!!"
                ),
                player=replace(before.player, hit_points=17),
            )
        )
    assert memory.kicks[(5, 2)] == 8
    assert memory.kick_outcomes[(5, 2)] == ["ouch"] + ["whamm"] * 7
    action = ExploreLevelSkill().select_action(memory, actions).action
    assert action is None or action_name(actions, action.action_index) != "Command.KICK"


def test_pending_kick_accepts_only_the_gate_direction(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
) -> None:
    from nethack_agent.decision import ActionSelection, SkillSelectionSource
    from nethack_agent.replay import kick_action_error
    from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

    memory = remembered(
        template, ("        ", " -----  ", " |..@+  ", " -----  ", "        ")
    )
    memory.locked_doors.add((5, 2))
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.EXPLORE_LEVEL,
        SkillSelectionSource.ARBITER,
        None,
        actions["CompassDirection.E"].index,
        "Direct the kick.",
        ActionIntent(IntentDestination(DestinationKind.LOCKED_DOOR, 5, 2), None, None),
    )
    # A wait while approaching a gate is not a kick answer.
    assert kick_action_error("MiscDirection.WAIT", selection, memory) is None
    memory.record(ActionRecord(ActionKind.KICK, memory.position, (5, 2)))
    assert kick_action_error("CompassDirection.E", selection, memory) is None
    assert kick_action_error("CompassDirection.W", selection, memory) is not None
    assert (
        kick_action_error(
            "CompassDirection.E",
            replace(selection, intent=None),
            memory,
        )
        is not None
    )


@pytest.mark.parametrize(
    ("connection", "identity", "allowed"),
    [
        (StairConnection.MAIN, StairIdentityKind.BRANCH, True),
        (StairConnection.MAIN, StairIdentityKind.MAIN, False),
        (StairConnection.MAIN, StairIdentityKind.UNKNOWN, False),
        (StairConnection.ANY, StairIdentityKind.BRANCH, False),
    ],
)
def test_exit_gate_uses_goal_compatible_downstairs(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    connection: StairConnection,
    identity: StairIdentityKind,
    allowed: bool,
) -> None:
    from nethack_agent.coordinator import ActionGate, ActionGateError
    from nethack_agent.decision import ActionSelection, SkillSelectionSource
    from nethack_agent.replay import kick_action_error
    from nethack_agent.tasks import ActionProfile

    before = sketch(
        template,
        ("        ", " -----  ", " |>..@+ ", " -----  ", "        "),
        dungeon_level=3,
    )
    memory = LevelMemory()
    memory.observe(before)
    memory.locked_doors.add((6, 2))
    if identity is not StairIdentityKind.UNKNOWN:
        memory.stair_identities[(2, 2)] = StairIdentity(
            identity,
            2 if identity is StairIdentityKind.BRANCH else 0,
            IdentityEvidence.TRAVERSED,
        )
    target = StairTarget(StairDirection.DOWN, connection, None)
    goal = StandOnStairsGoal(target)
    result = ExploreLevelSkill().select_action(memory, actions, target).action
    assert (
        result is not None
        and action_name(actions, result.action_index) == "Command.KICK"
    ) is allowed
    kick = actions["Command.KICK"]
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        goal,
        Skill.EXPLORE_LEVEL,
        SkillSelectionSource.ARBITER,
        None,
        kick.index,
        "Force the exit route.",
        ActionIntent(IntentDestination(DestinationKind.LOCKED_DOOR, 6, 2), None, None),
    )
    profile = ActionProfile.NLE_TASK_ACTIONS
    legal = tuple(
        LegalAction(i, int(a), f"{type(a).__name__}.{a.name}")
        for i, a in enumerate(profile.actions)
    )
    gate = ActionGate(legal, profile)
    if allowed:
        assert kick_action_error(kick.name, selection, memory) is None
        assert (
            gate.resolve(kick.index, selection=selection, before=before, memory=memory)
            == kick
        )
    else:
        assert kick_action_error(kick.name, selection, memory) is not None
        with pytest.raises(ActionGateError):
            gate.resolve(kick.index, selection=selection, before=before, memory=memory)


def test_main_exit_checks_covered_cells_despite_known_branch_stairs(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
) -> None:
    memory = remembered(
        template, ("         ", " ------- ", " |@..%>| ", " ------- ", "         ")
    )
    memory.stair_identities[(6, 2)] = StairIdentity(
        StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED
    )
    target = StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
    result = ExploreLevelSkill().select_action(memory, actions, target).action
    assert result is not None
    assert result.intent.destination == IntentDestination(
        DestinationKind.FRONTIER, 5, 2
    )
    assert action_name(actions, result.action_index) == "CompassDirection.E"


def test_known_branch_preserves_reachable_frontier_before_covered_exit_checks(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
) -> None:
    memory = remembered(
        template,
        (
            "             ",
            " ----------- ",
            " |@..%>D###  ",
            " ----------- ",
            "             ",
        ),
    )
    memory.stair_identities[(6, 2)] = StairIdentity(
        StairIdentityKind.BRANCH, 2, IdentityEvidence.TRAVERSED
    )
    target = StairTarget(StairDirection.DOWN, StairConnection.MAIN, None)
    result = ExploreLevelSkill().select_action(memory, actions, target).action
    assert result is not None
    assert result.intent.destination == IntentDestination(
        DestinationKind.FRONTIER, 10, 2
    )


@pytest.mark.parametrize(
    ("corridors", "hidden"),
    (
        (((4, 4), (5, 4), (5, 5), (6, 6), (6, 7), (6, 5)), (7, 5)),
        (((5, 4), (6, 4), (7, 4), (6, 5)), (6, 6)),
    ),
)
def test_search_checks_continuations_at_bends_and_fanned_corridor_ends(
    template: ProjectedObservation,
    actions: dict[str, LegalAction],
    corridors: tuple[tuple[int, int], ...],
    hidden: tuple[int, int],
) -> None:
    rows = [[" "] * 13 for _ in range(11)]
    for x, y in corridors:
        rows[y][x] = "#"
    frames = []
    for x, y in corridors:
        frame = [row.copy() for row in rows]
        frame[y][x] = "@"
        frames.append(tuple("".join(row) for row in frame))
    memory = remembered(template, *frames)
    memory.search_coverage = {point: SEARCHES_PER_ROUND for point in memory.cells()}
    memory.search_coverage[hidden] = 0

    result = ExploreLevelSkill().select_action(memory, actions)

    assert result.action is not None
    assert action_name(actions, result.action.action_index) == "Command.SEARCH"
    memory.record(result.action.record)
    assert memory.search_coverage[hidden] == 1


def test_known_boulder_is_not_a_hidden_passage_search_target(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    lines = ("             ",) * 5 + ("     @#0     ",) + ("             ",) * 5
    arrived = (*lines[:5], "     #@0     ", *lines[6:])
    memory = remembered(template, lines, arrived)
    memory.search_coverage = {point: SEARCHES_PER_ROUND for point in memory.cells()}
    memory.search_coverage[(7, 5)] = 0

    result = ExploreLevelSkill().select_action(memory, actions)

    assert result.action is None
    assert result.stuck is StuckReason.SEARCH_EXHAUSTED


def test_committed_search_is_not_interrupted_by_a_monster_blocked_frontier(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    lines = (
        "                        ",
        "                        ",
        " -------                ",
        " |.....|                ",
        " |.....D#####e##        ",
        " |.....|                ",
        " -------                ",
        "                        ",
        "                        ",
    )
    positions = [
        (x, y)
        for y, row in enumerate(lines)
        for x, char in enumerate(row)
        if char in ".#D" and x < 13
    ]
    memory = LevelMemory()
    initial = list(lines)
    initial[3] = " |@....|                "
    initial[4] = initial[4].replace("e", "#")
    memory.observe(sketch(template, tuple(initial)))
    for step, (x, y) in enumerate((*positions, (2, 3)), start=1):
        frame = list(lines)
        frame[y] = frame[y][:x] + "@" + frame[y][x + 1 :]
        memory.observe(sketch(template, tuple(frame), step=step))
    memory.search_goal = (2, 3)

    result = ExploreLevelSkill().select_action(memory, actions)

    assert result.action is not None
    assert result.action.record.kind is ActionKind.SEARCH
    assert result.action.record.search_spot == (2, 3)

    # Newly reachable unexplored terrain still takes precedence over a search.
    changed = list(frame)
    changed[3] = changed[3][:8] + "#" + changed[3][9:]
    memory.observe(sketch(template, tuple(changed), step=len(positions) + 2))
    next_action = ExploreLevelSkill().select_action(memory, actions).action
    assert next_action is not None
    assert next_action.intent.destination.kind is DestinationKind.FRONTIER


@pytest.mark.parametrize(
    ("encumbrance", "message", "must_drop"),
    (
        (1, "You can't do that while carrying so much stuff.", False),
        (2, "You can't do that while carrying so much stuff.", True),
        (5, "You can't do that while carrying so much stuff.", True),
        (5, "You see here a food ration.", False),
    ),
)
def test_burden_recovery_requires_public_load_refusal(
    template: ProjectedObservation,
    encumbrance: int,
    message: str,
    must_drop: bool,
) -> None:
    observation = replace(
        template,
        player=replace(template.player, encumbrance=encumbrance),
        message=message,
        inventory=(_ration(template, description="5 uncursed food rations"),),
    )
    proposed = BurdenRecovery().select_action(observation, _HUNGER_BY_COMMAND)
    if must_drop:
        assert proposed.intent.drop.quantity == 4
        assert proposed.action_index == _HUNGER_BY_NAME["Command.DROP"].index
    else:
        assert proposed is None


def test_burden_recovery_protects_ration_weapon_and_worn_armor(
    template: ProjectedObservation,
) -> None:
    weapon = replace(
        template.inventory[0],
        letter="a",
        object_class=2,
        description="a +1 long sword (weapon in hand)",
    )
    armor = replace(
        template.inventory[0],
        letter="c",
        object_class=3,
        description="an uncursed +0 small shield (being worn)",
    )
    reserve = _ration(template)
    spare = _ration(template, letter="e", description="4 food rations")
    observation = replace(template, inventory=(weapon, armor, reserve, spare))
    assert drop_candidate(observation, set()) == (spare, 4)
    assert (
        drop_candidate(replace(observation, inventory=(weapon, armor, reserve)), set())
        is None
    )
    unwielded = replace(
        weapon, description="a +1 long sword (alternate weapon; not wielded)"
    )
    assert (
        drop_candidate(
            replace(observation, inventory=(unwielded, armor, reserve)), set()
        )
        is None
    )
    apples = replace(reserve, letter="f", description="2 apples")
    assert drop_candidate(
        replace(observation, inventory=(weapon, armor, reserve, apples)), set()
    ) == (apples, 2)


def test_burden_recovery_partial_stack_uses_only_offered_current_item(
    template: ProjectedObservation,
) -> None:
    recovery = BurdenRecovery()
    before = replace(
        template,
        player=replace(template.player, encumbrance=5),
        message="You can't do that while carrying so much stuff.",
        inventory=(_ration(template, description="5 food rations"),),
    )
    initial = recovery.expected(before)
    prompt = replace(
        before,
        message="What do you want to drop? [d or ?*]",
        prompt=PromptState(True, False, False),
    )
    recovery.advance(initial, prompt)
    count = recovery.expected(prompt)
    assert (count.command, count.quantity) == (ord("4"), 4)
    recovery.advance(count, prompt)
    item = recovery.expected(prompt)
    assert (item.command, item.letter) == (ord("d"), "d")
    assert (
        recovery.expected(
            replace(prompt, message="What do you want to drop? [e or ?*]")
        )
        is None
    )
    assert (
        recovery.expected(
            replace(
                prompt, inventory=(_ration(template, description="4 food rations"),)
            )
        )
        is None
    )


def test_dropped_surplus_is_not_picked_up_into_another_drop_loop(
    template: ProjectedObservation,
) -> None:
    from nethack_agent.tasks import ActionProfile

    legal = tuple(
        LegalAction(i, int(a), f"{type(a).__name__}.{a.name}")
        for i, a in enumerate(ActionProfile.NLE_SURVIVAL_ACTIONS.actions)
    )
    by_name = {a.name: a for a in legal}
    by_command = {a.command: a for a in legal}
    before = replace(
        sketch(template, ("-----", "|.@.|", "-----")),
        player=replace(template.player, x=2, y=1, encumbrance=5, hunger=1),
        message="You can't do that while carrying so much stuff.",
        inventory=(
            _ration(template),
            _ration(template, letter="e", description="4 food rations"),
        ),
    )
    recovery = BurdenRecovery()
    initial = recovery.expected(before)
    prompt = replace(
        before,
        message="What do you want to drop? [de or ?*]",
        prompt=PromptState(True, False, False),
    )
    recovery.advance(initial, prompt)
    answer = recovery.expected(prompt)
    assert (answer.command, answer.quantity) == (ord("e"), 4)
    relieved = replace(
        before,
        inventory=(_ration(template),),
        player=replace(before.player, encumbrance=1),
        message="You drop 4 food rations.",
    )
    recovery.advance(answer, relieved)
    assert recovery.select_action(relieved, by_command) is None

    floor_food = replace(relieved, message="You see here 4 food rations.")
    memory = LevelMemory()
    memory.observe(floor_food)
    assert FoodSkill.select_action(floor_food, memory, by_name, by_command) is None
    unburdened = replace(floor_food, player=replace(floor_food.player, encumbrance=0))
    assert (
        FoodSkill.select_action(
            unburdened,
            memory,
            by_name,
            by_command,
            excluded_cells=recovery.excluded_food_cells(unburdened),
        )
        is None
    )
    assert recovery.select_action(unburdened, by_command) is None
    empty = replace(unburdened, inventory=())
    retrieved = FoodSkill.select_action(
        empty,
        memory,
        by_name,
        by_command,
        excluded_cells=recovery.excluded_food_cells(empty),
    )
    assert retrieved.action_index == by_name["Command.PICKUP"].index


@pytest.mark.parametrize(
    ("message", "prompt_active", "triggers"),
    (
        ("There are several objects here.", False, True),
        ("There are many objects here.", False, True),
        ("There are several objects here.", True, False),
        ("You see here a food ration.", False, False),
        ("", False, False),
    ),
)
def test_discover_ambiguous_pile_only_looks_at_an_unresolved_arrival_message(
    template: ProjectedObservation,
    message: str,
    prompt_active: bool,
    triggers: bool,
) -> None:
    from nethack_agent.skills import discover_ambiguous_pile
    from nethack_agent.tasks import ActionProfile

    by_name = {
        f"{type(a).__name__}.{a.name}": LegalAction(
            i, int(a), f"{type(a).__name__}.{a.name}"
        )
        for i, a in enumerate(ActionProfile.NLE_SURVIVAL_ACTIONS.actions)
    }
    observation = replace(
        template,
        message=message,
        prompt=PromptState(prompt_active, False, False),
    )
    result = discover_ambiguous_pile(observation, by_name)
    if triggers:
        assert result is not None
        assert result.action_index == by_name["Command.LOOK"].index
        assert result.intent is None
    else:
        assert result is None


@pytest.mark.parametrize(
    ("command", "quantity", "offer", "allowed"),
    (
        (ord("4"), 4, "d", True),
        (ord("5"), 4, "d", False),
        (ord("4"), 5, "d", False),
        (ord("4"), 4, "e", False),
    ),
)
def test_burden_prompt_runtime_gate_and_audit_reject_wrong_item_or_count(
    template: ProjectedObservation,
    command: int,
    quantity: int,
    offer: str,
    allowed: bool,
) -> None:
    from nethack_agent.coordinator import ActionGate, ActionGateError
    from nethack_agent.decision import ActionSelection, SkillSelectionSource
    from nethack_agent.evaluation import _action_is_valid
    from nethack_agent.events import StepPayload
    from nethack_agent.tasks import ActionProfile
    from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

    profile = ActionProfile.NLE_SURVIVAL_ACTIONS
    legal = tuple(
        LegalAction(i, int(a), f"{type(a).__name__}.{a.name}")
        for i, a in enumerate(profile.actions)
    )
    action = next(a for a in legal if a.command == command)
    refusal = replace(
        template,
        player=replace(template.player, encumbrance=5),
        message="You can't do that while carrying so much stuff.",
        inventory=(_ration(template, description="5 food rations"),),
    )
    before = replace(
        refusal,
        step_index=1,
        message=f"What do you want to drop? [{offer} or ?*]",
        prompt=PromptState(True, False, False),
    )
    recovery = BurdenRecovery()
    initial = recovery.expected(refusal)
    recovery.advance(initial, before)
    evidence = replace(initial, command=command, quantity=quantity)
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_PROMPT,
        STAND_ON_DOWNSTAIRS,
        Skill.BURDEN,
        SkillSelectionSource.ARBITER,
        None,
        action.index,
        "Drop only the approved surplus count.",
        ActionIntent(None, None, None, drop=evidence),
    )
    payload = StepPayload(
        selection,
        None,
        None,
        None,
        None,
        action,
        0.0,
        False,
        False,
        0,
        False,
        None,
        replace(before, step_index=2),
    )
    assert (
        _action_is_valid(payload, legal, before, True, profile, burden=recovery)
        is allowed
    )
    gate = ActionGate(legal, profile)
    if allowed:
        assert (
            gate.resolve(
                action.index, selection=selection, before=before, burden=recovery
            )
            == action
        )
    else:
        with pytest.raises(ActionGateError):
            gate.resolve(
                action.index, selection=selection, before=before, burden=recovery
            )
