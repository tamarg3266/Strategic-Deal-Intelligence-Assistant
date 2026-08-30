from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from deal_intel.config.settings import AppConfig
from deal_intel.evidence_plane.ingestion import EvidenceIngestor
from deal_intel.model_runtime.litellm import LiteLLMGateway


class RuntimeCheck(BaseModel):
    name: str
    status: Literal["pass", "fail", "skip"]
    detail: str


class DiagnosticsReport(BaseModel):
    environment: str
    litellm_endpoint: str
    ready: bool
    checks: list[RuntimeCheck]


class ModelProbe(BaseModel):
    status: Literal["ready"]


async def run_diagnostics(
    config: AppConfig,
    *,
    include_model: bool = True,
    probe_model: bool = False,
) -> DiagnosticsReport:
    checks = [
        _check_paths(config),
        _check_ingestion(config),
        _check_sqlite(config.paths.sqlite_path),
    ]

    model_check: RuntimeCheck | None = None
    if include_model:
        model_check = await _check_model_endpoint(config)
        checks.append(model_check)
    else:
        checks.append(
            RuntimeCheck(
                name="litellm_endpoint",
                status="skip",
                detail="Skipped by --offline.",
            )
        )

    if probe_model:
        if model_check is not None and model_check.status == "pass":
            checks.append(await _check_structured_generation(config))
        else:
            checks.append(
                RuntimeCheck(
                    name="structured_generation",
                    status="skip",
                    detail="Skipped because the LiteLLM endpoint check failed.",
                )
            )

    return DiagnosticsReport(
        environment=config.environment,
        litellm_endpoint=config.litellm.base_url,
        ready=not any(check.status == "fail" for check in checks),
        checks=checks,
    )


def _check_paths(config: AppConfig) -> RuntimeCheck:
    required_prompts = {
        "base_rules.md",
        "commercial_analyst.md",
        "buyer_signal_analyst.md",
        "risk_approval_analyst.md",
        "brief_composer.md",
    }
    missing: list[str] = []
    if not config.paths.data_root.is_dir():
        missing.append(str(config.paths.data_root))
    missing.extend(
        str(config.paths.prompt_root / name)
        for name in sorted(required_prompts)
        if not (config.paths.prompt_root / name).is_file()
    )
    if missing:
        return RuntimeCheck(
            name="configured_paths",
            status="fail",
            detail=f"Missing required path(s): {', '.join(missing)}",
        )

    config.paths.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    config.paths.artifact_dir.mkdir(parents=True, exist_ok=True)
    return RuntimeCheck(
        name="configured_paths",
        status="pass",
        detail="Data, prompts, database parent, and artifact directory are available.",
    )


def _check_ingestion(config: AppConfig) -> RuntimeCheck:
    try:
        records = EvidenceIngestor(config.paths.data_root).load_records()
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        return RuntimeCheck(
            name="source_ingestion",
            status="fail",
            detail=f"Source validation failed ({type(exc).__name__}).",
        )

    opportunity_ids = {record.opportunity_id for record in records}
    source_types = {record.source_type for record in records}
    expected_opportunities = {"OPP-1001", "OPP-1002", "OPP-1003"}
    expected_sources = {"salesforce", "gong", "pricing", "policies", "slack"}
    if not expected_opportunities.issubset(opportunity_ids):
        return RuntimeCheck(
            name="source_ingestion",
            status="fail",
            detail="The normalized evidence does not cover all three opportunities.",
        )
    if not expected_sources.issubset(source_types):
        return RuntimeCheck(
            name="source_ingestion",
            status="fail",
            detail="One or more required source types are absent.",
        )
    return RuntimeCheck(
        name="source_ingestion",
        status="pass",
        detail=f"Loaded {len(records)} records across all required source types.",
    )


def _check_sqlite(path: Path) -> RuntimeCheck:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("SELECT 1").fetchone()
            connection.execute(
                "CREATE VIRTUAL TABLE temp.fts5_readiness USING fts5(content)"
            )
    except sqlite3.Error as exc:
        return RuntimeCheck(
            name="sqlite",
            status="fail",
            detail=f"SQLite check failed ({type(exc).__name__}).",
        )
    return RuntimeCheck(
        name="sqlite",
        status="pass",
        detail=f"SQLite is writable and FTS5 is available at {path}.",
    )


async def _check_model_endpoint(config: AppConfig) -> RuntimeCheck:
    headers = _authorization_headers(config)
    try:
        async with httpx.AsyncClient(
            timeout=min(config.litellm.timeout_seconds, 10),
            verify=config.litellm.verify_tls,
        ) as client:
            response = await client.get(
                f"{config.litellm.base_url}/v1/models",
                headers=headers,
            )
            response.raise_for_status()
            available_models = _model_ids(response)
            configured_models = set(config.litellm.model_aliases.values())
            missing_models = sorted(configured_models - available_models)
            if missing_models:
                return RuntimeCheck(
                    name="litellm_endpoint",
                    status="fail",
                    detail=(
                        "Configured model IDs are not exposed by LiteLLM: "
                        f"{', '.join(missing_models)}."
                    ),
                )
            return RuntimeCheck(
                name="litellm_endpoint",
                status="pass",
                detail=(
                    "LiteLLM authentication succeeded and all configured model "
                    "IDs are available."
                ),
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            detail = "LiteLLM rejected authentication; set LITELLM_API_KEY."
        else:
            detail = f"LiteLLM returned HTTP {exc.response.status_code}."
        return RuntimeCheck(
            name="litellm_endpoint",
            status="fail",
            detail=detail,
        )
    except httpx.HTTPError as exc:
        return RuntimeCheck(
            name="litellm_endpoint",
            status="fail",
            detail=f"LiteLLM is unavailable ({type(exc).__name__}).",
        )
    except ValueError:
        return RuntimeCheck(
            name="litellm_endpoint",
            status="fail",
            detail="LiteLLM returned an invalid or empty model catalog.",
        )


async def _check_structured_generation(config: AppConfig) -> RuntimeCheck:
    gateway = LiteLLMGateway(
        endpoint=config.litellm.base_url,
        aliases=config.litellm.model_aliases,
        timeout_seconds=config.litellm.timeout_seconds,
        api_key=config.litellm.api_key(),
        verify_tls=config.litellm.verify_tls,
        max_output_tokens=256,
        temperature=config.litellm.temperature,
        schema_repair_attempts=0,
    )
    try:
        output = await gateway.generate_structured(
            model_alias="extraction_model",
            system="Return only valid JSON matching the supplied schema.",
            developer="This is a runtime readiness probe. Do not add prose.",
            user='Return {"status": "ready"}.',
            output_schema=ModelProbe,
            run_id="runtime-diagnostic",
            agent_name="runtime_diagnostic",
            prompt_version="runtime_diagnostic.v1",
        )
    except RuntimeError as exc:
        cause = type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__
        return RuntimeCheck(
            name="structured_generation",
            status="fail",
            detail=f"Structured generation failed ({cause}).",
        )
    return RuntimeCheck(
        name="structured_generation",
        status="pass",
        detail=f"Model returned the validated probe status: {output.status}.",
    )


def _authorization_headers(config: AppConfig) -> dict[str, str]:
    api_key = config.litellm.api_key()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _model_ids(response: httpx.Response) -> set[str]:
    try:
        body = response.json()
        rows = body["data"]
        model_ids = {
            row["id"]
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LiteLLM returned an invalid model catalog") from exc
    if not model_ids:
        raise ValueError("LiteLLM returned an empty model catalog")
    return model_ids
