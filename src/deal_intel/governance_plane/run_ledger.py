from __future__ import annotations

import json
from datetime import datetime, timezone

from deal_intel.contracts.schemas import (
    ApprovalDecisionRecord,
    ApprovalRequest,
    HumanFeedbackRecord,
    ModelInvocation,
    RunRequest,
    RunResult,
    TraceEvent,
)
from deal_intel.evidence_plane.ledger import EvidenceLedger


class RunLedger:
    """Durable run, trace, approval, and human-feedback persistence."""

    def __init__(self, ledger: EvidenceLedger) -> None:
        self.ledger = ledger
        self.initialize()

    def initialize(self) -> None:
        with self.ledger.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    requester_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    brief_json TEXT,
                    safe_error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trace_run ON trace_events(run_id, created_at);
                CREATE TABLE IF NOT EXISTS model_invocations (
                    invocation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    model_alias TEXT NOT NULL,
                    provider_model TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    required_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(run_id, status);
                CREATE TABLE IF NOT EXISTS approval_decisions (
                    decision_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS human_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    model_alias TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_approval
                    ON human_feedback(approval_id);
                """
            )

    def start_run(self, run_id: str, request: RunRequest) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.ledger.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO runs(
                    run_id, opportunity_id, requester_id, status, request_json, created_at
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id,
                    request.opportunity_id,
                    request.requester_id,
                    request.model_dump_json(),
                    now,
                ),
            )

    def persist_result(self, result: RunResult) -> None:
        completed_at = result.completed_at or datetime.now(timezone.utc)
        with self.ledger.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, opportunity_id, requester_id, status, request_json, brief_json,
                    safe_error, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    brief_json=excluded.brief_json,
                    safe_error=excluded.safe_error,
                    completed_at=excluded.completed_at
                """,
                (
                    result.run_id,
                    result.request.opportunity_id,
                    result.request.requester_id,
                    result.status,
                    result.request.model_dump_json(),
                    result.brief.model_dump_json() if result.brief else None,
                    result.safe_error,
                    result.created_at.isoformat(),
                    completed_at.isoformat(),
                ),
            )

    def append_trace(self, event: TraceEvent) -> None:
        with self.ledger.connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_events(
                    event_id, run_id, category, message, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.category,
                    event.message,
                    json.dumps(event.metadata, sort_keys=True),
                    event.created_at.isoformat(),
                ),
            )

    def append_model_invocation(self, invocation: ModelInvocation) -> None:
        with self.ledger.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_invocations(
                    invocation_id, run_id, agent_name, model_alias, provider_model,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invocation.invocation_id,
                    invocation.run_id,
                    invocation.agent_name,
                    invocation.model_alias,
                    invocation.provider_model,
                    invocation.model_dump_json(),
                    invocation.created_at.isoformat(),
                ),
            )

    def save_approval(self, approval: ApprovalRequest) -> None:
        with self.ledger.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, run_id, recommendation_id, required_role, status,
                    payload_json, created_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.run_id,
                    approval.recommendation_id,
                    approval.required_role,
                    approval.status,
                    approval.model_dump_json(),
                    approval.created_at.isoformat(),
                    approval.decided_at.isoformat() if approval.decided_at else None,
                ),
            )

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self.ledger.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        return ApprovalRequest.model_validate_json(row["payload_json"]) if row else None

    def list_approvals(self, run_id: str | None = None) -> list[ApprovalRequest]:
        query = "SELECT payload_json FROM approvals"
        params: tuple[str, ...] = ()
        if run_id:
            query += " WHERE run_id = ?"
            params = (run_id,)
        query += " ORDER BY created_at"
        with self.ledger.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ApprovalRequest.model_validate_json(row["payload_json"]) for row in rows]

    def record_human_decision(
        self,
        approval: ApprovalRequest,
        decision: ApprovalDecisionRecord,
        feedback: HumanFeedbackRecord,
    ) -> None:
        updated = approval.model_copy(
            update={"status": decision.decision, "decided_at": decision.decided_at}
        )
        with self.ledger.connect() as conn:
            current = conn.execute(
                "SELECT status FROM approvals WHERE approval_id = ?", (approval.approval_id,)
            ).fetchone()
            if current is None:
                raise KeyError("approval_not_found")
            if current["status"] != "pending":
                raise ValueError("approval_already_decided")
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, payload_json = ?, decided_at = ?
                WHERE approval_id = ?
                """,
                (
                    decision.decision,
                    updated.model_dump_json(),
                    decision.decided_at.isoformat(),
                    approval.approval_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO approval_decisions(
                    decision_id, approval_id, run_id, reviewer_id, reviewer_role,
                    decision, rationale, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.approval_id,
                    decision.run_id,
                    decision.reviewer_id,
                    decision.reviewer_role,
                    decision.decision,
                    decision.rationale,
                    decision.decided_at.isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO human_feedback(
                    feedback_id, approval_id, run_id, recommendation_id, model_alias,
                    prompt_version, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.feedback_id,
                    feedback.approval_id,
                    feedback.run_id,
                    feedback.recommendation_id,
                    feedback.model_alias,
                    feedback.prompt_version,
                    feedback.model_dump_json(),
                    feedback.created_at.isoformat(),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, object] | None:
        with self.ledger.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_feedback(self) -> list[HumanFeedbackRecord]:
        with self.ledger.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM human_feedback ORDER BY created_at"
            ).fetchall()
        return [HumanFeedbackRecord.model_validate_json(row["payload_json"]) for row in rows]


class TraceRecorder:
    def __init__(self, run_ledger: RunLedger) -> None:
        self.run_ledger = run_ledger
        self.event_ids: list[str] = []

    def record(
        self,
        run_id: str,
        category: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=run_id,
            category=category,
            message=message,
            metadata=metadata or {},
        )
        self.run_ledger.append_trace(event)
        self.event_ids.append(event.event_id)
        return event
