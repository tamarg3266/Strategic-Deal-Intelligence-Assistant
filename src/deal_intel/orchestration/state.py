from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import (
    AnalystReport,
    ApprovalRequest,
    EvidenceBundle,
    RunRequest,
    RunResult,
    StrategicBrief,
)
from deal_intel.control_plane.capabilities import EvidenceCapability


class GraphState(BaseModel):
    request: RunRequest
    run_id: str | None = None
    status: str = "running"
    capabilities: list[EvidenceCapability] = Field(default_factory=list)
    bundles: list[EvidenceBundle] = Field(default_factory=list)
    reports: list[AnalystReport] = Field(default_factory=list)
    brief: StrategicBrief | None = None
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    trace_event_ids: list[str] = Field(default_factory=list)
    safe_error: str | None = None
    result: RunResult | None = None
