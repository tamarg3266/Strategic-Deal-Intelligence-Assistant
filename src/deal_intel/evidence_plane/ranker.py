import re

from deal_intel.contracts.schemas import EvidenceRecord


class EvidenceRanker:
    """Small-data lexical ranker; authorization filtering has already happened."""

    token_pattern = re.compile(r"[A-Za-z0-9_]+")

    def rank(
        self, query: str, candidates: list[EvidenceRecord], limit: int = 40
    ) -> list[EvidenceRecord]:
        query_tokens = self._tokens(query)

        def score(record: EvidenceRecord) -> tuple[float, str, str]:
            record_tokens = self._tokens(record.text)
            overlap = len(query_tokens & record_tokens)
            coverage = overlap / max(len(query_tokens), 1)
            source_weight = {
                "salesforce": 1.0,
                "pricing": 0.95,
                "gong": 0.9,
                "slack": 0.85,
                "policies": 0.8,
            }[record.source_type]
            return (coverage + source_weight, record.source_date or "", record.evidence_id)

        return sorted(candidates, key=score, reverse=True)[:limit]

    def _tokens(self, text: str) -> set[str]:
        return {token.lower() for token in self.token_pattern.findall(text)}
