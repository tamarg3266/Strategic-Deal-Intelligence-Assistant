import asyncio
from typing import Literal

import httpx
from pydantic import BaseModel

from deal_intel.model_runtime.litellm import LiteLLMGateway


class ProbeOutput(BaseModel):
    status: Literal["ready"]


class StubResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [{"message": {"content": '{"status": "ready"}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }


class StubAsyncClient:
    init_kwargs: dict[str, object] = {}
    request_json: dict[str, object] = {}
    request_headers: dict[str, str] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).init_kwargs = kwargs

    async def __aenter__(self) -> "StubAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> StubResponse:
        assert url == "https://litellm.example.test/v1/chat/completions"
        type(self).request_json = json
        type(self).request_headers = headers
        return StubResponse()


def test_gateway_sends_json_mode_tls_and_bearer_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        "deal_intel.model_runtime.litellm.httpx.AsyncClient",
        StubAsyncClient,
    )
    gateway = LiteLLMGateway(
        endpoint="https://litellm.example.test",
        aliases={"extraction_model": "default"},
        api_key="secret",
        verify_tls=False,
        schema_repair_attempts=0,
    )

    output = asyncio.run(
        gateway.generate_structured(
            model_alias="extraction_model",
            system="system",
            developer="developer",
            user="user",
            output_schema=ProbeOutput,
            run_id="run-1",
            agent_name="probe",
            prompt_version="probe.v1",
        )
    )

    response_format = StubAsyncClient.request_json["response_format"]
    assert isinstance(response_format, dict)
    assert response_format == {"type": "json_object"}
    assert StubAsyncClient.init_kwargs["verify"] is False
    assert StubAsyncClient.request_headers == {"Authorization": "Bearer secret"}
    assert output.status == "ready"


def test_gateway_retries_only_transient_http_statuses() -> None:
    request = httpx.Request("POST", "https://litellm.example.test")
    rate_limited = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=httpx.Response(429, request=request),
    )
    bad_request = httpx.HTTPStatusError(
        "bad request",
        request=request,
        response=httpx.Response(400, request=request),
    )

    assert LiteLLMGateway._retryable(rate_limited) is True
    assert LiteLLMGateway._retryable(bad_request) is False
