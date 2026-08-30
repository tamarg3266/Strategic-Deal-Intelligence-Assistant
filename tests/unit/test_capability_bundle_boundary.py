from deal_intel.contracts.schemas import EvidenceRecord
from deal_intel.control_plane.capabilities import EvidenceCapability
from deal_intel.evidence_plane.bundles import EvidenceBundleBuilder


def test_bundle_builder_filters_by_capability_scope() -> None:
    capability = EvidenceCapability(
        run_id="RUN-1",
        requester_id="USR-1",
        opportunity_id="OPP-1",
        account_id="ACC-1",
        purpose="commercial_analysis",
        allowed_source_types={"gong"},
    )
    records = [
        EvidenceRecord(
            evidence_id="EV-GONG",
            source_file="gong.tsv",
            source_record_id="CALL-1",
            record_kind="gong_summary",
            source_type="gong",
            source_access_level="standard",
            account_id="ACC-1",
            opportunity_id="OPP-1",
            text="Allowed",
        ),
        EvidenceRecord(
            evidence_id="EV-PRICING",
            source_file="pricing.tsv",
            source_record_id="PRICE-1",
            record_kind="pricing_note",
            source_type="pricing",
            source_access_level="sensitive_pricing",
            account_id="ACC-1",
            opportunity_id="OPP-1",
            text="Not allowed",
        ),
    ]

    bundle = EvidenceBundleBuilder().build(capability, records)

    assert [record.evidence_id for record in bundle.records] == ["EV-GONG"]


def test_bundle_builder_filters_by_account_and_access_level() -> None:
    capability = EvidenceCapability(
        run_id="RUN-1",
        requester_id="USR-1",
        opportunity_id="OPP-1",
        account_id="ACC-1",
        purpose="risk_approval_analysis",
        allowed_source_types={"slack", "pricing"},
        can_view_sensitive_pricing=False,
        can_view_restricted_account=False,
    )
    records = [
        EvidenceRecord(
            evidence_id="EV-SLACK-ALLOWED",
            source_file="synthetic_data/slack/account_team_updates.tsv",
            source_record_id="SLACK-1",
            record_kind="slack_account_team_update",
            source_type="slack",
            source_access_level="standard",
            account_id="ACC-1",
            opportunity_id="OPP-1",
            text="Allowed standard update.",
        ),
        EvidenceRecord(
            evidence_id="EV-SLACK-WRONG-ACCOUNT",
            source_file="synthetic_data/slack/account_team_updates.tsv",
            source_record_id="SLACK-2",
            record_kind="slack_account_team_update",
            source_type="slack",
            source_access_level="standard",
            account_id="ACC-2",
            opportunity_id="OPP-1",
            text="Wrong account.",
        ),
        EvidenceRecord(
            evidence_id="EV-SLACK-SENSITIVE",
            source_file="synthetic_data/slack/account_team_updates.tsv",
            source_record_id="SLACK-3",
            record_kind="slack_account_team_update",
            source_type="slack",
            source_access_level="sensitive_pricing",
            account_id="ACC-1",
            opportunity_id="OPP-1",
            text="Sensitive pricing update.",
        ),
        EvidenceRecord(
            evidence_id="EV-SLACK-RESTRICTED",
            source_file="synthetic_data/slack/account_team_updates.tsv",
            source_record_id="SLACK-4",
            record_kind="slack_account_team_update",
            source_type="slack",
            source_access_level="restricted",
            account_id="ACC-1",
            opportunity_id="OPP-1",
            text="Restricted update.",
        ),
    ]

    bundle = EvidenceBundleBuilder().build(capability, records)

    assert [record.evidence_id for record in bundle.records] == ["EV-SLACK-ALLOWED"]
