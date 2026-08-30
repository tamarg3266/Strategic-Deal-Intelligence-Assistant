from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["salesforce", "gong", "pricing", "policies", "slack"]
AccessLevel = Literal["standard", "sensitive_pricing", "restricted"]
Confidence = Literal["low", "medium", "high"]
ApprovalStatus = Literal["pending", "approved", "rejected", "changes_requested"]
HumanDecision = Literal["approved", "rejected", "changes_requested"]

REQUIRED_BRIEF_SECTIONS = (
    "Deal Snapshot",
    "Executive Summary",
    "Buyer Goals and Business Drivers",
    "Stakeholder Map",
    "Negotiation State",
    "Recommended Next Actions",
    "Missing Information",
    "Source Evidence",
    "Confidence and Review Warnings",
)

TraceEventCategory = Literal[
    "authorization",
    "retrieval",
    "tool_call",
    "agent_invocation",
    "recommendation",
    "approval",
    "persistence",
    "validation",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunRequest(BaseModel):
    opportunity_id: str = Field(pattern=r"^OPP-\d+$")
    requester_id: str = Field(pattern=r"^USR-\d+$")
    user_input: str = Field(
        default="Generate an internal Strategic Deal Intelligence Brief.",
        min_length=1,
        max_length=2_000,
    )


class EvidenceRecord(BaseModel):
    evidence_id: str
    source_file: str
    source_record_id: str
    record_kind: str
    source_type: SourceType
    source_access_level: AccessLevel
    account_id: str
    opportunity_id: str
    source_date: str | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def citation(self) -> str:
        stable_key = {
            "gong": "call_id",
            "pricing": "pricing_note_id",
            "slack": "update_id",
            "policies": "policy_id",
            "salesforce": self.record_kind.replace("salesforce_", "") + "_id",
        }[self.source_type]
        return f"source={self.source_file}, {stable_key}={self.source_record_id}"


class EvidenceBundle(BaseModel):
    run_id: str
    capability_id: str
    records: list[EvidenceRecord] = Field(default_factory=list)


class CitedClaim(BaseModel):
    claim: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Confidence
    sensitivity_labels: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: str(uuid4()))
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Confidence
    impact_types: list[
        Literal[
            "internal_action",
            "pricing",
            "discount",
            "concession",
            "legal",
            "liability",
            "security",
            "data_retention",
            "customer_facing",
        ]
    ] = Field(default_factory=lambda: ["internal_action"])
    proposed_discount_percent: float | None = Field(default=None, ge=0, le=100)
    proposed_renewal_uplift_percent: float | None = Field(default=None, ge=-100, le=1000)
    customer_facing: bool = False


class AnalystReport(BaseModel):
    analyst_name: str
    claims: list[CitedClaim] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class BriefDraft(BaseModel):
    sections: dict[str, str]
    cited_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_all_sections(self) -> BriefDraft:
        missing = [
            section for section in REQUIRED_BRIEF_SECTIONS if section not in self.sections
        ]
        if missing:
            raise ValueError(f"Missing required brief sections: {missing}")
        return self


class StrategicBrief(BaseModel):
    status: Literal["allowed", "approval_required", "denied", "failed"]
    sections: dict[str, str] = Field(default_factory=dict)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    pending_approval_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_sections_for_usable_brief(self) -> StrategicBrief:
        if self.status in {"allowed", "approval_required"}:
            missing = [
                section
                for section in REQUIRED_BRIEF_SECTIONS
                if section not in self.sections
            ]
            if missing:
                raise ValueError(f"Missing required brief sections: {missing}")
        return self


class ApprovalRequirement(BaseModel):
    recommendation_id: str
    required_roles: list[str] = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)
    policy_rules: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    recommendation_id: str
    required_role: str
    status: ApprovalStatus = "pending"
    action: str
    rationale: str
    confidence: Confidence
    evidence_ids: list[str]
    reason_codes: list[str]
    policy_rules: list[str]
    explanation: str
    model_alias: str
    prompt_version: str
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


class ApprovalDecisionRecord(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    approval_id: str
    run_id: str
    reviewer_id: str
    reviewer_role: str
    decision: HumanDecision
    rationale: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=utc_now)


class HumanFeedbackRecord(BaseModel):
    """Immutable training candidate; it is never applied to the live model automatically."""

    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    approval_id: str
    run_id: str
    recommendation_id: str
    model_alias: str
    prompt_version: str
    original_action: str
    original_rationale: str
    evidence_ids: list[str]
    policy_reasons: list[str]
    human_decision: HumanDecision
    human_rationale: str
    reviewer_id: str
    reviewer_role: str
    created_at: datetime = Field(default_factory=utc_now)


class TraceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    category: TraceEventCategory
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ModelInvocation(BaseModel):
    invocation_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    agent_name: str
    model_alias: str
    provider_model: str
    prompt_version: str
    input_hash: str
    output_schema: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    success: bool
    error_type: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RunResult(BaseModel):
    run_id: str
    request: RunRequest
    status: Literal["running", "allowed", "approval_required", "denied", "failed"]
    brief: StrategicBrief | None = None
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    trace_event_ids: list[str] = Field(default_factory=list)
    safe_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
