# Technical Overview

## Contracts and Failure Behavior

Pydantic validates requests, evidence, claims, recommendations, drafts, approvals,
traces, and feedback. LiteLLM responses are parsed into the requested schema and
receive one configurable repair attempt. Transport failure, malformed JSON,
unsupported citations, missing brief sections, authorization drift, or an unroutable
approval fail the run safely and persist a non-sensitive terminal result.

The three analysts run concurrently and the orchestrator waits for every invocation
to settle. The current prototype records which required analysts failed and stops
before composition if any failed, avoiding a polished but incomplete brief.
Production could add per-agent retry queues and an explicitly labeled degraded mode.

The local operational console uses the same workflow as the CLI. Its readiness API
checks source ingestion and SQLite FTS5 locally, with an optional LiteLLM catalog
check. It binds to loopback by default and is not a substitute for an authenticated
production reviewer interface.

## Observability and Cost

Trace rows cover authorization, retrieval, tool calls, agent invocations,
recommendations, validation, approval, and persistence. Model invocation rows store
logical alias, actual provider model, prompt version, input hash, schema, latency,
token counts, and success. LiteLLM aliases allow cheaper extraction models and a
stronger synthesis model without changing agents.

## Production Evolution

- Replace fixture identity with signed SSO claims and policy-as-code authorization.
- Replace SQLite with transactional PostgreSQL and a managed hybrid evidence index.
- Add idempotent ingestion, durable LangGraph checkpoints, worker queues, and retries.
- Put LiteLLM behind private networking, secret management, quotas, and circuit breakers.
- Export traces through OpenTelemetry with redaction and retention controls.
- Verify claim-to-source entailment and add regression evaluations before release.
- Build a reviewer UI with authenticated roles, dual control, expiration, and escalation.
- Curate `human_feedback` into versioned datasets with offline evaluation and model registry gates.
