from __future__ import annotations

from typing import Any, cast

RELATIONAL_CONTEXT_SOURCE_KIND = "relational_context_artifact"


def build_relational_runner_context_summary(
    workspace_manifest: dict[str, Any] | None,
    contract_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = contract_inputs or {}
    recipe = dict_value(inputs.get("relational_feature_recipe"))
    diagnostics = dict_value(inputs.get("relational_feature_scenario_diagnostics"))
    sources = relational_context_sources(workspace_manifest)
    roles = sorted({str(source.get("role") or source.get("asset_type") or "relational_context") for source in sources})
    scenario_comparison = summarize_scenarios(list_value(diagnostics.get("scenario_comparison")))
    recommendations = summarize_recommended_scenarios(
        list_value(diagnostics.get("recommended_agent_task_scenarios")),
        scenario_comparison,
    )
    deferred_checks = deferred_safety_checks(recipe, diagnostics)
    preview_summary = dict_value(diagnostics.get("preview_summary"))
    split_compatibility = dict_value(diagnostics.get("split_compatibility"))
    return {
        "schema_version": "relational_runner_context_summary.v1",
        "status": "available" if sources else "missing",
        "source_count": len(sources),
        "roles": roles,
        "sources": sources,
        "coverage": {
            "has_plan": "relational_feature_plan" in roles,
            "has_recipe": "relational_feature_recipe" in roles,
            "has_preview_csv": "relational_feature_preview" in roles,
            "has_preview_profile": "relational_feature_preview_profile" in roles,
            "has_scenario_diagnostics": "relational_feature_scenario_diagnostics" in roles,
            "has_scenario_report": "relational_feature_scenario_report" in roles,
        },
        "preview_summary": {
            "generated_feature_count": int_value(preview_summary.get("generated_feature_count")),
            "usable_feature_count": int_value(preview_summary.get("usable_feature_count")),
            "constant_feature_count": int_value(preview_summary.get("constant_feature_count")),
            "high_missing_feature_count": int_value(preview_summary.get("high_missing_feature_count")),
        },
        "scenario_comparison": scenario_comparison,
        "recommended_agent_task_scenarios": recommendations,
        "deferred_safety_checks": deferred_checks,
        "split_compatibility": {
            "status": split_compatibility.get("status"),
            "evaluation_spec_id": split_compatibility.get("evaluation_spec_id"),
            "split_manifest_id": split_compatibility.get("split_manifest_id"),
            "policy": split_compatibility.get("policy"),
        },
        "safety": {
            **dict_value(recipe.get("safety")),
            **dict_value(diagnostics.get("safety")),
            "secrets_materialized": False,
            "connector_credentials_materialized": False,
            "model_training_performed_by_context_handoff": False,
        },
        "approach_flexibility": {
            "policy": "advisory_context_not_prescriptive_recipe",
            "runner_may_propose_alternative_approaches": True,
            "runner_may_request_more_research": True,
            "runner_should_explain_rejected_context": True,
            "hard_constraints": [
                "do_not_read_or_materialize_secrets",
                "do_not_use_connector_credentials",
                "respect_evaluation_spec_and_split_manifest",
                "fit_preprocessing_inside_training_folds",
                "register_important_outputs_as_artifacts",
            ],
        },
        "runner_guidance": runner_guidance(sources, deferred_checks, split_compatibility),
    }


def relational_context_sources(workspace_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    if workspace_manifest is None:
        return []
    sources: list[dict[str, Any]] = []
    for item in list_value(workspace_manifest.get("materialized_sources")):
        if not isinstance(item, dict) or item.get("source_kind") != RELATIONAL_CONTEXT_SOURCE_KIND:
            continue
        sources.append(
            {
                "role": item.get("role"),
                "asset_type": item.get("asset_type"),
                "artifact_id": item.get("artifact_id"),
                "name": item.get("name"),
                "context_path": item.get("context_path"),
                "content_hash": item.get("content_hash"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    return sources


def summarize_scenarios(raw_scenarios: list[Any]) -> list[dict[str, Any]]:
    scenarios = []
    for item in raw_scenarios[:8]:
        if not isinstance(item, dict):
            continue
        scenarios.append(
            {
                "scenario": item.get("scenario"),
                "status": item.get("status"),
                "risk_level": item.get("risk_level"),
                "feature_count": item.get("feature_count"),
                "next_action": item.get("next_action"),
            }
        )
    return scenarios


def summarize_recommended_scenarios(
    raw_recommendations: list[Any],
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations = []
    for item in raw_recommendations[:8]:
        if not isinstance(item, dict):
            continue
        recommendations.append(
            {
                "name": item.get("name"),
                "priority": item.get("priority"),
                "description": item.get("description"),
                "requires": list_value(item.get("requires"))[:8],
            }
        )
    if recommendations:
        return recommendations
    return [
        {
            "name": str(item.get("scenario") or "relational_scenario"),
            "priority": index + 1,
            "description": str(item.get("next_action") or "Review this relational scenario before execution."),
            "requires": ["harness_review"],
        }
        for index, item in enumerate(scenarios)
    ]


def deferred_safety_checks(recipe: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        {
            "check": "fit_preprocessing_inside_training_folds",
            "status": "required",
            "reason": "Relational preview artifacts are not a deployment-time preprocessing fit.",
        },
        {
            "check": "confirm_prediction_time_availability",
            "status": "required",
            "reason": "Supporting-table features must be available at prediction time before model claims.",
        },
    ]
    if bool(recipe.get("preview_only")) or bool(dict_value(recipe.get("execution_scope")).get("mode") == "preview_only"):
        checks.append(
            {
                "check": "replace_preview_with_train_fold_recipe",
                "status": "required_before_model_claim",
                "reason": "Preview CSV can inform planning but must not be treated as a fitted production feature matrix.",
            }
        )
    deferred_count = int_value(recipe.get("deferred_step_count"))
    if deferred_count:
        checks.append(
            {
                "check": "resolve_deferred_relational_steps",
                "status": "required",
                "reason": f"{deferred_count} relational recipe step(s) were deferred.",
            }
        )
    split_status = dict_value(diagnostics.get("split_compatibility")).get("status")
    if split_status not in {"ready", None}:
        checks.append(
            {
                "check": "lock_evaluation_context",
                "status": "required",
                "reason": f"Relational diagnostics split compatibility is `{split_status}`.",
            }
        )
    return checks


def runner_guidance(
    sources: list[dict[str, Any]],
    deferred_checks: list[dict[str, Any]],
    split_compatibility: dict[str, Any],
) -> list[str]:
    if not sources:
        return ["No relational context was materialized; use primary-table and other project context."]
    guidance = [
        "Inspect relational plan, recipe, preview profile, diagnostics, and report before selecting a feature approach.",
        "Treat preview relational features as advisory planning evidence, not a required recipe.",
        "The runner may reject, revise, or replace relational approaches when evidence supports a better path.",
        "Keep EvaluationSpec and SplitManifest controlled by the harness.",
    ]
    if deferred_checks:
        guidance.append("Address deferred safety checks before making model-improvement claims.")
    if split_compatibility.get("status") != "ready":
        guidance.append("Do not claim relational lift until evaluation context is approved and respected.")
    return guidance


def dict_value(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def int_value(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0
