import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest


def _rewrite_events(
    database: Path, rewrite: Callable[[dict[str, object]], bool]
) -> int:
    """Apply `rewrite` to every stored event; return how many it changed."""
    rewritten = 0
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT rowid, payload_json FROM events").fetchall()
        for rowid, text in rows:
            payload = json.loads(text)
            if not rewrite(payload):
                continue
            connection.execute(
                "UPDATE events SET payload_json = ? WHERE rowid = ?",
                (json.dumps(payload), rowid),
            )
            rewritten += 1
    return rewritten


def _milestone_1_event(payload: dict[str, object]) -> bool:
    observation = payload.get("observation")
    if observation is None:
        return False
    del observation["map"]["pet_rows"]  # type: ignore[index]
    for cell in observation["changed_cells"]:  # type: ignore[index]
        del cell["pet"]
    for item in observation["inventory"]:  # type: ignore[index]
        del item["buc"]
    selection = payload.get("selection")
    if selection is not None:
        del selection["intent"]  # type: ignore[attr-defined]
    return True


def _pathless_intent_event(payload: dict[str, object]) -> bool:
    selection = payload.get("selection")
    intent = None if selection is None else selection["intent"]  # type: ignore[index]
    if intent is None:
        return False
    del intent["path"]
    return True


def _to_milestone_1_shape(database: Path) -> int:
    """Rewrite stored events to the shape milestone 1 recorded.

    Milestone 1 events were persisted without observation inventory `buc`,
    `map.pet_rows`, changed-cell `pet`, or step `selection.intent`; this
    reproduces that exact shape from freshly recorded events and returns the
    """
    return _rewrite_events(database, _milestone_1_event)


def _to_pathless_intent_shape(database: Path) -> int:
    """Rewrite step intents to the shape recorded before routes existed.

    Those intents had `destination` and `attack_target` but no `path` key;
    returns the number of rewritten step events.
    """
    return _rewrite_events(database, _pathless_intent_event)


@pytest.fixture
def to_milestone_1_shape() -> Callable[[Path], int]:
    return _to_milestone_1_shape


@pytest.fixture
def to_pathless_intent_shape() -> Callable[[Path], int]:
    return _to_pathless_intent_shape
