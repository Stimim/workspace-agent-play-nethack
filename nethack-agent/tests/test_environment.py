from pathlib import Path

import numpy as np
import pytest

from nethack_agent.environment import (
    EnvironmentState,
    EnvironmentStateError,
    NleEnvironment,
    ScenarioConfig,
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
        transition = environment.step(0)
        assert transition.step_index == 1

    assert environment.state is EnvironmentState.CLOSED
    assert len(environment.ttyrec_files) == 1


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
