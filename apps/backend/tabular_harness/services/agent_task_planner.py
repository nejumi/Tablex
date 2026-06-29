from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    Assumption,
    DatasetSnapshot,
    EvaluationSpec,
    Job,
    Project,
    Question,
    SemanticCatalog,
    SplitManifest,
)
from tabular_harness.schemas import AgentTaskContract
from tabular_harness.services.approach import (
    artifact_metadata,
    build_recommended_approaches,
    build_research_query_plan,
    latest_project_artifact,
    recommend_research_assets,
    research_asset_context,
    research_plan_contract_inputs,
    store_json_artifact,
    summarize_columns,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.asset_library import seed_default_assets


@dataclass(frozen=True)
class AgentTaskPlanResult:
    contract: dict[str, Any]
    artifact: Artifact
    dataset_snapshot_id: str | None
    evaluation_spec_id: str | None
    split_manifest_id: str | None


def plan_project_agent_task(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
    objective: str | None = None,
    task_type: str = "implement_prediction_approach",
) -> AgentTaskPlanResult:
    seed_default_assets(db, store)
    dataset = latest_dataset(db, project.id)
    evaluation_spec = latest_approved_spec(db, project.id)
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    context_artifacts = planning_context_artifacts(db, project.id)
    semantic_columns = latest_semantic_columns(db, dataset)
    profile = summarize_columns(semantic_columns)
    assumptions = latest_assumptions(db, project.id)
    questions = latest_open_questions(db, project.id)
    assets = latest_active_assets(db)
    asset_context = [research_asset_context(asset) for asset in assets]
    research_queries = build_research_query_plan(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        profile=profile,
        context_artifacts=context_artifacts,
    )
    asset_recommendations = recommend_research_assets(asset_context, profile, context_artifacts)
    approach_candidates = build_planner_approach_candidates(
        project=project,
        profile=profile,
        context_artifacts=context_artifacts,
    )
    contract = build_agent_task_contract_payload(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        semantic_columns=semantic_columns,
        profile=profile,
        assumptions=assumptions,
        questions=questions,
        context_artifacts=context_artifacts,
        asset_recommendations=asset_recommendations,
        approach_candidates=approach_candidates,
        research_queries=research_queries,
        objective=objective,
        task_type=task_type,
    )
    validate_agent_task_contract(contract)
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_task_contract",
        name=f"agent_task_contract_{job.id if job else new_id('planned')}",
        filename="agent_task_contract.json",
        payload=contract,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "task_id": contract["task_id"],
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
            "recommended_approach_count": len(approach_candidates),
            "research_query_count": len(research_queries),
            "recommended_asset_count": len(asset_recommendations),
            "artifact_expectation_count": len(contract["inputs"]["artifact_expectations"]),
            "benchmark_id": benchmark_context(context_artifacts).get("benchmark_id"),
        },
    )
    create_planner_lineage(
        db,
        project=project,
        artifact=artifact,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        context_artifacts=context_artifacts,
        asset_recommendations=asset_recommendations,
        job=job,
    )
    return AgentTaskPlanResult(
        contract=contract,
        artifact=artifact,
        dataset_snapshot_id=dataset.id if dataset else None,
        evaluation_spec_id=evaluation_spec.id if evaluation_spec else None,
        split_manifest_id=split_manifest.id if split_manifest else None,
    )


def build_agent_task_contract_payload(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    semantic_columns: list[dict[str, Any]],
    profile: dict[str, Any],
    assumptions: list[Assumption],
    questions: list[Question],
    context_artifacts: dict[str, Artifact | None],
    asset_recommendations: list[dict[str, Any]],
    approach_candidates: list[dict[str, Any]],
    research_queries: list[dict[str, Any]],
    objective: str | None,
    task_type: str,
) -> dict[str, Any]:
    research_plan_artifact = context_artifacts.get("research_plan")
    research_inputs = research_plan_contract_inputs(research_plan_artifact)
    source_pack_inputs = research_source_pack_contract_inputs(context_artifacts.get("research_source_pack"))
    synthesis_inputs = research_synthesis_contract_inputs(context_artifacts.get("research_finding_synthesis"))
    relational_plan_inputs = relational_feature_plan_contract_inputs(context_artifacts.get("relational_feature_plan"))
    relational_recipe_inputs = relational_feature_recipe_contract_inputs(
        context_artifacts.get("relational_feature_recipe")
    )
    relational_diagnostics_inputs = relational_feature_scenario_diagnostics_contract_inputs(
        context_artifacts.get("relational_feature_scenario_diagnostics")
    )
    source_policy = source_pack_inputs.get("source_policy") or research_inputs.get(
        "research_source_policy",
        {"network_default": "disabled_until_runner_policy_allows"},
    )
    return {
        "task_id": new_id("agt"),
        "task_type": task_type,
        "project_id": project.id,
        "objective": objective
        or (
            "Plan and implement a project-specific tabular prediction approach inside the controlled "
            "workspace, using current evidence, Skill assets, and approved evaluation constraints."
        ),
        "inputs": {
            "schema_version": "agent_task_planning.v1",
            "dataset_context": dataset_context(dataset, profile, semantic_columns),
            "evaluation_contract": evaluation_contract(evaluation_spec, split_manifest),
            "assumption_context": assumption_context(assumptions, questions),
            "benchmark_context": benchmark_context(context_artifacts),
            "available_context_artifacts": available_context_artifacts(context_artifacts),
            "constraints": safety_constraints(project),
            "recommended_approach_candidates": approach_candidates,
            "research_queries": research_queries,
            "library_recommendations": asset_recommendations,
            "reporting_requirements": reporting_requirements(),
            "artifact_expectations": artifact_expectations(),
            "allowed_research_modes": ["project_artifacts", "skill_library", "controlled_web_search"],
            "must_respect_split_manifest": True,
            "recommended_asset_ids": research_inputs.get("recommended_asset_ids", []),
            "recommended_asset_version_ids": research_inputs.get("recommended_asset_version_ids", []),
            "research_source_policy": source_policy,
            "research_source_pack": source_pack_inputs,
            "research_finding_synthesis": synthesis_inputs,
            "relational_feature_plan": relational_plan_inputs,
            "relational_feature_recipe": relational_recipe_inputs,
            "relational_feature_scenario_diagnostics": relational_diagnostics_inputs,
        },
        "required_outputs": [
            {
                "path": "reports/approach_report.md",
                "schema": "markdown_report.v1",
                "description": "Self-contained report with approach choice, implementation notes, metrics, risks, citations, and next actions.",
            },
            {
                "path": "artifacts/feature_recipe.json",
                "schema": "feature_recipe.v1",
                "description": "Train-fold-safe feature generation recipe, including rejected or deferred feature families.",
            },
            {
                "path": "artifacts/experiment_metrics.json",
                "schema": "experiment_metrics.v1",
                "description": "Metrics computed only with the harness EvaluationSpec and SplitManifest.",
            },
            {
                "path": "artifacts/visualization_spec.json",
                "schema": "visualization_spec.v1",
                "description": "Portable visualization spec for leaderboard, diagnostics, and report panels.",
            },
            {
                "path": "artifacts/evidence.json",
                "schema": "evidence_set.v1",
                "description": "Artifact-backed evidence, including source summaries for any external claims.",
            },
        ],
        "quality_checks": [
            "Use the approved EvaluationSpec and SplitManifest when they exist.",
            "Fit preprocessing and feature extraction on the training split only.",
            "Compare against a sanity floor and explain failures or non-improvements.",
            "Register important outputs as artifacts with lineage-ready metadata.",
            "Return report and visualization outputs that are understandable inside Tablex UI.",
        ],
        "forbidden_actions": [
            "Do not read secrets or connector credentials.",
            "Do not pass connector credentials to any agent, script, prompt, or workspace file.",
            "Do not use validation/test targets in feature generation prompts, encoders, joins, or imputers.",
            "Do not destructively modify evaluation_spec or split_manifest.",
            "Do not write to production databases or external systems.",
        ],
        "context_files": [
            "AGENTS.md",
            "docs/dev.md",
            "schemas/agent_task_contract.schema.json",
            "schemas/agent_result.schema.json",
            "schemas/visualization_spec.schema.json",
        ],
        "output_schema_path": "schemas/agent_result.schema.json",
        "assumption_context": {
            "target_column": project.target_column,
            "unresolved_count": len([item for item in assumptions if item.status not in {"confirmed", "retired"}]),
            "requires_source_backed_claims": True,
        },
        "autonomy_level": 3,
    }


def build_planner_approach_candidates(
    *,
    project: Project,
    profile: dict[str, Any],
    context_artifacts: dict[str, Artifact | None],
) -> list[dict[str, Any]]:
    candidates = build_recommended_approaches(project, profile)
    relational_metadata = artifact_metadata(context_artifacts.get("relational_catalog"))
    if int(relational_metadata.get("table_count") or 0) > 1:
        candidates.append(
            {
                "title": "Relational aggregation and entity-history approach",
                "approach_type": "relational_feature_recipe",
                "hypothesis": (
                    "Supporting tables may add signal if joins, aggregation windows, and entity leakage "
                    "are validated against the harness split."
                ),
                "rationale_md": (
                    "Use RelationalCatalog and benchmark/source context to propose aggregation features. "
                    "Do not apply automatic joins until key semantics and prediction-time availability are clear."
                ),
                "feature_strategy": {
                    "relational": "count, recency, mean/max/min, and recent-window aggregates by confirmed keys",
                    "scenario_compare": ["primary_table_only", "safe_relational_aggregates"],
                    "guardrails": ["fold-safe aggregation", "entity leakage review", "prediction-time availability"],
                },
                "modeling_strategy": {
                    "families_to_consider": ["tree_boosting", "regularized_linear_sanity_floor"],
                    "selection_policy": "promote only if relational lift survives leakage and split checks",
                },
                "evaluation_notes_md": "Prefer group/time-aware validation when relational entity overlap or event time is material.",
                "confidence": 0.52,
                "risk_level": "high",
            }
        )
    if context_artifacts.get("benchmark_scenario_pack"):
        candidates.append(
            {
                "title": "Benchmark-informed approach review",
                "approach_type": "benchmark_context_review",
                "hypothesis": "Benchmark-specific patterns can inform candidate approaches without becoming fixed policy.",
                "rationale_md": (
                    "Use BenchmarkScenarioPack to identify task caveats, table bundle shape, and useful comparison "
                    "points. Treat external benchmark recipes as evidence requiring citation and adaptation."
                ),
                "feature_strategy": {
                    "benchmark_context": "inspect scenario pack, source card, and known leakage caveats",
                    "scenario_compare": ["harness_baseline", "benchmark_informed_candidate"],
                },
                "modeling_strategy": {
                    "families_to_consider": ["task_specific_tree_boosting", "diagnostic_sanity_floor"],
                    "selection_policy": "adapt from evidence rather than copying leaderboard assumptions",
                },
                "evaluation_notes_md": "Keep Tablex EvaluationSpec as the source of truth even for benchmark datasets.",
                "confidence": 0.5,
                "risk_level": "medium",
            }
        )
    return candidates


def dataset_context(
    dataset: DatasetSnapshot | None,
    profile: dict[str, Any],
    semantic_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    if dataset is None:
        return {
            "dataset_snapshot_id": None,
            "status": "missing",
            "profile": profile,
            "semantic_columns": [],
        }
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "source_type": dataset.source_type,
        "source_ref": dataset.source_ref,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema_hash": dataset.schema_hash,
        "data_hash": dataset.data_hash,
        "profile": profile,
        "semantic_columns": semantic_columns[:80],
    }


def evaluation_contract(
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> dict[str, Any]:
    if evaluation_spec is None:
        return {
            "status": "missing",
            "evaluation_spec_id": None,
            "split_manifest_id": None,
            "policy": "planning_only_until_evaluation_spec_is_approved",
        }
    return {
        "status": evaluation_spec.status,
        "evaluation_spec_id": evaluation_spec.id,
        "dataset_snapshot_id": evaluation_spec.dataset_snapshot_id,
        "split_type": evaluation_spec.split_type,
        "primary_metric": evaluation_spec.primary_metric,
        "secondary_metrics": loads_json(evaluation_spec.secondary_metrics_json, []),
        "time_column": evaluation_spec.time_column,
        "group_column": evaluation_spec.group_column,
        "stratify_column": evaluation_spec.stratify_column,
        "excluded_columns": loads_json(evaluation_spec.excluded_columns_json, []),
        "risk_level": evaluation_spec.risk_level,
        "split_manifest": split_manifest_payload(split_manifest),
        "policy": "must_respect_approved_evaluation_spec_and_split_manifest",
    }


def split_manifest_payload(split_manifest: SplitManifest | None) -> dict[str, Any] | None:
    if split_manifest is None:
        return None
    return {
        "split_manifest_id": split_manifest.id,
        "artifact_id": split_manifest.artifact_id,
        "train_count": split_manifest.train_count,
        "valid_count": split_manifest.valid_count,
        "test_count": split_manifest.test_count,
        "summary": loads_json(split_manifest.summary_json, {}),
    }


def assumption_context(assumptions: list[Assumption], questions: list[Question]) -> dict[str, Any]:
    high_risk = [
        item
        for item in assumptions
        if item.risk_level in {"high", "blocking", "deployment_blocking"}
        or item.status in {"challenged", "needs_review"}
    ]
    blocking_questions = [item for item in questions if item.fallback_policy == "block_until_answered"]
    return {
        "unresolved_assumptions": [assumption_item(item) for item in assumptions[:16]],
        "high_risk_assumptions": [assumption_item(item) for item in high_risk[:12]],
        "open_questions": [question_item(item) for item in questions[:12]],
        "blocking_question_count": len(blocking_questions),
        "policy": "continue_with_recorded_assumptions_unless_deployment_or_blocking_policy_requires_answer",
    }


def assumption_item(assumption: Assumption) -> dict[str, Any]:
    return {
        "id": assumption.id,
        "topic": assumption.topic,
        "statement": assumption.statement,
        "status": assumption.status,
        "confidence": assumption.confidence,
        "risk_level": assumption.risk_level,
        "fallback_policy": assumption.fallback_policy,
    }


def question_item(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "topic": question.topic,
        "question": question.question,
        "risk_level": question.risk_level,
        "fallback_policy": question.fallback_policy,
        "can_proceed_without_answer": question.can_proceed_without_answer,
        "blocks_next_phase": question.blocks_next_phase,
    }


def benchmark_context(context_artifacts: dict[str, Artifact | None]) -> dict[str, Any]:
    scenario_pack = context_artifacts.get("benchmark_scenario_pack")
    import_manifest = context_artifacts.get("benchmark_import_manifest")
    relational_catalog = context_artifacts.get("relational_catalog")
    metadata = artifact_metadata(scenario_pack) or artifact_metadata(import_manifest)
    relational_metadata = artifact_metadata(relational_catalog)
    benchmark_id = metadata.get("benchmark_id") or relational_metadata.get("benchmark_id")
    return {
        "status": "available" if benchmark_id or metadata or relational_metadata else "missing",
        "benchmark_id": benchmark_id,
        "scenario_pack_artifact_id": scenario_pack.id if scenario_pack else None,
        "import_manifest_artifact_id": import_manifest.id if import_manifest else None,
        "relational_catalog_artifact_id": relational_catalog.id if relational_catalog else None,
        "table_count": relational_metadata.get("table_count"),
        "relationship_count": relational_metadata.get("relationship_count"),
        "policy": "benchmark context may inform candidates but does not override Tablex evaluation contracts",
    }


def available_context_artifacts(context_artifacts: dict[str, Artifact | None]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for role, artifact in context_artifacts.items():
        if artifact is None:
            continue
        refs.append(
            {
                "role": role,
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "name": artifact.name,
                "version": artifact.version,
                "metadata": artifact_metadata(artifact),
                "preview_url": f"/api/artifacts/{artifact.id}/preview",
                "download_url": f"/api/artifacts/{artifact.id}/download",
            }
        )
    return refs


def safety_constraints(project: Project) -> dict[str, Any]:
    return {
        "product_context": {
            "working_name": "Tablex",
            "product_name_status": "not_final",
        },
        "target_column": project.target_column,
        "secret_access": "forbidden",
        "connector_credentials": "never_materialized",
        "network": "disabled_by_default_requires_runner_policy",
        "production_write": "forbidden",
        "evaluation_spec_mutation": "forbidden_without_harness_approval",
        "split_manifest": "must_be_respected",
        "feature_generation_prompt_policy": "validation_and_test_targets_must_not_be_included",
    }


def reporting_requirements() -> dict[str, Any]:
    return {
        "self_contained_ui": True,
        "required_sections": [
            "objective",
            "data_and_evaluation_context",
            "approach_selection_reasoning",
            "implementation_summary",
            "metrics_and_diagnostics",
            "assumptions_and_risks",
            "artifact_inventory",
            "next_actions",
        ],
        "visualization_expectations": [
            "leaderboard_or_metric_card",
            "error_or_slice_summary_when_predictions_exist",
            "artifact_readiness_or_decision_status",
        ],
        "citation_policy": "external claims require source summaries with URL/DOI and retrieval date",
    }


def artifact_expectations() -> list[dict[str, Any]]:
    return [
        {"asset_type": "feature_recipe", "required": True, "purpose": "explain train-fold-safe features"},
        {"asset_type": "experiment_metrics", "required": True, "purpose": "record harness metrics"},
        {"asset_type": "run_report", "required": True, "purpose": "summarize result inside Tablex"},
        {"asset_type": "visualization_spec", "required": True, "purpose": "drive UI/report visualization"},
        {"asset_type": "evidence", "required": True, "purpose": "support claims and assumptions"},
        {"asset_type": "model_package", "required": False, "purpose": "persist runnable model when implemented"},
        {"asset_type": "prediction_output", "required": False, "purpose": "support diagnostics"},
    ]


def planning_context_artifacts(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "eda_profile": latest_project_artifact(db, project_id, "eda_profile"),
        "understanding_report": latest_project_artifact(db, project_id, "understanding_report"),
        "data_quality_gate": latest_project_artifact(db, project_id, "data_quality_gate"),
        "relational_catalog": latest_project_artifact(db, project_id, "relational_catalog"),
        "relational_feature_plan": latest_project_artifact(db, project_id, "relational_feature_plan"),
        "relational_feature_recipe": latest_project_artifact(db, project_id, "relational_feature_recipe"),
        "relational_feature_scenario_diagnostics": latest_project_artifact(
            db, project_id, "relational_feature_scenario_diagnostics"
        ),
        "benchmark_import_manifest": latest_project_artifact(db, project_id, "benchmark_import_manifest"),
        "benchmark_scenario_pack": latest_project_artifact(db, project_id, "benchmark_scenario_pack"),
        "evaluation_scenario_comparison": latest_project_artifact(
            db, project_id, "evaluation_scenario_comparison"
        ),
        "evaluation_approval_review": latest_project_artifact(db, project_id, "evaluation_approval_review"),
        "baseline_strategy_plan": latest_project_artifact(db, project_id, "baseline_strategy_plan"),
        "research_plan": latest_project_artifact(db, project_id, "research_plan"),
        "research_source_pack": latest_project_artifact(db, project_id, "research_source_pack"),
        "research_finding_synthesis": latest_project_artifact(db, project_id, "research_finding_synthesis"),
        "evaluation_diagnostics": latest_project_artifact(db, project_id, "evaluation_diagnostics"),
        "decision_dashboard": latest_project_artifact(db, project_id, "decision_dashboard"),
    }


def research_source_pack_contract_inputs(source_pack_artifact: Artifact | None) -> dict[str, Any]:
    if source_pack_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(source_pack_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    citation_requirements = (
        payload.get("citation_requirements") if isinstance(payload.get("citation_requirements"), dict) else {}
    )
    return {
        "artifact_id": source_pack_artifact.id,
        "source_policy": source_policy,
        "citation_requirements": citation_requirements,
        "freshness_expectations": payload.get("freshness_expectations")
        if isinstance(payload.get("freshness_expectations"), dict)
        else {},
        "controlled_query_count": len(payload.get("controlled_queries", []))
        if isinstance(payload.get("controlled_queries"), list)
        else 0,
    }


def research_synthesis_contract_inputs(synthesis_artifact: Artifact | None) -> dict[str, Any]:
    if synthesis_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(synthesis_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    return {
        "artifact_id": synthesis_artifact.id,
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "citation_audit": payload.get("citation_audit") if isinstance(payload.get("citation_audit"), dict) else {},
        "follow_up_requirements": payload.get("follow_up_requirements")
        if isinstance(payload.get("follow_up_requirements"), list)
        else [],
        "agent_task_handoff": payload.get("agent_task_handoff")
        if isinstance(payload.get("agent_task_handoff"), dict)
        else {},
    }


def relational_feature_plan_contract_inputs(plan_artifact: Artifact | None) -> dict[str, Any]:
    if plan_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(plan_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    return {
        "artifact_id": plan_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "table_coverage": payload.get("table_coverage") if isinstance(payload.get("table_coverage"), dict) else {},
        "aggregation_candidate_count": len(payload.get("aggregation_candidates", []))
        if isinstance(payload.get("aggregation_candidates"), list)
        else 0,
        "risk_register": payload.get("risk_register") if isinstance(payload.get("risk_register"), list) else [],
        "agent_task_handoff": payload.get("agent_task_handoff")
        if isinstance(payload.get("agent_task_handoff"), dict)
        else {},
    }


def relational_feature_recipe_contract_inputs(recipe_artifact: Artifact | None) -> dict[str, Any]:
    if recipe_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(recipe_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    raw_execution_summary = payload.get("execution_summary")
    raw_safety = payload.get("safety")
    raw_steps = payload.get("steps")
    raw_deferred_steps = payload.get("deferred_steps")
    raw_execution_scope = payload.get("execution_scope")
    execution_summary: dict[str, Any] = raw_execution_summary if isinstance(raw_execution_summary, dict) else {}
    safety: dict[str, Any] = raw_safety if isinstance(raw_safety, dict) else {}
    steps: list[Any] = raw_steps if isinstance(raw_steps, list) else []
    deferred_steps: list[Any] = raw_deferred_steps if isinstance(raw_deferred_steps, list) else []
    execution_scope: dict[str, Any] = raw_execution_scope if isinstance(raw_execution_scope, dict) else {}
    return {
        "artifact_id": recipe_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "execution_summary": execution_summary,
        "safety": safety,
        "generated_feature_count": int(execution_summary.get("generated_feature_count") or 0),
        "executed_step_count": len(steps),
        "deferred_step_count": len(deferred_steps),
        "preview_only": execution_scope.get("mode") == "preview_only" if execution_scope else True,
    }


def relational_feature_scenario_diagnostics_contract_inputs(diagnostics_artifact: Artifact | None) -> dict[str, Any]:
    if diagnostics_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(diagnostics_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    raw_preview_summary = payload.get("preview_summary")
    raw_split_compatibility = payload.get("split_compatibility")
    raw_safety = payload.get("safety")
    raw_scenarios = payload.get("scenario_comparison")
    preview_summary: dict[str, Any] = raw_preview_summary if isinstance(raw_preview_summary, dict) else {}
    split_compatibility: dict[str, Any] = (
        raw_split_compatibility if isinstance(raw_split_compatibility, dict) else {}
    )
    safety: dict[str, Any] = raw_safety if isinstance(raw_safety, dict) else {}
    scenarios: list[Any] = raw_scenarios if isinstance(raw_scenarios, list) else []
    return {
        "artifact_id": diagnostics_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "preview_summary": preview_summary,
        "split_compatibility": split_compatibility,
        "scenario_count": len(scenarios),
        "scenario_comparison": scenarios[:4],
        "safety": safety,
    }


def create_planner_lineage(
    db: Session,
    *,
    project: Project,
    artifact: Artifact,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    context_artifacts: dict[str, Artifact | None],
    asset_recommendations: list[dict[str, Any]],
    job: Job | None,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="plans_agent_task",
    )
    if job:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="informs_agent_task",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="constrains_agent_task",
        )
    if split_manifest:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="split_manifest",
            from_asset_id=split_manifest.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="constrains_agent_task",
        )
    for context_artifact in context_artifacts.values():
        if context_artifact:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=context_artifact.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="informs_agent_task",
            )
    seen_asset_ids: set[str] = set()
    for recommendation in asset_recommendations:
        asset_id = recommendation.get("asset_id")
        if not isinstance(asset_id, str) or asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="asset",
            from_asset_id=asset_id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="recommended_for_agent_task",
        )


def validate_agent_task_contract(payload: dict[str, Any]) -> None:
    Draft202012Validator(load_agent_task_contract_schema()).validate(payload)
    AgentTaskContract.model_validate(payload)


def load_agent_task_contract_schema() -> dict[str, Any]:
    candidates = [
        Path("schemas/agent_task_contract.schema.json"),
        Path(__file__).resolve().parents[4] / "schemas" / "agent_task_contract.schema.json",
    ]
    for path in candidates:
        if path.exists():
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    raise ValueError("schemas/agent_task_contract.schema.json not found")


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest)
        .where(SplitManifest.evaluation_spec_id == spec_id)
        .order_by(SplitManifest.created_at.desc())
    )


def latest_semantic_columns(db: Session, dataset: DatasetSnapshot | None) -> list[dict[str, Any]]:
    if dataset is None:
        return []
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        return []
    columns = loads_json(catalog.columns_json, [])
    return [cast(dict[str, Any], column) for column in columns if isinstance(column, dict)]


def latest_assumptions(db: Session, project_id: str) -> list[Assumption]:
    return list(
        db.scalars(
            select(Assumption)
            .where(Assumption.project_id == project_id)
            .order_by(Assumption.updated_at.desc())
            .limit(24)
        ).all()
    )


def latest_open_questions(db: Session, project_id: str) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .where(Question.project_id == project_id, Question.status == "open")
            .order_by(Question.priority.desc(), Question.created_at.desc())
            .limit(24)
        ).all()
    )


def latest_active_assets(db: Session) -> list[Asset]:
    return list(
        db.scalars(select(Asset).where(Asset.status == "active").order_by(Asset.created_at.desc())).all()
    )
