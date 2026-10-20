"""Build the compact 0055 per-death records from the diagnosis outputs.

Usage: build_record.py ANALYSIS_DIR OUT_DIR
ANALYSIS_DIR holds baseline-deaths.json, cand-deaths.json and lastsec.json
(written by deaths.py and lastsec.py); report paths are fixed below.
"""

import glob
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from summarize import klass  # noqa: E402

E = Path(os.path.expanduser("~/nethack-evidence"))
BASELINE_ARMS = ("0052-base-mt-reg", "0052-base-or-reg", "0052-base-d5-reg", "0052-base-mt-fresh", "0052-base-or-fresh")
# Baseline outcome of each candidate case/seed: the target suite it reruns.
CAND_BASELINE = {
    "oracle-diag": E / "0052/0052-base-or-reg",
    "minetown-diag": E / "0052/0052-base-mt-reg",
}
FRESH_537 = E / "0051/run2/base-or-fresh"
FIELDS = (
    "arm", "case", "seed", "cause", "hunger_at_death", "level", "depth", "xl", "maxhp", "ac",
    "death_turn", "fight_turns", "hp_entry", "frac_entry", "pray_ok_entry", "prayed_in_fight",
    "turns_until_prayer_entry", "up_dist", "max_nearby_speed", "attackers", "unseen_attack_msgs",
    "blind", "food_items", "last_live_hp", "last_live_max", "last_live_critical", "class",
)
COMMON = {
    "base_commit": "22d0a5f",
    "policy_version": "hierarchical-survival-hp-prayer-burden-look-ration-v1",
    "model": "scripted-development",
    "diagnosis_only": True,
    "class_definition": "summarize.py klass(): A hunger Weak+/starved; B >=3 unseen-attack msgs or blind; "
    "C entry HP <50%; D healthy entry, fight <=10 turns; E healthy entry, fight >10 turns",
    "derived_fields": {
        "hunger_at_death": "deaths.py `hunger`",
        "max_nearby_speed": "max of deaths.py `nearby_speeds` (hostiles within 2 cells during the fight), 0 if none",
        "last_live_*": "lastsec.py; null for hunger (class A) deaths, which lastsec.py skips",
    },
    "regenerate": [
        "cd <checkout>  # deaths.py imports nethack_agent, so run it through the repo's uv project",
        "uv run --project nethack-agent python docs/notes/evidence/0055/scripts/deaths.py OUT/baseline-deaths.json "
        + " ".join(f"~/nethack-evidence/0052/{a}" for a in BASELINE_ARMS),
        "uv run --project nethack-agent python docs/notes/evidence/0055/scripts/deaths.py OUT/cand-deaths.json "
        "~/nethack-evidence/0055-death-analysis/cand",
        "python3 -I docs/notes/evidence/0055/scripts/lastsec.py OUT/baseline-deaths.json OUT/lastsec.json",
        "python3 -I docs/notes/evidence/0055/scripts/summarize.py OUT/baseline-deaths.json",
        "python3 -I docs/notes/evidence/0055/scripts/build_record.py OUT docs/notes/evidence/0055",
        "python3 -I docs/notes/evidence/0055/scripts/verify.py docs/notes/evidence/0055",
        "python3 -I docs/notes/evidence/0055/scripts/prayers.py docs/notes/evidence/0055/baseline-deaths.json",
    ],
    "script_changes": "deaths.py, lastsec.py, summarize.py copied unchanged from ~/nethack-evidence/0055-death-analysis; "
    "imports resolve as-is (summarize via the script directory, nethack_agent via uv). Regenerated outputs were "
    "byte-identical to the originals on 2026-10-20.",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report(arm: Path) -> Path:
    return Path(glob.glob(str(arm / "reports" / "*.json"))[0])


def inputs(paths) -> list[dict]:
    return [{"path": str(p).replace(str(E), "~/nethack-evidence"), "sha256": sha(p)} for p in paths]


def row(r: dict, last: dict | None) -> dict:
    out = dict(r, hunger_at_death=r["hunger"], max_nearby_speed=max(r["nearby_speeds"].values() or [0]))
    out.update(
        last_live_hp=None if last is None else last["last_live_hp"],
        last_live_max=None if last is None else last["last_live_max"],
        last_live_critical=None if last is None else last["last_live_critical"],
        **{"class": klass(r)[0]},
    )
    return {k: out[k] for k in FIELDS}


def write(path: Path, header: dict, rows: list[dict]) -> None:
    rows.sort(key=lambda r: (r["arm"], r["case"], r["seed"]))
    body = ",\n".join(json.dumps(r, separators=(",", ":")) for r in rows)
    path.write_text('{"header":' + json.dumps(header, indent=1) + ',\n"rows":[\n' + body + "\n]}\n")


def main():
    src, out = Path(sys.argv[1]).expanduser(), Path(sys.argv[2])
    base = json.load(open(src / "baseline-deaths.json"))
    last = {(o["arm"], o["seed"]): o for o in json.load(open(src / "lastsec.json"))}
    assert len(last) == len(json.load(open(src / "lastsec.json")))  # (arm, seed) is unique
    rows = [row(r, last.get((r["arm"], r["seed"]))) for r in base]
    assert sum(r["last_live_hp"] is not None for r in rows) == len(last)
    base_reports = [report(E / "0052" / a) for a in BASELINE_ARMS]
    write(out / "baseline-deaths.json", {
        "record": "0055 death analysis: 0052 baseline arms, one row per death",
        "suites": "minetown/oracle-regression-v2, descend-d5 regression arm, minetown/oracle-fresh-v1 (0052 baseline arms)",
        **COMMON,
        "inputs": inputs([src / "baseline-deaths.json", src / "lastsec.json", *base_reports]),
    }, rows)

    cand = json.load(open(src / "cand-deaths.json"))
    outcomes = {}
    for case, arm in CAND_BASELINE.items():
        rep = json.load(open(report(arm)))
        for c in rep["case_results"]:
            for e in c["results"]:
                outcomes.setdefault((case, e["seed"]), []).append(e["outcome"])
    for c in json.load(open(report(FRESH_537)))["case_results"]:
        for e in c["results"]:
            if e["seed"] == 537:
                outcomes[("oracle-diag", 537)] = [e["outcome"]]
    crows = []
    for r in cand:
        found = outcomes[(r["case"], r["seed"])]
        assert len(found) == 1, (r["case"], r["seed"], found)
        crows.append(dict(row(r, None), baseline_outcome=found[0]))
    cand_report = report(E / "0055-death-analysis/cand")
    write(out / "candidate-0054-deaths.json", {
        "record": "0055 death analysis: unqualified 0054 stall-budget candidate rerun (T=400, C=20), one row per death",
        "suite": "death-diagnosis-0054-candidate (~/nethack-evidence/0055-death-analysis/suite.json), not qualification evidence",
        "candidate_branch": "rule-0054-no-progress-budget",
        "baseline_outcome": "oracle-diag seeds from 0052-base-or-reg, minetown-diag from 0052-base-mt-reg, "
        "537 from 0051 run2 base-or-fresh",
        **COMMON,
        "inputs": inputs([src / "cand-deaths.json", E / "0055-death-analysis/suite.json", cand_report,
                          report(CAND_BASELINE["oracle-diag"]), report(CAND_BASELINE["minetown-diag"]),
                          report(FRESH_537)]),
    }, crows)


if __name__ == "__main__":
    main()
