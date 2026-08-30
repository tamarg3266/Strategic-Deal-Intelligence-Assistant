from deal_intel.contracts.schemas import EvidenceBundle
from deal_intel.control_plane.capabilities import EvidenceCapability
from deal_intel.evidence_plane.ledger import EvidenceLedger


class EvidenceRetriever:
    """The only production path from a capability to an agent evidence bundle."""

    def __init__(self, ledger: EvidenceLedger, max_items: int = 40) -> None:
        self.ledger = ledger
        self.max_items = max_items

    def retrieve(self, capability: EvidenceCapability, query: str) -> EvidenceBundle:
        records = self.ledger.scoped_search(capability, query, self.max_items)
        return EvidenceBundle(
            run_id=capability.run_id,
            capability_id=capability.capability_id,
            records=records,
        )
