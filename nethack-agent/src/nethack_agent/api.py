from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager, suppress
from importlib.resources import files
from typing import Annotated, Final

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from nethack_agent.coordinator import (
    ActionGateError,
    CoordinatorError,
    CoordinatorLifecycleError,
)
from nethack_agent.model import DecisionFailure
from nethack_agent.run_manager import RunControlError, RunManager
from nethack_agent.storage import (
    DEFAULT_EVENT_PAGE_LIMIT,
    MAX_EVENT_PAGE_LIMIT,
    RunNotFoundError,
)

_TERMINAL_STATES = {"terminal", "stopped", "error"}
_UI_ASSETS: Final = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "client.js": "text/javascript; charset=utf-8",
    "render.js": "text/javascript; charset=utf-8",
}
UI_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
_UI_HEADERS: Final = {
    "Content-Security-Policy": UI_CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: Annotated[StrictInt, Field(ge=1, le=sys.maxsize)]
    max_episode_steps: Annotated[StrictInt, Field(ge=1, le=100_000)] = 5_000
    auto_start: StrictBool = False


def create_app(manager: RunManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        try:
            yield
        finally:
            await asyncio.to_thread(manager.close)

    app = FastAPI(title="NetHack Agent", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(_, error: RunNotFoundError):  # type: ignore[no-untyped-def]
        return _error_response(404, f"run not found: {error.args[0]}")

    @app.exception_handler(RunControlError)
    @app.exception_handler(CoordinatorLifecycleError)
    async def run_conflict(_, error: Exception):  # type: ignore[no-untyped-def]
        return _error_response(409, str(error))

    @app.exception_handler(ActionGateError)
    @app.exception_handler(DecisionFailure)
    async def model_unavailable(_, error: Exception):  # type: ignore[no-untyped-def]
        return _error_response(503, str(error))

    @app.exception_handler(CoordinatorError)
    async def coordinator_failure(_, error: Exception):  # type: ignore[no-untyped-def]
        return _error_response(500, str(error))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def ui_index() -> Response:
        return _ui_asset_response("index.html")

    @app.get("/ui/{name}", include_in_schema=False)
    def ui_asset(name: str) -> Response:
        if name not in _UI_ASSETS:
            raise HTTPException(status_code=404, detail="asset not found")
        return _ui_asset_response(name)

    @app.post("/api/runs", status_code=201)
    def create_run(request: CreateRunRequest) -> dict[str, object]:
        try:
            record = manager.create_run(
                seed=request.seed,
                max_episode_steps=request.max_episode_steps,
                auto_start=request.auto_start,
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return manager.status(record.id)

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, object]:
        return manager.status(run_id)

    @app.get("/api/runs/{run_id}/events")
    def run_events(
        run_id: str,
        after: Annotated[int, Query(ge=-1)] = -1,
        limit: Annotated[
            int, Query(ge=1, le=MAX_EVENT_PAGE_LIMIT)
        ] = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> dict[str, object]:
        page = manager.event_page(run_id, after, limit=limit)
        return {
            "events": [event.to_json() for event in page.events],
            "next_after": page.next_after,
            "has_more": page.has_more,
            "limit": limit,
        }

    @app.post("/api/runs/{run_id}/pause")
    def pause(run_id: str) -> dict[str, object]:
        manager.pause(run_id)
        return manager.status(run_id)

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, object]:
        manager.resume(run_id)
        return manager.status(run_id)

    @app.post("/api/runs/{run_id}/step")
    def step(run_id: str) -> dict[str, object]:
        manager.step(run_id)
        return manager.status(run_id)

    @app.post("/api/runs/{run_id}/stop")
    def stop(run_id: str) -> dict[str, object]:
        manager.stop(run_id)
        return manager.status(run_id)

    @app.websocket("/api/runs/{run_id}/events/ws")
    async def event_stream(
        websocket: WebSocket,
        run_id: str,
        after: int = -1,
        limit: Annotated[
            int, Query(ge=1, le=MAX_EVENT_PAGE_LIMIT)
        ] = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> None:
        try:
            await asyncio.to_thread(manager.status, run_id)
        except RunNotFoundError:
            await websocket.close(code=4404, reason="run not found")
            return
        await websocket.accept()
        sequence = after
        disconnect_task = asyncio.create_task(_wait_for_disconnect(websocket))
        try:
            while not disconnect_task.done():
                page = await asyncio.to_thread(
                    manager.event_page, run_id, sequence, limit=limit
                )
                for event in page.events:
                    await websocket.send_json(event.to_json())
                sequence = page.next_after
                if page.has_more:
                    continue
                status = await asyncio.to_thread(manager.status, run_id)
                state = status["run"]["state"]  # type: ignore[index]
                if state in _TERMINAL_STATES:
                    await websocket.close(code=1000)
                    return
                with suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(disconnect_task), timeout=0.2)
        except WebSocketDisconnect:
            return
        finally:
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task

    return app


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


def _error_response(status_code: int, detail: str):  # type: ignore[no-untyped-def]
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


def _ui_asset_response(name: str) -> Response:
    content = files("nethack_agent").joinpath("ui", name).read_bytes()
    return Response(content, media_type=_UI_ASSETS[name], headers=_UI_HEADERS)
