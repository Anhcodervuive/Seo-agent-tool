# Feature Notes

This folder is the handoff log for completed, significant product features.
It complements the architecture and pipeline documents: each note records what
was delivered, how a user operates it, how data flows through the system, and
what must be checked when supporting it.

## Current notes

- [Week 3 data foundation and dashboard performance](2026-08-week3-data-foundation.md)
- [Week 3 comparable trends and interactive charts](2026-08-week3-trend-comparisons-and-charts.md)
- [Week 3 Health Score v2 and AI Copilot](2026-08-week3-health-and-copilot.md)
- [AI SEO Copilot chat mechanism (Vietnamese)](2026-08-ai-copilot-chat-mechanism.md)
- [Week 3 dashboard and Copilot operating guide](2026-08-week3-dashboard-and-copilot-operating-guide.md)
- [Deployment daily trend reconciliation](2026-08-deployment-daily-trend-reconciliation.md)

Client-facing, non-technical documentation is maintained separately in
[User Guides](../user-guides/README.md).

## Rule for future features

Create one Markdown file in this folder when a feature is complete and before
it is handed over. Use this filename pattern:

```text
YYYY-MM-short-feature-name.md
```

Each note should contain:

1. Purpose and user-facing result.
2. How to use it.
3. Data flow and the source of truth.
4. Important configuration, migrations, or deployment actions.
5. Verification steps and known limitations.
6. The commit(s) that delivered it.

Do not put API keys, credentials, client secrets, or personally sensitive
data in these notes.
