from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    Base,
    ExperimentRun,
    LineageEdge,
    Project,
    ResearchPlanCurrentWork,
    ResearchPlanRevision,
    User,
    utc_now,
)
from tabular_harness.services.research_plan_timeline import (
    build_research_plan_timeline_response,
    clean_research_plan_timeline_blocks,
)
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    attach_research_plan_artifact,
    commit_research_plan_revision,
    ensure_harness_initial_research_plan_revision,
    latest_research_plan_current_work,
    record_harness_dataset_upload_in_research_plan,
    record_harness_objective_in_research_plan,
    request_research_plan_human_attention,
    research_plan_artifact_output_types,
    set_research_plan_current_work,
)


def test_research_plan_timeline_preserves_codex_authored_text_without_locale_masking() -> None:
    raw_blocks = [
        {
            "id": "feature_availability_audit_v22",
            "title": "feature availability and leakage surface audit v22",
            "why_it_matters": "target policy承認待ちの間に、安全に使える入力列を整理する。",
            "next_action": "Use this matrix before the post-approval rebuild.",
            "blockers": ["data owner approval is pending"],
            "status": "done",
        }
    ]

    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert blocks[0]["title"] == "feature availability and leakage surface audit v22"
    assert blocks[0]["subtitle"] == "target policy承認待ちの間に、安全に使える入力列を整理する。"
    assert blocks[0]["next_action"] == "Use this matrix before the post-approval rebuild."
    assert blocks[0]["blockers"] == ["data owner approval is pending"]


def test_research_plan_artifact_output_types_include_model_pipeline_research_and_pilot_contracts() -> None:
    cases = {
        "research_findings_report": {"research_findings", "prior_research"},
        "prediction_pipeline": {"prediction_pipeline", "reproducible_pipeline"},
        "model_diagnostics_artifact_pack": {"model_diagnostics", "model_diagnostics_artifacts"},
        "feature_importance": {"model_diagnostics", "native_feature_importance"},
        "permutation_importance": {"model_diagnostics", "permutation_importance"},
        "partial_dependence": {"model_diagnostics", "partial_dependence", "pdp"},
        "shap_summary": {"model_diagnostics", "shap", "shap_summary"},
        "pilot_scoring_report": {"pilot_scoring", "pilot_report"},
        "validation_scheme_audit": {"validation_audit", "pilot_audit"},
    }

    for asset_type, expected in cases.items():
        artifact = Artifact(
            id=f"art_{asset_type}",
            project_id="p_contracts",
            asset_type=asset_type,
            name=asset_type,
            version=1,
            uri="/tmp/non_notebook",
            content_hash="hash",
            metadata_json="{}",
        )

        assert expected.issubset(research_plan_artifact_output_types(artifact))


def test_initial_research_plan_anchors_declare_artifact_contracts() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_initial_contracts", name="Initial Contracts")
        db.add(project)
        db.commit()

        revision = ensure_harness_initial_research_plan_revision(db, project_id=project.id)
        document = loads_json(revision.document_json, {})
        blocks = {block["id"]: block for block in document["timeline_blocks"]}

        assert blocks["data_understanding"]["deliverable_contract"]["expected_outputs"] == ["notebook"]
        assert blocks["prior_knowledge_research"]["deliverable_contract"]["expected_outputs"] == [
            "research_findings"
        ]


def test_harness_dataset_upload_records_canonical_initial_plan_progress() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_upload_plan", name="Upload Plan")
        artifact = Artifact(
            id="art_uploaded_dataset",
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
            version=1,
            uri="/tmp/uploaded.csv",
            content_hash="hash",
            size_bytes=12,
            metadata_json="{}",
        )
        db.add_all([project, artifact])
        db.commit()

        ensure_harness_initial_research_plan_revision(db, project_id=project.id)
        revision = record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=[artifact.id],
            dataset_snapshot_id="ds_uploaded",
            primary_artifact_id=artifact.id,
        )
        db.commit()

        assert revision is not None
        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        blocks = {block["id"]: block for block in response["blocks"]}
        assert blocks["data_upload"]["status"] == "done"
        assert blocks["objective_framing"]["status"] == "active"
        assert response["contract_validation"]["status"] == "ok"
        assert any(link["artifact_id"] == artifact.id for link in blocks["data_upload"]["attached_artifacts"])


def test_research_plan_links_dedupe_duplicate_artifact_edges_before_lookup() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_duplicate_plan_edges", name="Duplicate Plan Edges")
        artifact = Artifact(
            id="art_duplicate_edge_dataset",
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
            version=1,
            uri="/tmp/uploaded.csv",
            content_hash="hash",
            size_bytes=12,
            metadata_json="{}",
        )
        db.add_all([project, artifact])
        db.commit()

        revision = ensure_harness_initial_research_plan_revision(db, project_id=project.id)
        db.add_all(
            [
                LineageEdge(
                    id=f"lin_duplicate_edge_{index}",
                    project_id=project.id,
                    from_asset_type="research_plan_revision",
                    from_asset_id=revision.id,
                    to_asset_type="artifact",
                    to_asset_id=artifact.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json({"node_id": "data_upload", "role": "artifact"}),
                )
                for index in range(1200)
            ]
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        blocks = {block["id"]: block for block in response["blocks"]}
        assert response["contract_validation"]["status"] == "ok"
        assert [link["artifact_id"] for link in blocks["data_upload"]["attached_artifacts"]] == [artifact.id]


def test_harness_objective_records_canonical_plan_progress_after_upload() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_objective_plan", name="Objective Plan", target_column="salary")
        artifact = Artifact(
            id="art_uploaded_dataset_for_objective",
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
            version=1,
            uri="/tmp/uploaded.csv",
            content_hash="hash",
            size_bytes=12,
            metadata_json="{}",
        )
        db.add_all([project, artifact])
        db.commit()

        record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=[artifact.id],
            dataset_snapshot_id="ds_uploaded",
            primary_artifact_id=artifact.id,
        )
        revision = record_harness_objective_in_research_plan(
            db,
            project_id=project.id,
            objective_label=project.target_column,
        )
        db.commit()

        assert revision is not None
        response = build_research_plan_timeline_response(db, project_id=project.id, locale="ja-JP")
        blocks = {block["id"]: block for block in response["blocks"]}
        assert blocks["data_upload"]["status"] == "done"
        assert blocks["objective_framing"]["status"] == "done"
        assert blocks["data_understanding"]["status"] == "active"
        assert response["current_work"]["node_id"] == "data_understanding"


def test_research_plan_current_work_live_state_uses_observed_codex_process(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_current_work_observation",
            name="Current Work Observation",
            current_phase="AUTONOMOUS_LOOP",
        )
        session = AgentSession(
            id="ags_current_work_observation",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue.",
            last_heartbeat_at=utc_now(),
        )
        db.add_all([project, session])
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "deep_data_understanding",
                        "title": "Deep data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex declared the current chapter.",
            strict_validation=True,
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="deep_data_understanding",
            summary="Inspecting relational data.",
            status="active",
            revision_id=revision.id,
        )
        db.commit()

        monkeypatch.setattr(
            "tabular_harness.services.research_plan_timeline.running_codex_processes_for_project",
            lambda project_id: [],
        )
        scheduled_response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        scheduled_current_work = scheduled_response["current_work"]
        assert scheduled_current_work["activity_state"] == "scheduled"
        assert scheduled_current_work["is_live"] is False
        assert scheduled_current_work["observed_codex_process_count"] == 0

        monkeypatch.setattr(
            "tabular_harness.services.research_plan_timeline.running_codex_processes_for_project",
            lambda project_id: [{"pid": 12345, "command": f"codex exec /tmp/{project_id}/task"}],
        )
        active_response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        active_current_work = active_response["current_work"]
        assert active_current_work["activity_state"] == "active"
        assert active_current_work["is_live"] is True
        assert active_current_work["observed_codex_process_count"] == 1


def test_derived_current_work_is_not_marked_live_from_process_presence(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_derived_current_work_observation",
            name="Derived Current Work Observation",
            current_phase="AUTONOMOUS_LOOP",
        )
        session = AgentSession(
            id="ags_derived_current_work_observation",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue.",
            last_heartbeat_at=utc_now(),
        )
        db.add_all([project, session])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "objective_framing",
                        "title": "Objective framing",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex left one active ResearchPlan node in the revision.",
            strict_validation=True,
        )
        db.commit()

        monkeypatch.setattr(
            "tabular_harness.services.research_plan_timeline.running_codex_processes_for_project",
            lambda project_id: [{"pid": 12345, "command": f"codex exec /tmp/{project_id}/task"}],
        )

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        current_work = response["current_work"]
        assert current_work["source"] == "research_plan_revision_status"
        assert current_work["activity_state"] == "declared_only"
        assert current_work["is_live"] is False
        assert current_work["observed_codex_process_count"] == 1


def test_harness_dataset_upload_does_not_override_codex_authored_plan() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_upload_codex_plan", name="Upload Codex Plan")
        artifact = Artifact(
            id="art_uploaded_dataset_codex",
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
            version=1,
            uri="/tmp/uploaded.csv",
            content_hash="hash",
            size_bytes=12,
            metadata_json="{}",
        )
        db.add_all([project, artifact])
        db.commit()
        codex_result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "codex_data_story",
                        "title": "Codex data story",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex owns the project-specific plan.",
            strict_validation=True,
        )
        db.commit()

        revision = record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=[artifact.id],
            dataset_snapshot_id="ds_uploaded",
            primary_artifact_id=artifact.id,
        )
        db.commit()

        assert revision is None
        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert response["source_revision_id"] == codex_result.revision.id
        assert [block["id"] for block in response["blocks"]] == ["codex_data_story"]


def test_research_plan_timeline_uses_explicit_localized_display_when_codex_supplies_it() -> None:
    raw_blocks = [
        {
            "id": "feature_availability_audit_v22",
            "title": "feature availability and leakage surface audit v22",
            "why_it_matters": "Use this matrix before the post-approval rebuild.",
            "status": "active",
            "localizations": {
                "ja-JP": {
                    "title": "特徴量の利用可能性を監査する",
                    "why_it_matters": "承認後の再構築で使える入力列を先に整理します。",
                }
            },
        }
    ]

    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert blocks[0]["title"] == "特徴量の利用可能性を監査する"
    assert blocks[0]["subtitle"] == "承認後の再構築で使える入力列を先に整理します。"


def test_research_plan_timeline_accepts_human_locale_alias_keys() -> None:
    raw_blocks = [
        {
            "id": "deep_eda",
            "title": "Deep EDA and feature hypothesis review",
            "why_it_matters": "Find the data story before modeling.",
            "status": "active",
            "localizations": {
                "Japanese": {
                    "title": "深いEDAと特徴量仮説の確認",
                    "why_it_matters": "モデリング前にデータの物語を見つけます。",
                }
            },
            "subtasks": [
                {
                    "id": "tail_story",
                    "title": "Tail story",
                    "detail": "Inspect high-salary segments.",
                    "status": "pending",
                    "human_display": {
                        "日本語": {
                            "title": "裾の見立て",
                            "detail": "高salaryセグメントを確認します。",
                        }
                    },
                }
            ],
        }
    ]

    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert blocks[0]["title"] == "深いEDAと特徴量仮説の確認"
    assert blocks[0]["subtitle"] == "モデリング前にデータの物語を見つけます。"
    assert blocks[0]["subtasks"][0]["title"] == "裾の見立て"
    assert blocks[0]["subtasks"][0]["detail"] == "高salaryセグメントを確認します。"


def test_research_plan_commit_rejects_missing_japanese_display_locale_for_japanese_project() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        user = User(id="u_plan_locale_contract", email="plan-locale-contract@example.com", locale="ja-JP")
        project = Project(
            id="p_plan_locale_contract",
            name="Plan Locale Contract",
            created_by=user.id,
        )
        db.add_all([user, project])
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "data_upload",
                            "title": "Data upload",
                            "subtitle": "Uploaded data is available.",
                            "granularity": "chapter",
                            "status": "active",
                        }
                    ],
                },
                author_type="codex",
                reason="Codex submitted an English-only plan for a Japanese project.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            issues = exc.issues
        else:
            issues = []

        assert {issue["code"] for issue in issues} == {"localized_display_missing"}
        assert {issue["path"] for issue in issues} == {
            "/timeline_blocks/0/title",
            "/timeline_blocks/0/subtitle",
        }


def test_research_plan_commit_accepts_explicit_japanese_display_locale_for_japanese_project() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        user = User(id="u_plan_locale_ok", email="plan-locale-ok@example.com", locale="ja-JP")
        project = Project(
            id="p_plan_locale_ok",
            name="Plan Locale OK",
            created_by=user.id,
        )
        db.add_all([user, project])
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_upload",
                        "title": "Data upload",
                        "subtitle": "Uploaded data is available.",
                        "granularity": "chapter",
                        "status": "active",
                        "localizations": {
                            "ja-JP": {
                                "title": "データアップロード",
                                "subtitle": "アップロード済みデータを利用できます。",
                            }
                        },
                    }
                ],
            },
            author_type="codex",
            reason="Codex submitted localized display values for a Japanese project.",
            strict_validation=True,
        )

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="ja-JP")
        assert result.created is True
        assert timeline["blocks"][0]["title"] == "データアップロード"
        assert timeline["blocks"][0]["subtitle"] == "アップロード済みデータを利用できます。"


def test_research_plan_timeline_keeps_mixed_language_blocks_visible() -> None:
    raw_blocks = [
        {
            "id": "data_upload",
            "title": "データアップロード / project context",
            "why_it_matters": "Dataset identity、target hint、locale、output contractが確定している。",
            "done_criteria": "context and GOAL are available.",
            "status": "done",
        },
        {
            "id": "approval_response_contract_v19",
            "title": "approval response contract v19",
            "why_it_matters": "data ownerが承認・override・拒否・追加質問を曖昧なく返せるcontractを作る。",
            "next_action": "Apply the response after owner approval.",
            "done_criteria": "approval response schema/template/options exist.",
            "status": "active",
        },
    ]

    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert blocks[0]["title"] == "データアップロード / project context"
    assert blocks[0]["subtitle"] == "Dataset identity、target hint、locale、output contractが確定している。"
    assert blocks[0]["done_criteria"] == "context and GOAL are available."
    assert blocks[1]["title"] == "approval response contract v19"
    assert blocks[1]["next_action"] == "Apply the response after owner approval."


def test_research_plan_timeline_does_not_rewrite_done_status_for_missing_supporting_artifacts() -> None:
    raw_blocks = [
        {
            "id": "data_understanding",
            "title": "Data understanding",
            "status": "done",
            "supporting_artifacts": [{"path": "notebooks/grandmaster_eda.py", "exists": False}],
        }
    ]

    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="en-US")

    assert blocks[0]["status"] == "done"
    assert blocks[0]["missing_supporting_artifact_count"] == 1
    assert blocks[0]["evidence_verified"] is False
    assert blocks[0]["status_adjustment_reason"] is None


def test_research_plan_timeline_prefers_active_db_revision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_revision", name="Plan Revision")
        db.add(project)
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "revision_owned_step",
                        "title": "Revision-owned data understanding",
                        "why_it_matters": "The active revision is the canonical timeline source.",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex committed the active plan.",
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["source_revision_id"] == result.revision.id
        assert response["research_plan_id"] == result.plan.id
        assert response["revision_index"] == 1
        assert response["revision_author_type"] == "codex"
        assert response["blocks"][0]["id"] == "revision_owned_step"
        assert response["blocks"][0]["title"] == "Revision-owned data understanding"

        revisions = list(db.scalars(select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)))
        assert [revision.id for revision in revisions] == [result.revision.id]


def test_research_plan_timeline_does_not_promote_invalid_legacy_artifact(tmp_path: Path) -> None:
    plan_path = tmp_path / "research_plan.json"
    plan_path.write_text(
        dumps_json(
            {
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {"id": f"fine_step_{index}", "title": f"Fine step {index}", "status": "done"}
                    for index in range(8)
                ],
            }
        ),
        encoding="utf-8",
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_invalid_legacy_plan", name="Invalid Legacy Plan")
        artifact = Artifact(
            id="art_invalid_legacy_plan",
            project_id=project.id,
            asset_type="research_plan",
            name="invalid_legacy_plan",
            version=1,
            uri=str(tmp_path),
            content_hash="hash",
            size_bytes=plan_path.stat().st_size,
            metadata_json=dumps_json({"primary_path": str(plan_path)}),
        )
        db.add_all([project, artifact])
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["blocks"][0]["id"] == "data_upload"
        assert response["blocks"][0]["title"] == "Data upload"
        assert len(response["blocks"]) == 4
        ignored = response["ignored_source_artifact"]
        assert ignored["source_artifact_id"] == artifact.id
        assert ignored["contract_validation"]["status"] == "needs_revision"
        assert ignored["contract_validation"]["error_count"] > 0
        revisions = list(db.scalars(select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)))
        assert len(revisions) == 1
        assert revisions[0].source_artifact_id is None


def test_research_plan_timeline_exposes_contract_validation_issues() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_contract", name="Plan Contract")
        db.add(project)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "status": "done",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Legacy file-based plan without tool-contract fields.",
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        validation = response["contract_validation"]
        assert validation["status"] == "needs_revision"
        issue_codes = {issue["code"] for issue in validation["issues"]}
        assert "done_node_missing_completion_evidence" in issue_codes
        assert "done_node_missing_deliverable_contract" in issue_codes
        assert "missing_current_node" in issue_codes
        assert response["blocks"][0]["status"] == "done"


def test_research_plan_rejects_erasing_completed_node_display_detail() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_completed_detail_guard", name="Completed Detail Guard")
        db.add(project)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "subtitle": "Summarize row meaning and leakage-sensitive fields.",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Fixture evidence.",
                        "completion_evidence": [{"output_type": "none"}],
                    }
                ],
            },
            author_type="codex",
            reason="Codex completed data understanding.",
            strict_validation=True,
        )
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "data_understanding",
                            "title": "Data understanding",
                            "granularity": "chapter",
                            "status": "done",
                            "no_output_required": True,
                            "no_output_required_rationale": "Fixture evidence.",
                            "completion_evidence": [{"output_type": "none"}],
                        }
                    ],
                },
                author_type="codex",
                reason="This incorrectly erases completed node display detail.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            detail = getattr(exc, "issues", [])
        else:
            detail = []

        issue_codes = {issue["code"] for issue in detail}
        assert "completed_node_display_text_erased" in issue_codes


def test_research_plan_allows_completed_node_display_detail_rewording() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_completed_detail_reword", name="Completed Detail Reword")
        db.add(project)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "subtitle": "Summarize row meaning and leakage-sensitive fields.",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Fixture evidence.",
                        "completion_evidence": [{"output_type": "none"}],
                    }
                ],
            },
            author_type="codex",
            reason="Codex completed data understanding.",
            strict_validation=True,
        )
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "why_it_matters": "Data meaning and leakage-sensitive fields are recorded in the notebook.",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Fixture evidence.",
                        "completion_evidence": [{"output_type": "none"}],
                    }
                ],
            },
            author_type="codex",
            reason="Codex reworded completed node detail without erasing it.",
            strict_validation=True,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert response["contract_validation"]["status"] == "ok"
        assert response["blocks"][0]["subtitle"] == "Data meaning and leakage-sensitive fields are recorded in the notebook."


def test_research_plan_timeline_exposes_current_work_and_artifact_links(tmp_path: Path) -> None:
    notebook_path = tmp_path / "deep_eda.py"
    notebook_path.write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_tools", name="Plan Tools")
        db.add(project)
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "deep_data_understanding",
                        "title": "Deep data understanding",
                        "why_it_matters": "Codex is inspecting the data story before modeling.",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex committed a concrete plan.",
        )
        artifact = Artifact(
            id="art_deep_eda",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="deep_eda",
            version=1,
            uri=str(notebook_path.parent),
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json(
                {"primary_path": str(notebook_path), "workspace_relative_path": "notebooks/deep_eda.py"}
            ),
        )
        db.add(artifact)
        db.flush()

        current = set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="deep_data_understanding",
            summary="Building the EDA notebook and checking leakage-sensitive columns.",
            expected_outputs=["marimo notebook", "profile findings"],
            revision_id=result.revision.id,
        )
        edge = attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id="deep_data_understanding",
            artifact_id=artifact.id,
            role="notebook",
            revision_id=result.revision.id,
        )
        question = request_research_plan_human_attention(
            db,
            project_id=project.id,
            node_id="deep_data_understanding",
            question="Is this salary definition the one used in production?",
            why_it_matters="The answer changes target construction and evaluation.",
            provisional_assumption="Continue with the uploaded salary field.",
            urgency="high",
            revision_id=result.revision.id,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["current_work"]["id"] == current.id
        assert response["current_work"]["node_id"] == "deep_data_understanding"
        assert response["current_work"]["expected_outputs"] == ["marimo notebook", "profile findings"]
        assert response["artifact_links"][0]["id"] == edge.id
        assert response["artifact_links"][0]["node_id"] == "deep_data_understanding"
        assert response["artifact_links"][0]["artifact_id"] == "art_deep_eda"
        assert response["artifact_links"][0]["target_tab"] == "Notebooks"
        assert response["artifact_links"][0]["target_anchor"] == "notebook-native-marimo-top"
        assert response["blocks"][0]["attached_artifacts"][0]["artifact_id"] == "art_deep_eda"
        assert response["blocks"][0]["attached_artifacts"][0]["target_tab"] == "Notebooks"

        db.refresh(question)
        assert question.priority == 75
        assert question.can_proceed_without_answer is True


def test_research_plan_current_work_rejects_terminal_node_as_active() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_terminal_current", name="Plan Terminal Current")
        db.add(project)
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Synthetic test node already completed.",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "active",
                    },
                ],
            },
            author_type="codex",
            reason="Declare a completed node and the next active node.",
            strict_validation=True,
        )
        db.commit()

        try:
            set_research_plan_current_work(
                db,
                project_id=project.id,
                node_id="data_understanding",
                summary="This would incorrectly revive a completed node.",
                status="active",
                revision_id=result.revision.id,
            )
        except ValueError as exc:
            message = str(exc)
        else:
            message = ""

        assert "points to a done ResearchPlan node" in message
        assert latest_research_plan_current_work(db, project_id=project.id) is None


def test_research_plan_timeline_drops_stale_current_work_after_node_completes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_stale_completed_presence", name="Stale Completed Presence")
        db.add(project)
        db.commit()

        active_result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex started data understanding.",
            strict_validation=True,
        )
        current = set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="data_understanding",
            summary="Working on the data-understanding notebook.",
            status="active",
            revision_id=active_result.revision.id,
        )
        db.commit()

        completed_result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "The output was intentionally omitted in this regression fixture.",
                    }
                ],
            },
            author_type="codex",
            reason="Codex completed the active node.",
            strict_validation=True,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert completed_result.revision.id != active_result.revision.id
        assert latest_research_plan_current_work(db, project_id=project.id).id == current.id
        assert response["blocks"][0]["status"] == "done"
        assert response["current_work"] is None


def test_research_plan_current_work_rejects_non_presence_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_work_presence_only", name="Current Work Presence Only")
        db.add(project)
        db.commit()
        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare active data understanding.",
            strict_validation=True,
        )
        db.commit()

        try:
            set_research_plan_current_work(
                db,
                project_id=project.id,
                node_id="data_understanding",
                summary="This should be represented by the revision, not current_work.",
                status="pending",
                revision_id=result.revision.id,
            )
        except ValueError as exc:
            message = str(exc)
        else:
            message = ""

        assert "current_work represents live presence" in message
        assert latest_research_plan_current_work(db, project_id=project.id) is None


def test_research_plan_current_work_rejects_blank_summary() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_work_blank_summary", name="Current Work Blank Summary")
        db.add(project)
        db.commit()
        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare active data understanding.",
            strict_validation=True,
        )
        db.commit()

        try:
            set_research_plan_current_work(
                db,
                project_id=project.id,
                node_id="data_understanding",
                summary="   ",
                status="active",
                revision_id=result.revision.id,
            )
        except ValueError as exc:
            message = str(exc)
        else:
            message = ""

        assert "current_work.summary is required" in message
        assert latest_research_plan_current_work(db, project_id=project.id) is None


def test_research_plan_timeline_ignores_legacy_blank_current_work() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_legacy_blank_current_work", name="Legacy Blank Current Work")
        db.add(project)
        db.commit()
        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "prior_research",
                        "title": "Prior research",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare active prior research.",
            strict_validation=True,
        )
        plan = result.plan
        db.add(
            ResearchPlanCurrentWork(
                id="rpcw_legacy_blank",
                org_id=plan.org_id,
                project_id=project.id,
                research_plan_id=plan.id,
                revision_id=result.revision.id,
                node_id="prior_research",
                status="active",
                summary="",
                expected_outputs_json="[]",
                updated_by_type="codex",
            )
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["current_work"]["node_id"] == "prior_research"
        assert response["current_work"]["source"] == "research_plan_revision_status"
        assert response["current_work"]["summary"] == "Prior research"


def test_research_plan_timeline_exposes_completion_evidence_artifacts_and_runs(tmp_path: Path) -> None:
    notebook_path = tmp_path / "story_notebook.py"
    notebook_path.write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_evidence_links", name="Plan Evidence Links")
        artifact = Artifact(
            id="art_story_notebook",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="story_notebook",
            version=1,
            uri=str(tmp_path),
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json({"workspace_relative_path": "notebooks/story.py", "primary_path": str(notebook_path)}),
        )
        run = ExperimentRun(
            id="run_story_model",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "text_masked_ridge"}),
            metrics_json=dumps_json({"mae": 25275.0}),
        )
        db.add_all([project, artifact, run])
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "analysis_and_modeling",
                        "title": "Analysis and modeling",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook", "leaderboard_entry"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "workspace_path": "notebooks/story.py"},
                            {"output_type": "leaderboard_entry", "experiment_run_id": run.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Commit registered evidence links.",
            strict_validation=True,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["contract_validation"]["status"] == "ok"
        links = response["blocks"][0]["attached_artifacts"]
        artifact_link = next(link for link in links if link["link_type"] == "artifact")
        run_link = next(link for link in links if link["link_type"] == "experiment_run")
        assert artifact_link["artifact_id"] == artifact.id
        assert artifact_link["asset_type"] == "analysis_notebook"
        assert artifact_link["target_tab"] == "Notebooks"
        assert artifact_link["target_anchor"] == "notebook-native-marimo-top"
        assert run_link["run_id"] == run.id
        assert run_link["target_tab"] == "Leaderboard"
        assert "text_masked_ridge" in run_link["artifact_name"]


def test_research_plan_accepts_marimo_notebook_asset_type_as_native_notebook(tmp_path: Path) -> None:
    notebook_path = tmp_path / "native_marimo.py"
    notebook_path.write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_marimo_asset_type", name="Plan Marimo Asset Type")
        artifact = Artifact(
            id="art_native_marimo_notebook",
            project_id=project.id,
            asset_type="marimo_notebook",
            name="native_marimo_notebook",
            version=1,
            uri=str(tmp_path),
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json(
                {"workspace_relative_path": "notebooks/native_marimo.py", "primary_path": str(notebook_path)}
            ),
        )
        db.add_all([project, artifact])
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "artifact_id": artifact.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Commit native marimo notebook evidence.",
            strict_validation=True,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert response["contract_validation"]["status"] == "ok"
        links = response["blocks"][0]["attached_artifacts"]
        assert any(
            link["artifact_id"] == artifact.id
            and link["asset_type"] == "marimo_notebook"
            and link["target_tab"] == "Notebooks"
            and link["target_anchor"] == "notebook-native-marimo-top"
            for link in links
        )


def test_research_plan_timeline_rewrites_static_notebook_html_links_to_native_source(tmp_path: Path) -> None:
    notebook_path = tmp_path / "story.py"
    notebook_path.write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")
    html_path = tmp_path / "story.html"
    html_path.write_text("<html><body>legacy snapshot</body></html>", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_static_html_link", name="Plan Static HTML Link")
        notebook = Artifact(
            id="art_native_story",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="native_story",
            version=1,
            uri=str(tmp_path),
            content_hash="hash-native",
            size_bytes=12,
            metadata_json=dumps_json({"workspace_relative_path": "notebooks/story.py", "primary_path": str(notebook_path)}),
        )
        html = Artifact(
            id="art_static_story_html",
            project_id=project.id,
            asset_type="notebook_execution_html",
            name="legacy_story_html",
            version=1,
            uri=str(tmp_path),
            content_hash="hash-html",
            size_bytes=12,
            metadata_json=dumps_json({"notebook_artifact_id": notebook.id, "primary_path": str(html_path)}),
        )
        db.add_all([project, notebook, html])
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "analysis",
                        "title": "Analysis",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "artifact_id": notebook.id},
                            {"output_type": "artifact", "artifact_id": html.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Commit native source and a legacy static html link.",
            strict_validation=True,
        )
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id="analysis",
            artifact_id=html.id,
            role="notebook",
            revision_id=result.revision.id,
        )
        db.commit()

        response = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        links = response["blocks"][0]["attached_artifacts"]
        assert all(link["asset_type"] != "notebook_execution_html" for link in links)
        assert any(
            link["artifact_id"] == notebook.id
            and link["asset_type"] == "analysis_notebook"
            and link["target_anchor"] == "notebook-native-marimo-top"
            for link in links
        )


def test_research_plan_rejects_static_html_as_notebook_deliverable(tmp_path: Path) -> None:
    html_path = tmp_path / "grandmaster_eda_static.html"
    html_path.write_text("<html><body>static snapshot</body></html>", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_static_html_guard", name="Plan Static HTML Guard")
        artifact = Artifact(
            id="art_static_html_notebook",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="static_html_notebook",
            version=1,
            uri=str(tmp_path),
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json({"workspace_relative_path": "notebooks/grandmaster_eda.py", "primary_path": str(html_path)}),
        )
        db.add_all([project, artifact])
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "data_understanding",
                            "title": "Data understanding",
                            "granularity": "chapter",
                            "status": "done",
                            "deliverable_contract": {"expected_outputs": ["notebook"]},
                            "completion_evidence": [
                                {"output_type": "notebook", "artifact_id": artifact.id},
                            ],
                        }
                    ],
                },
                author_type="codex",
                reason="Static HTML must not satisfy notebook deliverables.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            detail = getattr(exc, "issues", [])
        else:
            detail = []

        issue_codes = {issue["code"] for issue in detail}
        assert "done_node_missing_registered_deliverables" in issue_codes


def test_research_plan_accepts_structured_report_asset_type_suffix(tmp_path: Path) -> None:
    report_path = tmp_path / "run_report.md"
    report_path.write_text("# Run report\n", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_report_suffix", name="Plan Report Suffix")
        artifact = Artifact(
            id="art_run_report",
            project_id=project.id,
            asset_type="run_report",
            name="run_report",
            version=1,
            uri=str(tmp_path),
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json({"workspace_relative_path": "reports/run_report.md", "primary_path": str(report_path)}),
        )
        db.add_all([project, artifact])
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "reporting",
                        "title": "Reporting",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["report"]},
                        "completion_evidence": [
                            {"output_type": "report", "artifact_id": artifact.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered run_report should satisfy report deliverable contracts.",
            strict_validation=True,
        )
        db.commit()

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert timeline["contract_validation"]["status"] == "ok"
        link = timeline["blocks"][0]["attached_artifacts"][0]
        assert link["asset_type"] == "run_report"
        assert link["role"] == "report"


def test_research_plan_rejects_dropping_open_deliverable_contract_without_replacement() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_open_contract_drop", name="Open Contract Drop")
        db.add(project)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Fixture setup.",
                        "completion_evidence": [{"output_type": "none"}],
                    },
                    {
                        "id": "prior_knowledge_research",
                        "title": "Prior knowledge research",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["research_findings"]},
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Start prior knowledge research.",
            strict_validation=True,
        )
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "data_understanding",
                            "title": "Data understanding",
                            "granularity": "chapter",
                            "status": "done",
                            "no_output_required": True,
                            "no_output_required_rationale": "Fixture setup.",
                            "completion_evidence": [{"output_type": "none"}],
                        },
                        {
                            "id": "modeling",
                            "title": "Modeling",
                            "granularity": "chapter",
                            "status": "active",
                        },
                    ],
                },
                author_type="codex",
                reason="This incorrectly drops the open prior research deliverable.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            detail = getattr(exc, "issues", [])
        else:
            detail = []

        issue_codes = {issue["code"] for issue in detail}
        assert "open_contract_node_removed" in issue_codes


def test_research_plan_allows_renaming_open_deliverable_contract_when_expected_output_is_preserved() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_open_contract_rename", name="Open Contract Rename")
        db.add(project)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "prior_knowledge_research",
                        "title": "Prior knowledge research",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["research_findings"]},
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Start prior knowledge research.",
            strict_validation=True,
        )
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "domain_and_literature_scan",
                        "title": "Domain and literature scan",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["research_findings"]},
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Rename the research node while preserving the deliverable contract.",
            strict_validation=True,
        )
        db.commit()

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")

        assert timeline["contract_validation"]["status"] == "ok"
        assert timeline["blocks"][0]["id"] == "domain_and_literature_scan"
