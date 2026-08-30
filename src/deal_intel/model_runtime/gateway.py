from collections.abc import Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel

from deal_intel.contracts.schemas import ModelInvocation

OutputT = TypeVar("OutputT", bound=BaseModel)
InvocationObserver = Callable[[ModelInvocation], None]


class ModelGateway(Protocol):
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
        max_output_tokens: int | None = None,
    ) -> OutputT:
        ...

    async def aclose(self) -> None:
        ...
