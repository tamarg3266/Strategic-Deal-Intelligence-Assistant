from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from deal_intel.config.settings import load_config
from deal_intel.contracts.schemas import RunRequest
from deal_intel.orchestration.graph import run_workflow

SCENARIOS = (
    ("authorized_opp_1001", "OPP-1001", "USR-5001"),
    ("authorized_opp_1002", "OPP-1002", "USR-5002"),
    ("authorized_opp_1003", "OPP-1003", "USR-5003"),
)

@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    opportunity_id: str
    requester_id: str
    file_name: str
    run_id: str
    status: str
    safe_error: str | None
    file_path: Path


def _is_valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, json.JSONDecodeError):
        return False


async def _run_scenario(opportunity_id: str, requester_id: str) -> dict:
    config = load_config(Path("config/default.yaml"))
    request = RunRequest(opportunity_id=opportunity_id, requester_id=requester_id)
    result = await run_workflow(request, config=config)
    return result.model_dump(mode="json")


async def _generate(
    scenarios: tuple[tuple[str, str, str], ...] = SCENARIOS,
    output_dir: Path = Path("scripts/artifacts"),
    run_scenario: Callable[[str, str], Awaitable[dict[str, object]]] = _run_scenario,
) -> tuple[list[ScenarioResult], dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[ScenarioResult] = []
    for scenario_id, opportunity_id, requester_id in scenarios:
        result_payload = await run_scenario(opportunity_id, requester_id)
        file_name = f"{scenario_id}_{opportunity_id}_{requester_id}.json"
        artifact_path = output_dir / file_name
        artifact_path.write_text(
            json.dumps(result_payload, indent=2),
            encoding="utf-8",
        )

        results.append(
            ScenarioResult(
                scenario_id=scenario_id,
                opportunity_id=opportunity_id,
                requester_id=requester_id,
                file_name=file_name,
                run_id=result_payload.get("run_id", "unknown"),
                status=result_payload.get("status", "unknown"),
                safe_error=result_payload.get("safe_error"),
                file_path=artifact_path,
            )
        )

    summary = _build_summary(results)
    summary_path = output_dir / "evaluation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return results, summary


def _build_summary(results: list[ScenarioResult]) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    for item in results:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    failed_scenarios = [
        item.file_name for item in results if item.status not in {"allowed", "approval_required", "denied"}
    ]

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/generate_deliverables.py",
        "config_path": "config/default.yaml",
        "artifacts_folder": "scripts/artifacts",
        "required_scenario_count": len(SCENARIOS),
        "actual_scenario_count": len(results),
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "opportunity_id": item.opportunity_id,
                "requester_id": item.requester_id,
                "run_id": item.run_id,
                "status": item.status,
                "safe_error": item.safe_error,
                "artifact_file": item.file_name,
            }
            for item in results
        ],
        "status_counts": status_counts,
        "verification": {
            "all_artifacts_present": all(item.file_path.exists() for item in results),
            "all_run_ids_present": all(bool(item.run_id) for item in results),
            "all_statuses_present": all(bool(item.status) for item in results),
            "unique_run_ids": len({item.run_id for item in results}) == len(results),
            "all_scenario_json_valid": all(_is_valid_json(item.file_path) for item in results),
            "failed_scenarios": failed_scenarios,
        },
    }

    return summary


async def main() -> None:
    results, summary = await _generate()
    print("Deliverable artifacts generated in scripts/artifacts:")
    for item in results:
        print(
            f"  - {item.file_name} | opportunity={item.opportunity_id} "
            f"requester={item.requester_id} | status={item.status} run_id={item.run_id}"
        )
    print(f"Evaluation summary: {summary['generated_at_utc']} -> {summary['status_counts']}")


if __name__ == "__main__":
    asyncio.run(main())
