import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest


def _strip_pet_evidence(database: Path) -> int:
    """Rewrite stored observations to the shape recorded before pet evidence.

    Milestone 1 events were persisted without observation inventory `buc`,
    `map.pet_rows`, or changed-cell `pet`; this reproduces that exact shape from
    freshly recorded events.
    """
    stripped = 0
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
            connection.execute(
                "UPDATE events SET payload_json = ? WHERE rowid = ?",
                (json.dumps(payload), rowid),
            )
            stripped += 1
    return stripped


@pytest.fixture
def strip_pet_evidence() -> Callable[[Path], int]:
    return _strip_pet_evidence
