from __future__ import annotations

from tabular_harness.services.research_plan_timeline import (
    clean_research_plan_timeline_blocks,
    research_plan_localization_summary,
)


def test_research_plan_timeline_masks_partially_localized_blocks() -> None:
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

    assert summary["missing_block_count"] == 1
    assert blocks[0]["title"] == "表示言語の更新待ち"
    assert blocks[0]["subtitle"] == ""
    assert blocks[0]["next_action"] is None
    assert blocks[0]["blockers"] == []
    assert blocks[0]["localization_status"] == "needs_locale_refresh"


def test_research_plan_timeline_uses_explicit_localized_display() -> None:
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


def test_research_plan_timeline_masks_codex_added_mixed_english_blocks() -> None:
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
        {
            "id": "registration_packet_supplement_v44",
            "title": "registration packet supplement v44",
            "why_it_matters": "登録候補の追加根拠をまとめる。",
            "status": "pending",
        },
    ]

    summary = research_plan_localization_summary(raw_blocks, locale="ja-JP")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="ja-JP")

    assert summary["missing_block_count"] == 3
    assert {block["title"] for block in blocks} == {"表示言語の更新待ち"}
    assert all(block["subtitle"] == "" for block in blocks)
    assert all(block["localization_status"] == "needs_locale_refresh" for block in blocks)
    assert all(block["next_action"] is None for block in blocks)


def test_research_plan_timeline_treats_human_japanese_locale_labels_as_japanese() -> None:
    raw_blocks = [
        {
            "id": "codex_added_modeling",
            "title": "Model diagnostics and feature importance",
            "why_it_matters": "Explain error slices before choosing the next experiment.",
            "status": "active",
        },
        {
            "id": "localized_modeling",
            "title": "モデル診断を深掘りする",
            "why_it_matters": "次の実験を選ぶ前に誤差スライスを確認します。",
            "status": "pending",
        },
    ]

    summary = research_plan_localization_summary(raw_blocks, locale="Japanese / 日本語")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="Japanese / 日本語")

    assert summary["requires_explicit_locale"] is True
    assert summary["missing_block_count"] == 1
    assert blocks[0]["title"] == "表示言語の更新待ち"
    assert blocks[0]["subtitle"] == ""
    assert blocks[0]["localization_status"] == "needs_locale_refresh"
    assert blocks[1]["title"] == "モデル診断を深掘りする"
    assert blocks[1]["subtitle"] == "次の実験を選ぶ前に誤差スライスを確認します。"
    assert blocks[1]["localization_status"] == "localized"


def test_research_plan_timeline_masks_japanese_blocks_for_english_display() -> None:
    raw_blocks = [
        {
            "id": "objective_task_framing",
            "title": "目的・タスク定義",
            "why_it_matters": "salary予測の目的を確認します。",
            "status": "active",
        },
        {
            "id": "model_review",
            "title": "Model review",
            "why_it_matters": "Compare the current run evidence.",
            "status": "pending",
        },
    ]

    summary = research_plan_localization_summary(raw_blocks, locale="en-US")
    blocks = clean_research_plan_timeline_blocks(raw_blocks, locale="en-US")

    assert summary["missing_block_count"] == 1
    assert blocks[0]["title"] == "Display language refresh pending"
    assert blocks[0]["subtitle"] == ""
    assert blocks[0]["localization_status"] == "needs_locale_refresh"
    assert blocks[1]["title"] == "Model review"
    assert blocks[1]["subtitle"] == "Compare the current run evidence."
    assert blocks[1]["localization_status"] == "localized"
