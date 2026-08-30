from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import SourceType

CapabilityPurpose = Literal[
    "commercial_analysis",
    "buyer_signal_analysis",
    "risk_approval_analysis",
]


class EvidenceCapability(BaseModel):
    """Server-created scope. No model output is accepted into these fields."""

    capability_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    requester_id: str
    opportunity_id: str
    account_id: str
    purpose: CapabilityPurpose
    allowed_source_types: set[SourceType]
    can_view_sensitive_pricing: bool = False
    can_view_restricted_account: bool = False
    can_request_approval: bool = False

    def permits_source(self, source_type: SourceType) -> bool:
        return source_type in self.allowed_source_types
