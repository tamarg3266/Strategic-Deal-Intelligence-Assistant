from deal_intel.contracts.schemas import (
    REQUIRED_BRIEF_SECTIONS,
    AnalystReport,
    CitedClaim,
    EvidenceRecord,
    Recommendation,
    StrategySynthesis,
)
from deal_intel.governance_plane.citation_verifier import CitationVerifier
from deal_intel.governance_plane.grounding_validator import GroundingValidator
from deal_intel.reasoning_plane.brief_assembler import BriefAssembler


def _record(evidence_id: str, text: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_file="synthetic_data/slack/account_team_updates.tsv",
        source_record_id="SLACK-1001-01",
        record_kind="slack_account_team_update",
        source_type="slack",
        source_access_level="standard",
        account_id="ACC-2001",
        opportunity_id="OPP-1001",
        text=text,
    )


def test_assembler_owns_sections_citations_and_recommendation_order() -> None:
    deal_claim = CitedClaim(
        claim="The renewal is in order review.",
        evidence_ids=["EV-DEAL"],
        confidence="high",
    )
    strategy_claim = CitedClaim(
        claim="The team needs an internal negotiation plan.",
        evidence_ids=["EV-TEAM"],
        confidence="medium",
    )
    first = Recommendation(
        recommendation_id="REC-1",
        action="Prepare the internal plan.",
        rationale="The team needs a negotiation plan.",
        owner_role="Account Owner",
        evidence_ids=["EV-TEAM"],
        confidence="medium",
    )
    second = first.model_copy(
        update={
            "recommendation_id": "REC-2",
            "action": "Confirm the order-review owner.",
            "rationale": "The renewal is in order review.",
            "evidence_ids": ["EV-DEAL"],
        }
    )
    reports = [
        AnalystReport(
            analyst_name="commercial_analyst",
            claims=[deal_claim],
            recommendations=[first, second],
            missing_information=["Confirm the meeting owner."],
            conflicts=["The owner is ambiguous."],
        )
    ]
    strategy = StrategySynthesis(
        executive_summary=[strategy_claim],
        prioritized_recommendation_ids=["REC-2", "REC-1"],
    )
    catalog = {
        "EV-DEAL": _record("EV-DEAL", deal_claim.claim),
        "EV-TEAM": _record("EV-TEAM", strategy_claim.claim),
    }

    brief = BriefAssembler().assemble(reports, strategy, catalog)

    assert list(brief.sections) == list(REQUIRED_BRIEF_SECTIONS)
    assert [item.recommendation_id for item in brief.recommendations] == [
        "REC-2",
        "REC-1",
    ]
    assert brief.cited_evidence_ids == ["EV-DEAL", "EV-TEAM"]
    assert "source=synthetic_data/slack/account_team_updates.tsv" in (
        brief.sections["Source Evidence"]
    )
    assert "Confirm the meeting owner." in brief.sections["Missing Information"]
    assert "reported 1 evidence conflict" in (
        brief.sections["Confidence and Review Warnings"]
    )


def test_strategy_validation_rejects_created_ids_and_unsupported_facts() -> None:
    evidence = _record("EV-TEAM", "The team discussed an internal plan.")
    reports = [
        AnalystReport(
            analyst_name="buyer_signal_analyst",
            claims=[
                CitedClaim(
                    claim="The team discussed an internal plan.",
                    evidence_ids=[evidence.evidence_id],
                    confidence="high",
                )
            ],
        )
    ]
    strategy = StrategySynthesis(
        executive_summary=[
            CitedClaim(
                claim="The team requested a 25 percent discount.",
                evidence_ids=[evidence.evidence_id],
                confidence="high",
            )
        ],
        prioritized_recommendation_ids=["REC-CREATED-BY-MODEL"],
    )

    citation_result = CitationVerifier().verify_strategy(strategy, reports)
    grounding_result = GroundingValidator().verify_strategy(
        strategy,
        {evidence.evidence_id: evidence},
    )

    assert citation_result.invalid_recommendation_ids == ["REC-CREATED-BY-MODEL"]
    assert "strategy_claim[0]:unsupported_number=25" in grounding_result.violations
