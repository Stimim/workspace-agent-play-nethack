import { installFieldTooltips } from "./render.js";

// Must equal the max-width breakpoint in app.css; its derivation is there.
export const NARROW_AGENT_QUERY = "(max-width: 1520px)";

export const element = (id) => document.getElementById(id);

export const view = {
  seed: element("seed"),
  maxSteps: element("max-steps"),
  autoStart: element("auto-start"),
  start: element("start"),
  attachId: element("attach-id"),
  attach: element("attach"),
  pause: element("pause"),
  resume: element("resume"),
  step: element("step"),
  stop: element("stop"),
  error: element("error"),
  runId: element("run-id"),
  runState: element("run-state"),
  runOutcome: element("run-outcome"),
  runSeed: element("run-seed"),
  runModel: element("run-model"),
  runGoal: element("run-goal"),
  runSkill: element("run-skill"),
  runError: element("run-error"),
  streamState: element("stream-state"),
  map: element("map"),
  mapStep: element("map-step"),
  message: element("message"),
  prompt: element("prompt"),
  stats: element("stats"),
  inventory: element("inventory"),
  metrics: element("metrics"),
  agentToggle: element("agent-toggle"),
  agentClose: element("agent-close"),
  agentColumn: element("agent-column"),
  agentScrim: element("agent-scrim"),
  tabs: Array.from(document.querySelectorAll('[role="tab"]')),
  events: element("events"),
  eventsAutoScroll: element("events-auto-scroll"),
  tools: element("tools"),
  toolsAutoScroll: element("tools-auto-scroll"),
  verbose: element("verbose"),
  verboseAutoScroll: element("verbose-auto-scroll"),
};

const TOOLTIP_GAP_PX = 6;
const TOOLTIP_MARGIN_PX = 8;
const agentMedia = window.matchMedia(NARROW_AGENT_QUERY);
let agentPanelOpen = false;
let activeTooltip = null;

function syncAgentPanel() {
  const narrow = agentMedia.matches;
  const open = !narrow || agentPanelOpen;
  const hiddenFocus = !open && view.agentColumn.contains(document.activeElement);
  view.agentColumn.classList.toggle("is-open", open);
  view.agentColumn.setAttribute("aria-hidden", String(!open));
  view.agentColumn.inert = !open;
  view.agentToggle.setAttribute("aria-expanded", String(open));
  view.agentScrim.hidden = !narrow || !open;
  document.body.classList.toggle("agent-overlay-open", narrow && open);
  if (hiddenFocus) {
    view.agentToggle.focus();
  }
}

function setAgentPanelOpen(open, restoreFocus = false) {
  agentPanelOpen = open;
  syncAgentPanel();
  if (open) {
    view.agentClose.focus();
  } else if (restoreFocus) {
    view.agentToggle.focus();
  }
}

function selectTab(selected, focus = false) {
  for (const tab of view.tabs) {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    const panel = element(tab.getAttribute("aria-controls"));
    panel.hidden = !active;
  }
  if (focus) {
    selected.focus();
  }
  const body = element(selected.getAttribute("aria-controls")).querySelector(".tab-body");
  const autoScroll = element(`${selected.id.slice(4)}-auto-scroll`);
  if (autoScroll.checked) {
    body.scrollTop = body.scrollHeight;
  }
}

function moveTabFocus(event) {
  const current = view.tabs.indexOf(event.currentTarget);
  let next = current;
  if (event.key === "ArrowRight") {
    next = (current + 1) % view.tabs.length;
  } else if (event.key === "ArrowLeft") {
    next = (current - 1 + view.tabs.length) % view.tabs.length;
  } else if (event.key === "Home") {
    next = 0;
  } else if (event.key === "End") {
    next = view.tabs.length - 1;
  } else {
    return;
  }
  event.preventDefault();
  selectTab(view.tabs[next], true);
}

// Tooltip text lives in fixed-position elements so scrollable tab bodies and
// overflow-clipped panels cannot hide it. Coordinates are CSSOM custom
// properties, which the style-src CSP permits (no inline style attributes).
function positionTooltip(wrapper) {
  const trigger = wrapper.querySelector(".tooltip-trigger");
  const content = wrapper.querySelector(".tooltip-content");
  if (!trigger || !content) {
    return;
  }
  const anchor = trigger.getBoundingClientRect();
  const width = content.offsetWidth;
  const height = content.offsetHeight;
  const maxLeft = window.innerWidth - width - TOOLTIP_MARGIN_PX;
  const left = Math.max(TOOLTIP_MARGIN_PX, Math.min(anchor.left, maxLeft));
  const above = anchor.top - height - TOOLTIP_GAP_PX;
  const top = above >= TOOLTIP_MARGIN_PX
    ? above
    : Math.min(anchor.bottom + TOOLTIP_GAP_PX, window.innerHeight - height - TOOLTIP_MARGIN_PX);
  content.style.setProperty("--tooltip-left", `${left}px`);
  content.style.setProperty("--tooltip-top", `${Math.max(TOOLTIP_MARGIN_PX, top)}px`);
}

function showTooltip(event) {
  const wrapper = event.target.closest?.(".tooltip");
  if (wrapper) {
    activeTooltip?.classList.remove("tooltip-dismissed");
    activeTooltip = wrapper;
    wrapper.classList.remove("tooltip-dismissed");
    positionTooltip(wrapper);
  }
}

function repositionActiveTooltip() {
  if (activeTooltip?.isConnected) {
    positionTooltip(activeTooltip);
  }
}

export function repositionShownTooltip() {
  const shown = document.querySelector(".tooltip:hover, .tooltip:focus-within");
  if (shown) {
    activeTooltip = shown;
    positionTooltip(shown);
  }
}

export function initializeView() {
  view.agentToggle.addEventListener("click", () => setAgentPanelOpen(!agentPanelOpen));
  view.agentClose.addEventListener("click", () => setAgentPanelOpen(false, true));
  view.agentScrim.addEventListener("click", () => setAgentPanelOpen(false, true));
  agentMedia.addEventListener("change", syncAgentPanel);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    if (activeTooltip?.isConnected && activeTooltip.matches(":hover, :focus-within")
        && !activeTooltip.classList.contains("tooltip-dismissed")) {
      activeTooltip.classList.add("tooltip-dismissed");
    } else if (agentMedia.matches && agentPanelOpen) {
      setAgentPanelOpen(false, true);
    }
  });
  document.addEventListener("mouseover", showTooltip);
  document.addEventListener("focusin", showTooltip);
  document.addEventListener("scroll", repositionActiveTooltip, true);
  window.addEventListener("resize", repositionActiveTooltip);
  for (const tab of view.tabs) {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", moveTabFocus);
  }
  for (const [log, checkbox] of [
    [view.events, view.eventsAutoScroll],
    [view.tools, view.toolsAutoScroll],
    [view.verbose, view.verboseAutoScroll],
  ]) {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        log.scrollTop = log.scrollHeight;
      }
    });
  }

  installFieldTooltips(document);
  syncAgentPanel();
}
