---
target: Admin settings
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-08-27T17-06-23Z
slug: pipeline-app-templates-settings-html
---
#### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | No visual progress/feedback during AI model check; Google account health/expiration status is not displayed. |
| 2 | Match System / Real World | 3 | "Legacy path" vs "Managed upload" terminology is internal jargon rather than actionable guidance. |
| 3 | User Control and Freedom | 2 | `assign_project.html` drops the sidebar navigation; no "Reset to default" for System Prompt; raw `confirm()` alerts. |
| 4 | Consistency and Standards | 1 | Severe modal token drift: `users.html` uses inline Tailwind Slate colors & pill buttons, while `google_accounts.html` uses `.app-modal`. |
| 5 | Error Prevention | 2 | No client-side JSON format preview before submission; modal errors wipe form state on page reload. |
| 6 | Recognition Rather Than Recall | 2 | System prompt textarea has no placeholder token cheatsheet; no search/filter for projects or users. |
| 7 | Flexibility and Efficiency | 2 | No bulk toggle/select all for project assignment; lacks keyboard accelerators. |
| 8 | Aesthetic and Minimalist Design | 2 | Basic Bootstrap `card shadow` containers lack the Search Intelligence Console atmospheric depth, borders, and token hierarchy. |
| 9 | Error Recovery | 3 | Good flash error messages, but failed modal submissions force reopening the modal and retyping from scratch. |
| 10 | Help and Documentation | 2 | Helpful inline hints exist, but no link or guide for Google Cloud Service Account creation or prompt engineering examples. |
| **Total** | | **21/40** | **Acceptable (52.5%)** |

#### Design Specificity Verdict

**LLM assessment**: The Admin Settings surface is functional and covers core administrative tasks (OpenRouter model selection, Service Account upload, user roles, and access control). However, visually and architecturally, it feels like a standard generic Bootstrap admin panel rather than an integral part of the premium *"Search Intelligence Console"*. The lack of consistent modal styling, missing sidebar context on sub-pages, unstyled raw alerts, and borrowed keyword chips create visual discord with the primary dashboard and project workflow.

**Deterministic scan**: Automated detector scanned `settings.html`, `_admin_sidebar.html`, `google_accounts.html`, `users.html`, and `assign_project.html`. It flagged 2 direct token violations in `users.html` (undocumented color `rgba(30, 41, 59, 0.85)` and non-standard `16px` border-radius). Manual code inspection revealed additional inline styles in `assign_project.html` (`var(--accent-purple)` switch hacks and inline border colors) and misaligned button geometry (`rounded-pill` on modal buttons).

**Visual overlays**: Browser subagent automation was degraded in this session; deterministic AST/regex scanning and source code analysis provided the underlying evidence.

#### Overall Impression
The backend logic and permission guards are well-implemented, but the frontend presentation is fragmented across Bootstrap defaults, hardcoded Tailwind styles, and legacy patterns. Unifying the admin suite into the dark-first Intelligence Console design language with resilient modals and streamlined workflows represents a high-leverage upgrade opportunity.

#### What's Working
1. **Clear Information Architecture in AI Settings**: Clean separation of model selection, OpenRouter catalog warning alert, and system prompt configuration.
2. **Robust Multi-Account Google Service Management**: Clear distinction between active/default accounts and private managed key storage.
3. **Streamlined Project Access Switchers**: Fast single-click toggle switches for assigning projects to team members.

#### Priority Issues

- **[P1] Design System & Token Drift Across Admin Modals and Controls**:
  - *Why it matters*: In `users.html`, the modal introduces hardcoded slate colors (`rgba(30, 41, 59, 0.85)`), arbitrary `16px` radius, and `rounded-pill` buttons, breaking away from [DESIGN.md](file:///d:/Freelancer/seo-internal-tool/seo-agent-src/seo-agent/DESIGN.md) tokens (`.app-modal`, `Panel Charcoal`, `10px control radius`). In `assign_project.html`, inline `<style>` blocks override switch components.
  - *Fix*: Standardize all modals to `.app-modal`, replace hardcoded inline styles with CSS variables/tokens, enforce 10px control radius for buttons, and replace `.keyword-chip` with dedicated admin status badges.
  - *Suggested command*: `/impeccable polish pipeline/app/templates/users.html`

- **[P1] Broken Navigation Continuity & Layout Shell in Access Management**:
  - *Why it matters*: `assign_project.html` omits `_admin_sidebar.html` entirely, breaking the spatial context of the Admin workspace and disorienting administrators.
  - *Fix*: Wrap `assign_project.html` in the standard 2-column Admin layout (`_admin_sidebar.html` on `col-xl-3`, content on `col-xl-9`), add search/filter and "Select All" actions for projects.
  - *Suggested command*: `/impeccable layout pipeline/app/templates/assign_project.html`

- **[P2] Form Resilience & Modal Error State UX Degradation**:
  - *Why it matters*: When a file upload fails or validation errors occur in `addGoogleAccountModal` or `addUserModal`, the server flashes an alert and reloads the page with the modal closed, discarding user input and forcing repetitive clicks.
  - *Fix*: Implement inline validation feedback or keep modal open on error, add JSON schema pre-validation, and replace browser-native `confirm()` with styled destructive confirmation dialogs.
  - *Suggested command*: `/impeccable harden pipeline/app/templates/google_accounts.html`

- **[P2] Surface Aesthetics & Intelligence Console Elevation**:
  - *Why it matters*: Current screens rely on flat Bootstrap `card shadow` structures with basic inputs, missing the depth, atmospheric layering, subtle borders (`rgba(255, 255, 255, 0.08)`), and refined typography (`Outfit` styling) defined for the Search Intelligence Console.
  - *Fix*: Elevate cards to `Glass Charcoal` / `Panel Charcoal`, add quick stat chips to sidebar links, introduce model capability pills (e.g., "Tool Calling Verified", "Context: 128k") in AI Settings.
  - *Suggested command*: `/impeccable bolder pipeline/app/templates/settings.html`

#### Persona Red Flags

- **Alex (Power User)**:
  - Cannot bulk "Select All" or "Invert" client assignments in Project Access.
  - No quick test/dry-run button for the AI System Prompt against sample project data before saving globally.
  - No search filter in project access or user lists when managing dozens of clients.

- **Jordan (First-Timer)**:
  - "Managed upload" vs "Legacy path" terminology is confusing without an explanation of whether action is required.
  - Uploading a Google Service Account JSON lacks a step-by-step helper or link to GCP Console IAM guide.
  - Modal form error clears input and closes modal without inline field highlighting.

- **Sam (Accessibility)**:
  - Custom switch in `assign_project.html` relies on inline SVG background without distinct focus ring token (`0 0 0 3px rgba(59, 130, 246, 0.2)`).
  - Color-alone badges (`bg-danger`, `bg-info`) in `users.html` without descriptive accessible labels.
  - Modals have missing `aria-describedby` associations.

#### Minor Observations
- `google_accounts.html` renders a separate modal DOM structure inside a `{% for account in google_accounts %}` loop, which multiplies DOM nodes unnecessarily.
- The "Save AI Defaults" button lacks loading state feedback during live OpenRouter compatibility checks.
- System prompt textarea lacks a monospace/code styling aid, font size toggle, or token reference list (e.g. `{project_name}`, `{domain}`).

#### Questions to Consider
- What if the Admin Sidebar displayed live counter badges (e.g. `2 Accounts`, `5 Users`) and operational health dots?
- Could project access assignment be handled inline via a searchable modal or drawer directly from the Team table?
- How might we give admins a live test sandbox for AI system prompts directly within the AI Settings screen?
