from collections import Counter
from pathlib import Path

from deal_intel.evidence_plane.ingestion import EvidenceIngestor


def test_ingestion_normalizes_every_required_source() -> None:
    records = EvidenceIngestor(Path("synthetic_data")).load_records()
    source_counts = Counter(record.source_type for record in records)

    assert source_counts["salesforce"] == 21
    assert source_counts["gong"] == 36
    assert source_counts["pricing"] == 5
    assert source_counts["policies"] == 3
    assert source_counts["slack"] == 6
    assert len({record.evidence_id for record in records}) == len(records)


def test_pricing_sensitivity_is_derived_from_multiple_fields() -> None:
    records = EvidenceIngestor(Path("synthetic_data")).load_records()
    pricing = {
        record.source_record_id: record
        for record in records
        if record.source_type == "pricing"
    }

    assert pricing["PN-4001"].source_access_level == "standard"
    assert pricing["PN-4004"].source_access_level == "sensitive_pricing"
    assert pricing["PN-4005"].source_access_level == "sensitive_pricing"


def test_stable_citation_contains_source_file_and_record_key() -> None:
    records = EvidenceIngestor(Path("synthetic_data")).load_records()
    gong = next(record for record in records if record.evidence_id == "EV-GONG-SUMMARY-CALL-008")

    assert gong.citation == (
        "source=synthetic_data/gong/gong_call_summaries.tsv, call_id=CALL-008"
    )
