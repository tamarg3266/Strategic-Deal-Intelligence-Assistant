# Script Deliverables (Current Implementation)

## Location

Generated artifacts are written to this folder by `scripts/generate_deliverables.py`:
`C:\projects\strategic-agent\Cato-IS-AI-Engineer-Exam\scripts\artifacts`

## Contents

### Scenario outputs

Each file below is a complete run result for one authorized scenario using live
system orchestration (`run_workflow`) and the current model-backed implementation:

- `authorized_opp_1001_OPP-1001_USR-5001.json`
- `authorized_opp_1002_OPP-1002_USR-5002.json`
- `authorized_opp_1003_OPP-1003_USR-5003.json`

### Evaluation summary

- `evaluation_summary.json`

## How it was generated

Command used:

```bash
& .venv\Scripts\python.exe scripts\generate_deliverables.py
```

The generator uses `SCENARIOS = (("authorized_opp_1001", "OPP-1001", "USR-5001"), ("authorized_opp_1002", "OPP-1002", "USR-5002"), ("authorized_opp_1003", "OPP-1003", "USR-5003"))`.

## Validation checks run

- JSON parse checks for all 3 scenario files and `evaluation_summary.json`.
- `evaluation_summary.json` verified:
  - `required_scenario_count == 3`
  - `actual_scenario_count == 3`
  - `all_artifacts_present == true`
  - `all_run_ids_present == true`
  - `all_statuses_present == true`
  - `all_scenario_json_valid == true`
  - `failed_scenarios == []`

As of generation time:
- `required_scenario_count`: 3
- `actual_scenario_count`: 3
- Status distribution: `{"approval_required": 3}`
- All run IDs are present and unique.
