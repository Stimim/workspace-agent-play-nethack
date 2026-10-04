"""Replay recorded public actions and inspect selected native snapshots."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from analysis import analyze, render
from native_truth import NativeTruth, ValidationError

from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.observation import ObservationProjector
from nethack_agent.tasks import TaskSpec

SHOPKEEPER_NAMES = tuple(
    name
    for name in Path(__file__)
    .with_name("shopkeeper_names.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if name
)
_SHOPKEEPER_NAME = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(
        re.escape(name) for name in sorted(SHOPKEEPER_NAMES, key=len, reverse=True)
    )
    + r")(?='s\b|\b)"
)


class ReplayMismatch(AssertionError):
    """Recorded and reproduced public observations differ."""


def normalize_names(value: object) -> object:
    """Normalize only source-listed shopkeeper names in recorded text fields."""
    if isinstance(value, str):
        return _SHOPKEEPER_NAME.sub("<SHOPKEEPER>", value)
    if isinstance(value, list):
        return [normalize_names(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_names(item) for key, item in value.items()}
    return value


def assert_observation(actual: dict, expected: dict, step: int) -> None:
    left, right = normalize_names(actual), normalize_names(expected)
    if left != right:
        keys = [key for key in actual if left.get(key) != right.get(key)]
        details = {key: {"actual": left[key], "recorded": right[key]} for key in keys}
        raise ReplayMismatch(
            f"observation mismatch at step {step}: {json.dumps(details)}"
        )


def replay(
    database: Path,
    *,
    run_id: str | None = None,
    seed: int | None = None,
    at: tuple[str, ...] = ("end",),
    every_level_entry: bool = False,
) -> dict:
    """Rebuild an entire episode; never publish snapshots from divergent replay.

    STEP is the projected observation step_index (0 is reset), and
    first-on-final-level means the first visit to the last recorded level.
    SEARCH coverage uses the before-action hero positions on that level.
    """
    if (run_id is None) == (seed is None):
        raise ValueError("select exactly one run id or seed")
    with sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro", uri=True
    ) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM runs WHERE " + ("id = ?" if run_id else "suite_seed = ?"),
            (run_id if run_id else seed,),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                f"selector matches {len(rows)} runs; use an unambiguous run id"
            )
        metadata = dict(rows[0])
        records = [
            (row["kind"], json.loads(row["payload_json"]))
            for row in connection.execute(
                "SELECT kind,payload_json FROM events WHERE run_id=? ORDER BY sequence",
                (metadata["id"],),
            )
        ]
    started = [payload for kind, payload in records if kind == "run_started"]
    steps = [payload for kind, payload in records if kind == "step"]
    if len(started) != 1:
        raise ValueError("run must have exactly one run_started event")
    initial = started[0]
    task = TaskSpec.from_json(json.loads(metadata["task"]))
    if metadata["nle_version"] != "1.3.0" or metadata["character"] != "val-dwa-law":
        raise ValidationError("recorded engine/character differs from supported replay")
    final = steps[-1]["observation"] if steps else initial["observation"]
    observations = [initial["observation"], *(step["observation"] for step in steps)]
    # Death observations may zero stats/map; identify the final actual level
    # from its last live public observation, never from that zeroed screen.
    last_live = observations[-2] if steps and steps[-1]["terminated"] else final
    final_level = (
        last_live["player"]["dungeon_number"],
        last_live["player"]["dungeon_level"],
    )
    wanted = set()
    for selector in at:
        if selector == "end":
            wanted.add(final["step_index"])
        elif selector == "first-on-final-level":
            wanted.add(
                next(
                    obs["step_index"]
                    for obs in observations
                    if (obs["player"]["dungeon_number"], obs["player"]["dungeon_level"])
                    == final_level
                )
            )
        else:
            index = int(selector)
            if not 0 <= index <= final["step_index"]:
                raise ValueError(f"snapshot step {index} outside recorded episode")
            wanted.add(index)
    snapshots = []
    searches = []
    comparisons = 0
    with (
        tempfile.TemporaryDirectory(prefix="native-truth-replay-") as artifacts,
        NleEnvironment(
            ScenarioConfig(
                metadata["suite_seed"],
                Path(artifacts),
                metadata["max_episode_steps"],
                task,
            )
        ) as env,
    ):
        seeds = env.seed_set
        for key, actual in (
            ("core_seed", seeds.core),
            ("display_seed", seeds.display),
            ("level_seed", seeds.level),
        ):
            if metadata[key] != actual:
                raise ReplayMismatch(f"{key} derivation differs from recorded seed")
        if [action.to_json() for action in env.legal_actions] != initial[
            "legal_actions"
        ]:
            raise ReplayMismatch("recorded action table differs")
        raw = env.reset()
        projector = ObservationProjector()
        public = projector.project(raw, step_index=0).to_json()
        assert_observation(public, initial["observation"], 0)
        comparisons += 1
        with NativeTruth(env, raw) as truth:
            previous_level = None
            before_terminal = None
            before_terminal_map = None

            def capture() -> None:
                nonlocal previous_level
                player = public["player"]
                level = (player["dungeon_number"], player["dungeon_level"])
                entry = level != previous_level
                if public["step_index"] in wanted or (entry and every_level_entry):
                    snap = truth.snapshot(raw)
                    snap["step"] = public["step_index"]
                    snap["known_map"] = public["map"]["rows"]
                    if snap["terminal"] and before_terminal is not None:
                        if all(
                            snap["hero"][key] == before_terminal["hero"][key]
                            for key in ("dnum", "dlevel")
                        ):
                            for key in ("traps", "boulders", "peaceful_monsters"):
                                snap[key] = before_terminal[key]
                            snap["dynamic_status"] = "last_live_before_terminal"
                            snap["dynamic_step"] = public["step_index"] - 1
                        snap["known_map"] = before_terminal_map
                    snapshots.append(snap)
                previous_level = level

            capture()
            for record in steps:
                index = record["observation"]["step_index"]
                if (
                    record["action"]
                    != env.legal_actions[record["action"]["index"]].to_json()
                ):
                    raise ReplayMismatch(f"action mismatch at step {index}")
                if record["action"]["name"] == "Command.SEARCH":
                    searches.append({"step": index, **public["player"]})
                if record["terminated"] or record["truncated"]:
                    before_terminal = truth.snapshot(raw)
                    before_terminal_map = public["map"]["rows"]
                transition = env.step(record["action"]["index"])
                raw = transition.observation
                public = projector.project(
                    raw, step_index=transition.step_index
                ).to_json()
                assert_observation(public, record["observation"], index)
                comparisons += 1
                if (transition.terminated, transition.truncated) != (
                    record["terminated"],
                    record["truncated"],
                ):
                    raise ReplayMismatch(f"terminal state mismatch at step {index}")
                capture()
    for snapshot in snapshots:
        diagnosis = analyze(snapshot)
        shortest = diagnosis.get("shortest")
        secrets = (
            []
            if shortest is None
            else [
                (item["x"], item["y"])
                for item in shortest["blockers"]
                if "secret" in item["classes"]
            ]
        )
        hero = snapshot["hero"]
        relevant = [
            s
            for s in searches
            if (s["dungeon_number"], s["dungeon_level"])
            == (hero["dnum"], hero["dlevel"])
        ]
        diagnosis["search_actions_on_level"] = len(relevant)
        diagnosis["search_adjacent_to_route_secret"] = sum(
            any(max(abs(s["x"] - x), abs(s["y"] - y)) <= 1 for x, y in secrets)
            for s in relevant
        )
        diagnosis["route_secret_cells"] = [list(p) for p in secrets]
        snapshot["analysis"] = diagnosis
        snapshot["ascii"] = render(snapshot, snapshot["known_map"])
    return {
        "run_id": metadata["id"],
        "seed": metadata["suite_seed"],
        "recorded_actions": len(steps),
        "observation_comparisons": comparisons,
        "snapshots": snapshots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--run-id")
    selector.add_argument("--seed", type=int)
    parser.add_argument("--at", action="append", default=[])
    parser.add_argument("--every-level-entry", action="store_true")
    parser.add_argument("--output", type=Path, help="JSON file; stdout otherwise")
    args = parser.parse_args()
    result = replay(
        args.database,
        run_id=args.run_id,
        seed=args.seed,
        at=tuple(args.at or ["end"]),
        every_level_entry=args.every_level_entry,
    )
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n")
        for snapshot in result["snapshots"]:
            print(f"step {snapshot['step']}, hero {snapshot['hero']}")
            print(snapshot["ascii"])
            diagnosis = snapshot["analysis"]
            print(
                json.dumps(
                    {
                        key: diagnosis[key]
                        for key in (
                            "goal",
                            "minimal_blocker_sets",
                            "route_secret_cells",
                            "search_actions_on_level",
                            "search_adjacent_to_route_secret",
                        )
                    },
                    indent=2,
                )
            )
    else:
        print(encoded)


if __name__ == "__main__":
    main()
