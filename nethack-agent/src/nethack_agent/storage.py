from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from nethack_agent.decision import RunOutcome, RunState
from nethack_agent.environment import ScenarioConfig, SeedSet

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    environment TEXT NOT NULL,
    character TEXT NOT NULL,
    suite_seed INTEGER NOT NULL,
    core_seed INTEGER NOT NULL,
    display_seed INTEGER NOT NULL,
    level_seed INTEGER NOT NULL,
    max_episode_steps INTEGER NOT NULL,
    model TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    knowledge_version TEXT NOT NULL,
    nle_version TEXT NOT NULL,
    ollama_version TEXT,
    ttyrec_path TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (run_id, sequence)
);
CREATE INDEX IF NOT EXISTS events_run_sequence ON events(run_id, sequence);
"""
DEFAULT_EVENT_PAGE_LIMIT: Final = 100
MAX_EVENT_PAGE_LIMIT: Final = 1_000


class RunNotFoundError(KeyError):
    pass


class RunStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    created_at: str
    kind: str
    payload: dict[str, Any]

    def to_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "created_at": self.created_at,
            "kind": self.kind,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[RunEvent, ...]
    next_after: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    created_at: str
    updated_at: str
    state: str
    outcome: str | None
    environment: str
    character: str
    suite_seed: int
    core_seed: int
    display_seed: int
    level_seed: int
    max_episode_steps: int
    model: str
    policy_version: str
    knowledge_version: str
    nle_version: str
    ollama_version: str | None
    ttyrec_path: str | None
    error: str | None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    def create_run(
        self,
        config: ScenarioConfig,
        seeds: SeedSet,
        *,
        environment: str,
        character: str,
        model: str,
        policy_version: str,
        knowledge_version: str,
        nle_version: str,
        run_id: str | None = None,
    ) -> RunRecord:
        run_id = run_id or str(uuid.uuid4())
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, created_at, updated_at, state, environment, character,
                    suite_seed, core_seed, display_seed, level_seed,
                    max_episode_steps, model, policy_version, knowledge_version,
                    nle_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    now,
                    RunState.IDLE.value,
                    environment,
                    character,
                    config.seed,
                    seeds.core,
                    seeds.display,
                    seeds.level,
                    config.max_episode_steps,
                    model,
                    policy_version,
                    knowledge_version,
                    nle_version,
                ),
            )
            record = self._get_run(connection, run_id)
        return record

    def update_run(
        self,
        run_id: str,
        *,
        state: RunState,
        outcome: RunOutcome | None = None,
        error: str | None = None,
        ollama_version: str | None = None,
        ttyrec_path: str | None = None,
        expected_states: frozenset[RunState] | None = None,
    ) -> RunRecord:
        with self._connection() as connection:
            self._update_run(
                connection,
                run_id,
                state=state,
                outcome=outcome,
                error=error,
                ollama_version=ollama_version,
                ttyrec_path=ttyrec_path,
                expected_states=expected_states,
            )
            record = self._get_run(connection, run_id)
        return record

    def update_run_and_append_event(
        self,
        run_id: str,
        *,
        state: RunState,
        kind: str,
        payload: dict[str, object],
        outcome: RunOutcome | None = None,
        error: str | None = None,
        ollama_version: str | None = None,
        ttyrec_path: str | None = None,
        expected_states: frozenset[RunState] | None = None,
    ) -> tuple[RunRecord, RunEvent]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._update_run(
                connection,
                run_id,
                state=state,
                outcome=outcome,
                error=error,
                ollama_version=ollama_version,
                ttyrec_path=ttyrec_path,
                expected_states=expected_states,
            )
            event = self._append_event(connection, run_id, kind, payload)
            record = self._get_run(connection, run_id)
        return record, event

    def append_event(
        self, run_id: str, kind: str, payload: dict[str, object]
    ) -> RunEvent:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = self._append_event(connection, run_id, kind, payload)
        return event

    def get_run(self, run_id: str) -> RunRecord:
        with self._connection() as connection:
            return self._get_run(connection, run_id)

    def events_after(
        self,
        run_id: str,
        sequence: int = -1,
        *,
        limit: int = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> tuple[RunEvent, ...]:
        return self.event_page(run_id, sequence, limit=limit).events

    def event_page(
        self,
        run_id: str,
        sequence: int = -1,
        *,
        limit: int = DEFAULT_EVENT_PAGE_LIMIT,
    ) -> EventPage:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("event page limit must be an integer")
        if not 1 <= limit <= MAX_EVENT_PAGE_LIMIT:
            raise ValueError(
                f"event page limit must be between 1 and {MAX_EVENT_PAGE_LIMIT}"
            )
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM runs WHERE id = ?", (run_id,)
                ).fetchone()
                is None
            ):
                raise RunNotFoundError(run_id)
            cursor = connection.execute(
                """
                SELECT sequence, created_at, kind, payload_json
                FROM events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (run_id, sequence, limit + 1),
            )
            rows = cursor.fetchmany(limit + 1)
        has_more = len(rows) > limit
        events = tuple(self._event_from_row(row) for row in rows[:limit])
        next_after = events[-1].sequence if events else sequence
        return EventPage(events, next_after, has_more)

    def _update_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        state: RunState,
        outcome: RunOutcome | None,
        error: str | None,
        ollama_version: str | None,
        ttyrec_path: str | None,
        expected_states: frozenset[RunState] | None,
    ) -> None:
        parameters: list[object] = [
            _now(),
            state.value,
            outcome.value if outcome else None,
            error,
            ollama_version,
            ttyrec_path,
            run_id,
        ]
        condition = ""
        if expected_states:
            values = sorted(item.value for item in expected_states)
            condition = f" AND state IN ({','.join('?' for _ in values)})"
            parameters.extend(values)
        cursor = connection.execute(
            f"""
            UPDATE runs
            SET updated_at = ?, state = ?, outcome = ?, error = ?,
                ollama_version = COALESCE(?, ollama_version),
                ttyrec_path = COALESCE(?, ttyrec_path)
            WHERE id = ?{condition}
            """,
            parameters,
        )
        if cursor.rowcount == 1:
            return
        row = connection.execute(
            "SELECT state FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        raise RunStateConflictError(
            f"run {run_id} is {row['state']}, expected "
            f"{', '.join(sorted(item.value for item in expected_states or ()))}"
        )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        kind: str,
        payload: dict[str, object],
    ) -> RunEvent:
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        created_at = _now()
        exists = connection.execute(
            "SELECT 1 FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if exists is None:
            raise RunNotFoundError(run_id)
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        sequence = int(row[0])
        connection.execute(
            """
            INSERT INTO events (run_id, sequence, created_at, kind, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, sequence, created_at, kind, serialized),
        )
        return RunEvent(sequence, created_at, kind, json.loads(serialized))

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> RunEvent:
        return RunEvent(
            sequence=int(row["sequence"]),
            created_at=str(row["created_at"]),
            kind=str(row["kind"]),
            payload=json.loads(row["payload_json"]),
        )

    @staticmethod
    def _get_run(connection: sqlite3.Connection, run_id: str) -> RunRecord:
        row = connection.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return RunRecord(**dict(row))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _now() -> str:
    return datetime.now(UTC).isoformat()
