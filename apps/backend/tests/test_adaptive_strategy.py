from __future__ import annotations

from tabular_harness.models.entities import DatasetSnapshot, EvaluationSpec, Project, SplitManifest
from tabular_harness.services.adaptive_strategy import build_candidate_lanes, choose_next_action


def test_strategy_next_action_allows_objective_definition_after_understanding() -> None:
    project = Project(
        id="p_strategy",
        name="Strategy fixture",
        task_type="unknown",
        target_column=None,
        current_phase="UNDERSTANDING",
    )
    dataset = DatasetSnapshot(
        id="ds_strategy",
        project_id=project.id,
        artifact_id="art_dataset",
        source_type="upload",
        source_ref="fixture.csv",
        row_count=10,
        column_count=4,
        schema_hash="schema",
        data_hash="data",
    )

    action = choose_next_action(
        project=project,
        dataset=dataset,
        evaluation_spec=None,
        split_manifest=None,
        latest_artifacts={},
        ideas=[],
        runs=[],
        assumptions=[],
        questions=[],
    )

    assert action["action_type"] == "agent_task"
    assert action["target_tab"] == "Understanding"
    assert "objective may be an existing supervised target" in action["prompt"]
    assert "clustering/anomaly detection" in action["prompt"]


def test_strategy_lanes_keep_baseline_advisory_and_codex_open_ended() -> None:
    project = Project(
        id="p_strategy",
        name="Strategy fixture",
        task_type="binary_classification",
        target_column="target",
        current_phase="EXPERIMENTS",
    )
    dataset = DatasetSnapshot(
        id="ds_strategy",
        project_id=project.id,
        artifact_id="art_dataset",
        source_type="upload",
        source_ref="fixture.csv",
        row_count=10,
        column_count=4,
        schema_hash="schema",
        data_hash="data",
    )
    spec = EvaluationSpec(
        id="spec_strategy",
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        name="Primary",
        split_type="stratified",
        primary_metric="roc_auc",
        rationale_md="Use stratification.",
        risk_level="medium",
        status="approved",
    )
    split = SplitManifest(
        id="split_strategy",
        project_id=project.id,
        evaluation_spec_id=spec.id,
        artifact_id="art_split",
        train_count=8,
        valid_count=2,
        test_count=None,
        summary_json="{}",
    )

    lanes = build_candidate_lanes(
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
        split_manifest=split,
        latest_artifacts={},
        ideas=[],
        runs=[],
        assumptions=[],
        questions=[],
    )

    codex_lane = next(lane for lane in lanes if lane["lane_id"] == "codex_approach_space")
    baseline_lane = next(lane for lane in lanes if lane["lane_id"] == "adaptive_baseline")
    assert codex_lane["status"] == "needs_handoff"
    assert "do not execute a fixed catalog blindly" in codex_lane["agent_role"]
    assert baseline_lane["status"] == "needs_plan"
    assert "when evidence supports them" in baseline_lane["agent_role"]
