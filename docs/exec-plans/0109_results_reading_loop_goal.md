# Goal 0109: Results Reading Loop

## Objective

Connect Experiments, Leaderboard, diagnostics, notebooks, and reports into a readable post-run loop. A user should be able to ask Agent Chat about results and receive guidance, while leaderboard/comparison state changes are made by explicit readout/comparison endpoints or validated proposals.

## Implemented Scope

- Deprecated: Agent Chat natural-language intents were removed. Result reading uses explicit readout/comparison endpoints and future schema-validated proposals for:
  - Showing the Leaderboard Reader.
  - Comparing current top/successful runs.
- Chat routes to Experiments when no successful run exists.
- Chat routes to Leaderboard when successful runs exist.
- Top-run comparison creates an `experiment_comparison` artifact, report, evidence, insight, and lineage through the existing experiment lifecycle service.
- Leaderboard Reader now exposes top-run actions directly:
  - Top Run Diagnostics.
  - Top Run Report.
  - Diagnostics Notebook.
- The primary Leaderboard row action now loads the diagnostics preview when diagnostics are generated.

## Design Rules

- Leaderboard ranks are not decisions by themselves.
- Run comparison must remain downstream of EvaluationSpec and SplitManifest.
- Diagnostics, run reports, and notebooks should be visible from the same reading surface as the rank.
- If a user asks for leaderboard before run evidence exists, route them to Experiments instead of showing an empty scoreboard as if it were useful.

## Validation Plan

- `ruff check apps/backend/tabular_harness/services/agent_chat.py apps/backend/tests/test_api_flow.py`
- `mypy apps/backend/tabular_harness`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest apps/backend/tests/test_api_flow.py -k "agent_chat_runs_core_harness_actions or project_upload_profile_evaluation_split_flow"`
- `npm run build`
- Full validation before commit:
  - `ruff check apps/backend`
  - `mypy apps/backend/tabular_harness`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest apps/backend/tests`
  - `npm run lint`
  - `npm run build`
- Browser validation:
  - Created a temporary project with approved EvaluationSpec, SplitManifest, baseline run, leaderboard chat, and top-run comparison chat.
  - Confirmed Leaderboard remains a primary tab.
  - Confirmed Leaderboard Reader shows top-run diagnostics, top-run report, and diagnostics notebook actions.

## Deferred

- A richer run comparison reader that previews the latest `experiment_comparison_report` directly in Leaderboard.
- Chat action to generate diagnostics and decision report in one bounded post-run workflow.
