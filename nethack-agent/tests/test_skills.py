from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.coordinator import AgentCoordinator
from nethack_agent.decision import (
    LEVEL_CHANGE_ACTIONS,
    ActionIntent,
    ActionSelectionSource,
    DestinationKind,
    IntentDestination,
    MapCell,
    RunOutcome,
    Skill,
    StuckReason,
)
from nethack_agent.environment import LegalAction, NleEnvironment, ScenarioConfig
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.navigation import (
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
    MapView,
    ObservationProjector,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.skills import (
    SEARCHES_PER_ROUND,
    ExploreLevelSkill,
    SafePromptHandler,
    SkillAction,
    StaircaseNavigationSkill,
    _past_monster,
)
from nethack_agent.traversal import (
    DUNGEON_EXIT,
    UNKNOWN_STAIR,
    IdentityEvidence,
    LevelKey,
    StairDirection,
    StairIdentity,
    StairIdentityKind,
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
    "0": nethack.GLYPH_OBJ_OFF + _BOULDER,
    "%": nethack.GLYPH_OBJ_OFF + _FOOD,
    "j": nethack.GLYPH_MON_OFF + _MONSTERS["jackal"],
    "e": nethack.GLYPH_MON_OFF + _MONSTERS["floating eye"],
    "f": nethack.GLYPH_PET_OFF + _MONSTERS["kitten"],
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
    downstairs = IntentDestination(DestinationKind.DOWNSTAIRS, 5, 1, UNKNOWN_STAIR)
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
        IntentDestination(DestinationKind.DOWNSTAIRS, 1, 1, UNKNOWN_STAIR),
        None,
        cells((3, 2), (2, 2), (1, 1)),
    )


def test_staircase_defense_keeps_the_chosen_downstairs_as_destination(
    template: ProjectedObservation, actions: dict[str, LegalAction]
) -> None:
    memory = remembered(template, ("-------", "|.j...|", "|@...>|", "-------"))

    proposal = StaircaseNavigationSkill().select_action(memory, actions)

    assert proposal is not None
    assert action_name(actions, proposal.action_index) == "CompassDirection.NE"
    # The attack leaves the route, so no path is recorded for this step.
    assert proposal.intent == ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 5, 2, UNKNOWN_STAIR),
        MapCell(2, 1),
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
    downstairs = IntentDestination(DestinationKind.DOWNSTAIRS, 5, 1, UNKNOWN_STAIR)

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
    assert result.action.rationale.startswith("Move beside the locked door")
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
    assert {record.selection.skill for record in records} == set(Skill)
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
