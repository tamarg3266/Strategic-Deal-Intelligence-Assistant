from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from deal_intel.contracts.schemas import AnalystReport, EvidenceBundle
from deal_intel.model_runtime.gateway import ModelGateway

PROMPT_VERSION = "analysts.v2"


class BaseAnalyst:
    """LLM analyst with no retrieval or approval capability."""

    analyst_name: str
    prompt_file: str
    model_alias: str = "extraction_model"

    def __init__(self, gateway: ModelGateway, prompt_root: Path | None = None) -> None:
        self.gateway = gateway
        self.prompt_root = prompt_root or Path("src/deal_intel/reasoning_plane/prompts")

    async def analyze(
        self,
        bundle: EvidenceBundle,
        user_input: str,
        validation_feedback: list[str] | None = None,
    ) -> AnalystReport:
        if not bundle.records:
            return AnalystReport(
                analyst_name=self.analyst_name,
                missing_information=[
                    "No authorized evidence was available for this analysis."
                ],
            )
        report = await self.gateway.generate_structured(
            model_alias=self.model_alias,
            system=self._read_prompt("base_rules.md"),
            developer=self._read_prompt(self.prompt_file),
            user=json.dumps(
                {
                    "user_request": user_input,
                    "validation_feedback": validation_feedback or [],
                    "allowed_evidence_ids": sorted(
                        record.evidence_id for record in bundle.records
                    ),
                    "authorized_evidence": [
                        self._prompt_record(record) for record in bundle.records
                    ],
                },
                sort_keys=True,
            ),
            output_schema=AnalystReport,
            run_id=bundle.run_id,
            agent_name=self.analyst_name,
            prompt_version=PROMPT_VERSION,
        )
        # Identity and recommendation IDs are application-owned fields.
        return report.model_copy(
            update={
                "analyst_name": self.analyst_name,
                "recommendations": [
                    recommendation.model_copy(update={"recommendation_id": str(uuid4())})
                    for recommendation in report.recommendations
                ],
            }
        )

    def _read_prompt(self, name: str) -> str:
        return (self.prompt_root / name).read_text(encoding="utf-8")

    @staticmethod
    def _prompt_record(record) -> dict[str, object]:
        return {
            "evidence_id": record.evidence_id,
            "citation": record.citation,
            "source_type": record.source_type,
            "record_kind": record.record_kind,
            "source_date": record.source_date,
            "content": record.text,
        }


class CommercialAnalyst(BaseAnalyst):
    analyst_name = "commercial_analyst"
    prompt_file = "commercial_analyst.md"


class BuyerSignalAnalyst(BaseAnalyst):
    analyst_name = "buyer_signal_analyst"
    prompt_file = "buyer_signal_analyst.md"


class RiskApprovalAnalyst(BaseAnalyst):
    analyst_name = "risk_approval_analyst"
    prompt_file = "risk_approval_analyst.md"
    model_alias = "risk_model"
