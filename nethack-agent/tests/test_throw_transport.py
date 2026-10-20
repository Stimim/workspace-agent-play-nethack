"""Real NLE I/O regression tests for the adapter's multi-step THROW exchange."""

from functools import partial
from pathlib import Path
from typing import Any

import gymnasium as gym
import pytest
from nle import nethack

from nethack_agent.environment import NleEnvironment, NleObservation, ScenarioConfig
from nethack_agent.tasks import STAIRCASE_TASK, ActionProfile, NleTask, TaskSpec


def _scenario(directory: Path) -> ScenarioConfig:
    return ScenarioConfig(
        seed=6,
        artifact_directory=directory,
        max_episode_steps=40,
        task=TaskSpec(
            NleTask.STAIRCASE,
            ActionProfile.NLE_SURVIVAL_ACTIONS,
            STAIRCASE_TASK.objective,
        ),
    )


def _step(environment: NleEnvironment, command: int) -> NleObservation:
    action = next(a for a in environment.legal_actions if a.command == command)
    transition = environment.step(action.index)
    assert not transition.is_terminal
    # The temporary override must never become the engine's default.
    assert not environment._raw_environment._allow_all_modes
    return transition.observation


def _message(observation: NleObservation) -> str:
    return bytes(observation.message).split(b"\0", 1)[0].decode()


def _dagger_letter(observation: NleObservation) -> int:
    return next(
        int(letter)
        for letter, description in zip(
            observation.inv_letters, observation.inv_strs, strict=True
        )
        if b"dagger" in bytes(description)
    )


def _assert_item_prompt(observation: NleObservation, letter: int) -> None:
    message = _message(observation)
    assert message.startswith("What do you want to throw?")
    assert observation.misc[0]
    # Check the actual native offer, including compact ranges and '$'.
    offer = message.split("[", 1)[1].split(" or ", 1)[0].split("]", 1)[0]
    offered = set(offer)
    for index in range(1, len(offer) - 1):
        if offer[index] == "-":
            offered.update(
                chr(value)
                for value in range(ord(offer[index - 1]), ord(offer[index + 1]) + 1)
            )
    assert chr(letter) in offered


def _finish_more(
    environment: NleEnvironment, observation: NleObservation
) -> NleObservation:
    for _ in range(10):
        if not observation.misc[2]:
            return observation
        assert environment._throw_prompt_open
        observation = _step(environment, int(nethack.MiscAction.MORE))
    pytest.fail("native THROW did not finish after ten MORE pages")


def _assert_ordinary_command_is_atomic(environment: NleEnvironment) -> None:
    assert not environment._throw_prompt_open
    # WIELD has an inventory question, but is not one of the reviewed prompts.
    # A leaked THROW mode would expose it instead of NLE dismissing it.
    observation = _step(environment, int(nethack.Command.WIELD))
    assert not any(observation.misc)
    assert not _message(observation).startswith("What do you want to wield?")
    assert not environment._throw_prompt_open


def test_native_starting_dagger_reaches_direction_and_leaves_inventory(
    tmp_path: Path,
) -> None:
    with NleEnvironment(_scenario(tmp_path)) as environment:
        initial = environment.reset()
        letter = _dagger_letter(initial)
        # The real Valkyrie dagger key collides with a compass action.
        assert letter == int(nethack.CompassDirection.SW)
        turn = int(initial.blstats[nethack.NLE_BL_TIME])
        position = tuple(int(value) for value in initial.blstats[:2])

        offered = _step(environment, int(nethack.Command.THROW))
        _assert_item_prompt(offered, letter)
        direction = _step(environment, letter)
        assert _message(direction).startswith("In what direction?")
        assert direction.misc[0]
        assert int(direction.blstats[nethack.NLE_BL_TIME]) == turn
        assert tuple(int(value) for value in direction.blstats[:2]) == position

        thrown = _finish_more(
            environment, _step(environment, int(nethack.CompassDirection.N))
        )
        assert letter not in thrown.inv_letters
        assert int(thrown.blstats[nethack.NLE_BL_TIME]) > turn
        assert tuple(int(value) for value in thrown.blstats[:2]) == position
        _assert_ordinary_command_is_atomic(environment)


@pytest.mark.parametrize("at_direction", [False, True])
def test_native_throw_cancellation_does_not_leak_prompt_mode(
    tmp_path: Path, at_direction: bool
) -> None:
    with NleEnvironment(_scenario(tmp_path)) as environment:
        initial = environment.reset()
        letter = _dagger_letter(initial)
        turn = int(initial.blstats[nethack.NLE_BL_TIME])
        _assert_item_prompt(_step(environment, int(nethack.Command.THROW)), letter)
        if at_direction:
            direction = _step(environment, letter)
            assert _message(direction).startswith("In what direction?")
        cancelled = _finish_more(
            environment, _step(environment, int(nethack.Command.ESC))
        )
        assert not any(cancelled.misc)
        assert letter in cancelled.inv_letters
        assert int(cancelled.blstats[nethack.NLE_BL_TIME]) == turn
        _assert_ordinary_command_is_atomic(environment)
        # Cancellation must also allow a fresh THROW, not only ordinary commands.
        _assert_item_prompt(_step(environment, int(nethack.Command.THROW)), letter)
        _step(environment, int(nethack.Command.ESC))


def test_native_gold_offer_survives_throw_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Diagnostic-only native setup: NLE's supported wizard/wizkit interface
    # creates real gold. No fabricated observation or native truth enters policy.
    original_make = gym.make

    def make_with_wizard(*args: Any, **kwargs: Any) -> gym.Env[Any, Any]:
        return original_make(*args, **kwargs, wizard=True)

    monkeypatch.setattr(gym, "make", make_with_wizard)
    with NleEnvironment(_scenario(tmp_path)) as environment:
        monkeypatch.setattr(
            environment._environment,
            "reset",
            partial(
                environment._environment.reset,
                options={"wizkit_items": ["10 gold pieces"]},
            ),
        )
        initial = environment.reset()
        gold = int(initial.blstats[nethack.NLE_BL_GOLD])
        assert gold >= 10
        turn = int(initial.blstats[nethack.NLE_BL_TIME])
        _assert_item_prompt(_step(environment, int(nethack.Command.THROW)), ord("$"))
        direction = _step(environment, ord("$"))
        assert _message(direction).startswith("In what direction?")
        assert direction.misc[0]
        thrown = _finish_more(
            environment, _step(environment, int(nethack.CompassDirection.N))
        )
        assert int(thrown.blstats[nethack.NLE_BL_GOLD]) < gold
        assert int(thrown.blstats[nethack.NLE_BL_TIME]) > turn
        _assert_ordinary_command_is_atomic(environment)
