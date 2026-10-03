from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Self

from nethack_agent.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    number_value,
    object_value,
    optional_enum_value,
    string_value,
)
from nethack_agent.decision import (
    EAT_ACTION_NAME,
    ESC_COMMAND,
    LEVEL_CHANGE_ACTIONS,
    PRAY_ACTION_NAME,
    YES_COMMAND,
    ActionDecision,
    ActionSelection,
    ActionSelectionSource,
    CorpseOutcome,
    CorpseOutcomeKind,
    DecisionMetrics,
    PrayerOutcome,
    PromptKind,
    PromptPermit,
    RunOutcome,
    RunState,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    classify_corpse_outcome,
    classify_prayer_outcome,
    confirmation_answer_error,
    confirmation_prompt_kind,
    level_change_selection_error,
    survival_action_selection_error,
)
from nethack_agent.environment import LegalAction
from nethack_agent.model import DecisionAttemptDiagnostic, DecisionFailure
from nethack_agent.observation import ProjectedObservation
from nethack_agent.traversal import GOAL_TYPES, Goal, goal_from_json


class EventKind(Enum):
    RUN_STARTED = "run_started"
    RUN_RESUMED = "run_resumed"
    RUN_PAUSED = "run_paused"
    STEP = "step"
    AGENT_ERROR = "agent_error"
    RUN_STOPPED = "run_stopped"


class ErrorPhase(Enum):
    CREATE_RUN = "create_run"
    ADVANCE = "advance"


@dataclass(frozen=True, slots=True)
class DecisionFailureTrace:
    message: str
    attempts: tuple[DecisionAttemptDiagnostic, ...]
    metrics: DecisionMetrics

    def __post_init__(self) -> None:
        string_value(self.message, "decision failure message", minimum=1, maximum=8192)
        if not all(
            isinstance(attempt, DecisionAttemptDiagnostic) for attempt in self.attempts
        ):
            raise TypeError(
                "decision failure attempts must be DecisionAttemptDiagnostic values"
            )
        if not isinstance(self.metrics, DecisionMetrics):
            raise TypeError("decision failure metrics must be DecisionMetrics")

    @classmethod
    def from_error(cls, error: DecisionFailure) -> Self:
        return cls(str(error), error.attempts, error.metrics)

    def to_json(self) -> dict[str, object]:
        return {
            "message": self.message,
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "metrics": self.metrics.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value, "decision failure", {"message", "attempts", "metrics"}
        )
        return cls(
            message=string_value(
                payload["message"],
                "decision failure message",
                minimum=1,
                maximum=8192,
            ),
            attempts=tuple(
                _attempt_from_json(item)
                for item in array_value(
                    payload["attempts"], "decision failure attempts"
                )
            ),
            metrics=DecisionMetrics.from_json(payload["metrics"]),
        )


@dataclass(frozen=True, slots=True)
class RunStartedPayload:
    observation: ProjectedObservation
    legal_actions: tuple[LegalAction, ...]
    goal: Goal
    skill: Skill | None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, ProjectedObservation):
            raise TypeError("run_started observation must be ProjectedObservation")
        if not all(isinstance(action, LegalAction) for action in self.legal_actions):
            raise TypeError("run_started legal_actions must contain LegalAction values")
        if not self.legal_actions:
            raise ContractError("run_started legal_actions must not be empty")
        indices = [action.index for action in self.legal_actions]
        if indices != list(range(len(indices))):
            raise ContractError("run_started legal_actions must be contiguous")
        if not isinstance(self.goal, GOAL_TYPES):
            raise TypeError("run_started goal must be a typed Goal")
        if self.skill is not None and not isinstance(self.skill, Skill):
            raise TypeError("run_started skill must be a Skill or None")

    def to_json(self) -> dict[str, object]:
        return {
            "observation": self.observation.to_json(),
            "legal_actions": [action.to_json() for action in self.legal_actions],
            "goal": self.goal.to_json(),
            "skill": self.skill.value if self.skill else None,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "run_started payload",
            {"observation", "legal_actions", "goal", "skill"},
        )
        return cls(
            observation=ProjectedObservation.from_json(payload["observation"]),
            legal_actions=tuple(
                LegalAction.from_json(item)
                for item in array_value(
                    payload["legal_actions"], "run_started legal_actions"
                )
            ),
            goal=goal_from_json(payload["goal"], "run_started goal"),
            skill=optional_enum_value(payload["skill"], "run_started skill", Skill),
        )


@dataclass(frozen=True, slots=True)
class RunResumedPayload:
    def to_json(self) -> dict[str, object]:
        return {}

    @classmethod
    def from_json(cls, value: object) -> Self:
        object_value(value, "run_resumed payload", set())
        return cls()


@dataclass(frozen=True, slots=True)
class RunPausedPayload:
    def to_json(self) -> dict[str, object]:
        return {}

    @classmethod
    def from_json(cls, value: object) -> Self:
        object_value(value, "run_paused payload", set())
        return cls()


@dataclass(frozen=True, slots=True)
class StepPayload:
    selection: ActionSelection
    skill_decision: SkillDecision | None
    skill_metrics: DecisionMetrics | None
    action_decision: ActionDecision | None
    action_metrics: DecisionMetrics | None
    action: LegalAction
    reward: float
    terminated: bool
    truncated: bool
    end_status: int
    is_ascended: bool
    outcome: RunOutcome | None
    observation: ProjectedObservation

    def __post_init__(self) -> None:
        if not isinstance(self.selection, ActionSelection):
            raise TypeError("step selection must be an ActionSelection")
        if not isinstance(self.action, LegalAction):
            raise TypeError("step action must be a LegalAction")
        if not isinstance(self.observation, ProjectedObservation):
            raise TypeError("step observation must be a ProjectedObservation")
        if self.skill_decision is not None and not isinstance(
            self.skill_decision, SkillDecision
        ):
            raise TypeError("step skill_decision must be a SkillDecision or None")
        if self.skill_metrics is not None and not isinstance(
            self.skill_metrics, DecisionMetrics
        ):
            raise TypeError("step skill_metrics must be DecisionMetrics or None")
        if self.action_decision is not None and not isinstance(
            self.action_decision, ActionDecision
        ):
            raise TypeError("step action_decision must be ActionDecision or None")
        if self.action_metrics is not None and not isinstance(
            self.action_metrics, DecisionMetrics
        ):
            raise TypeError("step action_metrics must be DecisionMetrics or None")
        if self.outcome is not None and not isinstance(self.outcome, RunOutcome):
            raise TypeError("step outcome must be a RunOutcome or None")
        if self.selection.action_index != self.action.index:
            raise ContractError("step selection and action indices must match")
        if self.skill_decision is not None and (
            self.skill_decision.goal != self.selection.goal
            or (
                self.selection.skill_selection is SkillSelectionSource.MODEL
                and self.skill_decision.skill is not self.selection.skill
            )
        ):
            raise ContractError("step skill decision does not match selection")
        if (self.skill_decision is None) != (self.skill_metrics is None):
            raise ContractError("step skill decision and metrics must appear together")
        fallback = self.selection.source is ActionSelectionSource.MODEL_FALLBACK
        if fallback != (self.action_decision is not None):
            raise ContractError("model fallback steps require an action decision")
        if fallback != (self.action_metrics is not None):
            raise ContractError("model fallback steps require action metrics")
        if (
            self.action_decision is not None
            and self.action_decision.action_index != self.action.index
        ):
            raise ContractError("step action decision and action indices must match")
        intent = self.selection.intent
        if intent is not None:
            rows = self.observation.map.rows
            if any(
                cell.y >= len(rows) or cell.x >= len(rows[0]) for cell in intent.cells()
            ):
                raise ContractError("step intent cell is outside the observation map")
        survival_error = survival_action_selection_error(
            self.action.name, self.selection
        )
        prayer = None if intent is None else intent.prayer
        if self.action.name == PRAY_ACTION_NAME:
            if (
                survival_error is None
                and confirmation_prompt_kind(
                    self.observation.message,
                    single_choice=self.observation.prompt.single_character_choice,
                )
                is not PromptKind.PRAYER_CONFIRMATION
            ):
                survival_error = "PRAY must produce its exact confirmation prompt"
        elif (
            self.action.command == YES_COMMAND
            and self.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and self.selection.skill is Skill.PRAYER
        ):
            if survival_error is None:
                survival_error = confirmation_answer_error(
                    self.action.command,
                    self.selection,
                    prompt_active=True,
                    prompt_kind=PromptKind.PRAYER_CONFIRMATION,
                    permit=PromptPermit(YES_COMMAND, PromptKind.PRAYER_CONFIRMATION),
                )
            if survival_error is None:
                if self.terminated or self.truncated:
                    if prayer is None or prayer.outcome is not None:
                        survival_error = (
                            "terminal prayer yes cannot claim an observed outcome"
                        )
                else:
                    kind = classify_prayer_outcome(
                        self.observation.player.hunger,
                        self.observation.message,
                    )
                    if (
                        self.observation.player.dungeon_level < 1
                        or kind is None
                        or prayer is None
                        or prayer.outcome
                        != PrayerOutcome(
                            self.observation.player.turn,
                            self.observation.player.hunger,
                            self.observation.message,
                            kind,
                        )
                    ):
                        survival_error = (
                            "prayer yes requires the matching observed outcome"
                        )
        elif (
            self.action.command == YES_COMMAND
            and self.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and self.selection.skill is Skill.CORPSE
        ):
            corpse = None if intent is None else intent.corpse
            if survival_error is None:
                survival_error = confirmation_answer_error(
                    self.action.command,
                    self.selection,
                    prompt_active=True,
                    prompt_kind=PromptKind.CORPSE_CONFIRMATION,
                    permit=PromptPermit(YES_COMMAND, PromptKind.CORPSE_CONFIRMATION),
                )
            if survival_error is None:
                if self.terminated or self.truncated:
                    if corpse is None or corpse.outcome is not None:
                        survival_error = (
                            "terminal corpse yes cannot claim an observed outcome"
                        )
                else:
                    kind = classify_corpse_outcome(
                        corpse.name, self.observation.message
                    )
                    if self.observation.player.dungeon_level < 1 or corpse.outcome != (
                        None
                        if kind is None
                        else CorpseOutcome(
                            kind,
                            self.observation.player.turn,
                            self.observation.player.hunger,
                            self.observation.message,
                        )
                    ):
                        survival_error = (
                            "corpse yes requires the matching observed outcome"
                        )
        elif (
            intent is not None
            and intent.corpse is not None
            and self.selection.skill is Skill.CORPSE
            and self.action.name != EAT_ACTION_NAME
        ):
            corpse = intent.corpse
            if self.action.name == "MiscDirection.WAIT":
                kind = (
                    None
                    if self.terminated or self.truncated
                    else classify_corpse_outcome(corpse.name, self.observation.message)
                )
                if (
                    self.selection.source
                    is not ActionSelectionSource.DETERMINISTIC_SKILL
                    or corpse.outcome
                    != (
                        None
                        if kind is None
                        else CorpseOutcome(
                            kind,
                            self.observation.player.turn,
                            self.observation.player.hunger,
                            self.observation.message,
                        )
                    )
                ):
                    survival_error = "meal continuation requires its observed outcome"
            elif self.action.command in (ord("n"), ESC_COMMAND):
                expected = (
                    None
                    if self.terminated or self.truncated
                    else CorpseOutcome(
                        CorpseOutcomeKind.DECLINED,
                        self.observation.player.turn,
                        self.observation.player.hunger,
                        self.observation.message,
                    )
                )
                if (
                    self.selection.source
                    is not ActionSelectionSource.DETERMINISTIC_PROMPT
                    or corpse.outcome != expected
                ):
                    survival_error = (
                        "corpse decline requires the matching observed outcome"
                    )
            elif (
                self.selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
                or corpse.outcome is not None
            ):
                survival_error = (
                    "corpse outcome requires its confirmation or meal continuation"
                )
        if (
            prayer is not None
            and self.action.name != PRAY_ACTION_NAME
            and not (
                self.action.command == YES_COMMAND
                and self.selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
                and self.selection.skill is Skill.PRAYER
            )
        ):
            survival_error = "prayer evidence requires PRAY or its confirmation answer"
        if survival_error is not None:
            raise ContractError(f"step survival action is invalid: {survival_error}")
        direction = LEVEL_CHANGE_ACTIONS.get(self.action.name)
        if direction is not None:
            error = level_change_selection_error(direction, self.selection)
            if error is not None:
                raise ContractError(f"step level change is invalid: {error}")
        reward = number_value(self.reward, "step reward")
        object.__setattr__(self, "reward", reward)
        boolean_value(self.terminated, "step terminated")
        boolean_value(self.truncated, "step truncated")
        integer_value(self.end_status, "step end_status")
        boolean_value(self.is_ascended, "step is_ascended")
        nle_ended = self.terminated or self.truncated
        if self.outcome is None and nle_ended:
            raise ContractError("terminal step must include an outcome")
        if self.outcome is RunOutcome.OBJECTIVE_COMPLETE:
            if nle_ended:
                raise ContractError(
                    "an objective completes only while NLE's episode continues"
                )
        elif self.outcome is not None and not nle_ended:
            raise ContractError("nonterminal step must not include an outcome")

    def to_json(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_json(),
            "skill_decision": (
                self.skill_decision.to_json() if self.skill_decision else None
            ),
            "skill_metrics": (
                self.skill_metrics.to_json() if self.skill_metrics else None
            ),
            "action_decision": (
                self.action_decision.to_json() if self.action_decision else None
            ),
            "action_metrics": (
                self.action_metrics.to_json() if self.action_metrics else None
            ),
            "action": self.action.to_json(),
            "reward": self.reward,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "end_status": self.end_status,
            "is_ascended": self.is_ascended,
            "outcome": self.outcome.value if self.outcome else None,
            "observation": self.observation.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "step payload",
            {
                "selection",
                "skill_decision",
                "skill_metrics",
                "action_decision",
                "action_metrics",
                "action",
                "reward",
                "terminated",
                "truncated",
                "end_status",
                "is_ascended",
                "outcome",
                "observation",
            },
        )
        return cls(
            selection=ActionSelection.from_json(payload["selection"]),
            skill_decision=(
                None
                if payload["skill_decision"] is None
                else SkillDecision.from_json(payload["skill_decision"])
            ),
            skill_metrics=(
                None
                if payload["skill_metrics"] is None
                else DecisionMetrics.from_json(payload["skill_metrics"])
            ),
            action_decision=(
                None
                if payload["action_decision"] is None
                else ActionDecision.from_json(payload["action_decision"])
            ),
            action_metrics=(
                None
                if payload["action_metrics"] is None
                else DecisionMetrics.from_json(payload["action_metrics"])
            ),
            action=LegalAction.from_json(payload["action"]),
            reward=number_value(payload["reward"], "step reward"),
            terminated=boolean_value(payload["terminated"], "step terminated"),
            truncated=boolean_value(payload["truncated"], "step truncated"),
            end_status=integer_value(payload["end_status"], "step end_status"),
            is_ascended=boolean_value(payload["is_ascended"], "step is_ascended"),
            outcome=optional_enum_value(payload["outcome"], "step outcome", RunOutcome),
            observation=ProjectedObservation.from_json(payload["observation"]),
        )


@dataclass(frozen=True, slots=True)
class AgentErrorPayload:
    error: str
    state: RunState
    phase: ErrorPhase
    decision_failure: DecisionFailureTrace | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, RunState):
            raise TypeError("agent error state must be a RunState")
        if not isinstance(self.phase, ErrorPhase):
            raise TypeError("agent error phase must be an ErrorPhase")
        if self.decision_failure is not None and not isinstance(
            self.decision_failure, DecisionFailureTrace
        ):
            raise TypeError(
                "agent error decision_failure must be a DecisionFailureTrace or None"
            )
        string_value(self.error, "agent error", minimum=1, maximum=8192)

    def to_json(self) -> dict[str, object]:
        return {
            "error": self.error,
            "state": self.state.value,
            "phase": self.phase.value,
            "decision_failure": (
                self.decision_failure.to_json() if self.decision_failure else None
            ),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "agent_error payload",
            {"error", "state", "phase", "decision_failure"},
        )
        return cls(
            error=string_value(
                payload["error"], "agent error", minimum=1, maximum=8192
            ),
            state=enum_value(payload["state"], "agent error state", RunState),
            phase=enum_value(payload["phase"], "agent error phase", ErrorPhase),
            decision_failure=(
                None
                if payload["decision_failure"] is None
                else DecisionFailureTrace.from_json(payload["decision_failure"])
            ),
        )


@dataclass(frozen=True, slots=True)
class RunStoppedPayload:
    previous_state: RunState

    def __post_init__(self) -> None:
        if not isinstance(self.previous_state, RunState):
            raise TypeError("run_stopped previous_state must be a RunState")

    def to_json(self) -> dict[str, object]:
        return {"previous_state": self.previous_state.value}

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "run_stopped payload", {"previous_state"})
        return cls(
            previous_state=enum_value(
                payload["previous_state"], "run_stopped previous_state", RunState
            )
        )


type EventPayload = (
    RunStartedPayload
    | RunResumedPayload
    | RunPausedPayload
    | StepPayload
    | AgentErrorPayload
    | RunStoppedPayload
)

_PAYLOAD_TYPES: dict[EventKind, type[EventPayload]] = {
    EventKind.RUN_STARTED: RunStartedPayload,
    EventKind.RUN_RESUMED: RunResumedPayload,
    EventKind.RUN_PAUSED: RunPausedPayload,
    EventKind.STEP: StepPayload,
    EventKind.AGENT_ERROR: AgentErrorPayload,
    EventKind.RUN_STOPPED: RunStoppedPayload,
}


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    created_at: str
    kind: EventKind
    payload: EventPayload

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            raise TypeError("event kind must be an EventKind")
        integer_value(self.sequence, "event sequence", minimum=0)
        string_value(self.created_at, "event created_at", minimum=1, maximum=100)
        if event_kind(self.payload) is not self.kind:
            raise ContractError("event kind does not match its payload variant")

    def to_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "created_at": self.created_at,
            "kind": self.kind.value,
            "payload": self.payload.to_json(),
        }


def event_kind(payload: EventPayload) -> EventKind:
    for kind, payload_type in _PAYLOAD_TYPES.items():
        if isinstance(payload, payload_type):
            return kind
    raise TypeError(f"unsupported event payload type {type(payload).__name__}")


def event_payload_from_json(kind: EventKind, value: object) -> EventPayload:
    payload_type = _PAYLOAD_TYPES[kind]
    return payload_type.from_json(value)


def _attempt_from_json(value: object) -> DecisionAttemptDiagnostic:
    payload = object_value(
        value,
        "decision attempt",
        {
            "error",
            "raw_response",
            "prompt_tokens",
            "output_tokens",
            "elapsed_ms",
            "returned_duration_ms",
        },
    )
    raw_response = payload["raw_response"]
    returned_duration = payload["returned_duration_ms"]
    return DecisionAttemptDiagnostic(
        error=string_value(
            payload["error"], "decision attempt error", minimum=1, maximum=8192
        ),
        raw_response=(
            None
            if raw_response is None
            else string_value(raw_response, "decision raw_response", maximum=65536)
        ),
        prompt_tokens=integer_value(
            payload["prompt_tokens"], "decision prompt_tokens", minimum=0
        ),
        output_tokens=integer_value(
            payload["output_tokens"], "decision output_tokens", minimum=0
        ),
        elapsed_ms=number_value(payload["elapsed_ms"], "decision elapsed_ms"),
        returned_duration_ms=(
            None
            if returned_duration is None
            else number_value(returned_duration, "decision returned_duration_ms")
        ),
    )
