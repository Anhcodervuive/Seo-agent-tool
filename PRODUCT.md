# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

SEO Copilot serves two primary audiences with equal product importance but different permissions and experiences:

- Admins and SEO specialists configure Projects, data sources, tracking, crawl scope, schedules, AI settings, and provider integrations; they also diagnose collection and analysis failures.
- Clients and operations teams review dashboards, run approved audits, inspect historical results, ask AI Copilot about stored Project data, and turn findings into follow-up work.

Future workflows should preserve this separation rather than forcing both audiences through the same controls or level of technical detail.

## Product Purpose

SEO Copilot brings the technical, organic, keyword, backlink, competitor, and historical evidence for a website into one Project. It supports repeatable data collection, stored Snapshots, trend analysis, health prioritization, and AI-assisted interpretation.

Success means users can understand the current SEO situation, verify the evidence behind important findings, identify what needs attention, and follow progress over time without manually joining several provider reports.

## Positioning

SEO Copilot combines an SEO operations platform with an AI analysis layer. Verifiable Project data is the foundation; AI helps explain that data and formulate action plans without replacing the underlying evidence.

The product is not positioned as a general-purpose chatbot or an autonomous website operator. Its differentiated mechanism is Project-scoped analysis over stored, attributable SEO evidence and historical Snapshots.

## Operating Context

- An admin creates a Project and configures its domain, business context, target market, optional Google data sources, tracked keywords, competitors, crawl scope, schedules, and optional AI override.
- A Full audit collects applicable crawl, GA4, GSC, ranking, backlink, and competitor data in the background and saves the result as a Snapshot.
- Ranking-only checks refresh tracked keyword positions without running the complete audit pipeline.
- Users review Overview, Trends, Keywords, Audit History, Snapshot evidence, reports, and Health Score.
- AI Copilot answers questions using stored data for the current Project. Chat does not implicitly refresh providers or start a crawl.
- The product is deployed as a Flask web application with background workers and PostgreSQL, and integrates with external SEO and AI providers.

## Capabilities and Constraints

- Projects may operate without GA4 or GSC, with either source independently, or with both.
- Missing data is represented honestly. Health Score reweights available pillars and exposes confidence rather than scoring missing pillars as zero.
- Audits and provider operations may complete partially; retained data and affected sources must remain distinguishable.
- AI may read and analyze Project data but must not perform external or destructive actions without an explicitly designed and authorized workflow.
- Important conclusions must remain traceable to stored source data, a Snapshot, or another identifiable Project record.
- Provider and AI model availability can change. The architecture must support validation, failure reporting, and replacement without silently changing a Project's selected configuration.
- Provider/tool integrations should remain extensible so new sources and AI tools can be introduced without rewriting the complete Copilot workflow.
- Existing business logic and functionality are product truth. Visual exploration may replace layouts, but it must preserve supported workflows and outcomes unless a functional change is explicitly approved.

## Brand Commitments

- Product name: SEO Copilot.
- The product should speak in plain, operational language while preserving precise SEO terminology where it is necessary.
- AI must be presented as an evidence-backed assistant, not as an infallible authority or autonomous actor.

## Evidence on Hand

- Working source code and automated tests for Project setup, audits, data collection, trends, keyword tracking, Health Score, Snapshot history, reports, provider integrations, and AI Copilot.
- User-facing workflow documentation in `docs/user-guides/seo-copilot-client-guide-en.md`.
- Feature status and implementation notes under `docs/`.
- Existing staging screenshots and local templates demonstrate the current interface and workflows.
- No confirmed testimonials, customer logos, benchmark claims, press coverage, or commercial performance claims are available. Future work must not fabricate them.

## Product Principles

1. Evidence before assertion: important findings and AI conclusions must remain traceable to real Project data.
2. Assist, do not act silently: AI explains and recommends; external actions require an explicit, authorized workflow.
3. Honest incompleteness: distinguish unavailable, not connected, skipped, partial, failed, and genuinely empty data.
4. Equal audiences, appropriate experiences: support specialists and clients without exposing unnecessary complexity to either group.
5. Extensible by design: new providers, models, and tools should fit a modular integration layer.

## Accessibility & Inclusion

No product-specific compliance target has been confirmed. Web interfaces should nevertheless support keyboard operation, visible focus, semantic labels and states, readable contrast, responsive layouts, and plain-language error recovery as a baseline.
