from __future__ import annotations

from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    Project,
    SplitManifest,
)
from tabular_harness.services.agent_task_planner import (
    build_agent_task_contract_payload,
    build_planner_approach_candidates,
    validate_agent_task_contract,
)


def test_planner_contract_carries_flexible_approach_context() -> None:
    project = Project(
        id="p_planner",
        name="Planner fixture",
        task_type="binary_classification",
        target_column="target",
        current_phase="EXPERIMENTS",
    )
    dataset = DatasetSnapshot(
        id="ds_planner",
        project_id=project.id,
        artifact_id="art_dataset",
        source_type="benchmark_catalog",
        source_ref="home_credit_application",
        row_count=100,
        column_count=5,
        schema_hash="schema_hash",
        data_hash="data_hash",
    )
    spec = EvaluationSpec(
        id="spec_planner",
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        name="Primary stratified",
        split_type="stratified",
        primary_metric="roc_auc",
        rationale_md="Use a stratified validation split.",
        risk_level="medium",
        status="approved",
    )
    split = SplitManifest(
        id="split_planner",
        project_id=project.id,
        evaluation_spec_id=spec.id,
        artifact_id="art_split",
        train_count=80,
        valid_count=20,
        test_count=None,
        summary_json=dumps_json({"train_fraction": 0.8}),
    )
    relational_catalog = Artifact(
        id="art_relational",
        project_id=project.id,
        asset_type="relational_catalog",
        name="relational_catalog_home_credit",
        version=1,
        uri="/tmp/relational",
        content_hash="hash",
        metadata_json=dumps_json({"benchmark_id": "home_credit", "table_count": 4, "relationship_count": 3}),
    )
    strategy_brief = Artifact(
        id="art_strategy",
        project_id=project.id,
        asset_type="adaptive_strategy_brief",
        name="adaptive_strategy_brief_fixture",
        version=1,
        uri="/tmp/strategy",
        content_hash="strategy_hash",
        metadata_json=dumps_json({"recommended_action_type": "agent_task", "lane_count": 7}),
    )
    profile = {
        "column_count": 5,
        "semantic_counts": {"text": 1, "datetime": 1, "numeric": 2},
        "roles": {"feature": 4, "target": 1},
        "has_text": True,
        "has_datetime": True,
        "has_group": False,
        "leakage_columns": ["post_target_status"],
    }
    semantic_columns = [
        {"column_name": "free_text", "semantic_type": "text", "role": "feature"},
        {"column_name": "event_time", "semantic_type": "datetime", "role": "feature"},
        {"column_name": "target", "semantic_type": "categorical", "role": "target"},
    ]
    context_artifacts = {
        "relational_catalog": relational_catalog,
        "adaptive_strategy_brief": strategy_brief,
        "research_plan": None,
        "benchmark_scenario_pack": None,
    }

    candidates = build_planner_approach_candidates(
        project=project,
        profile=profile,
        context_artifacts=context_artifacts,
    )
    approach_types = {candidate["approach_type"] for candidate in candidates}
    assert "tabular_gradient_boosting" in approach_types
    assert "text_enhanced_tabular" in approach_types
    assert "time_aware_tabular" in approach_types
    assert "relational_feature_recipe" in approach_types

    contract = build_agent_task_contract_payload(
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
        split_manifest=split,
        semantic_columns=semantic_columns,
        profile=profile,
        assumptions=[],
        questions=[],
        context_artifacts=context_artifacts,
        asset_recommendations=[
            {
                "asset_id": "asset_xgb",
                "asset_type": "feature_recipe",
                "latest_version_id": "av_xgb",
                "name": "xgboost_mixed_type_baseline",
                "reason": "Mixed-type tabular modeling is relevant.",
            }
        ],
        approach_candidates=candidates,
        research_queries=[
            {
                "query_id": "time_aware_tabular_features",
                "query": "time aware tabular features lag rolling statistics leakage validation",
                "purpose": "Plan temporal features.",
                "priority": 78,
                "expected_evidence": "source_summary",
            }
        ],
        objective=None,
        task_type="implement_prediction_approach",
    )

    validate_agent_task_contract(contract)
    inputs = contract["inputs"]
    assert inputs["schema_version"] == "agent_task_planning.v1"
    assert inputs["dataset_context"]["dataset_snapshot_id"] == dataset.id
    assert inputs["evaluation_contract"]["split_manifest"]["split_manifest_id"] == split.id
    assert inputs["constraints"]["connector_credentials"] == "never_materialized"
    assert inputs["benchmark_context"]["benchmark_id"] == "home_credit"
    assert inputs["adaptive_strategy_brief"]["artifact_id"] == strategy_brief.id
    assert inputs["adaptive_strategy_brief"]["policy"] == (
        "product_guidance_for_open_ended_runner_handoff_not_a_fixed_recipe"
    )
    assert inputs["open_ended_approach_space"]["strategy_brief_available"] is True
    assert any(
        item["role"] == "adaptive_strategy_brief" and item["artifact_id"] == strategy_brief.id
        for item in inputs["available_context_artifacts"]
    )
    assert len(inputs["artifact_expectations"]) >= 5
    assert any("validation/test targets" in item for item in contract["forbidden_actions"])
