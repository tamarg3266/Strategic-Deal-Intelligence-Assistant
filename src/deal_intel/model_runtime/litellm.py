from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx
from pydantic import ValidationError

from deal_intel.contracts.schemas import ModelInvocation
from deal_intel.model_runtime.gateway import InvocationObserver, OutputT


class LiteLLMGateway:
    """OpenAI-compatible LiteLLM proxy gateway with typed output validation."""

    def __init__(
        self,
        endpoint: str,
        aliases: dict[str, str],
        *,
        timeout_seconds: float = 60,
        api_key: str | None = None,
        verify_tls: bool = True,
        max_output_tokens: int = 4_000,
        temperature: float = 0,
        schema_repair_attempts: int = 1,
        transport_retries: int = 2,
        retry_backoff_seconds: float = 1,
        invocation_observer: InvocationObserver | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.aliases = aliases
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self.verify_tls = verify_tls
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.schema_repair_attempts = schema_repair_attempts
        self.transport_retries = transport_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.invocation_observer = invocation_observer

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
        if model_alias not in self.aliases:
            raise KeyError(f"Unknown model alias: {model_alias}")
        provider_model = self.aliases[model_alias]
        output_json_schema = output_schema.model_json_schema()
        schema_json = json.dumps(output_json_schema, sort_keys=True)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "developer",
                "content": f"{developer}\n\nOUTPUT JSON SCHEMA\n{schema_json}",
            },
            {"role": "user", "content": user},
        ]
        input_hash = hashlib.sha256(
            json.dumps(messages, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.perf_counter()
        last_error: Exception | None = None
        usage: dict[str, int | float] = {}

        schema_attempt = 0
        transport_retry = 0
        while schema_attempt <= self.schema_repair_attempts:
            try:
                payload = {
                    "model": provider_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": self.temperature,
                    "max_tokens": self.max_output_tokens,
                }
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    verify=self.verify_tls,
                ) as client:
                    response = await client.post(
                        f"{self.endpoint}/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                body = response.json()
                usage = body.get("usage") or {}
                if body.get("response_cost") is not None:
                    usage["response_cost"] = body["response_cost"]
                content = body["choices"][0]["message"]["content"]
                output = output_schema.model_validate_json(content)
                self._observe(
                    run_id=run_id,
                    agent_name=agent_name,
                    model_alias=model_alias,
                    provider_model=provider_model,
                    prompt_version=prompt_version,
                    input_hash=input_hash,
                    output_schema=output_schema.__name__,
                    started=started,
                    usage=usage,
                    success=True,
                )
                return output
            except (ValidationError, json.JSONDecodeError, KeyError, TypeError) as exc:
                last_error = exc
                if schema_attempt >= self.schema_repair_attempts:
                    break
                schema_attempt += 1
                validation_feedback = self._validation_feedback(exc)
                messages.append(
                    {
                        "role": "developer",
                        "content": (
                            "The previous response failed schema validation. Return only one JSON "
                            "object matching the supplied schema. Do not add prose or markdown. "
                            f"Validation feedback: {validation_feedback}"
                        ),
                    }
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if self._retryable(exc) and transport_retry < self.transport_retries:
                    delay = self.retry_backoff_seconds * (2**transport_retry)
                    transport_retry += 1
                    await asyncio.sleep(delay)
                    continue
                break

        self._observe(
            run_id=run_id,
            agent_name=agent_name,
            model_alias=model_alias,
            provider_model=provider_model,
            prompt_version=prompt_version,
            input_hash=input_hash,
            output_schema=output_schema.__name__,
            started=started,
            usage=usage,
            success=False,
            error_type=self._error_type(last_error),
        )
        raise RuntimeError("Model generation failed validation or transport checks") from last_error

    def _observe(
        self,
        *,
        run_id: str,
        agent_name: str,
        model_alias: str,
        provider_model: str,
        prompt_version: str,
        input_hash: str,
        output_schema: str,
        started: float,
        usage: dict[str, int | float],
        success: bool,
        error_type: str | None = None,
    ) -> None:
        if self.invocation_observer is None:
            return
        self.invocation_observer(
            ModelInvocation(
                run_id=run_id,
                agent_name=agent_name,
                model_alias=model_alias,
                provider_model=provider_model,
                prompt_version=prompt_version,
                input_hash=input_hash,
                output_schema=output_schema,
                latency_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=self._integer_usage(usage.get("prompt_tokens")),
                output_tokens=self._integer_usage(usage.get("completion_tokens")),
                estimated_cost_usd=self._float_usage(
                    usage.get("cost") or usage.get("response_cost")
                ),
                success=success,
                error_type=error_type,
            )
        )

    @staticmethod
    def _integer_usage(value: int | float | None) -> int | None:
        return int(value) if value is not None else None

    @staticmethod
    def _float_usage(value: int | float | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _retryable(error: httpx.HTTPError) -> bool:
        if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            return status in {408, 409, 429} or status >= 500
        return False

    @staticmethod
    def _error_type(error: Exception | None) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            return f"HTTP_{error.response.status_code}"
        return type(error).__name__ if error else "unknown_model_error"

    @staticmethod
    def _validation_feedback(error: Exception) -> str:
        if not isinstance(error, ValidationError):
            return type(error).__name__
        summaries = []
        for item in error.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in item["loc"]) or "root"
            summaries.append(f"{location}: {item['msg']}")
        return "; ".join(summaries[:10])
