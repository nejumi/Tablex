# 0124 Sol Review Hardening Directive

## Why This Exists

The GPT-5.6 Sol review reframed the next Tablex work from feature breadth to product trust. Tablex is already more than a Codex wrapper, but it must now prove that it makes Codex safer, more reproducible, and easier to operate rather than becoming a large protocol bureaucracy around the same raw work.

This directive absorbs the review without changing Tablex's core philosophy: Codex owns reasoning; Tablex owns fixed-format validation, artifacts, lineage, evaluation contracts, credentials, safety boundaries, and human navigation.

## Absolute Constraints

- Do not add natural-language keyword routers, heuristic target inference, or harness-authored analysis prose.
- Do not add static HTML notebook fallbacks.
- Do not turn TabPFN, LLM feature augmentation, or model-zoo work into harness-owned strategy logic. Those remain Skill/equipment concerns unless a later explicit phase asks otherwise.
- Do not jump to SaaS, Kubernetes, external connectors, W&B/MLflow, or complex RBAC UI before the local vertical slice proves durable.

## Workstream L1: Trust Boundary

Current state: authentication exists, but project authorization is not yet a full multi-user security boundary. Admin storage endpoints must not be callable by a non-admin authenticated user. The product must state clearly whether it is operating as local single-user or multi-user-safe.

Implementation direction:

- Add factual runtime capability fields that distinguish `auth_enabled`, `authorization_model`, and Codex/runner readiness.
- Require an admin user for `/api/admin/*` endpoints when auth is enabled.
- Scope project listings by owner for non-admin users when auth is enabled.
- Add project/artifact scoped checks for marimo session open/proxy as a follow-up. Native marimo must not be reachable merely because a session id leaked.

Acceptance:

- Auth-disabled local mode remains smooth.
- Auth-enabled non-admin users cannot call admin storage APIs.
- Auth-enabled non-admin users do not see all projects in `/api/projects`.
- The docs make clear that full multi-user project isolation is not claimed until the remaining endpoints use project-scoped authorization.

## Workstream L2: Network And Research Boundary

Current state: prior-knowledge research assumes web-enabled Codex in several places, but Tablex can run with network-off, local models, or constrained runners.

Implementation direction:

- Network-off research may use Codex internal knowledge only as non-source-backed prior knowledge.
- Source-backed research completion requires external or locally provided sources registered as Evidence/Report/Skill assets.
- UI and agent context should distinguish `source_backed=true` from `source_backed=false`; this is factual provenance, not a quality heuristic.

Acceptance:

- The product contract states that offline prior-knowledge notes are hypotheses, not Evidence.
- Codex can still reason from internal knowledge when internet is disabled, but cannot mark source-backed research complete unless sources exist or it explicitly records no source-backed findings.

## Workstream L3: Pipeline Dependency Safety

Current state: pipeline registration creates an isolated venv and may install agent-authored `requirements.txt`.

Implementation direction:

- Keep isolated venvs, but expose dependency policy in ack/runtime metadata.
- Separate registration from dependency installation when policy requires approval.
- Record install logs as artifacts for failed and successful validations.
- Continue rejecting URLs, local paths, editable installs, and installer options in requirements.

Acceptance:

- A pipeline with installable dependencies has visible dependency policy and logs.
- Dependency installation is never a silent hidden side effect.

## Workstream L4: Persistence Integrity

Current state: GC can reduce disk usage, but lifecycle and lineage state must stay explicit.

Implementation direction:

- Add tombstone or retained metadata for physically removed artifact files.
- Add orphan artifact-directory detection for content-hash dedup paths.
- Keep artifact lineage inspectable after GC.

Acceptance:

- A user can tell whether an artifact is present, GC-removed, or missing unexpectedly.
- GC reports include DB and filesystem effects separately.

## Workstream L5: Read Path Purity And Worker Atomicity

Current state: some GET endpoints still mutate convenience state; worker job claiming is not an atomic compare-and-set.

Implementation direction:

- Remove write side effects from GET endpoints.
- Claim jobs with an atomic update guarded by current status and lock staleness.
- Keep stale-lock recovery.

Acceptance:

- `/research-plan/timeline` does not write plan state.
- Two workers cannot both claim the same queued job through normal DB semantics.

## Workstream L6: Tablex vs Raw Codex Evidence

Current state: Tablex has rich tests and live evidence, but it has not yet proven its incremental value over raw Codex.

Implementation direction:

- Define a small benchmark comparing Tablex Full Auto against raw Codex on the same tabular project.
- Measure time to defensible baseline, leakage issues found, evaluation-contract quality, notebook/report completion, pipeline rerun success, forward validation readiness, user interventions, token cost, and reusable artifacts.

Acceptance:

- A golden slice records not just "Tablex works" but "Tablex makes Codex more reliable and inspectable than raw Codex."

## Workstream L7: Surface Responsibility Audit

Current state: Home, Leaderboard/model drawers, Notebooks, and Assets have become the real user navigation surfaces. The legacy Insights tab may now overlap with the canonical asset inventory and contextual related-output drawers.

Implementation direction:

- Audit whether Insights still has a unique user task.
- Preserve a deliberate insight-delivery path even if the old Insights tab taxonomy is retired. The problem is not only tab redundancy; human-readable reports, findings, and notebooks are often saved as artifacts without being actively delivered to the user.
- Make the surface answer "what should I read now?" before showing shelves or inventories.
- If the old Insights tab does not have a unique task after this, fold it into Assets as a saved filter or Home signal instead of maintaining another top-level destination.
- Do not add another top-level tab to compensate.

Acceptance:

- A first-time user can explain why each top-level tab exists.
- Notebook/report/research discovery has one canonical inventory plus context-specific drawers, not several competing places.
- Newly registered readable outputs are visible through a reading queue or equivalent delivery path rather than only through artifact inventory.

## Initial Execution Order

1. L1 partial trust boundary: admin checks, project list scoping, explicit local/multi-user capability fields.
2. L2 contract wording for offline research.
3. L5 read-path and job-claim corrections.
4. L3 dependency policy visibility.
5. L4 GC lifecycle.
6. L6 value benchmark.
7. L7 surface responsibility audit.
