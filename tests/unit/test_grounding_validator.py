from deal_intel.contracts.schemas import (
    REQUIRED_BRIEF_SECTIONS,
    AnalystReport,
    CitedClaim,
    EvidenceBundle,
    EvidenceRecord,
    Recommendation,
    StrategicBrief,
)
from deal_intel.governance_plane.grounding_validator import GroundingValidator


def evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        run_id="RUN-1",
        capability_id="CAP-1",
        records=[
            EvidenceRecord(
                evidence_id="EV-PRICING-PN-4004",
                source_file="synthetic_data/pricing/pricing_notes.tsv",
                source_record_id="PN-4004",
                record_kind="pricing_note",
                source_type="pricing",
                source_access_level="sensitive_pricing",
                account_id="ACC-2003",
                opportunity_id="OPP-1003",
                text=(
                    "Pricing note PN-4004 dated 2026-04-27 records an 18 percent "
                    "discount. The buyer said \"approval is required\"."
                ),
            )
        ],
    )


def test_grounding_accepts_supported_exact_facts() -> None:
    report = AnalystReport(
        analyst_name="risk_approval_analyst",
        claims=[
            CitedClaim(
                claim="PN-4004 records an 18 percent discount on 2026-04-27.",
                evidence_ids=["EV-PRICING-PN-4004"],
                confidence="high",
            )
        ],
        recommendations=[
            Recommendation(
                action="Prepare the 18 percent scenario for internal review.",
                rationale="The record says \"approval is required\".",
                owner_role="Account Owner",
                evidence_ids=["EV-PRICING-PN-4004"],
                confidence="low",
                impact_types=["pricing", "discount"],
                proposed_discount_percent=18,
            )
        ],
    )

    verification = GroundingValidator().verify_report(report, evidence_bundle())

    assert verification.valid


def test_grounding_rejects_citation_laundered_number_and_date() -> None:
    report = AnalystReport(
        analyst_name="risk_approval_analyst",
        claims=[
            CitedClaim(
                claim="PN-4004 records a 25 percent discount on 2026-05-30.",
                evidence_ids=["EV-PRICING-PN-4004"],
                confidence="high",
            )
        ],
    )

    verification = GroundingValidator().verify_report(report, evidence_bundle())

    assert not verification.valid
    assert "claim[0]:unsupported_number=25" in verification.violations
    assert "claim[0]:unsupported_date=2026-05-30" in verification.violations


def test_identifier_pattern_preserves_slack_update_suffix() -> None:
    identifiers = GroundingValidator.id_pattern.findall(
        "Use SLACK-1001-02, not an ambiguous prefix."
    )

    assert identifiers == ["SLACK-1001-02"]


def test_grounding_accepts_application_rendered_stable_citation() -> None:
    record = EvidenceRecord(
        evidence_id="EV-SLACK-SLACK-1001-02",
        source_file="synthetic_data/slack/account_team_updates.tsv",
        source_record_id="SLACK-1001-02",
        record_kind="slack_account_team_update",
        source_type="slack",
        source_access_level="standard",
        account_id="ACC-2001",
        opportunity_id="OPP-1001",
        text="The team confirmed the next internal action.",
    )
    sections = {section: "" for section in REQUIRED_BRIEF_SECTIONS}
    sections["Source Evidence"] = (
        f"- [{record.evidence_id}] {record.citation}"
    )
    brief = StrategicBrief(
        status="allowed",
        sections=sections,
        cited_evidence_ids=[record.evidence_id],
    )

    verification = GroundingValidator().verify_brief(
        brief,
        {record.evidence_id: record},
    )

    assert verification.valid
