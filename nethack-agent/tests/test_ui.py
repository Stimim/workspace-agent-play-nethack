import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nethack_agent.api import UI_CONTENT_SECURITY_POLICY, create_app
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager
from nethack_agent.tasks import STAIRCASE_TASK
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    ExploreLevelGoal,
    LevelKey,
    StairConnection,
    StairDirection,
    StairTarget,
    TraverseStairsGoal,
)

UI_DIR = Path(__file__).parents[1] / "src" / "nethack_agent" / "ui"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
NODE = shutil.which("node")


def _run_renderer_module(script: str, *, vm_modules: bool = False) -> dict[str, object]:
    assert NODE is not None
    completed = subprocess.run(
        [
            NODE,
            *(["--experimental-vm-modules"] if vm_modules else []),
            "--input-type=module",
            "--eval",
            script,
        ],
        cwd=UI_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RunManager(tmp_path, OllamaConfig(model="test"))))


def _assert_ui_headers(response, suffix: str) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPES[suffix]
    assert response.headers["content-security-policy"] == UI_CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"


def test_historical_steps_are_self_contained_after_service_restart(
    tmp_path: Path,
) -> None:
    manager = RunManager(
        tmp_path,
        OllamaConfig(model="scripted-development"),
        model_factory=lambda _: ScriptedDevelopmentModel(),
    )
    observations = []
    with TestClient(create_app(manager, STAIRCASE_TASK)) as running:
        created = running.post("/api/runs", json={"seed": 6, "max_episode_steps": 20})
        assert created.status_code == 201
        run_id = created.json()["run"]["id"]
        for _ in range(3):
            response = running.post(f"/api/runs/{run_id}/step")
            assert response.status_code == 200
            observations.append(response.json()["coordinator"]["observation"])
        assert running.post(f"/api/runs/{run_id}/stop").status_code == 200
        events = running.get(f"/api/runs/{run_id}/events").json()["events"]
        steps = [event for event in events if event["kind"] == "step"]

    with TestClient(
        create_app(RunManager(tmp_path, OllamaConfig(model="test")))
    ) as restarted:
        assert restarted.get(f"/api/runs/{run_id}").json()["coordinator"] is None
        for step, observation in zip(steps, observations, strict=True):
            # A trailing event page need not include the initial map or any
            # preceding delta: each selectable step must stand on its own.
            page = restarted.get(
                f"/api/runs/{run_id}/events",
                params={"after": step["sequence"] - 1, "limit": 1},
            )
            assert page.status_code == 200
            stored = page.json()["events"][0]
            assert stored == step
            assert stored["payload"]["observation"] == observation
            map_view = observation["map"]
            assert len(map_view["rows"]) == 21
            assert all(len(row) == 79 for row in map_view["rows"])
            assert len(map_view["color_rows"]) == 21
            assert all(len(row) == 158 for row in map_view["color_rows"])
            assert observation["inventory"]
            assert stored["payload"]["selection"]["intent"] is not None
        assert observations[0]["player"] != observations[-1]["player"]


def test_csp_allows_only_same_origin_resources_and_no_inline_script() -> None:
    directives = dict(
        directive.strip().split(" ", 1)
        for directive in UI_CONTENT_SECURITY_POLICY.split(";")
    )
    assert directives["default-src"] == "'none'"
    for name in ("script-src", "style-src", "connect-src", "img-src"):
        assert directives[name] == "'self'"
    assert "unsafe" not in UI_CONTENT_SECURITY_POLICY
    assert directives["frame-ancestors"] == "'none'"


def test_index_and_every_referenced_module_are_served_with_csp(
    api: TestClient,
) -> None:
    index = api.get("/")
    _assert_ui_headers(index, ".html")

    referenced = re.findall(r'(?:src|href)="ui/([^"]+)"', index.text)
    assert {"app.js", "app.css"} <= set(referenced)
    pending = list(referenced)
    served: set[str] = set()
    while pending:
        name = pending.pop()
        if name in served:
            continue
        response = api.get(f"/ui/{name}")
        _assert_ui_headers(response, Path(name).suffix)
        served.add(name)
        if name.endswith(".js"):
            pending.extend(re.findall(r'from "\./([^"]+)"', response.text))

    shipped = {path.name for path in UI_DIR.iterdir() if path.name != "index.html"}
    assert served == shipped


@pytest.mark.parametrize(
    "name", ["missing.js", "..%2Fapi.py", "api.py", "%2E%2E%2F__init__.py"]
)
def test_unlisted_assets_are_not_served(api: TestClient, name: str) -> None:
    assert api.get(f"/ui/{name}").status_code == 404


def test_page_is_self_contained_and_never_parses_data_as_html() -> None:
    external = re.compile(r"\b(?:https?|wss?|ftp)://|=[\"']//|@import|url\(")
    for path in UI_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not external.search(text), path.name
        if path.suffix == ".js":
            assert not re.search(
                r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(",
                text,
            ), path.name
    index = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", index)
    assert not re.search(r"\s(?:on[a-z]+|style)=", index)


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_player_stats_use_semantic_grouped_cells_with_full_labels() -> None:
    result = _run_renderer_module(
        """
        class Node {
          constructor(tag = "") {
            this.tag = tag; this.children = []; this.className = "";
            this.textContent = ""; this.attributes = {};
          }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) {
            this.children = nodes.flatMap(
              (node) => node.fragment ? node.children : [node],
            );
          }
          querySelectorAll() { return []; }
          setAttribute(name, value) { this.attributes[name] = value; }
        }
        globalThis.document = {
          activeElement: null,
          createDocumentFragment: () => Object.assign(new Node(), { fragment: true }),
          createElement: (tag) => new Node(tag),
        };
        const { renderStats } = await import("./render.js");
        const list = new Node("dl");
        renderStats(list, {
          hit_points: 12, max_hit_points: 12, energy: 3, max_energy: 3,
          armor_class: 4, experience_level: 1, experience_points: 0,
          depth: 1, dungeon_number: 0, dungeon_level: 1, x: 40, y: 10,
          turn: 5, gold: 0, score: 0, hunger: 1, encumbrance: 0,
          alignment: 1, strength_125: 66, dexterity: 15, constitution: 18,
          intelligence: 8, wisdom: 10, charisma: 9, conditions: [],
        });
        const text = (node) =>
          node.children[0]?.children[0]?.textContent ?? node.textContent;
        console.log(JSON.stringify({
          listTag: list.tag,
          cells: list.children.map((cell) => {
            const wrapper = cell.children[0].children[0];
            return {
              className: cell.className,
              tags: cell.children.map((node) => node.tag),
              label: text(cell.children[0]),
              value: text(cell.children[1]),
              accessibleTooltip:
                wrapper.children[0].tabIndex === 0
                && wrapper.children[0].attributes["aria-describedby"]
                  === wrapper.children[1].id
                && wrapper.children[1].attributes.role === "tooltip",
            };
          }),
        }));
        """
    )

    assert result["listTag"] == "dl"
    cells = result["cells"]
    assert isinstance(cells, list)
    assert [cell["label"] for cell in cells] == [
        "HP",
        "Pw",
        "AC",
        "Level",
        "Depth",
        "Position",
        "Turn",
        "Gold",
        "Score",
        "Hunger",
        "Encumbrance",
        "Alignment",
        "Strength",
        "Dexterity",
        "Constitution",
        "Intelligence",
        "Wisdom",
        "Charisma",
        "Conditions",
    ]
    assert [cell["value"] for cell in cells] == [
        "12 / 12",
        "3 / 3",
        "4",
        "XL 1 (0 xp)",
        "1 (dungeon 0, level 1)",
        "x 40, y 10",
        "5",
        "0",
        "0",
        "not hungry (1)",
        "unencumbered (0)",
        "lawful",
        "18/48",
        "15",
        "18",
        "8",
        "10",
        "9",
        "none",
    ]
    assert all(cell["tags"] == ["dt", "dd"] for cell in cells)
    assert all(cell["accessibleTooltip"] for cell in cells)
    assert [cell["className"] for cell in cells[:-1]] == ["stat-cell"] * 18
    assert cells[-1]["className"] == "stat-cell stat-cell-wide"


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_inventory_renders_all_typed_buc_states_with_text_and_tooltips() -> None:
    result = _run_renderer_module(
        """
        class Node {
          constructor(tag = "") {
            this.tag = tag; this.children = []; this.className = "";
            this.textContent = ""; this.attributes = {};
          }
          get childNodes() { return this.children; }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) {
            this.children = nodes.flatMap(
              (node) => node.fragment ? node.children : [node],
            );
          }
          setAttribute(name, value) { this.attributes[name] = value; }
        }
        globalThis.document = {
          createDocumentFragment: () => Object.assign(new Node(), { fragment: true }),
          createElement: (tag) => new Node(tag),
          createTextNode: (text) =>
            Object.assign(new Node("#text"), { textContent: text }),
        };
        const { renderInventory } = await import("./render.js");
        const list = new Node("ul");
        renderInventory(list, [
          { letter: "a", description: "a blessed potion", buc: "blessed" },
          { letter: "b", description: "an uncursed ration", buc: "uncursed" },
          { letter: "c", description: "a cursed scroll", buc: "cursed" },
          { letter: "d", description: "a +1 sword", buc: "unknown" },
        ]);
        console.log(JSON.stringify(list.children.map((entry) => {
          const wrapper = entry.children[0];
          return {
            entryClass: entry.className,
            markerClass: wrapper.className,
            marker: wrapper.children[0].textContent,
            describedBy: wrapper.children[0].attributes["aria-describedby"],
            tooltipRole: wrapper.children[1].attributes.role,
            tooltip: wrapper.children[1].textContent,
            item: entry.children[1].textContent,
          };
        })));
        """
    )

    assert [row["marker"] for row in result] == ["[B]", "[U]", "[C]", "[?]"]
    assert [row["entryClass"] for row in result] == [
        "inventory-item buc-blessed",
        "inventory-item buc-uncursed",
        "inventory-item buc-cursed",
        "inventory-item buc-unknown",
    ]
    assert all(
        row["markerClass"].startswith("tooltip buc-marker buc-") for row in result
    )
    assert all(row["describedBy"] for row in result)
    assert all(row["tooltipRole"] == "tooltip" for row in result)
    assert all(row["tooltip"] for row in result)
    assert [row["item"] for row in result] == [
        " a - a blessed potion",
        " b - an uncursed ration",
        " c - a cursed scroll",
        " d - a +1 sword",
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_tools_include_only_event_evidenced_deterministic_execution() -> None:
    result = _run_renderer_module(
        """
        const { deterministicExecution } = await import("./render.js");
        const event = {
          kind: "step",
          sequence: 7,
          payload: {
            selection: {
              source: "deterministic_skill",
              goal: {
                kind: "stand_on_stairs",
                target: { direction: "down", connection: "any", dungeon_number: null },
              },
              skill: "explore_level",
              skill_selection: "arbiter",
              rationale: "Walk to the nearest frontier.",
            },
            action: { index: 3, command: 108, name: "CompassDirection.E" },
            reward: 0,
            outcome: null,
          },
        };
        const skill = deterministicExecution(event);
        event.payload.selection.source = "deterministic_prompt";
        const prompt = deterministicExecution(event);
        event.payload.selection.source = "model_fallback";
        const model = deterministicExecution(event);
        const lifecycle = deterministicExecution({
          kind: "run_resumed",
          sequence: 8,
          payload: {},
        });
        event.payload.selection.source = "deterministic_skill";
        delete event.payload.action;
        const missingActionEvidence = deterministicExecution(event);
        console.log(JSON.stringify({
          skillSource: skill?.source,
          skillAction: skill?.action.name,
          promptSource: prompt?.source,
          model,
          lifecycle,
          missingActionEvidence,
        }));
        """
    )

    assert result == {
        "skillSource": "deterministic_skill",
        "skillAction": "CompassDirection.E",
        "promptSource": "deterministic_prompt",
        "model": None,
        "lifecycle": None,
        "missingActionEvidence": None,
    }


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_verbose_view_exposes_trace_text_but_not_raw_model_responses() -> None:
    result = _run_renderer_module(
        """
        const { verboseDetails } = await import("./render.js");
        const values = verboseDetails({
          kind: "agent_error",
          sequence: 9,
          payload: {
            error: "decision failed",
            decision_failure: {
              message: "invalid model response",
              attempts: [{
                error: "missing action_index",
                raw_response: "DO NOT DISPLAY RAW MODEL TEXT",
              }],
            },
          },
        });
        console.log(JSON.stringify(values));
        """
    )

    assert result == [
        {"label": "Agent error", "value": "decision failed"},
        {"label": "Decision failure", "value": "invalid model response"},
        {"label": "Attempt 1", "value": "missing action_index"},
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_messages_view_lists_every_nonblank_game_message() -> None:
    result = _run_renderer_module(
        """
        globalThis.document = {
          createElement: (tag) => ({
            tag, className: "", textContent: "", children: [],
            append(...nodes) { this.children.push(...nodes); },
          }),
        };
        const { gameMessage, renderMessageEntry, verboseDetails } =
          await import("./render.js");
        const withMessage = (kind, sequence, step, message) => ({
          kind, sequence, payload: { observation: { step_index: step, message } },
        });
        const events = [
          withMessage("run_started", 1, 0, "Hello Agent, welcome to NetHack!"),
          withMessage("step", 2, 1, "You kill the newt!"),
          withMessage("step", 3, 2, "You kill the newt!"),
          withMessage("step", 4, 3, "   "),
          withMessage("step", 5, 4, ""),
          withMessage("step", 6, 5, "  <b>It hits!</b>  "),
          { kind: "step", sequence: 7, payload: {} },
          { kind: "agent_error", sequence: 8, payload: { error: "boom" } },
        ];
        const messages = events.map(gameMessage);
        const row = renderMessageEntry(messages[5]);
        console.log(JSON.stringify({
          messages,
          row: [row.tag, row.className,
                ...row.children.map((c) => [c.className, c.textContent])],
          verboseKeepsMessage: verboseDetails(events[1])[0],
        }));
        """
    )

    assert result["messages"] == [
        {"sequence": 1, "step": 0, "text": "Hello Agent, welcome to NetHack!"},
        {"sequence": 2, "step": 1, "text": "You kill the newt!"},
        {"sequence": 3, "step": 2, "text": "You kill the newt!"},
        None,
        None,
        {"sequence": 6, "step": 5, "text": "<b>It hits!</b>"},
        None,
        None,
    ]
    assert result["row"] == [
        "li",
        "agent-row message-row",
        ["message-meta", "step 5 · #6"],
        ["message-text", "<b>It hits!</b>"],
    ]
    assert result["verboseKeepsMessage"] == {
        "label": "Game message",
        "value": "You kill the newt!",
    }


# A minimal DOM for `renderMap`: element children and class/text properties.
_MAP_DOM = """
class Node {
  constructor() {
    this.children = [];
    this.className = "";
    this.textContent = "";
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) {
    this.children = nodes.flatMap(
      (node) => node.fragment ? node.children : [node],
    );
  }
}
globalThis.document = {
  createDocumentFragment: () => Object.assign(new Node(), { fragment: true }),
  createElement: () => new Node(),
  createTextNode: (text) => ({ className: "", textContent: text }),
};
const { renderMap } = await import("./render.js");
const spans = (observation, intent, showPath) => {
  const pre = new Node();
  renderMap(pre, observation, intent, showPath);
  return pre.children.map((node) => [node.className, node.textContent]);
};
"""


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_map_highlights_only_explicit_pet_evidence() -> None:
    result = _run_renderer_module(
        _MAP_DOM
        + """
        const map = (petRows) => spans({
          map: { rows: ["@dd"], color_rows: ["070202"], pet_rows: petRows },
          player: { x: 0, y: 0 },
        });
        console.log(JSON.stringify({ known: map(["000100"]), unknown: map(null) }));
        """
    )

    # The same-character, same-color wild animal stays unhighlighted.
    assert result["known"] == [["player", "@"], ["pet c2", "d"], ["c2", "d"]]
    assert result["unknown"] == [["player", "@"], ["c2", "dd"]]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_map_marks_destination_and_attack_target_with_precedence() -> None:
    result = _run_renderer_module(
        _MAP_DOM
        + """
        const observation = {
          map: {
            rows: ["@r.f.", "....>"],
            color_rows: ["0703070f07", "0707070707"],
            pet_rows: ["0000000100", "0000000000"],
          },
          player: { x: 0, y: 0 },
        };
        const at = (x, y) => ({ x, y });
        console.log(JSON.stringify({
          both: spans(observation, {
            destination: { kind: "downstairs", ...at(4, 1) },
            attack_target: at(1, 0),
          }),
          onPet: spans(observation, {
            destination: { kind: "frontier", ...at(3, 0) },
            attack_target: null,
          }),
          sameCell: spans(observation, {
            destination: { kind: "downstairs", ...at(1, 0) },
            attack_target: at(1, 0),
          }),
          onPlayer: spans(observation, {
            destination: { kind: "search_spot", ...at(0, 0) },
            attack_target: null,
          }),
          none: spans(observation, null),
        }));
        """
    )

    newline = ["", "\n"]
    rest_of_row = [["c7", "."], ["pet c15", "f"], ["c7", "."], newline]
    # Distinct classes keep each cell's NetHack color.
    assert result["both"] == [
        ["player", "@"],
        ["attack-target c3", "r"],
        *rest_of_row,
        ["c7", "...."],
        ["destination c7", ">"],
    ]
    # A pet on the destination keeps its fill under the destination box.
    assert result["onPet"][:4] == [
        ["player", "@"],
        ["c3", "r"],
        ["c7", "."],
        ["destination pet c15", "f"],
    ]
    # The attack-target box wins over a destination box on the same cell.
    assert result["sameCell"][1] == ["attack-target c3", "r"]
    # The player highlight wins; a destination under the hero is not boxed.
    assert result["onPlayer"] == result["none"]
    assert not any(
        "destination" in key or "attack-target" in key for key, _ in result["none"]
    )


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_map_tints_the_recorded_path_beneath_intent_boxes_unless_hidden() -> None:
    result = _run_renderer_module(
        _MAP_DOM
        + """
        const observation = {
          map: {
            rows: ["@.f..", ".r..>"],
            color_rows: ["07070f0707", "0703070707"],
            pet_rows: ["0000010000", "0000000000"],
          },
          player: { x: 0, y: 0 },
        };
        const at = (x, y) => ({ x, y });
        const destination = { kind: "frontier", ...at(4, 1) };
        const route = [at(0, 0), at(1, 0), at(2, 0), at(3, 1), at(4, 1)];
        const attack = {
          destination,
          attack_target: at(1, 0),
          path: [at(1, 0), at(2, 0), at(3, 1), at(4, 1)],
        };
        const walk = { destination, attack_target: null, path: route };
        const pathless = { destination, attack_target: null };
        console.log(JSON.stringify({
          walk: spans(observation, walk),
          attack: spans(observation, attack),
          hidden: spans(observation, walk, false),
          nullPath: spans(observation, { ...pathless, path: null }),
          missingPath: spans(observation, pathless),
        }));
        """
    )

    newline = ["", "\n"]
    # The hero hides the route cell it stands on; the pet fill combines with
    # the tint; the destination box wins on the route's last cell.
    assert result["walk"] == [
        ["player", "@"],
        ["path c7", "."],
        ["path pet c15", "f"],
        ["c7", ".."],
        newline,
        ["c7", "."],
        ["c3", "r"],
        ["c7", "."],
        ["path c7", "."],
        ["destination c7", ">"],
    ]
    # The attack-target box wins over the tint on the route's first cell.
    assert result["attack"][1] == ["attack-target c7", "."]
    assert result["attack"][2] == ["path pet c15", "f"]
    # Hiding the path keeps every other mark; an unrecorded path draws none.
    assert result["hidden"] == result["nullPath"] == result["missingPath"]
    assert not any("path" in key for key, _ in result["hidden"])
    assert ["destination c7", ">"] in result["hidden"]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_decision_path_fact_reports_only_a_recorded_route() -> None:
    result = _run_renderer_module(
        """
        const { pathFact } = await import("./render.js");
        const destination = { kind: "downstairs", x: 19, y: 14 };
        const path = [11, 12, 13, 14].map((y) => ({ x: 19, y }));
        console.log(JSON.stringify({
          route: pathFact({ destination, attack_target: null, path }),
          single: pathFact({ destination, attack_target: null, path: path.slice(3) }),
          pathless: pathFact({ destination, attack_target: null }),
          nullPath: pathFact({ destination, attack_target: null, path: null }),
          noIntent: pathFact(null),
        }));
        """
    )

    assert result["route"]["text"] == "4 steps: (19, 11) to (19, 14)"
    assert "(19, 11)" in result["route"]["help"]
    assert result["single"]["text"] == "1 step: (19, 14)"
    # Intents recorded before routes existed show no route, even with a
    # destination that a route could have been guessed toward.
    assert result["pathless"] == result["nullPath"] == result["noIntent"]
    assert result["pathless"]["text"] == "none recorded"


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_map_intent_comes_only_from_the_step_that_produced_the_observation() -> None:
    result = _run_renderer_module(
        """
        const { intentFact, observationIntent } = await import("./render.js");
        const intent = {
          destination: { kind: "frontier", x: 57, y: 11 },
          attack_target: { x: 56, y: 10 },
          path: [{ x: 56, y: 10 }, { x: 57, y: 11 }],
        };
        const step = (selection) => ({
          kind: "step",
          payload: { selection, observation: { step_index: 4 } },
        });
        const current = step({ source: "deterministic_skill", intent });
        const legacy = step({ source: "deterministic_skill" });
        console.log(JSON.stringify({
          matching: observationIntent({ step_index: 4 }, current),
          newerObservation: observationIntent({ step_index: 5 }, current),
          noStep: observationIntent({ step_index: 0 }, null),
          legacy: observationIntent({ step_index: 4 }, legacy),
          fact: intentFact(intent),
          legacyFact: intentFact(undefined),
          nullFact: intentFact(null),
        }));
        """
    )

    assert result["matching"] == {
        "destination": {"kind": "frontier", "x": 57, "y": 11},
        "attack_target": {"x": 56, "y": 10},
        "path": [{"x": 56, "y": 10}, {"x": 57, "y": 11}],
    }
    assert result["newerObservation"] is None
    assert result["noStep"] is None
    # A step stored before intents existed has none; nothing is inferred.
    assert result["legacy"] is None
    assert result["legacyFact"] == result["nullFact"]
    assert "(" not in result["legacyFact"]["text"]
    assert "(57, 11)" in result["fact"]["text"]
    assert "(56, 10)" in result["fact"]["text"]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_map_draws_an_intent_only_on_the_level_it_was_recorded_for() -> None:
    result = _run_renderer_module(
        """
        const { intentFact, observationIntent } = await import("./render.js");
        const intent = {
          destination: {
            kind: "downstairs",
            x: 5,
            y: 3,
            stair: { kind: "branch", dungeon_number: 2, evidence: "elimination" },
          },
          attack_target: null,
          path: null,
          level: { dungeon_number: 0, dungeon_level: 2 },
        };
        const at = (dungeon_number, dungeon_level) => ({
          step_index: 9,
          player: { x: 5, y: 3, dungeon_number, dungeon_level },
        });
        const step = {
          kind: "step",
          payload: { selection: { intent }, observation: { step_index: 9 } },
        };
        const unleveled = {
          kind: "step",
          payload: {
            selection: { intent: { ...intent, level: null } },
            observation: { step_index: 9 },
          },
        };
        console.log(JSON.stringify({
          sameLevel: observationIntent(at(0, 2), step),
          afterDescending: observationIntent(at(2, 1), step),
          legacyLevel: observationIntent(at(2, 1), unleveled),
          fact: intentFact(intent),
        }));
        """
    )

    assert result["sameLevel"]["destination"]["kind"] == "downstairs"  # type: ignore[index]
    # The step that used the staircase recorded the previous level's cells.
    assert result["afterDescending"] is None
    # Intents recorded before levels were are drawn as before.
    assert result["legacyLevel"] is not None
    fact = result["fact"]
    assert fact["text"] == (  # type: ignore[index]
        "destination: downstairs (5, 3) [branch to 2 by elimination]; level (0, 2)"
    )
    assert "identity" in fact["help"]  # type: ignore[index]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_goal_text_is_the_token_the_model_is_offered() -> None:
    goals = [
        STAND_ON_DOWNSTAIRS,
        TraverseStairsGoal(StairTarget(StairDirection.UP, StairConnection.MAIN, None)),
        TraverseStairsGoal(StairTarget(StairDirection.DOWN, StairConnection.BRANCH, 2)),
    ]
    result = _run_renderer_module(
        f"""
        const {{ goalFact }} = await import("./render.js");
        const goals = {json.dumps([goal.to_json() for goal in goals])};
        console.log(JSON.stringify({{
          facts: goals.map(goalFact),
          missing: goalFact(null),
        }}));
        """
    )

    facts = result["facts"]
    assert [fact["text"] for fact in facts] == [goal.token for goal in goals]  # type: ignore[index]
    assert "without using it" in facts[0]["help"]  # type: ignore[index]
    assert "upstairs (<)" in facts[1]["help"]  # type: ignore[index]
    assert "(dungeon 2)" in facts[2]["help"]  # type: ignore[index]
    assert result["missing"] == {"text": None}


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_explore_level_goal_text_is_its_token_and_names_the_level() -> None:
    goal = ExploreLevelGoal(LevelKey(0, 2))
    stair_goals = [
        STAND_ON_DOWNSTAIRS,
        TraverseStairsGoal(StairTarget(StairDirection.DOWN, StairConnection.BRANCH, 2)),
    ]
    result = _run_renderer_module(
        f"""
        const {{ goalFact }} = await import("./render.js");
        console.log(JSON.stringify({{
          explore: goalFact({json.dumps(goal.to_json())}),
          stairs: {json.dumps([g.to_json() for g in stair_goals])}.map(goalFact),
        }}));
        """
    )

    assert result["explore"] == {
        "text": "explore_level:0:2",
        "help": (
            "Goal explore_level: explore this level until deterministic exploration "
            "finds no unexplored space, locked door to kick, or search spot left. "
            "Level: dungeon 0, level 2."
        ),
    }
    assert result["explore"]["text"] == goal.token  # type: ignore[index]
    # Stair goals keep their exact text and tooltip.
    assert result["stairs"] == [
        {
            "text": "stand_on_stairs:down:any",
            "help": (
                "Goal stand_on_stairs: stand on a remembered staircase that matches "
                "the target without using it. Target: downstairs (>), any staircase "
                "of that direction."
            ),
        },
        {
            "text": "traverse_stairs:down:branch:2",
            "help": (
                "Goal traverse_stairs: reach a remembered staircase that matches the "
                "target and use it to change level. Target: downstairs (>), the "
                "staircase into another dungeon (dungeon 2)."
            ),
        },
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_step_decision_shows_exhausted_level_only_when_recorded() -> None:
    result = _run_renderer_module(
        """
        class Node {
          constructor(tag = "") {
            this.tag = tag; this.children = []; this.className = "";
            this.textContent = ""; this.attributes = {};
          }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) {
            this.children = nodes.flatMap(
              (node) => node.fragment ? node.children : [node],
            );
          }
          querySelectorAll() { return []; }
          setAttribute(name, value) { this.attributes[name] = value; }
        }
        globalThis.document = {
          activeElement: null,
          createDocumentFragment: () => Object.assign(new Node(), { fragment: true }),
          createElement: (tag) => new Node(tag),
        };
        const { renderDecision } = await import("./render.js");
        const selection = {
          source: "deterministic_skill",
          goal: {
            kind: "explore_level",
            level: { dungeon_number: 0, dungeon_level: 2 },
          },
          skill: "explore_level",
          skill_selection: "arbiter",
          rationale: "explore",
          intent: null,
          stuck_reason: null,
        };
        const facts = (extra) => {
          const list = new Node("dl");
          renderDecision(list, new Node("tbody"), {
            kind: "step",
            payload: {
              selection: { ...selection, ...extra },
              action: { name: "search", index: 3, command: 115 },
              reward: 0, terminated: false, truncated: false, outcome: null,
              observation: { step_index: 7 },
            },
          }, {});
          const pairs = [];
          for (let i = 0; i < list.children.length; i += 2) {
            const [term, description] = [list.children[i], list.children[i + 1]];
            const wrapper = term.children[0];
            pairs.push({
              label: wrapper?.children[0]?.textContent ?? term.textContent,
              help: wrapper?.children[1]?.textContent ?? null,
              value: description.children[0]?.children[0]?.textContent
                ?? description.textContent,
            });
          }
          return pairs;
        };
        console.log(JSON.stringify({
          exhausted: facts({
            exhausted_level: { dungeon_number: 0, dungeon_level: 2 },
          }),
          nullMarker: facts({ exhausted_level: null }),
          legacy: facts({}),
        }));
        """
    )

    exhausted = [fact for fact in result["exhausted"] if fact["label"] == "Exhausted"]  # type: ignore[union-attr,index]
    assert exhausted == [
        {
            "label": "Exhausted",
            "help": (
                "The level this step's decision found exhausted: deterministic "
                "exploration had nothing left to do there. The evaluator re-derives "
                "this marker from the stored run."
            ),
            "value": "level (0, 2)",
        }
    ]
    goal = next(fact for fact in result["exhausted"] if fact["label"] == "Goal")  # type: ignore[union-attr,index]
    assert goal["value"] == "explore_level:0:2"
    # A null marker and a legacy event without the field render identically,
    # with no Exhausted row.
    assert result["nullMarker"] == result["legacy"]
    assert all(fact["label"] != "Exhausted" for fact in result["legacy"])  # type: ignore[union-attr,index]
    assert [fact for fact in result["exhausted"] if fact["label"] != "Exhausted"] == (
        result["legacy"]
    )


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_run_speed_controls_follow_live_status_without_unpinning_history() -> None:
    result = _run_renderer_module(
        """
        import vm from "node:vm";
        import { readFile } from "node:fs/promises";

        const nodes = new Map();
        const element = (id) => {
          if (!nodes.has(id)) {
            nodes.set(id, {
              value: "", checked: false, disabled: false, hidden: true,
              textContent: "", handlers: {},
              addEventListener(kind, callback) { this.handlers[kind] = callback; },
            });
          }
          return nodes.get(id);
        };
        const view = new Proxy({}, { get: (_, key) => element(key) });
        view.seed.value = "6";
        view.maxSteps.value = "200";
        view.startSpeed.value = "2.5";
        const frames = [];
        const timers = new Map();
        let nextTimer = 0;
        const calls = [];
        const streams = [];
        let selected = null;
        let latestEvent = null;
        let status = {
          run: { id: "live", state: "paused", error: null },
          coordinator: {
            current_goal: null, current_skill: null, last_error: null,
            observation: { step_index: 0 },
          },
          legal_actions: [],
          max_steps_per_second: 2.5,
        };
        const context = vm.createContext({
          URLSearchParams, location: { hash: "" },
          history: { replaceState() {} },
          requestAnimationFrame: (callback) => frames.push(callback),
          setTimeout: (callback, delay) => {
            const id = ++nextTimer;
            timers.set(id, { callback, delay });
            return id;
          },
          clearTimeout: (id) => timers.delete(id),
        });
        const modules = {
          "./client.js": {
            ApiError: Error,
            runPath: (id, suffix = "") => `api/runs/${id}${suffix}`,
            findLastSequence: async () => -1,
            request: async (method, path, body) => {
              calls.push({ method, path, body });
              if (path.endsWith("/speed")) {
                status.max_steps_per_second = body.max_steps_per_second || null;
              }
              return structuredClone(status);
            },
            EventStream: class {
              constructor(id, after, hooks) { this.hooks = hooks; streams.push(this); }
              start() {}
              close() {}
            },
          },
          "./view.js": {
            element, view, initializeView() {}, repositionShownTooltip() {},
            syncHeaderOffset() {},
          },
          "./event-log.js": {
            resetAgentLogs() {},
            selectStepEntry: (_, sequence) => { selected = sequence ?? null; },
            appendEventLog: (_, event, names, callback) => {
              latestEvent = { event, select: () => callback(event) };
            },
          },
          "./render.js": {
            goalFact: () => ({ text: "", help: "" }),
            observationIntent: () => null,
            promptText: () => "",
            renderInventory() {}, renderMetrics() {}, renderStats() {},
            renderMap: (node, observation) => { node.step = observation?.step_index; },
            setExplainedText() {},
            setText: (node, text) => { node.textContent = text ?? "-"; },
          },
        };
        const app = new vm.SourceTextModule(await readFile("app.js", "utf8"), { context });
        await app.link((specifier) => {
          const exports = modules[specifier];
          return new vm.SyntheticModule(Object.keys(exports), function () {
            for (const [key, value] of Object.entries(exports)) {
              this.setExport(key, value);
            }
          }, { context });
        });
        await app.evaluate();
        const flush = async () => {
          for (let i = 0; i < 20; i += 1) {
            await Promise.resolve();
            while (frames.length) frames.shift()();
          }
        };
        const submit = async (id) => {
          element(id).handlers.submit({ preventDefault() {} });
          await flush();
        };
        await flush();
        const detached = view.setSpeed.disabled && view.runSpeed.disabled;
        await submit("start-form");
        const started = {
          body: calls[0].body, current: view.currentSpeed.textContent,
          input: view.runSpeed.value, enabled: !view.setSpeed.disabled,
        };
        view.runSpeed.value = "0";
        await submit("speed-form");
        const unlimited = {
          request: calls.at(-1), current: view.currentSpeed.textContent,
        };
        view.runSpeed.value = "1.25";
        await submit("speed-form");
        const fractional = calls.at(-1);
        const callCount = calls.length;
        const invalid = [];
        for (const value of ["-1", "Infinity", "NaN", ""]) {
          view.runSpeed.value = value;
          await submit("speed-form");
          invalid.push(!view.error.hidden && calls.length === callCount);
        }
        const step = (index) => ({
          kind: "step", sequence: index,
          payload: {
            observation: { step_index: index }, selection: { goal: null, skill: null },
          },
        });
        streams[0].hooks.onEvent(step(1));
        latestEvent.select();
        await flush();
        streams[0].hooks.onEvent(step(2));
        status.max_steps_per_second = 4;
        status.coordinator.observation.step_index = 2;
        const poll = [...timers.values()].find((timer) => timer.delay === 1000);
        timers.clear();
        await poll.callback();
        await flush();
        const pinned = {
          step: view.map.step, selected, current: view.currentSpeed.textContent,
          input: view.runSpeed.value, historyVisible: !view.historyView.hidden,
        };
        view.backToLive.handlers.click();
        await flush();
        const liveStep = view.map.step;
        status = {
          ...status, run: { ...status.run, id: "old" },
          coordinator: null, max_steps_per_second: null,
        };
        view.attachId.value = "old";
        await submit("attach-form");
        const readOnlyCalls = calls.length;
        await submit("speed-form");
        console.log(JSON.stringify({
          detached, started, unlimited, fractional, invalid, pinned, liveStep,
          readOnly: {
            disabled: view.setSpeed.disabled && view.runSpeed.disabled,
            current: view.currentSpeed.textContent,
            noPost: calls.length === readOnlyCalls,
          },
        }));
        """,
        vm_modules=True,
    )
    assert result["detached"] is True
    assert result["started"] == {
        "body": {
            "seed": 6,
            "max_episode_steps": 200,
            "auto_start": False,
            "max_steps_per_second": 2.5,
        },
        "current": "Current: 2.5 steps/s",
        "input": "2.5",
        "enabled": True,
    }
    assert result["unlimited"] == {
        "request": {
            "method": "POST",
            "path": "api/runs/live/speed",
            "body": {"max_steps_per_second": 0},
        },
        "current": "Current: unlimited",
    }
    assert result["fractional"] == {
        "method": "POST",
        "path": "api/runs/live/speed",
        "body": {"max_steps_per_second": 1.25},
    }
    assert result["invalid"] == [True, True, True, True]
    assert result["pinned"] == {
        "step": 1,
        "selected": 1,
        "current": "Current: 4 steps/s",
        "input": "4",
        "historyVisible": True,
    }
    assert result["liveStep"] == 2
    assert result["readOnly"] == {
        "disabled": True,
        "current": "Current: unlimited",
        "noPost": True,
    }
