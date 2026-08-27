---
version: 1
slug: "pipeline-app-templates-add-project-html"
primary_target: "pipeline/app/templates/add_project.html"
related_targets: ["pipeline/app/templates/edit_project.html"]
---

# Project Dossier surface brief

- **Scope and visitor mode:** Create Project and Edit Project for authenticated Admin/SEO Specialists operating a desktop-first SEO management console, with complete tablet/mobile adaptation.
- **Audience, job, and proof:** Create should establish a valid project from name and domain quickly, then allow optional enrichment. Edit should make frequent configuration changes, 100+ keyword management, data-source status, schedules, crawl scope, and AI overrides directly reachable. Existing values, readiness, connection state, counts, validation, and unsaved changes are the evidence.
- **Chosen direction:** Project Dossier. A sticky indexed chapter rail organizes Identity, Data Sources, Tracking, Crawl, Schedules, and AI. The active chapter owns the central workspace. A compact ledger communicates readiness on Create and current state/unsaved changes on Edit. The memorable moment is that optional enrichment is visibly available without blocking project creation.
- **Approved comp:** `.impeccable/mocks/decision/project-dossier.png`. Carry the chapter topology, asymmetric central-workspace/ledger composition, compact density, quiet rules, and clear active chapter. Do not literalize invented fields or the Cash Home logo shown by the generated comp.
- **Boundaries:** Preserve all existing Flask routes, form names, fields, model validation, normalization, keyword/competitor parsing, schedule behavior, client-side validation, accessibility, themes, and submit destinations. No new business capability, no silent autosave, and no mandatory GA4/GSC connection.
- **Material states:** minimum new project; optional sources disconnected; connected source; empty and 100+ keyword lists; validation error; invalid AI model; unchanged/unsaved/saving; enabled/disabled schedule; narrow viewport; light and dark themes.

## Implementation record

- **Status:** Implemented, visually reviewed, and documented on 2026-08-28.
- **Production targets:** `pipeline/app/templates/add_project.html`, `pipeline/app/templates/edit_project.html`, and the namespaced Project Dossier rules in `pipeline/app/static/css/style.css`.
- **Implemented topology:** wide desktop uses chapter rail / active workspace / ledger; the ledger drops beneath the workspace at the intermediate breakpoint; tablet and mobile use a single-column flow with a horizontally scrollable chapter index and compact mobile actions.
- **Truthful state:** Create is blocked only by Project name and Domain. GA4 and GSC remain independent and optional. Tracking totals count populated rows. Edit identifies an existing Project without inventing lifecycle status and reports the chapter containing unsaved changes.
- **Accessibility:** chapter controls expose tab semantics and stable tab/panel relationships, support roving focus plus arrow/Home/End keys, preserve visible focus, and honor reduced-motion preferences.
- **Approved concept:** `.impeccable/mocks/decision/project-dossier.png`.
- **QA evidence:** `.impeccable/review/hero-repro.png`, `.impeccable/review/create-desktop.png`, `.impeccable/review/edit-desktop.png`, `.impeccable/review/create-mobile.png`, and `.impeccable/review/edit-mobile.png`.
- **Asset decision:** no new shipping raster is required. The concept and QA captures remain review-only; the conceptual Cash Home logo and all generated imagery are excluded from production.
