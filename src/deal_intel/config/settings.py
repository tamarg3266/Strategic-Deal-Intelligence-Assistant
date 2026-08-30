from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

REQUIRED_MODEL_ALIASES = {
    "extraction_model",
    "risk_model",
    "synthesis_model",
}


class PathConfig(BaseModel):
    data_root: Path = Path("synthetic_data")
    sqlite_path: Path = Path("var/deal_intel.sqlite")
    prompt_root: Path = Path("src/deal_intel/reasoning_plane/prompts")
    artifact_dir: Path = Path("var/artifacts")


class LiteLLMConfig(BaseModel):
    base_url: str = "http://localhost:4000"
    health_path: str = "/health"
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    api_key_env: str = "LITELLM_API_KEY"
    verify_tls: bool = True
    model_aliases: dict[str, str] = Field(
        default_factory=lambda: {
            "extraction_model": "default",
            "risk_model": "default",
            "synthesis_model": "default",
        }
    )
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=4_000, ge=256, le=65_536)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("LiteLLM base_url must use http:// or https://")
        return normalized

    @field_validator("health_path")
    @classmethod
    def validate_health_path(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"

    @field_validator("model_aliases")
    @classmethod
    def validate_model_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        missing = REQUIRED_MODEL_ALIASES - set(value)
        if missing:
            raise ValueError(f"Missing LiteLLM model aliases: {sorted(missing)}")
        empty = sorted(alias for alias in REQUIRED_MODEL_ALIASES if not value[alias].strip())
        if empty:
            raise ValueError(f"Empty LiteLLM model aliases: {empty}")
        return value

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class RetrievalConfig(BaseModel):
    max_evidence_items: int = Field(default=40, ge=1, le=200)


class WorkflowConfig(BaseModel):
    max_schema_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_grounding_repair_attempts: int = Field(default=1, ge=0, le=2)
    max_transport_retries: int = Field(default=2, ge=0, le=5)
    fail_closed_on_policy_ambiguity: bool = True


class AppConfig(BaseModel):
    """Deploy-time settings; authorization never comes from configuration."""

    environment: Literal["local", "test", "demo", "production"] = "local"
    paths: PathConfig = Field(default_factory=PathConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)


EnvCaster = Callable[[str], Any]
ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], EnvCaster]] = {
    "DEAL_INTEL_ENVIRONMENT": (("environment",), str),
    "DEAL_INTEL_DATA_ROOT": (("paths", "data_root"), str),
    "DEAL_INTEL_SQLITE_PATH": (("paths", "sqlite_path"), str),
    "DEAL_INTEL_PROMPT_ROOT": (("paths", "prompt_root"), str),
    "DEAL_INTEL_ARTIFACT_DIR": (("paths", "artifact_dir"), str),
    "DEAL_INTEL_MAX_EVIDENCE_ITEMS": (
        ("retrieval", "max_evidence_items"),
        int,
    ),
    "LITELLM_BASE_URL": (("litellm", "base_url"), str),
    "LITELLM_HEALTH_PATH": (("litellm", "health_path"), str),
    "LITELLM_TIMEOUT_SECONDS": (("litellm", "timeout_seconds"), float),
    "LITELLM_VERIFY_TLS": (("litellm", "verify_tls"), lambda value: _bool(value)),
    "LITELLM_EXTRACTION_MODEL": (
        ("litellm", "model_aliases", "extraction_model"),
        str,
    ),
    "LITELLM_RISK_MODEL": (
        ("litellm", "model_aliases", "risk_model"),
        str,
    ),
    "LITELLM_SYNTHESIS_MODEL": (
        ("litellm", "model_aliases", "synthesis_model"),
        str,
    ),
    "LITELLM_TEMPERATURE": (("litellm", "temperature"), float),
    "LITELLM_MAX_OUTPUT_TOKENS": (
        ("litellm", "max_output_tokens"),
        int,
    ),
}


def load_config(path: Path = Path("config/default.yaml")) -> AppConfig:
    config_path = path.expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    project_root = _project_root(config_path)
    load_dotenv(project_root / ".env", override=False)

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a mapping")
    _apply_environment(raw)
    config = AppConfig.model_validate(raw)
    return config.model_copy(update={"paths": _absolute_paths(config.paths, project_root)})


def _project_root(config_path: Path) -> Path:
    if config_path.parent.name == "config":
        return config_path.parent.parent
    return Path.cwd().resolve()


def _absolute_paths(paths: PathConfig, project_root: Path) -> PathConfig:
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else (project_root / path).resolve()

    return PathConfig(
        data_root=resolve(paths.data_root),
        sqlite_path=resolve(paths.sqlite_path),
        prompt_root=resolve(paths.prompt_root),
        artifact_dir=resolve(paths.artifact_dir),
    )


def _apply_environment(raw: dict[str, Any]) -> None:
    for env_name, (path, caster) in ENV_OVERRIDES.items():
        value = os.getenv(env_name)
        if value is None:
            continue
        target = raw
        for key in path[:-1]:
            child = target.setdefault(key, {})
            if not isinstance(child, dict):
                raise ValueError(f"Cannot override non-mapping configuration key: {key}")
            target = child
        target[path[-1]] = caster(value)


def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Expected boolean environment value, received: {value}")
