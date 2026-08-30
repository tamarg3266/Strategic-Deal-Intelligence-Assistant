from pathlib import Path

from deal_intel.contracts.schemas import EvidenceRecord
from deal_intel.control_plane.capabilities import EvidenceCapability
from deal_intel.evidence_plane.ledger import EvidenceLedger


def _record(
    evidence_id: str,
    text: str,
    *,
    account_id: str = "ACC-1",
    access_level: str = "standard",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_file="salesforce.tsv",
        source_record_id=evidence_id,
        record_kind="salesforce_opportunity",
        source_type="salesforce",
        source_access_level=access_level,
        account_id=account_id,
        opportunity_id="OPP-1",
        text=text,
    )


def _capability() -> EvidenceCapability:
    return EvidenceCapability(
        run_id="RUN-1",
        requester_id="USR-1",
        opportunity_id="OPP-1",
        account_id="ACC-1",
        purpose="commercial_analysis",
        allowed_source_types={"salesforce"},
    )


def test_scoped_search_uses_fts5_to_prioritize_matches(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "evidence.sqlite")
    ledger.replace_index(
        [
            _record("EV-NONMATCH", "General account background."),
            _record("EV-MATCH", "Renewal discount requires approval."),
        ]
    )

    records = ledger.scoped_search(_capability(), "discount approval", limit=2)

    assert [record.evidence_id for record in records] == ["EV-MATCH", "EV-NONMATCH"]
    with ledger.connect() as connection:
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'evidence_fts'"
        ).fetchone()["sql"]
    assert "fts5" in definition.casefold()


def test_scoped_search_never_returns_matching_but_unauthorized_rows(
    tmp_path: Path,
) -> None:
    ledger = EvidenceLedger(tmp_path / "evidence.sqlite")
    ledger.replace_index(
        [
            _record("EV-ALLOWED", "Standard opportunity context."),
            _record(
                "EV-WRONG-ACCOUNT",
                "Secret discount approval.",
                account_id="ACC-2",
            ),
            _record(
                "EV-SENSITIVE",
                "Sensitive discount approval.",
                access_level="sensitive_pricing",
            ),
        ]
    )

    records = ledger.scoped_search(_capability(), "discount approval", limit=10)

    assert [record.evidence_id for record in records] == ["EV-ALLOWED"]
