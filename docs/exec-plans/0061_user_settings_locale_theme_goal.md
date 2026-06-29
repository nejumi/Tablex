# 0061 User Settings Locale Theme Goal

## Goal

Add always-available User Settings from the top-right app chrome. Settings should cover display theme and language preferences without treating localization as a fixed closed list.

## Implementation Plan

- Add a top-right settings icon in the main UI.
- Store workbench preferences locally in browser `localStorage`.
- Support Light and Dark display modes through a theme attribute and CSS tokens.
- Represent language as LocalePack data, not a hard-coded language enum.
- Seed built-in `en-US` and `ja-JP` LocalePacks.
- Allow users to add a missing locale as a dynamic local LocalePack that falls back to English until a reviewed pack exists.
- Make app chrome, navigation tabs, global controls, create-project controls, settings, and persistent Agent Chat copy LocalePack-driven.
- Let users create a harness-owned `generate_locale_pack` AgentTaskContract for future Codex/runner localization work.

## In Scope

- Frontend User Settings panel.
- LocalePack catalog and English fallback behavior in the shell UI.
- Locale-driven tab labels and common top-level UI copy.
- Light/Dark theme toggle for the main workbench surfaces.
- Documentation updates.

## Out Of Scope

- Full application-wide translation coverage for every tab body.
- Translation of all panel titles, table headers, action tooltips, and domain empty states.
- Backend persistence for user settings.
- Real Codex execution that writes a completed locale pack back into the app.
- Organization/user account settings.
- Silent localization of artifact/report/runner-generated content. Those should become explicit translated assets with lineage.

## Risks and Open Questions

- Current locale packs live in browser storage; project/team-level settings will need a backend model later.
- Dynamic locale packs currently provide fallback rendering and AgentTask planning, not automatic trusted translation ingestion.
- The monolithic frontend still needs a fuller i18n key extraction pass before every body panel, table header, tooltip, and empty state can be translated consistently.
- Dark mode uses CSS tokens for main surfaces and targeted legacy overrides; future visual refinement should continue as UI components are split.

## Locale Scope Decision

- Tier 1: App chrome, navigation tabs, global controls, form placeholders, settings, and chat affordances are LocalePack-driven now.
- Tier 2: Reusable panel titles, table headers, tooltips, and empty-state guidance should move into LocalePacks as components are split out.
- Tier 3: Artifact/report/runner-generated content should be localized only through explicit translated Report/Artifact assets with lineage.
- Tier 4: Dataset values, column names, status enum values, IDs, artifact names, schema names, and runner contract fields remain source data unless a task explicitly creates a mapped display layer.
