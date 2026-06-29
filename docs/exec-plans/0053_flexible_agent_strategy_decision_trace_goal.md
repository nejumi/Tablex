# Goal 0053: Flexible Agent Strategy Decision Trace

## Objective

Prevent AgentRunner integration from becoming a closed recipe executor. Codex, Skill runners, and future controlled research runners should be able to use current project evidence, reusable assets, relational context, and fresh research to propose, revise, reject, or request more context for approaches. The harness owns evaluation, safety, artifacts, lineage, approvals, and credential boundaries.

## Implemented Scope

- Added `runner_autonomy_policy` and `open_ended_approach_space` to planner-generated AgentTaskContracts.
- Added `approach_decision_trace` as a required runner output.
- Updated `LocalStubAgentRunner` to emit `approach_decision_trace.json` with:
  - autonomy policy
  - context used
  - advisory candidates considered
  - fixed predefined recipe execution explicitly rejected as the product default
  - deferred relational safety checks when present
  - open hypotheses and research/Skill needs
  - hard safety and evaluation constraints
- Added decision trace artifact ids to planned and Idea-backed LocalStub job outputs.
- Extended AgentTaskResults API and Experiments UI with strategy trace summaries and preview/download actions.
- Updated Home Credit-like and standard API flow coverage to assert open-ended policy and decision trace propagation.
- Added `.env` to `.gitignore` and documented standard Kaggle env var names while keeping credentials out of runner workspaces.

## Deferred Scope

- Real Codex execution that produces a project-specific decision trace after code/research work.
- Human approval UI for runner-proposed new approach classes.
- Harness-only Kaggle downloader. Credential handling remains out of runner scope.

## Risks And Open Decisions

- LocalStub proves artifact shape and UI propagation only; it does not validate approach quality.
- Decision traces must stay expressive enough for novel approaches. Future schemas should avoid over-constraining runner reasoning.
- Secrets and connector credentials must never be copied into AgentTaskContracts, prompts, artifacts, or controlled workspaces.
