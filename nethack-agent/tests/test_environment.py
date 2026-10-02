from pathlib import Path

import gymnasium as gym
import numpy as np
import pytest
from nle import nethack

from nethack_agent.environment import (
    EnvironmentState,
    EnvironmentStateError,
    LegalAction,
    NleEnvironment,
    ScenarioConfig,
    make_nle_environment,
)
from nethack_agent.observation import ObservationProjector, PromptState
from nethack_agent.tasks import (
    STAIRCASE_TASK,
    ActionProfile,
    NleTask,
    TaskSpec,
)


def scenario(directory: Path, *, seed: int = 6, max_steps: int = 20) -> ScenarioConfig:
    return ScenarioConfig(
        seed=seed,
        artifact_directory=directory,
        max_episode_steps=max_steps,
    )


def test_episode_exposes_public_state_and_finalizes_ttyrec(tmp_path: Path) -> None:
    environment = NleEnvironment(scenario(tmp_path))

    with environment:
        observation = environment.reset()
        assert environment.state is EnvironmentState.RUNNING
        assert observation.chars.shape == (21, 79)
        assert not hasattr(observation, "internal")
        assert [action.index for action in environment.legal_actions] == list(
            range(len(environment.legal_actions))
        )
        assert all(
            LegalAction.from_json(action.to_json()) == action
            for action in environment.legal_actions
        )
        transition = environment.step(0)
        assert transition.step_index == 1

    assert environment.state is EnvironmentState.CLOSED
    assert len(environment.ttyrec_files) == 1


def _engine_options(environment: gym.Env) -> list[str]:  # type: ignore[type-arg]
    options = environment.unwrapped.nethack.options  # type: ignore[attr-defined]
    return [option for option in options if not option.startswith("name:")]


@pytest.mark.parametrize("task", list(NleTask))
def test_each_task_gets_nle_own_options_plus_autoopen(
    tmp_path: Path, task: NleTask
) -> None:
    # NLE applies a task's own option choice only when no options are passed;
    # the adapter must reproduce it, then pin `autoopen`. Both lists are read
    # from the live engine.
    default = gym.make(task.value)
    try:
        expected = [*_engine_options(default), "autoopen"]
    finally:
        default.close()
    adapted = make_nle_environment(
        task,
        ActionProfile.NLE_TASK_ACTIONS,
        max_episode_steps=5,
        savedir=tmp_path / "episode",
    )
    try:
        options = _engine_options(adapted)
    finally:
        adapted.close()

    assert options == expected
    if task is NleTask.GOLD:
        assert "pickup_types:$" in options


def test_legal_actions_are_the_profile_actions_nle_received(tmp_path: Path) -> None:
    profile = ActionProfile.NLE_TASK_ACTIONS
    with NleEnvironment(scenario(tmp_path)) as environment:
        engine_actions = tuple(environment._raw_environment.actions)
        table = [(action.command, action.name) for action in environment.legal_actions]

    assert engine_actions == profile.actions
    assert table == [
        (int(action), f"{type(action).__name__}.{action.name}")
        for action in profile.actions
    ]


def test_same_suite_seed_reproduces_initial_observation(tmp_path: Path) -> None:
    snapshots = []
    seed_sets = []
    for run_number in range(2):
        with NleEnvironment(scenario(tmp_path / f"run-{run_number}")) as environment:
            observation = environment.reset()
            snapshots.append(
                (
                    observation.glyphs.copy(),
                    observation.blstats.copy(),
                    observation.message.copy(),
                )
            )
            seed_sets.append(environment.seed_set)

    assert seed_sets[0] == seed_sets[1]
    for first, second in zip(snapshots[0], snapshots[1], strict=True):
        np.testing.assert_array_equal(first, second)


def test_invalid_action_is_rejected_without_advancing_episode(tmp_path: Path) -> None:
    with NleEnvironment(scenario(tmp_path)) as environment:
        environment.reset()

        with pytest.raises(ValueError, match="action_index"):
            environment.step(len(environment.legal_actions))

        assert environment.step_index == 0
        assert environment.state is EnvironmentState.RUNNING


def test_step_cap_terminates_adapter_lifecycle(tmp_path: Path) -> None:
    with NleEnvironment(scenario(tmp_path, max_steps=1)) as environment:
        environment.reset()
        transition = environment.step(0)

        assert transition.truncated
        assert transition.is_terminal
        assert environment.state is EnvironmentState.TERMINAL
        with pytest.raises(EnvironmentStateError, match="terminal"):
            environment.step(0)


def test_step_cap_above_nle_default_ends_as_truncation(tmp_path: Path) -> None:
    # NLE's own abort fires at 5,000 steps unless it receives the cap, and it
    # reports its cap as a terminated ABORTED (-1) episode, not a truncation.
    with NleEnvironment(scenario(tmp_path, max_steps=5_001)) as environment:
        environment.reset()
        transition = environment.step(0)  # MiscAction.MORE: no game time passes
        while not transition.is_terminal:
            transition = environment.step(0)

    assert transition.step_index == 5_001
    assert transition.truncated
    assert not transition.terminated
    assert transition.end_status == 0


def test_running_episode_cannot_be_reset(tmp_path: Path) -> None:
    with NleEnvironment(scenario(tmp_path)) as environment:
        environment.reset()

        with pytest.raises(EnvironmentStateError, match="running"):
            environment.reset()


def test_reusing_artifact_root_keeps_ttyrecs_isolated(tmp_path: Path) -> None:
    artifact_root = tmp_path / "shared"
    environments = [
        NleEnvironment(scenario(artifact_root, seed=seed)) for seed in (6, 7)
    ]

    for environment in environments:
        environment.reset()
        environment.close()

    first_files = environments[0].ttyrec_files
    second_files = environments[1].ttyrec_files
    assert len(first_files) == len(second_files) == 1
    assert first_files[0] != second_files[0]
    assert first_files[0].parent != second_files[0].parent
    assert set(first_files).isdisjoint(second_files)


def _survival_scenario(directory: Path, *, seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        seed=seed,
        artifact_directory=directory,
        max_episode_steps=5,
        task=TaskSpec(
            NleTask.STAIRCASE,
            ActionProfile.NLE_SURVIVAL_ACTIONS,
            STAIRCASE_TASK.objective,
        ),
    )


def test_pray_confirmation_is_the_real_nle_prompt(tmp_path: Path) -> None:
    with NleEnvironment(_survival_scenario(tmp_path, seed=6)) as environment:
        projector = ObservationProjector()
        projector.project(environment.reset(), step_index=0)
        pray = next(
            action.index
            for action in environment.legal_actions
            if action.command == int(nethack.Command.PRAY)
        )

        transition = environment.step(pray)
        observation = projector.project(
            transition.observation, step_index=transition.step_index
        )

        assert observation.message == "Are you sure you want to pray? [yn] (n) "
        assert observation.prompt == PromptState(True, False, False)


def test_eat_confirmation_on_a_newly_killed_floor_lichen(tmp_path: Path) -> None:
    # Seed 10 starts next to a lichen. A southeast melee kill leaves its
    # corpse on that square; walk onto it before issuing EAT.
    with NleEnvironment(_survival_scenario(tmp_path, seed=10)) as environment:
        projector = ObservationProjector()
        projector.project(environment.reset(), step_index=0)
        actions = {action.command: action.index for action in environment.legal_actions}

        kill = environment.step(actions[int(nethack.CompassDirection.SE)])
        killed = projector.project(kill.observation, step_index=kill.step_index)
        assert killed.message == "You kill the lichen!"

        move = environment.step(actions[int(nethack.CompassDirection.SE)])
        on_corpse = projector.project(move.observation, step_index=move.step_index)
        assert on_corpse.message == "You see here a lichen corpse."

        eat = environment.step(actions[int(nethack.Command.EAT)])
        offered = projector.project(eat.observation, step_index=eat.step_index)
        assert offered.message == "There is a lichen corpse here; eat it? [ynq] (n) "
        assert offered.prompt == PromptState(True, False, False)
