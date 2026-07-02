from __future__ import annotations

from pathlib import Path

from tabular_harness.services.agent_sessions import (
    asset_type_for_session_output,
    metadata_for_session_output,
)


def test_agent_session_marimo_notebook_outputs_are_analysis_notebooks() -> None:
    path = Path("notebooks/grandmaster_eda.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "data_understanding"


def test_agent_session_model_notebook_outputs_are_diagnostics_notebooks() -> None:
    path = Path("notebooks/salary_model_diagnostics.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "model_diagnostics"
