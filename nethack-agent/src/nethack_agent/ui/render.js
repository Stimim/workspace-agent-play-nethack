// DOM rendering. Every model- or game-provided string is inserted with
// textContent or text nodes; nothing here parses HTML.

const HUNGER = ["satiated", "not hungry", "hungry", "weak", "fainting", "fainted", "starved"];
const ENCUMBRANCE = ["unencumbered", "burdened", "stressed", "strained", "overtaxed", "overloaded"];
const ALIGNMENT = new Map([[-1, "chaotic"], [0, "neutral"], [1, "lawful"]]);

export function setText(element, value) {
  element.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
}

export function setFacts(list, pairs) {
  const fragment = document.createDocumentFragment();
  for (const [label, value] of pairs) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    setText(description, value);
    fragment.append(term, description);
  }
  list.replaceChildren(fragment);
}

export function hexToBytes(hex) {
  const bytes = new Array(Math.floor(hex.length / 2));
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

// Groups each row into spans of equal NetHack color; the player cell gets its
// own highlighted span.
export function renderMap(pre, observation) {
  if (!observation) {
    pre.replaceChildren();
    return;
  }
  const { rows, color_rows: colorRows } = observation.map;
  const { x, y } = observation.player;
  const fragment = document.createDocumentFragment();
  rows.forEach((row, rowIndex) => {
    const cells = Array.from(row);
    const colors = hexToBytes(colorRows[rowIndex] ?? "");
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
      const cellKey = rowIndex === y && columnIndex === x ? "player" : `c${colors[columnIndex] ?? 7}`;
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
    list.replaceChildren();
    return;
  }
  setFacts(list, [
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
    ["St Dx Co", `${strength(player)} ${player.dexterity} ${player.constitution}`],
    ["In Wi Ch", `${player.intelligence} ${player.wisdom} ${player.charisma}`],
    ["Conditions", player.conditions.length ? player.conditions.join(", ") : "none"],
  ]);
}

export function renderInventory(list, inventory) {
  const fragment = document.createDocumentFragment();
  for (const item of inventory ?? []) {
    const entry = document.createElement("li");
    entry.textContent = `${item.letter} - ${item.description}`;
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
    ["Goal", selection.goal],
    ["Skill", `${selection.skill} (${selection.skill_selection})`],
    ["Action", `${action.name} (#${action.index}, command ${action.command})`],
    ["Rationale", selection.rationale],
  ];
  if (selection.stuck_reason) {
    pairs.push(["Stuck", selection.stuck_reason]);
  }
  if (payload.skill_decision) {
    pairs.push([
      "Skill choice",
      `${payload.skill_decision.skill}: ${payload.skill_decision.rationale}`,
    ]);
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
      return `${prefix} goal=${payload.goal} skill=${payload.skill ?? "-"}`;
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
