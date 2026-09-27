import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest


def _to_milestone_1_shape(database: Path) -> int:
    """Rewrite stored events to the shape milestone 1 recorded.

    Milestone 1 events were persisted without observation inventory `buc`,
    `map.pet_rows`, changed-cell `pet`, or step `selection.intent`; this
    reproduces that exact shape from freshly recorded events and returns the
    rewritten event count.
    """
    rewritten = 0
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT rowid, payload_json FROM events").fetchall()
        for rowid, text in rows:
            payload = json.loads(text)
            observation = payload.get("observation")
            if observation is None:
                continue
            del observation["map"]["pet_rows"]
            for cell in observation["changed_cells"]:
                del cell["pet"]
            for item in observation["inventory"]:
                del item["buc"]
            selection = payload.get("selection")
            if selection is not None:
                del selection["intent"]
            connection.execute(
                "UPDATE events SET payload_json = ? WHERE rowid = ?",
                (json.dumps(payload), rowid),
            )
            rewritten += 1
    return rewritten


@pytest.fixture
def to_milestone_1_shape() -> Callable[[Path], int]:
    return _to_milestone_1_shape
