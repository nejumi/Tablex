from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    Base,
    ExperimentRun,
    Project,
    ResearchPlanRevision,
)
from tabular_harness.services.research_plan_timeline import (
    build_research_plan_timeline_response,
    clean_research_plan_timeline_blocks,
    research_plan_localization_summary,
)
from tabular_harness.services.research_plans import (
    attach_research_plan_artifact,
    commit_research_plan_revision,
    ensure_harness_initial_research_plan_revision,
    record_harness_dataset_upload_in_research_plan,
    request_research_plan_human_attention,
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

    summary = research_plan_localization_summary(raw_blocks, locale="ja-JP")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert summary["requires_explicit_locale"] is False
    assert summary["missing_block_count"] == 0
    assert blocks[0]["title"] == "feature availability and leakage surface audit v22"
    assert blocks[0]["subtitle"] == "target policy承認待ちの間に、安全に使える入力列を整理する。"
    assert blocks[0]["next_action"] == "Use this matrix before the post-approval rebuild."
    assert blocks[0]["blockers"] == ["data owner approval is pending"]
    assert blocks[0]["localization_status"] == "localized"


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

    summary = research_plan_localization_summary(raw_blocks, locale="ja-JP")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert summary["missing_block_count"] == 0
    assert blocks[0]["title"] == "特徴量の利用可能性を監査する"
    assert blocks[0]["subtitle"] == "承認後の再構築で使える入力列を先に整理します。"
    assert blocks[0]["localization_status"] == "localized"


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

    summary = research_plan_localization_summary(raw_blocks, locale="ja-JP")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert summary["missing_block_count"] == 0
    assert summary["missing_subtask_count"] == 0
    assert blocks[0]["title"] == "深いEDAと特徴量仮説の確認"
    assert blocks[0]["subtitle"] == "モデリング前にデータの物語を見つけます。"
    assert blocks[0]["subtasks"][0]["title"] == "裾の見立て"
    assert blocks[0]["subtasks"][0]["detail"] == "高salaryセグメントを確認します。"


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

    summary = research_plan_localization_summary(raw_blocks, locale="ja-JP")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert summary["missing_block_count"] == 0
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


def test_research_plan_timeline_exposes_current_work_and_artifact_links() -> None:
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
            uri="/tmp/deep_eda.py",
            content_hash="hash",
            size_bytes=12,
            metadata_json="{}",
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
        assert response["blocks"][0]["attached_artifacts"][0]["artifact_id"] == "art_deep_eda"

        db.refresh(question)
        assert question.priority == 75
        assert question.can_proceed_without_answer is True


def test_research_plan_timeline_exposes_completion_evidence_artifacts_and_runs() -> None:
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
            uri="/tmp/story_notebook.py",
            content_hash="hash",
            size_bytes=12,
            metadata_json=dumps_json({"workspace_relative_path": "notebooks/story.py"}),
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
        assert run_link["run_id"] == run.id
        assert run_link["target_tab"] == "Leaderboard"
        assert "text_masked_ridge" in run_link["artifact_name"]
