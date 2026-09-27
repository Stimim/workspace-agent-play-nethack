import {
  deterministicExecution,
  renderEventEntry,
  renderToolEntry,
  renderVerboseEntry,
  verboseDetails,
} from "./render.js";

const MAX_EVENT_LOG_ENTRIES = 300;

function resetLog(log, text) {
  const entry = document.createElement("li");
  entry.className = "empty-state";
  entry.textContent = text;
  log.replaceChildren(entry);
}

export function resetAgentLogs(view) {
  resetLog(view.events, "No events received.");
  resetLog(view.tools, "No deterministic execution evidenced by an event.");
  resetLog(view.verbose, "No unstructured details received.");
}

function appendLogEntry(log, entry, autoScroll) {
  log.querySelector(".empty-state")?.remove();
  log.append(entry);
  while (log.childElementCount > MAX_EVENT_LOG_ENTRIES) {
    log.firstElementChild.remove();
  }
  if (autoScroll.checked) {
    log.scrollTop = log.scrollHeight;
  }
}

export function appendEventLog(view, event, actionNames) {
  if (event.kind === "step") {
    for (const details of view.events.querySelectorAll("[data-decision]")) {
      details.open = false;
    }
  }
  appendLogEntry(
    view.events,
    renderEventEntry(event, actionNames, event.kind === "step"),
    view.eventsAutoScroll,
  );

  const execution = deterministicExecution(event);
  if (execution) {
    appendLogEntry(view.tools, renderToolEntry(execution), view.toolsAutoScroll);
  }

  const verbose = verboseDetails(event);
  if (verbose.length) {
    appendLogEntry(
      view.verbose,
      renderVerboseEntry(event, verbose),
      view.verboseAutoScroll,
    );
  }
}
