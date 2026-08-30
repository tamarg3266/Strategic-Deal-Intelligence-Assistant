# Configuration

Configuration contains deploy-time paths, the SQLite location, LiteLLM endpoint,
logical model aliases, token limits, retrieval limits, and schema-repair policy.

It must never contain requester-specific access overrides, account permissions,
approval outcomes, or publication decisions. Those controls come from authenticated
identity and deterministic application services.
