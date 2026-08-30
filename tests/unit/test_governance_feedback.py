from pathlib import Path

from deal_intel.contracts.schemas import AnalystReport, Recommendation
from deal_intel.evidence_plane.ledger import EvidenceLedger
from deal_intel.governance_plane.approval_simulator import ApprovalSimulator
from deal_intel.governance_plane.policy_engine import GovernancePolicyEngine
from deal_intel.governance_plane.run_ledger import RunLedger


def sensitive_recommendation() -> Recommendation:
    return Recommendation(
        recommendation_id="REC-1",
        action="Prepare an internal 18 percent discount scenario.",
        rationale="Procurement requested a material reduction.",
        owner_role="Account Owner",
        evidence_ids=["EV-PRICING-PN-4004"],
        confidence="low",
        impact_types=["pricing", "discount", "concession"],
        proposed_discount_percent=18,
    )


def test_policy_computes_roles_and_clear_explanation() -> None:
    recommendation = sensitive_recommendation()
    requirements = GovernancePolicyEngine().evaluate_recommendations(
        [recommendation], [AnalystReport(analyst_name="risk_approval_analyst")]
    )

    assert len(requirements) == 1
    requirement = requirements[0]
    assert set(requirement.required_roles) == {
        "deal_desk",
        "sales_leader",
        "human_reviewer",
    }
    assert "18" not in requirement.explanation
    assert "model cannot approve" in requirement.explanation.lower()
    assert "Deal Desk policy rule 2" in requirement.policy_rules


def test_human_decision_creates_separate_feedback_record(tmp_path: Path) -> None:
    ledger = RunLedger(EvidenceLedger(tmp_path / "deal_intel.sqlite"))
    service = ApprovalSimulator(ledger)
    recommendation = sensitive_recommendation()
    requirements = GovernancePolicyEngine().evaluate_recommendations(
        [recommendation], [AnalystReport(analyst_name="risk_approval_analyst")]
    )
    approvals = service.create_for_requirements(
        run_id="RUN-1",
        requirements=requirements,
        recommendations=[recommendation],
        model_alias="synthesis_model",
        prompt_version="brief_composer.v1",
    )
    deal_desk_approval = next(
        approval for approval in approvals if approval.required_role == "deal_desk"
    )

    decision, feedback = service.decide(
        approval_id=deal_desk_approval.approval_id,
        reviewer_id="USR-5005",
        reviewer_role="deal_desk",
        decision="rejected",
        rationale="The discount is too high without a term trade-off.",
    )

    assert decision.decision == "rejected"
    assert ledger.get_approval(deal_desk_approval.approval_id).status == "rejected"
    persisted_feedback = ledger.list_feedback()
    assert persisted_feedback == [feedback]
    assert feedback.original_action == recommendation.action
    assert feedback.human_rationale == "The discount is too high without a term trade-off."
