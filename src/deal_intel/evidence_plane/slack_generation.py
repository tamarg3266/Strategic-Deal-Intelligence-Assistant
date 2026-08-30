import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SLACK_COLUMNS = [
    "update_id",
    "opportunity_id",
    "account_id",
    "update_date",
    "channel",
    "author_role",
    "synthetic_notice",
    "source_access_level",
    "context_role",
    "evidence_basis_call_id",
    "update_text",
]


@dataclass(frozen=True)
class SlackUpdate:
    update_id: str
    opportunity_id: str
    account_id: str
    update_date: str
    channel: str
    author_role: str
    synthetic_notice: str
    source_access_level: str
    context_role: str
    evidence_basis_call_id: str
    update_text: str

    def as_row(self) -> dict[str, str]:
        return {
            "update_id": self.update_id,
            "opportunity_id": self.opportunity_id,
            "account_id": self.account_id,
            "update_date": self.update_date,
            "channel": self.channel,
            "author_role": self.author_role,
            "synthetic_notice": self.synthetic_notice,
            "source_access_level": self.source_access_level,
            "context_role": self.context_role,
            "evidence_basis_call_id": self.evidence_basis_call_id,
            "update_text": self.update_text,
        }


def generate_slack_updates() -> list[SlackUpdate]:
    """Create deterministic synthetic Slack-style updates for the assignment."""
    return [
        SlackUpdate(
            "SLACK-1001-01",
            "OPP-1001",
            "ACC-2001",
            "2026-04-20",
            "#deal-northstar-renewal",
            "Account Owner",
            "SYNTHETIC",
            "standard",
            "reinforces_known_fact",
            "CALL-008",
            "Customer-side stakeholders remain aligned on renewal if the owner matrix, "
            "migration success metrics, and payment schedule arrive before the 2026-04-28 "
            "package deadline.",
        ),
        SlackUpdate(
            "SLACK-1001-02",
            "OPP-1001",
            "ACC-2001",
            "2026-04-23",
            "#deal-northstar-renewal",
            "Customer Success Lead",
            "SYNTHETIC",
            "standard",
            "adds_missing_context",
            "CALL-006",
            "Plant operations asked for the support bridge to include one named escalation "
            "lead per region, which was not fully captured in the formal migration playbook "
            "notes.",
        ),
        SlackUpdate(
            "SLACK-1002-01",
            "OPP-1002",
            "ACC-2002",
            "2026-04-27",
            "#deal-meridian-expansion",
            "Sales Engineer",
            "SYNTHETIC",
            "standard",
            "reinforces_known_fact",
            "CALL-018",
            "The proof is still viewed as directionally successful, but the reporting export "
            "retest and incident owner map remain required before commercial approval can move "
            "forward.",
        ),
        SlackUpdate(
            "SLACK-1002-02",
            "OPP-1002",
            "ACC-2002",
            "2026-05-02",
            "#deal-meridian-expansion",
            "Account Owner",
            "SYNTHETIC",
            "standard",
            "introduces_ambiguity",
            "CALL-017",
            "Finance is open to milestone payments, while operations is asking for enough "
            "enablement coverage that a strict services cap may conflict with rollout success.",
        ),
        SlackUpdate(
            "SLACK-1003-01",
            "OPP-1003",
            "ACC-2003",
            "2026-04-29",
            "#deal-eclipse-restricted",
            "Deal Desk",
            "SYNTHETIC",
            "sensitive_pricing",
            "reinforces_known_fact",
            "CALL-027",
            "Any concession package for this restricted renewal must keep discount handling "
            "in the approval workflow before the account team prepares customer-facing language.",
        ),
        SlackUpdate(
            "SLACK-1003-02",
            "OPP-1003",
            "ACC-2003",
            "2026-05-06",
            "#deal-eclipse-restricted",
            "Legal",
            "SYNTHETIC",
            "restricted",
            "introduces_ambiguity",
            "CALL-023",
            "Legal wants approved liability language to lead the internal plan, while the "
            "commercial team is still debating whether cost relief or risk mitigation should "
            "anchor the negotiation.",
        ),
    ]


def validate_slack_updates(rows: list[SlackUpdate]) -> None:
    by_opportunity: dict[str, int] = {}
    context_roles = set()
    seen_ids = set()

    for row in rows:
        if row.update_id in seen_ids:
            raise ValueError(f"Duplicate Slack update ID: {row.update_id}")
        seen_ids.add(row.update_id)

        if row.synthetic_notice != "SYNTHETIC":
            raise ValueError(f"{row.update_id} is not marked synthetic")
        if row.source_access_level not in {"standard", "sensitive_pricing", "restricted"}:
            raise ValueError(f"{row.update_id} has invalid source access level")
        if row.context_role not in {
            "reinforces_known_fact",
            "adds_missing_context",
            "introduces_ambiguity",
        }:
            raise ValueError(f"{row.update_id} has invalid context role")
        if not row.evidence_basis_call_id.startswith("CALL-"):
            raise ValueError(f"{row.update_id} must reference a Gong call")
        if date.fromisoformat(row.update_date) >= date(2026, 6, 6):
            raise ValueError(f"{row.update_id} is outside the scenario chronology")

        by_opportunity[row.opportunity_id] = by_opportunity.get(row.opportunity_id, 0) + 1
        context_roles.add(row.context_role)

    for opportunity_id in {"OPP-1001", "OPP-1002", "OPP-1003"}:
        if by_opportunity.get(opportunity_id, 0) < 2:
            raise ValueError(f"{opportunity_id} needs at least two Slack updates")

    required_context = {
        "reinforces_known_fact",
        "adds_missing_context",
        "introduces_ambiguity",
    }
    missing_context = required_context - context_roles
    if missing_context:
        raise ValueError(f"Missing Slack context coverage: {sorted(missing_context)}")


def write_slack_updates(path: Path, rows: list[SlackUpdate]) -> None:
    validate_slack_updates(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SLACK_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_row())
