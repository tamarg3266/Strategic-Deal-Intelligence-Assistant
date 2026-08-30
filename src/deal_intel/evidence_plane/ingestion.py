from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from pathlib import Path

from deal_intel.contracts.schemas import AccessLevel, EvidenceRecord


class SourceIngestionPlan:
    required_sources = (
        "synthetic_data/salesforce/accounts.tsv",
        "synthetic_data/salesforce/opportunities.tsv",
        "synthetic_data/salesforce/contacts.tsv",
        "synthetic_data/gong/gong_call_summaries.tsv",
        "synthetic_data/gong/transcripts/*.md",
        "synthetic_data/pricing/pricing_notes.tsv",
        "synthetic_data/policies/deal_desk_policy.md",
        "synthetic_data/slack/account_team_updates.tsv",
    )


class EvidenceIngestor:
    """Normalizes every assignment source into stable, permission-aware records."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    def load_records(self) -> list[EvidenceRecord]:
        opportunities = self._read_tsv("salesforce/opportunities.tsv")
        opportunity_by_id = {row["opportunity_id"]: row for row in opportunities}
        opportunities_by_account: dict[str, list[dict[str, str]]] = {}
        for row in opportunities:
            opportunities_by_account.setdefault(row["account_id"], []).append(row)

        records = [
            *self._load_opportunities(opportunities),
            *self._load_accounts(opportunities_by_account),
            *self._load_contacts(opportunities_by_account),
            *self._load_gong(opportunity_by_id),
            *self._load_pricing(opportunity_by_id),
            *self._load_policy(opportunities),
            *self._load_slack_records(),
        ]
        evidence_ids = [record.evidence_id for record in records]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence ingestion produced duplicate evidence IDs")
        return records

    def _load_opportunities(self, rows: list[dict[str, str]]) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for row in rows:
            opportunity_id = self._required(row, "opportunity_id")
            records.append(
                EvidenceRecord(
                    evidence_id=f"EV-SF-OPPORTUNITY-{opportunity_id}",
                    source_file="synthetic_data/salesforce/opportunities.tsv",
                    source_record_id=opportunity_id,
                    record_kind="salesforce_opportunity",
                    source_type="salesforce",
                    source_access_level=(
                        "restricted"
                        if self._bool(row.get("restricted_access", "false"))
                        else "standard"
                    ),
                    account_id=self._required(row, "account_id"),
                    opportunity_id=opportunity_id,
                    source_date=row.get("close_date") or None,
                    text=self._row_text("Salesforce opportunity", row),
                    metadata=row,
                )
            )
        return records

    def _load_accounts(
        self, opportunities_by_account: dict[str, list[dict[str, str]]]
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for row in self._read_tsv("salesforce/accounts.tsv"):
            account_id = self._required(row, "account_id")
            for opportunity in opportunities_by_account.get(account_id, []):
                opportunity_id = opportunity["opportunity_id"]
                records.append(
                    EvidenceRecord(
                        evidence_id=f"EV-SF-ACCOUNT-{opportunity_id}-{account_id}",
                        source_file="synthetic_data/salesforce/accounts.tsv",
                        source_record_id=account_id,
                        record_kind="salesforce_account",
                        source_type="salesforce",
                        source_access_level=self._access_level(
                            row.get("access_level", "standard")
                        ),
                        account_id=account_id,
                        opportunity_id=opportunity_id,
                        text=self._row_text("Salesforce account", row),
                        metadata=row,
                    )
                )
        return records

    def _load_contacts(
        self, opportunities_by_account: dict[str, list[dict[str, str]]]
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for row in self._read_tsv("salesforce/contacts.tsv"):
            account_id = self._required(row, "account_id")
            for opportunity in opportunities_by_account.get(account_id, []):
                opportunity_id = opportunity["opportunity_id"]
                access_level: AccessLevel = (
                    "restricted"
                    if self._bool(opportunity.get("restricted_access", "false"))
                    else "standard"
                )
                contact_id = self._required(row, "contact_id")
                records.append(
                    EvidenceRecord(
                        evidence_id=f"EV-SF-CONTACT-{opportunity_id}-{contact_id}",
                        source_file="synthetic_data/salesforce/contacts.tsv",
                        source_record_id=contact_id,
                        record_kind="salesforce_contact",
                        source_type="salesforce",
                        source_access_level=access_level,
                        account_id=account_id,
                        opportunity_id=opportunity_id,
                        source_date=row.get("last_interaction_date") or None,
                        text=self._row_text("Salesforce contact", row),
                        metadata=row,
                    )
                )
        return records

    def _load_gong(self, opportunity_by_id: dict[str, dict[str, str]]) -> list[EvidenceRecord]:
        summaries = self._read_tsv("gong/gong_call_summaries.tsv")
        records: list[EvidenceRecord] = []
        summary_by_call: dict[str, dict[str, str]] = {}
        for row in summaries:
            call_id = self._required(row, "call_id")
            opportunity_id = self._required(row, "opportunity_id")
            if opportunity_id not in opportunity_by_id:
                raise ValueError(f"Gong row references unknown opportunity: {opportunity_id}")
            summary_by_call[call_id] = row
            records.append(
                EvidenceRecord(
                    evidence_id=f"EV-GONG-SUMMARY-{call_id}",
                    source_file="synthetic_data/gong/gong_call_summaries.tsv",
                    source_record_id=call_id,
                    record_kind="gong_call_summary",
                    source_type="gong",
                    source_access_level=self._access_level(row["source_access_level"]),
                    account_id=self._required(row, "account_id"),
                    opportunity_id=opportunity_id,
                    source_date=row.get("call_date") or None,
                    text=self._row_text("Gong call summary", row),
                    metadata=row,
                )
            )

        transcript_pattern = re.compile(r"^(OPP-\d+)_(CALL-\d+)\.md$")
        for path in sorted((self.data_root / "gong" / "transcripts").glob("*.md")):
            match = transcript_pattern.match(path.name)
            if not match:
                raise ValueError(f"Unexpected transcript filename: {path.name}")
            opportunity_id, call_id = match.groups()
            summary = summary_by_call.get(call_id)
            if summary is None or summary["opportunity_id"] != opportunity_id:
                raise ValueError(f"Transcript has no matching Gong summary: {path.name}")
            records.append(
                EvidenceRecord(
                    evidence_id=f"EV-GONG-TRANSCRIPT-{call_id}",
                    source_file=f"synthetic_data/gong/transcripts/{path.name}",
                    source_record_id=call_id,
                    record_kind="gong_transcript",
                    source_type="gong",
                    source_access_level=self._access_level(summary["source_access_level"]),
                    account_id=summary["account_id"],
                    opportunity_id=opportunity_id,
                    source_date=summary["call_date"],
                    text=path.read_text(encoding="utf-8"),
                    metadata={"title": summary["title"]},
                )
            )
        return records

    def _load_pricing(
        self, opportunity_by_id: dict[str, dict[str, str]]
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for row in self._read_tsv("pricing/pricing_notes.tsv"):
            opportunity_id = self._required(row, "opportunity_id")
            opportunity = opportunity_by_id.get(opportunity_id)
            if opportunity is None:
                raise ValueError(
                    f"Pricing row references unknown opportunity: {opportunity_id}"
                )
            requested_discount = float(row["requested_discount"])
            renewal_uplift = float(row["renewal_uplift"])
            approval_status = row["approval_status"]
            sensitive = (
                requested_discount > 10
                or renewal_uplift < 0
                or approval_status != "not_required"
                or self._bool(opportunity["restricted_access"])
            )
            note_id = self._required(row, "pricing_note_id")
            records.append(
                EvidenceRecord(
                    evidence_id=f"EV-PRICING-{note_id}",
                    source_file="synthetic_data/pricing/pricing_notes.tsv",
                    source_record_id=note_id,
                    record_kind="pricing_note",
                    source_type="pricing",
                    source_access_level="sensitive_pricing" if sensitive else "standard",
                    account_id=opportunity["account_id"],
                    opportunity_id=opportunity_id,
                    text=self._row_text("Pricing note", row),
                    metadata=row,
                )
            )
        return records

    def _load_policy(self, opportunities: list[dict[str, str]]) -> list[EvidenceRecord]:
        path = self.data_root / "policies" / "deal_desk_policy.md"
        policy_text = path.read_text(encoding="utf-8")
        return [
            EvidenceRecord(
                evidence_id=f"EV-POLICY-{row['opportunity_id']}-DEAL-DESK",
                source_file="synthetic_data/policies/deal_desk_policy.md",
                source_record_id="DEAL-DESK-POLICY-V1",
                record_kind="deal_desk_policy",
                source_type="policies",
                source_access_level="standard",
                account_id=row["account_id"],
                opportunity_id=row["opportunity_id"],
                text=policy_text,
                metadata={"policy_version": "v1"},
            )
            for row in opportunities
        ]

    def _load_slack_records(self) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for row in self._read_tsv("slack/account_team_updates.tsv", required=False):
            update_id = self._required(row, "update_id")
            records.append(
                EvidenceRecord(
                    evidence_id=f"EV-SLACK-{update_id}",
                    source_file="synthetic_data/slack/account_team_updates.tsv",
                    source_record_id=update_id,
                    record_kind="slack_account_team_update",
                    source_type="slack",
                    source_access_level=self._access_level(row["source_access_level"]),
                    account_id=self._required(row, "account_id"),
                    opportunity_id=self._required(row, "opportunity_id"),
                    source_date=row.get("update_date") or None,
                    text=self._required(row, "update_text"),
                    metadata={
                        key: value for key, value in row.items() if key != "update_text"
                    },
                )
            )
        return records

    def _read_tsv(self, relative_path: str, required: bool = True) -> list[dict[str, str]]:
        path = self.data_root / relative_path
        if not path.exists():
            if required:
                raise FileNotFoundError(path)
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    @staticmethod
    def _row_text(label: str, row: dict[str, str]) -> str:
        return f"{label}: {json.dumps(row, sort_keys=True, ensure_ascii=True)}"

    @staticmethod
    def _required(row: dict[str, str], column: str) -> str:
        value = row.get(column, "").strip()
        if not value:
            raise ValueError(f"Ingestion missing required column value: {column}")
        return value

    @staticmethod
    def _bool(value: str) -> bool:
        return value.strip().lower() == "true"

    @staticmethod
    def _access_level(value: str) -> AccessLevel:
        if value not in {"standard", "sensitive_pricing", "restricted"}:
            raise ValueError(f"Invalid source_access_level: {value}")
        return value  # type: ignore[return-value]

    @staticmethod
    def evidence_ids(records: Iterable[EvidenceRecord]) -> set[str]:
        return {record.evidence_id for record in records}
