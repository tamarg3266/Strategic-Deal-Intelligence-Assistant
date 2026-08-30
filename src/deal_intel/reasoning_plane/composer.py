from __future__ import annotations

import json
import re
from pathlib import Path

from deal_intel.contracts.schemas import (
    AnalystReport,
    BriefDraft,
    EvidenceRecord,
    Recommendation,
    StrategicBrief,
)
from deal_intel.model_runtime.gateway import ModelGateway

PROMPT_VERSION = "brief_composer.v1"


class BriefComposer:
    """LLM synthesis over validated reports; source rendering remains deterministic."""

    def __init__(self, gateway: ModelGateway, prompt_root: Path | None = None) -> None:
        self.gateway = gateway
        self.prompt_root = prompt_root or Path("src/deal_intel/reasoning_plane/prompts")

    async def compose(
        self,
        reports: list[AnalystReport],
        evidence_catalog: dict[str, EvidenceRecord] | None = None,
        run_id: str = "RUN-UNSPECIFIED",
    ) -> StrategicBrief:
        evidence_catalog = evidence_catalog or {}
        draft = await self.gateway.generate_structured(
            model_alias="synthesis_model",
            system=self._read_prompt("base_rules.md"),
            developer=self._read_prompt("brief_composer.md"),
            user=json.dumps(
                {
                    "validated_analyst_reports": [report.model_dump() for report in reports],
                    "citation_catalog": {
                        evidence_id: record.citation
                        for evidence_id, record in evidence_catalog.items()
                    },
                },
                sort_keys=True,
            ),
            output_schema=BriefDraft,
            run_id=run_id,
            agent_name="brief_composer",
            prompt_version=PROMPT_VERSION,
        )
        sections = dict(draft.sections)
        inline_evidence_ids = set(
            re.findall(r"\bEV-[A-Z0-9-]+\b", "\n".join(sections.values()))
        )
        recommendations = self._recommendations(reports)
        citation_ids = sorted(set(draft.cited_evidence_ids) | inline_evidence_ids)
        sections["Source Evidence"] = "\n".join(
            f"- [{evidence_id}] {evidence_catalog[evidence_id].citation}"
            for evidence_id in citation_ids
            if evidence_id in evidence_catalog
        )
        return StrategicBrief(
            status="allowed",
            sections=sections,
            cited_evidence_ids=citation_ids,
            recommendations=recommendations,
        )

    @staticmethod
    def _recommendations(reports: list[AnalystReport]) -> list[Recommendation]:
        seen: set[str] = set()
        recommendations: list[Recommendation] = []
        for report in reports:
            for recommendation in report.recommendations:
                if recommendation.recommendation_id in seen:
                    continue
                seen.add(recommendation.recommendation_id)
                recommendations.append(recommendation)
        return recommendations

    def _read_prompt(self, name: str) -> str:
        return (self.prompt_root / name).read_text(encoding="utf-8")
