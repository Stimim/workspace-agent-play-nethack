import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nethack_agent.api import UI_CONTENT_SECURITY_POLICY, create_app
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager

UI_DIR = Path(__file__).parents[1] / "src" / "nethack_agent" / "ui"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
NODE = shutil.which("node")


def _run_renderer_module(script: str) -> dict[str, object]:
    assert NODE is not None
    completed = subprocess.run(
        [NODE, "--input-type=module", "--eval", script],
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
              goal: "stand_on_downstairs",
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
const spans = (observation, intent) => {
  const pre = new Node();
  renderMap(pre, observation, intent);
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
def test_map_intent_comes_only_from_the_step_that_produced_the_observation() -> None:
    result = _run_renderer_module(
        """
        const { intentFact, observationIntent } = await import("./render.js");
        const intent = {
          destination: { kind: "frontier", x: 57, y: 11 },
          attack_target: { x: 56, y: 10 },
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
    }
    assert result["newerObservation"] is None
    assert result["noStep"] is None
    # A step stored before intents existed has none; nothing is inferred.
    assert result["legacy"] is None
    assert result["legacyFact"] == result["nullFact"]
    assert "(" not in result["legacyFact"]["text"]
    assert "(57, 11)" in result["fact"]["text"]
    assert "(56, 10)" in result["fact"]["text"]
