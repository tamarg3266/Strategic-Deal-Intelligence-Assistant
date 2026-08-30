# Strategic Deal Intelligence HLD

## Architectural Style

The implementation uses separation of control across five production planes:

- `control_plane`: resolves identity and creates immutable capabilities.
- `evidence_plane`: ingests, indexes, filters, ranks, and bundles evidence.
- `reasoning_plane`: runs three LLM analysts and the final LLM composer.
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
3. The evidence plane normalizes all required files into SQLite. Account,
   opportunity, source type, and sensitivity are filtered in SQL before ranking.
4. The control plane verifies every evidence bundle again before generation.
5. Commercial, Buyer Signal, and Risk and Approval analysts run concurrently. The
   orchestrator waits for all three results, records failed analyst identities, and
   stops before composition if any required analyst fails.
6. Governance rejects any claim or recommendation citing evidence outside its bundle.
7. The Brief Composer receives validated reports and a citation catalog, not tools.
8. Governance validates final citations and applies deterministic Deal Desk rules.
9. Sensitive recommendations become pending human approvals. The internal brief
   remains inspectable but is explicitly marked `approval_required`.
10. Every terminal result and its traces are stored in SQLite and as a JSON artifact.

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

## Operational Web Console

The local web console is a thin interface over the production workflow rather than
a second reasoning path. Vinext serves the browser interface and proxies two API
endpoints to a loopback-only Python process:

- `GET /api/health` validates configured paths, ingestion, SQLite/FTS5, and can
  optionally check the LiteLLM model catalog.
- `POST /api/runs` validates a `RunRequest`, invokes the same LangGraph workflow used
  by the CLI, and returns the persisted terminal `RunResult`.

The console displays readiness, accepts opportunity/requester scope and a bounded
request, and renders allowed, denied, failed, or approval-required outcomes. It is
bound to loopback by default because it has no production authentication layer.

## LLM Components

- Commercial Analyst: canonical deal and pricing state.
- Buyer Signal Analyst: goals, objections, stakeholder behavior, and ambiguity.
- Risk and Approval Analyst: structured high-impact and low-confidence risks.
- Brief Composer: all nine required brief sections from validated reports.

All calls use logical aliases through `ModelGateway`. LiteLLM supplies the live
OpenAI-compatible proxy endpoint and routes each alias to a provider model. Input
hashes, provider model, schema,
latency, token usage, and success state are stored without logging raw prompts.

## Human Approval and Learning Feedback

The policy engine, not the model, computes required roles from exact recommendation
fields and Deal Desk thresholds. An approval includes the original action and
rationale, evidence IDs, confidence, reason codes, policy rules, and a plain-language
explanation of why the model cannot proceed alone.

A reviewer decision is written transactionally to `approval_decisions` and to a
separate `human_feedback` table. The latter is an immutable training candidate for
an offline, curated learning process. It does not mutate prompts, weights, policy,
or live behavior at runtime.

## Persistence

`var/deal_intel.sqlite` contains evidence, runs, trace events, model invocations,
approvals, approval decisions, and human feedback. Terminal results are also saved
to `var/artifacts/<run_id>.json` for review and replay.
