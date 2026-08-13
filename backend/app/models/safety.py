from typing import Any

from pydantic import BaseModel, Field


class UncertainFactAnswerModel(BaseModel):
    label: str
    value: Any = None


class UncertainFactModel(BaseModel):
    fact_id: str
    label: str
    reason: str
    question: str
    # What an operator may answer. The machine defines these, so the UI can ask
    # a closed question instead of asking someone to type a value.
    answers: list[UncertainFactAnswerModel] = Field(default_factory=list)


class ActorStopReportModel(BaseModel):
    actor_id: str
    ok: bool
    message: str
    duration_ms: float


class RegisteredActorModel(BaseModel):
    actor_id: str
    description: str
    priority: int


class LastStopModel(BaseModel):
    reason: str
    source: str
    at: float
    ok: bool
    reports: list[dict[str, Any]] = Field(default_factory=list)


class AccessDoorModel(BaseModel):
    is_open: bool | None = None
    pin: int
    detected: bool
    override_active: bool
    blocks_run: bool
    reason: str


class SafetySnapshot(BaseModel):
    state: str
    motion_blocked: bool
    generation: int
    registered_actors: list[RegisteredActorModel] = Field(default_factory=list)
    requires_confirmation: list[UncertainFactModel] = Field(default_factory=list)
    last_stop: LastStopModel | None = None
    access_door: AccessDoorModel | None = None
    # False when a workflow must not be started: the E-Stop is latched, or the
    # access door is open without an override. A single block test is allowed
    # in the door case, so callers must not use this to gate that.
    run_allowed: bool = True


class AccessDoorOverrideRequest(BaseModel):
    enabled: bool
    operator: str = "operator"


class SafetyStopRequest(BaseModel):
    reason: str = "Operator pressed emergency stop."
    source: str = "operator"


class SafetyStopResponse(BaseModel):
    ok: bool
    state: str
    message: str
    results: list[ActorStopReportModel] = Field(default_factory=list)
    requires_confirmation: list[UncertainFactModel] = Field(default_factory=list)


class SafetyRearmRequest(BaseModel):
    operator: str = "operator"


class SafetyRearmResponse(BaseModel):
    ok: bool
    state: str
    message: str
    generation: int | None = None
    operator: str | None = None
    requires_confirmation: list[UncertainFactModel] = Field(default_factory=list)


class PhysicalStateConfirmRequest(BaseModel):
    fact_id: str
    # Deliberately untyped: a fact is a toolhead slot number, a boolean, or
    # null for "nothing held", depending on which fact is being confirmed.
    value: Any = None
    operator: str = "operator"
