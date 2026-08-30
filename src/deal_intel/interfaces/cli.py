from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import typer

from deal_intel.config.diagnostics import run_diagnostics
from deal_intel.config.settings import load_config
from deal_intel.contracts.schemas import RunRequest
from deal_intel.evidence_plane.ledger import EvidenceLedger
from deal_intel.governance_plane.approval_simulator import ApprovalSimulator
from deal_intel.governance_plane.run_ledger import RunLedger
from deal_intel.interfaces.web import create_web_server
from deal_intel.orchestration.graph import run_workflow

app = typer.Typer(help="Strategic Deal Intelligence Assistant")
approval_app = typer.Typer(help="Inspect and decide human approval requests")
run_app = typer.Typer(help="Inspect persisted runs")
feedback_app = typer.Typer(help="Export immutable human feedback for offline learning")
app.add_typer(approval_app, name="approval")
app.add_typer(run_app, name="run")
app.add_typer(feedback_app, name="feedback")


@app.command()
def doctor(
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
    offline: bool = typer.Option(False, "--offline"),
    probe_model: bool = typer.Option(False, "--probe-model"),
) -> None:
    """Validate local sources, storage, LiteLLM, and optional generation."""

    if offline and probe_model:
        raise typer.BadParameter("--probe-model cannot be combined with --offline")
    config = load_config(config_path)
    report = asyncio.run(
        run_diagnostics(
            config,
            include_model=not offline,
            probe_model=probe_model,
        )
    )
    typer.echo(report.model_dump_json(indent=2))
    if not report.ready:
        raise typer.Exit(code=1)


@app.command()
def brief(
    opportunity_id: str,
    requester_id: str,
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
    user_input: str = typer.Option(
        "Generate an internal Strategic Deal Intelligence Brief.", "--request"
    ),
) -> None:
    """Generate a live LLM-backed brief and persist its result."""

    config = load_config(config_path)
    request = RunRequest(
        opportunity_id=opportunity_id,
        requester_id=requester_id,
        user_input=user_input,
    )
    result = asyncio.run(run_workflow(request, config=config))
    typer.echo(result.model_dump_json(indent=2))
    if result.status == "denied":
        raise typer.Exit(code=2)
    if result.status == "failed":
        raise typer.Exit(code=1)


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
) -> None:
    """Serve the local operational console and workflow API."""

    server = create_web_server(
        load_config(config_path),
        host=host,
        port=port,
    )
    typer.echo(f"Deal Intelligence Console listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@approval_app.command("list")
def list_approvals(
    run_id: str | None = typer.Option(None, "--run-id"),
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
) -> None:
    ledger = _run_ledger(config_path)
    approvals = ledger.list_approvals(run_id)
    typer.echo(
        "[\n" + ",\n".join(approval.model_dump_json(indent=2) for approval in approvals) + "\n]"
    )


@approval_app.command("decide")
def decide_approval(
    approval_id: str,
    reviewer_id: str,
    reviewer_role: str,
    decision: Literal["approved", "rejected", "changes_requested"],
    rationale: str = typer.Option(..., "--rationale"),
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
) -> None:
    service = ApprovalSimulator(_run_ledger(config_path))
    decision_record, feedback = service.decide(
        approval_id=approval_id,
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        decision=decision,
        rationale=rationale,
    )
    typer.echo(
        "Human decision persisted.\n"
        f"decision_id={decision_record.decision_id}\n"
        f"feedback_id={feedback.feedback_id}"
    )


@run_app.command("show")
def show_run(
    run_id: str,
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
) -> None:
    row = _run_ledger(config_path).get_run(run_id)
    if row is None:
        raise typer.BadParameter("run_not_found")
    typer.echo(row)


@feedback_app.command("export")
def export_feedback(
    output: Path = typer.Option(Path("var/artifacts/human_feedback.jsonl"), "--output"),
    config_path: Path = typer.Option(Path("config/default.yaml"), "--config"),
) -> None:
    """Export training candidates; curation and model training happen offline."""

    feedback = _run_ledger(config_path).list_feedback()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(record.model_dump_json() for record in feedback) + ("\n" if feedback else ""),
        encoding="utf-8",
    )
    typer.echo(f"Exported {len(feedback)} feedback records to {output}")


def _run_ledger(config_path: Path) -> RunLedger:
    config = load_config(config_path)
    return RunLedger(EvidenceLedger(config.paths.sqlite_path))
