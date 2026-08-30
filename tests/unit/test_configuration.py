import asyncio
from pathlib import Path

from deal_intel.config.diagnostics import ModelProbe, _check_structured_generation, run_diagnostics
from deal_intel.config.settings import AppConfig, LiteLLMConfig, PathConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_default_configuration_resolves_paths_from_repository() -> None:
    config = load_config(PROJECT_ROOT / "config" / "default.yaml")

    assert config.paths.data_root == PROJECT_ROOT / "synthetic_data"
    assert config.paths.prompt_root == (
        PROJECT_ROOT / "src" / "deal_intel" / "reasoning_plane" / "prompts"
    )
    assert config.litellm.model_aliases["extraction_model"] == "gpt-5.6-luna"


def test_environment_overrides_yaml(monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_BASE_URL", "https://models.example.test/")
    monkeypatch.setenv("LITELLM_EXTRACTION_MODEL", "extract-v2")
    monkeypatch.setenv("LITELLM_VERIFY_TLS", "false")
    monkeypatch.setenv("DEAL_INTEL_MAX_EVIDENCE_ITEMS", "17")

    config = load_config(PROJECT_ROOT / "config" / "test.yaml")

    assert config.litellm.base_url == "https://models.example.test"
    assert config.litellm.model_aliases["extraction_model"] == "extract-v2"
    assert config.litellm.verify_tls is False
    assert config.retrieval.max_evidence_items == 17


def test_offline_diagnostics_validate_sources_and_sqlite(tmp_path: Path) -> None:
    config = AppConfig(
        environment="test",
        paths=PathConfig(
            data_root=PROJECT_ROOT / "synthetic_data",
            sqlite_path=tmp_path / "runtime.sqlite",
            prompt_root=(
                PROJECT_ROOT / "src" / "deal_intel" / "reasoning_plane" / "prompts"
            ),
            artifact_dir=tmp_path / "artifacts",
        ),
        litellm=LiteLLMConfig(),
    )

    report = asyncio.run(run_diagnostics(config, include_model=False))

    assert report.ready is True
    assert {check.name: check.status for check in report.checks} == {
        "configured_paths": "pass",
        "source_ingestion": "pass",
        "sqlite": "pass",
        "litellm_endpoint": "skip",
    }
    assert config.paths.sqlite_path.exists()


def test_structured_probe_uses_configured_temperature(monkeypatch) -> None:
    class StubGateway:
        temperature: float | None = None
        closed = False

        def __init__(self, **kwargs: object) -> None:
            type(self).temperature = kwargs["temperature"]  # type: ignore[assignment]

        async def generate_structured(self, **kwargs: object) -> ModelProbe:
            return ModelProbe(status="ready")

        async def aclose(self) -> None:
            type(self).closed = True

    monkeypatch.setattr(
        "deal_intel.config.diagnostics.LiteLLMGateway",
        StubGateway,
    )
    config = AppConfig(litellm=LiteLLMConfig(temperature=1))

    result = asyncio.run(_check_structured_generation(config))

    assert result.status == "pass"
    assert StubGateway.temperature == 1
    assert StubGateway.closed is True
