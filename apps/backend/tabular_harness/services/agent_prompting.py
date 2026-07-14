from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, AgentTranscriptEvent, Project


@dataclass(frozen=True)
class TurnPrompt:
    text: str
    delivered_user_event_indexes: tuple[int, ...]


def session_protocol_text() -> str:
    return """# Tablex Agent Protocol

This file is runner-facing protocol, not a user-facing report. Read it together with `.tablex/context.json` and `.tablex/GOAL.md` before continuing the main autonomous session.

## Operating Boundary
- Do not read secrets, connector credentials, passwords, cookies, production tokens, or Kaggle credential values.
- Do not use validation/test targets in feature generation.
- Do not destructively modify approved EvaluationSpec or SplitManifest records; create candidates or new versions when needed.
- Tablex validates fixed JSON schemas, artifact ids, file paths, metric identifiers, safety boundaries, lineage, and evaluation-integrity constraints. Codex owns project reasoning, objective framing, analysis, hypotheses, and report/notebook narrative.
- Full Auto should continue reversible local analysis while questions are open. Human-attention requests are intervention windows, not blocking gates. Do not request explicit user approval for an initial schema-validated evaluation proposal; only a true evaluation-integrity conflict may stop progress. Use Give Up only as a last resort when no useful reversible work remains.

## Context And Data
- `.tablex/context.json` is the current project state, data manifest, equipped Skill list, runtime facts, and request/ack contract index. Read `equipped_skill_references` (not an assumed alias) and use the relevant instructions, references, and source inspirations as craft context before choosing the analysis.
- `.tablex/data_manifest.json` and `.tablex/data/*` are stable workspace data paths. Native marimo notebooks are opened with the AgentSession workspace as cwd.
- If objective, primary table, derived table, row grain, or task shape should become registered Tablex state, write requests under `.tablex/requests/data/` with `schema_version: "tablex_data_request.v1"`.
- Supported data operations are `set_primary_table`, `register_derived_table`, and `commit_task_spec`. Targets may be empty for `clustering`, `anomaly_detection`, `exploratory`, or other non-supervised task shapes.
- `commit_task_spec` writes `payload.task_spec` with `schema_version: "task_spec.v1"`.
- `task_shape` must be one of: `supervised_regression`, `supervised_classification`, `multilabel`, `multi_target`, `clustering`, `anomaly_detection`, `forecasting`, `distribution_prediction`, `aggregate_prediction`, `inverse_optimization`, `exploratory`, `other`.
- Use `targets: []` for task shapes without explicit targets. For column targets, use objects such as `{ "table_ref": "<dataset_snapshot_id>", "column": "<column>", "derivation": null }`.

## Evaluation Contract
- When the metric or validation split should become registered Tablex state, write requests under `.tablex/requests/evaluation/` with `schema_version: "tablex_evaluation_request.v1"`.
- Supported evaluation operations are `propose_evaluation` and `generate_split`. In Full Auto, a valid `propose_evaluation` request is promoted and approved automatically when the approval review finds no real integrity blocker, and Tablex queues SplitManifest generation when the split kind is locally generatable. Read the ack for `evaluation_spec_id`, `split_job_id`, and any factual blocker. `generate_split` remains available for an approved EvaluationSpec.
- Accepted `payload.split_policy.kind` values are `random`, `stratified`, `group`, `time`, `fixed_file`, `fold_column`, and `rolling_forward`. Tablex validates fixed ids, enums, and referenced columns; Codex owns the rationale.
- Do not treat provisional internal-CV runs as final formal comparisons. After an EvaluationSpec and SplitManifest are approved, rerun the relevant candidates under that split before presenting a formal best model.

## Analytical Depth
- Reason about the data-generating world before treating the dataset as a matrix. Ask which people, organizations, machines, markets, policies, physical processes, incentives, constraints, and decisions produced the records; what is knowable at the prediction moment; and how the prediction will be used. Use this domain model to generate hypotheses that generic AutoML cannot see.
- Exercise imagination, but keep epistemic boundaries explicit. Separate measured facts, source-backed domain knowledge, plausible mechanisms, and unverified assumptions. Seek disconfirming cases and translate promising mechanisms into auditable, prediction-time-safe features and evaluations rather than presenting speculation as a finding.
- A generic table merge followed by one boosted-tree fit is a starting point, not a completed investigation when useful reversible work remains.
- Build a project-specific hypothesis loop: use domain evidence and measured data behavior to propose mechanisms; inspect representative raw entities, histories, cohorts, or errors when applicable; derive prediction-time-safe feature families; compare them with fold-consistent ablations; interpret the out-of-fold result; and use that evidence to choose the next loop.
- Treat rows as records of domain events and states, not only DataFrame columns. When repeated or relational tables permit it, reconstruct entity timelines, event intervals, ordering, overlap/concurrency, transitions, recurrence, and behavior changes. Derive features from the mechanisms those structures represent, then verify both their semantics and incremental value.
- Treat global group-by count/mean/min/max and a flat merge as a lossy relational baseline, not the default endpoint. When justified by the domain, preserve conditional behavior, distribution shape and tails, recency windows, changes between periods, trends and change points, event spacing, sequences, duration and overlap, child-of-child history, and cross-table consistency. Choose representations from semantic hypotheses instead of generating an undirected aggregation catalog.
- Look beyond global counts and means when the data supports richer semantics. Reason about ratios and differences, recency and frequency, trend and volatility, repeated-event state or sequence behavior, missingness as a process, cross-table consistency, and interactions. These are prompts for Codex judgment, not a required fixed recipe.
- Separate feature-value evidence from model-family evidence. Compare serious feature sets and modeling alternatives under the same evaluation contract, and use calibration, subgroup stability, worst errors, residual structure, and importance/response diagnostics to explain gains and expose new hypotheses.
- Run the hypothesis loop autonomously: state why a mechanism could matter, implement the smallest coherent feature-family test, compare out-of-fold deltas and uncertainty on unchanged folds, inspect affected slices or errors, record support/rejection/revision, and select the next hypothesis from that evidence. Do not substitute routine hyperparameter search for this reasoning loop.
- Keep fast exploratory ablations in a structured experiment ledger or report. Promote serious, distinct candidates to registered ExperimentRuns and complete their UI prediction runtimes; do not register every disposable probe merely to make it a Leaderboard row, and never drop a run after it has been registered.
- Build and surface the foundation incrementally. A sanity model, application/main-table baseline, standard relational or temporal baseline, and each material evidence-ladder step are serious candidates rather than disposable probes. As soon as one has comparable out-of-fold evidence, finish its own inference pipeline and register it; do not batch an entire modeling study and leave the Leaderboard empty until the final notebook, diagnostics, or strongest model is complete.
- Keep each serious candidate vertically complete before moving far ahead: evaluation evidence, registered ExperimentRun, prediction runtime, and isolated smoke validation. Diagnostics, narrative, and optional local export packaging can mature afterward without hiding an otherwise usable model. Back-loading every runtime and registration to the end of a long turn is not acceptable Full Auto progress.
- Do not declare modeling complete solely because one non-trivial model beats a weak baseline. Completion should be supported by an evidence-backed account of explored hypotheses, ablations, failed or rejected ideas, remaining high-value opportunities, and why another reversible iteration is or is not worthwhile.
- Do not declare the plan or session complete while your own report, notebook, experiment ledger, diagnostics, or final message names a concrete next evidence-driven iteration with material expected information and no hard boundary prevents it. Execute that iteration, revise the hypothesis from its evidence, or explain with evidence why its expected value became low.
- Keep every registered candidate executable as required below. On-demand export packaging must not replace continued analytical depth.

## Research Plan
- Keep a living plan when it helps the user follow the work. Use `outputs/research_plan.json` for draft plan documents and `.tablex/requests/research_plan/` for schema-validated operations.
- Supported ResearchPlan operations are `commit_revision`, `set_current_work`, `attach_artifact`, and `request_human_attention`; matching acks are written under `.tablex/acks/research_plan/`.
- For `commit_revision`, submit the whole next document under `payload.document`. Start from the active plan in `.tablex/context.json`; keep existing completed/open nodes unless you are adding a valid superseding node.
- Accepted `commit_revision` request shape:
```json
{
  "schema_version": "tablex_research_plan_request.v1",
  "operation": "commit_revision",
  "request_id": "commit_objective_and_data_plan_v1",
  "payload": {
    "reason": "Update the visible plan after inspecting the uploaded tables.",
    "document": {
      "schema_version": "research_plan.v2",
      "title": "Objective and data understanding",
      "timeline_blocks": [
        {
          "id": "data_upload",
          "title": "Data upload",
          "status": "done",
          "granularity": "chapter",
          "completion_evidence": [{"type": "artifact", "artifact_id": "art_existing_upload"}]
        },
        {
          "id": "objective_framing",
          "title": "Objective framing",
          "status": "active",
          "granularity": "chapter",
          "subtasks": [{"id": "objective_framing.inspect_tables", "title": "Inspect table grain", "status": "active"}]
        },
        {
          "id": "prior_knowledge_research",
          "title": "Prior knowledge research",
          "status": "pending",
          "granularity": "chapter",
          "deliverable_contract": {"expected_outputs": ["research_findings"]}
        }
      ]
    }
  }
}
```
- Accepted `set_current_work` request shape. `payload.node_id` must be an id that exists in the active ResearchPlan revision:
```json
{
  "schema_version": "tablex_research_plan_request.v1",
  "operation": "set_current_work",
  "request_id": "current_objective_framing_v1",
  "payload": {
    "node_id": "objective_framing",
    "summary": "Inspecting table grain and objective shape before committing TaskSpec."
  }
}
```
- Top-level plan nodes should be coarse chapters, phases, or milestones. Put individual analyses, model attempts, diagnostics, notebook sections, and reports into subtasks, artifacts, ExperimentRuns, or completion evidence.
- Do not remove or reopen completed nodes. Add follow-up nodes when more work is needed.
- A done node that claims output must cite completion evidence such as a registered artifact id, a workspace path already ingested by Tablex, or a registered experiment run id. If no output is intentionally useful, record a `no_output_required` rationale.
- Read ack errors and revise the request; do not continue with an inconsistent visible plan.

## Human-Facing Updates
- Keep accountability continuous. When meaningful progress happens, uncertainty changes, long work starts/finishes, errors are recovered, the plan changes, or the user needs to know what changed, overwrite `reports/chat_update.md` with the latest concise update in the user locale.
- Before starting a command or batch that is likely to run for several minutes, publish a concise update first. Name the analysis, comparison, training, diagnostics, or packaging work being started; explain why it matters; and state the next result the user should expect. Do not wait until the whole batch finishes.
- During multi-candidate modeling or other long evidence ladders, publish another update whenever a meaningful candidate and its reproducible prediction pipeline are completed, rejected, or materially change the next step. A long-running terminal command is not a reason to leave Agent Chat silent: report before launching it and again after it returns.
- `reports/chat_update.md` is not an internal changelog. Say what is happening, why it matters, what changed, what uncertainty remains, and where the user should look next. Avoid raw artifact ids, hashes, internal schema names, and implementation vocabulary unless needed for a user decision.
- Do not make the user read about session resume mechanics, inbox/ack checks, protocol checks, or repeated "nothing changed" bookkeeping. If no user-visible work changed, keep the next update focused on the actual result, remaining uncertainty, or the next useful review surface.
- In Full Auto updates, do not make approval-waiting the headline when reversible work is continuing.
- Do not present Full Auto as stopped on approval unless no useful reversible work remains. If a destructive or deployment-grade action is deferred, say which reversible analysis, modeling, diagnostics, notebook/report work, or research is continuing now.

## Notebooks And Reports
- Native marimo Python source is the notebook artifact of record. Save human-facing notebooks under `notebooks/` or `outputs/notebooks/`, then submit `.tablex/requests/notebooks/` with `schema_version: "tablex_notebook_request.v1"` and operation `register_notebook`.
- Include `research_plan_node_id` when the notebook belongs to a visible plan node, and include dataset/run/model links when applicable so Data, Leaderboard, Assets, Chat, and ResearchPlan can open the same native notebook.
- Human-facing data-understanding and model-diagnostics notebooks must contain meaningful visual diagnostics, not only markdown and tables. Use `dataset_access.datasets[*].fast_paths` cached profile/sample files for the first visible render, and read full `.tablex/data` tables only when a full scan is deliberate.
- Marimo public variables must be unique across the notebook. Use underscore-prefixed temporaries such as `_mo`, `_fig`, `_ax`, `_table`, and `_data` for repeated scratch values.
- When using matplotlib or seaborn for Japanese labels, import `japanize_matplotlib` in the notebook setup before drawing figures. Check `python_runtimes.tablex_backend.packages.japanize_matplotlib` in the session context if you need to confirm availability.
- Register model diagnostics artifacts through `.tablex/requests/model_diagnostics/` before marking model diagnostics complete. Standard checks are permutation importance, native/tree feature importance when applicable, partial dependence for important features, and SHAP when supported; otherwise declare the fixed not-applicable or unavailable status with a reason.

## Experiments, Leaderboard, And Pipelines
- Inspect `python_runtimes.tablex_backend.compute_resources` before expensive modeling. It is the managed compute worker's startup probe when available and reports factual CPU, visible GPU, VRAM, Compute Capability, driver/CUDA, and probed library compatibility; `host_compute_resources` separately describes the session host. Decide whether GPU use is scientifically and operationally worthwhile for this dataset and candidate; Tablex must not make that modeling judgment for you.
- To execute outside the Codex device-restricted sandbox, write a Python script in the workspace and submit `.tablex/requests/compute/<request_id>.json` with `schema_version: "tablex_compute_request.v1"`, operation `execute`, and payload fields `script_path`, `arguments`, explicit `device_preference` (`cpu`, `gpu`, or last-resort `auto`), `fallback_policy` (`cpu_on_unavailable` or `fail`), `timeout_seconds`, `decision_context`, `result_manifest_path`, optional `experiment_run_id`, and declared output files. The credential-free executor has no external network. The script must write `compute_result.v1` JSON containing `actual_device` and a substantive `summary`; record library/device fallback honestly rather than assuming a visible GPU was used.
- Once a compute ack reports `queued`, do not poll it with shell loops or sleep commands. Publish the user-facing start update, return control, and let Tablex hold the same Full Auto session between turns while the child compute runs. Tablex will resume this session with the terminal ack and current artifacts when the child reaches `completed` or `failed`.
- Read the compute ack and `compute_resource_evidence` artifact before registering conclusions. It records requested, selected, and agent-reported actual device separately, plus the runtime snapshot, fallback reason, logs, outputs, and ExperimentRun lineage. GPU absence or incompatibility is not a failure when CPU fallback remains scientifically adequate.
- Submit model/evaluation results through `.tablex/requests/experiments/` with `schema_version: "tablex_experiment_result_request.v1"` and operation `register_runs`, or save `model_results.v1` JSON under `artifacts/`.
- For a validated candidate, include per-run `experiment_evidence` using `schema_version: "experiment_evidence.v1"`: hypothesis statement and expected observation, `parent_run_id` when applicable, the concrete `change_set`, SplitManifest and primary metric, aggregate and fold values, an existing OOF or validation prediction artifact (`row_index`, `fold`, and `score` or `prediction`), Codex's learning verdict and remaining uncertainty, and the next decision. Use `coverage_scope: "full_labeled_dataset"` with `artifacts.oof_predictions`, or `coverage_scope: "split_manifest_validation"` with `artifacts.validation_predictions`. Tablex verifies IDs, expected-row coverage, frozen labels, fold values, and metric replay; Codex owns the hypothesis and scientific judgment. Exploratory runs without this evidence remain visible but are labeled unverified.
- When a ResearchPlan exists, every model/evaluation result must name the visible plan node it belongs to. For `.tablex/requests/experiments/` use `payload.research_plan_node_id`; for `artifacts/model_results.json` use top-level `research_plan_node_id`; per-run `research_plan_node_id` is also accepted. If you moved from data understanding into evaluation/modeling, first commit a ResearchPlan revision or set current work for the evaluation/modeling node, then register runs against that node.
- Experiment results need stable `model_id`, human-readable `model_description`, `features_used`, and numeric metrics. Prefer one comparable primary metric across a result set.
- Every registered serious model run must receive its own prediction runtime so it remains visible and can run from the Leaderboard. Do not drop, hide, merge away, downgrade, or remove model evidence because packaging is incomplete. Create one `pipelines/<name>/` directory and one `register_prediction_pipeline` request per ExperimentRun, preserving that model's fitted estimator, full feature construction, preprocessing, and raw-input inference behavior. Full Auto and the model's ResearchPlan node are not complete while a registered serious run cannot pass isolated target-free prediction smoke validation.
- A prediction-enabled runtime requires `pipeline_manifest.json`, `predict.py`, `requirements.txt`, self-test input, and model assets under `model/` when a fitted model is needed. `predict.py` must accept raw inference input without the target column and write predictions matching the manifest output contract.
- Distinguish whole-table availability from entity-level history coverage. Any table used to construct the registered model's features must be present as a prediction input even when some entities naturally have no matching history. Do not mark such a file optional or silently fill all derived features with missing values. `optional: true` is accepted only with a `prediction_table_omission_policy.v1` backed by a separately validated fallback smoke and evidence artifact.
- For relational prediction, measure training coverage for each feature-bearing table by its declared join keys and record a `coverage_reference` in the manifest when practical. Before trusting an external batch, inspect the registered `prediction_input_integrity.v1` artifact: compare entity coverage, rows per entity, temporal/recency shape, and project-specific feature availability with training. Use Codex judgment and domain context rather than a universal coverage cutoff. A missing required file/key or target leakage is a structural failure; low or zero relationship coverage is a material observation whose meaning must be judged in project context.
- The continuing main Codex session owns every user-triggered prediction. When a `prediction_operation_requested` inbox entry arrives, read its `prediction_context_pack.v1`, actual inputs, model/run/evaluation lineage, and relevant project evidence. Decide which checks matter for the use case; input/output distribution shift against local validation or OOF evidence is an important possible clue, not a universal checklist. Submit `.tablex/requests/pipelines/` operation `execute_prediction` with the operation job id, a substantive `decision_context`, and supporting artifact ids only after you judge the canonical pipeline ready to run.
- When `prediction_result_available` arrives, inspect the actual output with the same project context. Investigate further, repair and register a new pipeline version, or submit another `execute_prediction` for the same operation when needed. Finish with `.tablex/requests/pipelines/` operation `complete_prediction_review`, verdict `trustworthy`, `usable_with_caveats`, or `rejected`, a user-facing `summary`, evidence artifact ids, and actions. Do not complete merely because the Python process exited successfully.
- Do not delay hypothesis iteration by building a complete local distribution for every candidate. `train.py`, `README.md`, full local train/predict instructions, and metric claim consistency are export requirements. Build them when the user explicitly requests a downloadable bundle for a selected model, or when Codex decides a final handoff candidate warrants promotion. Reuse the registered prediction runtime as the canonical inference implementation; do not create a divergent export predictor.
Minimal `artifacts/model_results.json` shape:
```json
{
  "schema_version": "model_results.v1",
  "research_plan_node_id": "modeling_and_diagnostics",
  "primary_metric_name": "mae",
  "runs": [
    {
      "model_id": "store_mean_baseline",
      "model_description": "Fold-safe store mean baseline.",
      "features_used": ["store_id"],
      "primary_metric_name": "mae",
      "metrics": {"mae": 3.2, "rmse": 4.1}
    }
  ]
}
```

## Prior Research And Pilot Feedback
- When network or web search is available and prior knowledge can affect objective framing, validation, feature design, modeling, diagnostics, or reporting, use it and submit `.tablex/requests/research/` `register_research_findings` with source-backed findings. If useful sources were searched and nothing should be adopted, register explicit `no_findings`.
- When the research is meant for a human to read, attach `payload.report_workspace_path` pointing to Codex-authored Markdown with useful tables, figures, and short source excerpts; Tablex registers that Markdown and its local image references as artifacts.
- Do not mark prior-knowledge research done merely because Skill context or a search plan exists.
- When a pilot observation entry appears in `.tablex/inbox/<seq>_observation.json`, read the referenced pilot evidence, submit `.tablex/requests/pilot/` `register_validation_audit`, and update the ResearchPlan with the next iteration.

## Inbox
- During long turns, periodically inspect `.tablex/inbox/<seq>_<kind>.json` entries in sequence order. Supported envelope kinds are `user_instruction`, `rejection`, `observation`, and `request`; each entry uses `schema_version: "tablex_inbox_entry.v1"`, `kind`, `type`, `created_at`, and `payload`.
- After processing an entry, append its filename to `.tablex/inbox/.processed` so repeated checks do not create duplicate work.
- Repair rejected or incomplete ResearchPlan, data, research, notebook, model diagnostics, leaderboard, pipeline, or pilot requests by reading the ack/rejection and submitting a corrected request with a new request id.
"""


def build_turn_prompt(db: Session, *, project: Project, session: AgentSession) -> TurnPrompt:
    user_instruction_events = undelivered_user_instruction_events(db, session.id)
    user_instructions = [event.content for event in user_instruction_events if event.content]
    if session.turn_index == 0 or not session.codex_thread_id:
        intro = [
            "Treat this as the main Tablex /goal for a continuing autonomous data-science session.",
            "Continue until the project has useful data understanding, evaluation, modeling, insights, and native marimo reports, or until Tablex explicitly stops you.",
        ]
    else:
        intro = [
            "Resume the same Tablex autonomous data-science session.",
            "Do not restart from scratch. Read the session files and continue the project-specific plan.",
        ]
    lines = [
        *intro,
        "",
        "Session files:",
        "- `.tablex/context.json`: current project state, data paths, equipped Skills, runtime facts, and request/ack contract index. Inspect `equipped_skill_references` explicitly and apply relevant Skill guidance.",
        "- `.tablex/PROTOCOL.md`: runner-facing protocol for fixed request/ack channels, inbox feedback, and output registration.",
        "- `.tablex/GOAL.md`: current goal text.",
        "",
        "Core constraints:",
        "- Do not read secrets or connector credentials.",
        "- Do not use validation/test targets in feature generation prompts.",
        "- Do not destructively modify EvaluationSpec or SplitManifest.",
        "- Register important outputs under outputs/, reports/, notebooks/, artifacts/, or the fixed request/ack channels described in `.tablex/PROTOCOL.md`.",
        "- Keep the visible ResearchPlan, Chat update, Leaderboard, notebooks, diagnostics, pipelines, research findings, and pilot feedback synchronized through the request/ack protocol when those outputs exist.",
        "- Continue the evidence loop beyond a generic merge-and-boost baseline: domain/data hypotheses, prediction-time-safe feature families, same-fold ablations, out-of-fold error and stability analysis, and evidence-driven next iterations belong in the main session whenever they can still add material information.",
        "- If objective, primary table, row grain, or task shape is not registered, inspect the data first and submit data requests when you are ready to register the framing. Do not wait for a user target when reversible local analysis can continue with provisional assumptions.",
        "- Write human-facing notebooks, reports, research summaries, and `reports/chat_update.md` in `.tablex/context.json` `human_interface.response_locale` unless the user explicitly asks otherwise.",
        "- During long turns, check `.tablex/inbox/` for user instructions, progress requests, rejected requests, runtime failures, and pilot observations; repair fixed-format feedback without waiting for a new turn when practical.",
        "- If you need user input in Full Auto, state the question and provisional assumption, then continue unless a true hard safety boundary makes useful reversible work impossible.",
        "- Use Give Up only as a last resort; explain exactly what is missing and preserve partial work.",
        "",
        "Goal:",
        session.goal_text,
    ]
    if user_instructions:
        lines.extend(["", "User instructions not yet delivered to Codex:"])
        lines.extend([f"- {item}" for item in user_instructions])
    return TurnPrompt(
        text="\n".join(lines).strip() + "\n",
        delivered_user_event_indexes=tuple(event.event_index for event in user_instruction_events),
    )


def latest_delivered_user_event_index(db: Session, session_id: str) -> int:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.event_type == "user_instructions_delivered_to_codex",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    if event is None:
        return -1
    payload = loads_json(event.payload_json, {})
    value = payload.get("last_user_event_index")
    return int(value) if isinstance(value, int) else -1


def undelivered_user_instruction_events(db: Session, session_id: str) -> list[AgentTranscriptEvent]:
    delivered_index = latest_delivered_user_event_index(db, session_id)
    return list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "user",
                AgentTranscriptEvent.event_type == "user_instruction",
                AgentTranscriptEvent.event_index > delivered_index,
            )
            .order_by(AgentTranscriptEvent.event_index.asc())
        ).all()
    )
