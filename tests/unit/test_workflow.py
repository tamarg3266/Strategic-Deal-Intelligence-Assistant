import asyncio
from pathlib import Path

from deal_intel.config.settings import AppConfig, LiteLLMConfig, PathConfig
from deal_intel.contracts.schemas import (
    REQUIRED_BRIEF_SECTIONS,
    AnalystReport,
    CitedClaim,
    Recommendation,
    RunProgress,
    RunRequest,
    StrategySynthesis,
)
from deal_intel.model_runtime.fake import FakeGateway
from deal_intel.orchestration.graph import (
    _omit_unsupported_findings,
    _remove_unsupported_brief_identifiers,
    _strategy_is_incomplete,
    run_workflow,
)


def test_authorized_workflow_calls_three_agents_and_strategy(tmp_path: Path) -> None:
    progress: list[RunProgress] = []
    gateway = FakeGateway(
        {
            "commercial_analyst": AnalystReport(
                analyst_name="ignored",
                claims=[
                    CitedClaim(
                        claim="The opportunity is in order review.",
                        evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                        confidence="high",
                    )
                ],
            ),
            "buyer_signal_analyst": AnalystReport(
                analyst_name="ignored",
                claims=[
                    CitedClaim(
                        claim="Stakeholders support renewal with conditions.",
                        evidence_ids=["EV-GONG-SUMMARY-CALL-008"],
                        confidence="high",
                    )
                ],
            ),
            "risk_approval_analyst": AnalystReport(analyst_name="ignored"),
            "negotiation_strategy_agent": StrategySynthesis(
                executive_summary=[
                    CitedClaim(
                        claim="Stakeholders support renewal with conditions.",
                        evidence_ids=["EV-GONG-SUMMARY-CALL-008"],
                        confidence="high",
                    )
                ],
            ),
        }
    )
    result = asyncio.run(
        run_workflow(
            RunRequest(opportunity_id="OPP-1001", requester_id="USR-5001"),
            config=make_test_config(tmp_path),
            gateway=gateway,
            progress_observer=progress.append,
        )
    )

    assert result.status == "allowed"
    assert result.brief is not None
    assert len(gateway.calls) == 4
    assert {call["agent_name"] for call in gateway.calls} == {
        "commercial_analyst",
        "buyer_signal_analyst",
        "risk_approval_analyst",
        "negotiation_strategy_agent",
    }
    assert "source=synthetic_data/gong/gong_call_summaries.tsv" in (
        result.brief.sections["Source Evidence"]
    )
    strategy_call = next(
        call
        for call in gateway.calls
        if call["agent_name"] == "negotiation_strategy_agent"
    )
    assert "citation_catalog" not in strategy_call["user"]
    assert "authorized_evidence" not in strategy_call["user"]
    assert strategy_call["max_output_tokens"] == 1800
    completed_stages = {
        item.stage for item in progress if item.status == "completed"
    }
    assert completed_stages == {
        "authorization",
        "indexing",
        "retrieval",
        "analysis",
        "strategy",
        "governance",
        "persistence",
    }
    assert all("EV-" not in item.message for item in progress)


def test_analysts_run_concurrently_and_any_failure_blocks_strategy(
    tmp_path: Path,
) -> None:
    class ConcurrentFailingGateway:
        def __init__(self) -> None:
            self.started: set[str] = set()
            self.completed: set[str] = set()
            self.active = 0
            self.max_active = 0
            self.all_analysts_started = asyncio.Event()
            self.strategy_called = False

        async def generate_structured(self, **kwargs):
            agent_name = kwargs["agent_name"]
            output_schema = kwargs["output_schema"]
            if agent_name == "negotiation_strategy_agent":
                self.strategy_called = True
                raise AssertionError("Strategy must not run after an analyst failure")

            self.started.add(agent_name)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if len(self.started) == 3:
                self.all_analysts_started.set()
            try:
                await asyncio.wait_for(self.all_analysts_started.wait(), timeout=1)
                if agent_name == "buyer_signal_analyst":
                    raise RuntimeError("simulated analyst failure")
                await asyncio.sleep(0.02)
                self.completed.add(agent_name)
                return output_schema(analyst_name=agent_name)
            finally:
                self.active -= 1

    gateway = ConcurrentFailingGateway()
    result = asyncio.run(
        run_workflow(
            RunRequest(opportunity_id="OPP-1001", requester_id="USR-5001"),
            config=make_test_config(tmp_path),
            gateway=gateway,
        )
    )

    assert result.status == "failed"
    assert result.safe_error == "agent_execution_failed"
    assert gateway.started == {
        "commercial_analyst",
        "buyer_signal_analyst",
        "risk_approval_analyst",
    }
    assert gateway.max_active == 3
    assert gateway.completed == {
        "commercial_analyst",
        "risk_approval_analyst",
    }
    assert gateway.strategy_called is False


def test_sensitive_workflow_stops_at_human_approval(tmp_path: Path) -> None:
    pricing_recommendation = Recommendation(
        action="Prepare an internal 18 percent discount scenario.",
        rationale="The pricing note records the requested scenario.",
        owner_role="Account Owner",
        evidence_ids=["EV-PRICING-PN-4004"],
        confidence="low",
        impact_types=["pricing", "discount", "concession"],
        proposed_discount_percent=18,
    )
    gateway = FakeGateway(
        {
            "commercial_analyst": AnalystReport(analyst_name="ignored"),
            "buyer_signal_analyst": AnalystReport(analyst_name="ignored"),
            "risk_approval_analyst": AnalystReport(
                analyst_name="ignored",
                claims=[
                    CitedClaim(
                        claim="The pricing position is pending approval.",
                        evidence_ids=["EV-PRICING-PN-4004"],
                        confidence="high",
                    )
                ],
                recommendations=[pricing_recommendation],
            ),
            "negotiation_strategy_agent": StrategySynthesis(
                executive_summary=[
                    CitedClaim(
                        claim="The pricing position is pending approval.",
                        evidence_ids=["EV-PRICING-PN-4004"],
                        confidence="high",
                    )
                ]
            ),
        }
    )
    result = asyncio.run(
        run_workflow(
            RunRequest(opportunity_id="OPP-1003", requester_id="USR-5003"),
            config=make_test_config(tmp_path),
            gateway=gateway,
        )
    )

    assert result.status == "approval_required"
    assert result.brief is not None
    assert result.brief.status == "approval_required"
    assert len(result.approvals) == 1
    assert set(result.approvals[0].required_roles) == {
        "deal_desk",
        "sales_leader",
        "human_reviewer",
    }
    assert all(
        "model cannot approve" in approval.explanation.lower()
        for approval in result.approvals
    )


def test_grounding_failure_repairs_only_rejected_analyst(tmp_path: Path) -> None:
    invalid_report = AnalystReport(
        analyst_name="ignored",
        claims=[
            CitedClaim(
                claim="The opportunity is worth 999999.",
                evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                confidence="high",
            )
        ],
    )
    repaired_report = AnalystReport(
        analyst_name="ignored",
        claims=[
            CitedClaim(
                claim="The opportunity is in order review.",
                evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                confidence="high",
            )
        ],
    )
    gateway = FakeGateway(
        {
            "commercial_analyst": [invalid_report, repaired_report],
            "buyer_signal_analyst": AnalystReport(analyst_name="ignored"),
            "risk_approval_analyst": AnalystReport(analyst_name="ignored"),
            "negotiation_strategy_agent": StrategySynthesis(
                executive_summary=[repaired_report.claims[0]]
            ),
        }
    )

    result = asyncio.run(
        run_workflow(
            RunRequest(opportunity_id="OPP-1001", requester_id="USR-5001"),
            config=make_test_config(tmp_path),
            gateway=gateway,
        )
    )

    commercial_calls = [
        call for call in gateway.calls if call["agent_name"] == "commercial_analyst"
    ]
    assert result.status == "allowed"
    assert len(commercial_calls) == 2
    assert "unsupported_number=999999" in commercial_calls[1]["user"]


def test_unsupported_findings_are_omitted_after_failed_repair() -> None:
    report = AnalystReport(
        analyst_name="commercial_analyst",
        claims=[
            CitedClaim(
                claim="Unsupported 999999 claim.",
                evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                confidence="low",
            ),
            CitedClaim(
                claim="Grounded claim.",
                evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                confidence="high",
            ),
        ],
    )

    sanitized = _omit_unsupported_findings(
        report,
        invalid_evidence_ids=[],
        grounding_violations=["claim[0]:unsupported_number=999999"],
    )

    assert [claim.claim for claim in sanitized.claims] == ["Grounded claim."]
    assert "deterministic grounding validation failed" in (
        sanitized.missing_information[0]
    )


def test_unsupported_source_label_removal_preserves_full_evidence_id() -> None:
    from deal_intel.contracts.schemas import StrategicBrief

    brief = StrategicBrief(
        status="allowed",
        sections={
            section: (
                "Update [SLACK-1001] is summarized by "
                "[EV-SLACK-SLACK-1001-01]."
            )
            for section in REQUIRED_BRIEF_SECTIONS
        },
    )

    sanitized = _remove_unsupported_brief_identifiers(brief, {"SLACK-1001"})

    assert "[SLACK-1001]" not in sanitized.sections["Executive Summary"]
    assert "[EV-SLACK-SLACK-1001-01]" in sanitized.sections["Executive Summary"]


def test_empty_strategy_is_incomplete_when_validated_claims_exist() -> None:
    reports = [
        AnalystReport(
            analyst_name="commercial_analyst",
            claims=[
                CitedClaim(
                    claim="The opportunity is in order review.",
                    evidence_ids=["EV-SF-OPPORTUNITY-OPP-1001"],
                    confidence="high",
                )
            ],
        )
    ]

    assert _strategy_is_incomplete(StrategySynthesis(), reports) is True
    assert _strategy_is_incomplete(
        StrategySynthesis(executive_summary=reports[0].claims),
        reports,
    ) is False
    assert _strategy_is_incomplete(
        StrategySynthesis(),
        [AnalystReport(analyst_name="commercial_analyst")],
    ) is False


def test_denied_workflow_never_calls_model(tmp_path: Path) -> None:
    gateway = FakeGateway({})
    result = asyncio.run(
        run_workflow(
            RunRequest(opportunity_id="OPP-1003", requester_id="USR-5007"),
            config=make_test_config(tmp_path),
            gateway=gateway,
        )
    )

    assert result.status == "denied"
    assert result.safe_error == "access_denied"
    assert result.brief is None
    assert gateway.calls == []


def make_test_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        environment="test",
        paths=PathConfig(
            data_root=Path("synthetic_data"),
            sqlite_path=tmp_path / "deal_intel.sqlite",
            prompt_root=Path("src/deal_intel/reasoning_plane/prompts"),
            artifact_dir=tmp_path / "artifacts",
        ),
        litellm=LiteLLMConfig(
            model_aliases={
                "extraction_model": "fake-extraction",
                "risk_model": "fake-risk",
                "synthesis_model": "fake-synthesis",
            }
        ),
    )
