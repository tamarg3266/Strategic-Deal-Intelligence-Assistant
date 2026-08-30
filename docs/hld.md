# Strategic Deal Intelligence HLD

## Architectural Style

The implementation uses separation of control across five production planes:

- `control_plane`: resolves identity and creates immutable capabilities.
- `evidence_plane`: ingests, indexes, filters, ranks, and bundles evidence.
- `reasoning_plane`: runs three LLM analysts, an LLM Negotiation Strategy Agent,
  and a deterministic brief assembler.
- `governance_plane`: verifies citations, applies policy, gates approvals, and persists state.
- `model_runtime`: isolates LiteLLM behind the application `ModelGateway` contract.

The runtime rule is: control creates capabilities, evidence creates bundles,
reasoning creates claims and recommendations, and governance decides usability.

Diagrams: [logical view](architecture.mmd) and [deployment view](deployment.mmd).

## Runtime Flow

1. The CLI or local web API validates an opportunity ID, requester ID, and bounded
   user request.
2. The control plane maps the opportunity to an account internally, resolves the
   permission fixture, and either denies safely or creates three purpose-specific
   evidence capabilities.
3. At web startup, the evidence plane fingerprints all required `.tsv` and `.md`
   sources and normalizes them into SQLite only when source content changed. Every
   run rechecks that fingerprint before retrieval. Account, opportunity, source type,
   and sensitivity are filtered in SQL before ranking.
4. The control plane verifies every evidence bundle again before generation.
5. Commercial, Buyer Signal, and Risk and Approval analysts run concurrently. The
   orchestrator waits for all three results, records failed analyst identities, and
   stops before synthesis if any required analyst fails.
6. Governance rejects any claim or recommendation citing evidence outside its bundle.
7. The Negotiation Strategy Agent receives only validated claims and recommendations,
   not raw evidence, a citation catalog, or tools. Its structured synthesis is checked
   for allowed citation and recommendation IDs and grounded exact facts.
8. Application code assembles all nine required sections, renders stable citations,
   aggregates missing information and warnings, and orders validated recommendations.
9. Governance validates the assembled brief and applies deterministic Deal Desk rules.
10. Sensitive recommendations become pending human approvals. The internal brief
   remains inspectable but is explicitly marked `approval_required`.
11. Every terminal result and its traces are stored in SQLite and as a JSON artifact.

## Authorization Boundary

`EvidenceCapability` fields are application-owned:

```text
run_id, requester_id, opportunity_id, account_id, purpose,
allowed_source_types, can_view_sensitive_pricing,
can_view_restricted_account, can_request_approval
```

Models can neither create nor expand a capability. A denied request produces only
`access_denied`; retrieval and model invocation do not run, and restricted account
or source metadata is not included in the result trace.

## Evidence and Retrieval

The ingestor creates stable `EvidenceRecord` objects from:

- Salesforce accounts, opportunities, and contacts.
- Gong call summaries and every provided transcript snippet.
- Pricing notes, with sensitivity derived from discount, uplift, approval state,
  and restricted opportunity status.
- Deal Desk policy, scoped to the authorized opportunity.
- Generated Slack-style account-team updates.

SQLite stores normalized records and an FTS5 index. Retrieval applies account,
opportunity, source, and sensitivity constraints in the same SQL statement and uses
FTS5 BM25 to prioritize lexical matches. Non-matching authorized rows fill remaining
bundle capacity so narrow queries do not silently discard relevant deal context.
The source-content fingerprint and indexed row count are stored transactionally with
the index. A matching fingerprint and row count skips parsing and rebuilding; a
change or count mismatch triggers an atomic replacement and an observable refresh
trace. This does not cache authorization decisions or retrieved evidence bundles.

## Operational Web Console

The local web console is a thin interface over the production workflow rather than
a second reasoning path. Vinext serves the browser interface and proxies two API
endpoints to a loopback-only Python process:

- `GET /api/health` validates configured paths, ingestion, SQLite/FTS5, and can
  optionally check the LiteLLM model catalog.
- `POST /api/runs` validates a `RunRequest`, invokes the same LangGraph workflow used
  by the CLI, and returns the persisted terminal `RunResult`.
- `POST /api/runs/stream` invokes that same workflow and emits newline-delimited,
  non-sensitive stage events before the identical terminal `RunResult`.

The console displays readiness, accepts opportunity/requester scope and a bounded
request, and renders allowed, denied, failed, or approval-required outcomes. It is
bound to loopback by default because it has no production authentication layer.
Progress messages contain only stage, status, run ID, timestamp, and fixed text;
they never contain evidence IDs, source metadata, prompts, or deal facts.

## LLM Components

- Commercial Analyst: canonical deal and pricing state.
- Buyer Signal Analyst: goals, objections, stakeholder behavior, and ambiguity.
- Risk and Approval Analyst: structured high-impact and low-confidence risks.
- Negotiation Strategy Agent: concise synthesis and prioritization over validated
  claims and existing recommendation IDs.
- Brief Assembler: deterministic rendering of all nine required sections, citations,
  missing information, and review warnings.

All calls use logical aliases through `ModelGateway`. LiteLLM supplies the live
OpenAI-compatible proxy endpoint and routes each alias to a provider model. Input
hashes, provider model, schema,
latency, token usage, and success state are stored without logging raw prompts.
The strategy invocation has a separate 1,800-token output cap and defaults to the
faster synthesis alias; the configured limit is included in its invocation trace.
One gateway-owned `httpx.AsyncClient` is shared across all model calls in a workflow
and closed in a `finally` block. This preserves independent model invocation traces
while reusing connection pools and TLS sessions.

## Human Approval and Learning Feedback

The policy engine, not the model, computes required roles from exact recommendation
fields and Deal Desk thresholds. Recommendations with the same required-role routing
are consolidated into one approval gate. The gate includes all original actions and
rationales, recommendation and evidence IDs, confidence, reason codes, policy rules,
and a plain-language explanation of why the model cannot proceed alone. It remains
pending until every required role approves; a rejection or change request terminates
the grouped gate.

A reviewer decision is written transactionally to `approval_decisions` and to a
separate `human_feedback` table. The latter is an immutable training candidate for
an offline, curated learning process. It does not mutate prompts, weights, policy,
or live behavior at runtime.

## Persistence

`var/deal_intel.sqlite` contains evidence, runs, trace events, model invocations,
approvals, approval decisions, and human feedback. Terminal results are also saved
to `var/artifacts/<run_id>.json` for review and replay.
