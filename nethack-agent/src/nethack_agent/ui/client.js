// HTTP and WebSocket access to the local control API. All URLs are relative to
// the page so the UI works on any loopback host and port.

const STREAM_PAGE_LIMIT = 500;
const MAX_RECONNECT_DELAY_MS = 10_000;

export class ApiError extends Error {
  constructor(status, detail) {
    super(status ? `HTTP ${status}: ${detail}` : detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function runPath(runId, suffix = "") {
  return `api/runs/${encodeURIComponent(runId)}${suffix}`;
}

export function formatDetail(payload, fallback) {
  const detail = payload !== null && typeof payload === "object" ? payload.detail : undefined;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const location = Array.isArray(item?.loc) ? item.loc.join(".") : "";
        const message = typeof item?.msg === "string" ? item.msg : JSON.stringify(item);
        return location ? `${location}: ${message}` : message;
      })
      .join("; ");
  }
  return fallback || "request failed";
}

export async function request(method, path, body) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(new URL(path, document.baseURI), init);
  } catch (error) {
    throw new ApiError(0, `network error: ${error.message}`);
  }
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, formatDetail(payload, text || response.statusText));
  }
  return payload;
}

async function eventExists(runId, sequence) {
  const page = await request("GET", runPath(runId, `/events?after=${sequence - 1}&limit=1`));
  return Array.isArray(page?.events) && page.events.length > 0;
}

// Sequences are contiguous from 0, so the newest sequence can be located with
// O(log n) single-event page requests instead of downloading the history.
export async function findLastSequence(runId) {
  if (!(await eventExists(runId, 0))) {
    return -1;
  }
  let present = 0;
  let absent = 1;
  while (await eventExists(runId, absent)) {
    present = absent;
    absent *= 2;
  }
  while (absent - present > 1) {
    const middle = Math.floor((present + absent) / 2);
    if (await eventExists(runId, middle)) {
      present = middle;
    } else {
      absent = middle;
    }
  }
  return present;
}

export function eventStreamUrl(runId, after) {
  const url = new URL(runPath(runId, "/events/ws"), document.baseURI);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("after", String(after));
  url.searchParams.set("limit", String(STREAM_PAGE_LIMIT));
  return url;
}

// Follows one run's event stream. Reconnects from the last delivered sequence
// after abnormal closure. The server closes with 1000 once the run is terminal,
// stopped, or error; 4404 means the run is unknown. Neither reconnects.
export class EventStream {
  constructor(runId, after, { onEvent, onReconnect, onState, onFinished }) {
    this.runId = runId;
    this.after = after;
    this.onEvent = onEvent;
    this.onReconnect = onReconnect;
    this.onState = onState;
    this.onFinished = onFinished;
    this.socket = null;
    this.closed = false;
    this.attempts = 0;
    this.timer = null;
  }

  start() {
    this.connect();
  }

  connect() {
    if (this.closed) {
      return;
    }
    this.onState(this.attempts ? `reconnecting after #${this.after}` : "connecting");
    const socket = new WebSocket(eventStreamUrl(this.runId, this.after));
    this.socket = socket;
    socket.addEventListener("open", () => {
      if (socket === this.socket && !this.closed) {
        const reconnected = this.attempts > 0;
        this.attempts = 0;
        this.onState("live");
        if (reconnected) {
          this.onReconnect();
        }
      }
    });
    socket.addEventListener("message", (message) => {
      if (socket !== this.socket || this.closed) {
        return;
      }
      let event;
      try {
        event = JSON.parse(message.data);
      } catch {
        this.onState("received malformed event");
        return;
      }
      if (!Number.isInteger(event?.sequence) || event.sequence <= this.after) {
        return;
      }
      this.after = event.sequence;
      this.onEvent(event);
    });
    socket.addEventListener("close", (close) => {
      if (socket !== this.socket || this.closed) {
        return;
      }
      this.socket = null;
      if (close.code === 1000) {
        this.closed = true;
        this.onFinished("complete");
        return;
      }
      if (close.code === 4404) {
        this.closed = true;
        this.onFinished("run not found");
        return;
      }
      const delay = Math.min(MAX_RECONNECT_DELAY_MS, 500 * 2 ** this.attempts);
      this.attempts += 1;
      this.onState(`disconnected (code ${close.code}); retrying in ${Math.round(delay / 100) / 10}s`);
      this.timer = setTimeout(() => this.connect(), delay);
    });
  }

  close() {
    this.closed = true;
    clearTimeout(this.timer);
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState <= WebSocket.OPEN) {
      socket.close(1000);
    }
  }
}
