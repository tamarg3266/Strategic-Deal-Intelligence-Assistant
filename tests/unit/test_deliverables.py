import asyncio
import json
import shutil
from pathlib import Path

from scripts import generate_deliverables


def _fake_run_scenario(opportunity_id: str, requester_id: str) -> dict[str, object]:
    return {
        "run_id": f"RUN-{opportunity_id}-{requester_id}",
        "status": "allowed",
        "safe_error": None,
        "request": {
            "opportunity_id": opportunity_id,
            "requester_id": requester_id,
            "user_input": "Generate an internal Strategic Deal Intelligence Brief.",
        },
    }


async def fake_runner(opportunity_id: str, requester_id: str) -> dict[str, object]:
    return _fake_run_scenario(opportunity_id, requester_id)


def _clean_output_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_generate_deliverables_writes_all_required_files() -> None:
    scenarios = (
        ("authorized_opp_1001", "OPP-1001", "USR-5001"),
        ("authorized_opp_1002", "OPP-1002", "USR-5002"),
        ("authorized_opp_1003", "OPP-1003", "USR-5003"),
    )
    output_dir = _clean_output_dir(Path("tests/artifacts/generate"))

    results, summary = asyncio.run(
        generate_deliverables._generate(
            scenarios=scenarios,
            output_dir=output_dir,
            run_scenario=fake_runner,
        )
    )

    assert summary["required_scenario_count"] == len(scenarios)
    assert summary["actual_scenario_count"] == len(scenarios)
    assert summary["verification"]["all_artifacts_present"] is True
    assert summary["verification"]["all_run_ids_present"] is True
    assert summary["verification"]["all_statuses_present"] is True
    assert summary["verification"]["all_scenario_json_valid"] is True
    assert summary["verification"]["unique_run_ids"] is True
    assert summary["verification"]["failed_scenarios"] == []

    assert len(results) == len(scenarios)
    for result in results:
        artifact = output_dir / result.file_name
        assert artifact.exists()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["run_id"] == result.run_id
        assert payload["status"] == result.status
        assert payload["safe_error"] == result.safe_error

    file_names = {item["artifact_file"] for item in summary["scenarios"]}
    assert file_names == {
        "authorized_opp_1001_OPP-1001_USR-5001.json",
        "authorized_opp_1002_OPP-1002_USR-5002.json",
        "authorized_opp_1003_OPP-1003_USR-5003.json",
    }
    shutil.rmtree(output_dir)


def test_generate_deliverables_summary_reflects_failures() -> None:
    async def failing_runner(opportunity_id: str, requester_id: str) -> dict[str, object]:
        return {
            "run_id": f"RUN-{opportunity_id}",
            "status": "failed",
            "safe_error": "model_error",
            "request": {
                "opportunity_id": opportunity_id,
                "requester_id": requester_id,
                "user_input": "Generate an internal Strategic Deal Intelligence Brief.",
            },
        }

    scenarios = (("scenario_a", "OPP-1001", "USR-5001"),)
    output_dir = _clean_output_dir(Path("tests/artifacts/generate_failure"))
    _, summary = asyncio.run(
        generate_deliverables._generate(
            scenarios=scenarios,
            output_dir=output_dir,
            run_scenario=failing_runner,
        )
    )

    assert summary["verification"]["failed_scenarios"] == [
        "scenario_a_OPP-1001_USR-5001.json"
    ]
    assert summary["status_counts"]["failed"] == 1
    shutil.rmtree(output_dir)
