---
name: SEO Copilot
description: A premium search-intelligence console where verified project data stays clear and AI remains a restrained analytical layer.
colors:
  intelligence-blue: "#3b82f6"
  intelligence-purple: "#8b5cf6"
  console-black: "#0a0a0b"
  panel-charcoal: "#121214"
  glass-charcoal: "rgba(24, 24, 27, 0.6)"
  elevated-dark: "rgba(255, 255, 255, 0.02)"
  input-dark: "rgba(0, 0, 0, 0.2)"
  ink-primary: "#f4f4f5"
  ink-strong: "#ffffff"
  ink-muted: "#a1a1aa"
  ink-faint: "#71717a"
  border-subtle: "rgba(255, 255, 255, 0.08)"
  border-strong: "rgba(255, 255, 255, 0.15)"
  light-canvas: "#f5f7fb"
  light-panel: "#ffffff"
  light-ink: "#111827"
  success: "#22c55e"
  warning: "#f59e0b"
  danger: "#ef4444"
typography:
  display:
    fontFamily: "Outfit, sans-serif"
    fontSize: "clamp(2.55rem, 4.6vw, 4.65rem)"
    fontWeight: 700
    lineHeight: 0.99
    letterSpacing: "-0.055em"
  headline:
    fontFamily: "Outfit, sans-serif"
    fontSize: "clamp(1.65rem, 3vw, 2.05rem)"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Outfit, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Outfit, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "-0.01em"
  label:
    fontFamily: "Outfit, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.06em"
rounded:
  compact: "6px"
  control: "10px"
  field: "12px"
  cluster: "14px"
  panel: "18px"
  card: "20px"
  section: "22px"
  shell: "28px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  section: "28px"
  page: "36px"
components:
  button-primary:
    backgroundColor: "{colors.intelligence-blue}"
    textColor: "{colors.ink-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.6rem 1.2rem"
  button-secondary:
    backgroundColor: "{colors.elevated-dark}"
    textColor: "{colors.ink-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.6rem 1.2rem"
  field:
    backgroundColor: "{colors.input-dark}"
    textColor: "{colors.ink-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "0.8rem 1.2rem"
  card:
    backgroundColor: "{colors.glass-charcoal}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.card}"
    padding: "1.75rem"
  chip:
    backgroundColor: "{colors.elevated-dark}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.3rem 0.65rem"
---

# Design System: SEO Copilot

## Overview

**Creative North Star: "The Search Intelligence Console"**

SEO Copilot should feel like a premium analysis environment: composed, atmospheric, and purpose-built for understanding search performance. Its dark-first visual world uses restrained blue-to-purple light, translucent surfaces, and precise typography to create depth without competing with the data.

The visual hierarchy always serves verifiable project information first. AI is presented as an intelligent support layer, never as decorative spectacle or an autonomous actor. Dense operational screens should remain easy to scan, while progressive disclosure keeps advanced controls available without placing every option at the same visual level.

**Key Characteristics:**

- Dark-first, premium search-intelligence workspace with a complete light counterpart.
- Clear data hierarchy supported by quiet atmospheric depth.
- Refined controls with visible, restrained interaction feedback.
- Intelligence Gradient reserved for identity, selection, and primary actions.
- Compact but breathable layouts designed for repeated operational use.

## Colors

The palette pairs near-black neutral surfaces with a cool Intelligence Gradient, using semantic colors only where status must be understood immediately.

### Primary

- **Intelligence Blue** (`#3b82f6`): primary action, focus, link, selected-state, and data-series anchor.
- **Intelligence Purple** (`#8b5cf6`): the secondary end of the Intelligence Gradient and a selective AI or brand signal.

### Neutral

- **Console Black** (`#0a0a0b`): dark-mode application canvas.
- **Panel Charcoal** (`#121214`): stable card and section surface.
- **Glass Charcoal** (`rgba(24, 24, 27, 0.6)`): translucent elevated surface when backdrop context should remain perceptible.
- **Primary Ink** (`#f4f4f5`): default readable text on dark surfaces.
- **Strong Ink** (`#ffffff`): titles, key values, and active controls.
- **Muted Ink** (`#a1a1aa`): supporting copy, metadata, and inactive navigation.
- **Faint Ink** (`#71717a`): low-priority labels and tertiary metadata only.
- **Light Canvas** (`#f5f7fb`) and **Light Panel** (`#ffffff`): light-mode surface pair.

### Tertiary

- **Success Green** (`#22c55e`): completed, connected, ready, and positive movement.
- **Warning Amber** (`#f59e0b`): partial results and conditions requiring review.
- **Danger Red** (`#ef4444`): failed, destructive, or critical states.

### Named Rules

**The Intelligence Gradient Rule.** Use the blue-to-purple gradient for brand marks, primary actions, selected controls, and meaningful progress—not as a generic card fill.

**The Data Contrast Rule.** Decorative light must never reduce the contrast or legibility of values, labels, tables, charts, or source references.

## Typography

**Display Font:** Outfit (with sans-serif fallback)  
**Body Font:** Outfit (with sans-serif fallback)

**Character:** Outfit gives the product a geometric, contemporary voice while staying approachable at dashboard sizes. Hierarchy comes from size, weight, and contrast rather than mixing multiple font families.

### Hierarchy

- **Display** (700, `clamp(2.55rem, 4.6vw, 4.65rem)`, 0.99): rare public or authentication hero headlines.
- **Headline** (700, `clamp(1.65rem, 3vw, 2.05rem)`, 1.1): page identity and major workspace titles.
- **Title** (600, `1.15rem`, 1.3): cards, sections, and focused modules.
- **Body** (400, `0.95rem`, 1.55): instructions, descriptions, and form content; explanatory copy generally stays within roughly 42–65 characters per line where space permits.
- **Label** (700, `0.72rem`, `0.06em`): table headings, eyebrows, status metadata, and compact labels; uppercase is reserved for taxonomy, not ordinary field labels.

### Named Rules

**The Values Speak First Rule.** In analytical modules, key values and conclusions receive stronger contrast before explanatory text does.

**The Quiet Label Rule.** Small uppercase labels organize dense data; they must not become a second headline system.

## Layout

The application uses centered Bootstrap containers, with focused workspaces typically capped around 1180–1320px. Major surfaces follow an 8px-rooted rhythm, usually expressed as 8, 12, 16, 20, and 28px gaps or padding. Dashboard grids use repeatable cards; setup and settings flows organize content into sections with persistent navigation and clear action zones.

Desktop layouts may combine a narrow navigation or summary rail with a flexible content column. Project Dossier uses three columns above 1280px, moves its ledger below the active workspace from 1279px, and becomes a single-column flow below 992px. At mobile widths near 576px, fields and action groups compact further. Wide data tables and chapter indexes may scroll within their own region rather than forcing document-level horizontal overflow.

**The Scan Path Rule.** Arrange page title, current state, primary evidence, and action in that order; advanced configuration belongs behind a tab, drawer, or details disclosure.

**The Useful Density Rule.** Preserve enough density for comparison and operational scanning, but use spacing and grouping—not empty expanses—to create clarity.

## Elevation & Depth

The system is layered atmospheric. Depth comes first from tonal surface separation and subtle borders, then from soft ambient shadows. Glass blur is appropriate for the sticky application header and selected elevated surfaces. Glow is a scarce response to brand, focus, or hover—not a persistent halo around every panel.

### Shadow Vocabulary

- **Card Rest** (`0 20px 40px rgba(0, 0, 0, 0.2)`): ambient dark-mode separation for major cards.
- **Card Hover** (`0 30px 60px rgba(0, 0, 0, 0.3)`): interactive lift on cards that are actually clickable.
- **Light Card Rest** (`0 18px 36px rgba(15, 23, 42, 0.08)`): quiet light-mode surface separation.
- **Brand Mark** (`0 10px 24px rgba(79, 70, 229, 0.28)`): compact identity emphasis around the logo mark.
- **Focus Ring** (`0 0 0 3px rgba(59, 130, 246, 0.2)`): visible keyboard and field focus feedback.

### Named Rules

**The Layer Before Shadow Rule.** Prefer surface tone and one subtle border before adding elevation.

**The Earned Lift Rule.** Cards move or gain stronger shadow only when they are interactive; static data containers stay visually stable.

## Shapes

The form language is softly geometric. Controls use compact 10–12px corners, component clusters use 14–18px corners, major cards use 20–22px corners, and top-level form shells may reach 28px. Pills are reserved for statuses, tabs, compact filters, and counts. Borders are low contrast and should clarify grouping rather than outline every nested layer.

**The Radius Hierarchy Rule.** A larger enclosing surface must not feel visually tighter than the controls it contains.

**The One Useful Border Rule.** When background tone already separates two nested surfaces, remove the extra border unless it communicates state or interaction.

## Components

Components should feel refined and restrained: clear at rest, responsive on interaction, and free of ornamental noise.

### Buttons

- **Shape:** compact rounded rectangle (10px) with `0.6rem 1.2rem` padding.
- **Primary:** white text over the Intelligence Gradient, with a soft blue-violet shadow.
- **Hover / Focus:** lift by no more than 2px; strengthen the ambient shadow; preserve a clearly visible focus ring.
- **Secondary / Ghost:** neutral elevated background and subtle border; increase contrast on hover without introducing a second accent.
- **Destructive:** red appears only on destructive intent or destructive hover state.

### Chips

- **Style:** compact pill for state, filter, count, or source metadata; use tinted semantic surfaces with readable text and a restrained border.
- **State:** selected chips may use a soft Intelligence Gradient tint, while unselected chips remain neutral.

### Cards / Containers

- **Corner Style:** softly rounded major cards (20px) and nested clusters (14–18px).
- **Background:** glass charcoal or panel charcoal in dark mode; white or cool off-white in light mode.
- **Shadow Strategy:** major cards receive ambient depth; clickable cards earn hover lift; dense inner groups generally stay flat.
- **Border:** one low-contrast border at meaningful boundaries.
- **Internal Padding:** typically 20–28px for major content cards and 12–16px for dense nested groups.

### Inputs / Fields

- **Style:** dark recessed surface, subtle border, 12px radius, and generous horizontal padding.
- **Focus:** surface deepens, border shifts to Intelligence Blue, and a 3px translucent focus ring appears.
- **Error / Disabled:** error uses explicit red copy and border treatment; disabled content reduces emphasis while keeping labels readable.

### Navigation

The sticky header uses a blurred tonal surface with a fine bottom border. Navigation links are compact and muted at rest, become clearer on hover, and use a tinted Intelligence Gradient plus a small underline for the active destination. On smaller screens, primary navigation collapses into a clear menu instead of wrapping unpredictably.

### Form Workflow

Create and Edit workflows use numbered navigation, one visible section at a time, explicit previous/next actions, and progressive disclosure for bulk or advanced settings. Edit may add a summary rail and sticky save state; Create remains focused on completion. Shared fields, spacing, validation, and interaction language stay consistent across both experiences.

### Project Dossier

Create Project and Edit Project share the **Project Dossier** composition. On wide screens it is a three-part workspace: a compact indexed chapter rail, one dominant active form chapter, and a restrained state ledger. This replaces the previous horizontal wizard and nested-card stack while preserving every field, validation rule, and submission contract.

- **Create ledger:** separates the two blocking identity requirements from optional enrichment. Its primary action remains disabled until Project name and Domain are populated. Readiness updates in place, while keyword and competitor totals count only populated rows rather than blank starter rows.
- **Optional Google sources:** GA4 and GSC are independent, optional inputs. A Project may be created with neither source, either source, or both; their disconnected state is explicit, and neither blocks a general website health check.
- **Edit ledger:** identifies the record neutrally as an existing Project, summarizes the saved keyword, competitor, GA4, GSC, and AI-source state, and exposes a plain-language change ledger. When a field changes, the ledger names the affected chapter and marks the change as pending validation until save.
- **Chapter vocabulary:** Create uses Identity, Data Sources, Tracking, Crawl, and AI & Review. Edit adds Schedules and uses AI as its final chapter. Each chapter includes a compact state label so navigation communicates configuration state as well as position.
- **Responsive behavior:** above 1280px, chapter rail, active workspace, and ledger remain side by side. From 1279px, the ledger moves beneath the active workspace; below 992px, the surface becomes a single-column flow and the chapter index scrolls horizontally. At 575px and below, controls compact and the mobile action row remains horizontal with bottom scroll clearance.
- **Interaction states:** selected chapters use a restrained Intelligence Gradient tint; readiness and connection states use semantic color; disabled primary actions remain legible. Tabs expose tablist/tab/panel relationships, keep a single tab in the keyboard sequence, support arrow, Home, and End navigation, and synchronize `aria-selected`, `aria-controls`, and `aria-labelledby`. Focus remains visible, and reduced-motion preferences disable panel entry motion.
- **Asset stance:** Project Dossier ships entirely as code-native HTML, CSS, typography, icons, status indicators, and form controls. The approved comp and QA screenshots are review artifacts only; no generated logo, illustration, or raster decoration is copied into the product bundle.

**The Dossier Focus Rule.** Only one chapter owns the main reading column at a time. Supporting navigation and state may stay visible, but they must not become competing card walls.

**The Optional Means Optional Rule.** Data-source and enrichment UI must explicitly state when it is optional and must never imply that Google account linking is required for a general health check.

**The Honest Ledger Rule.** Readiness, counts, connection state, and change status must be derived from real form or Project state; never promote a placeholder row, inferred status, or conceptual comp label into a factual claim.

### SEO Copilot

The chat surface visually separates user, assistant, tool activity, typing, and failure states. AI content remains subordinate to project evidence: important analytical output should make source or Snapshot provenance easy to locate, and errors must be visible rather than leaving the conversation apparently idle.

## Do's and Don'ts

### Do:

- **Do** keep verified values, statuses, sources, and Snapshot references visually stronger than atmospheric decoration.
- **Do** use the Intelligence Gradient selectively for primary actions, selected state, progress, and AI identity.
- **Do** preserve compact, consistent scan paths across dashboard, Create, and Edit surfaces.
- **Do** use progressive disclosure for advanced settings and repeated tracking rows.
- **Do** provide explicit hover, focus-visible, disabled, loading, success, and error states.
- **Do** maintain a functional light-mode counterpart whenever a dark token or component changes.
- **Do** keep GA4 and GSC visibly optional and independently configurable in Project setup.
- **Do** keep Project Dossier ledgers truthful by counting populated records and naming the chapter that contains unsaved changes.

### Don't:

- **Don't** use excessive glow or gradients where they compete with data readability.
- **Don't** create deep stacks of bordered cards inside bordered cards when spacing or tonal separation is sufficient.
- **Don't** lower information density through oversized empty regions that make dashboards harder to scan.
- **Don't** make static containers lift on hover or otherwise imply clickability.
- **Don't** introduce new accent colors for decoration; semantic colors must retain semantic meaning.
- **Don't** present AI output as an untraceable authority or imply that AI will silently perform project actions.
- **Don't** ship generated comp logos, screenshots, or decorative raster assets as part of Project Dossier.
