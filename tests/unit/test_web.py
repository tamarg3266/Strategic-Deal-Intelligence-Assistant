import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from deal_intel.config.settings import AppConfig, LiteLLMConfig, PathConfig
from deal_intel.interfaces.web import create_web_server
from deal_intel.model_runtime.fake import FakeGateway


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        environment="test",
        paths=PathConfig(
            data_root=Path("synthetic_data"),
            sqlite_path=tmp_path / "web.sqlite",
            prompt_root=Path("src/deal_intel/reasoning_plane/prompts"),
            artifact_dir=tmp_path / "artifacts",
        ),
        litellm=LiteLLMConfig(
            model_aliases={
                "extraction_model": "fake-extraction",
                "risk_model": "fake-risk",
                "synthesis_model": "fake-synthesis",
            }
        ),
    )


def test_web_health_and_denied_workflow_end_to_end(tmp_path: Path) -> None:
    server = create_web_server(_config(tmp_path), port=0, gateway=FakeGateway({}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base_url}/api/health", timeout=5) as response:
            health = json.load(response)
        request = Request(
            f"{base_url}/api/runs",
            data=json.dumps(
                {"opportunity_id": "OPP-1003", "requester_id": "USR-5007"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert health["ready"] is True
    assert {check["name"] for check in health["checks"]} == {
        "configured_paths",
        "source_ingestion",
        "sqlite",
        "litellm_endpoint",
    }
    assert result["status"] == "denied"
    assert result["safe_error"] == "access_denied"
    assert result["brief"] is None


def test_web_stream_emits_safe_progress_and_terminal_result(tmp_path: Path) -> None:
    server = create_web_server(_config(tmp_path), port=0, gateway=FakeGateway({}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            f"{base_url}/api/runs/stream",
            data=json.dumps(
                {"opportunity_id": "OPP-1003", "requester_id": "USR-5007"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.headers["Content-Type"].startswith(
                "application/x-ndjson"
            )
            events = [
                json.loads(line)
                for line in response.read().decode("utf-8").splitlines()
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    progress_events = [item["progress"] for item in events if item["type"] == "progress"]
    terminal = next(item["result"] for item in events if item["type"] == "result")
    assert {item["stage"] for item in progress_events} == {
        "authorization",
        "persistence",
    }
    assert all("EV-" not in item["message"] for item in progress_events)
    assert terminal["status"] == "denied"
