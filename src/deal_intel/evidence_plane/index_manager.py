from pydantic import BaseModel

from deal_intel.evidence_plane.ingestion import EvidenceIngestor
from deal_intel.evidence_plane.ledger import EvidenceLedger


class IndexRefreshResult(BaseModel):
    refreshed: bool
    record_count: int
    source_fingerprint: str


class EvidenceIndexManager:
    """Keeps the normalized FTS5 index synchronized with local source content."""

    def __init__(self, ingestor: EvidenceIngestor, ledger: EvidenceLedger) -> None:
        self.ingestor = ingestor
        self.ledger = ledger

    def ensure_current(self) -> IndexRefreshResult:
        fingerprint = self.ingestor.source_fingerprint()
        current, record_count = self.ledger.is_index_current(fingerprint)
        if current:
            return IndexRefreshResult(
                refreshed=False,
                record_count=record_count,
                source_fingerprint=fingerprint,
            )

        records = self.ingestor.load_records()
        refreshed = self.ledger.refresh_index_if_changed(records, fingerprint)
        return IndexRefreshResult(
            refreshed=refreshed,
            record_count=len(records),
            source_fingerprint=fingerprint,
        )
