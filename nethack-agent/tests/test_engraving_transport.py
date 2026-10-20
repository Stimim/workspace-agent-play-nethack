"""Real NLE dialogue coverage; no policy or native-memory shortcuts."""

from pathlib import Path

import numpy as np
from nle import nethack

from nethack_agent.environment import NleEnvironment, NleObservation, ScenarioConfig
from nethack_agent.tasks import (
    STAIRCASE_TASK,
    ActionProfile,
    ActionRole,
    NleTask,
    TaskSpec,
)


def _scenario(directory: Path) -> ScenarioConfig:
    return ScenarioConfig(
        seed=6,
        artifact_directory=directory,
        max_episode_steps=100,
        task=TaskSpec(
            NleTask.SCORE,
            ActionProfile.NLE_SURVIVAL_ACTIONS,
            STAIRCASE_TASK.objective,
        ),
    )


def _step(environment: NleEnvironment, key: str) -> NleObservation:
    action = next(
        action for action in environment.legal_actions if action.command == ord(key)
    )
    transition = environment.step(action.index)
    assert not transition.is_terminal
    # Preservation is scoped to each native call, never left enabled globally.
    assert not environment._raw_environment._allow_all_modes
    return transition.observation


def _message(observation: NleObservation) -> str:
    return bytes(observation.message).split(b"\0", 1)[0].decode()


def _start(environment: NleEnvironment, *, overwrite: bool) -> NleObservation:
    observation = _step(environment, "E")
    assert _message(observation).startswith("What do you want to write with?")
    assert tuple(observation.misc) == (1, 0, 0)
    observation = _step(environment, "-")
    if overwrite:
        assert _message(observation).startswith(
            "Do you want to add to the current engraving?"
        )
        assert tuple(observation.misc) == (1, 0, 0)
        observation = _step(environment, "n")
        assert _message(observation) == (
            "You wipe out the message that was written in the dust here."
        )
        assert tuple(observation.misc) == (0, 0, 1)
        observation = _step(environment, "\r")
    assert _message(observation) == "You write in the dust with your fingertip."
    assert tuple(observation.misc) == (0, 1, 1)
    assert environment._engraving_prompt_open
    observation = _step(environment, "\r")
    assert _message(observation) == "What do you want to write in the dust here? "
    assert tuple(observation.misc) == (0, 1, 0)
    return observation


def _write(environment: NleEnvironment) -> None:
    for length, letter in enumerate("Elbereth", start=1):
        observation = _step(environment, letter)
        assert tuple(observation.misc) == (0, 1, 0)
        assert _message(observation) == (
            "What do you want to write in the dust here? " + "Elbereth"[:length]
        )
        # E and e are text, not a second engraving command or an EAT command.
        assert environment._engraving_prompt_open
        assert not environment._drop_prompt_open
        assert not environment._pickup_menu_open
        assert not environment._look_menu_open
    observation = _step(environment, "\r")
    assert not np.any(observation.misc)
    assert not environment._engraving_prompt_open
    assert environment._command_ready


def _read(environment: NleEnvironment) -> str:
    observation = _step(environment, ":")
    assert _message(observation) == (
        "There is a staircase up here.  Something is written here in the dust."
    )
    assert tuple(observation.misc) == (0, 0, 1)
    assert environment._look_menu_open
    observation = _step(environment, "\r")
    assert not np.any(observation.misc)
    assert not environment._look_menu_open
    assert not environment._engraving_prompt_open
    return _message(observation)


def test_survival_appends_minus_without_renumbering_existing_actions() -> None:
    actions = ActionProfile.NLE_SURVIVAL_ACTIONS.actions
    assert len(actions) == 73
    assert actions[43] is nethack.Command.ENGRAVE
    assert actions[60] is nethack.Command.LOOK
    assert actions[61:72] == tuple(
        nethack.TextCharacters(value)
        for value in (*range(ord("0"), ord("9") + 1), ord("$"))
    )
    assert actions[72] is nethack.TextCharacters.MINUS
    assert ActionProfile.NLE_SURVIVAL_ACTIONS.role(actions[43]) is ActionRole.ENGRAVING
    assert ActionProfile.NLE_SURVIVAL_ACTIONS.role(actions[72]) is ActionRole.PROMPT_KEY
    assert ActionProfile.NLE_HUNGER_ACTIONS.role(actions[43]) is ActionRole.PROMPT_KEY


def test_native_engraving_letters_commit_and_look_readback(tmp_path: Path) -> None:
    with NleEnvironment(_scenario(tmp_path)) as environment:
        initial = environment.reset()
        position = initial.blstats[:2].copy()
        _start(environment, overwrite=False)
        _write(environment)
        assert _read(environment) == 'You read: "Elbereth".'
        # Movement-letter keys in getlin did not move the hero.
        np.testing.assert_array_equal(
            environment._raw_environment.nethack._obs_buffers["blstats"][:2],
            position,
        )
        # Ordinary r must retain NLE's default auto-ESC rather than exposing a
        # new unrelated inventory-selection dialogue after engraving/readback.
        observation = _step(environment, "r")
        assert not np.any(observation.misc)
        assert not environment._engraving_prompt_open
        # Ordinary e must still open the food prompt, not restart getlin.
        observation = _step(environment, "e")
        assert _message(observation).startswith("What do you want to eat?")
        assert tuple(observation.misc) == (1, 0, 0)
        assert not environment._engraving_prompt_open


def test_native_overwrite_keeps_both_more_pages_and_corrupted_readback(
    tmp_path: Path,
) -> None:
    # The source-check seed-6 transcript has a correct first dust engraving,
    # then ElbOreth on overwrite. Readback must expose, not repair, corruption.
    with NleEnvironment(_scenario(tmp_path)) as environment:
        environment.reset()
        _start(environment, overwrite=False)
        _write(environment)
        assert _read(environment) == 'You read: "Elbereth".'
        _start(environment, overwrite=True)
        _write(environment)
        assert _read(environment) == 'You read: "ElbOreth".'


def test_native_escape_closes_engraving_preservation(tmp_path: Path) -> None:
    with NleEnvironment(_scenario(tmp_path)) as environment:
        environment.reset()
        _start(environment, overwrite=False)
        observation = _step(environment, "\x1b")
        assert not np.any(observation.misc)
        assert not environment._engraving_prompt_open
        observation = _step(environment, "r")
        assert not np.any(observation.misc)
        assert not environment._engraving_prompt_open


def test_native_inventory_letter_E_is_not_an_engraving_command(
    tmp_path: Path,
) -> None:
    with NleEnvironment(_scenario(tmp_path)) as environment:
        environment.reset()
        observation = _step(environment, "d")
        assert _message(observation).startswith("What do you want to drop?")
        assert environment._drop_prompt_open
        _step(environment, "E")
        assert not environment._engraving_prompt_open
