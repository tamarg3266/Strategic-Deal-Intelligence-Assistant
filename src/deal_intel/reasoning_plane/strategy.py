from __future__ import annotations

import json
from pathlib import Path

from deal_intel.contracts.schemas import AnalystReport, StrategySynthesis
from deal_intel.model_runtime.gateway import ModelGateway

PROMPT_VERSION = "negotiation_strategy.v2"


class NegotiationStrategyAgent:
    """Synthesizes validated findings without receiving raw evidence or tools."""

    agent_name = "negotiation_strategy_agent"
    model_alias = "synthesis_model"

    def __init__(
        self,
        gateway: ModelGateway,
        prompt_root: Path | None = None,
        max_output_tokens: int = 1_800,
    ) -> None:
        self.gateway = gateway
        self.prompt_root = prompt_root or Path(
            "src/deal_intel/reasoning_plane/prompts"
        )
        self.max_output_tokens = max_output_tokens

    async def synthesize(
        self,
        reports: list[AnalystReport],
        run_id: str,
    ) -> StrategySynthesis:
        validated_findings = [
            {
                "analyst_name": report.analyst_name,
                "claims": [claim.model_dump() for claim in report.claims],
                "recommendations": [
                    recommendation.model_dump()
                    for recommendation in report.recommendations
                ],
            }
            for report in reports
        ]
        allowed_evidence_ids = sorted(
            {
                evidence_id
                for report in reports
                for claim in report.claims
                for evidence_id in claim.evidence_ids
            }
            | {
                evidence_id
                for report in reports
                for recommendation in report.recommendations
                for evidence_id in recommendation.evidence_ids
            }
        )
        allowed_recommendation_ids = sorted(
            {
                recommendation.recommendation_id
                for report in reports
                for recommendation in report.recommendations
            }
        )
        return await self.gateway.generate_structured(
            model_alias=self.model_alias,
            system=self._read_prompt("base_rules.md"),
            developer=self._read_prompt("negotiation_strategy.md"),
            user=json.dumps(
                {
                    "validated_findings": validated_findings,
                    "allowed_evidence_ids": allowed_evidence_ids,
                    "allowed_recommendation_ids": allowed_recommendation_ids,
                },
                sort_keys=True,
            ),
            output_schema=StrategySynthesis,
            run_id=run_id,
            agent_name=self.agent_name,
            prompt_version=PROMPT_VERSION,
            max_output_tokens=self.max_output_tokens,
        )

    def _read_prompt(self, name: str) -> str:
        return (self.prompt_root / name).read_text(encoding="utf-8")
