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
