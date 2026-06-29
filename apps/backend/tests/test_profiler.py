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
    assert result.profile["profile_mode"] == "full"
    assert result.profile["target_profile"]["unique_count"] == 2
    assert "final_status" in result.profile["leakage_suspects"]
    assert any(item["risk_level"] == "high" for item in result.assumptions)
    assert "Data Understanding" in result.understanding_md


def test_profile_tabular_file_uses_bounded_sample_for_large_inputs(tmp_path: Path) -> None:
    dataset = tmp_path / "wide.csv"
    header = ["row_id", "target", *[f"feature_{index}" for index in range(85)]]
    rows = []
    for row_index in range(120):
        rows.append(
            ",".join(
                [
                    f"id_{row_index}",
                    str(row_index % 2),
                    *[str((row_index + column_index) % 7) for column_index in range(85)],
                ]
            )
        )
    dataset.write_text(",".join(header) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

    result = profile_tabular_file(
        dataset,
        project_id="p_large",
        target_column="target",
        sample_size=25,
        full_profile_max_rows=10,
        full_profile_max_columns=20,
    )

    assert result.row_count == 120
    assert result.column_count == 87
    assert result.profile["profile_mode"] == "bounded_sample"
    assert result.profile["profile_sample"]["sample_row_count"] == 25
    assert result.profile["deferred_deep_profile"]["recommended"] is True
    assert result.profile["deferred_deep_profile"]["deferred_column_count"] == 87
    row_id_profile = next(item for item in result.profile["columns"] if item["name"] == "row_id")
    assert row_id_profile["stats_scope"] == "sample"
    assert row_id_profile["unique_count_is_approximate"] is True
    assert row_id_profile["role"] == "identifier"
    assert any(item["topic"] == "data_understanding" for item in result.assumptions)
    assert "bounded_sample" in result.understanding_md
