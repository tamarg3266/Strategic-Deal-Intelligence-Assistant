from pathlib import Path

from deal_intel.evidence_plane.slack_generation import generate_slack_updates, write_slack_updates


def main() -> None:
    output_path = Path("synthetic_data/slack/account_team_updates.tsv")
    write_slack_updates(output_path, generate_slack_updates())
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
