from __future__ import annotations

import random
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, Self

import gymnasium as gym
import nle  # noqa: F401  # Registers the NLE Gymnasium environments.
import numpy as np
from nle import nethack
from numpy.typing import NDArray

from nethack_agent.contracts import integer_value, object_value, string_value

STAIRCASE_ENVIRONMENT: Final = "NetHackStaircase-v0"
STAIRCASE_CHARACTER: Final = "val-dwa-law"
# NLE's default option tuple does not name `autoopen`, even though vanilla
# NetHack currently defaults it on. Pin it so navigation does not depend on an
# upstream default.
NLE_OPTIONS: Final = (*nethack.NETHACKOPTIONS, "autoopen")
PUBLIC_OBSERVATION_KEYS: Final = (
    "glyphs",
    "chars",
    "colors",
    "specials",
    "blstats",
    "message",
    "program_state",
    "inv_glyphs",
    "inv_strs",
    "inv_letters",
    "inv_oclasses",
    "tty_chars",
    "tty_colors",
    "tty_cursor",
    "misc",
)

NleArray = NDArray[np.generic]


class EnvironmentState(Enum):
    READY = "ready"
    RUNNING = "running"
    TERMINAL = "terminal"
    CLOSED = "closed"


class EnvironmentStateError(RuntimeError):
    """The requested operation is invalid for the environment lifecycle."""


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Configuration fixed for one deterministic Staircase episode."""

    seed: int
    artifact_directory: Path
    max_episode_steps: int = 5_000

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")
        if not 1 <= self.seed <= sys.maxsize:
            raise ValueError(f"seed must be between 1 and {sys.maxsize}")
        if isinstance(self.max_episode_steps, bool) or not isinstance(
            self.max_episode_steps, int
        ):
            raise TypeError("max_episode_steps must be an integer")
        if self.max_episode_steps <= 0:
            raise ValueError("max_episode_steps must be greater than zero")
        artifact_directory = Path(self.artifact_directory).expanduser().resolve()
        if artifact_directory.exists() and not artifact_directory.is_dir():
            raise ValueError("artifact_directory must be a directory")
        object.__setattr__(self, "artifact_directory", artifact_directory)


@dataclass(frozen=True, slots=True)
class SeedSet:
    core: int
    display: int
    level: int

    @classmethod
    def derive(cls, seed: int) -> Self:
        generator = random.Random(seed)
        return cls(
            core=generator.randrange(1, sys.maxsize),
            display=generator.randrange(1, sys.maxsize),
            level=generator.randrange(1, sys.maxsize),
        )


@dataclass(frozen=True, slots=True)
class LegalAction:
    index: int
    command: int
    name: str

    def __post_init__(self) -> None:
        integer_value(self.index, "action index", minimum=0)
        integer_value(self.command, "action command")
        string_value(self.name, "action name", minimum=1, maximum=120)

    def to_json(self) -> dict[str, object]:
        return {"index": self.index, "command": self.command, "name": self.name}

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "legal action", {"index", "command", "name"})
        return cls(
            index=integer_value(payload["index"], "action index", minimum=0),
            command=integer_value(payload["command"], "action command"),
            name=string_value(payload["name"], "action name", minimum=1, maximum=120),
        )


@dataclass(frozen=True, slots=True)
class NleObservation:
    """Zero-copy public NLE observation, valid until the next reset or step."""

    glyphs: NleArray
    chars: NleArray
    colors: NleArray
    specials: NleArray
    blstats: NleArray
    message: NleArray
    program_state: NleArray
    inv_glyphs: NleArray
    inv_strs: NleArray
    inv_letters: NleArray
    inv_oclasses: NleArray
    tty_chars: NleArray
    tty_colors: NleArray
    tty_cursor: NleArray
    misc: NleArray

    @classmethod
    def from_nle(cls, observation: Mapping[str, NleArray]) -> Self:
        return cls(
            glyphs=observation["glyphs"],
            chars=observation["chars"],
            colors=observation["colors"],
            specials=observation["specials"],
            blstats=observation["blstats"],
            message=observation["message"],
            program_state=observation["program_state"],
            inv_glyphs=observation["inv_glyphs"],
            inv_strs=observation["inv_strs"],
            inv_letters=observation["inv_letters"],
            inv_oclasses=observation["inv_oclasses"],
            tty_chars=observation["tty_chars"],
            tty_colors=observation["tty_colors"],
            tty_cursor=observation["tty_cursor"],
            misc=observation["misc"],
        )


@dataclass(frozen=True, slots=True)
class StepTransition:
    observation: NleObservation
    reward: float
    terminated: bool
    truncated: bool
    end_status: int
    is_ascended: bool
    step_index: int

    @property
    def is_terminal(self) -> bool:
        return self.terminated or self.truncated


class NleEnvironment:
    """Validated lifecycle and action boundary around NLE's Staircase task."""

    def __init__(self, config: ScenarioConfig) -> None:
        config.artifact_directory.mkdir(parents=True, exist_ok=True)
        self._artifact_directory = Path(
            tempfile.mkdtemp(prefix="episode-", dir=config.artifact_directory)
        )
        environment = gym.make(
            STAIRCASE_ENVIRONMENT,
            character=STAIRCASE_CHARACTER,
            observation_keys=PUBLIC_OBSERVATION_KEYS,
            options=NLE_OPTIONS,
            save_ttyrec_every=1,
            savedir=str(self._artifact_directory),
            max_episode_steps=config.max_episode_steps,
            render_mode="ansi",
            fix_moon_phase=True,
        )
        raw_environment = environment.unwrapped
        self._config = config
        self._environment = environment
        self._raw_environment = raw_environment
        self._state = EnvironmentState.READY
        self._step_index = 0
        self._seed_set = SeedSet.derive(config.seed)
        self._legal_actions = tuple(
            LegalAction(
                index=index,
                command=int(command),
                name=f"{type(command).__name__}.{command.name}",
            )
            for index, command in enumerate(raw_environment.actions)
        )

    @property
    def config(self) -> ScenarioConfig:
        return self._config

    @property
    def state(self) -> EnvironmentState:
        return self._state

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def seed_set(self) -> SeedSet:
        return self._seed_set

    @property
    def legal_actions(self) -> tuple[LegalAction, ...]:
        return self._legal_actions

    @property
    def ttyrec_files(self) -> tuple[Path, ...]:
        return tuple(sorted(self._artifact_directory.glob("*.ttyrec*.bz2")))

    def reset(self) -> NleObservation:
        if self._state is EnvironmentState.CLOSED:
            raise EnvironmentStateError("cannot reset a closed environment")
        if self._state is EnvironmentState.RUNNING:
            raise EnvironmentStateError("cannot reset a running episode")
        self._raw_environment.seed(
            core=self._seed_set.core,
            disp=self._seed_set.display,
            reseed=False,
            lgen=self._seed_set.level,
        )
        observation, _ = self._environment.reset(seed=self._config.seed)
        self._step_index = 0
        self._state = EnvironmentState.RUNNING
        return NleObservation.from_nle(observation)

    def step(self, action_index: int) -> StepTransition:
        if self._state is not EnvironmentState.RUNNING:
            raise EnvironmentStateError(
                f"cannot step an environment in state {self._state.value!r}"
            )
        if isinstance(action_index, bool) or not isinstance(action_index, int):
            raise TypeError("action_index must be an integer")
        if not 0 <= action_index < len(self._legal_actions):
            raise ValueError(
                f"action_index must be between 0 and {len(self._legal_actions) - 1}"
            )

        observation, reward, terminated, truncated, information = (
            self._environment.step(action_index)
        )
        self._step_index += 1
        if terminated or truncated:
            self._state = EnvironmentState.TERMINAL
        return StepTransition(
            observation=NleObservation.from_nle(observation),
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            end_status=int(information["end_status"]),
            is_ascended=bool(information["is_ascended"]),
            step_index=self._step_index,
        )

    def close(self) -> None:
        if self._state is EnvironmentState.CLOSED:
            return
        self._environment.close()
        self._state = EnvironmentState.CLOSED

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
