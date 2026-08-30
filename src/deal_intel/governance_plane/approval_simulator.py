from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from deal_intel.contracts.schemas import (
    ApprovalDecisionRecord,
    ApprovalRequest,
    ApprovalRequirement,
    HumanDecision,
    HumanFeedbackRecord,
    Recommendation,
)
from deal_intel.governance_plane.run_ledger import RunLedger


class PendingApproval(BaseModel):
    approval_id: str
    run_id: str
    required_role: str
    reason_code: str
    status: str = "pending"


class ApprovalSimulator:
    """Creates and records human gates; it has no path to auto-approval."""

    def __init__(self, run_ledger: RunLedger | None = None) -> None:
        self.run_ledger = run_ledger

    def create_pending(
        self, run_id: str, roles: list[str], reason_code: str
    ) -> list[PendingApproval]:
        """Compatibility helper for narrow policy unit tests."""

        return [
            PendingApproval(
                approval_id=str(uuid4()),
                run_id=run_id,
                required_role=role,
                reason_code=reason_code,
            )
            for role in roles
        ]

    def create_for_requirements(
        self,
        *,
        run_id: str,
        requirements: list[ApprovalRequirement],
        recommendations: list[Recommendation],
        model_alias: str,
        prompt_version: str,
    ) -> list[ApprovalRequest]:
        recommendation_by_id = {
            recommendation.recommendation_id: recommendation
            for recommendation in recommendations
        }
        approvals: list[ApprovalRequest] = []
        for requirement in requirements:
            recommendation = recommendation_by_id[requirement.recommendation_id]
            for role in requirement.required_roles:
                approval = ApprovalRequest(
                    run_id=run_id,
                    recommendation_id=recommendation.recommendation_id,
                    required_role=role,
                    action=recommendation.action,
                    rationale=recommendation.rationale,
                    confidence=recommendation.confidence,
                    evidence_ids=recommendation.evidence_ids,
                    reason_codes=requirement.reason_codes,
                    policy_rules=requirement.policy_rules,
                    explanation=requirement.explanation,
                    model_alias=model_alias,
                    prompt_version=prompt_version,
                )
                approvals.append(approval)
                if self.run_ledger:
                    self.run_ledger.save_approval(approval)
        return approvals

    def decide(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        reviewer_role: str,
        decision: HumanDecision,
        rationale: str,
    ) -> tuple[ApprovalDecisionRecord, HumanFeedbackRecord]:
        if self.run_ledger is None:
            raise RuntimeError("Approval persistence is not configured")
        approval = self.run_ledger.get_approval(approval_id)
        if approval is None:
            raise KeyError("approval_not_found")
        if approval.status != "pending":
            raise ValueError("approval_already_decided")
        if reviewer_role != approval.required_role:
            raise PermissionError("reviewer_role_not_authorized")

        decision_record = ApprovalDecisionRecord(
            approval_id=approval.approval_id,
            run_id=approval.run_id,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            decision=decision,
            rationale=rationale,
        )
        feedback = HumanFeedbackRecord(
            approval_id=approval.approval_id,
            run_id=approval.run_id,
            recommendation_id=approval.recommendation_id,
            model_alias=approval.model_alias,
            prompt_version=approval.prompt_version,
            original_action=approval.action,
            original_rationale=approval.rationale,
            evidence_ids=approval.evidence_ids,
            policy_reasons=approval.reason_codes,
            human_decision=decision,
            human_rationale=rationale,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
        )
        self.run_ledger.record_human_decision(approval, decision_record, feedback)
        return decision_record, feedback
