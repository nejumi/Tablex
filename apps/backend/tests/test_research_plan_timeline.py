from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.models.entities import Base, Project, ResearchPlanRevision
from tabular_harness.services.research_plan_timeline import (
    build_research_plan_timeline_response,
    clean_research_plan_timeline_blocks,
    research_plan_localization_summary,
)
from tabular_harness.services.research_plans import commit_research_plan_revision


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
