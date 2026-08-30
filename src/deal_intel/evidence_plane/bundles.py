from deal_intel.contracts.schemas import EvidenceBundle, EvidenceRecord
from deal_intel.control_plane.capabilities import EvidenceCapability


class EvidenceBundleBuilder:
    """Builds capability-bound evidence bundles for reasoning-plane analysts."""

    def build(
        self, capability: EvidenceCapability, records: list[EvidenceRecord]
    ) -> EvidenceBundle:
        allowed = [record for record in records if self._is_allowed(capability, record)]
        return EvidenceBundle(
            run_id=capability.run_id,
            capability_id=capability.capability_id,
            records=allowed,
        )

    def _is_allowed(self, capability: EvidenceCapability, record: EvidenceRecord) -> bool:
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
