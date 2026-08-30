from collections import Counter
from datetime import date

from deal_intel.evidence_plane.slack_generation import (
    generate_slack_updates,
    validate_slack_updates,
)


def test_generated_slack_updates_satisfy_assignment_contract() -> None:
    rows = generate_slack_updates()

    validate_slack_updates(rows)

    counts = Counter(row.opportunity_id for row in rows)
    assert counts == {"OPP-1001": 2, "OPP-1002": 2, "OPP-1003": 2}
    assert {row.synthetic_notice for row in rows} == {"SYNTHETIC"}
    assert {"reinforces_known_fact", "adds_missing_context", "introduces_ambiguity"} <= {
        row.context_role for row in rows
    }
    assert all(date.fromisoformat(row.update_date) < date(2026, 6, 6) for row in rows)
