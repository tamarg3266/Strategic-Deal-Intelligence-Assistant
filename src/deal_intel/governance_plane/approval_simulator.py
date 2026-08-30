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
        grouped_requirements: dict[tuple[str, ...], list[ApprovalRequirement]] = {}
        for requirement in requirements:
            routing_key = tuple(sorted(set(requirement.required_roles)))
            grouped_requirements.setdefault(routing_key, []).append(requirement)

        approvals: list[ApprovalRequest] = []
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        for required_roles, group in grouped_requirements.items():
            grouped_recommendations = [
                recommendation_by_id[requirement.recommendation_id]
                for requirement in group
            ]
            recommendation_ids = list(
                dict.fromkeys(item.recommendation_id for item in grouped_recommendations)
            )
            reason_codes = list(
                dict.fromkeys(reason for item in group for reason in item.reason_codes)
            )
            policy_rules = list(
                dict.fromkeys(rule for item in group for rule in item.policy_rules)
            )
            role_text = ", ".join(required_roles)
            reason_text = ", ".join(reason_codes)
            approval = ApprovalRequest(
                run_id=run_id,
                grouping_key=f"roles:{'+'.join(required_roles)}",
                recommendation_ids=recommendation_ids,
                required_roles=list(required_roles),
                actions=[item.action for item in grouped_recommendations],
                rationales=[item.rationale for item in grouped_recommendations],
                confidence=min(
                    (item.confidence for item in grouped_recommendations),
                    key=confidence_rank.__getitem__,
                ),
                evidence_ids=list(
                    dict.fromkeys(
                        evidence_id
                        for item in grouped_recommendations
                        for evidence_id in item.evidence_ids
                    )
                ),
                reason_codes=reason_codes,
                policy_rules=policy_rules,
                explanation=(
                    f"Human approval is required from {role_text} for "
                    f"{len(recommendation_ids)} grouped recommendation(s) because they "
                    f"trigger: {reason_text}. The model cannot approve or publish these "
                    "recommendations."
                ),
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
        if reviewer_role not in approval.required_roles:
            raise PermissionError("reviewer_role_not_authorized")
        if reviewer_role in approval.approved_roles:
            raise ValueError("reviewer_role_already_decided")

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
            recommendation_ids=approval.recommendation_ids,
            model_alias=approval.model_alias,
            prompt_version=approval.prompt_version,
            original_actions=approval.actions,
            original_rationales=approval.rationales,
            evidence_ids=approval.evidence_ids,
            policy_reasons=approval.reason_codes,
            human_decision=decision,
            human_rationale=rationale,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
        )
        self.run_ledger.record_human_decision(approval, decision_record, feedback)
        return decision_record, feedback
