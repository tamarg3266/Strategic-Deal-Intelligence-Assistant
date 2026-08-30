from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph

from deal_intel.config.settings import AppConfig, load_config
from deal_intel.contracts.schemas import (
    AnalystReport,
    EvidenceRecord,
    ProgressStage,
    ProgressStatus,
    RunProgress,
    RunRequest,
    RunResult,
    StrategicBrief,
    StrategySynthesis,
    TraceEvent,
    utc_now,
)
from deal_intel.control_plane.authorization import AuthorizationEngine
from deal_intel.evidence_plane.index_manager import EvidenceIndexManager
from deal_intel.evidence_plane.ingestion import EvidenceIngestor
from deal_intel.evidence_plane.ledger import EvidenceLedger
from deal_intel.evidence_plane.retrieval import EvidenceRetriever
from deal_intel.governance_plane.approval_simulator import ApprovalSimulator
from deal_intel.governance_plane.citation_verifier import CitationVerifier
from deal_intel.governance_plane.grounding_validator import GroundingValidator
from deal_intel.governance_plane.policy_engine import GovernancePolicyEngine
from deal_intel.governance_plane.run_ledger import RunLedger
from deal_intel.model_runtime.gateway import ModelGateway
from deal_intel.model_runtime.litellm import LiteLLMGateway
from deal_intel.orchestration.state import GraphState
from deal_intel.reasoning_plane.analysts import (
    BuyerSignalAnalyst,
    CommercialAnalyst,
    RiskApprovalAnalyst,
)
from deal_intel.reasoning_plane.brief_assembler import BriefAssembler
from deal_intel.reasoning_plane.strategy import (
    PROMPT_VERSION as STRATEGY_PROMPT_VERSION,
)
from deal_intel.reasoning_plane.strategy import NegotiationStrategyAgent


@dataclass
class WorkflowServices:
    config: AppConfig
    authorization: AuthorizationEngine
    ingestor: EvidenceIngestor
    index_manager: EvidenceIndexManager
    evidence_ledger: EvidenceLedger
    retriever: EvidenceRetriever
    run_ledger: RunLedger
    gateway: ModelGateway
    analysts: dict[str, Any]
    strategy_agent: NegotiationStrategyAgent
    brief_assembler: BriefAssembler
    citations: CitationVerifier
    grounding: GroundingValidator
    policy: GovernancePolicyEngine
    approvals: ApprovalSimulator


def build_services(
    config: AppConfig | None = None,
    gateway: ModelGateway | None = None,
) -> WorkflowServices:
    config = config or load_config()
    evidence_ledger = EvidenceLedger(config.paths.sqlite_path)
    ingestor = EvidenceIngestor(config.paths.data_root)
    run_ledger = RunLedger(evidence_ledger)
    if gateway is None:
        gateway = LiteLLMGateway(
            endpoint=config.litellm.base_url,
            aliases=config.litellm.model_aliases,
            timeout_seconds=config.litellm.timeout_seconds,
            api_key=config.litellm.api_key(),
            verify_tls=config.litellm.verify_tls,
            max_output_tokens=config.litellm.max_output_tokens,
            temperature=config.litellm.temperature,
            schema_repair_attempts=config.workflow.max_schema_repair_attempts,
            transport_retries=config.workflow.max_transport_retries,
            invocation_observer=run_ledger.append_model_invocation,
        )
    prompt_root = config.paths.prompt_root
    return WorkflowServices(
        config=config,
        authorization=AuthorizationEngine(config.paths.data_root),
        ingestor=ingestor,
        index_manager=EvidenceIndexManager(ingestor, evidence_ledger),
        evidence_ledger=evidence_ledger,
        retriever=EvidenceRetriever(
            evidence_ledger, max_items=config.retrieval.max_evidence_items
        ),
        run_ledger=run_ledger,
        gateway=gateway,
        analysts={
            "commercial_analysis": CommercialAnalyst(gateway, prompt_root),
            "buyer_signal_analysis": BuyerSignalAnalyst(gateway, prompt_root),
            "risk_approval_analysis": RiskApprovalAnalyst(gateway, prompt_root),
        },
        strategy_agent=NegotiationStrategyAgent(
            gateway,
            prompt_root,
            max_output_tokens=config.litellm.synthesis_max_output_tokens,
        ),
        brief_assembler=BriefAssembler(),
        citations=CitationVerifier(),
        grounding=GroundingValidator(),
        policy=GovernancePolicyEngine(),
        approvals=ApprovalSimulator(run_ledger),
    )


def build_graph(
    config: AppConfig | None = None,
    gateway: ModelGateway | None = None,
    services: WorkflowServices | None = None,
    progress_observer: Callable[[RunProgress], None] | None = None,
):
    services = services or build_services(config, gateway)

    def progress(
        run_id: str,
        stage: ProgressStage,
        status: ProgressStatus,
        message: str,
    ) -> None:
        if progress_observer is None:
            return
        try:
            progress_observer(
                RunProgress(
                    run_id=run_id,
                    stage=stage,
                    status=status,
                    message=message,
                )
            )
        except Exception:
            # A disconnected UI must not interrupt a durable workflow run.
            return

    def trace(
        state: GraphState,
        category: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> list[str]:
        if state.run_id is None:
            raise RuntimeError("Trace attempted before run ID creation")
        event = TraceEvent(
            run_id=state.run_id,
            category=category,
            message=message,
            metadata=metadata or {},
        )
        services.run_ledger.append_trace(event)
        return [*state.trace_event_ids, event.event_id]

    def authorize(state: GraphState) -> dict[str, object]:
        run_id = state.run_id or str(uuid4())
        progress(run_id, "authorization", "started", "Checking request access.")
        services.run_ledger.start_run(run_id, state.request)
        decision = services.authorization.authorize(state.request, run_id)
        state_with_id = state.model_copy(update={"run_id": run_id})
        event_ids = trace(
            state_with_id,
            "authorization",
            "request_authorized" if decision.allowed else "request_denied",
            {"decision": "allow" if decision.allowed else "deny"},
        )
        if not decision.allowed:
            progress(run_id, "authorization", "completed", "Authorization completed.")
            return {
                "run_id": run_id,
                "status": "denied",
                "safe_error": "access_denied",
                "trace_event_ids": event_ids,
            }
        progress(run_id, "authorization", "completed", "Authorization completed.")
        return {
            "run_id": run_id,
            "capabilities": decision.capabilities,
            "trace_event_ids": event_ids,
        }

    def retrieve(state: GraphState) -> dict[str, object]:
        index_ready = False
        try:
            progress(state.run_id or "", "indexing", "started", "Checking evidence index.")
            index_result = services.index_manager.ensure_current()
            event_ids = trace(
                state,
                "tool_call",
                (
                    "evidence_index_refreshed"
                    if index_result.refreshed
                    else "evidence_index_reused"
                ),
                {"record_count": index_result.record_count},
            )
            progress(state.run_id or "", "indexing", "completed", "Evidence index is ready.")
            index_ready = True
            progress(state.run_id or "", "retrieval", "started", "Retrieving authorized evidence.")
            bundles = []
            for capability in state.capabilities:
                query = _query_for_purpose(capability.purpose, state.request.user_input)
                bundle = services.retriever.retrieve(capability, query)
                bundles.append(bundle)
                state_for_trace = state.model_copy(
                    update={"trace_event_ids": event_ids}
                )
                event_ids = trace(
                    state_for_trace,
                    "retrieval",
                    "authorized_evidence_retrieved",
                    {
                        "purpose": capability.purpose,
                        "record_count": len(bundle.records),
                        "evidence_ids": [record.evidence_id for record in bundle.records],
                    },
                )

            allowed_for_generation = services.authorization.authorize_generation(
                state.request, state.capabilities, bundles
            )
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "authorization",
                (
                    "generation_scope_verified"
                    if allowed_for_generation
                    else "generation_scope_denied"
                ),
                {"decision": "allow" if allowed_for_generation else "deny"},
            )
            if not allowed_for_generation:
                progress(state.run_id or "", "retrieval", "failed", "Evidence retrieval failed.")
                return {
                    "status": "failed",
                    "safe_error": "generation_not_authorized",
                    "trace_event_ids": event_ids,
                }
            progress(state.run_id or "", "retrieval", "completed", "Authorized evidence is ready.")
            return {"bundles": bundles, "trace_event_ids": event_ids}
        except Exception as exc:
            if index_ready:
                progress(state.run_id or "", "retrieval", "failed", "Evidence retrieval failed.")
            else:
                progress(state.run_id or "", "indexing", "failed", "Evidence indexing failed.")
            event_ids = trace(
                state,
                "retrieval",
                "evidence_retrieval_failed",
                {"error_type": type(exc).__name__},
            )
            return {
                "status": "failed",
                "safe_error": "evidence_retrieval_failed",
                "trace_event_ids": event_ids,
            }

    async def analyze(state: GraphState) -> dict[str, object]:
        progress(state.run_id or "", "analysis", "started", "Running specialized analysts.")
        bundle_by_capability = {bundle.capability_id: bundle for bundle in state.bundles}
        event_ids = list(state.trace_event_ids)
        jobs = []
        ordered = []
        for capability in state.capabilities:
            bundle = bundle_by_capability[capability.capability_id]
            analyst = services.analysts[capability.purpose]
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "agent_invocation",
                "agent_started",
                {
                    "agent_name": analyst.analyst_name,
                    "evidence_ids": [record.evidence_id for record in bundle.records],
                },
            )
            ordered.append((analyst, bundle))
            jobs.append(analyst.analyze(bundle, state.request.user_input))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        failures = [
            (analyst.analyst_name, result)
            for (analyst, _), result in zip(ordered, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            progress(state.run_id or "", "analysis", "failed", "Specialized analysis failed.")
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "agent_invocation",
                "agent_execution_failed",
                {
                    "failed_agents": [agent_name for agent_name, _ in failures],
                    "error_types": [
                        type(error).__name__ for _, error in failures
                    ],
                },
            )
            return {
                "status": "failed",
                "safe_error": "agent_execution_failed",
                "trace_event_ids": event_ids,
            }
        reports = [
            result for result in results if isinstance(result, AnalystReport)
        ]

        for index, ((analyst, bundle), report) in enumerate(
            zip(ordered, reports, strict=True)
        ):
            verification = services.citations.verify_report(report, bundle)
            grounding = services.grounding.verify_report(report, bundle)
            repair_attempt = 0
            while (
                not verification.valid or not grounding.valid
            ) and repair_attempt < services.config.workflow.max_grounding_repair_attempts:
                repair_attempt += 1
                feedback = [
                    *(f"invalid_evidence_id={item}" for item in verification.invalid_evidence_ids),
                    *grounding.violations,
                ]
                state_for_trace = state.model_copy(
                    update={"trace_event_ids": event_ids}
                )
                event_ids = trace(
                    state_for_trace,
                    "validation",
                    "analyst_report_repair_started",
                    {
                        "agent_name": analyst.analyst_name,
                        "repair_attempt": repair_attempt,
                        "violations": feedback,
                    },
                )
                try:
                    report = await analyst.analyze(
                        bundle,
                        state.request.user_input,
                        validation_feedback=feedback,
                    )
                except Exception as exc:
                    progress(state.run_id or "", "analysis", "failed", "Specialized analysis failed.")
                    state_for_trace = state.model_copy(
                        update={"trace_event_ids": event_ids}
                    )
                    event_ids = trace(
                        state_for_trace,
                        "agent_invocation",
                        "agent_repair_failed",
                        {
                            "agent_name": analyst.analyst_name,
                            "error_type": type(exc).__name__,
                        },
                    )
                    return {
                        "status": "failed",
                        "safe_error": "agent_execution_failed",
                        "trace_event_ids": event_ids,
                    }
                reports[index] = report
                verification = services.citations.verify_report(report, bundle)
                grounding = services.grounding.verify_report(report, bundle)
            if not verification.valid or not grounding.valid:
                progress(state.run_id or "", "analysis", "failed", "Analysis validation failed.")
                sanitized = _omit_unsupported_findings(
                    report,
                    verification.invalid_evidence_ids,
                    grounding.violations,
                )
                if sanitized != report:
                    report = sanitized
                    reports[index] = report
                    verification = services.citations.verify_report(report, bundle)
                    grounding = services.grounding.verify_report(report, bundle)
                    state_for_trace = state.model_copy(
                        update={"trace_event_ids": event_ids}
                    )
                    event_ids = trace(
                        state_for_trace,
                        "validation",
                        "unsupported_findings_omitted",
                        {
                            "agent_name": analyst.analyst_name,
                            "remaining_claim_count": len(report.claims),
                            "remaining_recommendation_count": len(
                                report.recommendations
                            ),
                        },
                    )
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "validation",
                (
                    "analyst_report_validated"
                    if verification.valid and grounding.valid
                    else "analyst_report_rejected"
                ),
                {
                    "agent_name": analyst.analyst_name,
                    "claim_count": len(report.claims),
                    "recommendation_count": len(report.recommendations),
                    "invalid_evidence_ids": verification.invalid_evidence_ids,
                    "grounding_violations": grounding.violations,
                },
            )
            if not verification.valid or not grounding.valid:
                return {
                    "status": "failed",
                    "safe_error": "unsupported_agent_claim",
                    "trace_event_ids": event_ids,
                }
        progress(state.run_id or "", "analysis", "completed", "Specialized analysis completed.")
        return {"reports": reports, "trace_event_ids": event_ids}

    async def synthesize(state: GraphState) -> dict[str, object]:
        progress(state.run_id or "", "strategy", "started", "Synthesizing negotiation strategy.")
        catalog = _evidence_catalog(state.bundles)
        event_ids = trace(
            state,
            "agent_invocation",
            "negotiation_strategy_started",
            {"validated_report_count": len(state.reports)},
        )
        try:
            strategy = await services.strategy_agent.synthesize(
                state.reports,
                state.run_id or "",
            )
        except Exception as exc:
            progress(state.run_id or "", "strategy", "failed", "Strategy synthesis failed.")
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "agent_invocation",
                "negotiation_strategy_failed",
                {"error_type": type(exc).__name__},
            )
            return {
                "status": "failed",
                "safe_error": "strategy_synthesis_failed",
                "trace_event_ids": event_ids,
            }

        verification = services.citations.verify_strategy(strategy, state.reports)
        grounding = services.grounding.verify_strategy(strategy, catalog)
        incomplete = _strategy_is_incomplete(strategy, state.reports)
        state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
        event_ids = trace(
            state_for_trace,
            "validation",
            (
                "strategy_synthesis_validated"
                if verification.valid and grounding.valid and not incomplete
                else "strategy_synthesis_rejected"
            ),
            {
                "invalid_evidence_ids": verification.invalid_evidence_ids,
                "invalid_recommendation_ids": (
                    verification.invalid_recommendation_ids
                ),
                "grounding_violations": grounding.violations,
                "missing_strategy_findings": incomplete,
            },
        )
        if incomplete:
            progress(state.run_id or "", "strategy", "failed", "Strategy validation failed.")
            return {
                "status": "failed",
                "safe_error": "incomplete_strategy_synthesis",
                "trace_event_ids": event_ids,
            }
        if not verification.valid or not grounding.valid:
            progress(state.run_id or "", "strategy", "failed", "Strategy validation failed.")
            return {
                "status": "failed",
                "safe_error": "unsupported_strategy_synthesis",
                "trace_event_ids": event_ids,
            }

        brief = services.brief_assembler.assemble(
            state.reports,
            strategy,
            catalog,
        )
        progress(state.run_id or "", "strategy", "completed", "Strategy synthesis completed.")
        return {"brief": brief, "trace_event_ids": event_ids}

    def govern(state: GraphState) -> dict[str, object]:
        progress(state.run_id or "", "governance", "started", "Applying deterministic governance.")
        if state.brief is None:
            progress(state.run_id or "", "governance", "failed", "Governance validation failed.")
            return {"status": "failed", "safe_error": "brief_missing"}
        brief = state.brief
        catalog = _evidence_catalog(state.bundles)
        verification = services.citations.verify_brief(brief, state.reports)
        grounding = services.grounding.verify_brief(
            brief,
            catalog,
        )
        unsupported_identifiers = _unsupported_brief_identifiers(
            grounding.violations
        )
        event_ids = list(state.trace_event_ids)
        if verification.valid and unsupported_identifiers:
            brief = _remove_unsupported_brief_identifiers(
                brief,
                unsupported_identifiers,
            )
            verification = services.citations.verify_brief(brief, state.reports)
            grounding = services.grounding.verify_brief(brief, catalog)
            state_for_trace = state.model_copy(
                update={"trace_event_ids": event_ids}
            )
            event_ids = trace(
                state_for_trace,
                "validation",
                "unsupported_source_labels_removed",
                {"removed_label_count": len(unsupported_identifiers)},
            )
        state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
        event_ids = trace(
            state_for_trace,
            "validation",
            (
                "brief_grounding_validated"
                if verification.valid and grounding.valid
                else "brief_grounding_rejected"
            ),
            {
                "invalid_evidence_ids": verification.invalid_evidence_ids,
                "grounding_violations": grounding.violations,
            },
        )
        if not verification.valid or not grounding.valid:
            progress(state.run_id or "", "governance", "failed", "Governance validation failed.")
            return {
                "status": "failed",
                "safe_error": "unsupported_brief_claim",
                "trace_event_ids": event_ids,
            }

        for recommendation in brief.recommendations:
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "recommendation",
                "recommendation_generated",
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "confidence": recommendation.confidence,
                    "impact_types": recommendation.impact_types,
                    "evidence_ids": recommendation.evidence_ids,
                },
            )

        requirements = services.policy.evaluate_recommendations(
            brief.recommendations, state.reports
        )
        if requirements and not all(
            capability.can_request_approval for capability in state.capabilities
        ):
            progress(state.run_id or "", "governance", "failed", "Approval routing failed.")
            state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
            event_ids = trace(
                state_for_trace,
                "approval",
                "approval_request_denied",
                {"reason": "requester_cannot_request_approval"},
            )
            return {
                "status": "failed",
                "safe_error": "approval_request_not_authorized",
                "trace_event_ids": event_ids,
            }

        approvals = services.approvals.create_for_requirements(
            run_id=state.run_id or "",
            requirements=requirements,
            recommendations=brief.recommendations,
            model_alias="synthesis_model",
            prompt_version=STRATEGY_PROMPT_VERSION,
        )
        status = "allowed"
        if approvals:
            status = "approval_required"
            brief = _attach_approval_explanations(brief, approvals)
            for approval in approvals:
                state_for_trace = state.model_copy(update={"trace_event_ids": event_ids})
                event_ids = trace(
                    state_for_trace,
                    "approval",
                    "human_approval_requested",
                    {
                        "approval_id": approval.approval_id,
                        "recommendation_ids": approval.recommendation_ids,
                        "required_roles": approval.required_roles,
                        "reason_codes": approval.reason_codes,
                    },
                )
        progress(state.run_id or "", "governance", "completed", "Governance checks completed.")
        return {
            "status": status,
            "brief": brief,
            "approvals": approvals,
            "trace_event_ids": event_ids,
        }

    def finalize(state: GraphState) -> dict[str, object]:
        if state.run_id is None:
            raise RuntimeError("Cannot finalize a run without an ID")
        progress(state.run_id, "persistence", "started", "Persisting run result.")
        status = state.status
        if state.brief is not None and state.safe_error is None:
            status = state.brief.status
        event_ids = trace(
            state,
            "persistence",
            "run_result_persisted",
            {"status": status},
        )
        result = RunResult(
            run_id=state.run_id,
            request=state.request,
            status=status,
            brief=state.brief,
            approvals=state.approvals,
            trace_event_ids=event_ids,
            safe_error=state.safe_error,
            completed_at=utc_now(),
        )
        services.run_ledger.persist_result(result)
        _write_artifacts(services.config.paths.artifact_dir, result)
        progress(state.run_id, "persistence", "completed", "Run result persisted.")
        return {"status": status, "trace_event_ids": event_ids, "result": result}

    graph = StateGraph(GraphState)
    graph.add_node("control_authorize", authorize)
    graph.add_node("evidence_retrieve", retrieve)
    graph.add_node("reasoning_analyze", analyze)
    graph.add_node("reasoning_synthesize", synthesize)
    graph.add_node("governance_validate", govern)
    graph.add_node("persist_terminal", finalize)
    graph.set_entry_point("control_authorize")
    graph.add_conditional_edges(
        "control_authorize",
        _route_on_error,
        {"continue": "evidence_retrieve", "terminal": "persist_terminal"},
    )
    graph.add_conditional_edges(
        "evidence_retrieve",
        _route_on_error,
        {"continue": "reasoning_analyze", "terminal": "persist_terminal"},
    )
    graph.add_conditional_edges(
        "reasoning_analyze",
        _route_on_error,
        {"continue": "reasoning_synthesize", "terminal": "persist_terminal"},
    )
    graph.add_conditional_edges(
        "reasoning_synthesize",
        _route_on_error,
        {"continue": "governance_validate", "terminal": "persist_terminal"},
    )
    graph.add_edge("governance_validate", "persist_terminal")
    graph.add_edge("persist_terminal", END)
    return graph.compile()


async def run_workflow(
    request: RunRequest,
    *,
    config: AppConfig | None = None,
    gateway: ModelGateway | None = None,
    progress_observer: Callable[[RunProgress], None] | None = None,
) -> RunResult:
    owns_gateway = gateway is None
    services = build_services(config=config, gateway=gateway)
    graph = build_graph(services=services, progress_observer=progress_observer)
    try:
        output = await graph.ainvoke(GraphState(request=request))
        result = output.get("result") if isinstance(output, dict) else output.result
        if not isinstance(result, RunResult):
            result = RunResult.model_validate(result)
        return result
    finally:
        if owns_gateway:
            close = getattr(services.gateway, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass


def _route_on_error(state: GraphState) -> str:
    return "terminal" if state.safe_error else "continue"


def _query_for_purpose(purpose: str, user_input: str) -> str:
    focus = {
        "commercial_analysis": (
            "deal amount pricing stage close date next step commercial terms"
        ),
        "buyer_signal_analysis": (
            "buyer goals objections urgency stakeholders commitments conflicts"
        ),
        "risk_approval_analysis": (
            "pricing discount legal liability security approval risk confidence"
        ),
    }[purpose]
    return f"{focus} {user_input}"


def _evidence_catalog(bundles) -> dict[str, EvidenceRecord]:
    return {
        record.evidence_id: record
        for bundle in bundles
        for record in bundle.records
    }


def _strategy_is_incomplete(
    strategy: StrategySynthesis,
    reports: list[AnalystReport],
) -> bool:
    return any(report.claims for report in reports) and not strategy.claims()


def _attach_approval_explanations(
    brief: StrategicBrief, approvals
) -> StrategicBrief:
    lines = [brief.sections["Confidence and Review Warnings"].rstrip()]
    lines.append("\nHuman approval gates:")
    for approval in approvals:
        lines.append(
            f"- Approval {approval.approval_id} requires "
            f"{', '.join(approval.required_roles)} for recommendations "
            f"{', '.join(approval.recommendation_ids)}: "
            f"{approval.explanation} Evidence: "
            f"{', '.join(approval.evidence_ids)}"
        )
    sections = dict(brief.sections)
    sections["Confidence and Review Warnings"] = "\n".join(line for line in lines if line)
    return brief.model_copy(
        update={
            "status": "approval_required",
            "sections": sections,
            "pending_approval_ids": [approval.approval_id for approval in approvals],
        }
    )


def _omit_unsupported_findings(
    report: AnalystReport,
    invalid_evidence_ids: list[str],
    grounding_violations: list[str],
) -> AnalystReport:
    invalid_ids = set(invalid_evidence_ids)
    invalid_claims = _violation_indexes(grounding_violations, "claim")
    invalid_recommendations = _violation_indexes(
        grounding_violations,
        "recommendation",
    )
    invalid_claims.update(
        index
        for index, claim in enumerate(report.claims)
        if invalid_ids.intersection(claim.evidence_ids)
    )
    invalid_recommendations.update(
        index
        for index, recommendation in enumerate(report.recommendations)
        if invalid_ids.intersection(recommendation.evidence_ids)
    )
    if not invalid_claims and not invalid_recommendations:
        return report
    warning = (
        "One or more model findings were omitted because deterministic "
        "grounding validation failed."
    )
    return report.model_copy(
        update={
            "claims": [
                claim
                for index, claim in enumerate(report.claims)
                if index not in invalid_claims
            ],
            "recommendations": [
                recommendation
                for index, recommendation in enumerate(report.recommendations)
                if index not in invalid_recommendations
            ],
            "missing_information": list(
                dict.fromkeys([*report.missing_information, warning])
            ),
        }
    )


def _violation_indexes(violations: list[str], label: str) -> set[int]:
    pattern = re.compile(rf"^{re.escape(label)}\[(\d+)]")
    return {
        int(match.group(1))
        for violation in violations
        if (match := pattern.match(violation)) is not None
    }


def _unsupported_brief_identifiers(violations: list[str]) -> set[str]:
    prefix = "brief:unsupported_id="
    if not violations or any(not item.startswith(prefix) for item in violations):
        return set()
    return {item.removeprefix(prefix) for item in violations}


def _remove_unsupported_brief_identifiers(
    brief: StrategicBrief,
    identifiers: set[str],
) -> StrategicBrief:
    sections = dict(brief.sections)
    for section_name, content in sections.items():
        cleaned = content
        for identifier in identifiers:
            pattern = re.compile(
                rf"\[?(?<![A-Z0-9-]){re.escape(identifier)}(?![A-Z0-9-])\]?",
                re.IGNORECASE,
            )
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
        sections[section_name] = cleaned
    return brief.model_copy(update={"sections": sections})


def _write_artifacts(artifact_dir: Path, result: RunResult) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
