"""Public-evidence consumers for bounded route-blocker clearance."""

from dataclasses import replace

import pytest
from nle import nethack
from test_skills import sketch
from test_skills import template as _native_template

from nethack_agent.environment import LegalAction
from nethack_agent.hazard import (
    ATTEMPT_COOLDOWN_TURNS,
    LEVEL_ATTEMPT_LIMIT,
    TARGET_ATTEMPT_LIMIT,
    WAIT_ALLOWANCE,
    expected_throw,
    throw_at_blocker,
)
from nethack_agent.navigation import (
    ActionKind,
    ActionRecord,
    DungeonMemory,
    LevelMemory,
)
from nethack_agent.observation import (
    BucStatus,
    CellDescription,
    InventoryItem,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.tasks import ActionProfile
from nethack_agent.traversal import (
    StairConnection,
    StairDirection,
    StairTarget,
    StandOnStairsGoal,
)


@pytest.fixture
def template(tmp_path):
    return _native_template.__wrapped__(tmp_path)


_GOAL = StandOnStairsGoal(StairTarget(StairDirection.DOWN, StairConnection.ANY, None))
_ACTIONS = {
    int(member): LegalAction(
        index, int(member), f"{type(member).__name__}.{member.name}"
    )
    for index, member in enumerate(ActionProfile.NLE_SURVIVAL_ACTIONS.actions)
}
_DAGGER = next(
    index
    for index in range(nethack.NUM_OBJECTS)
    if nethack.OBJ_NAME(nethack.objclass(index)) == "dagger"
)
_SPORE = next(
    index
    for index in range(nethack.NUMMONS)
    if nethack.permonst(index).mname == "gas spore"
)


def _frame(
    base: ProjectedObservation,
    *,
    target_x: int = 2,
    species: str = "floating eye",
    description: str | None = "floating eye",
    rows: tuple[str, ...] | None = None,
) -> ProjectedObservation:
    if rows is None:
        corridor = list("|@......>|")
        corridor[target_x] = "e"
        rows = ("----------", "".join(corridor), "----------")
    observation = sketch(base, rows)
    glyphs = [list(row) for row in observation.map.glyph_rows]
    if species == "gas spore":
        glyphs[1][target_x] = nethack.GLYPH_MON_OFF + _SPORE
    return replace(
        observation,
        map=replace(observation.map, glyph_rows=tuple(tuple(row) for row in glyphs)),
        player=replace(observation.player, turn=100, strength_25=18),
        inventory=(
            InventoryItem(
                "b",
                "an uncursed +0 dagger",
                nethack.GLYPH_OBJ_OFF + _DAGGER,
                2,
                BucStatus.UNCURSED,
            ),
        ),
        cell_descriptions=()
        if description is None
        else (CellDescription(target_x, 1, description),),
    )


def _show_prior_terrain(
    observation: ProjectedObservation, memory: LevelMemory
) -> ProjectedObservation:
    """Observe floor before a creature occupies it; never invent memory."""
    glyphs = tuple(
        tuple(
            nethack.GLYPH_CMAP_OFF + 19 if nethack.glyph_is_monster(glyph) else glyph
            for glyph in row
        )
        for row in observation.map.glyph_rows
    )
    memory.observe(
        replace(observation, map=replace(observation.map, glyph_rows=glyphs))
    )
    observation = replace(observation, step_index=observation.step_index + 1)
    memory.observe(observation)
    return observation


def _prepared(
    observation: ProjectedObservation,
) -> tuple[ProjectedObservation, LevelMemory]:
    memory = LevelMemory()
    observation = _show_prior_terrain(observation, memory)
    for step in range(1, WAIT_ALLOWANCE + 1):
        memory.record(ActionRecord(ActionKind.WAIT, memory.position))
        observation = replace(
            observation,
            step_index=step + 1,
            player=replace(observation.player, turn=100 + step),
        )
        memory.observe(observation)
    return observation, memory


def _proposal(observation: ProjectedObservation, memory: LevelMemory):
    return throw_at_blocker(observation, memory, _ACTIONS, _GOAL)


def _finish(
    observation: ProjectedObservation, memory: LevelMemory
) -> ProjectedObservation:
    action = _proposal(observation, memory)
    assert action is not None
    memory.record(action.record)
    for message, command in (
        ("What do you want to throw? [b or ?*]", ord("b")),
        ("In what direction?", ord("l")),
    ):
        observation = replace(
            observation,
            step_index=observation.step_index + 1,
            message=message,
            prompt=PromptState(True, False, False),
        )
        memory.observe(observation)
        action = _proposal(observation, memory)
        assert action is not None
        assert action.record.throw.command == command
        memory.record(action.record)
    observation = replace(
        observation,
        step_index=observation.step_index + 1,
        message="The dagger misses.",
        prompt=PromptState(False, False, False),
        player=replace(observation.player, turn=observation.player.turn + 1),
    )
    memory.observe(observation)
    return observation


def test_hostile_adjacent_eye_requires_eight_waits_and_actual_route_blockage(template):
    observation = _frame(template)
    memory = LevelMemory()
    observation = _show_prior_terrain(observation, memory)
    for step in range(WAIT_ALLOWANCE):
        assert expected_throw(observation, memory, _GOAL) is None
        memory.record(ActionRecord(ActionKind.WAIT, memory.position))
        observation = replace(observation, step_index=step + 2)
        memory.observe(observation)
    evidence = expected_throw(observation, memory, _GOAL)
    action = _proposal(observation, memory)
    assert evidence is not None and action is not None
    assert evidence.command == ord("t")
    assert evidence.direction == (1, 0)
    assert action.record.throw == evidence == action.intent.throw

    alternative, alternative_memory = _prepared(
        _frame(template, rows=("----------", "|@e.....>|", "|........|", "----------"))
    )
    assert expected_throw(alternative, alternative_memory, _GOAL) is None


@pytest.mark.parametrize(
    "description",
    [None, "peaceful floating eye", "tame floating eye", "a floating eye"],
)
def test_uncertain_or_peaceful_target_is_not_a_throw_license(template, description):
    observation, memory = _prepared(_frame(template, description=description))
    assert _proposal(observation, memory) is None


@pytest.mark.parametrize("overshoot", ["Q", "j", " "])
def test_full_ray_overshoot_vetoes_other_creatures_and_unknown_cells(
    template, overshoot
):
    row = list("|@e.....>|")
    row[6] = overshoot
    observation, memory = _prepared(
        _frame(template, rows=("----------", "".join(row), "----------"))
    )
    assert _proposal(observation, memory) is None


@pytest.mark.parametrize("distance,allowed", [(1, False), (2, True)])
def test_spore_requires_safe_blast_distance(template, distance, allowed):
    observation, memory = _prepared(
        _frame(
            template,
            target_x=1 + distance,
            species="gas spore",
            description="gas spore",
        )
    )
    assert (_proposal(observation, memory) is not None) is allowed


@pytest.mark.parametrize("collateral", ["f", "Q", "j", "e", " "])
def test_spore_blast_vetoes_collateral_chains_and_unknown_cells(template, collateral):
    top = list("----------")
    top[3] = collateral
    observation = _frame(
        template,
        target_x=3,
        species="gas spore",
        description="gas spore",
        rows=("".join(top), "|@.e....>|", "----------"),
    )
    if collateral == "e":
        glyphs = [list(row) for row in observation.map.glyph_rows]
        glyphs[0][3] = nethack.GLYPH_MON_OFF + _SPORE
        observation = replace(
            observation,
            map=replace(
                observation.map, glyph_rows=tuple(tuple(row) for row in glyphs)
            ),
        )
    observation, memory = _prepared(observation)
    assert _proposal(observation, memory) is None


@pytest.mark.parametrize(
    "buc,allowed", [(BucStatus.UNCURSED, True), (BucStatus.CURSED, False)]
)
def test_typed_dagger_buc_controls_disposal(template, buc, allowed):
    observation = _frame(template)
    observation = replace(
        observation,
        inventory=(
            replace(
                observation.inventory[0],
                buc=buc,
                description=f"a {buc.value} +0 dagger",
            ),
        ),
    )
    observation, memory = _prepared(observation)
    assert (_proposal(observation, memory) is not None) is allowed


@pytest.mark.parametrize("offer", ["$b", "$a-z", "a-z"])
def test_pending_dollar_offer_and_changed_evidence_use_owned_actions(template, offer):
    observation = _frame(template)
    observation = replace(
        observation, inventory=(replace(observation.inventory[0], letter="b"),)
    )
    observation, memory = _prepared(observation)
    action = _proposal(observation, memory)
    assert action is not None
    memory.record(action.record)
    offered = replace(
        observation,
        step_index=observation.step_index + 1,
        message=f"What do you want to throw? [{offer} or ?*]",
        prompt=PromptState(True, False, False),
    )
    memory.observe(offered)
    item = _proposal(offered, memory)
    assert item is not None and item.record.throw.command == ord("b")
    changed = replace(
        offered,
        step_index=offered.step_index + 1,
        cell_descriptions=(CellDescription(2, 1, "peaceful floating eye"),),
    )
    memory.observe(changed)
    cancel = _proposal(changed, memory)
    assert cancel is not None and cancel.record.throw.command == 27
    memory.record(cancel.record)
    assert memory.pending_throw is None
    assert memory.ranged_total_attempts == 1


def test_cooldown_target_budget_and_rearm_revisit_persist(template):
    observation, memory = _prepared(_frame(template))
    observation = _finish(observation, memory)
    assert _proposal(observation, memory) is None
    memory.rearm()
    assert _proposal(observation, memory) is None
    # A real DungeonMemory departure/return must select the same budget owner.
    dungeon = DungeonMemory()
    assert memory.level is not None
    dungeon.levels[memory.level] = memory
    dungeon.observe(observation)
    away = replace(
        observation,
        step_index=observation.step_index + 1,
        player=replace(observation.player, dungeon_level=2),
    )
    dungeon.observe(away)
    observation = replace(observation, step_index=away.step_index + 1)
    assert dungeon.observe(observation) is memory
    assert _proposal(observation, memory) is None
    for _ in range(TARGET_ATTEMPT_LIMIT - 1):
        observation = replace(
            observation,
            step_index=observation.step_index + 1,
            player=replace(
                observation.player,
                turn=observation.player.turn + ATTEMPT_COOLDOWN_TURNS,
            ),
        )
        memory.observe(observation)
        observation = _finish(observation, memory)
    observation = replace(
        observation,
        step_index=observation.step_index + 1,
        player=replace(
            observation.player, turn=observation.player.turn + ATTEMPT_COOLDOWN_TURNS
        ),
    )
    memory.observe(observation)
    assert _proposal(observation, memory) is None
    assert memory.ranged_total_attempts == TARGET_ATTEMPT_LIMIT


def test_level_budget_limits_distinct_route_blockers(template):
    observation, memory = _prepared(_frame(template))
    for attempt in range(LEVEL_ATTEMPT_LIMIT):
        if attempt:
            fresh = _frame(template, target_x=2 + attempt)
            observation = replace(
                fresh,
                step_index=observation.step_index + 1,
                player=replace(
                    fresh.player, turn=observation.player.turn + ATTEMPT_COOLDOWN_TURNS
                ),
            )
            memory.observe(observation)
        observation = _finish(observation, memory)
    fresh = _frame(template, target_x=2 + LEVEL_ATTEMPT_LIMIT)
    observation = replace(
        fresh,
        step_index=observation.step_index + 1,
        player=replace(
            fresh.player, turn=observation.player.turn + ATTEMPT_COOLDOWN_TURNS
        ),
    )
    memory.observe(observation)
    memory.rearm()
    assert memory.ranged_total_attempts == LEVEL_ATTEMPT_LIMIT
    assert _proposal(observation, memory) is None


def test_native_refusal_clears_ownership_without_zero_turn_reopen(template):
    observation, memory = _prepared(_frame(template))
    opening = _proposal(observation, memory)
    assert opening is not None
    memory.record(opening.record)
    refused = replace(
        observation,
        step_index=observation.step_index + 1,
        message="You cannot throw anything.",
    )
    memory.observe(refused)
    assert memory.pending_throw is None
    memory.rearm()
    assert memory.ranged_total_attempts == 1
    assert _proposal(refused, memory) is None


def test_unpaid_dagger_is_not_disposed_as_ammunition(template):
    observation = _frame(template)
    dagger = replace(
        observation.inventory[0],
        description="an uncursed +0 dagger (unpaid, 4 zorkmids)",
        buc=BucStatus.UNCURSED,
    )
    observation, memory = _prepared(replace(observation, inventory=(dagger,)))
    assert _proposal(observation, memory) is None


def test_unknown_exit_uses_monster_blocked_exploration_frontier(template):
    observation, memory = _prepared(
        _frame(template, rows=("----------", "|@e......|", "-------- -"))
    )
    assert not memory.stairs(StairDirection.DOWN)
    action = _proposal(observation, memory)
    assert action is not None
    assert action.record.throw.command == ord("t")
