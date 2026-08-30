from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from deal_intel.model_runtime.gateway import OutputT


class FakeGateway:
    """Deterministic gateway for tests; production workflow rejects it in live mode."""

    def __init__(self, outputs: dict[str, BaseModel | list[BaseModel]]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, str]] = []
        self._indices: defaultdict[str, int] = defaultdict(int)

    async def generate_structured(
        self,
        *,
        model_alias: str,
        system: str,
        developer: str,
        user: str,
        output_schema: type[OutputT],
        run_id: str,
        agent_name: str,
        prompt_version: str,
    ) -> OutputT:
        del system, developer
        self.calls.append(
            {
                "run_id": run_id,
                "agent_name": agent_name,
                "model_alias": model_alias,
                "prompt_version": prompt_version,
                "user": user,
            }
        )
        configured = self.outputs.get(agent_name, self.outputs.get(model_alias))
        if configured is None:
            raise KeyError(f"No fake output configured for {agent_name} or {model_alias}")
        if isinstance(configured, list):
            index = self._indices[agent_name]
            self._indices[agent_name] += 1
            configured = configured[index]
        return output_schema.model_validate(configured.model_dump())
