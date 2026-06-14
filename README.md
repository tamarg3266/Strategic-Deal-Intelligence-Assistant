# Cato GTM AI Engineer Home Task

This repository contains the assignment brief and synthetic source data for the Cato Networks GTM AI Engineer home task: building a Strategic Deal Intelligence Assistant for sales negotiation preparation.

The task asks candidates to build a runnable, LLM-backed multi-agent prototype that retrieves evidence from local GTM-style data, enforces permissions, generates grounded deal briefs, routes sensitive recommendations through human approval, and leaves observable traces.

## Contents

- [Assignment brief](Cato_GTM_AI_Engineer_Home_Task.md)
- [Synthetic data overview](synthetic_data/README.md)
- [Salesforce-style fixtures](synthetic_data/salesforce/)
- [Gong-style call summaries and transcripts](synthetic_data/gong/)
- [Pricing notes](synthetic_data/pricing/pricing_notes.tsv)
- [Access permissions](synthetic_data/policies/access_permissions.tsv)
- [Deal Desk policy](synthetic_data/policies/deal_desk_policy.md)

## Notes

The included data is fully synthetic and covers three fictional opportunities: `OPP-1001`, `OPP-1002`, and `OPP-1003`.

This branch intentionally excludes the generated Slack-style update dataset. Candidates should create and ingest their own synthetic Slack-style updates as described in the assignment brief.
