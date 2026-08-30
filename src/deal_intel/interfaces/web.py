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
from deal_intel.contracts.schemas import RunRequest
from deal_intel.model_runtime.gateway import ModelGateway
from deal_intel.orchestration.graph import run_workflow

MAX_REQUEST_BYTES = 16_384


class DealIntelRequestHandler(BaseHTTPRequestHandler):
    """Loopback JSON API for the local operational console."""

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
        if urlparse(self.path).path != "/api/runs":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
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
            return

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
    handler = partial(
        DealIntelRequestHandler,
        config=config,
        gateway=gateway,
    )
    return ThreadingHTTPServer((host, port), handler)
