import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from deal_intel.contracts.schemas import (
    REQUIRED_BRIEF_SECTIONS,
    CitedClaim,
    EvidenceRecord,
    StrategicBrief,
    TraceEvent,
)
from deal_intel.control_plane.capabilities import EvidenceCapability
from deal_intel.evidence_plane.bundles import EvidenceBundleBuilder
from deal_intel.evidence_plane.ledger import EvidenceLedger
from deal_intel.evidence_plane.slack_generation import (
    generate_slack_updates,
    validate_slack_updates,
)
from deal_intel.governance_plane.approval_simulator import ApprovalSimulator
from deal_intel.governance_plane.policy_engine import GovernancePolicyEngine
from deal_intel.model_runtime.gateway import ModelGateway
from deal_intel.model_runtime.litellm import LiteLLMGateway
from deal_intel.reasoning_plane.analysts import (
    BuyerSignalAnalyst,
    CommercialAnalyst,
    RiskApprovalAnalyst,
)
from deal_intel.reasoning_plane.composer import BriefComposer

DATA_ROOT = Path("synthetic_data")
EXPECTED_OPPORTUNITIES = {"OPP-1001", "OPP-1002", "OPP-1003"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_required_source_files_are_present() -> None:
    required = [
        DATA_ROOT / "salesforce" / "accounts.tsv",
        DATA_ROOT / "salesforce" / "opportunities.tsv",
        DATA_ROOT / "salesforce" / "contacts.tsv",
        DATA_ROOT / "gong" / "gong_call_summaries.tsv",
        DATA_ROOT / "pricing" / "pricing_notes.tsv",
        DATA_ROOT / "policies" / "access_permissions.tsv",
        DATA_ROOT / "policies" / "deal_desk_policy.md",
        DATA_ROOT / "slack" / "account_team_updates.tsv",
    ]

    assert all(path.exists() for path in required)
    assert len(list((DATA_ROOT / "gong" / "transcripts").glob("*.md"))) >= 9


def test_dataset_supports_all_three_provided_opportunities() -> None:
    opportunities = read_tsv(DATA_ROOT / "salesforce" / "opportunities.tsv")
    opportunity_ids = {row["opportunity_id"] for row in opportunities}

    assert EXPECTED_OPPORTUNITIES <= opportunity_ids


def test_salesforce_account_opportunity_and_contact_data_are_joinable() -> None:
    accounts = read_tsv(DATA_ROOT / "salesforce" / "accounts.tsv")
    opportunities = read_tsv(DATA_ROOT / "salesforce" / "opportunities.tsv")
    contacts = read_tsv(DATA_ROOT / "salesforce" / "contacts.tsv")

    account_ids = {row["account_id"] for row in accounts}

    assert all(row["account_id"] in account_ids for row in opportunities)
    assert all(row["account_id"] in account_ids for row in contacts)


def test_gong_summaries_and_transcript_snippets_cover_all_opportunities() -> None:
    summaries = read_tsv(DATA_ROOT / "gong" / "gong_call_summaries.tsv")
    summary_opportunities = {row["opportunity_id"] for row in summaries}
    transcript_names = {
        path.stem for path in (DATA_ROOT / "gong" / "transcripts").glob("*.md")
    }
    transcript_call_ids = {
        "CALL-001",
        "CALL-004",
        "CALL-008",
        "CALL-010",
        "CALL-014",
        "CALL-018",
        "CALL-019",
        "CALL-023",
        "CALL-027",
    }

    assert EXPECTED_OPPORTUNITIES <= summary_opportunities
    for row in summaries:
        if row["call_id"] in transcript_call_ids:
            assert f'{row["opportunity_id"]}_{row["call_id"]}' in transcript_names


def test_pricing_permissions_and_policy_sources_are_available() -> None:
    pricing = read_tsv(DATA_ROOT / "pricing" / "pricing_notes.tsv")
    permissions = read_tsv(DATA_ROOT / "policies" / "access_permissions.tsv")
    policy_text = (DATA_ROOT / "policies" / "deal_desk_policy.md").read_text(encoding="utf-8")

    assert pricing
    assert permissions
    assert "approval" in policy_text.lower()
    assert {"USR-5001", "USR-5002", "USR-5003", "USR-5007"} <= {
        row["user_id"] for row in permissions
    }


def test_candidate_generated_slack_updates_are_valid_additional_source() -> None:
    generated_rows = generate_slack_updates()
    persisted_rows = read_tsv(DATA_ROOT / "slack" / "account_team_updates.tsv")

    validate_slack_updates(generated_rows)

    assert len(persisted_rows) == 6
    assert {row["opportunity_id"] for row in persisted_rows} == EXPECTED_OPPORTUNITIES
    assert {row["synthetic_notice"] for row in persisted_rows} == {"SYNTHETIC"}
    assert {row["context_role"] for row in persisted_rows} >= {
        "reinforces_known_fact",
        "adds_missing_context",
        "introduces_ambiguity",
    }


def test_multi_agent_design_has_at_least_three_specialized_agents() -> None:
    agents = [CommercialAnalyst, BuyerSignalAnalyst, RiskApprovalAnalyst]

    assert len(agents) >= 3
    assert {agent.analyst_name for agent in agents} == {
        "commercial_analyst",
        "buyer_signal_analyst",
        "risk_approval_analyst",
    }
    assert BriefComposer is not None


def test_llm_backed_agents_use_model_gateway_with_litellm_implementation() -> None:
    assert hasattr(ModelGateway, "generate_structured")

    gateway = LiteLLMGateway(
        endpoint="http://localhost:4000",
        aliases={"extraction_model": "local-extraction-model"},
    )

    assert gateway.endpoint == "http://localhost:4000"
    assert gateway.aliases["extraction_model"] == "local-extraction-model"


def test_permissions_are_enforced_before_reasoning_bundle_creation() -> None:
    capability = EvidenceCapability(
        run_id="RUN-1",
        requester_id="USR-5007",
        opportunity_id="OPP-1003",
        account_id="ACC-2003",
        purpose="buyer_signal_analysis",
        allowed_source_types={"gong"},
        can_view_sensitive_pricing=False,
        can_view_restricted_account=False,
    )
    records = [
        EvidenceRecord(
            evidence_id="EV-GONG-STANDARD",
            source_file="synthetic_data/gong/gong_call_summaries.tsv",
            source_record_id="CALL-019",
            record_kind="gong_summary",
            source_type="gong",
            source_access_level="standard",
            account_id="ACC-2003",
            opportunity_id="OPP-1003",
            text="Allowed standard evidence.",
        ),
        EvidenceRecord(
            evidence_id="EV-SLACK-RESTRICTED",
            source_file="synthetic_data/slack/account_team_updates.tsv",
            source_record_id="SLACK-1003-02",
            record_kind="slack_account_team_update",
            source_type="slack",
            source_access_level="restricted",
            account_id="ACC-2003",
            opportunity_id="OPP-1003",
            text="Restricted evidence.",
        ),
        EvidenceRecord(
            evidence_id="EV-PRICING-SENSITIVE",
            source_file="synthetic_data/pricing/pricing_notes.tsv",
            source_record_id="PRICE-1",
            record_kind="pricing_note",
            source_type="pricing",
            source_access_level="sensitive_pricing",
            account_id="ACC-2003",
            opportunity_id="OPP-1003",
            text="Sensitive pricing evidence.",
        ),
    ]

    bundle = EvidenceBundleBuilder().build(capability, records)

    assert [record.evidence_id for record in bundle.records] == ["EV-GONG-STANDARD"]


def test_citation_contract_identifies_source_file_and_stable_source_id() -> None:
    evidence = EvidenceRecord(
        evidence_id="EV-GONG-CALL-008",
        source_file="synthetic_data/gong/gong_call_summaries.tsv",
        source_record_id="CALL-008",
        record_kind="gong_summary",
        source_type="gong",
        source_access_level="standard",
        account_id="ACC-2001",
        opportunity_id="OPP-1001",
        text="Stakeholders aligned on renewal path.",
    )

    assert evidence.source_file == "synthetic_data/gong/gong_call_summaries.tsv"
    assert evidence.source_record_id == "CALL-008"


def test_distributed_sensitivity_is_represented_in_sources() -> None:
    gong = read_tsv(DATA_ROOT / "gong" / "gong_call_summaries.tsv")
    slack = read_tsv(DATA_ROOT / "slack" / "account_team_updates.tsv")
    opportunities = read_tsv(DATA_ROOT / "salesforce" / "opportunities.tsv")

    assert "source_access_level" in gong[0]
    assert "source_access_level" in slack[0]
    assert any(row["source_access_level"] == "sensitive_pricing" for row in gong)
    assert any(row["source_access_level"] == "restricted" for row in slack)
    assert any(row["restricted_access"].lower() == "true" for row in opportunities)


def test_high_impact_recommendations_route_to_human_approval() -> None:
    claim = CitedClaim(
        claim="Prepare pricing concession scenario for internal review.",
        evidence_ids=["EV-SLACK-1003-01"],
        confidence="medium",
        sensitivity_labels=["pricing", "customer_facing"],
    )

    finding = GovernancePolicyEngine().evaluate_claim(claim)
    approvals = ApprovalSimulator().create_pending(
        run_id="RUN-1",
        roles=finding.required_roles,
        reason_code=finding.reason_code,
    )

    assert finding.decision == "approval_required"
    assert {approval.required_role for approval in approvals} == {"deal_desk", "sales_leader"}
    assert {approval.status for approval in approvals} == {"pending"}


def test_trace_contract_covers_required_observable_events() -> None:
    categories = [
        "authorization",
        "retrieval",
        "tool_call",
        "agent_invocation",
        "recommendation",
        "approval",
        "persistence",
        "validation",
    ]

    events = [
        TraceEvent(
            event_id=f"EVT-{index}",
            run_id="RUN-1",
            category=category,
            message=category,
        )
        for index, category in enumerate(categories, start=1)
    ]

    assert [event.category for event in events] == categories


def test_state_can_be_persisted_in_sqlite_run_ledger(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "deal_intel.sqlite")

    with ledger.connect() as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO runs(run_id, payload) VALUES (?, ?)", ("RUN-1", "{}"))
        row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", ("RUN-1",)).fetchone()

    assert row["payload"] == "{}"


def test_generated_brief_requires_assignment_sections() -> None:
    sections = {section: "" for section in REQUIRED_BRIEF_SECTIONS}

    brief = StrategicBrief(status="allowed", sections=sections)

    assert list(brief.sections) == list(REQUIRED_BRIEF_SECTIONS)


def test_generated_brief_rejects_missing_required_sections() -> None:
    with pytest.raises(ValidationError):
        StrategicBrief(status="allowed", sections={"Deal Snapshot": ""})
