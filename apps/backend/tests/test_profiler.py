from __future__ import annotations

from pathlib import Path

from tabular_harness.services.profiler import profile_tabular_file


def test_profile_tabular_file_generates_understanding_assets(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    dataset.write_text(
        "customer_id,created_at,feature,target,final_status\n"
        "c1,2026-01-01,10,1,won\n"
        "c1,2026-01-02,11,0,lost\n"
        "c2,2026-01-03,13,1,won\n",
        encoding="utf-8",
    )

    result = profile_tabular_file(dataset, project_id="p_test", target_column="target")

    assert result.row_count == 3
    assert result.column_count == 5
    assert result.profile["target_profile"]["unique_count"] == 2
    assert "final_status" in result.profile["leakage_suspects"]
    assert any(item["risk_level"] == "high" for item in result.assumptions)
    assert "Data Understanding" in result.understanding_md

