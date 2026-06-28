from __future__ import annotations

import json
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
    )
    return TestClient(create_app(settings))


def test_project_upload_profile_evaluation_split_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Demo", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    csv_bytes = (
        b"customer_id,created_at,feature,target,final_status\n"
        b"c1,2026-01-01,10,1,won\n"
        b"c1,2026-01-02,11,0,lost\n"
        b"c2,2026-01-03,13,1,won\n"
        b"c2,2026-01-04,9,0,lost\n"
        b"c3,2026-01-05,8,1,won\n"
        b"c3,2026-01-06,7,0,lost\n"
    )
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("demo.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]
    assert upload_response.json()["dataset_snapshot"]["row_count"] == 6

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "succeeded"
    assert len(quality_job["output"]["artifact_ids"]) == 3
    quality_gate = quality_job["output"]["gate"]
    assert quality_gate["schema_version"] == "data_quality_gate.v1"
    assert quality_gate["summary"]["severity"] in {"warning", "pass"}
    assert "final_status" in quality_gate["evaluation_guidance"]["excluded_columns"]
    assert quality_job["output"]["insight_id"]

    latest_quality_response = client.get(f"/api/datasets/{dataset_id}/quality/latest")
    assert latest_quality_response.status_code == 200
    quality_artifact_id = latest_quality_response.json()["id"]
    quality_preview_response = client.get(f"/api/artifacts/{quality_artifact_id}/preview")
    assert quality_preview_response.status_code == 200
    assert "data_quality_gate.v1" in quality_preview_response.json()["preview"]

    assumptions_response = client.get(f"/api/projects/{project_id}/assumptions")
    assert assumptions_response.status_code == 200
    assumptions = assumptions_response.json()
    assert any(item["fallback_policy"] == "exclude_until_confirmed" for item in assumptions)

    understanding_response = client.get(f"/api/projects/{project_id}/understanding/latest")
    assert understanding_response.status_code == 200
    assert "Data Understanding" in understanding_response.json()["markdown"]

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    first_question = questions_response.json()[0]
    answer_response = client.post(
        f"/api/questions/{first_question['id']}/answer",
        json={"answer_value": first_question["choices"][0], "answer_text": "integration test"},
    )
    assert answer_response.status_code == 200
    assert answer_response.json()["question_id"] == first_question["id"]

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200
    assert design_response.json()["status"] == "succeeded"

    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    primary = next(item for item in candidates if item["status"] == "primary_candidate")
    assert primary["split_type"] == "stratified"
    assert primary["stratify_column"] == "target"

    scenario_compare_response = client.post(f"/api/projects/{project_id}/evaluation/compare")
    assert scenario_compare_response.status_code == 200, scenario_compare_response.text
    scenario_compare_job = scenario_compare_response.json()
    assert scenario_compare_job["status"] == "succeeded"
    assert scenario_compare_job["output"]["artifact_id"]
    assert scenario_compare_job["output"]["candidate_count"] >= 2
    scenario_compare_preview_response = client.get(
        f"/api/artifacts/{scenario_compare_job['output']['artifact_id']}/preview"
    )
    assert scenario_compare_preview_response.status_code == 200
    scenario_compare_preview = scenario_compare_preview_response.json()["preview"]
    assert "evaluation_scenario_comparison.v1" in scenario_compare_preview
    assert "decision_support" in scenario_compare_preview

    promote_response = client.post(f"/api/evaluation-candidates/{primary['id']}/promote")
    assert promote_response.status_code == 200
    spec_id = promote_response.json()["id"]

    approval_review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert approval_review_response.status_code == 200, approval_review_response.text
    approval_review_job = approval_review_response.json()
    assert approval_review_job["status"] == "succeeded"
    assert approval_review_job["output"]["artifact_id"]
    assert approval_review_job["output"]["review_status"] in {"ready", "ready_with_assumptions"}
    approval_review_preview_response = client.get(
        f"/api/artifacts/{approval_review_job['output']['artifact_id']}/preview"
    )
    assert approval_review_preview_response.status_code == 200
    approval_review_preview = approval_review_preview_response.json()["preview"]
    assert "evaluation_approval_review.v1" in approval_review_preview
    assert "assumption_backed_proceed" in approval_review_preview

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    split = split_response.json()
    assert split["train_count"] > 0
    assert split["valid_count"] > 0
    assert split["project_id"] == project_id

    strategy_plan_response = client.post(f"/api/projects/{project_id}/baseline/strategy-plan")
    assert strategy_plan_response.status_code == 200, strategy_plan_response.text
    strategy_plan_job = strategy_plan_response.json()
    assert strategy_plan_job["status"] == "succeeded"
    assert strategy_plan_job["output"]["baseline_strategy_plan_artifact_id"]
    strategy_preview_response = client.get(
        f"/api/artifacts/{strategy_plan_job['output']['baseline_strategy_plan_artifact_id']}/preview"
    )
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "baseline_strategy_plan.v1" in strategy_preview
    assert "adaptive_baseline_planning" in strategy_preview
    assert "reporting_plan" in strategy_preview

    baseline_response = client.post(f"/api/projects/{project_id}/baseline/run")
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_job = baseline_response.json()
    assert baseline_job["status"] == "succeeded"
    assert baseline_job["output"]["experiment_run_id"]
    assert baseline_job["output"]["model_version_id"]
    baseline_metrics = baseline_job["output"]["metrics"]
    assert baseline_metrics["model_baseline_attempted"] is True
    assert baseline_metrics["baseline_type"] in {"xgboost_classifier", "logistic_regression", "majority_classifier"}
    assert baseline_metrics["primary_metric_value"] >= 0
    assert len(baseline_job["output"]["artifact_ids"]) >= 7

    model_response = client.get(f"/api/model-versions/{baseline_job['output']['model_version_id']}")
    assert model_response.status_code == 200, model_response.text
    model_version = model_response.json()
    assert model_version["model_family"] == "xgboost"
    assert model_version["model_type"] == "xgboost_classifier"
    assert model_version["artifact_id"]

    model_versions_response = client.get(f"/api/projects/{project_id}/model-versions")
    assert model_versions_response.status_code == 200
    assert model_versions_response.json()[0]["id"] == model_version["id"]

    validate_response = client.post(f"/api/model-versions/{model_version['id']}/validate")
    assert validate_response.status_code == 200, validate_response.text
    validate_job = validate_response.json()
    assert validate_job["status"] == "succeeded"
    assert validate_job["output"]["model_version_id"] == model_version["id"]
    assert validate_job["output"]["metrics"]["max_abs_metric_delta"] <= 1e-9
    assert len(validate_job["output"]["artifact_ids"]) == 3

    validation_history_response = client.get(f"/api/model-versions/{model_version['id']}/validations")
    assert validation_history_response.status_code == 200
    validation_history = validation_history_response.json()
    assert validation_history[0]["job"]["id"] == validate_job["id"]
    assert validation_history[0]["validation_status"] == "passed"
    assert validation_history[0]["max_abs_metric_delta"] <= 1e-9
    assert len(validation_history[0]["artifacts"]) == 3

    jobs_response = client.get(f"/api/projects/{project_id}/jobs")
    assert jobs_response.status_code == 200
    job_types = [item["job_type"] for item in jobs_response.json()]
    assert "validate_model_package" in job_types
    assert "run_baseline" in job_types
    assert "compare_evaluation_scenarios" in job_types
    assert "review_evaluation_approval" in job_types

    approval_job_response = client.post(
        "/api/jobs",
        json={
            "job_type": "run_agent_task",
            "project_id": project_id,
            "input": {"purpose": "approval gate integration test"},
            "policy": {"network": "restricted"},
            "max_attempts": 2,
        },
    )
    assert approval_job_response.status_code == 200, approval_job_response.text
    approval_job = approval_job_response.json()
    assert approval_job["status"] == "approval_required"
    assert approval_job["approval_required"] is True

    approve_job_response = client.post(f"/api/jobs/{approval_job['id']}/approve")
    assert approve_job_response.status_code == 200
    assert approve_job_response.json()["status"] == "queued"
    assert approve_job_response.json()["approved_by"] == "local-user"

    worker_response = client.post("/api/worker/run-once")
    assert worker_response.status_code == 200, worker_response.text
    assert worker_response.json()["id"] == approval_job["id"]
    assert worker_response.json()["status"] == "succeeded"
    assert worker_response.json()["attempt_count"] == 1

    dependency_a_response = client.post(
        "/api/jobs",
        json={"job_type": "infer_assumptions", "project_id": project_id, "input": {"name": "dependency-a"}},
    )
    assert dependency_a_response.status_code == 200
    dependency_a = dependency_a_response.json()
    dependency_b_response = client.post(
        "/api/jobs",
        json={
            "job_type": "draft_project_report",
            "project_id": project_id,
            "input": {"name": "dependency-b"},
            "dependency_job_ids": [dependency_a["id"]],
            "priority": 100,
        },
    )
    assert dependency_b_response.status_code == 200
    dependency_b = dependency_b_response.json()
    first_dependency_worker_response = client.post("/api/worker/run-once")
    assert first_dependency_worker_response.status_code == 200
    assert first_dependency_worker_response.json()["id"] == dependency_a["id"]
    second_dependency_worker_response = client.post("/api/worker/run-once")
    assert second_dependency_worker_response.status_code == 200
    assert second_dependency_worker_response.json()["id"] == dependency_b["id"]

    cancel_retry_response = client.post(
        "/api/jobs",
        json={
            "job_type": "infer_assumptions",
            "project_id": project_id,
            "input": {"purpose": "cancel-retry integration test"},
            "max_attempts": 2,
        },
    )
    assert cancel_retry_response.status_code == 200
    cancel_retry_job = cancel_retry_response.json()
    cancel_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    retry_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "queued"

    seed_assets_response = client.post("/api/assets/seed-defaults")
    assert seed_assets_response.status_code == 200
    seeded_assets = seed_assets_response.json()
    assert len(seeded_assets) >= 15
    seeded_asset_names = {item["name"] for item in seeded_assets}
    assert {
        "tabular_gradient_boosting_strategy",
        "xgboost_mixed_type_baseline",
        "text_tfidf_train_fold_recipe",
        "causal_time_lag_rolling_features",
        "relational_aggregation_recipe",
        "decision_report_prompt",
    }.issubset(seeded_asset_names)
    skill_asset = next(item for item in seeded_assets if item["asset_type"] == "skill")

    research_plan_response = client.post(f"/api/projects/{project_id}/approach/research-plan")
    assert research_plan_response.status_code == 200, research_plan_response.text
    research_plan_job = research_plan_response.json()
    assert research_plan_job["status"] == "succeeded"
    research_plan_artifact_id = research_plan_job["output"]["artifact_id"]
    assert research_plan_job["output"]["schema_version"] == "research_plan.v1"
    assert research_plan_job["output"]["query_count"] >= 2
    assert research_plan_job["output"]["recommended_asset_count"] >= 4
    assert research_plan_job["output"]["network_default"] == "disabled_until_runner_policy_allows"

    research_plan_preview_response = client.get(f"/api/artifacts/{research_plan_artifact_id}/preview")
    assert research_plan_preview_response.status_code == 200
    research_plan_preview = research_plan_preview_response.json()["preview"]
    assert "research_plan.v1" in research_plan_preview
    assert "controlled_web_search" in research_plan_preview
    assert "connector_credentials" in research_plan_preview
    assert "xgboost_mixed_type_baseline" in research_plan_preview
    assert "causal_time_lag_rolling_features" in research_plan_preview

    research_response = client.post(
        f"/api/projects/{project_id}/approach/research-briefs",
        json={"question": "What flexible approaches should be considered?"},
    )
    assert research_response.status_code == 200, research_response.text
    research_job = research_response.json()
    assert research_job["status"] == "succeeded"
    assert research_job["output"]["research_brief_id"]

    briefs_response = client.get(f"/api/projects/{project_id}/approach/research-briefs")
    assert briefs_response.status_code == 200
    brief = briefs_response.json()[0]
    assert "controlled web" in brief["summary_md"].lower() or "web" in brief["summary_md"].lower()
    assert len(brief["recommended_approaches"]) >= 2
    assert any(source["source_type"] == "research_plan" for source in brief["sources"])

    ideas_response = client.post(f"/api/projects/{project_id}/approach/ideas/generate")
    assert ideas_response.status_code == 200, ideas_response.text
    ideas_job = ideas_response.json()
    assert ideas_job["status"] == "succeeded"
    assert len(ideas_job["output"]["idea_ids"]) >= 2

    ideas_list_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert ideas_list_response.status_code == 200
    idea = ideas_list_response.json()[0]
    assert idea["status"] == "proposed"
    contract_inputs = idea["agent_task_contract"]["inputs"]
    assert contract_inputs["must_respect_split_manifest"] is True
    assert contract_inputs["research_plan_artifact_id"] == research_plan_artifact_id
    assert len(contract_inputs["recommended_asset_ids"]) >= 4
    assert len(contract_inputs["recommended_asset_version_ids"]) >= 4
    assert contract_inputs["research_source_policy"]["network_default"] == "disabled_until_runner_policy_allows"
    assert any("secrets" in item for item in idea["agent_task_contract"]["forbidden_actions"])

    assets_response = client.get("/api/assets")
    assert assets_response.status_code == 200
    assert any(item["name"] == skill_asset["name"] for item in assets_response.json())

    versions_response = client.get(f"/api/assets/{skill_asset['id']}/versions")
    assert versions_response.status_code == 200
    skill_version = versions_response.json()[0]
    assert skill_version["asset_id"] == skill_asset["id"]

    project_ref_response = client.post(
        f"/api/projects/{project_id}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_research",
        },
    )
    assert project_ref_response.status_code == 200, project_ref_response.text
    assert project_ref_response.json()["asset"]["asset_type"] == "skill"

    idea_ref_response = client.post(
        f"/api/ideas/{idea['id']}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_agent_task",
        },
    )
    assert idea_ref_response.status_code == 200, idea_ref_response.text
    assert idea_ref_response.json()["source_type"] == "idea"

    project_refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert project_refs_response.status_code == 200
    assert project_refs_response.json()[0]["asset"]["name"] == skill_asset["name"]

    skill_preview_response = client.get(f"/api/artifacts/{skill_version['artifact_id']}/preview")
    assert skill_preview_response.status_code == 200
    assert skill_preview_response.json()["preview_available"] is True

    context_response = client.post(f"/api/ideas/{idea['id']}/prepare-agent-context")
    assert context_response.status_code == 200, context_response.text
    context_job = context_response.json()
    assert context_job["status"] == "succeeded"
    assert context_job["output"]["schema_version"] == "agent_context_pack.v1"
    assert context_job["output"]["artifact_id"]
    assert context_job["output"]["asset_recommendation_count"] >= 4
    assert context_job["output"]["materialized_library_asset_count"] >= 4

    context_packs_response = client.get(f"/api/ideas/{idea['id']}/context-packs")
    assert context_packs_response.status_code == 200
    context_artifact = context_packs_response.json()[0]
    assert context_artifact["id"] == context_job["output"]["artifact_id"]

    context_preview_response = client.get(f"/api/artifacts/{context_artifact['id']}/preview")
    assert context_preview_response.status_code == 200
    context_download_response = client.get(f"/api/artifacts/{context_artifact['id']}/download")
    assert context_download_response.status_code == 200
    context_payload = context_download_response.json()
    assert context_payload["schema_version"] == "agent_context_pack.v1"
    assert "controlled_web_search" in context_payload["research_policy"]["allowed_modes"]
    assert context_payload["safety_controls"]["connector_credentials"] == "never passed to the agent"
    assert context_payload["evaluation_context"]["split_manifest_id"]
    assert context_payload["quality_gate_context"]["status"] == "available"
    assert context_payload["research_plan_context"]["artifact_id"] == research_plan_artifact_id
    assert len(context_payload["asset_recommendations"]) >= 4
    assert len(context_payload["materialized_library_assets"]) >= 4
    assert any(
        item["context_path"].startswith(".harness/context/library_assets/")
        for item in context_payload["materialized_library_assets"]
    )
    assert any(item["name"] == "xgboost_mixed_type_baseline" for item in context_payload["asset_recommendations"])

    experiment_plan_response = client.post(f"/api/ideas/{idea['id']}/experiment-plan")
    assert experiment_plan_response.status_code == 200, experiment_plan_response.text
    experiment_plan_job = experiment_plan_response.json()
    assert experiment_plan_job["status"] == "succeeded"
    assert experiment_plan_job["output"]["plan_id"]
    assert experiment_plan_job["output"]["artifact_id"]
    assert experiment_plan_job["output"]["readiness"]["status"] == "ready_for_runner"

    experiment_plans_response = client.get(f"/api/ideas/{idea['id']}/experiment-plans")
    assert experiment_plans_response.status_code == 200
    experiment_plan_artifact = experiment_plans_response.json()[0]
    assert experiment_plan_artifact["id"] == experiment_plan_job["output"]["artifact_id"]

    experiment_plan_preview_response = client.get(f"/api/artifacts/{experiment_plan_artifact['id']}/preview")
    assert experiment_plan_preview_response.status_code == 200
    assert "experiment_plan.v1" in experiment_plan_preview_response.json()["preview"]
    assert "source_policy" in experiment_plan_preview_response.json()["preview"]

    agent_task_response = client.post(f"/api/ideas/{idea['id']}/run-agent-task")
    assert agent_task_response.status_code == 200, agent_task_response.text
    agent_task_job = agent_task_response.json()
    assert agent_task_job["status"] == "succeeded"
    assert agent_task_job["output"]["idea_id"] == idea["id"]
    assert agent_task_job["output"]["agent_status"] == "succeeded"
    assert agent_task_job["output"]["requires_human_review"] is True
    assert len(agent_task_job["output"]["artifact_ids"]) >= 4
    assert agent_task_job["output"]["workspace_artifact_id"]
    assert len(agent_task_job["output"]["ingested_artifact_ids"]) == 3
    assert agent_task_job["output"]["report_id"]
    assert agent_task_job["output"]["evidence_id"]

    updated_ideas_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert updated_ideas_response.status_code == 200
    assert updated_ideas_response.json()[0]["status"] == "agent_stub_completed"

    visualization_response = client.post(f"/api/projects/{project_id}/visualizations/generate")
    assert visualization_response.status_code == 200, visualization_response.text
    visualization_job = visualization_response.json()
    assert visualization_job["status"] == "succeeded"
    assert len(visualization_job["output"]["visualization_ids"]) >= 4

    visualizations_response = client.get(f"/api/projects/{project_id}/visualizations")
    assert visualizations_response.status_code == 200
    visualizations = visualizations_response.json()
    chart_types = {item["chart_type"] for item in visualizations}
    assert {"metric_cards", "category_bars", "stage_status", "leaderboard_bar"}.issubset(chart_types)
    leaderboard_visualization = next(item for item in visualizations if item["chart_type"] == "leaderboard_bar")
    assert leaderboard_visualization["spec"]["schema_version"] == "visualization_spec.v1"

    insights_response = client.post(f"/api/projects/{project_id}/insights/generate")
    assert insights_response.status_code == 200, insights_response.text
    insights_job = insights_response.json()
    assert insights_job["status"] == "succeeded"
    assert len(insights_job["output"]["insight_ids"]) >= 5
    assert len(insights_job["output"]["evidence_ids"]) >= 5

    insights_list_response = client.get(f"/api/projects/{project_id}/insights")
    assert insights_list_response.status_code == 200
    insight = insights_list_response.json()[0]
    assert insight["artifact_id"] == insights_job["output"]["artifact_id"]
    assert insight["evidence_ids"]

    insight_preview_response = client.get(f"/api/artifacts/{insight['artifact_id']}/preview")
    assert insight_preview_response.status_code == 200
    assert "insight_set.v1" in insight_preview_response.json()["preview"]

    report_response = client.post(
        f"/api/projects/{project_id}/reports/draft",
        json={"title": "Integration report", "report_type": "project_summary"},
    )
    assert report_response.status_code == 200, report_response.text
    report_job = report_response.json()
    assert report_job["status"] == "succeeded"

    reports_response = client.get(f"/api/projects/{project_id}/reports")
    assert reports_response.status_code == 200
    report = reports_response.json()[0]
    assert report["artifact_id"] == report_job["output"]["artifact_id"]

    report_preview_response = client.get(f"/api/artifacts/{report['artifact_id']}/preview")
    assert report_preview_response.status_code == 200
    assert "Project Report" in report_preview_response.json()["preview"]
    assert "## Insights" in report_preview_response.json()["preview"]

    report_preview_by_id_response = client.get(f"/api/reports/{report['id']}/preview")
    assert report_preview_by_id_response.status_code == 200
    assert "## Visualizations" in report_preview_by_id_response.json()["preview"]

    decision_response = client.post(f"/api/projects/{project_id}/decision-dashboard/generate")
    assert decision_response.status_code == 200, decision_response.text
    decision_job = decision_response.json()
    assert decision_job["status"] == "succeeded"
    assert decision_job["output"]["schema_version"] == "decision_dashboard.v1"
    assert decision_job["output"]["decision_dashboard_artifact_id"]
    assert decision_job["output"]["decision_report_artifact_id"]
    assert decision_job["output"]["report_id"]
    assert len(decision_job["output"]["visualization_ids"]) == 3

    decision_dashboard_preview_response = client.get(
        f"/api/artifacts/{decision_job['output']['decision_dashboard_artifact_id']}/preview"
    )
    assert decision_dashboard_preview_response.status_code == 200
    decision_dashboard_preview = decision_dashboard_preview_response.json()["preview"]
    assert "decision_dashboard.v1" in decision_dashboard_preview
    assert "readiness_stages" in decision_dashboard_preview

    decision_report_preview_response = client.get(f"/api/reports/{decision_job['output']['report_id']}/preview")
    assert decision_report_preview_response.status_code == 200
    decision_report_preview = decision_report_preview_response.json()["preview"]
    assert "Decision Report" in decision_report_preview
    assert "## Readiness Stages" in decision_report_preview

    runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert runs_response.status_code == 200
    assert runs_response.json()[0]["runner_type"] == "local_baseline"
    assert runs_response.json()[0]["model_version_id"] == model_version["id"]

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()[0]["primary_metric_value"] is not None

    diagnostics_response = client.post(f"/api/runs/{runs_response.json()[0]['id']}/diagnostics")
    assert diagnostics_response.status_code == 200, diagnostics_response.text
    diagnostics_job = diagnostics_response.json()
    assert diagnostics_job["status"] == "succeeded"
    assert len(diagnostics_job["output"]["artifact_ids"]) == 3
    diagnostics_payload = diagnostics_job["output"]["diagnostics"]
    assert diagnostics_payload["schema_version"] == "evaluation_diagnostics.v1"
    assert diagnostics_payload["task_kind"] == "classification"
    assert diagnostics_payload["summary"]["count"] > 0
    assert diagnostics_job["output"]["insight_id"]
    assert diagnostics_job["output"]["evidence_id"]

    run_report_response = client.post(f"/api/runs/{runs_response.json()[0]['id']}/report")
    assert run_report_response.status_code == 200, run_report_response.text
    run_report_job = run_report_response.json()
    assert run_report_job["status"] == "succeeded"
    assert run_report_job["output"]["report_id"]
    assert run_report_job["output"]["artifact_id"]

    comparison_response = client.post(f"/api/projects/{project_id}/experiments/compare")
    assert comparison_response.status_code == 200, comparison_response.text
    comparison_job = comparison_response.json()
    assert comparison_job["status"] == "succeeded"
    assert comparison_job["output"]["comparison"]["schema_version"] == "experiment_comparison.v1"
    assert comparison_job["output"]["comparison"]["decision"]["best_run_id"] == runs_response.json()[0]["id"]
    assert len(comparison_job["output"]["artifact_ids"]) >= 2
    assert comparison_job["output"]["report_id"]
    assert comparison_job["output"]["insight_id"]

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "baseline_plan",
        "baseline_strategy_plan",
        "feature_recipe",
        "model_package",
        "model_validation_report",
        "model_validation_metrics",
        "prediction_replay",
        "data_quality_gate",
        "data_quality_report",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "research_plan",
        "research_brief",
        "approach_candidate",
        "report",
        "visualization_spec",
        "insight_set",
        "evaluation_diagnostics",
        "evaluation_diagnostics_report",
        "experiment_plan",
        "experiment_comparison",
        "experiment_comparison_report",
        "run_report",
        "decision_dashboard",
        "decision_report",
        "agent_workspace_manifest",
        "agent_context_pack",
        "agent_task_report",
        "agent_result",
    }.issubset(asset_types)
    artifacts = artifacts_response.json()
    validation_report = next(item for item in artifacts if item["asset_type"] == "model_validation_report")
    model_package = next(item for item in artifacts if item["asset_type"] == "model_package")
    diagnostics_report = next(item for item in artifacts if item["asset_type"] == "evaluation_diagnostics_report")
    run_report = next(item for item in artifacts if item["asset_type"] == "run_report")
    experiment_comparison = next(item for item in artifacts if item["asset_type"] == "experiment_comparison")
    approval_review = next(item for item in artifacts if item["asset_type"] == "evaluation_approval_review")
    workspace_manifest = next(item for item in artifacts if item["asset_type"] == "agent_workspace_manifest")

    preview_response = client.get(f"/api/artifacts/{validation_report['id']}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["preview_available"] is True
    assert "Model Package Validation Report" in preview_response.json()["preview"]

    diagnostics_preview_response = client.get(f"/api/artifacts/{diagnostics_report['id']}/preview")
    assert diagnostics_preview_response.status_code == 200
    assert "Evaluation Diagnostics" in diagnostics_preview_response.json()["preview"]

    run_report_preview_response = client.get(f"/api/artifacts/{run_report['id']}/preview")
    assert run_report_preview_response.status_code == 200
    assert "Run Report" in run_report_preview_response.json()["preview"]

    comparison_preview_response = client.get(f"/api/artifacts/{experiment_comparison['id']}/preview")
    assert comparison_preview_response.status_code == 200
    assert "experiment_comparison.v1" in comparison_preview_response.json()["preview"]

    approval_review_late_preview_response = client.get(f"/api/artifacts/{approval_review['id']}/preview")
    assert approval_review_late_preview_response.status_code == 200
    assert "evaluation_approval_review.v1" in approval_review_late_preview_response.json()["preview"]

    workspace_preview_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/preview")
    assert workspace_preview_response.status_code == 200
    workspace_download_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/download")
    assert workspace_download_response.status_code == 200
    workspace_payload = workspace_download_response.json()
    assert workspace_payload["schema_version"] == "agent_workspace_manifest.v1"
    assert workspace_payload["safety"]["connector_credentials"] == "not_materialized"
    materialized_paths = [item["context_path"] for item in workspace_payload["materialized_sources"]]
    assert any("research_plan.json" in path for path in materialized_paths)
    assert any(path.startswith(".harness/context/library_assets/") for path in materialized_paths)
    assert any(item.get("asset_name") == "xgboost_mixed_type_baseline" for item in workspace_payload["materialized_sources"])

    package_preview_response = client.get(f"/api/artifacts/{model_package['id']}/preview")
    assert package_preview_response.status_code == 200
    assert package_preview_response.json()["preview_available"] is False

    download_response = client.get(f"/api/artifacts/{validation_report['id']}/download")
    assert download_response.status_code == 200
    assert b"Model Package Validation Report" in download_response.content

    lineage_response = client.get(f"/api/projects/{project_id}/lineage")
    assert lineage_response.status_code == 200
    assert any(item["to_asset_type"] == "model_version" for item in lineage_response.json())

    schema_response = client.get(f"/api/datasets/{dataset_id}/schema")
    assert schema_response.status_code == 200
    assert len(schema_response.json()["columns"]) == 5


def test_evaluation_approval_blocks_required_unanswered_question(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Missing target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("features.csv", b"feature_a,feature_b\n1,10\n2,20\n3,30\n4,40\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    assert any(item["fallback_policy"] == "block_until_answered" for item in questions_response.json())

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidate = candidates_response.json()[0]

    promote_response = client.post(f"/api/evaluation-candidates/{candidate['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]

    review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert review_response.status_code == 200, review_response.text
    review_job = review_response.json()
    assert review_job["output"]["review_status"] == "blocked"
    assert review_job["output"]["blocker_count"] >= 1

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 409
    assert "block_until_answered" in approve_response.text

    spec_response = client.get(f"/api/evaluation-specs/{spec_id}")
    assert spec_response.status_code == 200
    assert spec_response.json()["status"] == "draft"


def test_benchmark_catalog_and_local_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    benchmarks_response = client.get("/api/benchmarks")
    assert benchmarks_response.status_code == 200, benchmarks_response.text
    benchmarks = benchmarks_response.json()
    assert any(item["id"] == "kaggle_home_credit_default_risk" for item in benchmarks)
    assert any(item["id"] == "uci_wine_quality" for item in benchmarks)
    assert any(item["id"] == "openml_credit_g" for item in benchmarks)
    home_credit_benchmark = next(item for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk")
    assert home_credit_benchmark["source_card"]["access"]["requires_account"] is True
    assert home_credit_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "user_managed_outside_tablex"
    assert home_credit_benchmark["source_card"]["table_bundle"]["supporting_table_count"] >= 1
    assert home_credit_benchmark["source_card"]["source_verification"]["source_count"] >= 1
    uci_benchmark = next(item for item in benchmarks if item["id"] == "uci_bank_marketing")
    assert uci_benchmark["local_status"]["ready"] is False
    assert uci_benchmark["fixture_available"] is True
    assert uci_benchmark["source_card"]["access"]["supports_direct_download"] is True
    assert uci_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "not_required"
    assert uci_benchmark["scenario"]["kind"] == "single_table_categorical_smoke"
    openml_benchmark = next(item for item in benchmarks if item["id"] == "openml_credit_g")
    assert openml_benchmark["source_card"]["table_bundle"]["kind"] == "single_table_bundle"
    assert openml_benchmark["source_card"]["source_verification"]["access_checked"]["requires_account"] is False
    assert "Do not paste Kaggle credentials" in next(
        item["download_instructions"] for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk"
    )

    source_card_response = client.get("/api/benchmarks/uci_bank_marketing/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["schema_version"] == "benchmark_source_card.v1"
    assert source_card["access"]["kind"] == "public_direct_download"
    assert "bank+marketing.zip" in str(source_card["download"]["download_urls"])

    readiness_response = client.get("/api/benchmarks/uci_bank_marketing/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is False
    assert any("fixture" in item.lower() for item in readiness_response.json()["next_actions"])

    project_response = client.post(
        "/api/projects",
        json={"name": "Benchmark import", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    import_missing_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_missing_response.status_code == 400
    assert "Missing required benchmark files" in import_missing_response.text

    fixture_response = client.post("/api/benchmarks/uci_bank_marketing/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["schema_version"] == "benchmark_fixture.v1"
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "bank-full.csv" for item in fixture["generated_files"])

    status_response = client.get("/api/benchmarks/uci_bank_marketing/local-status")
    assert status_response.status_code == 200
    assert status_response.json()["ready"] is True

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_response.status_code == 200, import_response.text
    payload = import_response.json()
    assert payload["primary_file"] == "bank-full.csv"
    assert payload["dataset_snapshot"]["source_type"] == "benchmark_catalog"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_bank_marketing:bank-full.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_bank_marketing"
    assert payload["import_manifest_artifact"]["asset_type"] == "benchmark_import_manifest"
    assert payload["relational_catalog_artifact"]["asset_type"] == "relational_catalog"
    assert payload["supporting_table_artifacts"] == []

    project_after_import = client.get(f"/api/projects/{project_id}")
    assert project_after_import.status_code == 200
    assert project_after_import.json()["target_column"] == "y"

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    assert "benchmark_import_manifest.v1" in manifest_preview_response.json()["preview"]
    assert "not_stored_or_passed_to_agent" in manifest_preview_response.json()["preview"]

    relational_preview_response = client.get(f"/api/artifacts/{payload['relational_catalog_artifact']['id']}/preview")
    assert relational_preview_response.status_code == 200
    assert "relational_catalog.v1" in relational_preview_response.json()["preview"]

    scenario_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack")
    assert scenario_response.status_code == 200, scenario_response.text
    scenario_job = scenario_response.json()
    assert scenario_job["status"] == "succeeded"
    assert scenario_job["output"]["scenario_kind"] == "single_table_categorical_smoke"
    assert scenario_job["output"]["benchmark_scenario_pack_artifact_id"]
    scenario_preview_response = client.get(
        f"/api/artifacts/{scenario_job['output']['benchmark_scenario_report_artifact_id']}/preview"
    )
    assert scenario_preview_response.status_code == 200
    assert "Benchmark Scenario Report" in scenario_preview_response.json()["preview"]


def test_public_uci_wine_fixture_source_card_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    source_card_response = client.get("/api/benchmarks/uci_wine_quality/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["access"]["requires_account"] is False
    assert source_card["access"]["supports_direct_download"] is True
    assert "wine+quality.zip" in str(source_card["download"]["download_urls"])
    assert source_card["import_readiness"]["can_import_now"] is False

    fixture_response = client.post("/api/benchmarks/uci_wine_quality/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "winequality-red.csv" for item in fixture["generated_files"])

    readiness_response = client.get("/api/benchmarks/uci_wine_quality/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is True

    project_response = client.post(
        "/api/projects",
        json={"name": "Wine quality public smoke", "task_type": "regression"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_wine_quality/import", json={})
    assert import_response.status_code == 200, import_response.text
    payload = import_response.json()
    assert payload["primary_file"] == "winequality-red.csv"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_wine_quality:winequality-red.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert payload["relational_catalog_artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert len(payload["supporting_table_artifacts"]) == 1

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    manifest_preview = manifest_preview_response.json()["preview"]
    assert "benchmark_import_manifest.v1" in manifest_preview
    assert "public_direct_download" in manifest_preview


def test_public_benchmark_download_extracts_expected_files(tmp_path: Path, monkeypatch: Any) -> None:
    archive_dir = tmp_path / "served"
    archive_dir.mkdir()
    archive_path = archive_dir / "public.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/public.csv", "feature,target\n1,0\n2,1\n")
        archive.writestr("../evil.csv", "feature,target\n9,9\n")
        archive.writestr("ignored.txt", "ignore me\n")

    handler = partial(SimpleHTTPRequestHandler, directory=str(archive_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/public.zip"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_zip_smoke",
                            "name": "Public Zip Smoke",
                            "source_kind": "public_test_archive",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "zip",
                                        "expected_files": ["public.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "public.csv", "target_column": "target"},
                            "required_files": [
                                {"path": "public.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_archive",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "zip", "expected_files": ["public.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        readiness_response = client.get("/api/benchmarks/public_zip_smoke/import-readiness")
        assert readiness_response.status_code == 200
        assert readiness_response.json()["can_import_now"] is False

        download_response = client.post("/api/benchmarks/public_zip_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "succeeded"
        assert job["output"]["extracted_file_count"] == 1
        assert job["output"]["local_ready"] is True
        assert job["output"]["artifact_id"]

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_zip_smoke"
        assert (benchmark_root / "public.csv").read_text(encoding="utf-8").startswith("feature,target")
        assert not (benchmark_root / "evil.csv").exists()

        status_response = client.get("/api/benchmarks/public_zip_smoke/local-status")
        assert status_response.status_code == 200
        assert status_response.json()["ready"] is True

        manifest_preview_response = client.get(f"/api/artifacts/{job['output']['artifact_id']}/preview")
        assert manifest_preview_response.status_code == 200
        manifest_preview = manifest_preview_response.json()["preview"]
        assert "benchmark_public_download_manifest.v1" in manifest_preview
        assert "unsafe_path" in manifest_preview
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_download_places_direct_csv(tmp_path: Path, monkeypatch: Any) -> None:
    served_dir = tmp_path / "served_direct"
    served_dir.mkdir()
    (served_dir / "credit.csv").write_text("feature,class\n1,good\n2,bad\n", encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/credit.csv"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_csv_smoke",
                            "name": "Public CSV Smoke",
                            "source_kind": "public_test_file",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "csv",
                                        "expected_files": ["credit.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "credit.csv", "target_column": "class"},
                            "required_files": [
                                {"path": "credit.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_direct_file",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "csv", "expected_files": ["credit.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        download_response = client.post("/api/benchmarks/public_csv_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "succeeded"
        assert job["output"]["extracted_file_count"] == 1
        assert job["output"]["local_ready"] is True

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_csv_smoke"
        assert (benchmark_root / "credit.csv").read_text(encoding="utf-8").startswith("feature,class")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_home_credit_fixture_smoke_harness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit fixture smoke", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    smoke_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke",
        json={"overwrite": True},
    )
    assert smoke_response.status_code == 200, smoke_response.text
    smoke_job = smoke_response.json()
    assert smoke_job["status"] == "succeeded"
    output = smoke_job["output"]
    assert output["fixture"]["local_status"]["ready"] is True
    assert output["fixture"]["fixture_matches_expected"] is True
    assert output["dataset_snapshot_id"]
    assert output["quality_gate"]["schema_version"] == "data_quality_gate.v1"
    assert output["evaluation_scenario_comparison_artifact_id"]
    assert output["approval_review_artifact_id"]
    assert output["split_manifest_id"]
    assert output["baseline_strategy_plan_artifact_id"]
    assert output["research_plan_artifact_id"]
    assert output["benchmark_scenario_pack_artifact_id"]
    assert output["benchmark_scenario_report_artifact_id"]
    assert len(output["artifact_ids"]) >= 16

    strategy_preview_response = client.get(f"/api/artifacts/{output['baseline_strategy_plan_artifact_id']}/preview")
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "adaptive_baseline_planning" in strategy_preview
    assert "relational_aggregation_features" in strategy_preview
    assert "reporting_plan" in strategy_preview

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "benchmark_import_manifest",
        "relational_catalog",
        "data_quality_gate",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "split_manifest",
        "baseline_strategy_plan",
        "research_plan",
        "benchmark_supporting_table",
        "benchmark_scenario_pack",
        "benchmark_scenario_report",
    }.issubset(asset_types)

    scenario_report_preview_response = client.get(f"/api/artifacts/{output['benchmark_scenario_report_artifact_id']}/preview")
    assert scenario_report_preview_response.status_code == 200
    scenario_report_preview = scenario_report_preview_response.json()["preview"]
    assert "multi_table_credit_risk" in scenario_report_preview
    assert "Fixture results are product smoke checks" in scenario_report_preview


def test_benchmark_relational_catalog_infers_shared_keys(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit tiny", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    benchmark_dir = tmp_path / "data" / "benchmarks" / "kaggle_home_credit_default_risk"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "application_train.csv").write_text(
        "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL\n"
        "100001,1,120000\n"
        "100002,0,90000\n"
        "100003,0,110000\n",
        encoding="utf-8",
    )
    (benchmark_dir / "bureau.csv").write_text(
        "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE\n"
        "100001,200001,Active\n"
        "100001,200002,Closed\n"
        "100002,200003,Closed\n",
        encoding="utf-8",
    )

    import_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/import",
        json={},
    )
    assert import_response.status_code == 200, import_response.text
    assert len(import_response.json()["supporting_table_artifacts"]) == 1
    assert import_response.json()["supporting_table_artifacts"][0]["asset_type"] == "benchmark_supporting_table"
    output_job_response = client.get(f"/api/projects/{project_id}/jobs")
    assert output_job_response.status_code == 200
    import_job = next(item for item in output_job_response.json() if item["job_type"] == "import_benchmark_dataset")
    assert import_job["output"]["table_count"] == 2
    assert import_job["output"]["relationship_count"] >= 1

    relational_artifact_id = import_response.json()["relational_catalog_artifact"]["id"]
    relational_preview_response = client.get(f"/api/artifacts/{relational_artifact_id}/preview")
    assert relational_preview_response.status_code == 200
    preview = relational_preview_response.json()["preview"]
    assert "relational_catalog.v1" in preview
    assert "SK_ID_CURR" in preview
    assert "shared_key_name" in preview
