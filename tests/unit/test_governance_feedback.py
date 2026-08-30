from pathlib import Path

import pytest

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
        prompt_version="negotiation_strategy.v1",
    )
    assert len(approvals) == 1
    grouped_approval = approvals[0]
    assert grouped_approval.required_roles == [
        "deal_desk",
        "human_reviewer",
        "sales_leader",
    ]

    decision, feedback = service.decide(
        approval_id=grouped_approval.approval_id,
        reviewer_id="USR-5005",
        reviewer_role="deal_desk",
        decision="rejected",
        rationale="The discount is too high without a term trade-off.",
    )

    assert decision.decision == "rejected"
    assert ledger.get_approval(grouped_approval.approval_id).status == "rejected"
    persisted_feedback = ledger.list_feedback()
    assert persisted_feedback == [feedback]
    assert feedback.original_actions == [recommendation.action]
    assert feedback.human_rationale == "The discount is too high without a term trade-off."


def test_approval_groups_recommendations_and_requires_every_role(tmp_path: Path) -> None:
    ledger = RunLedger(EvidenceLedger(tmp_path / "deal_intel.sqlite"))
    service = ApprovalSimulator(ledger)
    recommendations = [
        sensitive_recommendation(),
        sensitive_recommendation().model_copy(
            update={
                "recommendation_id": "REC-2",
                "action": "Prepare a second internal discount scenario.",
            }
        ),
    ]
    requirements = GovernancePolicyEngine().evaluate_recommendations(
        recommendations, [AnalystReport(analyst_name="risk_approval_analyst")]
    )

    approvals = service.create_for_requirements(
        run_id="RUN-2",
        requirements=requirements,
        recommendations=recommendations,
        model_alias="synthesis_model",
        prompt_version="negotiation_strategy.v1",
    )

    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.recommendation_ids == ["REC-1", "REC-2"]
    assert len(approval.actions) == 2

    for role in ["deal_desk", "sales_leader"]:
        service.decide(
            approval_id=approval.approval_id,
            reviewer_id=f"reviewer-{role}",
            reviewer_role=role,
            decision="approved",
            rationale=f"Approved by {role}.",
        )
        assert ledger.get_approval(approval.approval_id).status == "pending"

    with pytest.raises(ValueError, match="reviewer_role_already_decided"):
        service.decide(
            approval_id=approval.approval_id,
            reviewer_id="second-deal-desk-reviewer",
            reviewer_role="deal_desk",
            decision="approved",
            rationale="Duplicate decision.",
        )

    service.decide(
        approval_id=approval.approval_id,
        reviewer_id="reviewer-human",
        reviewer_role="human_reviewer",
        decision="approved",
        rationale="Evidence reviewed.",
    )
    persisted = ledger.get_approval(approval.approval_id)
    assert persisted.status == "approved"
    assert set(persisted.approved_roles) == set(persisted.required_roles)
    assert len(ledger.list_feedback()) == 3
