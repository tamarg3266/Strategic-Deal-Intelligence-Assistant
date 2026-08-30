from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import AnalystReport, EvidenceBundle, StrategicBrief


class CitationVerification(BaseModel):
    valid: bool
    invalid_evidence_ids: list[str] = Field(default_factory=list)


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
