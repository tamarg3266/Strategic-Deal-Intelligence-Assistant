# Security Notes

## Enforced Controls

- Opportunity-to-account mapping happens internally before evidence retrieval.
- Unknown users, unknown opportunities, account mismatches, and restricted-account
  mismatches return the same non-sensitive `access_denied` reason.
- Source type and sensitivity filters are derived from server-owned capabilities.
- Restricted or sensitive rows never enter an unauthorized model context.
- A second scope check runs immediately before LLM generation.
- Evidence text is marked untrusted in every system prompt.
- Agent and brief citations must resolve to evidence present in the exact authorized bundle.
- The LLM cannot set approval status, reviewer role, permission scope, or publication status.
- Customer-facing, legal, pricing, concession, and low-confidence recommendations are
  routed by deterministic policy.
- Raw prompts are not stored. Model traces store hashes, model identifiers, latency,
  token usage, schema, and safe error type.

## Human Feedback Safety

Human feedback is stored separately because direct online learning would create
poisoning, privacy, drift, and audit risks. Before training, feedback records need
role verification, deduplication, restricted-data handling, quality review, train/eval
splitting, model evaluation, and a controlled deployment approval.

## Prototype Limitations

- The fixture identity resolver is not authentication; production requires SSO claims.
- SQLite replacement indexing is appropriate for the demo, not concurrent ingestion.
- Citation ID validation proves provenance membership, not semantic entailment.
- The lexical ranker is deterministic but not semantic or multilingual.
- Approval role input is simulated by CLI; production must verify reviewer roles from IAM.
- Local artifact files inherit host filesystem protections and need production encryption
  and retention policy.
