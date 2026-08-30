from __future__ import annotations

from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import (
    AnalystReport,
    ApprovalRequirement,
    CitedClaim,
    Recommendation,
)


class PolicyFinding(BaseModel):
    decision: str
    reason_code: str
    required_roles: list[str] = Field(default_factory=list)


class GovernancePolicyEngine:
    """Applies Deal Desk rules to structured recommendations, never model approval flags."""

    prompt_version = "governance_policy.v1"

    # Kept for the claim-level compatibility check used by the assignment tests.
    claim_role_map = {
        "pricing": ["deal_desk", "sales_leader"],
        "discount": ["deal_desk", "sales_leader"],
        "legal": ["legal"],
        "liability": ["legal"],
        "customer_facing": ["sales_leader"],
        "low_confidence": ["human_reviewer"],
        "conflicting_evidence": ["human_reviewer"],
    }

    def evaluate_claim(self, claim: CitedClaim) -> PolicyFinding:
        roles = sorted(
            {
                role
                for label in claim.sensitivity_labels
                for role in self.claim_role_map.get(label, [])
            }
        )
        if roles:
            return PolicyFinding(
                decision="approval_required",
                reason_code="sensitive_or_uncertain_claim",
                required_roles=roles,
            )
        return PolicyFinding(decision="allowed", reason_code="no_governance_flags")

    def evaluate_recommendations(
        self,
        recommendations: list[Recommendation],
        reports: list[AnalystReport],
    ) -> list[ApprovalRequirement]:
        has_conflict = any(report.conflicts for report in reports)
        has_missing_information = any(report.missing_information for report in reports)
        requirements: list[ApprovalRequirement] = []
        for recommendation in recommendations:
            roles: set[str] = set()
            reasons: list[str] = []
            rules: list[str] = []
            impacts = set(recommendation.impact_types)

            discount = recommendation.proposed_discount_percent
            if discount is not None and discount > 10:
                roles.add("deal_desk")
                reasons.append("discount_above_10_percent")
                rules.append("Deal Desk policy rule 1")
            if discount is not None and discount > 15:
                roles.add("sales_leader")
                reasons.append("discount_above_15_percent")
                rules.append("Deal Desk policy rule 2")
            if discount is None and impacts & {"pricing", "discount"}:
                roles.add("deal_desk")
                reasons.append("pricing_recommendation")
                rules.append("Deal Desk policy rule 1")

            uplift = recommendation.proposed_renewal_uplift_percent
            if uplift is not None and uplift < 0:
                roles.add("deal_desk")
                reasons.append("negative_renewal_uplift")
                rules.append("Deal Desk policy rule 3")

            if impacts & {"legal", "liability"}:
                roles.add("legal")
                reasons.append("legal_or_liability_change")
                rules.append("Deal Desk policy rule 4")

            if recommendation.customer_facing and impacts & {"security", "data_retention"}:
                roles.add("legal")
                reasons.append("customer_specific_security_or_retention_language")
                rules.append("Deal Desk policy rule 5")

            if impacts & {"concession"}:
                roles.update({"deal_desk", "sales_leader"})
                reasons.append("commercial_concession")
                rules.extend(["Deal Desk policy rule 1", "Deal Desk policy rule 6"])

            if recommendation.customer_facing or "customer_facing" in impacts:
                roles.add("sales_leader")
                reasons.append("customer_facing_language")
                rules.append("Deal Desk policy rule 6")

            if recommendation.confidence == "low":
                roles.add("human_reviewer")
                reasons.append("low_confidence_recommendation")
                rules.append("Deal Desk policy rule 7")

            if has_conflict:
                roles.add("human_reviewer")
                reasons.append("conflicting_evidence")
                rules.append("Deal Desk policy rule 7")

            if has_missing_information:
                roles.add("human_reviewer")
                reasons.append("missing_source_data")
                rules.append("Deal Desk policy rule 7")

            if roles:
                role_text = ", ".join(sorted(roles))
                reason_text = ", ".join(dict.fromkeys(reasons))
                requirements.append(
                    ApprovalRequirement(
                        recommendation_id=recommendation.recommendation_id,
                        required_roles=sorted(roles),
                        reason_codes=list(dict.fromkeys(reasons)),
                        policy_rules=list(dict.fromkeys(rules)),
                        explanation=(
                            f"Human approval is required from {role_text} because the "
                            f"recommendation triggers: {reason_text}. The model cannot approve "
                            "or publish this recommendation."
                        ),
                        evidence_ids=recommendation.evidence_ids,
                    )
                )
        return requirements
