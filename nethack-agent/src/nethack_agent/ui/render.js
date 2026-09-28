// DOM rendering. Every model- or game-provided string is inserted with
// textContent or text nodes; nothing here parses HTML.

const HUNGER = ["satiated", "not hungry", "hungry", "weak", "fainting", "fainted", "starved"];
const ENCUMBRANCE = ["unencumbered", "burdened", "stressed", "strained", "overtaxed", "overloaded"];
const ALIGNMENT = new Map([[-1, "chaotic"], [0, "neutral"], [1, "lawful"]]);

const FIELD_HELP = Object.freeze({
  "Run id": "The stable identifier used by the API, event stream, and URL fragment.",
  State: "The persisted run lifecycle state. Control availability also depends on whether this service owns the run.",
  Outcome: "The terminal task result, when the run has ended.",
  Seed: "The suite seed and configured maximum episode step count.",
  Model: "The local model identity and fixed policy version recorded for this run.",
  Goal: "The typed goal the objective planner set, shown as its token. A stair goal (stand on or traverse stairs) names the stair direction and main/branch target as kind:direction:connection[:dungeon]; an explore_level goal names the level to explore until deterministic exploration is exhausted, as explore_level:dungeon:level.",
  Skill: "The typed executing skill from the Skill enum in decision.py.",
  Stream: "The browser's WebSocket connection state, including reconnects and normal closure.",
  "Last error": "The latest coordinator or persisted run error.",
  HP: "Current and maximum hit points.",
  Pw: "Current and maximum magical energy.",
  AC: "Armor class; lower values provide better protection in NetHack.",
  Level: "Experience level and accumulated experience points.",
  Depth: "Displayed depth plus the dungeon and level identifiers reported by NLE.",
  Position: "Zero-based map coordinates from the projected player state.",
  Turn: "The NetHack turn counter.",
  Gold: "Gold currently carried.",
  Score: "The score reported by NLE.",
  Hunger: "The decoded NetHack hunger state and its numeric value.",
  Encumbrance: "The decoded carrying-load state and its numeric value.",
  Alignment: "The player's alignment.",
  Strength: "Strength, including NetHack's 18/xx exceptional-strength notation.",
  Dexterity: "Dexterity.",
  Constitution: "Constitution.",
  Intelligence: "Intelligence.",
  Wisdom: "Wisdom.",
  Charisma: "Charisma.",
  Blessed: "B: explicitly described by NetHack as blessed.",
  Uncursed: "U: explicitly described by NetHack as uncursed.",
  Cursed: "C: explicitly described by NetHack as cursed.",
  Unknown: "?: no explicit blessed, uncursed, or cursed adjective is present in the NLE inventory description.",
  Conditions: "Active status conditions projected from NLE.",
  Source: "The typed ActionSelectionSource that produced the executed action.",
  "Skill selected by": "The typed SkillSelectionSource: the arbiter or a stuck-state model consultation.",
  Action: "The executed legal action, stable action index, and NetHack command value.",
  Rationale: "The persisted concise rationale. This is an auditable decision trace, not hidden chain-of-thought.",
  Intent: "The typed map intent a deterministic skill recorded with this step: its destination (route goal) and any attack target, in zero-based map coordinates. Prompt answers, model fallbacks, and steps recorded before intents existed have none.",
  Stuck: "The typed reason deterministic exploration could not propose an action.",
  Exhausted: "The level this step's decision found exhausted: deterministic exploration had nothing left to do there. The evaluator re-derives this marker from the stored run.",
  "Skill choice": "The typed skill returned by the model consultation.",
  "Skill rationale": "The concise rationale returned with the model skill choice.",
  "Model rationale": "The concise rationale returned with a model fallback action.",
  Reward: "The reward returned by NLE for this executed step.",
  Ended: "Whether this step terminated or truncated the episode.",
  "Skill model": "Inference metrics for a skill consultation on the latest step.",
  "Action model": "Inference metrics for a fallback-action consultation on the latest step.",
  "Steps seen": "Step events received by this browser attachment.",
  "Model calls": "Skill and action model calls represented by received step events.",
  Tokens: "Prompt and output token totals represented by received events.",
  "Mean latency": "Mean reported model latency across received model calls.",
  Repairs: "Received model calls that used the one allowed schema-repair attempt.",
  "Observation step": "The projected observation's one-based action count, or zero immediately after reset.",
  "Legal actions": "The number of indexed actions exposed by the environment for this run.",
  Transition: "The lifecycle transition represented by this event.",
  "Error phase": "The typed phase in which the agent error occurred.",
  Error: "The persisted error message associated with the event.",
  "Decision failure": "The bounded model-decision failure recorded with an agent error.",
  "Failed attempts": "The number of failed initial or schema-repair model attempts.",
  "Previous state": "The lifecycle state immediately before the run was stopped.",
  "Event kind": "The discriminated event variant from the typed event contract.",
  Evidence: "The exact typed event field that qualifies this row as deterministic execution.",
  Player: "The hero's cell from the projected player coordinates. This highlight wins over every other map highlight.",
  Pet: "A cell whose glyph NLE identifies as a pet (the observation's pet_rows). Observations recorded before pet evidence existed show none. The fill stays visible beneath a destination box, attack-target box, or path tint.",
  Destination: "The cell the latest step's deterministic skill works toward: a frontier, remembered downstairs or upstairs, search spot, or locked door. Usually not the adjacent cell stepped into; hidden when it is the player's own cell. A step that used a staircase recorded its intent on the previous level, so the new level's map shows none.",
  "Attack target": "The displayed hostile monster the latest step's deterministic skill attacks by moving into it. Its box wins over a destination box on the same cell.",
  Path: "The breadth-first route a deterministic skill's step followed, in order from the cell it stepped into to its destination (for a locked door, the cell beside it where the hero kicks). The map tints it beneath the destination and attack-target boxes; the player's cell hides it. Show path turns the map tint off. Waiting, searching, kicking, adjacent-hostile defense, prompt answers, model fallbacks, and steps recorded before routes existed have none.",
});

const VALUE_HELP = Object.freeze({
  staircase_navigation: "Skill.STAIRCASE_NAVIGATION: route to the nearest remembered reachable staircase that matches the goal, handling an adjacent hostile first, then wait on it or use it as the goal requires.",
  explore_level: "Skill.EXPLORE_LEVEL: explore unseen space, handle doors and adjacent hostiles, and search for hidden passages.",
  arbiter: "The deterministic arbiter selected the skill for this step.",
  model: "The model selected the skill after deterministic exploration reported that it was stuck.",
  deterministic_skill: "A deterministic skill selected this action.",
  deterministic_prompt: "The deterministic safe-prompt handler selected this response.",
  model_fallback: "The local model selected this action for an unhandled prompt or stuck fallback.",
});

const DETERMINISTIC_SOURCES = new Set(["deterministic_skill", "deterministic_prompt"]);
let tooltipSequence = 0;
// Live renders run on every event. Unchanged content keeps its DOM so a hovered
// or keyboard-focused tooltip is not replaced; changed content restores focus
// to the trigger at the same position.
const renderedContent = new WeakMap();

function replaceExplained(element, signature, build) {
  if (renderedContent.get(element) === signature) {
    return;
  }
  const triggers = Array.from(element.querySelectorAll(".tooltip-trigger"));
  const focused = triggers.indexOf(document.activeElement);
  build();
  renderedContent.set(element, signature);
  if (focused >= 0) {
    element.querySelectorAll(".tooltip-trigger")[focused]?.focus();
  }
}

function displayed(value) {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function appendTooltip(parent, text, help, markerClass = null) {
  if (!help) {
    parent.textContent = text;
    return;
  }
  tooltipSequence += 1;
  const tooltipId = `tooltip-${tooltipSequence}`;
  const wrapper = document.createElement("span");
  wrapper.className = markerClass ? `tooltip ${markerClass}` : "tooltip";
  const trigger = document.createElement("span");
  trigger.className = "tooltip-trigger";
  trigger.tabIndex = 0;
  trigger.setAttribute("aria-describedby", tooltipId);
  const tooltip = document.createElement("span");
  trigger.textContent = text;
  tooltip.id = tooltipId;
  tooltip.className = "tooltip-content";
  tooltip.setAttribute("role", "tooltip");
  tooltip.textContent = help;
  wrapper.append(trigger, tooltip);
  parent.append(wrapper);
}

export function setText(element, value) {
  element.textContent = displayed(value);
}

export function setExplainedText(element, value, help = undefined) {
  const text = displayed(value);
  replaceExplained(element, text, () => {
    element.replaceChildren();
    appendTooltip(element, text, help ?? VALUE_HELP[text]);
  });
}

const GOAL_HELP = Object.freeze({
  stand_on_stairs: "Goal stand_on_stairs: stand on a remembered staircase that matches the target without using it.",
  traverse_stairs: "Goal traverse_stairs: reach a remembered staircase that matches the target and use it to change level.",
  explore_level: "Goal explore_level: explore this level until deterministic exploration finds no unexplored space, locked door to kick, or search spot left.",
});

const CONNECTION_HELP = Object.freeze({
  any: "any staircase of that direction",
  main: "the staircase to the adjacent level of the current dungeon",
  branch: "the staircase into another dungeon",
});

// Text and tooltip for a typed goal. The text is the goal's token, the same
// identifier the model is offered: kind:direction:connection[:dungeon] for a
// stair goal, explore_level:dungeon:level for a level-exploration goal.
export function goalFact(goal) {
  if (goal?.kind === "explore_level" && goal.level) {
    const { dungeon_number: dungeon, dungeon_level: level } = goal.level;
    return {
      text: `${goal.kind}:${dungeon}:${level}`,
      help: `${GOAL_HELP[goal.kind]} Level: dungeon ${dungeon}, level ${level}.`,
    };
  }
  if (!goal?.target) {
    return { text: null, help: undefined };
  }
  const { direction, connection, dungeon_number: dungeon } = goal.target;
  const hasDungeon = dungeon !== null && dungeon !== undefined;
  const parts = [goal.kind, direction, connection, ...(hasDungeon ? [String(dungeon)] : [])];
  const glyph = direction === "down" ? ">" : "<";
  const into = hasDungeon ? ` (dungeon ${dungeon})` : "";
  return {
    text: parts.join(":"),
    help: `${GOAL_HELP[goal.kind] ?? `Goal ${goal.kind}.`} Target: ${direction}stairs (${glyph}), ${CONNECTION_HELP[connection] ?? connection}${into}.`,
  };
}

function goalPair(goal) {
  const fact = goalFact(goal);
  return ["Goal", fact.text, { valueHelp: fact.help }];
}

export function installFieldTooltips(root) {
  for (const element of root.querySelectorAll("[data-help-key]")) {
    const label = element.dataset.helpKey;
    element.replaceChildren();
    appendTooltip(element, label, FIELD_HELP[label]);
  }
}

export function setFacts(list, pairs) {
  const rows = pairs.map(([label, value, options = {}]) => {
    const text = displayed(value);
    return [label, text, options.help ?? FIELD_HELP[label], options.valueHelp ?? VALUE_HELP[text]];
  });
  replaceExplained(list, JSON.stringify(rows), () => {
    const fragment = document.createDocumentFragment();
    for (const [label, text, help, valueHelp] of rows) {
      const term = document.createElement("dt");
      appendTooltip(term, label, help);
      const description = document.createElement("dd");
      appendTooltip(description, text, valueHelp);
      fragment.append(term, description);
    }
    list.replaceChildren(fragment);
  });
}

function setStatCells(list, pairs) {
  const cells = pairs.map(([label, value, options = {}]) => {
    const text = displayed(value);
    return [
      label,
      text,
      options.help ?? FIELD_HELP[label],
      options.valueHelp ?? VALUE_HELP[text],
      options.wide ?? false,
    ];
  });
  replaceExplained(list, JSON.stringify(cells), () => {
    const fragment = document.createDocumentFragment();
    for (const [label, text, help, valueHelp, wide] of cells) {
      const cell = document.createElement("div");
      cell.className = wide ? "stat-cell stat-cell-wide" : "stat-cell";
      const term = document.createElement("dt");
      appendTooltip(term, label, help);
      const description = document.createElement("dd");
      appendTooltip(description, text, valueHelp);
      cell.append(term, description);
      fragment.append(cell);
    }
    list.replaceChildren(fragment);
  });
}

export function hexToBytes(hex) {
  const bytes = new Array(Math.floor(hex.length / 2));
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

// The typed intent of the step decision that produced `observation`: the
// latest step event, when it carries that same observation. A status snapshot
// newer than the latest received step shows no intent until its step arrives.
// An intent recorded for another level (the step that used a staircase) is
// not drawn on this level's map; intents recorded before levels were (null
// level) are drawn as before.
export function observationIntent(observation, stepEvent) {
  const payload = stepEvent?.payload;
  if (!observation || payload?.observation?.step_index !== observation.step_index) {
    return null;
  }
  const intent = payload.selection?.intent ?? null;
  const level = intent?.level;
  const { player } = observation;
  if (
    level &&
    (level.dungeon_number !== player?.dungeon_number || level.dungeon_level !== player?.dungeon_level)
  ) {
    return null;
  }
  return intent;
}

function atCell(cell, x, y) {
  return cell !== null && cell.x === x && cell.y === y;
}

// Groups each row into spans of equal highlight and NetHack color. Precedence:
// the player cell gets only its own highlight; otherwise the attack-target box
// wins over the destination box, which wins over the path tint, and the pet
// fill (only from the API's explicit pet evidence) combines with any of them.
// Non-player cells keep their NetHack foreground color. A null `pet_rows`
// (observations stored before pet evidence existed) highlights no pet, a null
// intent marks no target, and a null `path` (none recorded) draws no route.
// `showPath` false hides only the path tint.
export function renderMap(pre, observation, intent = null, showPath = true) {
  if (!observation) {
    pre.replaceChildren();
    return;
  }
  const { rows, color_rows: colorRows, pet_rows: petRows } = observation.map;
  const { x, y } = observation.player;
  const destination = intent?.destination ?? null;
  const attackTarget = intent?.attack_target ?? null;
  const path = new Set(showPath ? (intent?.path ?? []).map((cell) => `${cell.x},${cell.y}`) : []);
  const fragment = document.createDocumentFragment();
  rows.forEach((row, rowIndex) => {
    const cells = Array.from(row);
    const colors = hexToBytes(colorRows[rowIndex] ?? "");
    const pets = hexToBytes(petRows?.[rowIndex] ?? "");
    let text = "";
    let key = null;
    const flush = () => {
      if (text) {
        const span = document.createElement("span");
        span.className = key;
        span.textContent = text;
        fragment.append(span);
      }
      text = "";
    };
    cells.forEach((cell, columnIndex) => {
      let cellKey = "player";
      if (rowIndex !== y || columnIndex !== x) {
        const classes = [];
        if (atCell(attackTarget, columnIndex, rowIndex)) {
          classes.push("attack-target");
        } else if (atCell(destination, columnIndex, rowIndex)) {
          classes.push("destination");
        } else if (path.has(`${columnIndex},${rowIndex}`)) {
          classes.push("path");
        }
        if (pets[columnIndex] === 1) {
          classes.push("pet");
        }
        classes.push(`c${colors[columnIndex] ?? 7}`);
        cellKey = classes.join(" ");
      }
      if (cellKey !== key) {
        flush();
        key = cellKey;
      }
      text += cell;
    });
    flush();
    if (rowIndex < rows.length - 1) {
      fragment.append(document.createTextNode("\n"));
    }
  });
  pre.replaceChildren(fragment);
}

// NLE's STR125 value uses NetHack's encoding: 18/xx is 18 + xx, 18/** is 118,
// and 19..25 are 119..125.
function strength(player) {
  const value = player.strength_125;
  if (value <= 18) {
    return String(value);
  }
  if (value < 118) {
    return `18/${String(value - 18).padStart(2, "0")}`;
  }
  return value === 118 ? "18/**" : String(value - 100);
}

function labelled(names, value) {
  return names[value] === undefined ? String(value) : `${names[value]} (${value})`;
}

export function renderStats(list, player) {
  if (!player) {
    setFacts(list, []);
    return;
  }
  setStatCells(list, [
    ["HP", `${player.hit_points} / ${player.max_hit_points}`],
    ["Pw", `${player.energy} / ${player.max_energy}`],
    ["AC", player.armor_class],
    ["Level", `XL ${player.experience_level} (${player.experience_points} xp)`],
    ["Depth", `${player.depth} (dungeon ${player.dungeon_number}, level ${player.dungeon_level})`],
    ["Position", `x ${player.x}, y ${player.y}`],
    ["Turn", player.turn],
    ["Gold", player.gold],
    ["Score", player.score],
    ["Hunger", labelled(HUNGER, player.hunger)],
    ["Encumbrance", labelled(ENCUMBRANCE, player.encumbrance)],
    ["Alignment", ALIGNMENT.get(player.alignment) ?? String(player.alignment)],
    ["Strength", strength(player)],
    ["Dexterity", player.dexterity],
    ["Constitution", player.constitution],
    ["Intelligence", player.intelligence],
    ["Wisdom", player.wisdom],
    ["Charisma", player.charisma],
    [
      "Conditions",
      player.conditions.length ? player.conditions.join(", ") : "none",
      { wide: true },
    ],
  ]);
}

const BUC_MARKERS = Object.freeze({
  blessed: {
    text: "[B]",
    help: "Blessed: the NLE inventory description explicitly starts with the adjective blessed.",
  },
  uncursed: {
    text: "[U]",
    help: "Uncursed: the NLE inventory description explicitly starts with the adjective uncursed.",
  },
  cursed: {
    text: "[C]",
    help: "Cursed: the NLE inventory description explicitly starts with the adjective cursed.",
  },
  unknown: {
    text: "[?]",
    help: "Unknown BUC: the NLE inventory description contains no explicit leading beatitude adjective.",
  },
});


export function renderInventory(list, inventory) {
  const fragment = document.createDocumentFragment();
  for (const item of inventory ?? []) {
    const entry = document.createElement("li");
    const status = Object.hasOwn(BUC_MARKERS, item.buc) ? item.buc : "unknown";
    const marker = BUC_MARKERS[status];
    entry.className = `inventory-item buc-${status}`;
    appendTooltip(entry, marker.text, marker.help, `buc-marker buc-${status}`);
    const description = document.createElement("span");
    description.className = "inventory-description";
    description.textContent = ` ${item.letter} - ${item.description}`;
    entry.append(description);
    fragment.append(entry);
  }
  if (!fragment.childNodes.length) {
    const entry = document.createElement("li");
    entry.className = "muted";
    entry.textContent = "empty";
    fragment.append(entry);
  }
  list.replaceChildren(fragment);
}

export function promptText(prompt) {
  if (!prompt) {
    return "Prompt: -";
  }
  const active = Object.entries(prompt)
    .filter(([, value]) => value === true)
    .map(([name]) => name);
  return `Prompt: ${active.length ? active.join(", ") : "none"}`;
}

export function actionLabel(index, actionNames) {
  const name = actionNames.get(index);
  return name ? `${name} (#${index})` : `#${index}`;
}

function formatMetrics(metrics) {
  if (!metrics) {
    return "none";
  }
  const latency = Number(metrics.latency_ms).toFixed(1);
  const repair = metrics.repair_attempted ? ", schema repair" : "";
  return `${latency} ms, ${metrics.prompt_tokens} prompt / ${metrics.output_tokens} output tokens${repair}`;
}

const DESTINATION_LABELS = Object.freeze({
  downstairs: "downstairs",
  upstairs: "upstairs",
  frontier: "frontier",
  search_spot: "search spot",
  locked_door: "locked door",
});

const DESTINATION_HELP = Object.freeze({
  downstairs: "Destination downstairs: the remembered > that staircase navigation routes to, stands on, or uses.",
  upstairs: "Destination upstairs: the remembered < that staircase navigation routes to, stands on, or uses.",
  frontier: "Destination frontier: the known cell next to never-observed space that exploration routes to.",
  search_spot: "Destination search spot: the committed cell exploration walks to and searches for hidden passages from.",
  locked_door: "Destination locked door: the known-locked door exploration walks beside, kicks, and aims its kick at.",
});

const ATTACK_HELP = "Attack target: the adjacent displayed hostile monster this action attacks by moving into it.";
const NO_INTENT_HELP =
  "No intent recorded: a prompt answer, a model fallback, a skill action without a map target, or a step stored before intents existed.";

function cellText(cell) {
  return `(${cell.x}, ${cell.y})`;
}

// Text and tooltip for a step's typed intent; missing or null means none was
// recorded, never an inferred target.
export function intentFact(intent) {
  if (!intent) {
    return { text: "none recorded", help: NO_INTENT_HELP };
  }
  const text = [];
  const help = [];
  if (intent.destination) {
    const { kind, stair } = intent.destination;
    const identity = stair ? ` [${stairText(stair)}]` : "";
    text.push(`destination: ${DESTINATION_LABELS[kind] ?? kind} ${cellText(intent.destination)}${identity}`);
    help.push(DESTINATION_HELP[kind] ?? `Destination kind ${kind}.`);
    if (stair) {
      help.push(STAIR_HELP);
    }
  }
  if (intent.attack_target) {
    text.push(`attack target: ${cellText(intent.attack_target)}`);
    help.push(ATTACK_HELP);
  }
  if (intent.level) {
    text.push(`level ${levelText(intent.level)}`);
    help.push(LEVEL_HELP);
  }
  return { text: text.join("; "), help: help.join(" ") };
}

const STAIR_HELP =
  "The bracket is the staircase identity the skill believed when it chose this destination: main, branch (to a dungeon number), exit, or unknown, and the evidence (traversed, arrival, elimination, or rule).";
const LEVEL_HELP =
  "Level: the (dungeon number, dungeon level) the intent's cells belong to, from NLE's bottom-line statistics.";

function stairText(stair) {
  const target = stair.dungeon_number === null || stair.dungeon_number === undefined ? "" : ` to ${stair.dungeon_number}`;
  const evidence = stair.evidence ? ` by ${stair.evidence}` : "";
  return `${stair.kind}${target}${evidence}`;
}

function levelText(level) {
  return `(${level.dungeon_number}, ${level.dungeon_level})`;
}

const NO_PATH_HELP =
  "No route recorded: the action followed no route (waiting, searching, kicking, adjacent-hostile defense, a prompt answer, or a model fallback), or the step was stored before routes were recorded.";

// Text and tooltip for the route a step's intent recorded; a missing or null
// path means none was recorded, never a route rebuilt from other fields.
export function pathFact(intent) {
  const path = intent?.path;
  if (!path?.length) {
    return { text: "none recorded", help: NO_PATH_HELP };
  }
  const steps = `${path.length} ${path.length === 1 ? "step" : "steps"}`;
  const first = cellText(path[0]);
  const last = cellText(path[path.length - 1]);
  const cells = path.length === 1 ? first : `${first} to ${last}`;
  return {
    text: `${steps}: ${cells}`,
    help: `Path: the breadth-first route this step followed, ${steps} from ${first}, the cell it stepped into, to ${last}. The map tints these cells while Show path is on.`,
  };
}

export function renderDecision(list, candidateBody, stepEvent, actionNames) {
  if (!stepEvent) {
    setFacts(list, [["Decision", "no step yet"]]);
    candidateBody.replaceChildren();
    return;
  }
  const payload = stepEvent.payload;
  const { selection, action } = payload;
  const pairs = [
    ["Source", selection.source],
    goalPair(selection.goal),
    ["Skill", selection.skill],
    ["Skill selected by", selection.skill_selection],
    ["Action", `${action.name} (#${action.index}, command ${action.command})`],
    ["Rationale", selection.rationale],
  ];
  const intent = intentFact(selection.intent);
  pairs.push(["Intent", intent.text, { valueHelp: intent.help }]);
  const path = pathFact(selection.intent);
  pairs.push(["Path", path.text, { valueHelp: path.help }]);
  if (selection.stuck_reason) {
    pairs.push(["Stuck", selection.stuck_reason]);
  }
  if (selection.exhausted_level) {
    const { dungeon_number: dungeon, dungeon_level: level } = selection.exhausted_level;
    pairs.push(["Exhausted", `level (${dungeon}, ${level})`]);
  }
  if (payload.skill_decision) {
    pairs.push(
      ["Skill choice", payload.skill_decision.skill],
      ["Skill rationale", payload.skill_decision.rationale],
    );
  }
  if (payload.action_decision) {
    pairs.push(["Model rationale", payload.action_decision.rationale]);
  }
  pairs.push(
    ["Reward", payload.reward],
    ["Ended", payload.terminated ? "terminated" : payload.truncated ? "truncated" : "no"],
    ["Outcome", payload.outcome],
  );
  setFacts(list, pairs);

  const fragment = document.createDocumentFragment();
  const decision = payload.action_decision;
  if (decision) {
    for (const candidate of decision.candidates) {
      const row = document.createElement("tr");
      if (candidate.action_index === decision.action_index) {
        row.className = "chosen";
      }
      for (const value of [
        actionLabel(candidate.action_index, actionNames),
        Number(candidate.score).toFixed(2),
        candidate.reason,
      ]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      fragment.append(row);
    }
  } else {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.className = "muted";
    cell.textContent = `No model candidates: ${selection.source} selection.`;
    row.append(cell);
    fragment.append(row);
  }
  candidateBody.replaceChildren(fragment);
}

export function renderMetrics(list, stepEvent, totals) {
  const payload = stepEvent?.payload;
  const meanLatency = totals.modelCalls ? (totals.latencyMs / totals.modelCalls).toFixed(1) : "-";
  setFacts(list, [
    ["Skill model", payload ? formatMetrics(payload.skill_metrics) : "-"],
    ["Action model", payload ? formatMetrics(payload.action_metrics) : "-"],
    ["Steps seen", totals.steps],
    ["Model calls", totals.modelCalls],
    ["Tokens", `${totals.promptTokens} prompt / ${totals.outputTokens} output`],
    ["Mean latency", totals.modelCalls ? `${meanLatency} ms` : "-"],
    ["Repairs", totals.repairs],
  ]);
}

export function eventSummary(event) {
  const payload = event.payload ?? {};
  const time = typeof event.created_at === "string" ? event.created_at.slice(11, 23) : "";
  const prefix = `#${event.sequence} ${time} ${event.kind}`;
  switch (event.kind) {
    case "run_started":
      return `${prefix} goal=${goalFact(payload.goal).text ?? "-"} skill=${payload.skill ?? "-"}`;
    case "step": {
      const outcome = payload.outcome ? ` outcome=${payload.outcome}` : "";
      return `${prefix} ${payload.action?.name} via ${payload.selection?.source} reward=${payload.reward}${outcome}`;
    }
    case "agent_error": {
      const failure = payload.decision_failure
        ? ` (${payload.decision_failure.attempts.length} attempts, ${formatMetrics(payload.decision_failure.metrics)})`
        : "";
      return `${prefix} [${payload.phase}] state=${payload.state}: ${payload.error}${failure}`;
    }
    case "run_stopped":
      return `${prefix} previous_state=${payload.previous_state}`;
    default:
      return prefix;
  }
}

function candidateTable() {
  const table = document.createElement("table");
  table.className = "candidates";
  const caption = document.createElement("caption");
  caption.textContent = "Model fallback candidates";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Action", "Score", "Reason"]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  table.append(caption, head, body);
  return table;
}

function renderEventDetails(container, event, actionNames) {
  const payload = event.payload ?? {};
  if (event.kind === "step") {
    const facts = document.createElement("dl");
    facts.className = "facts";
    const table = candidateTable();
    renderDecision(facts, table.tBodies[0], event, actionNames);
    container.append(facts, table);
    return;
  }

  const facts = document.createElement("dl");
  facts.className = "facts";
  switch (event.kind) {
    case "run_started":
      setFacts(facts, [
        goalPair(payload.goal),
        ["Skill", payload.skill],
        ["Observation step", payload.observation?.step_index],
        ["Legal actions", payload.legal_actions?.length],
      ]);
      break;
    case "run_resumed":
      setFacts(facts, [["Transition", "run resumed"]]);
      break;
    case "run_paused":
      setFacts(facts, [["Transition", "run paused"]]);
      break;
    case "agent_error":
      setFacts(facts, [
        ["Error phase", payload.phase],
        ["State", payload.state],
        ["Error", payload.error],
        ["Decision failure", payload.decision_failure?.message],
        ["Failed attempts", payload.decision_failure?.attempts?.length],
      ]);
      break;
    case "run_stopped":
      setFacts(facts, [["Previous state", payload.previous_state]]);
      break;
    default:
      setFacts(facts, [["Event kind", event.kind]]);
      break;
  }
  container.append(facts);
}

export function renderEventEntry(event, actionNames, expandDecision = false) {
  const entry = document.createElement("li");
  entry.className = `kind-${event.kind}`;
  const details = document.createElement("details");
  details.className = "agent-row";
  if (event.kind === "step") {
    details.dataset.decision = "true";
    details.open = expandDecision;
  }
  const summary = document.createElement("summary");
  summary.textContent = eventSummary(event);
  const content = document.createElement("div");
  content.className = "event-detail";
  renderEventDetails(content, event, actionNames);
  details.append(summary, content);
  entry.append(details);
  return entry;
}

export function deterministicExecution(event) {
  if (event?.kind !== "step") {
    return null;
  }
  const payload = event.payload;
  const source = payload?.selection?.source;
  if (!DETERMINISTIC_SOURCES.has(source) || !payload?.action) {
    return null;
  }
  return {
    event,
    source,
    action: payload.action,
    selection: payload.selection,
    reward: payload.reward,
    outcome: payload.outcome,
  };
}

export function renderToolEntry(execution) {
  const { event, source, action, selection, reward, outcome } = execution;
  const entry = document.createElement("li");
  const details = document.createElement("details");
  details.className = "agent-row";
  const summary = document.createElement("summary");
  summary.textContent = `#${event.sequence} ${action.name} via ${source}`;
  const content = document.createElement("div");
  content.className = "event-detail";
  const facts = document.createElement("dl");
  facts.className = "facts";
  setFacts(facts, [
    ["Evidence", `event.payload.selection.source = ${source}`],
    ["Action", `${action.name} (#${action.index}, command ${action.command})`],
    goalPair(selection.goal),
    ["Skill", selection.skill],
    ["Skill selected by", selection.skill_selection],
    ["Rationale", selection.rationale],
    ["Reward", reward],
    ["Outcome", outcome],
  ]);
  content.append(facts);
  details.append(summary, content);
  entry.append(details);
  return entry;
}

export function verboseDetails(event) {
  const payload = event?.payload ?? {};
  const values = [];
  const add = (label, value) => {
    if (typeof value === "string" && value.length) {
      values.push({ label, value });
    }
  };

  add("Game message", payload.observation?.message);
  if (event?.kind === "step") {
    add("Selection rationale", payload.selection?.rationale);
    add("Skill rationale", payload.skill_decision?.rationale);
    add("Model rationale", payload.action_decision?.rationale);
    for (const candidate of payload.action_decision?.candidates ?? []) {
      add(`Candidate #${candidate.action_index}`, candidate.reason);
    }
  } else if (event?.kind === "agent_error") {
    add("Agent error", payload.error);
    add("Decision failure", payload.decision_failure?.message);
    for (const [index, attempt] of (payload.decision_failure?.attempts ?? []).entries()) {
      add(`Attempt ${index + 1}`, attempt.error);
    }
  }
  return values;
}

export function renderVerboseEntry(event, values) {
  const entry = document.createElement("li");
  const details = document.createElement("details");
  details.className = "agent-row";
  const summary = document.createElement("summary");
  const preview = values[0].value.replace(/\s+/g, " ");
  const shortened = preview.length > 80 ? `${preview.slice(0, 79)}…` : preview;
  summary.textContent = `#${event.sequence} ${event.kind} · ${values[0].label}: ${shortened}`;
  const content = document.createElement("div");
  content.className = "event-detail";
  const list = document.createElement("dl");
  list.className = "verbose-fields";
  for (const { label, value } of values) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    list.append(term, description);
  }
  content.append(list);
  details.append(summary, content);
  entry.append(details);
  return entry;
}

// NetHack's own top-line text carried by an event's observation. Repeats are
// kept because the game repeats messages; whitespace-only text is not a
// message and surrounding whitespace is padding, so both are dropped.
export function gameMessage(event) {
  const observation = event?.payload?.observation;
  const text = typeof observation?.message === "string" ? observation.message.trim() : "";
  if (!text) {
    return null;
  }
  return { sequence: event.sequence, step: observation.step_index ?? null, text };
}

export function renderMessageEntry(message) {
  const entry = document.createElement("li");
  entry.className = "agent-row message-row";
  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = `step ${displayed(message.step)} · #${message.sequence}`;
  const text = document.createElement("span");
  text.className = "message-text";
  text.textContent = message.text;
  entry.append(meta, text);
  return entry;
}
