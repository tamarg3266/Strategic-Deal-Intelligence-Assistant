# Strategic Deal Intelligence Assistant

Runnable implementation of the Cato Networks GTM AI Engineer home task. The
prototype uses LangGraph, SQLite, and live models routed through LiteLLM to
produce permission-scoped, evidence-backed negotiation briefs.

## What Is Implemented

- Fixture-backed authorization before retrieval and again before generation.
- Ingestion of Salesforce, Gong summaries and transcripts, pricing notes,
  Deal Desk policy, and generated Slack updates.
- SQLite FTS5 evidence retrieval with capability-scoped metadata filtering and BM25 ranking.
- Three specialized LLM agents plus an LLM brief composer.
- Typed Pydantic contracts and schema-repair handling at the model boundary.
- Deterministic citation validation and Deal Desk policy enforcement.
- Human approval requests with explicit roles, reasons, policy rules, and evidence.
- SQLite persistence for runs, traces, model usage, approvals, decisions, and feedback.
- JSON run artifacts under `var/artifacts/`.

Red-team agents are intentionally outside this implementation scope.

## Setup

From Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

The default configuration uses the existing LiteLLM proxy at
`http://localhost:4000`. Add its API key to `.env`:

```bash
LITELLM_API_KEY='your-token'
```

After authentication, set `LITELLM_EXTRACTION_MODEL`, `LITELLM_RISK_MODEL`,
and `LITELLM_SYNTHESIS_MODEL` to model IDs returned by `/v1/models`. The same
model may be used for all three roles when only one capable model is available.

Validate configuration, sources, SQLite, and the server before generating data:

```bash
deal-intel doctor
deal-intel doctor --probe-model
```

`--probe-model` performs a small live structured-output call. For local checks
that deliberately do not contact a model, use `deal-intel doctor --offline`.

Build and test the installable package:

```bash
python -m build
python -m pytest -q
python -m ruff check src tests scripts
```

## Run

Generate an authorized standard brief:

```bash
deal-intel brief OPP-1001 USR-5001
```

Generate a restricted brief that must route sensitive recommendations to humans:

```bash
deal-intel brief OPP-1003 USR-5003
```

Verify a non-leaking denial:

```bash
deal-intel brief OPP-1003 USR-5007
```

Run all required demo scenarios:

```bash
python scripts/run_scenarios.py
```

Build the local operational console:

```bash
cd web && npm run build
```

Run the API and console in two terminals:

```bash
deal-intel web
cd web && npm run dev
```

Open the local URL printed by Vinext to check runtime readiness and generate a brief
through the same workflow used by the CLI. The API intentionally binds to loopback.

The two authorized scenarios require live LiteLLM responses. The denied
scenario exits before model invocation and can be used to verify fail-closed
authorization even while the model server is unavailable.

## Human Approval

List the complete approval payload, including why approval is required:

```bash
deal-intel approval list --run-id RUN_ID
```

Record a human decision. The reviewer role must match the required role:

```bash
deal-intel approval decide APPROVAL_ID USR-5005 deal_desk rejected \
  --rationale 'The concession needs a term trade-off.'
```

The transaction updates the approval and inserts two immutable rows:

- `approval_decisions`: the audit record for the human decision.
- `human_feedback`: the original recommendation, model and prompt version,
  cited evidence, policy reasons, reviewer decision, and rationale.

Export feedback candidates for a separately governed SFT, preference-learning,
or RLHF pipeline:

```bash
deal-intel feedback export --output var/artifacts/human_feedback.jsonl
```

Feedback is never applied automatically to the live model. It must be reviewed,
redacted, quality-controlled, split for evaluation, and used in an offline model
training and deployment process.

## Tests

```bash
python -m pytest -q
```

See [HLD](docs/hld.md), [security notes](docs/security.md), and
[technical overview](docs/technical_overview.md).
