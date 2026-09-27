import { ApiError, EventStream, findLastSequence, request, runPath } from "./client.js";
import { appendEventLog, resetAgentLogs } from "./event-log.js";
import {

  promptText,
  renderInventory,
  renderMap,
  renderMetrics,
  renderStats,
  setExplainedText,
  setText,
} from "./render.js";
import {
  element,
  initializeView,
  repositionShownTooltip,
  view,
} from "./view.js";

// Attaching to an existing run replays only this many trailing events.
const ATTACH_HISTORY_EVENTS = 50;
const STATUS_REFRESH_DELAY_MS = 250;
const FINISHED_STATES = new Set(["terminal", "stopped", "error"]);


function emptyTotals() {
  return { steps: 0, modelCalls: 0, promptTokens: 0, outputTokens: 0, latencyMs: 0, repairs: 0 };
}

const state = {
  generation: 0,
  runId: null,
  run: null,
  controllable: false,
  goal: null,
  skill: null,
  lastError: null,
  actionNames: new Map(),
  observation: null,
  latestStep: null,
  totals: emptyTotals(),
  stream: null,
  streamState: "idle",
  busy: false,
  renderQueued: false,
  statusTimer: null,
};


function showError(error) {
  view.error.textContent = error instanceof Error ? error.message : String(error);
  view.error.hidden = false;
}

function clearError() {
  view.error.hidden = true;
  view.error.textContent = "";
}

function setActionNames(actions) {
  if (Array.isArray(actions)) {
    state.actionNames = new Map(actions.map((action) => [action.index, action.name]));
  }
}

function setObservation(observation) {
  if (observation && (!state.observation || observation.step_index >= state.observation.step_index)) {
    state.observation = observation;
  }
}

function applyStatus(status) {
  state.run = status.run;
  state.controllable = status.coordinator !== null;
  setActionNames(status.legal_actions);
  if (status.coordinator) {
    state.goal = status.coordinator.current_goal;
    state.skill = status.coordinator.current_skill;
    state.lastError = status.coordinator.last_error ?? status.run.error;
    setObservation(status.coordinator.observation);
  } else {
    state.lastError = status.run.error;
  }
  scheduleRender();
}

function recordMetrics(metrics) {
  if (!metrics) {
    return;
  }
  state.totals.modelCalls += 1;
  state.totals.promptTokens += metrics.prompt_tokens;
  state.totals.outputTokens += metrics.output_tokens;
  state.totals.latencyMs += metrics.latency_ms;
  state.totals.repairs += metrics.repair_attempted ? 1 : 0;
}

function setRunState(runState, outcome) {
  if (state.run) {
    state.run = { ...state.run, state: runState, outcome: outcome ?? state.run.outcome };
  }
}

function handleEvent(generation, event) {
  if (generation !== state.generation) {
    return;
  }
  const payload = event.payload;
  switch (event.kind) {
    case "run_started":
      setActionNames(payload.legal_actions);
      setObservation(payload.observation);
      state.goal = payload.goal;
      state.skill = payload.skill;
      break;
    case "step":
      state.latestStep = event;
      state.totals.steps += 1;
      recordMetrics(payload.skill_metrics);
      recordMetrics(payload.action_metrics);
      state.goal = payload.selection.goal;
      state.skill = payload.selection.skill;
      setObservation(payload.observation);
      if (payload.outcome) {
        setRunState("terminal", payload.outcome);
      }
      break;
    case "run_paused":
      setRunState("paused");
      break;
    case "run_resumed":
      setRunState("running");
      break;
    case "run_stopped":
      setRunState("stopped", "stopped");
      break;
    case "agent_error":
      setRunState(payload.state);
      state.lastError = payload.error;
      break;
    default:
      break;
  }
  appendEventLog(view, event, state.actionNames);
  if (event.kind !== "step" || payload.outcome) {
    scheduleStatusRefresh(generation);
  }
  scheduleRender();
}



function scheduleStatusRefresh(generation) {
  clearTimeout(state.statusTimer);
  state.statusTimer = setTimeout(() => refreshStatus(generation), STATUS_REFRESH_DELAY_MS);
}

async function refreshStatus(generation) {
  if (generation !== state.generation || !state.runId) {
    return;
  }
  try {
    const status = await request("GET", runPath(state.runId));
    if (generation === state.generation) {
      applyStatus(status);
    }
  } catch (error) {
    if (generation === state.generation) {
      showError(error);
    }
  }
}

function setStreamState(generation, text) {
  if (generation === state.generation) {
    state.streamState = text;
    scheduleRender();
  }
}

function closeStream() {
  state.stream?.close();
  state.stream = null;
}

async function attach(runId, { initialStatus = null } = {}) {
  closeStream();
  clearTimeout(state.statusTimer);
  state.generation += 1;
  const generation = state.generation;
  Object.assign(state, {
    runId,
    run: null,
    controllable: false,
    goal: null,
    skill: null,
    lastError: null,
    actionNames: new Map(),
    observation: null,
    latestStep: null,
    totals: emptyTotals(),
    streamState: "loading",
  });
  resetAgentLogs(view);
  view.attachId.value = runId;
  history.replaceState(null, "", `#run=${encodeURIComponent(runId)}`);
  scheduleRender();

  const status = initialStatus ?? (await request("GET", runPath(runId)));
  if (generation !== state.generation) {
    return;
  }
  applyStatus(status);
  let after = -1;
  if (!initialStatus) {
    const last = await findLastSequence(runId);
    after = Math.max(-1, last - ATTACH_HISTORY_EVENTS);
    if (after >= 0 && !status.legal_actions) {
      const first = await request("GET", runPath(runId, "/events?after=-1&limit=1"));
      first.events.forEach((event) => handleEvent(generation, event));
    }
  }
  if (generation !== state.generation) {
    return;
  }
  const stream = new EventStream(runId, after, {
    onEvent: (event) => handleEvent(generation, event),
    // A reconnect may follow a service restart; re-read controllability.
    onReconnect: () => refreshStatus(generation),
    onState: (text) => setStreamState(generation, text),
    onFinished: (reason) => {
      setStreamState(generation, `closed (${reason})`);
      if (generation === state.generation) {
        state.stream = null;
        refreshStatus(generation);
      }
    },
  });
  state.stream = stream;
  stream.start();
}

async function runAction(action) {
  if (state.busy) {
    return;
  }
  state.busy = true;
  scheduleRender();
  try {
    await action();
    clearError();
  } catch (error) {
    showError(error);
  } finally {
    state.busy = false;
    scheduleRender();
  }
}

function readInteger(input, name) {
  const value = Number(input.value);
  if (!input.value.trim() || !Number.isSafeInteger(value)) {
    throw new ApiError(0, `${name} must be an integer`);
  }
  return value;
}

async function startRun() {
  const body = {
    seed: readInteger(view.seed, "seed"),
    max_episode_steps: readInteger(view.maxSteps, "max steps"),
    auto_start: view.autoStart.checked,
  };
  const status = await request("POST", "api/runs", body);
  await attach(status.run.id, { initialStatus: status });
}

async function control(command) {
  const runId = state.runId;
  const generation = state.generation;
  const status = await request("POST", runPath(runId, `/${command}`));
  if (generation === state.generation) {
    applyStatus(status);
  }
}

function scheduleRender() {
  if (!state.renderQueued) {
    state.renderQueued = true;
    requestAnimationFrame(render);
  }
}

function render() {
  state.renderQueued = false;
  const run = state.run;
  const runState = run?.state ?? null;
  setText(view.runId, state.runId ?? "none");
  setText(view.runState, runState && !state.controllable ? `${runState} (not controllable by this service)` : runState);
  view.runState.className = runState ? `state-${runState}` : "";
  setText(view.runOutcome, run?.outcome);
  setText(view.runSeed, run ? `${run.suite_seed} (max ${run.max_episode_steps} steps)` : null);
  setText(view.runModel, run ? `${run.model}; policy ${run.policy_version}` : null);
  setExplainedText(view.runGoal, state.goal);
  setExplainedText(view.runSkill, state.skill);
  setText(view.runError, state.lastError);
  setText(view.streamState, state.streamState);

  const observation = state.observation;
  renderMap(view.map, observation);
  setText(view.mapStep, observation ? `step ${observation.step_index}` : "");
  view.message.textContent = observation?.message || "\u00a0";
  view.prompt.textContent = promptText(observation?.prompt);
  renderStats(view.stats, observation?.player);
  renderInventory(view.inventory, observation?.inventory);
  renderMetrics(view.metrics, state.latestStep, state.totals);

  const live = state.controllable && !state.busy && runState !== null && !FINISHED_STATES.has(runState);
  view.pause.disabled = !(live && runState === "running");
  view.resume.disabled = !(live && runState === "paused");
  view.step.disabled = !(live && runState === "paused");
  view.stop.disabled = !live;
  view.start.disabled = state.busy;
  view.attach.disabled = state.busy;
  repositionShownTooltip();
}


element("start-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction(startRun);
});
element("attach-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const runId = view.attachId.value.trim();
  if (runId) {
    runAction(() => attach(runId));
  }
});
for (const command of ["pause", "resume", "step", "stop"]) {
  view[command].addEventListener("click", () => runAction(() => control(command)));
}
view.error.addEventListener("click", clearError);
initializeView();
const initialRun = new URLSearchParams(location.hash.slice(1)).get("run");
if (initialRun) {
  runAction(() => attach(initialRun));
}
scheduleRender();
