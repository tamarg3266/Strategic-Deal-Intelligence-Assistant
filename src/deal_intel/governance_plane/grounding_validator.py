from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from deal_intel.contracts.schemas import (
    AnalystReport,
    EvidenceBundle,
    EvidenceRecord,
    StrategicBrief,
)


class GroundingVerification(BaseModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)


class GroundingValidator:
    """Rejects unsupported exact facts even when a valid citation ID is supplied."""

    date_pattern = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
    percent_pattern = re.compile(r"(?<![\w-])-?\d+(?:\.\d+)?\s*(?:%|percent)\b", re.I)
    number_pattern = re.compile(r"(?<![\w-])-?(?:\d{2,}|\d[\d,]{3,})(?:\.\d+)?\b")
    id_pattern = re.compile(r"\b(?:OPP|ACC|CON|CALL|PN|SLACK)-\d+(?:-\d+)?\b")
    quote_pattern = re.compile(r'"([^"]{5,})"')

    def verify_report(
        self, report: AnalystReport, bundle: EvidenceBundle
    ) -> GroundingVerification:
        catalog = {record.evidence_id: record for record in bundle.records}
        violations: list[str] = []
        for index, claim in enumerate(report.claims):
            source_text = self._source_text(claim.evidence_ids, catalog)
            violations.extend(self._violations(f"claim[{index}]", claim.claim, source_text))
        for index, recommendation in enumerate(report.recommendations):
            source_text = self._source_text(recommendation.evidence_ids, catalog)
            text = f"{recommendation.action}\n{recommendation.rationale}"
            violations.extend(
                self._violations(f"recommendation[{index}]", text, source_text)
            )
            if recommendation.proposed_discount_percent is not None:
                token = self._normalize_number(recommendation.proposed_discount_percent)
                if token not in self._normalized_numbers(source_text):
                    violations.append(
                        f"recommendation[{index}]:unsupported_discount={token}"
                    )
            if recommendation.proposed_renewal_uplift_percent is not None:
                token = self._normalize_number(
                    recommendation.proposed_renewal_uplift_percent
                )
                if token not in self._normalized_numbers(source_text):
                    violations.append(
                        f"recommendation[{index}]:unsupported_uplift={token}"
                    )
        return GroundingVerification(valid=not violations, violations=violations)

    def verify_brief(
        self,
        brief: StrategicBrief,
        evidence_catalog: dict[str, EvidenceRecord],
    ) -> GroundingVerification:
        source_text = self._source_text(brief.cited_evidence_ids, evidence_catalog)
        rendered = "\n".join(brief.sections.values())
        violations = self._violations("brief", rendered, source_text)
        return GroundingVerification(valid=not violations, violations=violations)

    def _violations(self, label: str, text: str, source_text: str) -> list[str]:
        violations: list[str] = []
        source_lower = source_text.casefold()
        source_numbers = self._normalized_numbers(source_text)

        for date in self.date_pattern.findall(text):
            if date.casefold() not in source_lower:
                violations.append(f"{label}:unsupported_date={date}")
        for identifier in self.id_pattern.findall(text):
            if identifier.casefold() not in source_lower:
                violations.append(f"{label}:unsupported_id={identifier}")
        for value in self._numeric_tokens(text):
            if value not in source_numbers:
                violations.append(f"{label}:unsupported_number={value}")
        for quote in self.quote_pattern.findall(text):
            normalized_quote = " ".join(quote.split()).casefold()
            if normalized_quote not in " ".join(source_text.split()).casefold():
                violations.append(f"{label}:unsupported_quote")
        return list(dict.fromkeys(violations))

    def _numeric_tokens(self, text: str) -> set[str]:
        raw = self.percent_pattern.findall(text) + self.number_pattern.findall(text)
        return {self._normalize_number(value) for value in raw}

    def _normalized_numbers(self, text: str) -> set[str]:
        raw = re.findall(r"(?<![\w-])-?\d[\d,]*(?:\.\d+)?", text)
        return {self._normalize_number(value) for value in raw}

    @staticmethod
    def _normalize_number(value: str | int | float) -> str:
        text = str(value).lower().replace(",", "")
        text = re.sub(r"\s*(?:%|percent)\s*$", "", text)
        try:
            number = float(text)
        except ValueError:
            return text
        return str(int(number)) if number.is_integer() else str(number)

    @staticmethod
    def _source_text(
        evidence_ids: Iterable[str], catalog: dict[str, EvidenceRecord]
    ) -> str:
        return "\n".join(
            "\n".join(
                (
                    catalog[evidence_id].evidence_id,
                    catalog[evidence_id].citation,
                    catalog[evidence_id].text,
                )
            )
            for evidence_id in evidence_ids
            if evidence_id in catalog
        )
