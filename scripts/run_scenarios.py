import asyncio
from pathlib import Path

from deal_intel.config.settings import load_config
from deal_intel.contracts.schemas import RunRequest
from deal_intel.orchestration.graph import run_workflow

SCENARIOS = (
    ("OPP-1001", "USR-5001"),
    ("OPP-1002", "USR-5002"),
    ("OPP-1003", "USR-5003"),
    ("OPP-1003", "USR-5007"),
)


async def main() -> None:
    config = load_config(Path("config/default.yaml"))
    for opportunity_id, requester_id in SCENARIOS:
        result = await run_workflow(
            RunRequest(opportunity_id=opportunity_id, requester_id=requester_id),
            config=config,
        )
        print(
            f"{opportunity_id} requester={requester_id} "
            f"run_id={result.run_id} status={result.status}"
        )


if __name__ == "__main__":
    asyncio.run(main())
