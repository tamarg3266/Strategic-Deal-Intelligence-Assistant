import csv
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import EvidenceBundle, RunRequest, SourceType
from deal_intel.control_plane.capabilities import CapabilityPurpose, EvidenceCapability
from deal_intel.control_plane.identity import IdentityResolver, RequesterIdentity


class AuthorizationDecision(BaseModel):
    allowed: bool
    run_id: str
    safe_reason: str | None = None
    identity: RequesterIdentity | None = None
    capabilities: list[EvidenceCapability] = Field(default_factory=list)


class OpportunityScope(BaseModel):
    opportunity_id: str
    account_id: str
    restricted: bool


class AuthorizationEngine:
    """Creates immutable, purpose-specific evidence capabilities before retrieval."""

    purpose_sources: dict[CapabilityPurpose, set[SourceType]] = {
        "commercial_analysis": {"salesforce", "pricing", "policies", "slack", "gong"},
        "buyer_signal_analysis": {"salesforce", "gong", "slack"},
        "risk_approval_analysis": {"salesforce", "gong", "pricing", "policies", "slack"},
    }

    def __init__(self, data_root: Path = Path("synthetic_data")) -> None:
        self.data_root = data_root
        self.identity_resolver = IdentityResolver(
            data_root / "policies" / "access_permissions.tsv"
        )

    def authorize(
        self, request: RunRequest, run_id: str | None = None
    ) -> AuthorizationDecision:
        run_id = run_id or str(uuid4())
        identity = self.identity_resolver.resolve(request.requester_id)
        scope = self._opportunity_scope(request.opportunity_id)

        # Denials deliberately use one reason and contain no account/source metadata.
        if identity is None or scope is None:
            return AuthorizationDecision(
                allowed=False, run_id=run_id, safe_reason="access_denied"
            )
        if scope.account_id not in identity.allowed_account_ids:
            return AuthorizationDecision(
                allowed=False, run_id=run_id, safe_reason="access_denied"
            )
        if scope.restricted and not identity.can_view_restricted_account:
            return AuthorizationDecision(
                allowed=False, run_id=run_id, safe_reason="access_denied"
            )

        capabilities = [
            EvidenceCapability(
                run_id=run_id,
                requester_id=identity.requester_id,
                opportunity_id=scope.opportunity_id,
                account_id=scope.account_id,
                purpose=purpose,
                allowed_source_types=identity.allowed_source_types & purpose_sources,
                can_view_sensitive_pricing=identity.can_view_sensitive_pricing,
                can_view_restricted_account=identity.can_view_restricted_account,
                can_request_approval=identity.can_request_approval,
            )
            for purpose, purpose_sources in self.purpose_sources.items()
        ]
        return AuthorizationDecision(
            allowed=True,
            run_id=run_id,
            identity=identity,
            capabilities=capabilities,
        )

    def authorize_generation(
        self,
        request: RunRequest,
        capabilities: list[EvidenceCapability],
        bundles: list[EvidenceBundle],
    ) -> bool:
        """Second boundary: generation receives only bundles matching server scopes."""

        if len(capabilities) != len(bundles) or not capabilities:
            return False
        capability_by_id = {item.capability_id: item for item in capabilities}
        for bundle in bundles:
            capability = capability_by_id.get(bundle.capability_id)
            if capability is None:
                return False
            if capability.requester_id != request.requester_id:
                return False
            if capability.opportunity_id != request.opportunity_id:
                return False
            for record in bundle.records:
                if record.account_id != capability.account_id:
                    return False
                if record.opportunity_id != capability.opportunity_id:
                    return False
                if not capability.permits_source(record.source_type):
                    return False
                if (
                    record.source_access_level == "sensitive_pricing"
                    and not capability.can_view_sensitive_pricing
                ):
                    return False
                if (
                    record.source_access_level == "restricted"
                    and not capability.can_view_restricted_account
                ):
                    return False
        return True

    def _opportunity_scope(self, opportunity_id: str) -> OpportunityScope | None:
        path = self.data_root / "salesforce" / "opportunities.tsv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["opportunity_id"] == opportunity_id:
                    return OpportunityScope(
                        opportunity_id=opportunity_id,
                        account_id=row["account_id"],
                        restricted=row["restricted_access"].strip().lower() == "true",
                    )
        return None
