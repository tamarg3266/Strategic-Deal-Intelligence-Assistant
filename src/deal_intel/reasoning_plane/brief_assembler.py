from __future__ import annotations

from collections.abc import Iterable

from deal_intel.contracts.schemas import (
    AnalystReport,
    CitedClaim,
    EvidenceRecord,
    Recommendation,
    StrategicBrief,
    StrategySynthesis,
)


class BriefAssembler:
    """Renders the required brief structure from validated structured data."""

    def assemble(
        self,
        reports: list[AnalystReport],
        strategy: StrategySynthesis,
        evidence_catalog: dict[str, EvidenceRecord],
    ) -> StrategicBrief:
        report_by_name = {report.analyst_name: report for report in reports}
        commercial_claims = report_by_name.get(
            "commercial_analyst",
            AnalystReport(analyst_name="commercial_analyst"),
        ).claims
        recommendations = self._ordered_recommendations(reports, strategy)
        rendered_claims = [*commercial_claims, *strategy.claims()]
        cited_evidence_ids = self._cited_evidence_ids(
            rendered_claims,
            recommendations,
        )

        sections = {
            "Deal Snapshot": self._render_claims(commercial_claims),
            "Executive Summary": self._render_claims(strategy.executive_summary),
            "Buyer Goals and Business Drivers": self._render_claims(
                strategy.buyer_goals_and_drivers
            ),
            "Stakeholder Map": self._render_claims(strategy.stakeholder_map),
            "Negotiation State": self._render_claims(strategy.negotiation_state),
            "Recommended Next Actions": self._render_recommendations(recommendations),
            "Missing Information": self._render_missing_information(reports),
            "Source Evidence": self._render_sources(
                cited_evidence_ids,
                evidence_catalog,
            ),
            "Confidence and Review Warnings": self._render_warnings(reports),
        }
        return StrategicBrief(
            status="allowed",
            sections=sections,
            cited_evidence_ids=cited_evidence_ids,
            recommendations=recommendations,
        )

    @staticmethod
    def _render_claims(claims: list[CitedClaim]) -> str:
        if not claims:
            return "No validated findings were available."
        return "\n".join(
            f"- {claim.claim} [{', '.join(claim.evidence_ids)}] "
            f"(confidence: {claim.confidence})"
            for claim in claims
        )

    @staticmethod
    def _render_recommendations(recommendations: list[Recommendation]) -> str:
        if not recommendations:
            return "No validated next actions were generated."
        return "\n".join(
            f"- {item.action} Owner: {item.owner_role}. Rationale: {item.rationale} "
            f"[{', '.join(item.evidence_ids)}] (confidence: {item.confidence})"
            for item in recommendations
        )

    @staticmethod
    def _render_missing_information(reports: list[AnalystReport]) -> str:
        items = list(
            dict.fromkeys(
                item
                for report in reports
                for item in report.missing_information
            )
        )
        return "\n".join(f"- {item}" for item in items) or "No missing information reported."

    @staticmethod
    def _render_warnings(reports: list[AnalystReport]) -> str:
        warnings: list[str] = []
        for report in reports:
            if report.conflicts:
                warnings.append(
                    f"- {report.analyst_name} reported {len(report.conflicts)} "
                    "evidence conflict(s); human review is required."
                )
            low_confidence_count = sum(
                claim.confidence == "low" for claim in report.claims
            ) + sum(
                recommendation.confidence == "low"
                for recommendation in report.recommendations
            )
            if low_confidence_count:
                warnings.append(
                    f"- {report.analyst_name} produced {low_confidence_count} "
                    "low-confidence finding(s)."
                )
        return "\n".join(warnings) or "No deterministic review warnings were raised."

    @staticmethod
    def _render_sources(
        evidence_ids: list[str],
        evidence_catalog: dict[str, EvidenceRecord],
    ) -> str:
        return "\n".join(
            f"- [{evidence_id}] {evidence_catalog[evidence_id].citation}"
            for evidence_id in evidence_ids
            if evidence_id in evidence_catalog
        ) or "No cited evidence was rendered."

    @staticmethod
    def _ordered_recommendations(
        reports: list[AnalystReport],
        strategy: StrategySynthesis,
    ) -> list[Recommendation]:
        by_id: dict[str, Recommendation] = {}
        for report in reports:
            for recommendation in report.recommendations:
                by_id.setdefault(recommendation.recommendation_id, recommendation)
        ordered_ids = list(
            dict.fromkeys(
                [*strategy.prioritized_recommendation_ids, *by_id]
            )
        )
        return [by_id[item_id] for item_id in ordered_ids if item_id in by_id]

    @staticmethod
    def _cited_evidence_ids(
        claims: Iterable[CitedClaim],
        recommendations: Iterable[Recommendation],
    ) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *(evidence_id for claim in claims for evidence_id in claim.evidence_ids),
                    *(
                        evidence_id
                        for recommendation in recommendations
                        for evidence_id in recommendation.evidence_ids
                    ),
                ]
            )
        )
