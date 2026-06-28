from __future__ import annotations

from pathlib import Path

import pytest
from tabular_harness.services.planned_agent_workspace import (
    ensure_safe_context_target,
    safe_filename_part,
)


def test_safe_filename_part_removes_path_characters() -> None:
    assert safe_filename_part("../secret/key.json") == "secret_key.json"
    assert safe_filename_part("feature recipe: tf-idf + xgboost") == "feature_recipe__tf-idf___xgboost"


def test_ensure_safe_context_target_rejects_escape(tmp_path: Path) -> None:
    context_dir = tmp_path / "workspace" / ".harness" / "context"
    context_dir.mkdir(parents=True)

    ensure_safe_context_target(context_dir, context_dir / "library_assets" / "asset.json")
    with pytest.raises(ValueError):
        ensure_safe_context_target(context_dir, tmp_path / "outside.json")
