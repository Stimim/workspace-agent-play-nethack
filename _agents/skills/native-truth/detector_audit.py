"""Audit Minetown-temple and Oracle detectors against native truth, offline.

Each run is replayed with full public-observation checks. The public detector
state is rebuilt exactly as the evaluator rebuilds it; native state is read
only to score that detector afterwards and never reaches policy or completion.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from native_truth import NativeTruth, ValidationError
from replay import ReplayMismatch, load_run, replay_environment, replay_step

from nethack_agent.conduct import attack_evidence
from nethack_agent.events import StepPayload
from nethack_agent.navigation import DungeonMemory
from nethack_agent.observation import ProjectedObservation
from nethack_agent.planner import leg_complete
from nethack_agent.replay import derive_action_record
from nethack_agent.targets import ORACLE_SPECIES, TEMPLE_MESSAGES, mines_candidate
from nethack_agent.tasks import TaskSpec
from nethack_agent.traversal import EnterMinetownTempleLeg, FindOracleLeg

TEMPLE_ROOM = 10  # mkroom.h TEMPLE
ROOMOFFSET = 3  # rm.h: roomno = rooms[] index + ROOMOFFSET


def native_minetown_success(snapshot: dict) -> bool:
    """Hero inside a temple room's interior, or on Orcish Town's altar.

    priest.c locates the hero with rm.roomno; a doorway is the room's edge,
    not its interior. Orcish Town (minetn-1) has no temple room at all.
    """
    if snapshot["special_level"] != "minetn":
        return False
    hero = snapshot["hero"]
    cell = snapshot["terrain"][hero["y"]][hero["x"]]
    rooms = {room["index"]: room for room in snapshot["rooms"]}
    if not any(room["original_type"] == TEMPLE_ROOM for room in rooms.values()):
        return cell["terrain"] == "ALTAR"
    room = rooms.get(cell["roomno"] - ROOMOFFSET)
    return (
        room is not None and room["type"] == TEMPLE_ROOM and cell["terrain"] != "DOOR"
    )


def native_oracle_success(snapshot: dict) -> bool:
    """A peaceful Oracle (live monster list) in the hero's 8 neighbours."""
    hero = snapshot["hero"]
    return any(
        monster["monster_index"] == ORACLE_SPECIES
        and max(abs(monster["x"] - hero["x"]), abs(monster["y"] - hero["y"])) == 1
        for monster in snapshot["peaceful_monsters"]
    )


def _audited(leg: object, player: dict) -> bool:
    level = (player["dungeon_number"], player["dungeon_level"])
    if isinstance(leg, EnterMinetownTempleLeg):
        return level[0] == 2
    return level[0] == 0 and 5 <= level[1] <= 9


def audit_run(database: Path, run_id: str) -> dict:
    metadata, initial, steps = load_run(database, run_id=run_id)
    task = TaskSpec.from_json(json.loads(metadata["task"]))
    (leg,) = task.objective.legs
    if not isinstance(leg, EnterMinetownTempleLeg | FindOracleLeg):
        raise ValueError(f"run {run_id} has no Minetown or Oracle leg")
    minetown = isinstance(leg, EnterMinetownTempleLeg)
    result = {
        "run_id": run_id,
        "seed": metadata["suite_seed"],
        "target": "minetown" if minetown else "oracle",
        "levels": {},
        "first_claim_step": None,
        "native_at_first_claim": None,
        "first_native_success_step": None,
        "native_unavailable": [],
    }
    if not any(_audited(leg, s["observation"]["player"]) for s in steps):
        return result
    memory = DungeonMemory()
    start = ProjectedObservation.from_json(initial["observation"])
    if start.player.dungeon_level >= 1:
        memory.observe(start)
    with (
        replay_environment(metadata, initial) as (env, raw, _, projector),
        NativeTruth(env, raw) as truth,
    ):
        for record in steps:
            payload = StepPayload.from_json(record)
            # Mirror evaluation.py's completion replay for target legs.
            if memory.levels:
                if memory.current.live_observation is not None:
                    name, _ = attack_evidence(
                        payload.action,
                        memory.current.live_observation,
                        memory.current,
                    )
                    memory.current.oracle_attacks += name == "Oracle"
                memory.current.record(
                    derive_action_record(
                        payload.selection, payload.action.name, memory.current
                    )
                )
                memory.current.pending_force_fight = (
                    payload.action.name == "Command.FIGHT"
                )
            raw, public = replay_step(env, projector, record)
            observation = payload.observation
            if observation.player.dungeon_level < 1:
                continue
            memory.observe(observation)
            claim = leg_complete(leg, memory)
            player = public["player"]
            # A terminal (died or truncated) snapshot has no live monster list.
            ending = record["terminated"] or record["truncated"]
            if not (claim or _audited(leg, player)) or ending:
                continue
            step = observation.step_index
            try:
                snapshot = truth.snapshot(raw)
            except ValidationError as error:
                result["native_unavailable"].append([step, str(error)])
                continue
            native = (
                native_minetown_success(snapshot)
                if minetown
                else native_oracle_success(snapshot)
            )
            key = f"{player['dungeon_number']}:{player['dungeon_level']}"
            level = result["levels"].setdefault(
                key,
                {
                    "depth": player["depth"],
                    "special_level": snapshot["special_level"],
                    "variant_candidates": snapshot["special_variant_candidates"],
                    "has_temple_flag": snapshot["level_flags"]["has_temple"],
                    "audited_steps": 0,
                    "town_identified": False,
                    "mines_candidate": False,
                    "native_success_steps": [],
                    "claim_steps": [],
                    "temple_message_steps": [],
                },
            )
            level["audited_steps"] += 1
            level["town_identified"] |= memory.current.town_identified
            level["mines_candidate"] |= mines_candidate(memory)
            if any(text in observation.message for text in TEMPLE_MESSAGES):
                level["temple_message_steps"].append(step)
            if native:
                level["native_success_steps"].append(step)
                if result["first_native_success_step"] is None:
                    result["first_native_success_step"] = step
            if claim:
                level["claim_steps"].append(step)
                if result["first_claim_step"] is None:
                    result["first_claim_step"] = step
                    result["native_at_first_claim"] = native
    return result


def classify(run: dict) -> str:
    if run["first_claim_step"] is not None:
        return "true_positive" if run["native_at_first_claim"] else "false_positive"
    return "false_negative" if run["first_native_success_step"] else "true_negative"


def summarize(runs: list[dict]) -> dict:
    outcomes = Counter(classify(run) for run in runs)
    mines = [
        level
        for run in runs
        if run["target"] == "minetown"
        for level in run["levels"].values()
    ]
    town = Counter(
        (level["special_level"] == "minetn", level["town_identified"])
        for level in mines
    )
    variants = Counter(
        "/".join(level["variant_candidates"]) or "none"
        for level in mines
        if level["special_level"] == "minetn"
    )
    silent_entries = sum(
        1
        for level in mines
        if level["native_success_steps"] and not level["temple_message_steps"]
    )
    return {
        "runs": len(runs),
        "success_claims": dict(outcomes),
        "town_identity": {
            f"native_minetn={native} detector_town={detected}": count
            for (native, detected), count in sorted(town.items())
        },
        "minetn_variant_candidates": dict(variants),
        "levels_with_native_success_but_no_temple_message": silent_entries,
        "native_unavailable_steps": sum(len(run["native_unavailable"]) for run in runs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="JSON file")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    with sqlite3.connect(f"{args.database.resolve().as_uri()}?mode=ro", uri=True) as db:
        run_ids = [row[0] for row in db.execute("SELECT id FROM runs ORDER BY rowid")]
    runs, failures = [], []
    with ProcessPoolExecutor(args.workers) as pool:
        futures = {pool.submit(audit_run, args.database, i): i for i in run_ids}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                runs.append(future.result())
                print(f"[{done}/{len(run_ids)}] {classify(runs[-1])}", flush=True)
            except (ReplayMismatch, ValidationError, ValueError) as error:
                failures.append({"run_id": futures[future], "error": str(error)})
                print(f"[{done}/{len(run_ids)}] FAILED {error}", flush=True)
    runs.sort(key=lambda run: run["seed"])
    report = {"summary": summarize(runs), "failures": failures, "runs": runs}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
