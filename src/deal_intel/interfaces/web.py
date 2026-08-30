from __future__ import annotations

import asyncio
import json
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from deal_intel.config.diagnostics import run_diagnostics
from deal_intel.config.settings import AppConfig
from deal_intel.contracts.schemas import RunProgress, RunRequest
from deal_intel.evidence_plane.index_manager import EvidenceIndexManager
from deal_intel.evidence_plane.ingestion import EvidenceIngestor
from deal_intel.evidence_plane.ledger import EvidenceLedger
from deal_intel.model_runtime.gateway import ModelGateway
from deal_intel.orchestration.graph import run_workflow

MAX_REQUEST_BYTES = 16_384


class DealIntelRequestHandler(BaseHTTPRequestHandler):
    """Loopback JSON API for the local operational console."""

    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        *args: Any,
        config: AppConfig,
        gateway: ModelGateway | None,
        **kwargs: Any,
    ) -> None:
        self.config = config
        self.gateway = gateway
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            include_model = parse_qs(parsed.query).get("include_model") == ["true"]
            report = asyncio.run(
                run_diagnostics(self.config, include_model=include_model)
            )
            self._send_json(HTTPStatus.OK, report.model_dump(mode="json"))
            return
        if parsed.path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/api/runs", "/api/runs/stream"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        request = self._read_run_request()
        if request is None:
            return
        if path == "/api/runs/stream":
            self._run_stream(request)
            return

        self._run_json(request)

    def _read_run_request(self) -> RunRequest | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_size"})
            return
        try:
            body = json.loads(self.rfile.read(content_length))
            request = RunRequest.model_validate(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_request"})
            return None
        return request

    def _run_json(self, request: RunRequest) -> None:
        try:
            result = asyncio.run(
                run_workflow(request, config=self.config, gateway=self.gateway)
            )
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "workflow_execution_failed"},
            )
            return
        self._send_json(HTTPStatus.OK, result.model_dump(mode="json"))

    def _run_stream(self, request: RunRequest) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def observe(progress: RunProgress) -> None:
            self._send_stream_event(
                {"type": "progress", "progress": progress.model_dump(mode="json")}
            )

        try:
            result = asyncio.run(
                run_workflow(
                    request,
                    config=self.config,
                    gateway=self.gateway,
                    progress_observer=observe,
                )
            )
            self._send_stream_event(
                {"type": "result", "result": result.model_dump(mode="json")}
            )
        except Exception:
            try:
                self._send_stream_event(
                    {"type": "error", "error": "workflow_execution_failed"}
                )
            except OSError:
                pass

    def _send_stream_event(self, payload: object) -> None:
        body = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def create_web_server(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    gateway: ModelGateway | None = None,
) -> ThreadingHTTPServer:
    ingestor = EvidenceIngestor(config.paths.data_root)
    EvidenceIndexManager(
        ingestor,
        EvidenceLedger(config.paths.sqlite_path),
    ).ensure_current()
    handler = partial(
        DealIntelRequestHandler,
        config=config,
        gateway=gateway,
    )
    return ThreadingHTTPServer((host, port), handler)
