# 0002: Control API clients

Date: 2026-09-26

## Question

The initial architecture diagram showed a direct browser-to-coordinator edge. During review, this raised two issues: whether the browser bypassed the local API, and whether a coding agent could use the same control surface to run targeted development scenarios.

## Clarification

No external client communicates with the coordinator directly. The local service provides one client-neutral control/status API and WebSocket event stream for:

- the browser UI;
- coding-agent tools;
- future headless CLI and evaluation tooling.

Coding agents need to launch the service, start a validated task/seed configuration, observe structured events, pause or single-step when diagnosing behavior, and stop the run gracefully after collecting evidence. This is a first-milestone requirement, not a browser-only convenience.

The API does not accept arbitrary code or unvalidated NLE actions. Lifecycle commands pass through the coordinator state machine. Graceful stop closes NLE and flushes SQLite and ttyrec metadata before reporting a terminal state.

An online coding agent may orchestrate development scenarios through this loopback API. Such runs are not valid offline evaluation episodes; fixed evaluation suites run without online intervention.
