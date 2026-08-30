from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import (
    AnalystReport,
    EvidenceBundle,
    StrategicBrief,
    StrategySynthesis,
)


class CitationVerification(BaseModel):
    valid: bool
    invalid_evidence_ids: list[str] = Field(default_factory=list)
    invalid_recommendation_ids: list[str] = Field(default_factory=list)


class CitationVerifier:
    """Checks citations against the exact evidence that crossed into reasoning."""

    def verify_report(self, report: AnalystReport, bundle: EvidenceBundle) -> CitationVerification:
        allowed = {record.evidence_id for record in bundle.records}
        cited = {
            evidence_id
            for claim in report.claims
            for evidence_id in claim.evidence_ids
        } | {
            evidence_id
            for recommendation in report.recommendations
            for evidence_id in recommendation.evidence_ids
        }
        invalid = sorted(cited - allowed)
        return CitationVerification(valid=not invalid, invalid_evidence_ids=invalid)

    def verify_brief(
        self, brief: StrategicBrief, reports: list[AnalystReport]
    ) -> CitationVerification:
        allowed = {
            evidence_id
            for report in reports
            for claim in report.claims
            for evidence_id in claim.evidence_ids
        } | {
            evidence_id
            for report in reports
            for recommendation in report.recommendations
            for evidence_id in recommendation.evidence_ids
        }
        invalid = sorted(set(brief.cited_evidence_ids) - allowed)
        return CitationVerification(valid=not invalid, invalid_evidence_ids=invalid)

    def verify_strategy(
        self,
        strategy: StrategySynthesis,
        reports: list[AnalystReport],
    ) -> CitationVerification:
        allowed_evidence_ids = {
            evidence_id
            for report in reports
            for claim in report.claims
            for evidence_id in claim.evidence_ids
        } | {
            evidence_id
            for report in reports
            for recommendation in report.recommendations
            for evidence_id in recommendation.evidence_ids
        }
        allowed_recommendation_ids = {
            recommendation.recommendation_id
            for report in reports
            for recommendation in report.recommendations
        }
        cited_evidence_ids = {
            evidence_id
            for claim in strategy.claims()
            for evidence_id in claim.evidence_ids
        }
        invalid_evidence_ids = sorted(cited_evidence_ids - allowed_evidence_ids)
        invalid_recommendation_ids = sorted(
            set(strategy.prioritized_recommendation_ids)
            - allowed_recommendation_ids
        )
        return CitationVerification(
            valid=not invalid_evidence_ids and not invalid_recommendation_ids,
            invalid_evidence_ids=invalid_evidence_ids,
            invalid_recommendation_ids=invalid_recommendation_ids,
        )
