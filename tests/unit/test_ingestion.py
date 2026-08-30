from collections import Counter
from pathlib import Path

from deal_intel.evidence_plane.ingestion import EvidenceIngestor


def test_ingestor_loads_slack_updates_as_evidence_records() -> None:
    records = EvidenceIngestor(Path("synthetic_data")).load_records()
    slack_records = [record for record in records if record.source_type == "slack"]

    assert len(slack_records) == 6
    assert Counter(record.opportunity_id for record in slack_records) == {
        "OPP-1001": 2,
        "OPP-1002": 2,
        "OPP-1003": 2,
    }
    assert {record.record_kind for record in slack_records} == {"slack_account_team_update"}
    assert all(
        record.source_file == "synthetic_data/slack/account_team_updates.tsv"
        for record in slack_records
    )
    assert all(record.source_record_id.startswith("SLACK-") for record in slack_records)
    assert all(
        record.evidence_id == f"EV-SLACK-{record.source_record_id}" for record in slack_records
    )
    assert {record.metadata["synthetic_notice"] for record in slack_records} == {"SYNTHETIC"}
