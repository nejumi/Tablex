from __future__ import annotations

import json
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import tabular_harness.api.routes as routes_module
import tabular_harness.services.marimo_sessions as marimo_sessions_module
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from tabular_harness.api.routes import (
    compact_agent_chat_history_turns,
    format_elapsed_seconds,
    heartbeat_phrase_for_locale,
    matching_main_session_update_for_chat_job,
    merge_activity_workers,
    seconds_since_timestamp,
    summarize_runtime_error_for_chat,
    visible_activity_workers,
)
from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    AssetReference,
    DatasetSnapshot,
    DeliverableExpectation,
    EvaluationCandidate,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Job,
    LineageEdge,
    ModelVersion,
    PilotPredictionBatch,
    Project,
    Question,
    ResearchBrief,
    SplitManifest,
    User,
    utc_now,
)
from tabular_harness.schemas import AgentResult
from tabular_harness.services.agent_inbox import list_inbox_entries
from tabular_harness.services.agent_requests.deliverables import process_deliverable_tool_requests
from tabular_harness.services.agent_session_results import process_experiment_result_requests
from tabular_harness.services.agent_sessions import (
    append_runner_stream_to_workspace,
    append_session_event,
    execute_notebook_registration_request,
    ingest_session_workspace_outputs,
    latest_user_instruction_path,
    maybe_register_chat_update_from_workspace_output,
    pipeline_acks_dir,
    pipeline_requests_dir,
    prepare_session_workspace,
    progress_request_path,
    register_agent_session_attention_chat_turn,
    user_instructions_inbox_path,
)
from tabular_harness.services.analysis_notebooks import marimo_notebook_source_hash_for_artifact
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.deliverable_expectations import (
    fulfill_run_pipeline_bundle_expectations,
    maybe_write_open_deliverable_expectation_observation,
)
from tabular_harness.services.jobs import (
    acquire_next_job,
    create_job,
    mark_job_running,
    reap_stale_running_jobs,
)
from tabular_harness.services.marimo_sessions import NativeMarimoSession
from tabular_harness.services.metric_preferences import metric_lower_is_better
from tabular_harness.services.portal import target_tab_for_artifact, target_tab_for_job
from tabular_harness.services.research_plans import (
    commit_research_plan_revision,
    set_research_plan_current_work,
)
from tabular_harness.services.result_notebook_evidence import (
    latest_model_diagnostics_notebook_for_run,
)
from tabular_harness.services.result_readout import (
    gap_target_tab,
    next_result_action,
    normalize_result_readout_target_tab,
)
from tabular_harness.worker.jobs import (
    agent_chat_turn_handler,
    continue_autonomous_session_handler,
    create_default_worker,
)
from tabular_harness.worker.runner import SyncWorker


def make_client(tmp_path: Path, *, api_agent_session_supervisor_enabled: bool = True) -> TestClient:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        api_agent_session_supervisor_enabled=api_agent_session_supervisor_enabled,
        local_worker_enabled=False,
    )
    return TestClient(create_app(settings))


def run_queued_agent_chat_turn(client: TestClient, job_id: str) -> dict[str, Any]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        worker = SyncWorker(handlers={"agent_chat_turn": agent_chat_turn_handler}, store=app.state.artifact_store)
        completed = worker.run_job(db, job)
        assert completed.status == "succeeded", completed.error_message
        return loads_json(completed.output_json, {})


def run_queued_job(client: TestClient, job_id: str) -> dict[str, Any]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        worker = create_default_worker(store=app.state.artifact_store)
        completed = worker.run_job(db, job)
        assert completed.status == "succeeded", completed.error_message
        return loads_json(completed.output_json, {})


def test_research_findings_json_preview_renders_source_link_list(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Research Preview"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_findings_report",
            name="research_preview",
            filename="research_findings.json",
            metadata={"topic": "salary prediction prior knowledge"},
            payload={
                "schema_version": "research_findings_report.v1",
                "topic": "salary prediction prior knowledge",
                "sources": [
                    {
                        "url": "https://example.com/prior",
                        "title": "Prior source",
                        "source_type": "other",
                        "retrieved_at": "2026-07-06T00:00:00Z",
                        "key_claims": ["Group validation is useful when entities repeat."],
                    }
                ],
                "findings": [
                    {
                        "claim": "Repeated companies should not be split across train and validation.",
                        "source_indexes": [0],
                        "implication_for_project": "Use company-aware validation when company_id is present.",
                        "recommended_action": "Register company-grouped split evidence before model comparison.",
                    }
                ],
            },
        )
        db.commit()

    response = client.get(f"/api/artifacts/{artifact.id}/preview")

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["content_type"] == "md"
    assert "[0] [Prior source](https://example.com/prior)" in preview["preview"]
    assert "Repeated companies should not be split across train and validation." in preview["preview"]
    assert "Project implication: Use company-aware validation when company_id is present." in preview["preview"]


def test_research_findings_json_preview_prefers_rich_markdown_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Research Rich Preview"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        figure = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_report_figure",
            name="research_preview_figure_chart",
            filename="chart.svg",
            text="<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            metadata={"markdown_reference": "figures/chart.svg"},
        )
        second_figure = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_report_figure",
            name="research_preview_figure_scatter",
            filename="scatter.svg",
            text="<svg xmlns='http://www.w3.org/2000/svg'><circle cx='4' cy='4' r='3'/></svg>",
            metadata={"markdown_reference": "figures/scatter.svg"},
        )
        rich_report = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_markdown_report",
            name="research_rich_preview",
            filename="report.md",
            text=(
                "# Rich research report\n\n"
                "| Source | Claim |\n"
                "| --- | --- |\n"
                "| Prior source | Group-aware validation is relevant. |\n\n"
                "![Chart](figures/chart.svg)\n\n"
                "![Scatter](figures/scatter.svg)\n"
            ),
            metadata={
                "figure_artifact_ids": [figure.id, second_figure.id],
                "figure_references": [
                    {"markdown_reference": "figures/chart.svg", "artifact_id": figure.id},
                    {"markdown_reference": "figures/scatter.svg", "artifact_id": second_figure.id},
                ],
            },
        )
        artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_findings_report",
            name="research_preview_with_rich_report",
            filename="research_findings.json",
            metadata={"rich_report_artifact_id": rich_report.id},
            payload={
                "schema_version": "research_findings_report.v1",
                "topic": "salary prediction prior knowledge",
                "rich_report_artifact_id": rich_report.id,
                "sources": [
                    {
                        "url": "https://example.com/prior",
                        "title": "Prior source",
                        "source_type": "other",
                        "retrieved_at": "2026-07-06T00:00:00Z",
                        "key_claims": ["Fallback source list should not be the preview when rich report exists."],
                    }
                ],
                "findings": [
                    {
                        "claim": "Fallback finding",
                        "source_indexes": [0],
                        "implication_for_project": "Fallback implication.",
                        "recommended_action": "Fallback action.",
                    }
                ],
            },
        )
        db.commit()

    response = client.get(f"/api/artifacts/{artifact.id}/preview")

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["content_type"] == "md"
    assert "# Rich research report" in preview["preview"]
    assert "| Source | Claim |" in preview["preview"]
    assert f"/api/artifacts/{figure.id}/download" in preview["preview"]
    assert f"/api/artifacts/{second_figure.id}/download" in preview["preview"]
    assert "Fallback finding" not in preview["preview"]


def test_pilot_report_previews_hide_internal_ids(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Pilot Preview"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        scoring = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="pilot_scoring_report",
            name="pilot_scoring_preview",
            filename="pilot_scoring_report.json",
            metadata={"deployment_id": "pd_hidden"},
            payload={
                "schema_version": "pilot_scoring_report.v1",
                "deployment_id": "pd_hidden",
                "matched_rows": 12,
                "metric_count": 2,
                "metrics": {"mae": 1500.0, "rmse": 1581.1},
                "as_of_violations": {"count": 0},
            },
        )
        audit = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="validation_scheme_audit",
            name="validation_audit_preview",
            filename="validation_scheme_audit.json",
            metadata={"deployment_id": "pd_hidden"},
            payload={
                "schema_version": "validation_scheme_audit.v1",
                "deployment_id": "pd_hidden",
                "scheme_verdict": "partially_confirmed",
                "next_iteration_focus": "Collect a larger forward batch.",
                "gap_decomposition": [
                    {
                        "component": "sample_noise",
                        "evidence": "Small pilot batch.",
                        "magnitude": "small",
                        "confidence": "low",
                    }
                ],
                "hypotheses": [
                    {
                        "id": "h_hidden",
                        "statement": "Pilot error remains close to validation.",
                        "test_plan": "Use a larger batch.",
                        "expected_evidence": "Stable MAE bands.",
                    }
                ],
            },
        )
        db.commit()

    scoring_preview = client.get(f"/api/artifacts/{scoring.id}/preview").json()
    audit_preview = client.get(f"/api/artifacts/{audit.id}/preview").json()

    assert scoring_preview["content_type"] == "md"
    assert "Pilot scoring report" in scoring_preview["preview"]
    assert "mae: 1500" in scoring_preview["preview"]
    assert "pd_hidden" not in scoring_preview["preview"]
    assert audit_preview["content_type"] == "md"
    assert "Validation scheme audit" in audit_preview["preview"]
    assert "partially confirmed" in audit_preview["preview"]
    assert "Collect a larger forward batch." in audit_preview["preview"]
    assert "pd_hidden" not in audit_preview["preview"]
    assert "h_hidden" not in audit_preview["preview"]


def collect_target_tabs(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        tabs = [payload["target_tab"]] if isinstance(payload.get("target_tab"), str) else []
        for value in payload.values():
            tabs.extend(collect_target_tabs(value))
        return tabs
    if isinstance(payload, list):
        tabs: list[str] = []
        for item in payload:
            tabs.extend(collect_target_tabs(item))
        return tabs
    return []


def run_queued_job_expect_status(client: TestClient, job_id: str, expected_status: str) -> tuple[Job, dict[str, Any]]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        worker = create_default_worker(store=app.state.artifact_store)
        completed = worker.run_job(db, job)
        assert completed.status == expected_status, completed.error_message
        return completed, loads_json(completed.output_json, {})


def wait_for_job_status(
    client: TestClient,
    job_id: str,
    *,
    statuses: set[str],
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["status"] in statuses:
            return latest
        time.sleep(0.05)
    assert latest is not None
    raise AssertionError(f"Job {job_id} did not reach {sorted(statuses)}; latest status was {latest['status']}")


def test_sqlite_engine_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
    )
    app = create_app(settings)

    with app.state.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000


def test_visible_activity_workers_hide_old_terminal_cards() -> None:
    now = utc_now()
    old_time = (now - timedelta(seconds=60)).isoformat()
    recent_time = (now - timedelta(seconds=4)).isoformat()

    workers = visible_activity_workers(
        [
            {"worker_id": "old", "status": "succeeded", "updated_at": old_time, "active": False},
            {"worker_id": "recent", "status": "failed", "updated_at": recent_time, "active": False},
            {"worker_id": "old-queued", "status": "queued", "updated_at": old_time, "active": False},
            {"worker_id": "queued", "status": "queued", "updated_at": recent_time, "active": True},
            {"worker_id": "session", "status": "running", "updated_at": old_time, "active": True},
        ],
        now=now,
    )

    assert [worker["worker_id"] for worker in workers] == ["recent", "queued", "session"]


def test_visible_activity_workers_limit_terminal_upload_import_cards() -> None:
    now = utc_now()
    recent_time = (now - timedelta(seconds=4)).isoformat()
    worker_payloads = [
        {
            "worker_id": f"upload-{index}",
            "job_type": "upload_data_bundle" if index % 2 == 0 else "import_benchmark_dataset",
            "status": "succeeded",
            "updated_at": recent_time,
            "active": False,
        }
        for index in range(7)
    ]
    worker_payloads.append(
        {
            "worker_id": "model-report",
            "job_type": "train_model_candidates",
            "status": "succeeded",
            "updated_at": recent_time,
            "active": False,
        }
    )

    workers = visible_activity_workers(worker_payloads, now=now)

    assert [worker["worker_id"] for worker in workers if str(worker.get("worker_id", "")).startswith("upload-")] == [
        "upload-0",
        "upload-1",
        "upload-2",
        "upload-3",
        "upload-4",
    ]
    assert any(worker["worker_id"] == "model-report" for worker in workers)


def test_merge_activity_workers_keeps_subagent_cards_distinct() -> None:
    now = utc_now()
    old_time = (now - timedelta(seconds=30)).isoformat()
    recent_time = (now - timedelta(seconds=3)).isoformat()
    workers = merge_activity_workers(
        [
            {
                "worker_id": "child-a",
                "job_id": "job_shared",
                "status": "queued",
                "updated_at": old_time,
                "active": True,
                "detail": "queued fallback",
                "token_usage": {"is_estimate": True, "series": []},
            },
            {
                "worker_id": "child-a",
                "job_id": "job_shared",
                "status": "running",
                "updated_at": recent_time,
                "active": True,
                "detail": "live child A",
                "project_name": "Project A",
                "human_description": {"title": "Child A", "summary": "live"},
                "token_usage": {"is_estimate": False, "series": [{"step": "live", "tokens": 12}]},
            },
            {
                "worker_id": "child-b",
                "job_id": "job_shared",
                "status": "running",
                "updated_at": recent_time,
                "active": True,
                "detail": "live child B",
                "token_usage": {"is_estimate": True, "series": []},
            },
            {
                "worker_id": "main-agent-session",
                "agent_session_id": "ags_same",
                "status": "between_turns",
                "updated_at": old_time,
                "active": True,
                "detail": "older session",
                "token_usage": {"is_estimate": True, "series": []},
            },
            {
                "worker_id": "main-agent-session-retry",
                "agent_session_id": "ags_same",
                "status": "running",
                "updated_at": recent_time,
                "active": True,
                "detail": "live session",
                "raw_transcript": {"stdout_line_count": 5},
                "token_usage": {"is_estimate": True, "series": []},
            },
        ]
    )

    assert [worker["worker_id"] for worker in workers] == ["child-a", "child-b", "main-agent-session-retry"]
    assert workers[0]["status"] == "running"
    assert workers[0]["detail"] == "live child A"
    assert workers[0]["project_name"] == "Project A"
    assert workers[0]["token_usage"]["is_estimate"] is False
    assert workers[2]["raw_transcript"]["stdout_line_count"] == 5
    assert len([worker for worker in workers if worker["active"]]) == 3
    assert len(visible_activity_workers(workers, now=now)) == 3


def test_agent_activity_elapsed_output_helpers() -> None:
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)

    assert seconds_since_timestamp(now - timedelta(seconds=42), now=now) == 42
    assert seconds_since_timestamp(None, now=now) is None
    assert format_elapsed_seconds(42) == "42s"
    assert format_elapsed_seconds(125) == "2m"
    assert format_elapsed_seconds(3660) == "1h 1m"
    assert heartbeat_phrase_for_locale(75, locale="ja-JP") == " 最終出力は1分前です。"
    assert heartbeat_phrase_for_locale(75, locale="Japanese") == " 最終出力は1分前です。"
    assert heartbeat_phrase_for_locale(75, locale="en-US") == " Last observed output was 1m ago."


def test_agent_activity_default_targets_use_current_top_level_surfaces() -> None:
    assert target_tab_for_job("run_planned_agent_task_codex") == "Home"
    assert target_tab_for_job("continue_autonomous_session") == "Home"
    assert target_tab_for_job("upload_data_bundle") == "Data"
    assert target_tab_for_job("train_model_candidates") == "Leaderboard"
    assert target_tab_for_job("run_baseline") == "Leaderboard"
    assert target_tab_for_job("register_experiment_results") == "Leaderboard"

    assert target_tab_for_artifact("agent_session_report") == "Insight"
    assert target_tab_for_artifact("analysis_notebook") == "Notebooks"
    assert target_tab_for_artifact("agent_task_contract") == "Home"
    assert target_tab_for_artifact("research_plan") == "Home"


def test_result_readout_targets_use_current_top_level_surfaces() -> None:
    assert normalize_result_readout_target_tab("Overview") == "Home"
    assert normalize_result_readout_target_tab("Approach") == "Home"
    assert normalize_result_readout_target_tab("Experiments") == "Leaderboard"
    assert normalize_result_readout_target_tab("Reports") == "Insight"

    assert gap_target_tab("Runner Results") == "Home"
    assert gap_target_tab("Citations") == "Home"
    assert gap_target_tab("Reports") == "Insight"
    assert gap_target_tab("Experiments") == "Leaderboard"

    top_run = cast(ExperimentRun, SimpleNamespace(id="run_1"))
    assert next_result_action(
        top_run=None,
        evaluation_status="ready",
        experiment_status="missing",
        has_diagnostics=False,
        has_comparison=False,
        decision_report_available=False,
        bundle_next_action={},
    )["target_tab"] == "Leaderboard"
    assert next_result_action(
        top_run=top_run,
        evaluation_status="ready",
        experiment_status="ready",
        has_diagnostics=True,
        has_comparison=True,
        decision_report_available=False,
        bundle_next_action={},
    )["target_tab"] == "Insight"
    legacy_report_tab = "Report" + "s"
    assert next_result_action(
        top_run=top_run,
        evaluation_status="ready",
        experiment_status="ready",
        has_diagnostics=True,
        has_comparison=True,
        decision_report_available=True,
        bundle_next_action={"title": "Read legacy report", "target_tab": legacy_report_tab},
    )["target_tab"] == "Insight"


def test_agent_chat_history_compaction_preserves_user_turns() -> None:
    turns: list[dict[str, Any]] = []
    for index in range(40):
        turns.append(
            {
                "created_at": f"2026-07-03T00:{index:02d}:00",
                "user_message": "",
                "assistant_message": f"progress {index}",
                "intent": {"type": "autonomous_agent_progress_report"},
            }
        )
    turns.append(
        {
            "created_at": "2026-07-03T00:10:30",
            "user_message": "状況を説明してください",
            "assistant_message": "説明します。",
            "intent": {"type": "agent_conversation"},
        }
    )

    compacted = compact_agent_chat_history_turns(turns, max_turns=20, max_autonomous_progress_turns=5)

    progress_turns = [turn for turn in compacted if turn["intent"]["type"] == "autonomous_agent_progress_report"]
    assert len(progress_turns) == 5
    assert any(turn["user_message"] == "状況を説明してください" for turn in compacted)
    assert compacted[-1]["assistant_message"] == "progress 39"


def test_agent_chat_history_compaction_groups_adjacent_notebook_updates() -> None:
    turns = [
        {
            "created_at": "2026-07-03T00:01:00",
            "user_message": "",
            "assistant_message": "分析ノートブックのソースを保存しました。",
            "intent": {"type": "notebook_artifact_update", "status": "source_saved"},
            "actions": [
                {
                    "type": "open_artifact",
                    "label": "ノートブックを開く",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook_1",
                }
            ],
            "response_brief": {"notebook_artifact_id": "art_notebook_1"},
            "artifact_id": "art_chat_1",
        },
        {
            "created_at": "2026-07-03T00:02:00",
            "user_message": "",
            "assistant_message": "分析ノートブックのソースを保存しました。",
            "intent": {"type": "notebook_artifact_update", "status": "source_saved"},
            "actions": [
                {
                    "type": "open_artifact",
                    "label": "ノートブックを開く",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook_2",
                }
            ],
            "response_brief": {"notebook_artifact_id": "art_notebook_2"},
            "artifact_id": "art_chat_2",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    grouped = compacted[0]
    assert grouped["assistant_message"] == "分析ノートブック2件の最新版をここからmarimoで開けます。"
    assert grouped["intent"]["grouped"] is True
    assert grouped["response_brief"]["notebook_artifact_ids"] == ["art_notebook_1", "art_notebook_2"]
    assert [action["artifact_id"] for action in grouped["actions"]] == ["art_notebook_1", "art_notebook_2"]


def test_agent_chat_history_compaction_dedupes_experiment_registration_notices() -> None:
    turns = [
        {
            "created_at": "2026-07-07T09:01:00",
            "user_message": "",
            "assistant_message": "4件のモデル評価をLeaderboardに登録しました。次に必要な登録: モデル診断Notebook。",
            "intent": {"type": "experiment_results_registered", "status": "ready"},
            "actions": [{"type": "open_surface", "label": "リーダーボードを開く", "target_tab": "Leaderboard"}],
            "response_brief": {
                "schema_version": "experiment_results_registered.v1",
                "notification_fingerprint": "same-result-set",
                "run_ids": ["run_a", "run_b", "run_c", "run_d"],
            },
            "artifact_id": "art_chat_old",
        },
        {
            "created_at": "2026-07-07T09:01:30",
            "user_message": "",
            "assistant_message": "別の進捗です。",
            "intent": {"type": "autonomous_agent_progress_report", "status": "ready"},
            "actions": [],
            "response_brief": {"schema_version": "progress.v1"},
            "artifact_id": "art_progress_between",
        },
        {
            "created_at": "2026-07-07T09:02:00",
            "user_message": "",
            "assistant_message": "4件のモデル評価をLeaderboardに登録しました。次に必要な登録: モデル診断Notebook。",
            "intent": {"type": "experiment_results_registered", "status": "ready"},
            "actions": [
                {"type": "open_surface", "label": "リーダーボードを開く", "target_tab": "Leaderboard"},
                {"type": "open_artifact", "label": "根拠アセットを見る", "target_tab": "Assets"},
            ],
            "response_brief": {
                "schema_version": "experiment_results_registered.v1",
                "notification_fingerprint": "same-result-set",
                "run_ids": ["run_a", "run_b", "run_c", "run_d"],
            },
            "artifact_id": "art_chat_latest",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 2
    assert compacted[0]["artifact_id"] == "art_progress_between"
    assert compacted[1]["artifact_id"] == "art_chat_latest"
    assert [action["label"] for action in compacted[1]["actions"]] == ["リーダーボードを開く", "根拠アセットを見る"]


def test_agent_chat_history_compaction_dedupes_identical_progress_reports() -> None:
    repeated_message = (
        "同じセッションを再開し、文脈、目標、直近成果物を確認しました。"
        "現時点で追加できる可逆的分析はありません。"
    )
    turns = [
        {
            "created_at": f"2026-07-07T09:0{index}:00",
            "user_message": "",
            "assistant_message": repeated_message,
            "intent": {"type": "autonomous_agent_progress_report", "status": "ready"},
            "actions": [{"type": "open_surface", "label": "ノートブックを開く", "target_tab": "Notebooks"}],
            "response_brief": {"schema_version": "progress.v1", "source_event_index": index},
            "artifact_id": f"art_progress_{index}",
        }
        for index in range(3)
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    assert compacted[0]["artifact_id"] == "art_progress_2"
    assert compacted[0]["assistant_message"] == repeated_message


def test_agent_chat_history_compaction_dedupes_identical_attention_turns() -> None:
    repeated_message = "モデル評価結果はまだLeaderboardに反映していません。作業は継続中です。"
    turns = [
        {
            "created_at": f"2026-07-07T10:0{index}:00",
            "user_message": "",
            "assistant_message": repeated_message,
            "intent": {"type": "agent_attention_event", "status": "needs_attention", "message_kind": "model_results_pending"},
            "actions": [{"type": "open_surface", "label": "状況を見る", "target_tab": "Home"}],
            "response_brief": {"schema_version": "attention.v1", "source_event_index": index},
            "artifact_id": f"art_attention_{index}",
        }
        for index in range(3)
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    assert compacted[0]["artifact_id"] == "art_attention_2"
    assert compacted[0]["assistant_message"] == repeated_message


def test_agent_chat_history_compaction_replaces_legacy_experiment_registration_state() -> None:
    turns = [
        {
            "created_at": "2026-07-07T09:01:00",
            "user_message": "",
            "assistant_message": "4件のモデル評価をLeaderboardに登録しました。次に必要な登録: モデル診断Notebook。",
            "intent": {"type": "experiment_results_registered", "status": "ready"},
            "actions": [{"type": "open_surface", "label": "リーダーボードを開く", "target_tab": "Leaderboard"}],
            "response_brief": {
                "schema_version": "experiment_results_registered.v1",
                "run_ids": ["run_a", "run_b", "run_c", "run_d"],
                "pipeline_registration": {"status": "missing", "missing_count": 4},
                "model_diagnostics_artifacts": {"status": "missing", "missing_count": 4},
                "model_diagnostics_notebook": {"status": "missing", "missing_count": 4},
            },
            "artifact_id": "art_chat_missing",
        },
        {
            "created_at": "2026-07-07T09:02:00",
            "user_message": "",
            "assistant_message": "4件のモデル評価をLeaderboardに登録しました。この結果セットは現在開けます。",
            "intent": {"type": "experiment_results_registered", "status": "ready"},
            "actions": [{"type": "open_surface", "label": "リーダーボードを開く", "target_tab": "Leaderboard"}],
            "response_brief": {
                "schema_version": "experiment_results_registered.v1",
                "run_ids": ["run_a", "run_b", "run_c", "run_d"],
                "pipeline_registration": {"status": "ready", "missing_count": 0},
                "model_diagnostics_artifacts": {"status": "registered", "missing_count": 0},
                "model_diagnostics_notebook": {"status": "ready", "missing_count": 0},
            },
            "artifact_id": "art_chat_ready",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    assert compacted[0]["artifact_id"] == "art_chat_ready"
    assert "次に必要な登録" not in compacted[0]["assistant_message"]


def test_agent_chat_history_compaction_dedupes_experiment_registration_failures() -> None:
    turns = [
        {
            "created_at": "2026-07-07T09:01:00",
            "user_message": "",
            "assistant_message": "モデル評価結果はまだLeaderboardに反映していません。",
            "intent": {"type": "experiment_results_registration_failed", "status": "needs_attention"},
            "actions": [{"type": "open_surface", "label": "状況を見る", "target_tab": "Home"}],
            "response_brief": {
                "schema_version": "experiment_results_registration_failed.v1",
                "operation": "auto_register_model_results.v1",
                "error_type": "ValueError",
                "error_message": "payload.runs must contain at least one run",
            },
            "artifact_id": "art_failure_old",
        },
        {
            "created_at": "2026-07-07T09:02:00",
            "user_message": "",
            "assistant_message": "モデル評価結果はまだLeaderboardに反映していません。",
            "intent": {"type": "experiment_results_registration_failed", "status": "needs_attention"},
            "actions": [{"type": "open_surface", "label": "状況を見る", "target_tab": "Home"}],
            "response_brief": {
                "schema_version": "experiment_results_registration_failed.v1",
                "operation": "auto_register_model_results.v1",
                "error_type": "ValueError",
                "error_message": "payload.runs must contain at least one run",
            },
            "artifact_id": "art_failure_latest",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    assert compacted[0]["artifact_id"] == "art_failure_latest"


def test_agent_chat_history_compaction_groups_notebook_versions_by_latest(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        user = User(id="local-user", email="local-user@example.com")
        project = Project(id="p_notebook_version_compaction", name="Notebook Version Compaction", created_by=user.id)
        db.add_all([user, project])
        db.commit()
        older = Artifact(
            id="art_notebook_v1",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="agent_session_notebooks_grandmaster_eda",
            version=1,
            uri=str(tmp_path),
            content_hash="hash1",
            size_bytes=12,
            metadata_json="{}",
            created_by=user.id,
        )
        latest = Artifact(
            id="art_notebook_v2",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="agent_session_notebooks_grandmaster_eda",
            version=2,
            uri=str(tmp_path),
            content_hash="hash2",
            size_bytes=12,
            metadata_json="{}",
            created_by=user.id,
        )
        db.add_all([older, latest])
        db.commit()

        turns = [
            {
                "created_at": "2026-07-03T00:01:00",
                "user_message": "",
                "assistant_message": "分析ノートブックのソースを保存しました。",
                "intent": {"type": "notebook_artifact_update", "status": "source_saved"},
                "actions": [{"type": "open_artifact", "label": "ノートブックを開く", "artifact_id": older.id}],
                "response_brief": {"notebook_artifact_id": older.id},
                "artifact_id": "art_chat_v1",
            },
            {
                "created_at": "2026-07-03T00:02:00",
                "user_message": "",
                "assistant_message": "分析ノートブックのソースを保存しました。",
                "intent": {"type": "notebook_artifact_update", "status": "source_saved"},
                "actions": [{"type": "open_artifact", "label": "ノートブックを開く", "artifact_id": latest.id}],
                "response_brief": {"notebook_artifact_id": latest.id},
                "artifact_id": "art_chat_v2",
            },
        ]

        compacted = compact_agent_chat_history_turns(turns, locale="ja-JP", db=db, project_id=project.id)

        assert len(compacted) == 1
        grouped = compacted[0]
        assert grouped["assistant_message"] == "分析ノートブックを更新しました。最新版をここからmarimoで開けます。"
        assert grouped["response_brief"]["notebook_artifact_ids"] == [latest.id]
        assert [action["artifact_id"] for action in grouped["actions"]] == [latest.id]


def test_agent_chat_history_compaction_keeps_latest_notebook_action_status() -> None:
    turns = [
        {
            "created_at": "2026-07-03T00:01:00",
            "user_message": "",
            "assistant_message": "分析ノートブックのソースは保存しましたが、修正対象です。",
            "intent": {"type": "notebook_artifact_update", "status": "quality_needs_attention"},
            "actions": [
                {
                    "type": "open_artifact",
                    "status": "needs_attention",
                    "label": "ノートブックを確認",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook",
                }
            ],
            "response_brief": {"notebook_artifact_id": "art_notebook"},
            "artifact_id": "art_chat_1",
        },
        {
            "created_at": "2026-07-03T00:02:00",
            "user_message": "",
            "assistant_message": "分析ノートブックを保存しました。",
            "intent": {"type": "notebook_artifact_update", "status": "source_saved"},
            "actions": [
                {
                    "type": "open_artifact",
                    "status": "ready",
                    "label": "ノートブックを開く",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook",
                }
            ],
            "response_brief": {"notebook_artifact_id": "art_notebook"},
            "artifact_id": "art_chat_2",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    grouped = compacted[0]
    assert grouped["assistant_message"] == "分析ノートブックを更新しました。最新版をここからmarimoで開けます。"
    assert grouped["actions"][0]["status"] == "ready"
    assert grouped["actions"][0]["label"] == "ノートブックを開く"


def test_agent_chat_history_compaction_groups_adjacent_marimo_runtime_failures() -> None:
    turns = [
        {
            "created_at": "2026-07-03T00:01:00",
            "user_message": "",
            "assistant_message": "Notebook runtime error. First long detail.",
            "intent": {"type": "native_marimo_runtime_failed", "status": "needs_attention"},
            "actions": [
                {
                    "type": "open_artifact",
                    "label": "Notebookを修正対象として開く",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook_runtime",
                }
            ],
            "response_brief": {
                "schema_version": "native_marimo_runtime_failed.v1",
                "notebook_artifact_id": "art_notebook_runtime",
                "error_summary": "Traceback\n...\nValueError: first",
            },
            "artifact_id": "art_chat_runtime_1",
        },
        {
            "created_at": "2026-07-03T00:02:00",
            "user_message": "",
            "assistant_message": "Notebook runtime error. Second long detail.",
            "intent": {"type": "native_marimo_runtime_failed", "status": "needs_attention"},
            "actions": [
                {
                    "type": "open_artifact",
                    "label": "Notebookを修正対象として開く",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": "art_notebook_runtime",
                }
            ],
            "response_brief": {
                "schema_version": "native_marimo_runtime_failed.v1",
                "notebook_artifact_id": "art_notebook_runtime",
                "error_summary": "Traceback\n...\nNameError: second",
            },
            "artifact_id": "art_chat_runtime_2",
        },
    ]

    compacted = compact_agent_chat_history_turns(turns, locale="ja-JP")

    assert len(compacted) == 1
    grouped = compacted[0]
    assert grouped["intent"]["type"] == "native_marimo_runtime_failed"
    assert grouped["intent"]["grouped"] is True
    assert "同じNotebookでruntime error" in grouped["assistant_message"]
    assert "NameError: second" in grouped["assistant_message"]
    assert "ValueError: first" not in grouped["assistant_message"]
    assert grouped["response_brief"]["notebook_artifact_ids"] == ["art_notebook_runtime"]
    assert [action["artifact_id"] for action in grouped["actions"]] == ["art_notebook_runtime"]


def test_project_autonomy_mode_persists(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Mission Control"})
    assert project_response.status_code == 200
    project = project_response.json()
    assert project["autonomy_mode"] == "approval_based"

    update_response = client.patch(f"/api/projects/{project['id']}", json={"autonomy_mode": "full_auto"})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["autonomy_mode"] == "full_auto"

    read_response = client.get(f"/api/projects/{project['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["autonomy_mode"] == "full_auto"


def test_delete_project_removes_project_scoped_records(tmp_path: Path, monkeypatch: Any) -> None:
    stopped_projects: list[str] = []
    cleanup_requests: list[dict[str, str]] = []

    def fake_schedule_project_artifact_cleanup(settings: Any, *, org_id: str, project_id: str) -> dict[str, Any]:
        del settings
        cleanup_requests.append({"org_id": org_id, "project_id": project_id})
        return {"status": "scheduled", "target_count": 3}

    monkeypatch.setattr(
        "tabular_harness.api.routes.stop_native_marimo_sessions_for_project",
        lambda project_id: stopped_projects.append(project_id) or 2,
    )
    monkeypatch.setattr(
        "tabular_harness.api.routes.schedule_project_artifact_cleanup",
        fake_schedule_project_artifact_cleanup,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Temporary UI check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert refs_response.status_code == 200
    assert refs_response.json()

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_delete_project",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Delete regression context.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="thread.started",
            role="assistant",
            title="Thread started",
            content="Existing transcript row should not prevent project deletion.",
        )
        db.commit()

    delete_response = client.delete(f"/api/projects/{project_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["stopped_marimo_sessions"] == 2
    assert delete_response.json()["artifact_cleanup"] == {"status": "scheduled", "target_count": 3}
    assert stopped_projects == [project_id]
    assert cleanup_requests == [{"org_id": "local-org", "project_id": project_id}]

    assert client.get(f"/api/projects/{project_id}").status_code == 404
    projects = client.get("/api/projects").json()
    assert project_id not in {project["id"] for project in projects}

    with app.state.session_factory() as db:
        assert db.get(Project, project_id) is None
        assert not db.scalars(select(AssetReference).where(AssetReference.source_id == project_id)).all()


def test_delete_project_removes_evaluation_experiment_dependencies(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("tabular_harness.api.routes.stop_native_marimo_sessions_for_project", lambda project_id: 0)
    monkeypatch.setattr(
        "tabular_harness.api.routes.schedule_project_artifact_cleanup",
        lambda settings, *, org_id, project_id: {"status": "scheduled", "target_count": 0},
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Delete evaluation dependencies"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        dataset_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="dataset",
            name="delete_eval_dataset",
            filename="dataset.json",
            payload={"rows": 2},
            metadata={},
        )
        split_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="split_manifest",
            name="delete_eval_split",
            filename="split.json",
            payload={"train": [0], "valid": [1]},
            metadata={},
        )
        model_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="model_package",
            name="delete_eval_model",
            filename="model.json",
            payload={"model": "stub"},
            metadata={},
        )
        brief_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_brief",
            name="delete_eval_brief",
            filename="brief.json",
            payload={"brief": True},
            metadata={},
        )
        idea_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="idea",
            name="delete_eval_idea",
            filename="idea.json",
            payload={"idea": True},
            metadata={},
        )
        dataset = DatasetSnapshot(
            id="ds_delete_eval",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=2,
            column_count=2,
            schema_hash="schema",
            data_hash="data",
        )
        candidate = EvaluationCandidate(
            id="evc_delete_eval",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            name="candidate",
            split_type="random_split",
            primary_metric="mae",
            rationale_md="Candidate.",
            confidence=0.7,
            risk_level="medium",
            status="primary",
        )
        spec = EvaluationSpec(
            id="evs_delete_eval",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            source_evaluation_candidate_id=candidate.id,
            name="spec",
            split_type="random_split",
            primary_metric="mae",
            rationale_md="Spec.",
            risk_level="medium",
            status="approved",
        )
        split = SplitManifest(
            id="split_delete_eval",
            project_id=project_id,
            evaluation_spec_id=spec.id,
            artifact_id=split_artifact.id,
            train_count=1,
            valid_count=1,
            summary_json="{}",
        )
        run = ExperimentRun(
            id="run_delete_eval",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            evaluation_spec_id=spec.id,
            evaluation_candidate_id=candidate.id,
            split_manifest_id=split.id,
            runner_type="local",
            status="succeeded",
            metrics_json='{"mae": 1.0}',
        )
        brief = ResearchBrief(
            id="rb_delete_eval",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            evaluation_spec_id=spec.id,
            title="Brief",
            question="What should be tried?",
            summary_md="Summary.",
            artifact_id=brief_artifact.id,
            status="ready",
        )
        idea = Idea(
            id="idea_delete_eval",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            evaluation_spec_id=spec.id,
            research_brief_id=brief.id,
            title="Idea",
            hypothesis="Try something.",
            approach_type="baseline",
            rationale_md="Rationale.",
            artifact_id=idea_artifact.id,
            status="proposed",
        )
        db.add(dataset)
        db.flush()
        db.add(candidate)
        db.flush()
        db.add(spec)
        db.flush()
        db.add(split)
        db.flush()
        db.add(run)
        db.flush()
        model = ModelVersion(
            id="mv_delete_eval",
            project_id=project_id,
            experiment_run_id=run.id,
            dataset_snapshot_id=dataset.id,
            evaluation_spec_id=spec.id,
            split_manifest_id=split.id,
            artifact_id=model_artifact.id,
            name="model",
            version=1,
            model_family="stub",
            model_type="regressor",
            task_type="regression",
            status="created",
        )
        db.add(model)
        db.flush()
        run.model_version_id = model.id
        db.add(brief)
        db.flush()
        db.add(idea)
        db.commit()

    delete_response = client.delete(f"/api/projects/{project_id}")
    assert delete_response.status_code == 200, delete_response.text

    with app.state.session_factory() as db:
        assert db.get(Project, project_id) is None
        for model in (Idea, ResearchBrief, ModelVersion, ExperimentRun, SplitManifest, EvaluationSpec, EvaluationCandidate):
            assert not db.scalars(select(model).where(model.project_id == project_id)).all()


def test_sqlite_project_delete_indexes_are_created(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    inspector = inspect(app.state.engine)

    indexes_by_table = {
        table_name: {index["name"] for index in inspector.get_indexes(table_name)}
        for table_name in [
            "agent_transcript_events",
            "asset_references",
            "asset_versions",
            "dataset_snapshots",
            "evidence",
            "reports",
            "semantic_catalogs",
            "model_versions",
            "visualization_specs",
        ]
    }

    assert "ix_agent_transcript_events_artifact" in indexes_by_table["agent_transcript_events"]
    assert "ix_agent_transcript_events_job" in indexes_by_table["agent_transcript_events"]
    assert "ix_asset_references_target_asset_version" in indexes_by_table["asset_references"]
    assert "ix_asset_versions_artifact" in indexes_by_table["asset_versions"]
    assert "ix_dataset_snapshots_artifact" in indexes_by_table["dataset_snapshots"]
    assert "ix_evidence_source_artifact" in indexes_by_table["evidence"]
    assert "ix_reports_artifact" in indexes_by_table["reports"]
    assert "ix_semantic_catalogs_artifact" in indexes_by_table["semantic_catalogs"]
    assert "ix_model_versions_artifact" in indexes_by_table["model_versions"]
    assert "ix_visualization_specs_source_artifact" in indexes_by_table["visualization_specs"]


def test_dataset_upload_records_harness_research_plan_progress(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Upload plan progress"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("training.csv", b"feature,target\n1,0\n2,1\n3,0\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    uploaded_artifact_id = upload_response.json()["artifact"]["id"]

    timeline_response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    blocks = {block["id"]: block for block in timeline["blocks"]}
    assert blocks["data_upload"]["status"] == "done"
    assert blocks["objective_framing"]["status"] == "active"
    assert timeline["contract_validation"]["status"] == "ok"
    assert any(link["artifact_id"] == uploaded_artifact_id for link in blocks["data_upload"]["attached_artifacts"])


def test_project_artifacts_support_limit_and_asset_type_filters(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Artifact filters"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        for index in range(5):
            store_json_artifact(
                db,
                app.state.artifact_store,
                project_id=project_id,
                asset_type="agent_session_report" if index % 2 else "analysis_notebook",
                name=f"artifact_filter_{index}",
                filename="artifact.json",
                payload={"index": index},
                metadata={"index": index},
            )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="versioned_report",
            filename="artifact.json",
            payload={"version": 1},
            metadata={"version": 1},
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="versioned_report",
            filename="artifact.json",
            payload={"version": 2},
            metadata={"version": 2},
        )
        db.commit()

    limited_response = client.get(f"/api/projects/{project_id}/artifacts?limit=2")
    assert limited_response.status_code == 200
    assert len(limited_response.json()) == 2

    filtered_response = client.get(f"/api/projects/{project_id}/artifacts?asset_type=analysis_notebook")
    assert filtered_response.status_code == 200
    assert {item["asset_type"] for item in filtered_response.json()} == {"analysis_notebook"}

    latest_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert latest_response.status_code == 200
    latest_versioned = [item for item in latest_response.json() if item["name"] == "versioned_report"]
    assert len(latest_versioned) == 1
    assert latest_versioned[0]["version"] == 2

    all_versions_response = client.get(f"/api/projects/{project_id}/artifacts?latest_only=false")
    assert all_versions_response.status_code == 200
    all_versioned = [item for item in all_versions_response.json() if item["name"] == "versioned_report"]
    assert [item["version"] for item in all_versioned] == [2, 1]

    overview_response = client.get(f"/api/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview_counts = overview_response.json()["counts"]
    assert overview_counts["artifacts"] == 6
    assert overview_counts["artifact_versions"] == 7


def test_project_artifacts_include_surface_roles_for_assets_ui(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Artifact surface roles"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        report = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="human_report",
            filename="report.json",
            payload={"status": "ready"},
            metadata={},
        )
        notebook = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="native_marimo_source",
            filename="notebook.py",
            payload={"source": "import marimo"},
            metadata={},
        )
        chat_turn = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="chat_turn_record",
            filename="agent_chat_turn.json",
            payload={"schema_version": "agent_chat_turn.v1"},
            metadata={},
        )
        static_html = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="notebook_html",
            name="legacy_static_notebook_snapshot",
            filename="notebook.html",
            payload={"html": "<html></html>"},
            metadata={},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/artifacts?latest_only=false")
    assert response.status_code == 200
    roles_by_id = {item["id"]: item["surface_role"] for item in response.json()}
    assert roles_by_id[report.id] == "primary"
    assert roles_by_id[notebook.id] == "notebook"
    assert roles_by_id[chat_turn.id] == "supporting"
    assert static_html.id not in roles_by_id

    direct_static_response = client.get(f"/api/artifacts/{static_html.id}")
    assert direct_static_response.status_code == 400
    assert "Static HTML notebook snapshots are not Tablex artifacts" in direct_static_response.text
    static_download_response = client.get(f"/api/artifacts/{static_html.id}/download")
    assert static_download_response.status_code == 400
    assert "Static HTML notebook snapshots are not Tablex artifacts" in static_download_response.text


def test_autonomy_mode_change_is_persisted_in_agent_chat_history(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Mode history"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    update_response = client.patch(
        f"/api/projects/{project_id}",
        json={"autonomy_mode": "full_auto", "locale": "Japanese"},
    )
    assert update_response.status_code == 200, update_response.text

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[-1]["intent"]["type"] == "autonomy_mode_change"
    assert history[-1]["user_message"] == "フルオート"
    assert "フルオートに切り替えました" in history[-1]["assistant_message"]

    update_response = client.patch(
        f"/api/projects/{project_id}",
        json={"autonomy_mode": "approval_based", "locale": "日本語"},
    )
    assert update_response.status_code == 200, update_response.text

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[-1]["intent"]["type"] == "autonomy_mode_change"
    assert history[-1]["user_message"] == "承認ベース"
    assert "承認ベースに切り替えました" in history[-1]["assistant_message"]


def test_health_aliases_are_public_when_auth_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        auth_enabled=True,
    )
    client = TestClient(create_app(settings))

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/projects").status_code == 401


def test_admin_storage_usage_api_returns_categories(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/admin/storage/usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "storage_usage.v1"
    assert set(payload["categories"]) == {"datasets", "artifacts", "workspaces", "pipeline_envs", "marimo", "db"}


def test_admin_storage_gc_api_registers_dry_run_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/api/admin/storage/gc")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "artifact_gc_plan.v1"
    assert payload["dry_run"] is True
    assert isinstance(payload["report_artifact_id"], str)


def test_artifact_preview_includes_one_hop_lineage(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = Project(id="p_preview_lineage", name="Preview lineage")
        db.add(project)
        db.flush()
        source = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="source_data",
            filename="source.txt",
            text="source",
            metadata={},
        )
        target = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="model_diagnostics_artifact_report",
            name="target_report",
            filename="report.md",
            text="# report\n",
            metadata={},
        )
        output = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="decision_report",
            name="output_report",
            filename="decision.md",
            text="# decision\n",
            metadata={},
        )
        db.add_all(
            [
                LineageEdge(
                    id="lin_preview_input",
                    project_id=project.id,
                    from_asset_type="artifact",
                    from_asset_id=source.id,
                    to_asset_type="artifact",
                    to_asset_id=target.id,
                    relation_type="derived_from",
                    metadata_json="{}",
                ),
                LineageEdge(
                    id="lin_preview_output",
                    project_id=project.id,
                    from_asset_type="artifact",
                    from_asset_id=target.id,
                    to_asset_type="artifact",
                    to_asset_id=output.id,
                    relation_type="supports",
                    metadata_json="{}",
                ),
            ]
        )
        db.commit()
        source_id = source.id
        target_id = target.id
        output_id = output.id

    response = client.get(f"/api/artifacts/{target_id}/preview")

    assert response.status_code == 200
    lineage = response.json()["lineage"]
    assert lineage["inputs"][0]["asset_id"] == source_id
    assert lineage["inputs"][0]["label"] == "source_data"
    assert lineage["outputs"][0]["asset_id"] == output_id
    assert lineage["outputs"][0]["endpoint_asset_type"] == "decision_report"


def model_diagnostics_quality_manifest() -> dict[str, Any]:
    return {
        "schema_version": "tablex_notebook_quality_manifest.v1",
        "figure_count": 3,
        "table_count": 1,
        "key_findings": ["Diagnostics notebook registered for the model run."],
        "read_order": [{"label": "diagnostics"}],
        "data_sources_used": ["leaderboard run"],
        "limitations": ["Synthetic test notebook."],
        "model_diagnostics": {
            "schema_version": "tablex_model_diagnostics_manifest.v1",
            "checks": [
                {"name": "permutation_importance", "status": "included", "evidence": ["test"]},
                {"name": "native_feature_importance", "status": "included", "evidence": ["test"]},
                {"name": "partial_dependence", "status": "included", "evidence": ["test"]},
                {"name": "shap", "status": "included", "evidence": ["test"]},
            ],
        },
    }


def test_deliverable_expectation_flow_from_runs_to_model_notebook(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace"
    experiments_dir = workspace / ".tablex" / "requests" / "experiments"
    experiments_dir.mkdir(parents=True)
    request_path = experiments_dir / "register_runs_001.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "register_runs_001",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "fold_safe_baseline",
                            "model_description": "Fold-safe baseline.",
                            "features_used": ["x"],
                            "primary_metric_name": "roc_auc",
                            "metrics": {"roc_auc": 0.7},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with app.state.session_factory() as db:
        project = Project(id="p_deliverable_flow", name="Deliverable flow")
        db.add(project)
        db.flush()
        session = AgentSession(
            id="ags_deliverable_flow",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Register runs and notebook.",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.flush()

        runs = process_experiment_result_requests(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
            append_event=append_session_event,
        )
        assert len(runs) == 1
        run_id = runs[0].id
        expectation = db.scalar(
            select(DeliverableExpectation).where(
                DeliverableExpectation.project_id == project.id,
                DeliverableExpectation.kind == "model_diagnostics_notebook",
                DeliverableExpectation.subject_ref == f"experiment_run:{run_id}",
            )
        )
        assert expectation is not None
        assert expectation.status == "open"

        notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="model_diagnostics_notebook",
            filename="model_diagnostics.py",
            text=(
                "import marimo\n\n"
                "app = marimo.App()\n\n"
                "@app.cell\n"
                "def _():\n"
                "    import matplotlib.pyplot as plt\n"
                "    _fig, _ax = plt.subplots()\n"
                "    _ax.bar([1, 2], [3, 4])\n"
                "    return _fig,\n"
            ),
            metadata={"project_id": project.id},
        )
        execute_notebook_registration_request(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
            payload={
                "artifact_id": notebook.id,
                "notebook_kind": "model_diagnostics",
                "run_id": run_id,
                "quality_manifest": model_diagnostics_quality_manifest(),
            },
        )

        db.refresh(expectation)
        assert expectation.status == "fulfilled"
        assert expectation.fulfilled_by_artifact_id == notebook.id
        db.commit()

    leaderboard_response = client.get("/api/projects/p_deliverable_flow/leaderboard")
    assert leaderboard_response.status_code == 200
    row = leaderboard_response.json()[0]
    assert row["deliverable_expectations"][0]["status"] == "fulfilled"
    assert row["deliverable_expectations"][0]["fulfilled_by_artifact_id"] == notebook.id


def test_pipeline_bundle_fulfills_deliverable_expectation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = Project(id="p_pipeline_deliverable", name="Pipeline deliverable")
        db.add(project)
        db.flush()
        run = ExperimentRun(
            id="run_pipeline_deliverable",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps(
                {
                    "model_id": "pipeline_model",
                    "model_description": "Pipeline model.",
                    "features_used": ["x"],
                }
            ),
            metrics_json=json.dumps({"primary_metric_name": "roc_auc", "primary_metric_value": 0.71}),
        )
        pipeline = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="pipeline_deliverable_bundle",
            filename="pipeline.zip",
            text="pipeline",
            metadata={"experiment_run_ids": [run.id]},
        )
        db.add(run)
        db.flush()

        expectations = fulfill_run_pipeline_bundle_expectations(
            db,
            project=project,
            run_ids=[run.id],
            pipeline_artifact_id=pipeline.id,
        )
        db.commit()

    assert len(expectations) == 1
    assert expectations[0].kind == "pipeline_bundle"
    assert expectations[0].status == "fulfilled"
    assert expectations[0].fulfilled_by_artifact_id == pipeline.id


def test_waive_deliverable_requires_rationale_and_updates_expectation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace"
    request_dir = workspace / ".tablex" / "requests" / "deliverables"
    request_dir.mkdir(parents=True)

    with app.state.session_factory() as db:
        project = Project(id="p_deliverable_waive", name="Deliverable waive")
        db.add(project)
        db.flush()
        session = AgentSession(
            id="ags_deliverable_waive",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Waive deliverable.",
            workspace_path=str(workspace),
        )
        expectation = DeliverableExpectation(
            id="deliv_waive_target",
            project_id=project.id,
            kind="model_diagnostics_notebook",
            subject_ref="experiment_run:run_missing_notebook",
            status="open",
            created_from="test",
        )
        db.add_all([session, expectation])
        db.flush()

        (request_dir / "missing_rationale.json").write_text(
            json.dumps(
                {
                    "schema_version": "tablex_deliverable_request.v1",
                    "request_id": "missing_rationale",
                    "operation": "waive_deliverable",
                    "payload": {"expectation_id": expectation.id},
                }
            ),
            encoding="utf-8",
        )
        process_deliverable_tool_requests(
            db,
            project=project,
            session=session,
            workspace=workspace,
            append_session_event_fn=append_session_event,
        )
        failed_ack = json.loads(
            (workspace / ".tablex" / "acks" / "deliverables" / "missing_rationale.ack.json").read_text(
                encoding="utf-8"
            )
        )
        assert failed_ack["status"] == "failed"
        assert "rationale" in failed_ack["error"]["message"]
        db.refresh(expectation)
        assert expectation.status == "open"

        (request_dir / "waive_ok.json").write_text(
            json.dumps(
                {
                    "schema_version": "tablex_deliverable_request.v1",
                    "request_id": "waive_ok",
                    "operation": "waive_deliverable",
                    "payload": {
                        "expectation_id": expectation.id,
                        "rationale": "A diagnostics notebook is not applicable for this synthetic run.",
                    },
                }
            ),
            encoding="utf-8",
        )
        process_deliverable_tool_requests(
            db,
            project=project,
            session=session,
            workspace=workspace,
            append_session_event_fn=append_session_event,
        )
        succeeded_ack = json.loads(
            (workspace / ".tablex" / "acks" / "deliverables" / "waive_ok.ack.json").read_text(
                encoding="utf-8"
            )
        )
        assert succeeded_ack["status"] == "succeeded"
        db.refresh(expectation)
        assert expectation.status == "waived"
        assert expectation.waived_rationale == "A diagnostics notebook is not applicable for this synthetic run."
        db.commit()


def test_open_deliverable_expectation_observation_is_sent_once(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace"
    (workspace / ".tablex" / "inbox").mkdir(parents=True)
    observed_at = utc_now()
    with app.state.session_factory() as db:
        project = Project(id="p_deliverable_observation", name="Deliverable observation")
        db.add(project)
        db.flush()
        session = AgentSession(
            id="ags_deliverable_observation",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Observe deliverables.",
            workspace_path=str(workspace),
        )
        expectation = DeliverableExpectation(
            id="deliv_observation_target",
            project_id=project.id,
            kind="model_diagnostics_notebook",
            subject_ref="experiment_run:run_waiting_for_notebook",
            status="open",
            created_from="test",
            created_at=observed_at - timedelta(minutes=31),
            updated_at=observed_at - timedelta(minutes=31),
        )
        db.add_all([session, expectation])
        db.flush()

        first = maybe_write_open_deliverable_expectation_observation(
            db,
            project=project,
            session=session,
            workspace=workspace,
            now=observed_at,
        )
        second = maybe_write_open_deliverable_expectation_observation(
            db,
            project=project,
            session=session,
            workspace=workspace,
            now=observed_at + timedelta(minutes=5),
        )
        db.refresh(expectation)
        db.commit()

    inbox_entries = list_inbox_entries(workspace)
    deliverable_entries = [
        item for item in inbox_entries if item.get("type") == "deliverable_expectations_open"
    ]
    assert len(first) == 1
    assert second == []
    assert expectation.notification_sent_at is not None
    assert expectation.notification_sent_at.replace(tzinfo=timezone.utc) == observed_at
    assert len(deliverable_entries) == 1
    assert deliverable_entries[0]["payload"]["open_expectations"][0]["id"] == "deliv_observation_target"


def test_password_auth_protects_api_and_persists_user_settings(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        auth_enabled=True,
    )
    client = TestClient(create_app(settings))

    status_response = client.get("/api/auth/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["auth_enabled"] is True
    assert status["authenticated"] is False
    assert status["bootstrap_required"] is True

    protected_response = client.get("/api/projects")
    assert protected_response.status_code == 401

    weak_password_response = client.post(
        "/api/auth/bootstrap",
        json={"email": "weak@example.com", "password": "lowercaseonly", "display_name": "Weak"},
    )
    assert weak_password_response.status_code == 400
    assert "uppercase" in weak_password_response.json()["detail"]

    bootstrap_response = client.post(
        "/api/auth/bootstrap",
        json={
            "email": "owner@example.com",
            "password": "CorrectHorse1!",
            "display_name": "Owner",
        },
    )
    assert bootstrap_response.status_code == 200, bootstrap_response.text
    assert bootstrap_response.json()["authenticated"] is True
    assert bootstrap_response.json()["user"]["is_admin"] is True
    owner_user_id = bootstrap_response.json()["user"]["id"]

    project_response = client.post("/api/projects", json={"name": "Authed project"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    assert project_response.json()["created_by"] == owner_user_id

    project_refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert project_refs_response.status_code == 200
    equipped_skill_names = {
        reference["asset"]["name"]
        for reference in project_refs_response.json()
        if reference["asset"] and reference["relation_type"] == "equipped_for_agent_context"
    }
    assert "tablex_grandmaster_eda" in equipped_skill_names

    settings_response = client.patch(
        "/api/auth/me/settings",
        json={
            "settings": {
                "locale": "ja-JP",
                "displayTheme": "dark",
                "userAvatarDataUrl": "data:image/svg+xml;base64,PHN2Zy8+",
                "agentModel": "gpt-5.5-xhigh",
                "utilityModel": "gpt-5-mini",
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text
    saved_settings = settings_response.json()["settings"]
    assert saved_settings["locale"] == "ja-JP"
    assert saved_settings["displayTheme"] == "dark"
    assert saved_settings["userAvatarDataUrl"].startswith("data:image/")

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/projects").status_code == 401

    bad_login_response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "wrong password"},
    )
    assert bad_login_response.status_code == 401

    login_response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "CorrectHorse1!"},
    )
    assert login_response.status_code == 200, login_response.text
    assert login_response.json()["user"]["settings"]["locale"] == "ja-JP"
    assert client.get("/api/projects").status_code == 200


def test_full_auto_start_creates_main_agent_session_without_dataset_even_with_legacy_runner_mode(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Autonomous no data"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    start_response = client.post(f"/api/projects/{project_id}/autonomy/start", json={"runner_mode": "harness_only"})
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["job_type"] == "start_autonomous_loop"
    assert queued_job["status"] == "succeeded"
    assert queued_job["input"]["runner_mode"] == "codex_cli_if_available"
    assert queued_job["input"]["requested_runner_mode"] == "harness_only"
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    assert queued_job["output"]["agent_session_id"]

    job_response = client.get(f"/api/jobs/{queued_job['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "succeeded"
    assert job["output"]["schema_version"] == "agent_session_start.v1"
    assert "Full Auto" in job["output"]["assistant_message"]
    assert job["output"]["worker_events"]

    session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["id"] == queued_job["output"]["agent_session_id"]
    assert session["session_type"] == "main_autonomous"

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    assert project_read_response.json()["autonomy_mode"] == "full_auto"
    assert project_read_response.json()["current_phase"] == "AUTONOMOUS_LOOP"

    stop_response = client.post(f"/api/projects/{project_id}/autonomy/stop")
    assert stop_response.status_code == 200, stop_response.text
    stop_job = stop_response.json()
    assert stop_job["job_type"] == "stop_autonomous_loop"
    assert stop_job["status"] == "succeeded"
    assert stop_job["output"]["schema_version"] == "autonomous_loop_stop.v1"
    assert stop_job["output"]["worker_events"][0]["status"] == "cancelled"

    stopped_project_response = client.get(f"/api/projects/{project_id}")
    assert stopped_project_response.status_code == 200
    assert stopped_project_response.json()["autonomy_mode"] == "full_auto"
    assert stopped_project_response.json()["current_phase"] == "IDLE"

    restart_response = client.post(f"/api/projects/{project_id}/autonomy/start", json={"runner_mode": "harness_only"})
    assert restart_response.status_code == 200, restart_response.text
    restart_job = restart_response.json()
    assert restart_job["output"]["schema_version"] == "agent_session_start.v1"
    assert restart_job["output"]["agent_session_id"] == queued_job["output"]["agent_session_id"]
    assert restart_job["output"]["status"] == "resumed"
    assert "resumed" in restart_job["output"]["assistant_message"]

    restarted_session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert restarted_session_response.status_code == 200
    restarted_session = restarted_session_response.json()
    assert restarted_session["id"] == queued_job["output"]["agent_session_id"]
    assert restarted_session["status"] in {"between_turns", "running", "starting"}

    transcript_response = client.get(f"/api/projects/{project_id}/agent-session/transcript")
    assert transcript_response.status_code == 200
    transcript_event_types = [event["event_type"] for event in transcript_response.json()]
    assert "session_resumed_after_power_on" in transcript_event_types


def test_autonomy_stop_cancels_project_work_without_old_job_type_allowlist(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Stop cancels all active work"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    other_response = client.post("/api/projects", json={"name": "Other project"})
    assert other_response.status_code == 200
    other_project_id = other_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        queued_report = create_job(db, job_type="generate_decision_report", project_id=project_id)
        waiting_chat = create_job(db, job_type="agent_chat_turn", project_id=project_id)
        waiting_chat.status = "waiting_for_agent"
        approval_job = create_job(db, job_type="review_evaluation_approval", project_id=project_id)
        approval_job.status = "approval_required"
        running_training = create_job(db, job_type="train_model_candidates", project_id=project_id)
        mark_job_running(running_training)
        upload_job = create_job(db, job_type="upload_data_bundle", project_id=project_id)
        other_project_job = create_job(db, job_type="generate_decision_report", project_id=other_project_id)
        db.commit()
        cancellable_ids = {queued_report.id, waiting_chat.id, approval_job.id, running_training.id}
        upload_job_id = upload_job.id
        other_project_job_id = other_project_job.id

    stop_response = client.post(f"/api/projects/{project_id}/autonomy/stop")
    assert stop_response.status_code == 200, stop_response.text
    output = stop_response.json()["output"]
    assert set(output["cancelled_job_ids"]) == cancellable_ids

    with app.state.session_factory() as db:
        cancelled_statuses = {db.get(Job, job_id).status for job_id in cancellable_ids}  # type: ignore[union-attr]
        assert cancelled_statuses == {"cancelled"}
        assert db.get(Job, upload_job_id).status == "queued"  # type: ignore[union-attr]
        assert db.get(Job, other_project_job_id).status == "queued"  # type: ignore[union-attr]


def test_autonomy_stop_terminates_observed_project_codex_processes(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Stop child process cleanup"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        running_child = create_job(db, job_type="run_planned_agent_task_codex", project_id=project_id)
        mark_job_running(running_child)
        db.commit()

    observed_calls: list[str] = []
    terminated_pids: list[int] = []

    def fake_running_codex_processes_for_project(requested_project_id: str) -> list[dict[str, Any]]:
        observed_calls.append(requested_project_id)
        assert requested_project_id == project_id
        return [
            {"pid": 1111, "command": f"codex exec --cd /tmp/{project_id}/child-one"},
            {"pid": 2222, "command": f"codex exec --cd /tmp/{project_id}/child-two"},
        ]

    def fake_terminate(pid: int) -> dict[str, Any]:
        terminated_pids.append(pid)
        return {"pid": pid, "status": "terminated", "terminated": True, "kill_escalated": False}

    monkeypatch.setattr(routes_module, "running_codex_processes_for_project", fake_running_codex_processes_for_project)
    monkeypatch.setattr(routes_module, "terminate_codex_process_for_autonomy_stop", fake_terminate)

    stop_response = client.post(f"/api/projects/{project_id}/autonomy/stop")
    assert stop_response.status_code == 200, stop_response.text
    output = stop_response.json()["output"]
    assert observed_calls == [project_id]
    assert terminated_pids == [1111, 2222]
    assert output["codex_process_cleanup"]["schema_version"] == "project_codex_process_cleanup.v1"
    assert output["codex_process_cleanup"]["observed_count"] == 2
    assert output["codex_process_cleanup"]["terminated_count"] == 2
    assert output["codex_process_cleanup"]["remaining_count"] == 0
    assert [item["pid"] for item in output["codex_process_cleanup"]["processes"]] == [1111, 2222]

    with app.state.session_factory() as db:
        assert db.get(Job, running_child.id).status == "cancelled"  # type: ignore[union-attr]


def test_autonomy_stop_does_not_scan_or_stop_other_project_processes(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    target_response = client.post("/api/projects", json={"name": "Stop target"})
    assert target_response.status_code == 200
    target_project_id = target_response.json()["id"]
    other_response = client.post("/api/projects", json={"name": "Stop other"})
    assert other_response.status_code == 200
    other_project_id = other_response.json()["id"]

    terminated_pids: list[int] = []

    def fake_running_codex_processes_for_project(requested_project_id: str) -> list[dict[str, Any]]:
        if requested_project_id == target_project_id:
            return [{"pid": 3333, "command": f"codex exec --cd /tmp/{target_project_id}/child"}]
        if requested_project_id == other_project_id:
            return [{"pid": 9999, "command": f"codex exec --cd /tmp/{other_project_id}/child"}]
        return []

    def fake_terminate(pid: int) -> dict[str, Any]:
        terminated_pids.append(pid)
        return {"pid": pid, "status": "terminated", "terminated": True, "kill_escalated": False}

    monkeypatch.setattr(routes_module, "running_codex_processes_for_project", fake_running_codex_processes_for_project)
    monkeypatch.setattr(routes_module, "terminate_codex_process_for_autonomy_stop", fake_terminate)

    stop_response = client.post(f"/api/projects/{target_project_id}/autonomy/stop")
    assert stop_response.status_code == 200, stop_response.text
    output = stop_response.json()["output"]
    assert terminated_pids == [3333]
    assert output["codex_process_cleanup"]["observed_count"] == 1
    assert output["codex_process_cleanup"]["processes"][0]["pid"] == 3333


def test_agent_activity_hides_future_autonomous_heartbeat_when_project_is_off(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Future heartbeat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Continue the main Full Auto session",
                    "summary": "Reserved heartbeat for the autonomous session.",
                }
            },
            run_after=utc_now() + timedelta(minutes=5),
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 0
    assert activity["turn_state"]["state"] == "waiting_for_user"
    assert activity["workers"] == []


def test_agent_activity_turn_state_waits_for_user_when_no_agent_work_is_observed(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Idle turn state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    turn_state = activity_response.json()["turn_state"]
    assert turn_state["state"] == "waiting_for_user"
    assert turn_state["owner"] == "user"
    assert turn_state["input_attention"] is True
    assert "local_process_table.codex_exec" in turn_state["sources"]


def test_agent_activity_completed_plan_waits_for_new_input_options(tmp_path: Path) -> None:
    client = make_client(tmp_path, api_agent_session_supervisor_enabled=False)

    project_response = client.post("/api/projects", json={"name": "Completed wait options"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "IDLE"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_completed_wait_options",
            project_id=project_id,
            session_type="main_autonomous",
            status="completed",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Completed available work.",
            created_at=utc_now() - timedelta(minutes=10),
            started_at=utc_now() - timedelta(minutes=10),
            ended_at=utc_now() - timedelta(minutes=1),
        )
        db.add(session)
        commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project_id,
                "timeline_blocks": [
                    {
                        "id": "current_work_done",
                        "title": "Current work done",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            author_type="codex",
            reason="No further reversible work is available without new input.",
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 0
    assert activity["turn_state"]["state"] == "waiting_for_user"
    assert "test data" in activity["turn_state"]["detail"]
    assert "outcomes" in activity["turn_state"]["detail"]
    assert "instruction" in activity["turn_state"]["detail"]


def test_agent_activity_surfaces_malformed_agent_chat_turn_without_crashing(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Malformed chat activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        malformed = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="malformed_agent_chat_turn",
            filename="agent_chat_turn.json",
            text='{"schema_version":"agent_chat_turn.v1"}\n{"extra": true}',
            metadata={"project_id": project_id},
        )
        db.commit()
        malformed_artifact_id = malformed.id

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    workers = activity_response.json()["workers"]
    issue_workers = [worker for worker in workers if worker.get("artifact_id") == malformed_artifact_id]
    assert issue_workers
    assert issue_workers[0]["status"] == "failed"
    assert issue_workers[0]["target_tab"] == "Assets"


def test_agent_activity_treats_stale_running_session_as_off_when_project_idle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.running_codex_processes_for_project",
        lambda project_id: [],
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Idle stale session"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "IDLE"
        stale_at = utc_now() - timedelta(minutes=20)
        db.add(
            AgentSession(
                id="ags_idle_stale_running",
                project_id=project_id,
                session_type="main_autonomous",
                status="running",
                autonomy_mode="full_auto",
                runner_kind="codex_cli",
                goal_text="Continue autonomously.",
                last_heartbeat_at=stale_at,
                updated_at=stale_at,
            )
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 0
    assert activity["turn_state"]["state"] == "waiting_for_user"
    assert activity["turn_state"]["owner"] == "user"
    assert all(worker.get("agent_session_id") != "ags_idle_stale_running" for worker in activity["workers"])


def test_agent_activity_hides_queued_autonomous_worker_when_project_idle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.services.portal.running_codex_processes_for_project",
        lambda project_id: [],
    )
    monkeypatch.setattr(
        "tabular_harness.api.routes.running_codex_processes_for_project",
        lambda project_id: [],
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Idle queued heartbeat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "IDLE"
        queued_job = create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            context={"human_description": {"title": "Continue autonomous session", "summary": "Resume Codex."}},
        )
        db.commit()
        queued_job_id = queued_job.id

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 0
    assert activity["turn_state"]["state"] == "waiting_for_user"
    assert activity["turn_state"].get("active_job_id") != queued_job_id
    assert all(worker.get("job_id") != queued_job_id for worker in activity["workers"])


def test_agent_activity_watchdog_starts_main_session_when_full_auto_has_no_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Watchdog restart"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["state"] in {"agent_running", "agent_scheduled"}
    session_id = activity["turn_state"]["agent_session_id"]

    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"


def test_agent_activity_last_output_uses_codex_transcript_not_sidecar_heartbeat(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Codex output clock"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_codex_output_clock",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        codex_event = append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="A real Codex update.",
            payload={},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="sidecar_status",
            role="harness",
            title="Sidecar status",
            content="Harness sidecar update.",
            payload={},
        )
        expected_output_at = codex_event.created_at.replace(tzinfo=None).isoformat()
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["last_output_at"] == expected_output_at
    assert activity["workers"][0]["last_output_at"] == expected_output_at
    assert activity["workers"][0]["human_description"]["summary"] != "A real Codex update."
    assert "A real Codex update" not in activity["workers"][0]["detail"]
    assert "Harness sidecar update" not in activity["workers"][0]["detail"]


def test_agent_activity_uses_session_attention_chat_turn_as_human_summary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Attention activity summary"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    attention_message = "Notebook preview failed; Codex can repair and resubmit the fixed notebook request."

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_attention_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_attention_summary",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": attention_message,
                "intent": {"type": "agent_attention_event", "message_kind": "notebook_request_failed"},
                "actions": [],
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_attention",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["human_description"]["summary"] != attention_message
    assert activity["workers"][0]["detail"] != attention_message
    assert "notebook has not been registered yet" in activity["workers"][0]["detail"]
    assert "request" not in activity["workers"][0]["detail"].lower()


def test_agent_activity_surfaces_codex_start_silence_attention_worker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Start silence activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_start_silence_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue the main autonomous analysis.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        chat_artifact = register_agent_session_attention_chat_turn(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            attention_key="turn_start_silence:ags_start_silence_activity:300",
            status="recovering",
            message_kind="turn_start_silence",
            details={"idle_timeout_seconds": 300, "timeout_kind": "turn_start_silence"},
        )
        assert chat_artifact is not None
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    worker_ids = [worker["worker_id"] for worker in activity["workers"]]
    assert "main-agent-session" in worker_ids
    assert "agent-availability-ags_start_silence_activity-turn_start_silence" not in worker_ids

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    attention_turns = [
        turn
        for turn in history_response.json()
        if turn.get("intent", {}).get("message_kind") == "turn_start_silence"
    ]
    assert len(attention_turns) == 1
    assert attention_turns[0]["response_brief"]["details"]["timeout_kind"] == "turn_start_silence"


def test_agent_attention_chat_display_hides_internal_tool_terms(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Attention display cleanup"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    legacy_message = "ResearchPlanの更新要求 `set_current_work` をackできませんでした。requestを修正してください。"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_attention_cleanup",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="legacy_internal_tool_attention",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": legacy_message,
                "intent": {"type": "agent_attention_event", "message_kind": "research_plan_request_failed"},
                "actions": [],
                "worker_events": [],
                "response_brief": {
                    "details": {
                        "operation": "set_current_work",
                        "request_id": "bad_current",
                        "error_message": "node_id is required",
                    }
                },
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_attention",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history_turn = history_response.json()[0]
    assert history_turn["assistant_message"] != legacy_message
    assert "set_current_work" not in history_turn["assistant_message"]
    assert "ack" not in history_turn["assistant_message"].lower()
    assert "request" not in history_turn["assistant_message"].lower()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity_summary = activity_response.json()["workers"][0]["human_description"]["summary"]
    assert activity_summary != legacy_message
    assert "set_current_work" not in activity_summary
    assert "ack" not in activity_summary.lower()
    assert "request" not in activity_summary.lower()


def test_agent_activity_prefers_newer_research_plan_current_work_over_stale_chat(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Current work activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    stale_message = "Older chat summary that should not hide the declared current work."
    current_summary = "Codex is writing the model diagnostics notebook and linking run evidence."

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_current_work_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        stale_chat = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="stale_agent_summary",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": stale_message,
                "intent": {"type": "agent_attention_event", "message_kind": "notebook_request_failed"},
                "actions": [],
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_attention",
            },
        )
        stale_chat.created_at = utc_now() - timedelta(minutes=10)
        revision = commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "model_diagnostics",
                        "title": "Model diagnostics",
                        "subtitle": "Interpret run errors and readable notebook evidence.",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["notebook", "report"]},
                    }
                ],
            },
            author_type="codex",
            reason="Codex declared the active diagnostics chapter.",
            strict_validation=True,
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project_id,
            node_id="model_diagnostics",
            summary=current_summary,
            status="active",
            expected_outputs=["notebook", "report"],
            revision_id=revision.id,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["detail"].startswith(current_summary)
    assert activity["workers"][0]["human_description"]["summary"].startswith(current_summary)
    assert activity["workers"][0]["target_tab"] == "Home"
    assert activity["workers"][0]["target_anchor"] == "research-plan"


def test_agent_activity_does_not_show_command_shaped_current_work(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Command shaped activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    human_message = "モデル診断の準備を続けています。結果が揃い次第、LeaderboardとNotebookに登録します。"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_command_shaped_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content=human_message,
            payload={},
        )
        revision = commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "model_diagnostics",
                        "title": "Model diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["notebook", "report"]},
                    }
                ],
            },
            author_type="codex",
            reason="Codex declared the active diagnostics chapter.",
            strict_validation=True,
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project_id,
            node_id="model_diagnostics",
            summary="/bin/bash -lc \".tablex/bin/python - <<'PY' request = {'schema_version': 'tablex_research_plan_request.v1'}\"",
            status="active",
            expected_outputs=["notebook", "report"],
            revision_id=revision.id,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert not activity["workers"][0]["detail"].startswith(human_message)
    assert not activity["workers"][0]["human_description"]["summary"].startswith(human_message)
    assert "/bin/bash" not in activity["workers"][0]["detail"]
    assert "schema_version" not in activity["workers"][0]["detail"]


def test_agent_activity_surfaces_research_plan_request_success_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "ResearchPlan success activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_research_plan_success_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep ResearchPlan activity visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="research_plan_request_succeeded",
            role="harness",
            title="ResearchPlan request processed",
            content="Processed ResearchPlan request `commit_revision`.",
            payload={
                "schema_version": "tablex_research_plan_ack.v1",
                "request_id": "commit_plan",
                "operation": "commit_revision",
                "status": "succeeded",
                "result": {"revision_id": "rprev_success_activity"},
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    worker = activity["workers"][0]
    assert worker["detail"] == "The Research Plan was updated."
    assert worker["human_description"]["summary"] == "The Research Plan was updated."
    assert "commit_revision" not in worker["detail"]
    assert worker["target_tab"] == "Home"
    assert worker["target_anchor"] == "research-plan"


def test_agent_activity_surfaces_research_plan_request_failure_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "ResearchPlan failure activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_research_plan_failure_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep ResearchPlan request failures visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="research_plan_request_failed",
            role="harness",
            title="ResearchPlan request failed",
            content="missing current node",
            payload={
                "schema_version": "tablex_research_plan_ack.v1",
                "request_id": "commit_invalid_plan",
                "operation": "commit_revision",
                "status": "failed",
                "error": {
                    "type": "ResearchPlanValidationError",
                    "message": "missing_current_node",
                    "issues": [{"code": "missing_current_node"}],
                },
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    worker = activity_response.json()["workers"][0]
    assert "visible work plan has not been updated yet" in worker["detail"]
    assert "commit_revision" not in worker["detail"]
    assert "missing_current_node" not in worker["detail"]
    assert "structured" not in worker["detail"].lower()
    assert worker["target_tab"] == "Home"
    assert worker["target_anchor"] == "research-plan"


def test_agent_activity_marks_terminal_chat_worker_events_inactive(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Terminal chat worker cleanup"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_terminal_chat_worker_cleanup",
            project_id=project_id,
            session_type="main_autonomous",
            status="starting",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Start full auto.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        job = create_job(
            db,
            job_type="start_autonomous_loop",
            project_id=project_id,
            input_payload={},
            created_by="test",
        )
        job.status = "succeeded"
        terminal_job_id = job.id
        job.output_json = json.dumps(
            {
                "worker_events": [
                    {
                        "worker_id": "main-agent-session",
                        "display_name": "自律分析",
                        "status": "starting",
                        "headline": "分析を開始しています",
                        "detail": "プロジェクトの状況を確認し、次の分析ステップを開始しています。",
                        "job_id": terminal_job_id,
                        "job_type": "start_autonomous_loop",
                        "project_id": project_id,
                        "agent_session_id": session.id,
                        "target_tab": "Home",
                        "target_anchor": "agent-workspace",
                        "active": True,
                    }
                ]
            }
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="start_job_chat_worker",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": "フルオートを開始しました。",
                "intent": {"type": "autonomous_loop_started"},
                "actions": [],
                "worker_events": loads_json(job.output_json, {})["worker_events"],
            },
            metadata={"project_id": project_id, "agent_session_id": session.id},
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 1
    terminal_workers = [
        worker
        for worker in activity["workers"]
        if worker.get("job_id") == terminal_job_id and worker.get("source_chat_artifact_id")
    ]
    assert terminal_workers
    assert terminal_workers[0]["status"] == "succeeded"
    assert terminal_workers[0]["active"] is False


def test_agent_activity_does_not_use_raw_codex_messages_as_status_detail(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Raw message activity boundary"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    raw_message = (
        "The inbox is asking for the current ResearchPlan chapter to be declared. "
        "I will read the ack and continue."
    )
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_raw_message_activity_boundary",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep raw transcript out of Activity summary.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content=raw_message,
            payload={"type": "item.completed"},
            update_heartbeat=True,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert raw_message not in activity["turn_state"]["detail"]
    assert "ack" not in activity["turn_state"]["detail"].lower()
    assert "inbox" not in activity["turn_state"]["detail"].lower()
    main_worker = next(worker for worker in activity["workers"] if worker["worker_id"] == "main-agent-session")
    assert raw_message not in main_worker["detail"]
    assert "ack" not in main_worker["detail"].lower()
    assert "inbox" not in main_worker["detail"].lower()


def test_agent_activity_uses_research_plan_current_work_ack_node_id(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "ResearchPlan current work ack activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_research_plan_current_ack_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep ResearchPlan current work visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="research_plan_request_succeeded",
            role="harness",
            title="ResearchPlan request processed",
            content="Processed ResearchPlan request `set_current_work`.",
            payload={
                "schema_version": "tablex_research_plan_ack.v1",
                "request_id": "set_current",
                "operation": "set_current_work",
                "status": "succeeded",
                "result": {"current_work": {"node_id": "model_diagnostics", "status": "active"}},
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    worker = activity["workers"][0]
    assert "The Research Plan was updated. Current node: model_diagnostics" in worker["detail"]
    assert worker["target_tab"] == "Home"
    assert worker["target_anchor"] == "research-plan"


def test_agent_activity_surfaces_experiment_result_success_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Experiment result success activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_experiment_success_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep experiment result activity visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="experiment_result_request_succeeded",
            role="harness",
            title="Experiment result request processed",
            content="Registered 2 leaderboard run(s).",
            payload={
                "schema_version": "tablex_experiment_result_ack.v1",
                "request_id": "register_runs",
                "operation": "register_runs",
                "status": "succeeded",
                "result": {"registered_run_ids": ["run_a", "run_b"]},
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    worker = activity_response.json()["workers"][0]
    assert "Experiment results were registered on the Leaderboard. 2 run(s) are comparable." in worker["detail"]
    assert worker["target_tab"] == "Leaderboard"
    assert worker["target_anchor"] == "result-readout"


def test_agent_activity_surfaces_experiment_result_failure_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Experiment result failure activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_experiment_failure_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep experiment result failures visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="experiment_result_request_failed",
            role="harness",
            title="Experiment result request failed",
            content="unknown ResearchPlan node",
            payload={
                "schema_version": "tablex_experiment_result_ack.v1",
                "request_id": "register_runs",
                "operation": "register_runs",
                "status": "failed",
                "error": {"type": "ValueError", "message": "ResearchPlan node `missing_node` is not present"},
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    worker = activity_response.json()["workers"][0]
    assert "model evaluation results have not been added to the Leaderboard yet" in worker["detail"]
    assert "missing_node" not in worker["detail"]
    assert worker["target_tab"] == "Home"
    assert worker["target_anchor"] == "agent-workspace"


def test_agent_activity_surfaces_notebook_request_success_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook request success activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_notebook_success_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep notebook request activity visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="notebook_request_succeeded",
            role="harness",
            title="Notebook request processed",
            content="Processed notebook request `register_notebook`.",
            payload={
                "schema_version": "tablex_notebook_ack.v1",
                "request_id": "register_data_story",
                "operation": "register_notebook",
                "status": "succeeded",
                "result": {
                    "notebook_artifact_id": "art_notebook_activity",
                    "research_plan_node_id": "data_understanding",
                },
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    worker = activity_response.json()["workers"][0]
    assert "marimo notebook was registered" in worker["detail"]
    assert "data_understanding" in worker["detail"]
    assert worker["target_tab"] == "Notebooks"
    assert worker["target_anchor"] == "notebook-native-marimo-top"
    assert worker["artifact_id"] == "art_notebook_activity"


def test_agent_activity_surfaces_notebook_request_failure_event(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook request failure activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_notebook_failure_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep notebook request failures visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="notebook_request_failed",
            role="harness",
            title="Notebook request failed",
            content="notebook source is not native marimo",
            payload={
                "schema_version": "tablex_notebook_ack.v1",
                "request_id": "register_bad_notebook",
                "operation": "register_notebook",
                "status": "failed",
                "error": {"type": "ValueError", "message": "notebook source is not native marimo"},
            },
            update_heartbeat=False,
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    worker = activity_response.json()["workers"][0]
    assert "marimo notebook has not been registered yet" in worker["detail"]
    assert "register_bad_notebook" not in worker["detail"]
    assert "native marimo" not in worker["detail"]
    assert worker["target_tab"] == "Notebooks"
    assert worker["target_anchor"] == "notebook-native-marimo-top"


def test_research_plan_current_work_is_paused_when_agent_power_is_off(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "tabular_harness.services.research_plan_timeline.running_codex_processes_for_project",
        lambda project_id: [{"pid": 12345, "command": f"codex exec /tmp/{project_id}/task"}],
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Paused current work"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    current_summary = "Codex is diagnosing the salary error slices."
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_paused_current_work",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "error_slice_diagnostics",
                        "title": "Error slice diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["notebook", "leaderboard_entry"]},
                    }
                ],
            },
            author_type="codex",
            reason="Codex declared the current diagnostics chapter.",
            strict_validation=True,
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project_id,
            node_id="error_slice_diagnostics",
            summary=current_summary,
            status="active",
            expected_outputs=["notebook", "leaderboard_entry"],
            revision_id=revision.id,
        )
        db.commit()

    active_timeline_response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert active_timeline_response.status_code == 200
    active_current_work = active_timeline_response.json()["current_work"]
    assert active_current_work["node_id"] == "error_slice_diagnostics"
    assert active_current_work["activity_state"] == "active"
    assert active_current_work["is_live"] is True

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        session = db.get(AgentSession, "ags_paused_current_work")
        assert project is not None
        assert session is not None
        project.current_phase = "IDLE"
        session.status = "stopped"
        session.pid = None
        session.updated_at = utc_now()
        db.commit()

    paused_timeline_response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert paused_timeline_response.status_code == 200
    paused_current_work = paused_timeline_response.json()["current_work"]
    assert paused_current_work["node_id"] == "error_slice_diagnostics"
    assert paused_current_work["summary"] == current_summary
    assert paused_current_work["activity_state"] == "paused"
    assert paused_current_work["is_live"] is False

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["state"] == "waiting_for_user"
    assert current_summary not in activity["turn_state"]["detail"]


def test_agent_activity_uses_research_plan_question_target_from_chat_turn(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Question activity target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    question_message = "Codex has a question for you. Is this objective production-facing?"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_question_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_question_summary",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": question_message,
                "intent": {
                    "type": "agent_attention_event",
                    "message_kind": "research_plan_human_attention_requested",
                },
                "actions": [
                    {
                        "type": "open_surface",
                        "target_tab": "Assumptions",
                        "target_anchor": "assumption-review",
                    }
                ],
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_attention",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["human_description"]["summary"] == question_message
    assert activity["workers"][0]["target_tab"] == "Assumptions"
    assert activity["workers"][0]["target_anchor"] == "assumption-review"


def test_leaderboard_display_uses_structured_raw_model_context() -> None:
    params = {
        "model_id": "ridge_sparse_sgd__strict_no_engagement__capped_annualized",
        "raw": {
            "model_name": "ridge_sparse_sgd_capped_annualized",
            "feature_policy": "strict_no_engagement",
            "split": "test",
            "fold": "test",
        },
    }

    assert routes_module.leaderboard_model_label(
        params,
        model_id="ridge_sparse_sgd__strict_no_engagement__capped_annualized",
    ) == "ridge_sparse_sgd_capped_annualized"
    assert routes_module.leaderboard_model_description(
        params,
        summary_md="ridge_sparse_sgd__strict_no_engagement__capped_annualized",
        model_id="ridge_sparse_sgd__strict_no_engagement__capped_annualized",
    ) == ""
    assert routes_module.leaderboard_feature_summary(params, {}) == "feature policy: strict no engagement / split: test / fold: test"


def test_leaderboard_metric_direction_handles_derived_loss_names() -> None:
    assert metric_lower_is_better("rmse_log_salary") is True
    assert metric_lower_is_better("mae_raw_salary") is True
    assert metric_lower_is_better("median_absolute_percentage_error") is True
    assert metric_lower_is_better("roc_auc") is False


def test_leaderboard_read_does_not_reconcile_existing_run_into_chat_links(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Leaderboard reconciliation"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        session = AgentSession(
            id="ags_leaderboard_reconcile",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Register model results.",
        )
        db.add(session)
        db.flush()
        source_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_artifact",
            name="existing_structured_model_results",
            filename="model_results.json",
            text=json.dumps({"schema_version": "model_results.v1", "models": []}),
            metadata={
                "source": "main_agent_session_workspace",
                "agent_session_id": session.id,
                "workspace_relative_path": "artifacts/model_results.json",
            },
        )
        notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="leaderboard_model_notebook",
            filename="model_notebook.py",
            text="import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "run_id": "run_leaderboard_reconcile",
                "notebook_kind": "model_diagnostics",
            },
        )
        pipeline_bundle = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="prediction_pipeline",
            name="hierarchical_median_pipeline",
            filename="pipeline_bundle.zip",
            text="zip placeholder",
            metadata={"experiment_run_ids": ["run_leaderboard_reconcile"]},
        )
        prediction_input_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="pipeline_prediction_input",
            filename="input.csv",
            text="x\n1\n",
            metadata={"project_id": project_id},
        )
        prediction_input = DatasetSnapshot(
            id="ds_pipeline_prediction_input",
            project_id=project_id,
            artifact_id=prediction_input_artifact.id,
            source_type="upload",
            source_ref="input.csv",
            row_count=1,
            column_count=1,
            schema_hash="pipeline_prediction_input",
        )
        run = ExperimentRun(
            id="run_leaderboard_reconcile",
            project_id=project_id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps(
                {
                    "agent_session_id": session.id,
                    "source_artifact_id": source_artifact.id,
                    "source_key": "existing_structured_model_results:hierarchical_median",
                    "model_id": "hierarchical_median",
                    "model_description": "Hierarchical median grouped by pay period and experience.",
                    "features_used": ["pay_period", "experience_level", "work_type"],
                    "feature_summary": "pay period, experience, work type",
                    "pipeline_artifact_id": pipeline_bundle.id,
                    "research_plan_node_id": "modeling",
                }
            ),
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 27531.0, "mae": 27531.0}),
            summary_md="Recovered model comparison result.",
        )
        db.add_all([prediction_input, run])
        commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is comparing model candidates.",
            strict_validation=True,
        )
        db.commit()

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard_row = leaderboard_response.json()[0]
    assert leaderboard_row["run_id"] == "run_leaderboard_reconcile"
    assert leaderboard_row["model_id"] == "hierarchical_median"
    assert leaderboard_row["model_label"] == "hierarchical_median"
    assert leaderboard_row["model_description"] == "Hierarchical median grouped by pay period and experience."
    assert leaderboard_row["features_used"] == ["pay_period", "experience_level", "work_type"]
    assert leaderboard_row["feature_summary"] == "pay period, experience, work type"
    assert leaderboard_row["summary_md"] == "Recovered model comparison result."
    assert leaderboard_row["pipeline_artifact_id"] == pipeline_bundle.id
    assert leaderboard_row["related_notebook_artifact_ids"] == [notebook.id]
    assert len(leaderboard_row["related_notebooks"]) == 1
    related_notebook = leaderboard_row["related_notebooks"][0]
    assert related_notebook["artifact_id"] == notebook.id
    assert related_notebook["title"] == "Model Diagnostics Notebook"
    assert related_notebook["notebook_kind"] == "model_diagnostics"
    assert related_notebook["status"] == "needs_attention"
    assert related_notebook["native_marimo_status"] == "source_registered"
    assert related_notebook["needs_attention"] is True
    assert related_notebook["openable"] is True
    assert related_notebook["run_id"] == "run_leaderboard_reconcile"
    assert related_notebook["model_version_id"] is None
    assert related_notebook["related_run_ids"] == []
    assert isinstance(related_notebook["recommendation_score"], int)
    bundle_response = client.get("/api/experiment-runs/run_leaderboard_reconcile/pipeline-bundle")
    assert bundle_response.status_code == 200
    assert bundle_response.content == b"zip placeholder"
    predict_response = client.post(
        f"/api/projects/{project_id}/pipelines/{pipeline_bundle.id}/predict",
        json={"dataset_snapshot_id": "ds_pipeline_prediction_input"},
    )
    assert predict_response.status_code == 200, predict_response.text
    predict_job = predict_response.json()
    assert predict_job["job_type"] == "run_prediction_pipeline"
    assert predict_job["status"] == "queued"
    deployment_response = client.post(
        f"/api/projects/{project_id}/pilot-deployments",
        json={"pipeline_artifact_id": pipeline_bundle.id, "experiment_run_id": "run_leaderboard_reconcile"},
    )
    assert deployment_response.status_code == 200, deployment_response.text
    deployment = deployment_response.json()
    assert deployment["pipeline_artifact_id"] == pipeline_bundle.id
    pilot_predict_response = client.post(
        f"/api/pilot-deployments/{deployment['id']}/predict",
        json={"dataset_snapshot_id": "ds_pipeline_prediction_input", "as_of": "2026-07-06T00:00:00Z"},
    )
    assert pilot_predict_response.status_code == 200, pilot_predict_response.text
    pilot_job = pilot_predict_response.json()
    assert pilot_job["job_type"] == "run_prediction_pipeline"
    assert pilot_job["status"] == "queued"
    with app.state.session_factory() as db:
        outcome_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="pilot_outcomes",
            name="pilot_outcomes_for_api",
            filename="outcomes.csv",
            text="id,actual\n1,2\n",
            metadata={"project_id": project_id},
        )
        scoring_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="pilot_scoring_report",
            name="pilot_scoring_report_for_api",
            filename="pilot_scoring_report.json",
            payload={
                "schema_version": "pilot_scoring_report.v1",
                "deployment_id": deployment["id"],
                "matched_rows": 1,
                "metric_count": 1,
                "metrics": {"mae": 0.5},
                "as_of_violations": {"count": 0},
            },
            metadata={"project_id": project_id, "deployment_id": deployment["id"]},
        )
        db.commit()
    pilot_outcomes_response = client.post(
        f"/api/pilot-deployments/{deployment['id']}/outcomes",
        json={
            "outcomes_artifact_id": outcome_artifact.id,
            "join_keys": ["id"],
            "actual_column": "actual",
            "prediction_column": "prediction",
        },
    )
    assert pilot_outcomes_response.status_code == 200, pilot_outcomes_response.text
    pilot_outcomes_job = pilot_outcomes_response.json()
    assert pilot_outcomes_job["job_type"] == "score_pilot_outcomes"
    assert pilot_outcomes_job["status"] == "queued"
    pilot_index_response = client.get(f"/api/projects/{project_id}/pilot-deployments")
    assert pilot_index_response.status_code == 200, pilot_index_response.text
    pilot_index = pilot_index_response.json()
    assert pilot_index["schema_version"] == "pilot_deployment_index.v1"
    assert len(pilot_index["deployments"]) == 1
    assert pilot_index["deployments"][0]["id"] == deployment["id"]
    assert pilot_index["deployments"][0]["outcome_batches"][0]["outcomes_artifact_id"] == outcome_artifact.id
    assert pilot_index["deployments"][0]["scoring_reports"][0]["artifact"]["id"] == scoring_artifact.id
    assert pilot_index["deployments"][0]["scoring_reports"][0]["metrics"]["mae"] == 0.5

    with app.state.session_factory() as db:
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="native_marimo_runtime_failure_model_notebook",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": "Notebook runtime failed.",
                "intent": {"type": "native_marimo_runtime_failed"},
                "actions": [],
            },
            metadata={
                "project_id": project_id,
                "source": "native_marimo_runtime_failure",
                "notebook_artifact_id": notebook.id,
                "notebook_source_hash": marimo_notebook_source_hash_for_artifact(notebook),
            },
        )
        db.commit()

    failed_notebook_leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert failed_notebook_leaderboard_response.status_code == 200, failed_notebook_leaderboard_response.text
    failed_notebook_leaderboard_row = failed_notebook_leaderboard_response.json()[0]
    assert failed_notebook_leaderboard_row["related_notebook_artifact_ids"] == [notebook.id]
    assert failed_notebook_leaderboard_row["related_notebooks"][0]["artifact_id"] == notebook.id
    assert failed_notebook_leaderboard_row["related_notebooks"][0]["needs_attention"] is True
    assert failed_notebook_leaderboard_row["related_notebooks"][0]["openable"] is True
    assert failed_notebook_leaderboard_row["related_notebooks"][0]["native_marimo_status"] == "runtime_error"

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200, history_response.text
    experiment_turns = [
        turn for turn in history_response.json() if turn["intent"].get("type") == "experiment_results_registered"
    ]
    assert experiment_turns == []

    second_history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert second_history_response.status_code == 200
    second_turns = [
        turn for turn in second_history_response.json() if turn["intent"].get("type") == "experiment_results_registered"
    ]
    assert second_turns == []
    with app.state.session_factory() as db:
        chat_artifacts = list(
            db.scalars(
                select(Artifact).where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            ).all()
        )
        registration_artifacts = [
            artifact
            for artifact in chat_artifacts
            if loads_json(artifact.metadata_json, {}).get("source") == "main_agent_session_experiment_registration"
        ]
        assert registration_artifacts == []


def test_pipeline_bundle_download_omits_validation_cache_files(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Clean pipeline download"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    source_zip = tmp_path / "dirty_pipeline.zip"
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pipeline_manifest.json", "{}")
        archive.writestr("predict.py", "print('predict')\n")
        archive.writestr("train.py", "print('train')\n")
        archive.writestr("requirements.txt", "\n")
        archive.writestr("README.md", "# Pipeline\n")
        archive.writestr("model/model.txt", "model")
        archive.writestr(".tablex_smoke/register/input.csv", "x\n1\n")
        archive.writestr(".tablex_smoke/register/predictions.csv", "prediction\n0.1\n")
        archive.writestr("__pycache__/predict.cpython-313.pyc", b"cache")

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        version = next_artifact_version(db, project_id, "prediction_pipeline", "dirty_pipeline")
        target_dir, stored, content_hash = app.state.artifact_store.store_existing_file(
            org_id=project.org_id,
            project_id=project_id,
            asset_type="prediction_pipeline",
            name="dirty_pipeline",
            version=version,
            source_path=source_zip,
            filename="dirty_pipeline.zip",
            metadata={"experiment_run_ids": ["run_dirty_pipeline"]},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project_id,
            asset_type="prediction_pipeline",
            name="dirty_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"experiment_run_ids": ["run_dirty_pipeline"]},
            version=version,
            org_id=project.org_id,
        )
        run = ExperimentRun(
            id="run_dirty_pipeline",
            project_id=project_id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps(
                {
                    "model_id": "dirty_pipeline",
                    "model_description": "Pipeline bundle with validation cache files.",
                    "features_used": ["x"],
                    "pipeline_artifact_id": pipeline_artifact.id,
                }
            ),
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Pipeline bundle with validation cache files.",
        )
        db.add(run)
        db.commit()

    response = client.get("/api/experiment-runs/run_dirty_pipeline/pipeline-bundle")
    assert response.status_code == 200
    clean_zip = tmp_path / "downloaded_pipeline.zip"
    clean_zip.write_bytes(response.content)
    with zipfile.ZipFile(clean_zip) as archive:
        names = archive.namelist()
    assert "predict.py" in names
    assert "pipeline_manifest.json" in names
    assert "model/model.txt" in names
    assert not any(name.startswith(".tablex_smoke/") for name in names)
    assert not any("__pycache__/" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)


def test_agent_chat_history_surfaces_legacy_experiment_registration_payload(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "legacy experiment chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="legacy_experiment_registration_payload",
            filename="agent_chat_turn.json",
            payload={
                "actions": [
                    {
                        "type": "open_surface",
                        "status": "ready",
                        "label": "Open leaderboard",
                        "target_tab": "Leaderboard",
                        "target_anchor": "result-readout",
                        "entity_ids": ["run_legacy"],
                    }
                ],
                "response_brief": {
                    "schema_version": "experiment_results_registered.v1",
                    "run_ids": ["run_legacy"],
                    "research_plan_node_ids": ["modeling"],
                    "visible_surfaces": {
                        "leaderboard": {
                            "target_tab": "Leaderboard",
                            "target_anchor": "result-readout",
                            "run_ids": ["run_legacy"],
                        }
                    },
                },
            },
            metadata={
                "project_id": project_id,
                "source": "main_agent_session_experiment_registration",
                "source_key": "legacy",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()
    assert len(history) == 1
    turn = history[0]
    assert turn["schema_version"] == "agent_chat_turn.v1"
    assert turn["intent"]["type"] == "experiment_results_registered"
    assert turn["assistant_message"] == "Registered 1 model evaluation(s) on the leaderboard."
    assert turn["actions"][0]["target_tab"] == "Leaderboard"
    assert turn["response_brief"]["run_ids"] == ["run_legacy"]


def test_pilot_phase_vertical_loop_registers_pipeline_predicts_scores_and_notifies_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Pilot vertical loop"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace"
    pipeline_dir = workspace / "pipelines" / "plus_one_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {
                "columns": [
                    {"name": "id", "dtype": "string", "required": True},
                    {"name": "x", "dtype": "float", "required": True},
                ],
                "description": "Inference rows with an id and numeric x column.",
            },
            "history_requirements": {
                "required": False,
                "as_of_column": None,
                "history_window": None,
                "history_format": None,
                "notes": "No history is required for this deterministic test pipeline.",
            },
        },
        "output_contract": {
            "columns": [
                {"name": "id", "dtype": "string"},
                {"name": "prediction", "dtype": "float"},
            ],
            "id_columns": ["id"],
            "prediction_column": "prediction",
        },
        "training": {
            "dataset_snapshot_id": "ds_pilot_vertical_a",
            "split_manifest_id": None,
            "evaluation_spec_id": None,
            "seed": 1,
            "deterministic": True,
        },
        "expected_metrics": [{"name": "mae", "value": 0.0, "split": "validation"}],
        "runtime": {"python": ">=3.11", "timeout_seconds_predict": 60},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('pretrained test pipeline')\n", encoding="utf-8")
    (pipeline_dir / "requirements.txt").write_text("# stdlib only\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text(
        "Deterministic test pipeline that predicts x + 1 from raw inference input.\n",
        encoding="utf-8",
    )
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.input, encoding='utf-8-sig', newline='') as src, open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    reader = csv.DictReader(src)\n"
        "    writer = csv.DictWriter(dst, fieldnames=['id', 'prediction'])\n"
        "    writer.writeheader()\n"
        "    for row in reader:\n"
        "        writer.writerow({'id': row['id'], 'prediction': float(row['x']) + 1.0})\n",
        encoding="utf-8",
    )
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True, exist_ok=True)
    (request_dir / "register_plus_one_pipeline.json").write_text(
        json.dumps(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "operation": "register_prediction_pipeline",
                "request_id": "register_plus_one_pipeline",
                "payload": {
                    "pipeline_name": "plus_one_pipeline",
                    "workspace_dir": "pipelines/plus_one_pipeline",
                    "experiment_run_ids": ["run_pilot_vertical"],
                    "research_plan_node_id": "pilot_modeling",
                    "manifest": manifest,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.target_column = "actual"
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_pilot_vertical",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue from pilot observations.",
            workspace_path=str(workspace),
        )
        input_a_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="pilot_input_a",
            filename="input_a.csv",
            text="id,x\n1,1\n2,2\n",
            metadata={"project_id": project_id},
        )
        input_b_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="pilot_input_b",
            filename="input_b.csv",
            text="id,x\n1,10\n2,20\n",
            metadata={"project_id": project_id},
        )
        dataset_a = DatasetSnapshot(
            id="ds_pilot_vertical_a",
            project_id=project_id,
            artifact_id=input_a_artifact.id,
            source_type="upload",
            source_ref="input_a.csv",
            row_count=2,
            column_count=2,
            schema_hash="pilot_vertical_a",
        )
        dataset_b = DatasetSnapshot(
            id="ds_pilot_vertical_b",
            project_id=project_id,
            artifact_id=input_b_artifact.id,
            source_type="upload",
            source_ref="input_b.csv",
            row_count=2,
            column_count=2,
            schema_hash="pilot_vertical_b",
        )
        run = ExperimentRun(
            id="run_pilot_vertical",
            project_id=project_id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps(
                {
                    "model_id": "plus_one_pipeline",
                    "model_description": "Deterministic smoke model used to verify pilot lifecycle plumbing.",
                    "features_used": ["x"],
                }
            ),
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 0.0, "mae": 0.0}),
            summary_md="Pilot lifecycle smoke run.",
        )
        db.add_all([session, dataset_a, dataset_b, run])
        commit_research_plan_revision(
            db,
            project_id=project_id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "pilot_modeling",
                        "title": "Pilot modeling",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is preparing a pilot-ready pipeline.",
            strict_validation=True,
        )
        db.flush()
        ingest_session_workspace_outputs(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()

    queued_ack = loads_json(
        (pipeline_acks_dir(workspace) / "register_plus_one_pipeline.ack.json").read_text(encoding="utf-8"),
        {},
    )
    assert queued_ack["status"] == "queued"
    pipeline_registration_output = run_queued_job(client, queued_ack["job_id"])
    pipeline_artifact_id = pipeline_registration_output["pipeline_artifact_id"]
    final_ack = loads_json(
        (pipeline_acks_dir(workspace) / "register_plus_one_pipeline.ack.json").read_text(encoding="utf-8"),
        {},
    )
    assert final_ack["status"] == "succeeded"
    assert final_ack["result"]["pipeline_artifact_id"] == pipeline_artifact_id

    bundle_response = client.get("/api/experiment-runs/run_pilot_vertical/pipeline-bundle")
    assert bundle_response.status_code == 200
    assert bundle_response.content.startswith(b"PK")
    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard_row = next(row for row in leaderboard_response.json() if row["run_id"] == "run_pilot_vertical")
    assert leaderboard_row["run_id"] == "run_pilot_vertical"
    assert leaderboard_row["pipeline_artifact_id"] == pipeline_artifact_id
    assert leaderboard_row["model_description"] == "Deterministic smoke model used to verify pilot lifecycle plumbing."
    assert leaderboard_row["features_used"] == ["x"]

    deployment_response = client.post(
        f"/api/projects/{project_id}/pilot-deployments",
        json={"pipeline_artifact_id": pipeline_artifact_id, "experiment_run_id": "run_pilot_vertical"},
    )
    assert deployment_response.status_code == 200, deployment_response.text
    deployment = deployment_response.json()
    predict_a_response = client.post(
        f"/api/pilot-deployments/{deployment['id']}/predict",
        json={"dataset_snapshot_id": "ds_pilot_vertical_a", "as_of": "2026-07-06T00:00:00Z"},
    )
    assert predict_a_response.status_code == 200, predict_a_response.text
    prediction_a_output = run_queued_job(client, predict_a_response.json()["id"])
    assert prediction_a_output["pilot_prediction_batch_id"] is not None
    assert prediction_a_output["runtime_isolated"] is True
    assert "_pipeline_envs" in prediction_a_output["python_executable"]

    predict_b_response = client.post(
        f"/api/pilot-deployments/{deployment['id']}/predict",
        json={"dataset_snapshot_id": "ds_pilot_vertical_b", "as_of": "2026-07-07T00:00:00Z"},
    )
    assert predict_b_response.status_code == 200, predict_b_response.text
    prediction_b_output = run_queued_job(client, predict_b_response.json()["id"])
    prediction_batch_b_id = prediction_b_output["pilot_prediction_batch_id"]
    assert prediction_batch_b_id is not None
    assert prediction_b_output["runtime_isolated"] is True
    assert prediction_b_output["requirements_hash"] == prediction_a_output["requirements_hash"]

    with app.state.session_factory() as db:
        outcome_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="pilot_outcomes",
            name="pilot_vertical_outcomes",
            filename="outcomes.csv",
            text="id,actual,observed_at\n1,12,2026-07-08T00:00:00Z\n2,21,2026-07-09T00:00:00Z\n",
            metadata={"project_id": project_id},
        )
        outcome_artifact_id = outcome_artifact.id
        db.commit()

    outcomes_response = client.post(
        f"/api/pilot-deployments/{deployment['id']}/outcomes",
        json={
            "outcomes_artifact_id": outcome_artifact_id,
            "prediction_batch_id": prediction_batch_b_id,
            "join_keys": ["id"],
            "actual_column": "actual",
            "prediction_column": "prediction",
            "observed_at_column": "observed_at",
        },
    )
    assert outcomes_response.status_code == 200, outcomes_response.text
    scoring_output = run_queued_job(client, outcomes_response.json()["id"])
    assert scoring_output["matched_rows"] == 2
    assert scoring_output["metric_count"] == 2
    assert scoring_output["metrics"]["mae"] == 0.5
    assert scoring_output["as_of_violations"]["count"] == 0
    assert scoring_output["notified_agent_session_id"] == "ags_pilot_vertical"

    with app.state.session_factory() as db:
        prediction_batches = db.scalars(
            select(PilotPredictionBatch).where(PilotPredictionBatch.deployment_id == deployment["id"])
        ).all()
        assert len(prediction_batches) == 2
        report_artifact = db.get(Artifact, scoring_output["pilot_scoring_report_artifact_id"])
        assert report_artifact is not None
        report = loads_json(artifact_primary_path(report_artifact).read_text(encoding="utf-8"), {})
        assert report["schema_version"] == "pilot_scoring_report.v1"
        assert report["prediction_batch_id"] == prediction_batch_b_id
        assert report["metrics"]["mae"] == 0.5
        transcript_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == "ags_pilot_vertical",
                AgentTranscriptEvent.event_type == "pilot_observation_available",
            )
        )
        assert transcript_event is not None
        assert transcript_event.artifact_id == scoring_output["pilot_scoring_report_artifact_id"]
        assert loads_json(transcript_event.payload_json, {})["prediction_batch_id"] == prediction_batch_b_id
        prediction_artifact = db.get(Artifact, prediction_b_output["prediction_batch_artifact_id"])
        assert prediction_artifact is not None
        prediction_metadata = loads_json(prediction_artifact.metadata_json, {})
        assert prediction_metadata["runtime_isolated"] is True
        assert prediction_metadata["requirements_hash"] == prediction_b_output["requirements_hash"]
        validation_audit = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="validation_scheme_audit",
            name="pilot_vertical_validation_audit",
            filename="validation_audit.json",
            payload={
                "schema_version": "validation_scheme_audit.v1",
                "deployment_id": deployment["id"],
                "scoring_report_artifact_ids": [scoring_output["pilot_scoring_report_artifact_id"]],
                "scheme_verdict": "partially_confirmed",
                "gap_decomposition": [{"component": "sample_noise", "magnitude": "small"}],
                "next_iteration_focus": "Keep the same validation scheme and monitor the next pilot batch.",
            },
            metadata={
                "project_id": project_id,
                "deployment_id": deployment["id"],
                "scheme_verdict": "partially_confirmed",
                "scoring_report_artifact_ids": [scoring_output["pilot_scoring_report_artifact_id"]],
            },
        )
        validation_audit_id = validation_audit.id
        db.commit()
    inbox_notices = [
        entry for entry in list_inbox_entries(workspace) if entry["kind"] == "observation" and entry["type"] == "pilot_observation_available"
    ]
    assert len(inbox_notices) == 1
    notice_payload = inbox_notices[0]["payload"]
    assert notice_payload["pilot_scoring_report_artifact_id"] == scoring_output["pilot_scoring_report_artifact_id"]
    assert notice_payload["pilot_scoring_report_workspace_path"]
    assert notice_payload["prediction_batch_id"] == prediction_batch_b_id
    assert notice_payload["metrics"]["mae"] == 0.5
    workspace_report = loads_json(
        (workspace / notice_payload["pilot_scoring_report_workspace_path"]).read_text(encoding="utf-8"),
        {},
    )
    assert workspace_report["schema_version"] == "pilot_scoring_report.v1"
    assert workspace_report["metrics"]["mae"] == 0.5

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200, activity_response.text
    activity = activity_response.json()
    main_worker = next(worker for worker in activity["workers"] if worker["worker_id"] == "main-agent-session")
    assert main_worker["target_tab"] == "Leaderboard"
    assert main_worker["target_anchor"] == "pilot"
    assert main_worker["artifact_id"] == scoring_output["pilot_scoring_report_artifact_id"]
    assert "pilot observation" in main_worker["detail"].lower()

    pilot_index_response = client.get(f"/api/projects/{project_id}/pilot-deployments")
    assert pilot_index_response.status_code == 200, pilot_index_response.text
    pilot_index = pilot_index_response.json()
    assert len(pilot_index["deployments"]) == 1
    indexed_deployment = pilot_index["deployments"][0]
    assert indexed_deployment["id"] == deployment["id"]
    assert indexed_deployment["pipeline_artifact_id"] == pipeline_artifact_id
    assert indexed_deployment["experiment_run_id"] == "run_pilot_vertical"
    assert len(indexed_deployment["prediction_batches"]) == 2
    indexed_prediction_artifact_ids = {
        batch["predictions_artifact_id"] for batch in indexed_deployment["prediction_batches"]
    }
    assert prediction_a_output["prediction_batch_artifact_id"] in indexed_prediction_artifact_ids
    assert prediction_b_output["prediction_batch_artifact_id"] in indexed_prediction_artifact_ids
    indexed_prediction_batch_ids = {batch["id"] for batch in indexed_deployment["prediction_batches"]}
    assert prediction_a_output["pilot_prediction_batch_id"] in indexed_prediction_batch_ids
    assert prediction_b_output["pilot_prediction_batch_id"] in indexed_prediction_batch_ids
    assert len(indexed_deployment["outcome_batches"]) == 1
    assert indexed_deployment["scoring_reports"][0]["artifact"]["id"] == scoring_output["pilot_scoring_report_artifact_id"]
    assert indexed_deployment["scoring_reports"][0]["artifact"]["asset_type"] == "pilot_scoring_report"
    assert indexed_deployment["scoring_reports"][0]["prediction_batch_id"] == prediction_batch_b_id
    assert indexed_deployment["scoring_reports"][0]["metrics"]["mae"] == 0.5
    assert indexed_deployment["validation_audits"][0]["artifact"]["id"] == validation_audit_id
    assert indexed_deployment["validation_audits"][0]["artifact"]["asset_type"] == "validation_scheme_audit"
    assert scoring_output["pilot_scoring_report_artifact_id"] in indexed_deployment["validation_audits"][0]["scoring_report_artifact_ids"]
    assert indexed_deployment["validation_audits"][0]["scheme_verdict"] == "partially_confirmed"
    assert indexed_deployment["validation_audits"][0]["next_iteration_focus"] == (
        "Keep the same validation scheme and monitor the next pilot batch."
    )


def test_pipeline_bundle_download_returns_404_when_not_registered(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Missing pipeline bundle"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = client.app

    with app.state.session_factory() as db:
        run = ExperimentRun(
            id="run_without_pipeline_bundle",
            project_id=project_id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps(
                {
                    "model_id": "described_model",
                    "model_description": "A described model with no registered bundle yet.",
                    "features_used": ["feature_a"],
                }
            ),
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 3.0, "mae": 3.0}),
            summary_md="A described model with no registered bundle yet.",
        )
        db.add(run)
        db.commit()

    bundle_response = client.get("/api/experiment-runs/run_without_pipeline_bundle/pipeline-bundle")
    assert bundle_response.status_code == 404
    assert "Prediction pipeline bundle is not registered" in bundle_response.text


def test_agent_activity_uses_experiment_registration_chat_turn_as_human_summary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Experiment registration activity summary"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    registration_message = "Registered 2 model evaluations on the leaderboard."

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_experiment_registration_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_experiment_registration_summary",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": registration_message,
                "intent": {"type": "experiment_results_registered", "status": "ready"},
                "actions": [{"type": "open_surface", "target_tab": "Leaderboard", "target_anchor": "result-readout"}],
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_experiment_registration",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["human_description"]["summary"] == registration_message
    assert activity["workers"][0]["detail"] == registration_message
    assert activity["workers"][0]["target_tab"] == "Leaderboard"
    assert activity["workers"][0]["target_anchor"] == "result-readout"


def test_latest_codex_chat_update_links_registered_notebooks_and_leaderboard(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Chat output links"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        user = User(id="u_chat_output_links", email="chat-output-links@example.com", locale="ja-JP")
        project = db.get(Project, project_id)
        assert project is not None
        project.created_by = user.id
        session = AgentSession(
            id="ags_chat_output_links",
            project_id=project_id,
            session_type="main_autonomous",
            status="stopped",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Expose registered outputs from the latest progress update.",
        )
        db.add_all([user, session])
        notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="salary_eda_notebook",
            filename="salary_eda.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "agent_session_id": session.id},
        )
        run = ExperimentRun(
            id="run_chat_output_links",
            project_id=project_id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=json.dumps({"agent_session_id": session.id, "model_id": "hierarchical_median"}),
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 27531.0, "mae": 27531.0}),
            summary_md="Hierarchical median baseline.",
        )
        db.add(run)
        progress = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="codex_progress_without_actions",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": "分析とモデル評価を保存しました。",
                "intent": {"type": "autonomous_agent_progress_report", "status": "running"},
                "actions": [],
                "response_brief": {"schema_version": "progress.v1"},
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_codex_session_chat_update",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200, history_response.text
    progress_turn = next(turn for turn in history_response.json() if turn["artifact_id"] == progress.id)
    target_tabs = [action["target_tab"] for action in progress_turn["actions"]]
    assert "Notebooks" in target_tabs
    assert "Leaderboard" in target_tabs
    notebook_action = next(action for action in progress_turn["actions"] if action["target_tab"] == "Notebooks")
    assert notebook_action["artifact_id"] == notebook.id
    assert progress_turn["next_focus"]["target_tab"] == "Leaderboard"
    assert progress_turn["response_brief"]["linked_action_source"] == "registered_output_evidence"


def test_agent_activity_uses_notebook_update_chat_turn_as_target(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook update activity target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    notebook_message = "A native marimo notebook is ready for the latest data understanding work."

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_notebook_update_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_notebook_update_summary",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": notebook_message,
                "intent": {"type": "notebook_artifact_update", "status": "ready"},
                "actions": [
                    {
                        "type": "open_artifact",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "artifact_id": "art_notebook_source",
                    }
                ],
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_notebook_update",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["human_description"]["summary"] == notebook_message
    assert activity["workers"][0]["detail"] == notebook_message
    assert activity["workers"][0]["target_tab"] == "Notebooks"
    assert activity["workers"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert activity["workers"][0]["artifact_id"] == "art_notebook_source"
    assert activity["workers"][0]["artifact_ids"] == []


def test_agent_activity_rewrites_legacy_notebook_preview_action_to_native_source(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Legacy notebook preview activity"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_legacy_notebook_preview_activity",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep native marimo activity links.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="native_notebook_source_activity",
            filename="source.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        html_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="notebook_html",
            name="legacy_notebook_html_activity",
            filename="preview.html",
            text="<html><body>legacy preview</body></html>",
            metadata={"project_id": project_id, "notebook_artifact_id": notebook_artifact.id},
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="legacy_notebook_preview_activity_turn",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": "The notebook preview is ready.",
                "intent": {"type": "notebook_artifact_update", "status": "ready"},
                "actions": [
                    {
                        "type": "open_artifact",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "artifact_id": html_artifact.id,
                        "artifact_ids": [notebook_artifact.id, html_artifact.id],
                    }
                ],
                "response_brief": {
                    "schema_version": "notebook_artifact_update.v1",
                    "notebook_artifact_id": notebook_artifact.id,
                    "preview_artifact_id": html_artifact.id,
                    "status": "ready",
                },
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_notebook_update",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    worker = activity["workers"][0]
    assert "preview" not in worker["human_description"]["summary"].lower()
    assert worker["target_tab"] == "Notebooks"
    assert worker["target_anchor"] == "notebook-native-marimo-top"
    assert worker["artifact_id"] == notebook_artifact.id
    assert worker["artifact_ids"] == [notebook_artifact.id]


def test_agent_chat_history_surfaces_notebook_update_link(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook chat history link"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    notebook_message = "分析ノートブックを保存し、Tablex内のnative marimoで開けるようにしました。"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_notebook_history",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep notebooks visible.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_notebook_history_update",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "user_message": "",
                "assistant_message": notebook_message,
                "intent": {"type": "notebook_artifact_update", "status": "ready"},
                "actions": [
                    {
                        "type": "open_artifact",
                        "status": "ready",
                        "label": "ノートブックを開く",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "artifact_id": "art_notebook_source",
                        "artifact_ids": ["art_notebook_source"],
                    }
                ],
                "worker_events": [],
                "next_focus": {"target_tab": "Notebooks", "target_anchor": "notebook-preview-top", "label": "ノートブック"},
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_notebook_update",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    turn = next(item for item in history if item["assistant_message"] == notebook_message)
    assert turn["intent"]["type"] == "notebook_artifact_update"
    assert turn["actions"][0]["target_tab"] == "Notebooks"
    assert turn["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["actions"][0]["artifact_id"] == "art_notebook_source"
    assert turn["actions"][0]["artifact_ids"] == ["art_notebook_source"]
    assert turn["next_focus"]["target_tab"] == "Notebooks"
    assert turn["next_focus"]["target_anchor"] == "notebook-native-marimo-top"


def test_agent_chat_history_rewrites_legacy_notebook_preview_action_to_native_source(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Legacy notebook preview action"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        session = AgentSession(
            id="ags_legacy_notebook_preview",
            project_id=project_id,
            session_type="main_autonomous",
            status="succeeded",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep native marimo links.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="native_notebook_source",
            filename="source.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        html_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="notebook_html",
            name="legacy_notebook_html",
            filename="preview.html",
            text="<html><body>legacy preview</body></html>",
            metadata={"project_id": project_id, "notebook_artifact_id": notebook_artifact.id},
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="legacy_notebook_preview_turn",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "user_message": "",
                "assistant_message": "分析ノートブックを保存し、Tablex内で開けるプレビューを用意しました。",
                "intent": {"type": "notebook_artifact_update", "status": "ready"},
                "actions": [
                    {
                        "type": "open_artifact",
                        "status": "ready",
                        "label": "ノートブックを開く",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "artifact_id": html_artifact.id,
                        "artifact_ids": [notebook_artifact.id, html_artifact.id],
                    }
                ],
                "worker_events": [],
                "next_focus": {
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-preview-top",
                    "artifact_id": html_artifact.id,
                    "artifact_ids": [notebook_artifact.id, html_artifact.id],
                },
                "response_brief": {
                    "schema_version": "notebook_artifact_update.v1",
                    "notebook_artifact_id": notebook_artifact.id,
                    "preview_artifact_id": html_artifact.id,
                    "status": "ready",
                },
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_notebook_update",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    turn = next(item for item in history if item["intent"].get("type") == "notebook_artifact_update")
    assert "preview" not in turn["assistant_message"].lower()
    assert "プレビュー" not in turn["assistant_message"]
    assert turn["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["actions"][0]["artifact_id"] == notebook_artifact.id
    assert turn["actions"][0]["artifact_ids"] == [notebook_artifact.id]
    assert "preview" not in turn["actions"][0]["detail"].lower()
    assert "プレビュー" not in turn["actions"][0]["detail"]
    assert turn["next_focus"]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["next_focus"]["artifact_id"] == notebook_artifact.id
    assert turn["next_focus"]["artifact_ids"] == [notebook_artifact.id]
    assert turn["response_brief"]["notebook_artifact_id"] == notebook_artifact.id
    assert turn["response_brief"]["source_artifact_id"] == notebook_artifact.id
    assert "preview_artifact_id" not in turn["response_brief"]
    assert "html_artifact_id" not in turn["response_brief"]


def test_agent_chat_history_keeps_source_only_session_notebook_read_only(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook chat backfill"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        session = AgentSession(
            id="ags_source_only_notebook",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Backfill source-only notebooks.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_source_only_notebook",
            filename="source_only.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
                "workspace_relative_path": "notebooks/source_only.py",
                "notebook_kind": "data_understanding",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    notebook_turns = [
        item
        for item in history
        if item["intent"].get("type") == "notebook_artifact_update"
        and item["response_brief"]["notebook_artifact_id"] == notebook_artifact.id
    ]
    assert notebook_turns == []

    second_history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert second_history_response.status_code == 200
    second_history = second_history_response.json()
    second_notebook_turns = [
        item
        for item in second_history
        if item["intent"].get("type") == "notebook_artifact_update"
        and item["response_brief"]["notebook_artifact_id"] == notebook_artifact.id
    ]
    assert second_notebook_turns == []


def test_agent_chat_history_hides_resolved_notebook_context_attention(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Resolved notebook context attention"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        session = AgentSession(
            id="ags_resolved_notebook_context",
            project_id=project_id,
            session_type="main_autonomous",
            status="stopped",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep resolved attentions quiet.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="resolved_context_notebook",
            filename="source.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
                "workspace_relative_path": "notebooks/source.py",
                "notebook_kind": "data_understanding",
            },
        )
        duplicate_notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="resolved_context_notebook_duplicate",
            filename="source_duplicate.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
                "workspace_relative_path": "notebooks/source.py",
                "notebook_kind": "data_understanding",
            },
        )
        db.add(
            LineageEdge(
                id="le_resolved_notebook_context",
                project_id=project_id,
                from_asset_type="research_plan_revision",
                from_asset_id="rprev_resolved_notebook_context",
                to_asset_type="artifact",
                to_asset_id=notebook_artifact.id,
                relation_type="supports_plan_node",
                metadata_json=json.dumps({"node_id": "data_understanding", "role": "notebook_source"}),
            )
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="stale_notebook_context_attention",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "assistant_message": "Notebook context is not declared yet.",
                "intent": {
                    "type": "agent_attention_event",
                    "message_kind": "notebook_context_registration_needed",
                    "status": "needs_attention",
                },
                "actions": [],
                "response_brief": {
                    "schema_version": "agent_attention_event.v1",
                    "agent_session_id": session.id,
                    "attention_key": "notebook_context_registration_needed:test",
                    "status": "needs_attention",
                    "message_kind": "notebook_context_registration_needed",
                    "details": {"notebook_artifact_ids": [duplicate_notebook_artifact.id]},
                },
                "worker_events": [],
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_attention",
                "attention_key": "notebook_context_registration_needed:test",
                "message_kind": "notebook_context_registration_needed",
            },
        )
        db.commit()

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert not [
        item
        for item in history
        if item["intent"].get("message_kind") == "notebook_context_registration_needed"
    ]


def test_agent_activity_keeps_source_only_notebook_context_read_only(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook activity context backfill"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = tmp_path / "agent-session-workspace"

    with app.state.session_factory() as db:
        session = AgentSession(
            id="ags_activity_context_notebook",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Backfill notebook context from activity.",
            workspace_path=str(workspace),
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_source_only_activity_notebook",
            filename="source_only_activity.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
                "workspace_relative_path": "notebooks/source_only_activity.py",
                "notebook_kind": "data_understanding",
            },
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    context_entries = [
        entry for entry in list_inbox_entries(workspace) if entry["kind"] == "request" and entry["type"] == "notebook_context_request"
    ]
    assert context_entries == []
    assert all(notebook_artifact.id not in entry["content"] for entry in context_entries)

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    context_turns = [
        item
        for item in history_response.json()
        if item["intent"].get("message_kind") == "notebook_context_registration_needed"
    ]
    assert context_turns == []


def test_native_marimo_open_failure_is_recorded_in_chat_and_inbox(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fail_marimo_start(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("marimo runtime missing test failure")

    monkeypatch.setattr(routes_module, "start_or_get_native_marimo_session", fail_marimo_start)
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo failure visibility"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_marimo_failure"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_marimo_failure",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Repair notebook runtime failures.",
            workspace_path=str(workspace),
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="runtime_failure_notebook",
            filename="notebook.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={
                "project_id": project_id,
                "agent_session_id": session.id,
                "notebook_kind": "data_understanding",
            },
        )
        notebook_id = notebook_artifact.id
        db.commit()

    open_response = client.post(f"/api/analysis-notebooks/{notebook_id}/marimo-session")
    assert open_response.status_code == 400
    assert "marimo runtime missing test failure" in open_response.text

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    failure_turns = [item for item in history if item["intent"].get("type") == "native_marimo_open_failed"]
    assert len(failure_turns) == 1
    turn = failure_turns[0]
    assert turn["actions"][0]["target_tab"] == "Notebooks"
    assert turn["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["actions"][0]["artifact_id"] == notebook_id
    assert turn["next_focus"]["target_tab"] == "Notebooks"
    assert turn["next_focus"]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["next_focus"]["artifact_id"] == notebook_id
    assert turn["next_focus"]["artifact_ids"] == [notebook_id]
    assert "partial preview" not in turn["assistant_message"]
    assert "未完成のプレビュー" not in turn["assistant_message"]
    assert turn["response_brief"]["error_type"] == "RuntimeError"
    assert "marimo runtime missing test failure" in turn["response_brief"]["error_message"]

    runtime_entries = [
        entry for entry in list_inbox_entries(workspace) if entry["kind"] == "observation" and entry["type"] == "notebook_runtime_failure"
    ]
    assert len(runtime_entries) == 1
    assert notebook_id in runtime_entries[0]["content"]

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["workers"][0]["target_tab"] == "Notebooks"
    assert activity["workers"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert activity["workers"][0]["artifact_id"] == notebook_id
    marimo_workers = [
        worker for worker in activity["workers"] if worker.get("worker_id") == f"native-marimo-{notebook_id}"
    ]
    assert len(marimo_workers) == 1
    assert marimo_workers[0]["target_tab"] == "Notebooks"
    assert marimo_workers[0]["artifact_id"] == notebook_id
    assert "marimo runtime missing test failure" not in activity["workers"][0]["detail"]
    assert "repair target" in activity["workers"][0]["detail"]


def test_native_marimo_open_rejects_static_html_notebook_artifact(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("tabular_harness.services.marimo_sessions.marimo_available", lambda: True)
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Reject static notebook open"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        static_notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="static_html_notebook",
            filename="grandmaster_eda_static.html",
            text="<html><body>static notebook snapshot</body></html>",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        static_marimo_notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="marimo_notebook",
            name="static_html_marimo_notebook",
            filename="old_snapshot.html",
            text="<html><body>old notebook snapshot</body></html>",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        legacy_notebook_html = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="notebook_html",
            name="legacy_notebook_html_snapshot",
            filename="preview.html",
            text="<html><body>legacy notebook snapshot</body></html>",
            metadata={"project_id": project_id, "notebook_artifact_id": static_notebook.id},
        )
        execution_html = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="notebook_execution_html",
            name="legacy_notebook_execution_html_snapshot",
            filename="execution_preview.html",
            text="<html><body>legacy execution snapshot</body></html>",
            metadata={"project_id": project_id, "notebook_artifact_id": static_notebook.id},
        )
        notebook_id = static_notebook.id
        marimo_notebook_id = static_marimo_notebook.id
        legacy_notebook_html_id = legacy_notebook_html.id
        execution_html_id = execution_html.id
        db.commit()

    open_response = client.post(f"/api/analysis-notebooks/{notebook_id}/marimo-session")
    assert open_response.status_code == 400
    assert "Python marimo source file" in open_response.text

    preview_response = client.get(f"/api/artifacts/{notebook_id}/preview")
    assert preview_response.status_code == 400
    assert "native marimo Python source" in preview_response.text

    inline_preview_response = client.get(f"/api/artifacts/{notebook_id}/inline-preview")
    assert inline_preview_response.status_code == 400
    assert "native marimo Python source" in inline_preview_response.text

    marimo_preview_response = client.get(f"/api/artifacts/{marimo_notebook_id}/preview")
    assert marimo_preview_response.status_code == 400
    assert "native marimo Python source" in marimo_preview_response.text

    marimo_inline_preview_response = client.get(f"/api/artifacts/{marimo_notebook_id}/inline-preview")
    assert marimo_inline_preview_response.status_code == 400
    assert "native marimo Python source" in marimo_inline_preview_response.text

    legacy_html_preview_response = client.get(f"/api/artifacts/{legacy_notebook_html_id}/preview")
    assert legacy_html_preview_response.status_code == 400
    assert "Static HTML notebook snapshots are not notebook artifacts" in legacy_html_preview_response.text

    legacy_html_detail_response = client.get(f"/api/artifacts/{legacy_notebook_html_id}")
    assert legacy_html_detail_response.status_code == 400
    assert "Static HTML notebook snapshots are not Tablex artifacts" in legacy_html_detail_response.text

    legacy_html_download_response = client.get(f"/api/artifacts/{legacy_notebook_html_id}/download")
    assert legacy_html_download_response.status_code == 400
    assert "Static HTML notebook snapshots are not Tablex artifacts" in legacy_html_download_response.text

    legacy_html_inline_preview_response = client.get(f"/api/artifacts/{legacy_notebook_html_id}/inline-preview")
    assert legacy_html_inline_preview_response.status_code == 400
    assert "Static HTML notebook snapshots are not notebook artifacts" in legacy_html_inline_preview_response.text

    execution_html_preview_response = client.get(f"/api/artifacts/{execution_html_id}/preview")
    assert execution_html_preview_response.status_code == 400
    assert "Static HTML notebook snapshots are not notebook artifacts" in execution_html_preview_response.text

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts?latest_only=false")
    assert artifacts_response.status_code == 200
    listed_asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert "notebook_html" not in listed_asset_types
    assert "notebook_execution_html" not in listed_asset_types

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    failure_turns = [item for item in history_response.json() if item["intent"].get("type") == "native_marimo_open_failed"]
    assert len(failure_turns) == 1
    turn = failure_turns[0]
    assert turn["actions"][0]["target_tab"] == "Notebooks"
    assert turn["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["actions"][0]["artifact_id"] == notebook_id
    assert turn["response_brief"]["error_type"] == "ValueError"
    assert "Python marimo source file" in turn["response_brief"]["error_message"]


def test_native_marimo_open_returns_session_payload(tmp_path: Path, monkeypatch: Any) -> None:
    class FakeNativeMarimoSession:
        def __init__(self, artifact_id: str, project_id: str | None) -> None:
            self.artifact_id = artifact_id
            self.project_id = project_id

        def to_dict(self) -> dict[str, Any]:
            return {
                "schema_version": "native_marimo_session.v1",
                "session_id": "mos_test",
                "artifact_id": self.artifact_id,
                "project_id": self.project_id,
                "proxy_url": "/api/marimo-sessions/mos_test/proxy/",
                "base_url": "/api/marimo-sessions/mos_test/proxy",
                "status": "running",
            }

    def fake_marimo_start(*, artifact: Artifact, settings: Settings) -> FakeNativeMarimoSession:
        assert settings.app_display_name == "Tablex"
        return FakeNativeMarimoSession(artifact.id, artifact.project_id)

    monkeypatch.setattr(routes_module, "start_or_get_native_marimo_session", fake_marimo_start)
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo open"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="native_marimo_notebook",
            filename="notebook.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        notebook_id = notebook_artifact.id
        db.commit()

    response = client.post(f"/api/analysis-notebooks/{notebook_id}/marimo-session")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "native_marimo_session.v1"
    assert payload["artifact_id"] == notebook_id
    assert payload["project_id"] == project_id
    assert payload["proxy_url"] == "/api/marimo-sessions/mos_test/proxy/"
    assert payload["status"] == "running"


def test_native_marimo_opens_figure_rich_notebook_through_proxy(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo success"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace" / "native_marimo_success"
    notebook_dir = workspace / "notebooks"
    notebook_dir.mkdir(parents=True)
    notebook_path = notebook_dir / "figure_rich_report.py"
    notebook_path.write_text(
        "import marimo\n\n"
        "app = marimo.App(width='medium')\n\n"
        "@app.cell\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    import pandas as pd\n"
        "    import plotly.express as px\n"
        "    _df = pd.DataFrame({'segment': ['A', 'B', 'C'], 'value': [3, 8, 5], 'rate': [0.2, 0.5, 0.3]})\n"
        "    _bar = px.bar(_df, x='segment', y='value', title='Segment value')\n"
        "    _scatter = px.scatter(_df, x='value', y='rate', text='segment', title='Value-rate relationship')\n"
        "    _line = px.line(_df, x='segment', y='rate', markers=True, title='Segment rate')\n"
        "    mo.vstack([\n"
        "        mo.md('# Figure-rich marimo report'),\n"
        "        _bar,\n"
        "        _scatter,\n"
        "        _line,\n"
        "        mo.ui.table(_df),\n"
        "    ])\n"
        "    return\n",
        encoding="utf-8",
    )

    with app.state.session_factory() as db:
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="figure_rich_native_marimo_report",
            filename="figure_rich_report.py",
            text=notebook_path.read_text(encoding="utf-8"),
            metadata={
                "project_id": project_id,
                "workspace_path": str(notebook_path),
                "workspace_dir": str(workspace),
                "workspace_relative_path": "notebooks/figure_rich_report.py",
                "notebook_kind": "data_understanding",
                "quality_manifest": {
                    "schema_version": "tablex_notebook_quality_manifest.v1",
                    "figure_count": 3,
                    "table_count": 1,
                    "key_findings": ["Synthetic figure-rich notebook opens through native marimo."],
                    "read_order": [{"label": "Figure-rich report"}],
                    "data_sources_used": ["synthetic fixture"],
                    "limitations": ["Synthetic runtime smoke."],
                },
            },
        )
        notebook_id = notebook_artifact.id
        db.commit()

    session_response = client.post(f"/api/analysis-notebooks/{notebook_id}/marimo-session")
    assert session_response.status_code == 200, session_response.text
    session_payload = session_response.json()
    assert session_payload["schema_version"] == "native_marimo_session.v1"
    assert session_payload["artifact_id"] == notebook_id
    session_id = session_payload["session_id"]
    status_payload = session_payload
    deadline = time.monotonic() + 15
    while status_payload["status"] == "starting" and time.monotonic() < deadline:
        time.sleep(0.2)
        status_response = client.get(f"/api/marimo-sessions/{session_id}")
        assert status_response.status_code == 200, status_response.text
        status_payload = status_response.json()
    assert status_payload["status"] == "running", status_payload
    assert status_payload["runtime"]["has_error"] is False

    proxy_response = client.get(status_payload["proxy_url"])
    assert proxy_response.status_code == 200, proxy_response.text[:500]
    assert "text/html" in proxy_response.headers.get("content-type", "")
    assert b"marimo" in proxy_response.content[:20_000].lower()

    stop_response = client.delete(f"/api/marimo-sessions/{session_id}")
    assert stop_response.status_code == 200
    assert stop_response.json()["stopped"] is True


def test_native_marimo_opens_notebook_that_reads_session_data_access(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo data access"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = tmp_path / "agent_workspace" / "native_marimo_data_access"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        dataset_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="native_data_access_dataset",
            filename="train.csv",
            text="segment,value,rate\nA,3,0.2\nB,8,0.5\nC,5,0.3\n",
            metadata={"project_id": project_id},
        )
        dataset = DatasetSnapshot(
            id="ds_native_data_access",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            source_ref="train.csv",
            row_count=3,
            column_count=3,
            schema_hash="native_data_access_schema",
        )
        session = AgentSession(
            id="ags_native_data_access",
            project_id=project_id,
            session_type="main_autonomous",
            goal_text="Open a native marimo notebook that reads Tablex session data links.",
            workspace_path=str(workspace),
        )
        db.add_all([dataset, session])
        db.flush()
        prepare_session_workspace(db, store=app.state.artifact_store, project=project, session=session)
        notebook_dir = workspace / "notebooks"
        notebook_dir.mkdir(parents=True, exist_ok=True)
        notebook_path = notebook_dir / "data_access_report.py"
        notebook_path.write_text(
            "import marimo\n\n"
            "app = marimo.App(width='medium')\n\n"
            "@app.cell\n"
            "def _():\n"
            "    from pathlib import Path\n"
            "    import marimo as mo\n"
            "    import pandas as pd\n"
            "    import plotly.express as px\n"
            "    _data_path = Path('.tablex/data/ds_native_data_access__train.csv')\n"
            "    _df = pd.read_csv(_data_path)\n"
            "    _bar = px.bar(_df, x='segment', y='value', title='Value by segment')\n"
            "    _scatter = px.scatter(_df, x='value', y='rate', text='segment', title='Value and rate')\n"
            "    mo.vstack([mo.md('# Data access report'), _bar, _scatter, mo.ui.table(_df)])\n"
            "    return\n",
            encoding="utf-8",
        )
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="native_marimo_data_access_report",
            filename="data_access_report.py",
            text=notebook_path.read_text(encoding="utf-8"),
            metadata={
                "project_id": project_id,
                "workspace_path": str(notebook_path),
                "workspace_dir": str(workspace),
                "workspace_relative_path": "notebooks/data_access_report.py",
                "notebook_kind": "data_understanding",
                "dataset_snapshot_id": dataset.id,
                "quality_manifest": {
                    "schema_version": "tablex_notebook_quality_manifest.v1",
                    "figure_count": 2,
                    "table_count": 1,
                    "key_findings": ["The notebook reads the session data link at runtime."],
                    "read_order": [{"label": "Data access report"}],
                    "data_sources_used": [dataset.id],
                    "limitations": ["Synthetic runtime smoke."],
                },
            },
        )
        notebook_id = notebook_artifact.id
        db.commit()

    assert (workspace / ".tablex" / "data" / "ds_native_data_access__train.csv").exists()
    session_response = client.post(f"/api/analysis-notebooks/{notebook_id}/marimo-session")
    assert session_response.status_code == 200, session_response.text
    session_payload = session_response.json()
    session_id = session_payload["session_id"]
    status_payload = session_payload
    deadline = time.monotonic() + 15
    while status_payload["status"] == "starting" and time.monotonic() < deadline:
        time.sleep(0.2)
        status_response = client.get(f"/api/marimo-sessions/{session_id}")
        assert status_response.status_code == 200, status_response.text
        status_payload = status_response.json()
    assert status_payload["status"] == "running", status_payload
    assert status_payload["runtime"]["has_error"] is False

    proxy_response = client.get(status_payload["proxy_url"])
    assert proxy_response.status_code == 200, proxy_response.text[:500]
    assert "text/html" in proxy_response.headers.get("content-type", "")
    assert b"marimo" in proxy_response.content[:20_000].lower()

    stop_response = client.delete(f"/api/marimo-sessions/{session_id}")
    assert stop_response.status_code == 200
    assert stop_response.json()["stopped"] is True


def test_native_marimo_runtime_error_is_recorded_in_chat_once(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo runtime"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="runtime_error_notebook",
            filename="notebook.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        notebook_id = notebook_artifact.id
        db.commit()

    class FakeNativeMarimoSession:
        def __init__(self, artifact_id: str, project_id: str) -> None:
            self.id = "mos_runtime_error"
            self.artifact_id = artifact_id
            self.project_id = project_id

        def to_dict(self) -> dict[str, Any]:
            return {
                "schema_version": "native_marimo_session.v1",
                "session_id": self.id,
                "artifact_id": self.artifact_id,
                "project_id": self.project_id,
                "proxy_url": f"/api/marimo-sessions/{self.id}/proxy/",
                "base_url": f"/api/marimo-sessions/{self.id}/proxy",
                "status": "running",
                "started_at": utc_now().isoformat(),
                "last_accessed_at": utc_now().isoformat(),
                "runtime": {
                    "has_error": True,
                    "error_excerpt": "Traceback (most recent call last):\nNameError: name 'true' is not defined",
                },
            }

    monkeypatch.setattr(
        routes_module,
        "native_marimo_session",
        lambda session_id: FakeNativeMarimoSession(notebook_id, project_id),
    )

    first_response = client.get("/api/marimo-sessions/mos_runtime_error")
    assert first_response.status_code == 200
    assert first_response.json()["runtime"]["has_error"] is True
    second_response = client.get("/api/marimo-sessions/mos_runtime_error")
    assert second_response.status_code == 200

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    runtime_turns = [
        item for item in history_response.json()
        if item["intent"].get("type") == "native_marimo_runtime_failed"
    ]
    assert len(runtime_turns) == 1
    turn = runtime_turns[0]
    assert turn["actions"][0]["target_tab"] == "Notebooks"
    assert turn["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["actions"][0]["artifact_id"] == notebook_id
    assert isinstance(turn["response_brief"]["notebook_source_hash"], str)
    assert len(turn["response_brief"]["notebook_source_hash"]) == 64
    assert "NameError" in turn["response_brief"]["error_message"]


def test_native_marimo_runtime_error_excerpt_prefers_traceback(tmp_path: Path) -> None:
    stderr_path = tmp_path / "stderr.log"
    stderr_path.write_text(
        "\n".join(
            [
                "2026-07-04T11:25:16Z ERROR codex_rmcp_client::logging_client_handler: MCP server log message",
                "Traceback (most recent call last):",
                '  File "/tmp/notebook.py", line 27, in <module>',
                f"    payload = {{'very_long_json_like_line': '{'x' * 5000}', 'reference_only': true}}",
                "NameError: name 'true' is not defined. Did you mean: 'True'?",
                "[E 250704 11:25:17 runtime:123] An ancestor raised an exception (NameError):",
            ]
        ),
        encoding="utf-8",
    )
    session = NativeMarimoSession(
        id="mos_test",
        artifact_id="art_notebook",
        project_id="p_test",
        notebook_path=tmp_path / "notebook.py",
        port=18888,
        process=cast(Any, SimpleNamespace(poll=lambda: None)),
        base_url="/api/marimo-sessions/mos_test/proxy",
        proxy_url="/api/marimo-sessions/mos_test/proxy/",
        workdir=tmp_path,
        started_at=utc_now(),
        last_accessed_at=utc_now(),
        stdout_path=tmp_path / "stdout.log",
        stderr_path=stderr_path,
        source_hash="test_source_hash",
    )

    excerpt = session.runtime_error_excerpt()

    assert excerpt is not None
    assert excerpt.startswith("Traceback (most recent call last):")
    assert "NameError: name 'true' is not defined" in excerpt
    assert "repeated" in excerpt
    assert "x" * 100 not in excerpt
    assert len(excerpt) <= 4000


def test_native_marimo_session_reports_starting_without_blocking(tmp_path: Path, monkeypatch: Any) -> None:
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    session = NativeMarimoSession(
        id="mos_starting",
        artifact_id="art_notebook",
        project_id="p_test",
        notebook_path=tmp_path / "notebook.py",
        port=18888,
        process=cast(Any, SimpleNamespace(poll=lambda: None)),
        base_url="/api/marimo-sessions/mos_starting/proxy",
        proxy_url="/api/marimo-sessions/mos_starting/proxy/",
        workdir=tmp_path,
        started_at=utc_now(),
        last_accessed_at=utc_now(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        source_hash="test_source_hash",
    )
    monkeypatch.setattr(marimo_sessions_module, "_http_ready", lambda _session, timeout=0.05: False)

    payload = session.to_dict()

    assert payload["status"] == "starting"
    assert payload["runtime"]["has_error"] is False


def test_native_marimo_failed_session_records_open_failure_from_status_endpoint(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Native marimo failed status"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        notebook_artifact = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="startup_failed_notebook",
            filename="notebook.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        notebook_id = notebook_artifact.id
        db.commit()

    class FakeFailedNativeMarimoSession:
        def __init__(self, artifact_id: str, project_id: str) -> None:
            self.id = "mos_failed_startup"
            self.artifact_id = artifact_id
            self.project_id = project_id

        def to_dict(self) -> dict[str, Any]:
            return {
                "schema_version": "native_marimo_session.v1",
                "session_id": self.id,
                "artifact_id": self.artifact_id,
                "project_id": self.project_id,
                "proxy_url": f"/api/marimo-sessions/{self.id}/proxy/",
                "base_url": f"/api/marimo-sessions/{self.id}/proxy",
                "status": "failed",
                "started_at": utc_now().isoformat(),
                "last_accessed_at": utc_now().isoformat(),
                "runtime": {
                    "has_error": True,
                    "error_excerpt": "marimo process exited before the notebook became available.",
                },
            }

    monkeypatch.setattr(
        routes_module,
        "native_marimo_session",
        lambda session_id: FakeFailedNativeMarimoSession(notebook_id, project_id),
    )

    response = client.get("/api/marimo-sessions/mos_failed_startup")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    open_failure_turns = [
        item for item in history_response.json()
        if item["intent"].get("type") == "native_marimo_open_failed"
    ]
    assert len(open_failure_turns) == 1
    turn = open_failure_turns[0]
    assert turn["actions"][0]["target_tab"] == "Notebooks"
    assert turn["actions"][0]["artifact_id"] == notebook_id
    assert turn["response_brief"]["error_type"] == "RuntimeError"


def test_runtime_error_chat_summary_keeps_terminal_exception() -> None:
    error_message = "\n".join(
        [
            "Traceback (most recent call last):",
            f"  payload = {{'long': '{'x' * 5000}', 'reference_only': true}}",
            "NameError: name 'true' is not defined. Did you mean: 'True'?",
            "[E 250704 11:25:17 runtime:123] An ancestor raised an exception (NameError):",
        ]
    )

    summary = summarize_runtime_error_for_chat(error_message)

    assert summary.startswith("Traceback (most recent call last):")
    assert "NameError: name 'true' is not defined" in summary
    assert len(summary) <= 900


def test_agent_activity_surfaces_runner_retry_state(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Runner retry state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_retry_state",
            project_id=project_id,
            session_type="main_autonomous",
            status="waiting_for_runner",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_error="Codex CLI is not available.",
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_retry_scheduled",
            role="harness",
            title="Codex runner retry scheduled",
            content="Codex CLI is unavailable. Tablex will retry.",
            payload={"retry_delay_seconds": 120, "failure_kind": "runner_unavailable"},
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["state"] == "agent_scheduled"
    assert activity["turn_state"]["label"] == "Waiting to resume"
    assert "120s" in activity["turn_state"]["detail"]
    assert "runner" not in activity["turn_state"]["label"].lower()
    assert activity["turn_state"]["retry_state"]["event_type"] == "runner_retry_scheduled"
    assert activity["turn_state"]["retry_state"]["event_index"] == 0
    assert activity["turn_state"]["retry_state"]["created_at"]
    assert activity["turn_state"]["retry_state"]["retry_delay_seconds"] == 120
    assert activity["turn_state"]["retry_state"]["failure_kind"] == "runner_unavailable"
    assert activity["workers"][0]["status"] == "waiting_for_runner"
    assert activity["workers"][0]["headline"] == "Waiting to resume"
    assert activity["workers"][0]["retry_state"]["retry_delay_seconds"] == 120
    assert activity["workers"][0]["retry_state"]["failure_kind"] == "runner_unavailable"


def test_project_update_starts_main_session_after_target_change(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Update restart"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        db.commit()

    update_response = client.patch(f"/api/projects/{project_id}", json={"target_column": "salary"})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["target_column"] == "salary"

    with app.state.session_factory() as db:
        task_specs = db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "task_spec")
            .order_by(Artifact.created_at.desc())
        ).all()
        assert len(task_specs) == 1
        task_spec = loads_json(artifact_primary_path(task_specs[0]).read_text(encoding="utf-8"), {})
        assert task_spec["schema_version"] == "task_spec.v1"
        assert task_spec["status"] == "user_confirmed"
        assert task_spec["objective_text"] == "salary"
        assert task_spec["task_shape"] == "other"
        assert task_spec["targets"] == [{"column": "salary", "derivation": None}]

    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["session_type"] == "main_autonomous"
    assert "salary" in session["goal_text"]


def test_agent_activity_turn_state_flags_stale_codex_runner_without_local_process(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Stale runner turn state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Run Codex",
                    "summary": "This should be backed by a local codex exec process.",
                }
            },
        )
        old_timestamp = utc_now() - timedelta(minutes=2)
        job.status = "running"
        job.locked_by = "test-worker"
        job.started_at = old_timestamp
        job.updated_at = old_timestamp
        job_id = job.id
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    turn_state = activity_response.json()["turn_state"]
    assert turn_state["state"] == "stale_runner"
    assert turn_state["owner"] == "system"
    assert turn_state["input_attention"] is False
    assert turn_state["active_job_id"] == job_id


def test_agent_activity_does_not_count_heartbeat_waiting_on_active_codex_runner(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Heartbeat with active runner"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        runner_job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Run Codex on the main objective",
                    "summary": "Codex is doing the autonomous data-science work.",
                }
            },
        )
        runner_job.status = "running"
        runner_job.locked_by = "test-worker"
        runner_job.started_at = utc_now()
        create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"active_child_job_ids_at_schedule_time": [runner_job.id]},
            context={
                "human_description": {
                    "title": "Continue the main Full Auto session",
                    "summary": "Heartbeat waiting for Codex to return control.",
                }
            },
            run_after=utc_now() - timedelta(seconds=1),
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 1
    workers_by_type = {worker["job_type"]: worker for worker in activity["workers"]}
    assert workers_by_type["run_planned_agent_task_codex"]["active"] is True
    assert workers_by_type["continue_autonomous_session"]["active"] is False


def test_autonomous_continuation_does_not_backoff_after_recent_codex_failure(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Runner failure no backoff"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        failed_job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            input_payload={"agent_task_contract_artifact_id": "art_failed_contract"},
        )
        failed_job.status = "failed"
        failed_job.error_message = "Codex CLI failed."
        failed_job.started_at = utc_now()
        failed_job.ended_at = utc_now()
        failed_job.updated_at = utc_now()
        continuation_job = create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"runner_mode": "codex_cli_if_available", "locale": "ja-JP"},
        )
        db.flush()

        output = continue_autonomous_session_handler(db, continuation_job, app.state.artifact_store)
        assert output["status"] in {"advanced", "waiting_for_data"}
        assert output.get("recent_failed_codex_job_id") is None
        assert output.get("status") != "runner_backoff"
        assert output["session_continuation_job_id"]
        assert failed_job.status == "failed"


def test_approval_based_start_creates_real_planning_evidence_with_dataset(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Autonomous with data"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,value"] + [f"{index},{'a' if index % 2 else 'b'},{index * 3}" for index in range(1, 31)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("autonomous.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "harness_only", "autonomy_mode": "approval_based"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["status"] == "queued"
    assert queued_job["output"]["schema_version"] == "autonomous_loop_start_queued.v1"
    job = wait_for_job_status(client, queued_job["id"], statuses={"succeeded"})
    output = job["output"]
    assert output["status"] == "advanced"
    labels = {step["label"] for step in output["steps"]}
    assert {
        "data_quality",
        "eda_review",
        "research_brief",
        "approach_ideas",
        "agent_task_contract",
        "agent_workspace",
        "evaluation_spec",
        "reflection",
    }.issubset(labels)
    assert output["artifact_ids"]
    assert output["next_human_boundary"]
    assert output["interventions"]
    assert output["interventions"][0]["kind"] == "target_definition"
    target_step = next(step for step in output["steps"] if step["label"] == "target_definition")
    assert target_step["status"] == "needs_approval"
    evaluation_step = next(step for step in output["steps"] if step["label"] == "evaluation_spec")
    assert evaluation_step["status"] == "deferred"

    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    asset_types = {artifact["asset_type"] for artifact in artifacts}
    assert "data_quality_gate" in asset_types
    assert "eda_review_bundle" in asset_types
    assert "agent_task_contract" in asset_types
    assert "agent_workspace_manifest" in asset_types

    contract_steps = [step for step in output["steps"] if step["label"] == "agent_task_contract"]
    assert contract_steps[-1]["entity_ids"]["task_type"] == "target_definition_review"


def test_full_auto_codex_start_creates_main_agent_session_transcript(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fake_supervisor(
        session_factory: Any,
        store: LocalArtifactStore,
        *,
        project_id: str,
        session_id: str,
        agent_model: str | None = None,
        **_: Any,
    ) -> None:
        del project_id, agent_model
        with session_factory() as db:
            from tabular_harness.models.entities import AgentSession

            session = db.get(AgentSession, session_id)
            assert session is not None
            session.status = "running"
            workspace_path = Path(session.workspace_path or "")
            append_runner_stream_to_workspace(
                workspace_path,
                stream_name="stdout",
                line='{"type":"thread.started","thread_id":"thread_test"}\n',
            )
            append_runner_stream_to_workspace(
                workspace_path,
                stream_name="stdout",
                line='{"type":"item.completed","item":{"type":"agent_message","text":"I am continuing."}}\n',
            )
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="thread.started",
                role="runner",
                title="Thread started",
                content=None,
                payload={"type": "thread.started", "thread_id": "thread_test"},
            )
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="item.completed",
                role="runner",
                title="Codex message",
                content="I am continuing the main autonomous session.",
                payload={"type": "item.completed", "item": {"type": "agent_message", "text": "I am continuing."}},
            )
            store_json_artifact(
                db,
                store,
                project_id=session.project_id,
                asset_type="agent_chat_turn",
                name=f"agent_session_chat_update_{session.id}",
                filename="agent_chat_turn.json",
                payload={
                    "schema_version": "agent_chat_turn.v1",
                    "project_id": session.project_id,
                    "user_message": "",
                    "assistant_message": "データ理解の根拠を確認し、次に評価設計へ進む準備をしています。",
                    "intent": {"type": "autonomous_agent_progress_report"},
                    "actions": [],
                    "action_summary": {},
                },
                metadata={
                    "project_id": session.project_id,
                    "agent_session_id": session.id,
                    "source": "main_codex_session_chat_update",
                },
            )
            db.commit()

    monkeypatch.setattr("tabular_harness.api.routes.run_main_agent_session_supervisor", fake_supervisor)
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Session Full Auto"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("session.csv", b"x,y\n1,0\n2,1\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    start_job = start_response.json()
    assert start_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = start_job["output"]["agent_session_id"]

    session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"
    assert session["observed_codex_process_count"] == 0
    assert session["pid_is_observed_codex_process"] is False
    assert session["observed_runner_state"] == "supervisor_should_continue"

    transcript_response = client.get(f"/api/projects/{project_id}/agent-session/transcript")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert [event["event_type"] for event in transcript][-2:] == ["thread.started", "item.completed"]
    assert transcript[-1]["source"] == "codex_cli"
    assert transcript[-1]["content"] == "I am continuing the main autonomous session."

    delta_response = client.get(
        f"/api/projects/{project_id}/agent-session/transcript?since_index={transcript[-2]['event_index']}"
    )
    assert delta_response.status_code == 200
    delta = delta_response.json()
    assert [event["event_index"] for event in delta] == [transcript[-1]["event_index"]]

    empty_delta_response = client.get(
        f"/api/projects/{project_id}/agent-session/transcript?since_index={transcript[-1]['event_index']}"
    )
    assert empty_delta_response.status_code == 200
    assert empty_delta_response.json() == []

    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript")
    assert raw_transcript_response.status_code == 200
    raw_transcript = raw_transcript_response.json()
    assert raw_transcript["session_id"] == session_id
    assert raw_transcript["stdout_line_count"] == 2
    assert raw_transcript["stderr_line_count"] == 0
    assert raw_transcript["stdout_download_url"].endswith("/agent-session/raw-transcript/stdout/download")
    assert raw_transcript["stderr_download_url"].endswith("/agent-session/raw-transcript/stderr/download")
    assert raw_transcript["stdout_tail"][-1].startswith('{"type":"item.completed"')
    assert raw_transcript["stdout_tail_lines"][-1]["line_number"] == 2
    assert raw_transcript["stdout_tail_lines"][-1]["parsed"]["type"] == "item.completed"
    assert raw_transcript["stdout_tail_lines"][-1]["truncated"] is False
    assert raw_transcript["stderr_tail_lines"] == []
    raw_stdout_download = client.get(raw_transcript["stdout_download_url"])
    assert raw_stdout_download.status_code == 200
    assert raw_stdout_download.headers["content-type"].startswith("text/plain")
    assert raw_stdout_download.text.startswith('{"type":"thread.started"')
    invalid_raw_download = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript/stdin/download")
    assert invalid_raw_download.status_code == 404

    raw_path = Path(session["workspace_path"]) / ".tablex" / "codex_raw_transcript.jsonl"
    raw_path.write_text(
        '{"type":"item.completed","item":{"type":"command_execution","aggregated_output":"'
        + ("x" * 20_000)
        + '"}}\n',
        encoding="utf-8",
    )
    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript")
    assert raw_transcript_response.status_code == 200
    large_tail = raw_transcript_response.json()["stdout_tail_lines"][-1]
    assert large_tail["truncated"] is True
    assert large_tail["original_length"] > 20_000
    assert len(large_tail["text"]) < large_tail["original_length"]
    assert large_tail["parsed"]["type"] == "item.completed"
    assert "[truncated" in large_tail["parsed"]["item"]["aggregated_output"]

    raw_path.write_text(
        "\n".join(f'{{"type":"item.completed","index":{index}}}' for index in range(1, 1501)) + "\n",
        encoding="utf-8",
    )
    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript?limit=3")
    assert raw_transcript_response.status_code == 200
    long_raw = raw_transcript_response.json()
    assert long_raw["stdout_line_count"] == 1500
    assert [line["line_number"] for line in long_raw["stdout_tail_lines"]] == [1498, 1499, 1500]
    assert [line["parsed"]["index"] for line in long_raw["stdout_tail_lines"]] == [1498, 1499, 1500]

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    main_worker = next(worker for worker in activity["workers"] if worker.get("agent_session_id") == session_id)
    assert activity["turn_state"]["raw_transcript"]["session_id"] == session_id
    assert activity["turn_state"]["raw_transcript"]["stdout_line_count"] >= 1
    assert activity["turn_state"]["raw_transcript"]["stderr_line_count"] == 0
    assert activity["turn_state"]["raw_transcript"]["updated_at"]
    assert main_worker["raw_transcript"]["stdout_line_count"] == activity["turn_state"]["raw_transcript"]["stdout_line_count"]
    assert "データ理解の根拠" in main_worker["detail"]
    assert "データ理解の根拠" in main_worker["human_description"]["summary"]


def test_agent_chat_appends_user_instruction_to_active_main_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Session chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "評価指標はROC-AUCで考えてください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text

    transcript = client.get(f"/api/projects/{project_id}/agent-session/transcript").json()
    user_events = [event for event in transcript if event["source"] == "user" and event["event_type"] == "user_instruction"]
    assert user_events
    assert user_events[-1]["content"] == "評価指標はROC-AUCで考えてください"


def test_worker_acquire_handles_sqlite_naive_run_after(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Run-after worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        created = create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"reason": "timezone-regression"},
            run_after=utc_now() - timedelta(seconds=1),
        )
        created_id = created.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="timezone-test-worker", job_types={"continue_autonomous_session"})
        assert acquired is not None
        assert acquired.id == created_id


def test_worker_acquire_skips_currently_locked_queued_job(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Locked worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        locked = create_job(db, job_type="profile_dataset", project_id=project_id, priority=100)
        locked.locked_by = "active-worker"
        locked.locked_at = utc_now()
        available = create_job(db, job_type="profile_dataset", project_id=project_id, priority=10)
        available_id = available.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="second-worker", job_types={"profile_dataset"})
        assert acquired is not None
        assert acquired.id == available_id
        assert acquired.locked_by == "second-worker"


def test_worker_acquire_recovers_stale_queued_lock(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Stale lock worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        stale = create_job(db, job_type="profile_dataset", project_id=project_id, priority=100)
        stale.locked_by = "dead-worker"
        stale.locked_at = utc_now() - timedelta(minutes=11)
        stale_id = stale.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="recovery-worker", job_types={"profile_dataset"})
        assert acquired is not None
        assert acquired.id == stale_id
        assert acquired.locked_by == "recovery-worker"


def test_reap_stale_running_jobs_times_out_orphaned_running_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Stale running cleanup"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    now = utc_now()
    with session_factory() as db:
        stale_chat = create_job(db, job_type="agent_chat_turn", project_id=project_id, priority=90)
        stale_chat.status = "running"
        stale_chat.locked_by = "dead-worker"
        stale_chat.locked_at = now - timedelta(minutes=6)
        stale_continuation = create_job(db, job_type="continue_autonomous_session", project_id=project_id, priority=45)
        stale_continuation.status = "running"
        stale_continuation.locked_by = "dead-worker"
        stale_continuation.locked_at = now - timedelta(minutes=11)
        stale_upload = create_job(db, job_type="upload_data_bundle", project_id=project_id, priority=85)
        stale_upload.status = "running"
        stale_upload.locked_by = "dead-worker"
        stale_upload.locked_at = now - timedelta(hours=11)
        stale_upload.updated_at = now - timedelta(hours=10)
        stale_primary = create_job(db, job_type="select_primary_table", project_id=project_id, priority=80)
        stale_primary.status = "running"
        stale_primary.locked_by = "dead-worker"
        stale_primary.locked_at = now - timedelta(minutes=20)
        stale_primary.updated_at = now - timedelta(minutes=16)
        old_training = create_job(db, job_type="train_model_candidates", project_id=project_id, priority=60)
        old_training.status = "running"
        old_training.locked_by = "busy-worker"
        old_training.locked_at = now - timedelta(hours=2)
        fresh_chat = create_job(db, job_type="agent_chat_turn", project_id=project_id, priority=90)
        fresh_chat.status = "running"
        fresh_chat.locked_by = "active-worker"
        fresh_chat.locked_at = now - timedelta(minutes=1)
        active_upload = create_job(db, job_type="upload_data_bundle", project_id=project_id, priority=85)
        active_upload.status = "running"
        active_upload.locked_by = "active-worker"
        active_upload.locked_at = now - timedelta(hours=3)
        active_upload.updated_at = now - timedelta(minutes=10)
        ids = {
            "stale_chat": stale_chat.id,
            "stale_continuation": stale_continuation.id,
            "stale_upload": stale_upload.id,
            "stale_primary": stale_primary.id,
            "old_training": old_training.id,
            "fresh_chat": fresh_chat.id,
            "active_upload": active_upload.id,
        }
        db.commit()
        db.execute(
            update(Job)
            .where(Job.id.in_([ids["stale_chat"], ids["stale_continuation"]]))
            .values(created_at=now - timedelta(minutes=30), updated_at=now - timedelta(minutes=30))
        )
        db.execute(
            update(Job)
            .where(Job.id == ids["stale_upload"])
            .values(created_at=now - timedelta(hours=11), updated_at=now - timedelta(hours=10))
        )
        db.execute(
            update(Job)
            .where(Job.id == ids["stale_primary"])
            .values(created_at=now - timedelta(minutes=20), updated_at=now - timedelta(minutes=16))
        )
        db.execute(
            update(Job)
            .where(Job.id == ids["old_training"])
            .values(created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=2))
        )
        db.commit()

    with session_factory() as db:
        assert reap_stale_running_jobs(db, now=now) == 4
        db.commit()

    with session_factory() as db:
        assert db.get(Job, ids["stale_chat"]).status == "timed_out"
        assert db.get(Job, ids["stale_continuation"]).status == "timed_out"
        assert db.get(Job, ids["stale_upload"]).status == "timed_out"
        assert db.get(Job, ids["stale_primary"]).status == "timed_out"
        assert db.get(Job, ids["old_training"]).status == "running"
        assert db.get(Job, ids["fresh_chat"]).status == "running"
        assert db.get(Job, ids["active_upload"]).status == "running"


def test_project_jobs_endpoint_reaps_stale_upload_data_bundle(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Stale upload visibility"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    now = utc_now()
    with session_factory() as db:
        stale_upload = create_job(db, job_type="upload_data_bundle", project_id=project_id, priority=85)
        stale_upload.status = "running"
        stale_upload.locked_by = "dead-worker"
        stale_upload.locked_at = now - timedelta(hours=11)
        stale_upload.updated_at = now - timedelta(hours=10)
        stale_upload_id = stale_upload.id
        db.commit()
        db.execute(
            update(Job)
            .where(Job.id == stale_upload_id)
            .values(created_at=now - timedelta(hours=11), updated_at=now - timedelta(hours=10))
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/jobs")
    assert response.status_code == 200
    job = next(item for item in response.json() if item["id"] == stale_upload_id)
    assert job["status"] == "timed_out"
    assert "upload_data_bundle exceeded" in job["error_message"]


def test_sync_worker_marks_failed_after_handler_transaction_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Worker rollback"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        job = create_job(db, job_type="profile_dataset", project_id=project_id)
        job_id = job.id
        db.commit()

    def broken_handler(db: Any, job: Job, store: LocalArtifactStore) -> dict[str, object]:
        del store
        duplicate_a = Artifact(
            id="art_duplicate_a",
            project_id=job.project_id,
            asset_type="duplicate_test",
            name="same",
            version=1,
            uri="local://a",
            content_hash="a",
        )
        duplicate_b = Artifact(
            id="art_duplicate_b",
            project_id=job.project_id,
            asset_type="duplicate_test",
            name="same",
            version=1,
            uri="local://b",
            content_hash="b",
        )
        db.add_all([duplicate_a, duplicate_b])
        try:
            db.flush()
        except IntegrityError as exc:
            raise RuntimeError("simulated handler transaction failure") from exc
        return {"unexpected": True}

    worker = SyncWorker(
        handlers={"profile_dataset": broken_handler},
        store=cast(Any, app).state.artifact_store,
        worker_id="rollback-test-worker",
    )
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        result = worker.run_job(db, job)
        assert result.status == "failed"
        assert "simulated handler transaction failure" in (result.error_message or "")

    with session_factory() as db:
        recovered = db.get(Job, job_id)
        assert recovered is not None
        assert recovered.status == "failed"


def test_full_auto_start_queues_training_for_large_dataset_boundary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TABLEX_AUTONOMY_SYNC_TRAINING_ROW_LIMIT", "10")
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Autonomous queued training", "target_column": "label", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("queued_training.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"
    assert "fixed recipes" in session["goal_text"].lower()

    activity = client.get(f"/api/projects/{project_id}/agent-activity").json()
    assert activity["turn_state"]["agent_session_id"] == session_id
    assert any(worker.get("agent_session_id") == session_id for worker in activity["workers"])

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history
    assert history[-1]["intent"]["type"] == "agent_loop_control"
    assert "Full Auto" in history[-1]["assistant_message"]


def test_full_auto_passes_readiness_constraints_to_main_codex_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Constrained autonomous session", "target_column": "label", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("constrained.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        db.add(
            Question(
                id="q_block_autonomous",
                project_id=project_id,
                question_set_id="qs_block_autonomous",
                topic="evaluation_boundary",
                question="Should the current validation boundary be confirmed before interpreting model results?",
                why_it_matters="This affects whether model comparison evidence can be trusted.",
                default_assumption="Continue with the current split as a provisional boundary.",
                impact_if_wrong="The leaderboard may overstate generalization.",
                choices_json="[]",
                status="open",
                priority=95,
                risk_level="high",
                value_of_answer="high",
                can_proceed_without_answer=False,
                fallback_policy="block_until_answered",
                blocks_next_phase=True,
            )
        )
        db.commit()

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert "Design reliable evaluation" in session["goal_text"]
    transcript = client.get(f"/api/projects/{project_id}/agent-session/transcript").json()
    assert any(event["event_type"] == "session_created" for event in transcript)


def test_full_auto_delegates_target_definition_to_codex_without_harness_target_heuristics(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TABLEX_AUTONOMY_SYNC_TRAINING_ROW_LIMIT", "10")
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Home Credit style upload"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    train_rows = ["SK_ID_CURR,feature,TARGET"] + [f"{100000 + index},{index % 7},{1 if index % 5 == 0 else 0}" for index in range(1, 80)]
    train_upload = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("application_train.csv", "\n".join(train_rows).encode("utf-8"), "text/csv")},
    )
    assert train_upload.status_code == 200, train_upload.text

    submission_rows = ["SK_ID_CURR,TARGET"] + [f"{200000 + index},0.0" for index in range(1, 80)]
    submission_upload = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("sample_submission.csv", "\n".join(submission_rows).encode("utf-8"), "text/csv")},
    )
    assert submission_upload.status_code == 200, submission_upload.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    assert train_upload.json()["dataset_snapshot"]["id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert "infer or construct the prediction objective from evidence" in session["goal_text"]

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["target_column"] is None
    assert project["task_type"] is None


def test_full_auto_codex_target_proposal_drives_evaluation_and_runs(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Codex target proposal"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("codex_target.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    def fake_codex_runner(*args: Any, **kwargs: Any) -> Any:
        agent_result = AgentResult(
            task_id="agt_fake",
            status="succeeded",
            final_message="Codex reviewed the data context and proposed a target.",
            outputs={
                "target_definition_proposal": {
                    "recommended_target": {
                        "kind": "existing_column",
                        "column_name": "label",
                        "task_type": "binary_classification",
                        "confidence": 0.82,
                        "risk_level": "medium",
                        "rationale": "The proposal is based on the profiled project context supplied to Codex.",
                    },
                    "alternatives": [],
                    "risks": ["Confirm prediction-time availability before deployment."],
                },
                "report_md": "Target definition review complete.",
            },
            artifacts=[],
            warnings=[],
        )
        return SimpleNamespace(
            agent_result=agent_result,
            artifact_ids=[],
            report_id="rpt_fake",
            evidence_id="ev_fake",
            workspace_artifact_id="art_workspace_fake",
            readiness_artifact_id="art_readiness_fake",
            readiness_status="ready_with_warnings",
            ingested_artifact_ids=[],
            auto_prepared_workspace=False,
            experiment_ingestion=SimpleNamespace(run=None),
            relational_context_summary={},
            relational_context_summary_artifact_id=None,
            approach_decision_trace_artifact_id=None,
        )

    del fake_codex_runner
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert "Current target/objective hint" in session["goal_text"]

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    project = project_read_response.json()
    assert project["target_column"] is None
    assert project["task_type"] is None


def test_approval_based_start_runs_but_does_not_auto_adopt_evaluation(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Approval based with data", "target_column": "value", "task_type": "regression"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,value"] + [f"{index},{'a' if index % 2 else 'b'},{index * 3}" for index in range(1, 31)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("approval.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "harness_only", "autonomy_mode": "approval_based"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "autonomous_loop_start_queued.v1"
    job = wait_for_job_status(client, queued_job["id"], statuses={"succeeded"})
    output = job["output"]
    assert output["mode"] == "approval_based"
    assert any(step["label"] == "evaluation_review" for step in output["steps"])
    evaluation_step = next(step for step in output["steps"] if step["label"] == "evaluation_spec")
    assert evaluation_step["status"] == "blocked"
    assert "Human approval" in evaluation_step["boundary"]

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    assert project_read_response.json()["autonomy_mode"] == "approval_based"
    assert project_read_response.json()["current_phase"] == "AUTONOMOUS_LOOP"

    specs = client.get(f"/api/projects/{project_id}/evaluation/specs").json()
    assert all(spec["status"] != "approved" for spec in specs)


def test_project_guidance_recommends_next_focus(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Guided UX"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    empty_guidance_response = client.get(f"/api/projects/{project_id}/guidance")
    assert empty_guidance_response.status_code == 200, empty_guidance_response.text
    empty_guidance = empty_guidance_response.json()
    assert empty_guidance["schema_version"] == "project_guidance.v1"
    assert empty_guidance["attention_budget"] == 1
    assert empty_guidance["recommended_focus"]["focus_key"] == "upload_data"
    assert empty_guidance["recommended_focus"]["target_tab"] == "Data"
    assert empty_guidance["recommended_focus"]["primary_action"]["action_type"] == "navigate"
    assert empty_guidance["supporting_counts"]["datasets"] == 0
    empty_navigation = empty_guidance["autonomous_navigation"]
    assert empty_navigation["schema_version"] == "autonomous_navigation.v1"
    assert empty_navigation["mode"] == "one_decision_at_a_time"
    assert empty_navigation["attention_budget"] == 1
    assert empty_navigation["headline"] == empty_guidance["recommended_focus"]["title"]
    assert empty_navigation["primary_action"]["id"] == empty_guidance["recommended_focus"]["primary_action"]["id"]
    assert empty_navigation["codex_navigation"]["runner_may_choose_approach"] is True
    assert empty_navigation["decision_brief"]["schema_version"] == "autonomous_decision_brief.v1"
    assert empty_navigation["decision_brief"]["attention_budget"] == 1
    assert empty_navigation["decision_brief"]["decision_question"]
    empty_journey = {stage["id"]: stage for stage in empty_guidance["journey_stages"]}
    assert empty_guidance["current_stage_id"] == "data_intake"
    assert empty_journey["data_intake"]["status"] == "current"
    assert empty_journey["understanding"]["status"] == "waiting"
    assert empty_journey["notebooks"]["target_tab"] == "Notebooks"
    assert empty_journey["notebooks"]["status"] == "waiting"
    assert empty_journey["approach"]["summary"].startswith("Prepare an open-ended Codex")
    legacy_tabs = {"Overview", "Approach", "Experiments", "Reports"}
    assert not legacy_tabs.intersection(collect_target_tabs(empty_guidance))

    csv_bytes = b"feature,target\n1,0\n2,1\n3,0\n4,1\n"
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("guided.csv", csv_bytes, "text/csv")},
        data={"target_column": "target"},
    )
    assert upload_response.status_code == 200, upload_response.text

    next_guidance_response = client.get(f"/api/projects/{project_id}/guidance")
    assert next_guidance_response.status_code == 200, next_guidance_response.text
    next_guidance = next_guidance_response.json()
    assert next_guidance["supporting_counts"]["datasets"] == 1
    next_journey = {stage["id"]: stage for stage in next_guidance["journey_stages"]}
    assert next_journey["data_intake"]["status"] == "done"
    assert next_guidance["current_stage_id"] in {
        "understanding",
        "assumptions",
        "evaluation",
        "approach",
    }
    assert next_guidance["recommended_focus"]["focus_key"] in {
        "assumptions",
        "evaluation",
        "understand_data",
    }
    assert next_guidance["recommended_focus"]["primary_action"]["target_tab"]
    assert next_guidance["agent_guidance"]
    next_navigation = next_guidance["autonomous_navigation"]
    assert next_navigation["attention_budget"] == 1
    assert next_navigation["journey_progress"]["total_count"] == len(next_guidance["journey_stages"])
    assert "show_the_next_decision" in next_navigation["aesthetic_principle"]
    assert next_navigation["decision_brief"]["target_tab"] == next_guidance["recommended_focus"]["target_tab"]
    assert not legacy_tabs.intersection(collect_target_tabs(next_guidance))

    snapshot_response = client.post(f"/api/projects/{project_id}/guidance/snapshot")
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot_job = snapshot_response.json()
    assert snapshot_job["status"] == "queued"
    assert snapshot_job["policy"]["execution"] == "queued_worker"
    assert snapshot_job["job_type"] == "save_guided_journey_snapshot"
    snapshot_output = run_queued_job(client, snapshot_job["id"])
    assert snapshot_output["schema_version"] == "guided_journey_snapshot.v1"
    assert snapshot_output["guided_journey_snapshot_artifact_id"]
    assert snapshot_output["guided_journey_report_id"]
    assert snapshot_output["visualization_artifact_id"]

    report_preview_response = client.get(f"/api/reports/{snapshot_output['guided_journey_report_id']}/preview")
    assert report_preview_response.status_code == 200, report_preview_response.text
    assert "Guided Journey" in report_preview_response.json()["preview"]

    decision_brief_response = client.post(f"/api/projects/{project_id}/guidance/decision-brief")
    assert decision_brief_response.status_code == 200, decision_brief_response.text
    decision_brief_job = decision_brief_response.json()
    assert decision_brief_job["status"] == "queued"
    assert decision_brief_job["policy"]["execution"] == "queued_worker"
    assert decision_brief_job["job_type"] == "save_autonomous_decision_brief"
    decision_brief_output = run_queued_job(client, decision_brief_job["id"])
    assert decision_brief_output["schema_version"] == "autonomous_decision_brief.v1"
    assert decision_brief_output["autonomous_decision_brief_artifact_id"]
    assert decision_brief_output["autonomous_decision_brief_report_id"]

    decision_brief_preview_response = client.get(
        f"/api/reports/{decision_brief_output['autonomous_decision_brief_report_id']}/preview"
    )
    assert decision_brief_preview_response.status_code == 200, decision_brief_preview_response.text
    assert "Autonomous Decision Brief" in decision_brief_preview_response.json()["preview"]

    second_snapshot_response = client.post(f"/api/projects/{project_id}/guidance/snapshot")
    assert second_snapshot_response.status_code == 200, second_snapshot_response.text
    second_snapshot_job = second_snapshot_response.json()
    assert second_snapshot_job["status"] == "queued"
    run_queued_job(client, second_snapshot_job["id"])

    comparison_response = client.post(f"/api/projects/{project_id}/guidance/snapshots/compare")
    assert comparison_response.status_code == 200, comparison_response.text
    comparison_job = comparison_response.json()
    assert comparison_job["status"] == "queued"
    assert comparison_job["policy"]["execution"] == "queued_worker"
    assert comparison_job["job_type"] == "compare_guided_journey_snapshots"
    comparison_output = run_queued_job(client, comparison_job["id"])
    assert comparison_output["schema_version"] == "guided_journey_comparison.v1"
    assert comparison_output["guided_journey_comparison_artifact_id"]
    assert comparison_output["guided_journey_comparison_report_id"]

    comparison_preview_response = client.get(
        f"/api/reports/{comparison_output['guided_journey_comparison_report_id']}/preview"
    )
    assert comparison_preview_response.status_code == 200, comparison_preview_response.text
    assert "Guided Journey Comparison" in comparison_preview_response.json()["preview"]


def test_guidance_and_result_helpers_count_marimo_notebook_as_native_notebook(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "marimo source guidance"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        run = ExperimentRun(
            id="run_marimo_guidance",
            project_id=project_id,
            runner_type="codex_cli",
            status="succeeded",
            metrics_json=json.dumps({"primary_metric_name": "mae", "primary_metric_value": 12.3}),
        )
        db.add(run)
        notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="marimo_notebook",
            name="model_diagnostics_marimo",
            filename="model_diagnostics.py",
            text="import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
            metadata={
                "project_id": project_id,
                "notebook_kind": "model_diagnostics",
                "run_id": run.id,
            },
        )
        db.commit()

        latest = latest_model_diagnostics_notebook_for_run(db, project_id, run.id)
        assert latest is not None
        assert latest.id == notebook.id

    guidance_response = client.get(f"/api/projects/{project_id}/guidance")
    assert guidance_response.status_code == 200, guidance_response.text
    guidance = guidance_response.json()
    assert guidance["supporting_counts"]["analysis_notebooks"] == 1
    assert guidance["state_summary"]["analysis_notebook_count"] == 1
    assert guidance["state_summary"]["latest_analysis_notebook_artifact_id"] == notebook.id


def test_agent_chat_records_conversation_without_mutating_project_state(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Metric chat", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,target"] + [f"{index},0" for index in range(1, 10)] + ["10,1"]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("metric.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    assert design_response.json()["status"] == "queued"
    run_queued_job(client, design_response.json()["id"])
    candidates_before = client.get(f"/api/projects/{project_id}/evaluation/candidates").json()
    assert any(candidate["primary_metric"] == "pr_auc" for candidate in candidates_before)

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "metricはROCーAUCにして", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["schema_version"] == "agent_chat_turn.v1"
    assert chat["intent"]["type"] == "agent_conversation"
    assert chat["actions"] == []
    assert chat["job"]["status"] == "queued"
    assert chat["response_composer"]["status"] == "queued"
    assert chat["artifact_id"].startswith("pending_")
    assert "返答を準備しています" in chat["assistant_message"]
    assert chat["response_brief"]["wait_state"]["worker_state"] == "waiting_for_local_worker"

    pending_history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert pending_history_response.status_code == 200
    pending_history = pending_history_response.json()
    assert len(pending_history) == 1
    assert pending_history[0]["job_id"] == chat["job"]["id"]
    assert pending_history[0]["artifact_id"] == f"job_pending_{chat['job']['id']}"
    assert pending_history[0]["response_composer"]["status"] == "queued"
    assert "返答を準備しています" in pending_history[0]["assistant_message"]
    assert pending_history[0]["response_brief"]["wait_state"]["worker_state"] == "waiting_for_local_worker"
    assert pending_history[0]["response_brief"]["wait_state"]["job_age_seconds"] >= 0

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        old_job = db.get(Job, chat["job"]["id"])
        assert old_job is not None
        old_time = utc_now() - timedelta(seconds=75)
        old_job.created_at = old_time
        old_job.updated_at = old_time
        db.commit()
    stale_history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert stale_history[0]["response_brief"]["wait_state"]["possibly_stale"] is True
    assert "まだ返答が戻っていません" in stale_history[0]["assistant_message"]

    output = run_queued_agent_chat_turn(client, chat["job"]["id"])
    assert output["schema_version"] == "agent_chat_turn.v1"

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    answered = history[0]
    assert answered["user_message"] == "metricはROCーAUCにして"
    assert answered["actions"] == []
    assert answered["intent"]["type"] == "agent_conversation"
    assert answered["artifact_id"] == output["artifact_id"]
    assert answered["action_summary"]["outcome"] == "answered"
    assert "schema-validated agent proposals" in answered["action_summary"]["boundaries"][0]
    assert answered["response_brief"]["response_locale"] == "ja-JP"
    assert answered["response_brief"]["conversation_context"]["schema_version"] == "agent_conversation_context.v1"
    explicit_actions = {
        item["action"] for item in answered["response_brief"]["conversation_context"]["available_explicit_actions"]
    }
    assert {"create_skill", "equip_existing_skill"} <= explicit_actions
    assert answered["response_brief"]["conversation_context"]["skill_context"]["purpose"].startswith("Skills are reusable")
    assert answered["token_usage"]["is_estimate"] is True

    candidates_after = client.get(f"/api/projects/{project_id}/evaluation/candidates").json()
    assert candidates_after == candidates_before
    leaderboard = client.get(f"/api/projects/{project_id}/leaderboard").json()
    assert leaderboard == []
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    assert any(item["asset_type"] == "agent_chat_turn" for item in artifacts)
    assert not any(item["asset_type"] == "evaluation_metric_preference" for item in artifacts)

    metric_response = client.post(f"/api/projects/{project_id}/leaderboard/metric", json={"metric": "ROCーAUC"})
    assert metric_response.status_code == 200, metric_response.text
    assert metric_response.json()["metric"] == "roc_auc"


def test_agent_chat_brief_includes_recent_conversation_turns(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Conversation Memory"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    first_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "この会話でsalaryの扱いを後で確認したいです。", "locale": "ja-JP"},
    )
    assert first_response.status_code == 200, first_response.text
    first_output = run_queued_agent_chat_turn(client, first_response.json()["job"]["id"])
    assert first_output["schema_version"] == "agent_chat_turn.v1"

    second_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "さっきの話を踏まえて状況を説明してください。", "locale": "ja-JP"},
    )
    assert second_response.status_code == 200, second_response.text
    run_queued_agent_chat_turn(client, second_response.json()["job"]["id"])

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    second_turn = history_response.json()[-1]
    recent_turns = second_turn["response_brief"]["conversation_context"]["recent_conversation_turns"]
    assert any("salaryの扱い" in turn["user_message"] for turn in recent_turns)
    assert any(turn["artifact_id"] == first_output["artifact_id"] for turn in recent_turns)


def test_agent_chat_writes_active_session_instruction_to_workspace_inbox(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path, api_agent_session_supervisor_enabled=False)
    project_response = client.post("/api/projects", json={"name": "Inbox delivery"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_inbox_delivery"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_inbox_delivery",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working and read the workspace inbox.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="現在のデータを確認しています。",
            payload={"type": "item.completed", "item": {"type": "agent_message"}},
        )
        db.commit()
    append_runner_stream_to_workspace(workspace, stream_name="stdout", line='{"type":"turn.started"}')

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "この条件で特徴量を見直してください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["job"]["job_type"] == "agent_chat_turn"
    assert chat["job"]["status"] == "waiting_for_agent"
    assert chat["job"]["priority"] == 90
    assert chat["job"]["run_after"] is None
    assert chat["response_composer"]["mode"] == "main_codex_session"
    assert chat["response_composer"]["status"] == "waiting_for_agent"
    assert "入力は進行中の分析エージェントに届いています" in chat["assistant_message"]
    assert "worker待ち" not in chat["assistant_message"]
    assert chat["response_brief"]["wait_state"]["worker_state"] == "waiting_for_main_agent_reply"
    assert chat["response_brief"]["progress_update_requested_event_id"]
    observation = chat["response_brief"]["agent_session_observation"]
    assert observation["schema_version"] == "agent_session_chat_wait_observation.v1"
    assert observation["agent_session_id"] == "ags_inbox_delivery"
    assert observation["status"] == "running"
    assert observation["last_codex_output_seconds_ago"] is not None
    assert observation["latest_codex_message"]["content"] == "現在のデータを確認しています。"
    assert observation["latest_codex_message"]["event_index"] == 0
    assert observation["raw_transcript"]["stdout_line_count"] == 1

    inbox = user_instructions_inbox_path(workspace)
    latest = latest_user_instruction_path(workspace)
    progress_request = progress_request_path(workspace)
    assert inbox.exists()
    assert latest.exists()
    assert progress_request.exists()
    instruction_entry = loads_json(inbox.read_text(encoding="utf-8"), {})
    payload = instruction_entry["payload"]
    assert instruction_entry["schema_version"] == "tablex_inbox_entry.v1"
    assert instruction_entry["kind"] == "user_instruction"
    assert payload["schema_version"] == "tablex_user_instruction.v1"
    assert payload["session_id"] == "ags_inbox_delivery"
    assert payload["locale"] == "ja-JP"
    assert payload["message"] == "この条件で特徴量を見直してください"
    progress_request_text = loads_json(progress_request.read_text(encoding="utf-8"), {})["content"]
    assert "trigger: user_chat_message" in progress_request_text
    assert "latest_user_message:" in progress_request_text
    assert "この条件で特徴量を見直してください" in progress_request_text
    assert "ユーザーがAgent Chatで返答を待っています" in progress_request_text
    assert "この条件で特徴量を見直してください" in loads_json(latest.read_text(encoding="utf-8"), {})["content"]
    jobs = client.get(f"/api/projects/{project_id}/jobs").json()
    assert any(job["job_type"] == "agent_chat_turn" and job["status"] == "waiting_for_agent" for job in jobs)
    activity = client.get(f"/api/projects/{project_id}/agent-activity").json()
    waiting_workers = [
        worker
        for worker in activity["workers"]
        if worker.get("job_id") == chat["job"]["id"] and worker.get("status") == "waiting_for_agent"
    ]
    assert waiting_workers
    assert waiting_workers[0]["active"] is True
    assert activity["active_count"] >= 1
    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history[-1]["job_id"] == chat["job"]["id"]
    assert history[-1]["user_message"] == "この条件で特徴量を見直してください"
    assert history[-1]["response_composer"]["mode"] == "main_codex_session"
    assert history[-1]["response_composer"]["status"] == "waiting_for_agent"
    assert "Codexの返答が届き次第" in history[-1]["assistant_message"]
    assert history[-1]["response_brief"]["delivered_agent_session_id"] == "ags_inbox_delivery"
    assert history[-1]["response_brief"]["wait_state"]["worker_state"] == "waiting_for_main_agent_reply"
    history_observation = history[-1]["response_brief"]["agent_session_observation"]
    assert history_observation["agent_session_id"] == "ags_inbox_delivery"
    assert history_observation["latest_codex_message"]["content"] == "現在のデータを確認しています。"
    assert history_observation["raw_transcript"]["stdout_line_count"] == 1

    with app.state.session_factory() as db:
        session = db.get(AgentSession, "ags_inbox_delivery")
        assert session is not None
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="特徴量候補と評価境界を確認しています。",
            payload={"type": "item.completed", "item": {"type": "agent_message"}},
        )
        db.commit()
    refreshed_history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    refreshed_observation = refreshed_history[-1]["response_brief"]["agent_session_observation"]
    assert refreshed_observation["latest_codex_message"]["content"] == "特徴量候補と評価境界を確認しています。"
    assert refreshed_observation["latest_codex_message"]["event_index"] > observation["latest_codex_message"]["event_index"]

    worker = SyncWorker(handlers={"agent_chat_turn": agent_chat_turn_handler}, store=app.state.artifact_store)
    with app.state.session_factory() as db:
        assert worker.run_next_job(db, project_id=project_id, job_types={"agent_chat_turn"}) is None
        waiting_job = db.get(Job, chat["job"]["id"])
        assert waiting_job is not None
        assert waiting_job.status == "waiting_for_agent"
        direct_run_result = worker.run_job(db, waiting_job)
        assert direct_run_result.status == "waiting_for_agent"
        db.refresh(waiting_job)
        assert waiting_job.status == "waiting_for_agent"
        assert waiting_job.started_at is None
        assert waiting_job.ended_at is None

    report_path = workspace / "reports" / "chat_update.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("特徴量の見直し依頼を受け取りました。次に利用可能な列と漏洩リスクを確認します。", encoding="utf-8")
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        session = db.get(AgentSession, "ags_inbox_delivery")
        assert project is not None
        assert session is not None
        source_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="agent_session_reports_chat_update_md",
            filename="chat_update.md",
            payload={"message": report_path.read_text(encoding="utf-8")},
            metadata={"project_id": project_id, "agent_session_id": session.id},
        )
        maybe_register_chat_update_from_workspace_output(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            path=report_path,
            artifact=source_artifact,
        )
        db.commit()

    completed_history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    completed_turn = completed_history[-1]
    assert completed_turn["job_id"] == chat["job"]["id"]
    assert "特徴量の見直し依頼" in completed_turn["assistant_message"]
    assert completed_turn["response_composer"]["mode"] == "main_codex_session"
    assert completed_turn["response_brief"]["progress_artifact_id"]


def test_agent_chat_wakes_between_turns_main_session(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    supervisor_starts: list[dict[str, str]] = []

    def fake_start_supervisor(*args: Any, **kwargs: Any) -> None:
        supervisor_starts.append(
            {
                "project_id": str(kwargs["project_id"]),
                "session_id": str(kwargs["session_id"]),
            }
        )

    monkeypatch.setattr(routes_module, "start_main_agent_session_supervisor_thread", fake_start_supervisor)
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Wake between turns"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_wake_between_turns"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_wake_between_turns",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="between_turns",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue when a user instruction arrives.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.commit()

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "この観点も次の分析に入れてください", "locale": "ja-JP"},
    )

    assert chat_response.status_code == 200, chat_response.text
    assert supervisor_starts == [{"project_id": project_id, "session_id": "ags_wake_between_turns"}]
    chat = chat_response.json()
    assert chat["response_composer"]["mode"] == "main_codex_session"
    assert chat["job"]["status"] == "waiting_for_agent"
    assert user_instructions_inbox_path(workspace).exists()


def test_agent_chat_wait_observation_falls_back_to_raw_codex_transcript(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Raw only Codex wait"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_raw_only_wait"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_raw_only_wait",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep the raw transcript visible while chat waits.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.flush()
        old_event = append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="DBにだけある古い進捗です。",
            payload={"type": "item.completed", "item": {"type": "agent_message"}},
        )
        old_event.created_at = utc_now() - timedelta(minutes=10)
        db.commit()
    append_runner_stream_to_workspace(
        workspace,
        stream_name="stdout",
        line='{"type":"item.completed","item":{"type":"agent_message","text":"Raw transcriptだけにある進捗です。"}}',
    )

    response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "状況を説明してください", "locale": "ja-JP"},
    )
    assert response.status_code == 200, response.text
    observation = response.json()["response_brief"]["agent_session_observation"]
    assert observation["raw_transcript"]["stdout_line_count"] == 1
    assert observation["latest_codex_message"]["source"] == "raw_transcript_file"
    assert observation["latest_codex_message"]["line_number"] == 1
    assert observation["latest_codex_message"]["content"] == "Raw transcriptだけにある進捗です。"
    assert observation["last_codex_output_at"] == observation["latest_codex_message"]["created_at"]
    assert observation["last_codex_output_seconds_ago"] is not None

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    history_observation = history[-1]["response_brief"]["agent_session_observation"]
    assert history_observation["latest_codex_message"]["source"] == "raw_transcript_file"
    assert history_observation["latest_codex_message"]["content"] == "Raw transcriptだけにある進捗です。"


def test_agent_chat_history_pairs_main_session_update_to_delivered_instruction(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Main session chat update pairing"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_update_pairing"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_update_pairing",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working and publish chat updates.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.commit()

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "いま何を見ていますか？", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert "入力は進行中の分析エージェントに届いています" in chat["assistant_message"]

    with app.state.session_factory() as db:
        progress_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_chat_update_ags_update_pairing_manual",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "project_id": project_id,
                "user_message": "",
                "assistant_message": "データの粒度と欠損の偏りを確認しています。次に候補特徴量の漏洩リスクを見ます。",
                "intent": {
                    "type": "autonomous_agent_progress_report",
                    "source": "main_codex_session",
                    "routing_policy": "codex_authored_human_update",
                },
                "actions": [],
                "action_summary": {},
                "response_brief": {
                    "schema_version": "agent_progress_report_brief.v1",
                    "agent_session_id": "ags_update_pairing",
                    "source_artifact_id": "art_manual_chat_update",
                    "workspace_relative_path": "reports/chat_update.md",
                },
                "response_composer": {
                    "schema_version": "agent_response_composer.v1",
                    "mode": "main_codex_session",
                    "status": "codex_authored",
                },
                "worker_events": [],
                "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
                "next_focus": {"target_tab": "Data", "target_anchor": "notebook-preview-top", "label": "Data"},
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": "ags_update_pairing",
                "source_artifact_id": "art_manual_chat_update",
                "source": "main_codex_session_chat_update",
            },
        )
        db.commit()

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert len(history) == 1
    turn = history[0]
    assert turn["user_message"] == "いま何を見ていますか？"
    assert "データの粒度" in turn["assistant_message"]
    assert "worker待ち" not in turn["assistant_message"]
    assert turn["intent"]["source"] == "main_codex_session_chat_update"
    assert turn["response_composer"]["mode"] == "main_codex_session"
    assert turn["response_composer"]["status"] == "codex_authored"
    assert turn["response_brief"]["progress_artifact_id"] == progress_artifact.id
    assert turn["response_brief"]["agent_session_observation"]["agent_session_id"] == "ags_update_pairing"
    assert turn["response_brief"]["agent_session_observation"]["schema_version"] == "agent_session_chat_wait_observation.v1"
    assert turn["next_focus"]["target_tab"] == "Notebooks"
    assert turn["next_focus"]["target_anchor"] == "notebook-native-marimo-top"
    assert turn["job_id"] == chat["job"]["id"]


def test_agent_chat_history_pairs_each_main_session_update_once(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "One progress update per chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_one_update"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        db.add(
            AgentSession(
                id="ags_one_update",
                project_id=project_id,
                org_id=project.org_id,
                session_type="main_autonomous",
                status="running",
                autonomy_mode="full_auto",
                runner_kind="codex_cli",
                goal_text="Keep working and publish chat updates.",
                workspace_path=str(workspace),
                created_by="test",
            )
        )
        db.commit()

    first_chat = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "最初の質問です。", "locale": "ja-JP"},
    ).json()
    second_chat = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "二つ目の質問です。", "locale": "ja-JP"},
    ).json()

    with app.state.session_factory() as db:
        progress_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_chat_update_ags_one_update_manual",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "project_id": project_id,
                "user_message": "",
                "assistant_message": "最初の質問に対応する進捗です。次は評価設計を見ます。",
                "intent": {
                    "type": "autonomous_agent_progress_report",
                    "source": "main_codex_session",
                    "routing_policy": "codex_authored_human_update",
                },
                "actions": [],
                "action_summary": {},
                "response_brief": {
                    "schema_version": "agent_progress_report_brief.v1",
                    "agent_session_id": "ags_one_update",
                    "source_artifact_id": "art_one_update",
                    "workspace_relative_path": "reports/chat_update.md",
                },
                "response_composer": {
                    "schema_version": "agent_response_composer.v1",
                    "mode": "main_codex_session",
                    "status": "codex_authored",
                },
                "worker_events": [],
                "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
                "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"},
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": "ags_one_update",
                "source_artifact_id": "art_one_update",
                "source": "main_codex_session_chat_update",
            },
        )
        db.commit()

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    first_turn = next(turn for turn in history if turn.get("job_id") == first_chat["job"]["id"])
    second_turn = next(turn for turn in history if turn.get("job_id") == second_chat["job"]["id"])

    assert first_turn["user_message"] == "最初の質問です。"
    assert first_turn["response_brief"]["progress_artifact_id"] == progress_artifact.id
    assert "最初の質問に対応する進捗" in first_turn["assistant_message"]
    assert second_turn["user_message"] == "二つ目の質問です。"
    assert second_turn["response_composer"]["mode"] == "main_codex_session"
    assert second_turn["response_composer"]["status"] == "waiting_for_agent"
    assert "Codexの返答が届き次第" in second_turn["assistant_message"]
    assert second_turn["artifact_id"].startswith("job_pending_")


def test_main_session_update_pairing_uses_datetime_order_not_string_order() -> None:
    job = Job(
        id="job_chat_pair",
        job_type="agent_chat_turn",
        project_id="p_pair",
        input_json="{}",
        output_json="{}",
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    payload = {"delivered_agent_session_id": "ags_pair"}
    old_update_with_later_looking_local_time = {
        "agent_session_id": "ags_pair",
        "artifact_id": "art_old",
        "created_at": "2026-01-01T08:59:59+09:00",
    }
    new_update = {
        "agent_session_id": "ags_pair",
        "artifact_id": "art_new",
        "created_at": "2026-01-01T00:00:01Z",
    }

    paired = matching_main_session_update_for_chat_job(
        job,
        payload,
        [old_update_with_later_looking_local_time, new_update],
    )

    assert paired == new_update


def test_research_plan_timeline_reads_artifact_authored_blocks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Timeline Plan"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_research_plan",
            filename="research_plan.json",
            metadata={"project_id": project_id, "source": "test"},
            payload={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "deep_eda",
                        "title": "Deep EDA",
                        "why_it_matters": "Inspect salary tail and relational coverage.",
                        "next_action": "Open the EDA notebook and validate the tail story.",
                        "done_criteria": "Tail risk is documented with a readable artifact.",
                        "evidence": "1 evidence",
                        "blockers": ["Owner review is pending."],
                        "supporting_artifacts": [{"path": "notebooks/deep_eda.py", "exists": True}],
                        "status": "active",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "localizations": {
                            "ja-JP": {
                                "title": "深いEDA",
                                "why_it_matters": "salaryの裾とリレーショナルなカバレッジを確認します。",
                                "next_action": "EDAノートブックを開き、裾の見立てを確認します。",
                                "done_criteria": "裾のリスクが読めるartifactで記録されていること。",
                                "blockers": ["データオーナー確認が未完了です。"],
                            }
                        },
                        "subtasks": [
                            {
                                "id": "tail_review",
                                "title": "High salary tail review",
                                "detail": "Check whether tail labels need a separate decision path.",
                                "status": "pending",
                                "target_tab": "Insight",
                                "localizations": {
                                    "ja-JP": {
                                        "title": "高salary裾の確認",
                                        "detail": "裾ラベルに別の判断経路が必要か確認します。",
                                    }
                                },
                            }
                        ],
                    },
                    {
                        "id": "approval_response_contract_v19",
                        "title": "approval response contract v19",
                        "why_it_matters": "Prepare the data owner reply shape.",
                        "blockers": ["Owner review is pending.", "Metric choice is pending."],
                        "status": "blocked",
                    },
                    {
                        "id": "done_missing_notebook",
                        "title": "Done missing notebook",
                        "why_it_matters": "A readable notebook must exist before this can be treated as done.",
                        "supporting_artifacts": [{"path": "notebooks/missing_eda.py", "exists": False}],
                        "status": "done",
                        "localizations": {
                            "ja-JP": {
                                "title": "未生成Notebook待ち",
                                "why_it_matters": "読めるNotebookが存在するまでは完了扱いできません。",
                            }
                        },
                    },
                    {"id": "broken", "status": "done"},
                    {
                        "id": "invalid_status",
                        "title": "Invalid status becomes pending",
                        "phase": "modeling",
                        "status": "surprise",
                    },
                    {
                        "id": "mixed_language",
                        "title": "Codexが update model diagnostics and feature importance",
                        "why_it_matters": "Notebookで inspect error slices, PDP, and residual segments.",
                        "status": "active",
                    },
                    {
                        "id": "thin_japanese_mixed_title",
                        "title": "approved target rebuild と evaluation",
                        "why_it_matters": "承認後はresolved target candidate、evaluation rerun、case queue reviewが必要。",
                        "status": "active",
                    },
                    {
                        "id": "japanese_heading_english_phrase",
                        "title": "データアップロード / project context",
                        "why_it_matters": "Dataset identity、target hint、locale、output contractが確定している。",
                        "status": "done",
                    },
                ],
            },
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["source_artifact_id"] == artifact.id
    assert [block["id"] for block in timeline["blocks"]] == [
        "deep_eda",
        "approval_response_contract_v19",
        "done_missing_notebook",
        "invalid_status",
        "mixed_language",
        "thin_japanese_mixed_title",
        "japanese_heading_english_phrase",
    ]
    assert timeline["blocks"][0]["status"] == "active"
    assert timeline["blocks"][0]["subtitle"] == "Inspect salary tail and relational coverage."
    assert timeline["blocks"][0]["next_action"] == "Open the EDA notebook and validate the tail story."
    assert timeline["blocks"][0]["done_criteria"] == "Tail risk is documented with a readable artifact."
    assert timeline["blocks"][0]["evidence"] == "1 evidence"
    assert timeline["blocks"][0]["supporting_artifacts"][0]["path"] == "notebooks/deep_eda.py"
    assert timeline["blocks"][0]["subtasks"][0]["target_tab"] == "Insight"
    assert timeline["blocks"][1]["status"] == "blocked"
    assert timeline["blocks"][2]["status"] == "done"
    assert timeline["blocks"][2]["status_adjustment_reason"] is None
    assert timeline["blocks"][2]["missing_supporting_artifact_count"] == 1
    assert timeline["blocks"][2]["evidence_verified"] is False
    assert timeline["blocks"][2]["supporting_artifacts"][0]["exists"] is False
    assert timeline["blocks"][3]["status"] == "pending"
    assert timeline["blocks"][3]["evidence"] == "modeling"

    localized_response = client.get(f"/api/projects/{project_id}/research-plan/timeline?locale=ja-JP")
    assert localized_response.status_code == 200
    localized = localized_response.json()
    assert localized["response_locale"] == "ja-JP"
    assert localized["blocks"][0]["title"] == "深いEDA"
    assert localized["blocks"][0]["subtitle"] == "salaryの裾とリレーショナルなカバレッジを確認します。"
    assert localized["blocks"][0]["next_action"] == "EDAノートブックを開き、裾の見立てを確認します。"
    assert localized["blocks"][0]["done_criteria"] == "裾のリスクが読めるartifactで記録されていること。"
    assert localized["blocks"][0]["blockers"] == ["データオーナー確認が未完了です。"]
    assert localized["blocks"][0]["evidence"] == "1 evidence"
    assert localized["blocks"][0]["subtasks"][0]["title"] == "高salary裾の確認"
    assert localized["blocks"][0]["subtasks"][0]["detail"] == "裾ラベルに別の判断経路が必要か確認します。"
    assert localized["blocks"][1]["title"] == "approval response contract v19"
    assert localized["blocks"][1]["subtitle"] == "Prepare the data owner reply shape."
    assert localized["blocks"][1]["evidence"] == "ブロッカー 2件"
    assert localized["blocks"][1]["blockers"] == ["Owner review is pending.", "Metric choice is pending."]
    assert localized["blocks"][2]["title"] == "未生成Notebook待ち"
    assert localized["blocks"][2]["status"] == "done"
    assert localized["blocks"][2]["status_adjustment_reason"] is None
    assert localized["blocks"][2]["missing_supporting_artifact_count"] == 1
    assert localized["blocks"][2]["evidence_verified"] is False
    assert localized["blocks"][3]["status"] == "pending"
    assert localized["blocks"][3]["evidence"] == "modeling"
    assert localized["blocks"][3]["title"] == "Invalid status becomes pending"
    assert localized["blocks"][3]["subtitle"] == ""
    assert localized["blocks"][4]["title"] == "Codexが update model diagnostics and feature importance"
    assert localized["blocks"][4]["subtitle"] == "Notebookで inspect error slices, PDP, and residual segments."
    assert localized["blocks"][5]["title"] == "approved target rebuild と evaluation"
    assert localized["blocks"][5]["subtitle"] == "承認後はresolved target candidate、evaluation rerun、case queue reviewが必要。"
    assert localized["blocks"][6]["title"] == "データアップロード / project context"
    assert localized["blocks"][6]["subtitle"] == "Dataset identity、target hint、locale、output contractが確定している。"

    japanese_alias_response = client.get(
        f"/api/projects/{project_id}/research-plan/timeline",
        params={"locale": "Japanese"},
    )
    assert japanese_alias_response.status_code == 200
    japanese_alias = japanese_alias_response.json()
    assert japanese_alias["response_locale"] == "Japanese"
    assert japanese_alias["blocks"][0]["title"] == "深いEDA"
    assert japanese_alias["blocks"][1]["title"] == "approval response contract v19"
    assert japanese_alias["blocks"][1]["subtitle"] == "Prepare the data owner reply shape."


def test_research_plan_timeline_initializes_harness_anchors_when_empty(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Initial plan anchors"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline?locale=ja-JP")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision_author_type"] == "harness"
    assert payload["contract_validation"]["status"] == "ok"
    assert [block["id"] for block in payload["blocks"][:4]] == [
        "data_upload",
        "objective_framing",
        "data_understanding",
        "prior_knowledge_research",
    ]
    assert payload["blocks"][0]["status"] == "active"
    assert payload["blocks"][0]["title"] == "データアップロード"
    assert payload["blocks"][1]["status"] == "pending"


def test_research_plan_tool_substrate_endpoints_expose_codex_owned_progress(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan substrate API"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    revision_response = client.post(
        f"/api/projects/{project_id}/research-plan/revisions",
        json={
            "document": {
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "deep_data_understanding",
                        "title": "Deep data understanding",
                        "why_it_matters": "Understand the relational data before modeling.",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            "reason": "Codex committed the current plan.",
            "author_type": "codex",
        },
    )
    assert revision_response.status_code == 200, revision_response.text
    revision = revision_response.json()
    assert revision["created"] is True
    assert revision["revision_index"] == 1

    current_response = client.post(
        f"/api/projects/{project_id}/research-plan/current-work",
        json={
            "node_id": "deep_data_understanding",
            "summary": "Inspecting key coverage and preparing the EDA notebook.",
            "expected_outputs": ["marimo notebook", "finding summary"],
            "revision_id": revision["revision_id"],
        },
    )
    assert current_response.status_code == 200, current_response.text
    assert current_response.json()["current_work"]["node_id"] == "deep_data_understanding"

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        notebook_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="deep_data_understanding_notebook",
            filename="notebook_manifest.json",
            payload={"path": "notebooks/deep_data_understanding.py"},
            metadata={"project_id": project_id},
        )
        db.commit()

    link_response = client.post(
        f"/api/projects/{project_id}/research-plan/artifacts",
        json={
            "node_id": "deep_data_understanding",
            "artifact_id": notebook_artifact.id,
            "role": "notebook",
            "revision_id": revision["revision_id"],
        },
    )
    assert link_response.status_code == 200, link_response.text
    assert link_response.json()["link"]["metadata"]["node_id"] == "deep_data_understanding"

    attention_response = client.post(
        f"/api/projects/{project_id}/research-plan/human-attention",
        json={
            "node_id": "deep_data_understanding",
            "question": "Is this target definition production-facing?",
            "why_it_matters": "The answer changes evaluation and leakage boundaries.",
            "provisional_assumption": "Continue as provisional and record the risk.",
            "urgency": "high",
            "revision_id": revision["revision_id"],
        },
    )
    assert attention_response.status_code == 200, attention_response.text
    assert attention_response.json()["question"]["topic"] == "research_plan"
    assert attention_response.json()["question"]["can_proceed_without_answer"] is True

    timeline_response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["source_revision_id"] == revision["revision_id"]
    assert timeline["current_work"]["node_id"] == "deep_data_understanding"
    assert timeline["current_work"]["expected_outputs"] == ["marimo notebook", "finding summary"]
    assert timeline["artifact_links"][0]["artifact_id"] == notebook_artifact.id
    assert timeline["blocks"][0]["attached_artifacts"][0]["role"] == "notebook"


def test_research_plan_tool_endpoint_rejects_invalid_done_payload_with_issues(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan substrate rejection"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    revision_response = client.post(
        f"/api/projects/{project_id}/research-plan/revisions",
        json={
            "document": {
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            "reason": "Invalid Codex tool commit should return fixable issues.",
            "author_type": "codex",
        },
    )

    assert revision_response.status_code == 400, revision_response.text
    detail = revision_response.json()["detail"]
    assert detail["schema_version"] == "research_plan_tool_error.v1"
    issue_codes = {issue["code"] for issue in detail["issues"]}
    assert "done_node_missing_deliverable_contract" in issue_codes
    assert "done_node_missing_completion_evidence" in issue_codes

    timeline_response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert timeline_response.status_code == 200
    timeline_payload = timeline_response.json()
    assert timeline_payload["revision_author_type"] == "harness"
    assert timeline_payload["blocks"][0]["id"] == "data_upload"
    assert timeline_payload["blocks"][0]["status"] == "active"


def test_research_plan_timeline_uses_artifact_locale_and_codex_display_fields(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan display locale"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_plan_with_display_locale",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "project": {"locale": "ja-JP"},
                "timeline_blocks": [
                    {
                        "id": "approval_contract",
                        "title": "approval response contract",
                        "why_it_matters": "Keep the owner decision reversible and auditable.",
                        "next_action": "Review the response choices.",
                        "done_criteria": "The owner can answer without ambiguity.",
                        "blockers": ["Owner answer is missing."],
                        "display_title": "承認応答の設計",
                        "display_why_it_matters": "オーナー判断を可逆的かつ監査可能に保ちます。",
                        "display_next_action": "回答選択肢を確認します。",
                        "display_done_criteria": "オーナーが迷わず回答できること。",
                        "display_blockers": ["オーナー回答が未提出です。"],
                        "status": "active",
                        "subtasks": [
                            {
                                "id": "response_options",
                                "title": "response options",
                                "detail": "Check choices before publication.",
                                "status": "pending",
                                "human_display": {
                                    "title": "回答選択肢",
                                    "detail": "公開前に選択肢を確認します。",
                                },
                            }
                        ],
                    },
                    {
                        "id": "translation_map",
                        "title": "model review",
                        "why_it_matters": "Keep diagnostics readable.",
                        "status": "pending",
                        "translations": {
                            "ja": {
                                "title": "モデル確認",
                                "why_it_matters": "診断結果を読みやすく保ちます。",
                            }
                        },
                    },
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["requested_locale"] is None
    assert timeline["authored_locale"] == "ja-JP"
    assert timeline["response_locale"] == "ja-JP"
    assert timeline["blocks"][0]["title"] == "承認応答の設計"
    assert timeline["blocks"][0]["subtitle"] == "オーナー判断を可逆的かつ監査可能に保ちます。"
    assert timeline["blocks"][0]["next_action"] == "回答選択肢を確認します。"
    assert timeline["blocks"][0]["done_criteria"] == "オーナーが迷わず回答できること。"
    assert timeline["blocks"][0]["blockers"] == ["オーナー回答が未提出です。"]
    assert timeline["blocks"][0]["subtasks"][0]["title"] == "回答選択肢"
    assert timeline["blocks"][0]["subtasks"][0]["detail"] == "公開前に選択肢を確認します。"
    assert timeline["blocks"][1]["title"] == "モデル確認"
    assert timeline["blocks"][1]["subtitle"] == "診断結果を読みやすく保ちます。"


def test_research_plan_timeline_uses_artifact_locale_when_query_locale_absent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan artifact locale"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_artifact_locale"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_artifact_locale",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep plan display readable.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_plan_artifact_locale",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "project": {"locale": "ja-JP"},
                "timeline_blocks": [
                    {
                        "id": "codex_added_plan",
                        "title": "model review and deployment readiness",
                        "why_it_matters": "Explain the next validation work.",
                        "status": "active",
                    }
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["requested_locale"] is None
    assert timeline["response_locale"] == "ja-JP"
    assert timeline["blocks"][0]["title"] == "model review and deployment readiness"
    assert timeline["blocks"][0]["subtitle"] == "Explain the next validation work."


def test_research_plan_timeline_defaults_to_latest_project_locale(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / "p_project_locale_plan" / "ags_project_locale_plan"

    with app.state.session_factory() as db:
        user = User(id="u_project_locale_plan", email="plan-locale-default@example.com", locale="ja-JP")
        project = Project(
            id="p_project_locale_plan",
            name="Project locale plan",
            created_by=user.id,
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        db.add_all([user, project])
        db.commit()
        session = AgentSession(
            id="ags_project_locale_plan",
            project_id=project.id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep project plan display localized.",
            workspace_path=str(workspace),
            created_by=user.id,
        )
        db.add(session)
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project.id,
            asset_type="research_plan",
            name="codex_plan_project_locale",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "codex_added_modeling",
                        "title": "Model diagnostics and feature importance",
                        "why_it_matters": "Explain error slices before choosing the next experiment.",
                        "status": "active",
                    }
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get("/api/projects/p_project_locale_plan/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["response_locale"] == "ja-JP"
    assert timeline["requested_locale"] == "ja-JP"
    assert timeline["blocks"][0]["title"] == "Model diagnostics and feature importance"
    assert timeline["blocks"][0]["subtitle"] == "Explain error slices before choosing the next experiment."


def test_adaptive_strategy_brief_returns_locale_display_fields(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Strategy locale"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    response = client.get(f"/api/projects/{project_id}/approach/strategy-brief?locale=ja-JP")
    assert response.status_code == 200, response.text
    brief = response.json()
    assert brief["response_locale"] == "ja-JP"
    assert brief["recommended_next_action"]["label"] == "Upload data"
    assert brief["recommended_next_action"]["display_label"] == "データをアップロードする"
    assert "DatasetSnapshot" not in brief["recommended_next_action"]["display_reason"]
    data_lane = next(lane for lane in brief["candidate_lanes"] if lane["lane_id"] == "data_understanding")
    assert data_lane["title"] == "Understand data before choosing the task shape"
    assert data_lane["display_title"] == "データ理解を先に固める"
    assert data_lane["display"]["why"]

    job_response = client.post(
        f"/api/projects/{project_id}/approach/strategy-brief",
        json={"locale": "ja-JP"},
    )
    assert job_response.status_code == 200, job_response.text
    job = job_response.json()
    assert job["status"] == "queued"
    output = run_queued_job(client, job["id"])
    assert output["response_locale"] == "ja-JP"
    artifact_response = client.get(f"/api/artifacts/{output['adaptive_strategy_brief_artifact_id']}/download")
    assert artifact_response.status_code == 200
    artifact_payload = artifact_response.json()
    assert artifact_payload["response_locale"] == "ja-JP"
    assert artifact_payload["candidate_lanes"][0]["display_title"]


def test_model_candidates_endpoint_queues_requested_models_into_leaderboard(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Candidate training", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,segment,target"]
    for index in range(1, 61):
        target = 1 if index % 3 == 0 else 0
        segment = "high" if index % 5 in {0, 1} else "low"
        rows.append(f"{index},{segment},{target}")
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("candidate_training.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    assert design_response.json()["status"] == "queued"
    run_queued_job(client, design_response.json()["id"])
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    primary = next(item for item in candidates_response.json() if item["status"] == "primary_candidate")
    promote_response = client.post(f"/api/evaluation-candidates/{primary['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]
    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200, approve_response.text
    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    assert split_response.json()["status"] == "queued"
    run_queued_job(client, split_response.json()["id"])

    queue_response = client.post(
        f"/api/projects/{project_id}/model-candidates/run",
        json={"models": ["LightGBM", "LogisticRegression"]},
    )
    assert queue_response.status_code == 200, queue_response.text
    queued_training_job = queue_response.json()
    assert queued_training_job["job_type"] == "train_model_candidates"
    assert queued_training_job["status"] == "queued"
    assert set(queued_training_job["input"]["normalized_models"]) == {"lightgbm", "logistic_regression"}

    run_job_response = client.post(f"/api/jobs/{queued_training_job['id']}/run")
    assert run_job_response.status_code == 200, run_job_response.text
    nudged_job = run_job_response.json()
    assert nudged_job["status"] == "queued"
    assert nudged_job["priority"] >= 90

    interactive_worker_response = client.post("/api/worker/run-once")
    assert interactive_worker_response.status_code == 200, interactive_worker_response.text
    assert interactive_worker_response.json() is None
    queued_after_interactive_response = client.get(f"/api/projects/{project_id}/jobs")
    assert queued_after_interactive_response.status_code == 200
    queued_after_interactive = next(
        item for item in queued_after_interactive_response.json() if item["id"] == queued_training_job["id"]
    )
    assert queued_after_interactive["status"] == "queued"

    worker_response = client.post("/api/worker/run-once?include_long_running=true")
    assert worker_response.status_code == 200, worker_response.text
    training_job = worker_response.json()
    assert training_job["id"] == queued_training_job["id"]
    assert training_job["status"] == "succeeded"
    assert training_job["output"]["success_count"] == 2
    assert training_job["output"]["worker_events"][0]["display_name"] == "Training Worker"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard = leaderboard_response.json()
    assert len(leaderboard) == 2
    baseline_types = {row["metrics"]["baseline_type"] for row in leaderboard}
    assert baseline_types == {"lightgbm_classifier", "logistic_regression"}
    assert {row["model_id"] for row in leaderboard} == {"lightgbm_classifier", "logistic_regression"}
    assert all(row["display_metric_name"] for row in leaderboard)


def test_notebook_execution_endpoints_queue_worker_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Notebook execution queue"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    notebook_source = "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n"

    with app.state.session_factory() as db:
        notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="analysis_notebook",
            name="codex_authored_notebook",
            filename="notebook.py",
            text=notebook_source,
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        notebook_id = notebook.id
        marimo_notebook = store_text_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="marimo_notebook",
            name="codex_authored_marimo_notebook",
            filename="marimo_notebook.py",
            text=notebook_source,
            metadata={"project_id": project_id, "notebook_kind": "data_understanding"},
        )
        marimo_notebook_id = marimo_notebook.id
        db.commit()

    plan_response = client.post(f"/api/analysis-notebooks/{notebook_id}/execution-plan")
    assert plan_response.status_code == 200, plan_response.text
    plan_job = plan_response.json()
    assert plan_job["status"] == "queued"
    assert plan_job["job_type"] == "plan_notebook_execution"
    assert plan_job["policy"]["execution"] == "queued_worker"
    plan_output = run_queued_job(client, plan_job["id"])
    assert plan_output["execution_status"] == "planned_not_executed"
    assert plan_output["analysis_notebook_artifact_id"] == notebook_id
    assert plan_output["notebook_execution_plan_artifact_id"]
    assert plan_output["agent_task_contract_artifact_id"]

    removed_capture_response = client.post(f"/api/analysis-notebooks/{notebook_id}/execution-capture")
    assert removed_capture_response.status_code == 405

    marimo_plan_response = client.post(f"/api/analysis-notebooks/{marimo_notebook_id}/execution-plan")
    assert marimo_plan_response.status_code == 200, marimo_plan_response.text
    marimo_plan_output = run_queued_job(client, marimo_plan_response.json()["id"])
    assert marimo_plan_output["analysis_notebook_artifact_id"] == marimo_notebook_id
    assert marimo_plan_output["notebook_execution_plan_artifact_id"]


def test_core_harness_actions_use_explicit_endpoints(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Explicit action loop", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,segment,target"] + [f"{index},{'A' if index % 2 else 'B'},{index % 2}" for index in range(1, 14)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("explicit_actions.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    understanding_response = client.post(f"/api/projects/{project_id}/understanding/run")
    assert understanding_response.status_code == 200, understanding_response.text
    understanding_job = understanding_response.json()
    assert understanding_job["status"] == "queued"
    assert understanding_job["job_type"] == "profile_dataset"
    understanding_output = run_queued_job(client, understanding_job["id"])
    assert understanding_output["dataset_snapshot_id"]
    assert understanding_output["source_dataset_snapshot_id"] == dataset_id

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "queued"
    quality_output = run_queued_job(client, quality_job["id"])
    assert quality_output["artifact_ids"]

    evaluation_response = client.post(f"/api/projects/{project_id}/evaluation/compare")
    assert evaluation_response.status_code == 200, evaluation_response.text
    evaluation_job = evaluation_response.json()
    assert evaluation_job["status"] == "queued"
    evaluation_output = run_queued_job(client, evaluation_job["id"])
    assert evaluation_output["artifact_id"]

    report_response = client.post(f"/api/projects/{project_id}/decision-report/generate")
    assert report_response.status_code == 200, report_response.text
    report_job = report_response.json()
    assert report_job["status"] == "queued"
    assert report_job["policy"]["execution"] == "queued_worker"
    report_output = run_queued_job(client, report_job["id"])
    assert report_output["decision_report_artifact_id"]

    readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert readout_response.status_code == 200, readout_response.text
    readout = readout_response.json()
    assert readout["schema_version"] == "result_readout.v1"

def test_relational_schema_hint_upload_preview_and_agent_route(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "ER evidence"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    er_json = {
        "tables": [
            {"table_name": "customers", "columns": ["customer_id", "segment"]},
            {"table_name": "applications", "columns": ["application_id", "customer_id", "target"]},
        ],
        "relationships": [
            {
                "left_table": "customers",
                "left_column": "customer_id",
                "right_table": "applications",
                "right_column": "customer_id",
                "relation_type": "one_to_many",
                "confidence": 0.85,
            }
        ],
    }
    json_upload_response = client.post(
        f"/api/projects/{project_id}/relational/schema-hints/upload",
        files={"file": ("er_hint.json", json.dumps(er_json).encode("utf-8"), "application/json")},
        data={"note": "Customer to application relationship from source ERD."},
    )
    assert json_upload_response.status_code == 200, json_upload_response.text
    json_job = json_upload_response.json()
    assert json_job["status"] == "queued"
    assert json_job["policy"]["execution"] == "queued_worker"
    json_output = run_queued_job(client, json_job["id"])
    assert json_output["schema_version"] == "relational_schema_hint.v1"
    assert json_output["parsed_table_count"] == 2
    assert json_output["parsed_relationship_count"] == 1

    json_preview_response = client.get(
        f"/api/artifacts/{json_output['relational_schema_hint_artifact_id']}/preview"
    )
    assert json_preview_response.status_code == 200
    json_preview = json_preview_response.json()
    assert json_preview["content_type"] == "json"
    assert "customers" in json_preview["preview"]

    report_preview_response = client.get(
        f"/api/artifacts/{json_output['relational_schema_hint_report_artifact_id']}/preview"
    )
    assert report_preview_response.status_code == 200
    report_preview = report_preview_response.json()["preview"]
    assert "Relational Schema Hint" in report_preview
    assert "customers.customer_id -> applications.customer_id" in report_preview

    png_upload_response = client.post(
        f"/api/projects/{project_id}/relational/schema-hints/upload",
        files={"file": ("er_diagram.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png")},
    )
    assert png_upload_response.status_code == 200, png_upload_response.text
    png_job = png_upload_response.json()
    assert png_job["status"] == "queued"
    assert png_job["policy"]["execution"] == "queued_worker"
    png_output = run_queued_job(client, png_job["id"])
    png_preview_response = client.get(
        f"/api/artifacts/{png_output['relational_schema_hint_artifact_id']}/preview"
    )
    assert png_preview_response.status_code == 200
    png_preview = png_preview_response.json()
    assert png_preview["content_type"] == "image/png"
    assert png_preview["preview_available"] is True
    assert png_preview["preview"].endswith("/download")



def test_upload_data_bundle_profiles_primary_supporting_tables_and_er_hint(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Bundle upload"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    application_csv = "\n".join(
        [
            "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL",
            "100001,0,150000",
            "100002,1,90000",
            "100003,0,120000",
        ]
    )
    bureau_csv = "\n".join(
        [
            "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE",
            "100001,50001,Active",
            "100001,50002,Closed",
            "100002,50003,Active",
        ]
    )
    er_json = {
        "tables": [{"name": "application_train"}, {"name": "bureau"}],
        "relationships": [
            {
                "left_table": "application_train",
                "left_column": "SK_ID_CURR",
                "right_table": "bureau",
                "right_column": "SK_ID_CURR",
                "relation_type": "one_to_many",
            }
        ],
    }

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload-bundle",
        files=[
            ("files", ("application_train.csv", application_csv.encode("utf-8"), "text/csv")),
            ("files", ("bureau.csv", bureau_csv.encode("utf-8"), "text/csv")),
            ("files", ("home_credit_er.json", json.dumps(er_json).encode("utf-8"), "application/json")),
        ],
        data={
            "primary_filename": "application_train.csv",
            "target_column": "TARGET",
            "note": "Home Credit style one-to-many relationship.",
        },
    )
    assert upload_response.status_code == 200, upload_response.text
    job = upload_response.json()
    assert job["status"] == "queued"
    assert job["output"]["schema_version"] == "upload_data_bundle_staging.v1"
    assert job["output"]["staged_table_artifact_ids"]
    output = run_queued_job(client, job["id"])
    assert output["schema_version"] == "upload_data_bundle.v1"
    assert output["dataset_snapshot_id"]
    assert len(output["supporting_table_artifact_ids"]) == 1
    assert len(output["relational_hint_artifact_ids"]) == 1
    assert output["relational_catalog_artifact_id"]
    assert output["relational_table_bundle_manifest_artifact_id"]
    assert output["analysis_notebook_artifact_id"] is None
    assert output["notebook_kind"] is None
    assert output["notebook_warning"] == "awaiting_agent_authored_notebook"
    assert output["notebook_authoring_brief_artifact_ids"]
    assert output["runner_context"]["fixed_recipe_required"] is False
    project_after_upload = client.get(f"/api/projects/{project_id}").json()
    assert project_after_upload["primary_dataset_snapshot_id"] == output["dataset_snapshot_id"]
    datasets_after_upload = client.get(f"/api/projects/{project_id}/datasets").json()
    assert datasets_after_upload[0]["id"] == output["dataset_snapshot_id"]
    assert datasets_after_upload[0]["is_primary"] is True

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {artifact["asset_type"] for artifact in artifacts_response.json()}
    assert "dataset_snapshot" in asset_types
    assert "uploaded_supporting_table" in asset_types
    assert "relational_schema_hint" in asset_types
    assert "relational_catalog" in asset_types
    assert "relational_table_bundle_manifest" in asset_types
    assert "analysis_notebook" not in asset_types
    assert "notebook_authoring_brief" in asset_types

    catalog_preview_response = client.get(f"/api/artifacts/{output['relational_catalog_artifact_id']}/preview")
    assert catalog_preview_response.status_code == 200
    catalog_preview = catalog_preview_response.json()
    assert catalog_preview["content_type"] == "json"
    assert "application_train" in catalog_preview["preview"]
    assert "runner_defined" in catalog_preview["preview"]

    primary_change_response = client.post(
        f"/api/projects/{project_id}/datasets/primary",
        json={"artifact_id": output["supporting_table_artifact_ids"][0], "target_column": "TARGET"},
    )
    assert primary_change_response.status_code == 200, primary_change_response.text
    changed_dataset = primary_change_response.json()
    assert changed_dataset["source_ref"] == "bureau.csv"
    assert changed_dataset["is_primary"] is True
    project_after_change = client.get(f"/api/projects/{project_id}").json()
    assert project_after_change["primary_dataset_snapshot_id"] == changed_dataset["id"]
    datasets_after_change = client.get(f"/api/projects/{project_id}/datasets").json()
    assert datasets_after_change[0]["id"] == changed_dataset["id"]
    assert datasets_after_change[0]["artifact_id"] == output["supporting_table_artifact_ids"][0]
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        task_spec_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "task_spec")
            .order_by(Artifact.created_at.desc())
            .limit(1)
        )
        assert task_spec_artifact is not None
        task_spec = loads_json(artifact_primary_path(task_spec_artifact).read_text(encoding="utf-8"), {})
        assert task_spec["status"] == "user_confirmed"
        assert task_spec["objective_text"] == "TARGET"
        assert task_spec["targets"] == [
            {"column": "TARGET", "derivation": None, "table_ref": changed_dataset["id"]}
        ]


def test_upload_data_bundle_allows_primary_table_to_remain_open(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Bundle primary open"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload-bundle",
        files=[
            ("files", ("a.csv", b"id,target\n1,0\n", "text/csv")),
            ("files", ("b.csv", b"id,value\n1,10\n", "text/csv")),
        ],
    )
    assert upload_response.status_code == 200, upload_response.text
    job = upload_response.json()
    output = run_queued_job(client, job["id"])
    assert output["schema_version"] == "upload_data_bundle.v1"
    assert output["dataset_snapshot_id"] is None
    assert output["primary_dataset_snapshot_id"] is None
    assert len(output["dataset_snapshot_ids"]) == 2
    project_after_upload = client.get(f"/api/projects/{project_id}").json()
    assert project_after_upload["primary_dataset_snapshot_id"] is None
    assert project_after_upload["target_column"] is None

    columns_response = client.get(f"/api/projects/{project_id}/data/columns")
    assert columns_response.status_code == 200
    column_catalog = columns_response.json()
    assert {table["source_ref"] for table in column_catalog["tables"]} == {"a.csv", "b.csv"}
    for table in column_catalog["tables"]:
        assert table["is_primary"] is False
        for column in table["column_details"]:
            assert "role" not in column
            assert "is_leakage_suspect" not in column
            assert "available_at_prediction_time" not in column

    start_response = client.post(f"/api/projects/{project_id}/autonomy/start", json={"autonomy_mode": "full_auto"})
    assert start_response.status_code == 200, start_response.text
    start_job = start_response.json()
    assert start_job["status"] == "succeeded"
    assert start_job["output"]["schema_version"] == "agent_session_start.v1"
    project_after_start = client.get(f"/api/projects/{project_id}").json()
    assert project_after_start["current_phase"] == "AUTONOMOUS_LOOP"
    assert project_after_start["autonomy_mode"] == "full_auto"



def test_portal_overview_ideas_and_agent_activity(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Portal Ops", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    idea_response = client.post("/api/portal/ideas", json={"text": "Make worker boxes transient and lively."})
    assert idea_response.status_code == 200, idea_response.text
    idea = idea_response.json()
    assert idea["artifact_id"]
    assert idea["text"].startswith("Make worker")

    ideas_response = client.get("/api/portal/ideas")
    assert ideas_response.status_code == 200
    assert any(item["id"] == idea["id"] for item in ideas_response.json())

    csv_bytes = b"feature,target\n1,0\n2,1\n3,0\n4,1\n"
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("portal.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    notebook_response = client.post(f"/api/projects/{project_id}/analysis-notebooks/data-understanding")
    assert notebook_response.status_code == 200, notebook_response.text
    notebook_job = notebook_response.json()
    assert notebook_job["status"] == "queued"
    assert notebook_job["job_type"] == "prepare_data_understanding_notebook_authoring"
    notebook_output = run_queued_job(client, notebook_job["id"])
    assert notebook_output["analysis_notebook_artifact_id"] is None
    assert notebook_output["notebook_authoring_brief_artifact_id"]

    eda_response = client.post(f"/api/datasets/{dataset_id}/eda-review")
    assert eda_response.status_code == 200, eda_response.text
    eda_job = eda_response.json()
    assert eda_job["status"] == "queued"
    eda_output = run_queued_job(client, eda_job["id"])
    assert eda_output["eda_review_bundle_artifact_id"]

    author_response = client.post(f"/api/projects/{project_id}/notebook-authoring/brief")
    assert author_response.status_code == 200, author_response.text
    author_job = author_response.json()
    assert author_job["status"] == "queued"
    author_output = run_queued_job(client, author_job["id"])
    assert author_output["notebook_authoring_brief_artifact_id"]

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "状況を説明してください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["intent"]["type"] == "agent_conversation"
    assert chat["actions"] == []
    assert chat["response_composer"]["status"] == "queued"

    run_queued_agent_chat_turn(client, chat["job"]["id"])
    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history[-1]["response_brief"]["conversation_context"]["counts"]["datasets"] == 1

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["schema_version"] == "agent_activity.v1"

    overview_response = client.get("/api/portal/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["schema_version"] == "portal_overview.v1"
    assert overview["summary"]["project_count"] >= 1
    assert overview["summary"]["active_project_count"] == 1
    assert overview["summary"]["idea_count"] >= 1
    recent_updates = overview["recent_updates"]
    assert all("agent_chat_turn" not in update["title"] for update in recent_updates)
    assert all("agent_chat_turn" not in update["summary"] for update in recent_updates)


def test_portal_overview_limits_terminal_upload_import_activity_cards(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Portal intake history"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    now = utc_now()
    with app.state.session_factory() as db:
        for index in range(7):
            job_type = "upload_data_bundle" if index % 2 == 0 else "import_benchmark_dataset"
            job = create_job(db, job_type=job_type, project_id=project_id)
            observed_at = now - timedelta(seconds=index)
            job.status = "succeeded"
            job.created_at = observed_at
            job.updated_at = observed_at
            job.started_at = observed_at
            job.ended_at = observed_at
            job.output_json = json.dumps(
                {
                    "worker_events": [
                        {
                            "worker_id": f"intake-{index}",
                            "status": "succeeded",
                            "headline": "Data import finished",
                            "detail": "Data import finished",
                            "created_at": observed_at.isoformat(),
                            "updated_at": observed_at.isoformat(),
                        }
                    ]
                }
            )
        db.commit()

    overview_response = client.get("/api/portal/overview")
    assert overview_response.status_code == 200
    activity = overview_response.json()["agent_activity"]
    intake_ids = [
        event["worker_id"]
        for event in activity
        if event.get("job_type") in {"upload_data_bundle", "import_benchmark_dataset"}
    ]

    assert intake_ids == ["intake-0", "intake-1", "intake-2", "intake-3", "intake-4"]
    jobs_response = client.get(f"/api/projects/{project_id}/jobs")
    assert jobs_response.status_code == 200
    assert len([job for job in jobs_response.json() if job["job_type"] in {"upload_data_bundle", "import_benchmark_dataset"}]) == 7


def test_project_upload_profile_evaluation_split_flow(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Demo", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    csv_bytes = (
        b"customer_id,created_at,feature,target,final_status\n"
        b"c1,2026-01-01,10,1,won\n"
        b"c1,2026-01-02,11,0,lost\n"
        b"c2,2026-01-03,13,1,won\n"
        b"c2,2026-01-04,9,0,lost\n"
        b"c3,2026-01-05,8,1,won\n"
        b"c3,2026-01-06,7,0,lost\n"
    )
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("demo.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]
    assert upload_response.json()["dataset_snapshot"]["row_count"] == 6

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "queued"
    quality_output = run_queued_job(client, quality_job["id"])
    assert len(quality_output["artifact_ids"]) == 3
    quality_gate = quality_output["gate"]
    assert quality_gate["schema_version"] == "data_quality_gate.v1"
    assert quality_gate["summary"]["severity"] in {"warning", "pass"}
    assert "final_status" not in quality_gate["evaluation_guidance"]["excluded_columns"]
    assert quality_output["insight_id"]

    latest_quality_response = client.get(f"/api/datasets/{dataset_id}/quality/latest")
    assert latest_quality_response.status_code == 200
    quality_artifact_id = latest_quality_response.json()["id"]
    quality_preview_response = client.get(f"/api/artifacts/{quality_artifact_id}/preview")
    assert quality_preview_response.status_code == 200
    assert "data_quality_gate.v1" in quality_preview_response.json()["preview"]

    eda_review_response = client.post(f"/api/datasets/{dataset_id}/eda-review")
    assert eda_review_response.status_code == 200, eda_review_response.text
    eda_review_job = eda_review_response.json()
    assert eda_review_job["status"] == "queued"
    assert eda_review_job["job_type"] == "run_eda_review"
    eda_review_output = run_queued_job(client, eda_review_job["id"])
    assert eda_review_output["schema_version"] == "eda_review.v1"
    assert eda_review_output["eda_review_bundle_artifact_id"]
    assert eda_review_output["eda_review_report_id"]
    assert len(eda_review_output["eda_review_figure_artifact_ids"]) >= 4
    eda_bundle_response = client.get(
        f"/api/artifacts/{eda_review_output['eda_review_bundle_artifact_id']}/download"
    )
    assert eda_bundle_response.status_code == 200
    eda_bundle = eda_bundle_response.json()
    assert eda_bundle["schema_version"] == "eda_review.v1"
    assert eda_bundle["dataset_snapshot_id"] == dataset_id
    assert eda_bundle["summary"]["target_column"] == "target"
    assert eda_bundle["read_this_first"]
    assert eda_bundle["story_cards"]
    assert eda_bundle["playbook"]
    assert eda_bundle["codex_next_prompts"]
    eda_svg_response = client.get(
        f"/api/artifacts/{eda_review_output['eda_review_figure_artifact_ids'][0]}/preview"
    )
    assert eda_svg_response.status_code == 200
    assert eda_svg_response.json()["content_type"] == "image/svg+xml"

    eda_story_response = client.get(f"/api/projects/{project_id}/analysis-story")
    assert eda_story_response.status_code == 200, eda_story_response.text
    eda_story = eda_story_response.json()
    assert eda_story["schema_version"] == "analysis_story_surface.v1"
    assert eda_story["available"] is False
    assert eda_story["story"] is None
    assert eda_story["empty_state"]["primary_action"]["action_type"] == "start_autonomous_loop"

    assumptions_response = client.get(f"/api/projects/{project_id}/assumptions")
    assert assumptions_response.status_code == 200
    assumptions = assumptions_response.json()
    assert assumptions
    assert not any(item["fallback_policy"] == "exclude_until_confirmed" for item in assumptions)

    infer_response = client.post(f"/api/projects/{project_id}/assumptions/infer")
    assert infer_response.status_code == 200, infer_response.text
    infer_job = infer_response.json()
    assert infer_job["status"] == "queued"
    assert infer_job["job_type"] == "infer_assumptions"
    infer_output = run_queued_job(client, infer_job["id"])
    assert infer_output["policy"] == "fallbacks_already_materialized_in_assumptions"
    assert infer_output["unanswered_questions"] >= 0

    review_queue_response = client.get(f"/api/projects/{project_id}/assumptions/review-queue")
    assert review_queue_response.status_code == 200, review_queue_response.text
    review_queue = review_queue_response.json()
    assert review_queue["schema_version"] == "assumption_review_queue.v1"
    assert review_queue["counts"]["total_assumptions"] >= 1
    assert review_queue["next_item"]["item_type"] in {"assumption", "question"}
    assert review_queue["next_item"]["primary_actions"]
    if review_queue["next_item"]["item_type"] == "assumption":
        assert review_queue["next_item"]["evidence"]
        confirm_review_response = client.post(f"/api/assumptions/{review_queue['next_item']['id']}/confirm")
        assert confirm_review_response.status_code == 200, confirm_review_response.text
        next_review_queue_response = client.get(f"/api/projects/{project_id}/assumptions/review-queue")
        assert next_review_queue_response.status_code == 200
        assert next_review_queue_response.json()["next_item"]["id"] != review_queue["next_item"]["id"]

    understanding_response = client.get(f"/api/projects/{project_id}/understanding/latest")
    assert understanding_response.status_code == 200
    assert "Data Understanding" in understanding_response.json()["markdown"]

    notebook_response = client.post(f"/api/projects/{project_id}/analysis-notebooks/data-understanding")
    assert notebook_response.status_code == 200, notebook_response.text
    notebook_job = notebook_response.json()
    assert notebook_job["status"] == "queued"
    assert notebook_job["job_type"] == "prepare_data_understanding_notebook_authoring"
    notebook_output = run_queued_job(client, notebook_job["id"])
    assert notebook_output["schema_version"] == "notebook_authoring_preparation.v1"
    assert notebook_output["execution_status"] == "awaiting_agent_authored_notebook"
    assert notebook_output["analysis_notebook_artifact_id"] is None
    assert notebook_output["notebook_run_manifest_artifact_id"] is None
    assert notebook_output["notebook_report_id"] is None
    assert notebook_output["notebook_authoring_brief_artifact_id"]

    authoring_preview_response = client.get(
        f"/api/artifacts/{notebook_output['notebook_authoring_brief_artifact_id']}/preview"
    )
    assert authoring_preview_response.status_code == 200
    authoring_preview = authoring_preview_response.json()
    assert authoring_preview["preview_available"] is True
    assert authoring_preview["content_type"] == "json"
    assert "notebook_authoring_brief.v1" in authoring_preview["preview"]

    notebook_index_response = client.get(f"/api/projects/{project_id}/analysis-notebooks")
    assert notebook_index_response.status_code == 200
    notebook_index = notebook_index_response.json()
    assert notebook_index["counts"]["total"] == 0

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    first_question = questions_response.json()[0]
    answer_response = client.post(
        f"/api/questions/{first_question['id']}/answer",
        json={"answer_value": first_question["choices"][0], "answer_text": "integration test"},
    )
    assert answer_response.status_code == 200
    assert answer_response.json()["question_id"] == first_question["id"]

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200
    design_job = design_response.json()
    assert design_job["status"] == "queued"
    run_queued_job(client, design_job["id"])

    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    primary = next(item for item in candidates if item["status"] == "primary_candidate")
    assert primary["split_type"] == "stratified"
    assert primary["stratify_column"] == "target"

    scenario_compare_response = client.post(f"/api/projects/{project_id}/evaluation/compare")
    assert scenario_compare_response.status_code == 200, scenario_compare_response.text
    scenario_compare_job = scenario_compare_response.json()
    assert scenario_compare_job["status"] == "queued"
    scenario_compare_output = run_queued_job(client, scenario_compare_job["id"])
    assert scenario_compare_output["artifact_id"]
    assert scenario_compare_output["candidate_count"] >= 2
    scenario_compare_preview_response = client.get(
        f"/api/artifacts/{scenario_compare_output['artifact_id']}/preview"
    )
    assert scenario_compare_preview_response.status_code == 200
    scenario_compare_preview = scenario_compare_preview_response.json()["preview"]
    assert "evaluation_scenario_comparison.v1" in scenario_compare_preview
    assert "decision_support" in scenario_compare_preview

    promote_response = client.post(f"/api/evaluation-candidates/{primary['id']}/promote")
    assert promote_response.status_code == 200
    spec_id = promote_response.json()["id"]

    approval_review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert approval_review_response.status_code == 200, approval_review_response.text
    approval_review_job = approval_review_response.json()
    assert approval_review_job["status"] == "queued"
    approval_review_output = run_queued_job(client, approval_review_job["id"])
    assert approval_review_output["artifact_id"]
    assert approval_review_output["review_status"] in {"ready", "ready_with_assumptions"}
    approval_review_preview_response = client.get(
        f"/api/artifacts/{approval_review_output['artifact_id']}/preview"
    )
    assert approval_review_preview_response.status_code == 200
    approval_review_preview = approval_review_preview_response.json()["preview"]
    assert "evaluation_approval_review.v1" in approval_review_preview
    assert "assumption_backed_proceed" in approval_review_preview

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    split_job = split_response.json()
    assert split_job["status"] == "queued"
    split_output = run_queued_job(client, split_job["id"])
    split_response = client.get(f"/api/split-manifests/{split_output['split_manifest_id']}")
    assert split_response.status_code == 200, split_response.text
    split = split_response.json()
    assert split["train_count"] > 0
    assert split["valid_count"] > 0
    assert split["project_id"] == project_id

    strategy_plan_response = client.post(f"/api/projects/{project_id}/baseline/strategy-plan")
    assert strategy_plan_response.status_code == 200, strategy_plan_response.text
    strategy_plan_job = strategy_plan_response.json()
    assert strategy_plan_job["status"] == "queued"
    strategy_plan_output = run_queued_job(client, strategy_plan_job["id"])
    assert strategy_plan_output["baseline_strategy_plan_artifact_id"]
    strategy_preview_response = client.get(
        f"/api/artifacts/{strategy_plan_output['baseline_strategy_plan_artifact_id']}/preview"
    )
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "baseline_strategy_plan.v1" in strategy_preview
    assert "adaptive_baseline_planning" in strategy_preview
    assert "reporting_plan" in strategy_preview


    strategy_brief_response = client.get(f"/api/projects/{project_id}/approach/strategy-brief")
    assert strategy_brief_response.status_code == 200, strategy_brief_response.text
    strategy_brief = strategy_brief_response.json()
    assert strategy_brief["schema_version"] == "adaptive_strategy_brief.v1"
    assert strategy_brief["summary"]["fixed_recipe_policy"] == "advisory_candidates_only"
    assert strategy_brief["codex_handoff"]["autonomy_policy"]["can_propose_new_approach_classes"] is True
    assert strategy_brief["codex_handoff"]["autonomy_policy"]["must_emit_approach_decision_trace"] is True
    assert any(lane["lane_id"] == "adaptive_baseline" for lane in strategy_brief["candidate_lanes"])

    strategy_brief_job_response = client.post(f"/api/projects/{project_id}/approach/strategy-brief")
    assert strategy_brief_job_response.status_code == 200, strategy_brief_job_response.text
    strategy_brief_job = strategy_brief_job_response.json()
    assert strategy_brief_job["status"] == "queued"
    strategy_brief_output = run_queued_job(client, strategy_brief_job["id"])
    assert strategy_brief_output["adaptive_strategy_brief_artifact_id"]
    assert strategy_brief_output["adaptive_strategy_report_artifact_id"]
    assert strategy_brief_output["visualization_artifact_id"]
    strategy_brief_preview_response = client.get(
        f"/api/artifacts/{strategy_brief_output['adaptive_strategy_brief_artifact_id']}/preview"
    )
    assert strategy_brief_preview_response.status_code == 200
    assert "adaptive_strategy_brief.v1" in strategy_brief_preview_response.json()["preview"]

    baseline_response = client.post(f"/api/projects/{project_id}/baseline/run")
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_job = baseline_response.json()
    assert baseline_job["status"] == "queued"
    assert baseline_job["job_type"] == "run_baseline"
    assert baseline_job["policy"]["execution"] == "queued_worker"
    baseline_output = run_queued_job(client, baseline_job["id"])
    assert baseline_output["experiment_run_id"]
    assert baseline_output["model_version_id"]
    baseline_metrics = baseline_output["metrics"]
    assert baseline_metrics["model_baseline_attempted"] is True
    assert baseline_metrics["baseline_type"] in {"xgboost_classifier", "logistic_regression", "majority_classifier"}
    assert baseline_metrics["primary_metric_value"] >= 0
    assert "roc_auc" in baseline_metrics
    assert len(baseline_output["artifact_ids"]) >= 7

    leaderboard_metric_response = client.post(
        f"/api/projects/{project_id}/leaderboard/metric",
        json={"metric": "ROCーAUC"},
    )
    assert leaderboard_metric_response.status_code == 200, leaderboard_metric_response.text
    assert leaderboard_metric_response.json()["metric"] == "roc_auc"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard = leaderboard_response.json()
    assert leaderboard[0]["run_id"] == baseline_output["experiment_run_id"]
    assert leaderboard[0]["display_metric_name"] == "roc_auc"
    assert leaderboard[0]["display_metric_source"] == "metric_preference"
    assert leaderboard[0]["display_metric_available"] is True
    assert abs(leaderboard[0]["display_metric_value"] - baseline_metrics["roc_auc"]) <= 1e-12


    initial_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert initial_readout_response.status_code == 200, initial_readout_response.text
    initial_readout = initial_readout_response.json()
    assert initial_readout["schema_version"] == "result_readout.v1"
    assert initial_readout["top_run"]["id"] == baseline_output["experiment_run_id"]
    assert initial_readout["evaluation_contract"]["status"] == "ready"
    assert initial_readout["next_action"]["target_tab"] == "Leaderboard"

    result_notebook_response = client.post(f"/api/projects/{project_id}/results/notebook-evidence")
    assert result_notebook_response.status_code == 200, result_notebook_response.text
    result_notebook_job = result_notebook_response.json()
    assert result_notebook_job["status"] == "queued"
    assert result_notebook_job["job_type"] == "prepare_result_notebook_evidence"
    assert result_notebook_job["policy"]["execution"] == "queued_worker"
    result_notebook_output = run_queued_job(client, result_notebook_job["id"])
    assert result_notebook_output["schema_version"] == "result_notebook_evidence.v1"
    assert result_notebook_output["top_run_id"] == baseline_output["experiment_run_id"]
    assert result_notebook_output["analysis_notebook_artifact_id"] is None
    assert result_notebook_output["source_artifact_id"] is None
    assert "preview_artifact_id" not in result_notebook_output
    assert result_notebook_output["source_registration"] == "awaiting_agent_authored_notebook"
    assert result_notebook_output["execution_status"] == "awaiting_agent_authored_notebook"
    assert result_notebook_output["notebook_authoring_brief_artifact_id"]

    notebook_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert notebook_readout_response.status_code == 200, notebook_readout_response.text
    notebook_readout = notebook_readout_response.json()
    assert notebook_readout["notebook"]["status"] in {"missing", "partial", "attention"}
    assert notebook_readout["notebook"]["action_endpoint"].endswith("/results/notebook-evidence")
    assert notebook_readout["read_order"][3]["target_tab"] == "Notebooks"
    assert notebook_readout["read_order"][3]["artifact_id"] is None


    compare_runs_response = client.post(f"/api/projects/{project_id}/experiments/compare")
    assert compare_runs_response.status_code == 200, compare_runs_response.text
    compare_runs_job = compare_runs_response.json()
    assert compare_runs_job["status"] == "queued"
    assert compare_runs_job["job_type"] == "compare_experiments"
    assert compare_runs_job["policy"]["execution"] == "queued_worker"
    compare_runs_output = run_queued_job(client, compare_runs_job["id"])
    assert compare_runs_output["artifact_ids"]

    comparison_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert comparison_readout_response.status_code == 200, comparison_readout_response.text
    comparison_readout = comparison_readout_response.json()
    assert comparison_readout["comparison"]["available"] is True
    assert comparison_readout["comparison"]["report_artifact"]["asset_type"] == "experiment_comparison_report"
    assert comparison_readout["read_order"][0]["title"] == "Read the result"

    model_response = client.get(f"/api/model-versions/{baseline_output['model_version_id']}")
    assert model_response.status_code == 200, model_response.text
    model_version = model_response.json()
    assert model_version["model_family"] == "xgboost"
    assert model_version["model_type"] == "xgboost_classifier"
    assert model_version["artifact_id"]

    model_versions_response = client.get(f"/api/projects/{project_id}/model-versions")
    assert model_versions_response.status_code == 200
    assert model_versions_response.json()[0]["id"] == model_version["id"]

    validate_response = client.post(f"/api/model-versions/{model_version['id']}/validate")
    assert validate_response.status_code == 200, validate_response.text
    validate_job = validate_response.json()
    assert validate_job["status"] == "queued"
    assert validate_job["job_type"] == "validate_model_package"
    assert validate_job["policy"]["execution"] == "queued_worker"
    validate_output = run_queued_job(client, validate_job["id"])
    assert validate_output["model_version_id"] == model_version["id"]
    assert validate_output["metrics"]["max_abs_metric_delta"] <= 1e-9
    assert len(validate_output["artifact_ids"]) == 3

    validation_history_response = client.get(f"/api/model-versions/{model_version['id']}/validations")
    assert validation_history_response.status_code == 200
    validation_history = validation_history_response.json()
    assert validation_history[0]["job"]["id"] == validate_job["id"]
    assert validation_history[0]["validation_status"] == "passed"
    assert validation_history[0]["max_abs_metric_delta"] <= 1e-9
    assert len(validation_history[0]["artifacts"]) == 3

    jobs_response = client.get(f"/api/projects/{project_id}/jobs")
    assert jobs_response.status_code == 200
    job_types = [item["job_type"] for item in jobs_response.json()]
    assert "validate_model_package" in job_types
    assert "run_baseline" in job_types
    assert "compare_evaluation_scenarios" in job_types
    assert "review_evaluation_approval" in job_types

    approval_job_response = client.post(
        "/api/jobs",
        json={
            "job_type": "run_agent_task",
            "project_id": project_id,
            "input": {"purpose": "approval gate integration test"},
            "policy": {"network": "restricted"},
            "max_attempts": 2,
        },
    )
    assert approval_job_response.status_code == 200, approval_job_response.text
    approval_job = approval_job_response.json()
    assert approval_job["status"] == "approval_required"
    assert approval_job["approval_required"] is True

    approve_job_response = client.post(f"/api/jobs/{approval_job['id']}/approve")
    assert approve_job_response.status_code == 200
    assert approve_job_response.json()["status"] == "queued"
    assert approve_job_response.json()["approved_by"] == "local-user"

    worker_response = client.post("/api/worker/run-once")
    assert worker_response.status_code == 200, worker_response.text
    assert worker_response.json() is None
    queued_approval_response = client.get(f"/api/projects/{project_id}/jobs")
    assert queued_approval_response.status_code == 200
    queued_approval = next(item for item in queued_approval_response.json() if item["id"] == approval_job["id"])
    assert queued_approval["status"] == "queued"

    dependency_a_response = client.post(
        "/api/jobs",
        json={
            "job_type": "agent_chat_turn",
            "project_id": project_id,
            "input": {"message": "dependency-a", "locale": "en-US"},
        },
    )
    assert dependency_a_response.status_code == 200
    dependency_a = dependency_a_response.json()
    dependency_b_response = client.post(
        "/api/jobs",
        json={
            "job_type": "agent_chat_turn",
            "project_id": project_id,
            "input": {"message": "dependency-b", "locale": "en-US"},
            "dependency_job_ids": [dependency_a["id"]],
            "priority": 100,
        },
    )
    assert dependency_b_response.status_code == 200
    dependency_b = dependency_b_response.json()
    first_dependency_worker_response = client.post("/api/worker/run-once")
    assert first_dependency_worker_response.status_code == 200
    assert first_dependency_worker_response.json()["id"] == dependency_a["id"]
    second_dependency_worker_response = client.post("/api/worker/run-once")
    assert second_dependency_worker_response.status_code == 200
    assert second_dependency_worker_response.json()["id"] == dependency_b["id"]

    cancel_retry_response = client.post(
        "/api/jobs",
        json={
            "job_type": "infer_assumptions",
            "project_id": project_id,
            "input": {"purpose": "cancel-retry integration test"},
            "max_attempts": 2,
        },
    )
    assert cancel_retry_response.status_code == 200
    cancel_retry_job = cancel_retry_response.json()
    cancel_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    retry_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "queued"

    seed_assets_response = client.post("/api/assets/seed-defaults")
    assert seed_assets_response.status_code == 200
    seeded_assets = seed_assets_response.json()
    assert len(seeded_assets) >= 15
    seeded_asset_names = {item["name"] for item in seeded_assets}
    assert {
        "tabular_gradient_boosting_strategy",
        "tablex_grandmaster_eda",
        "xgboost_mixed_type_baseline",
        "text_tfidf_train_fold_recipe",
        "causal_time_lag_rolling_features",
        "relational_aggregation_recipe",
        "decision_report_prompt",
    }.issubset(seeded_asset_names)
    skill_asset = next(item for item in seeded_assets if item["asset_type"] == "skill")

    research_plan_response = client.post(f"/api/projects/{project_id}/approach/research-plan")
    assert research_plan_response.status_code == 200, research_plan_response.text
    research_plan_job = research_plan_response.json()
    assert research_plan_job["status"] == "queued"
    research_plan_output = run_queued_job(client, research_plan_job["id"])
    research_plan_artifact_id = research_plan_output["artifact_id"]
    assert research_plan_output["schema_version"] == "research_plan.v1"
    assert research_plan_output["query_count"] >= 2
    assert research_plan_output["recommended_asset_count"] >= 4
    assert research_plan_output["network_default"] == "disabled_until_runner_policy_allows"

    research_plan_preview_response = client.get(f"/api/artifacts/{research_plan_artifact_id}/preview")
    assert research_plan_preview_response.status_code == 200
    research_plan_preview = research_plan_preview_response.json()["preview"]
    assert "research_plan.v1" in research_plan_preview
    research_plan_download_response = client.get(f"/api/artifacts/{research_plan_artifact_id}/download")
    assert research_plan_download_response.status_code == 200
    research_plan_download = research_plan_download_response.text
    assert "controlled_web_search" in research_plan_download
    assert "connector_credentials" in research_plan_download
    assert "xgboost_mixed_type_baseline" in research_plan_download
    assert "causal_time_lag_rolling_features" in research_plan_download

    source_pack_response = client.post(f"/api/projects/{project_id}/approach/research-source-pack")
    assert source_pack_response.status_code == 200, source_pack_response.text
    source_pack_job = source_pack_response.json()
    assert source_pack_job["status"] == "queued"
    source_pack_output = run_queued_job(client, source_pack_job["id"])
    assert source_pack_output["schema_version"] == "research_source_pack.v1"
    assert source_pack_output["research_plan_artifact_id"] == research_plan_artifact_id
    assert source_pack_output["research_source_pack_artifact_id"]
    assert source_pack_output["research_source_report_artifact_id"]
    assert source_pack_output["project_source_count"] >= 1
    assert source_pack_output["library_source_count"] >= 4
    assert source_pack_output["network_default"] == "disabled_until_runner_policy_allows"

    source_pack_preview_response = client.get(
        f"/api/artifacts/{source_pack_output['research_source_report_artifact_id']}/preview"
    )
    assert source_pack_preview_response.status_code == 200
    source_pack_preview = source_pack_preview_response.json()["preview"]
    assert "Research Source Pack" in source_pack_preview
    assert "Connector credentials" in source_pack_preview or "connector credentials" in source_pack_preview

    research_stub_response = client.post(
        f"/api/research-source-packs/{source_pack_output['research_source_pack_artifact_id']}/run-local-stub"
    )
    assert research_stub_response.status_code == 200, research_stub_response.text
    research_stub_job = research_stub_response.json()
    assert research_stub_job["status"] == "queued"
    research_stub_output = run_queued_job(client, research_stub_job["id"])
    assert research_stub_output["research_run_manifest_artifact_id"]
    assert research_stub_output["research_findings_report_id"]
    assert research_stub_output["research_findings_report_artifact_id"]
    assert research_stub_output["source_citation_manifest_artifact_id"]
    assert research_stub_output["visualization_id"]
    assert research_stub_output["evidence_id"]
    assert research_stub_output["external_network_accessed"] is False
    assert research_stub_output["connector_credentials_materialized"] is False

    research_stub_report_response = client.get(
        f"/api/artifacts/{research_stub_output['research_findings_report_artifact_id']}/preview"
    )
    assert research_stub_report_response.status_code == 200
    research_stub_report = research_stub_report_response.json()["preview"]
    assert "Controlled Research Runner Stub" in research_stub_report
    assert "External network accessed: false" in research_stub_report

    research_synthesis_response = client.post(f"/api/projects/{project_id}/approach/research-synthesis")
    assert research_synthesis_response.status_code == 200, research_synthesis_response.text
    research_synthesis_job = research_synthesis_response.json()
    assert research_synthesis_job["status"] == "queued"
    research_synthesis_output = run_queued_job(client, research_synthesis_job["id"])
    assert research_synthesis_output["schema_version"] == "research_finding_synthesis.v1"
    assert research_synthesis_output["research_finding_synthesis_artifact_id"]
    assert research_synthesis_output["research_finding_synthesis_report_id"]
    assert research_synthesis_output["research_finding_synthesis_report_artifact_id"]
    assert research_synthesis_output["visualization_id"]
    assert research_synthesis_output["evidence_id"]
    assert research_synthesis_output["external_network_accessed"] is False
    assert research_synthesis_output["has_only_stub_findings"] is True

    research_synthesis_report_response = client.get(
        f"/api/artifacts/{research_synthesis_output['research_finding_synthesis_report_artifact_id']}/preview"
    )
    assert research_synthesis_report_response.status_code == 200
    research_synthesis_report = research_synthesis_report_response.json()["preview"]
    assert "Research Finding Synthesis" in research_synthesis_report
    assert "Stub-only findings: true" in research_synthesis_report

    agent_task_plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert agent_task_plan_response.status_code == 200, agent_task_plan_response.text
    agent_task_plan_job = agent_task_plan_response.json()
    assert agent_task_plan_job["status"] == "queued"
    agent_task_plan_output = run_queued_job(client, agent_task_plan_job["id"])
    assert agent_task_plan_output["schema_version"] == "agent_task_planning.v1"
    assert agent_task_plan_output["agent_task_contract_artifact_id"]
    assert agent_task_plan_output["recommended_approach_count"] >= 2
    assert agent_task_plan_output["research_query_count"] >= 2
    assert agent_task_plan_output["recommended_asset_count"] >= 4

    agent_task_plan_preview_response = client.get(
        f"/api/artifacts/{agent_task_plan_output['agent_task_contract_artifact_id']}/preview"
    )
    assert agent_task_plan_preview_response.status_code == 200
    assert agent_task_plan_preview_response.json()["preview_available"] is True
    agent_task_plan_download_response = client.get(
        f"/api/artifacts/{agent_task_plan_output['agent_task_contract_artifact_id']}/download"
    )
    assert agent_task_plan_download_response.status_code == 200
    agent_task_contract = agent_task_plan_download_response.json()
    assert agent_task_contract["inputs"]["schema_version"] == "agent_task_planning.v1"
    assert len(agent_task_contract["inputs"]["recommended_approach_candidates"]) >= 2
    assert "reporting_requirements" in agent_task_contract["inputs"]
    assert agent_task_contract["inputs"]["research_source_pack"]["artifact_id"] == source_pack_output[
        "research_source_pack_artifact_id"
    ]
    assert (
        agent_task_contract["inputs"]["research_finding_synthesis"]["artifact_id"]
        == research_synthesis_output["research_finding_synthesis_artifact_id"]
    )
    assert agent_task_contract["inputs"]["research_finding_synthesis"]["citation_audit"][
        "external_network_accessed"
    ] is False
    assert agent_task_contract["inputs"]["research_source_policy"]["network_default"] == (
        "disabled_until_runner_policy_allows"
    )
    assert agent_task_contract["inputs"]["adaptive_strategy_brief"]["artifact_id"] == strategy_brief_output[
        "adaptive_strategy_brief_artifact_id"
    ]
    assert agent_task_contract["inputs"]["open_ended_approach_space"]["strategy_brief_available"] is True
    assert "skills/tablex-grandmaster-eda/SKILL.md" in agent_task_contract["context_files"]
    assert any(
        item["role"] == "adaptive_strategy_brief"
        and item["artifact_id"] == strategy_brief_output["adaptive_strategy_brief_artifact_id"]
        for item in agent_task_contract["inputs"]["available_context_artifacts"]
    )
    assert any(
        item["name"] == "xgboost_mixed_type_baseline"
        for item in agent_task_contract["inputs"]["library_recommendations"]
    )

    agent_task_job_artifacts_response = client.get(f"/api/jobs/{agent_task_plan_job['id']}/artifacts")
    assert agent_task_job_artifacts_response.status_code == 200
    agent_task_job_artifacts = agent_task_job_artifacts_response.json()
    assert agent_task_job_artifacts["summary"]["task_id"] == agent_task_plan_output["task_id"]
    assert agent_task_job_artifacts["summary"]["recommended_approach_count"] >= 2
    assert agent_task_job_artifacts["missing_artifact_ids"] == []
    assert agent_task_job_artifacts["artifacts"][0]["asset_type"] == "agent_task_contract"

    planned_workspace_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_output['agent_task_contract_artifact_id']}/prepare-workspace"
    )
    assert planned_workspace_response.status_code == 200, planned_workspace_response.text
    planned_workspace_job = planned_workspace_response.json()
    assert planned_workspace_job["status"] == "queued"
    planned_workspace_output = run_queued_job(client, planned_workspace_job["id"])
    assert planned_workspace_output["schema_version"] == "agent_workspace_manifest.v1"
    assert planned_workspace_output["agent_workspace_manifest_artifact_id"]
    assert planned_workspace_output["agent_task_contract_artifact_id"] == agent_task_plan_output[
        "agent_task_contract_artifact_id"
    ]
    assert planned_workspace_output["materialized_context_count"] >= 4
    assert planned_workspace_output["materialized_library_asset_count"] >= 4

    planned_workspace_download_response = client.get(
        f"/api/artifacts/{planned_workspace_output['agent_workspace_manifest_artifact_id']}/download"
    )
    assert planned_workspace_download_response.status_code == 200
    planned_workspace_manifest = planned_workspace_download_response.json()
    assert planned_workspace_manifest["source_contract_artifact_id"] == agent_task_plan_output[
        "agent_task_contract_artifact_id"
    ]
    assert ".harness/task_contract.json" in planned_workspace_manifest["files"]
    assert ".harness/agent_result.schema.json" in planned_workspace_manifest["files"]
    assert ".harness/execution_policy.json" in planned_workspace_manifest["files"]
    assert "README.md" in planned_workspace_manifest["files"]
    assert any(
        item["context_path"].startswith(".harness/context/library_assets/")
        for item in planned_workspace_manifest["materialized_sources"]
    )
    assert any(
        item["artifact_id"] == strategy_brief_output["adaptive_strategy_brief_artifact_id"]
        and item["source_kind"] == "context_artifact"
        for item in planned_workspace_manifest["materialized_sources"]
    )

    planned_workspace_job_artifacts_response = client.get(f"/api/jobs/{planned_workspace_job['id']}/artifacts")
    assert planned_workspace_job_artifacts_response.status_code == 200
    planned_workspace_job_artifacts = planned_workspace_job_artifacts_response.json()
    assert planned_workspace_job_artifacts["summary"]["agent_workspace_manifest_artifact_id"]
    assert planned_workspace_job_artifacts["summary"]["materialized_library_asset_count"] >= 4
    assert any(
        item["asset_type"] == "agent_workspace_manifest"
        for item in planned_workspace_job_artifacts["artifacts"]
    )

    readiness_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_output['agent_task_contract_artifact_id']}/readiness-review"
    )
    assert readiness_response.status_code == 200, readiness_response.text
    readiness_job = readiness_response.json()
    assert readiness_job["status"] == "queued"
    readiness_output = run_queued_job(client, readiness_job["id"])
    assert readiness_output["schema_version"] == "agent_task_readiness_review.v1"
    assert readiness_output["agent_task_readiness_review_artifact_id"]
    assert readiness_output["agent_task_readiness_report_artifact_id"]
    assert readiness_output["visualization_artifact_id"]
    assert readiness_output["readiness_status"] in {"ready", "ready_with_warnings", "blocked"}
    assert readiness_output["blocker_count"] == 0
    assert readiness_output["pass_count"] > 0
    assert isinstance(readiness_output["next_actions"], list)

    readiness_download_response = client.get(
        f"/api/artifacts/{readiness_output['agent_task_readiness_review_artifact_id']}/download"
    )
    assert readiness_download_response.status_code == 200
    readiness_payload = readiness_download_response.json()
    assert readiness_payload["schema_version"] == "agent_task_readiness_review.v1"
    assert readiness_payload["pass_count"] == readiness_output["pass_count"]
    assert readiness_payload["workspace_artifact_id"] == planned_workspace_output["agent_workspace_manifest_artifact_id"]
    artifacts_after_readiness = client.get(f"/api/projects/{project_id}/artifacts").json()
    readiness_artifact = next(
        item
        for item in artifacts_after_readiness
        if item["id"] == readiness_output["agent_task_readiness_review_artifact_id"]
    )
    assert readiness_artifact["metadata"]["pass_count"] == readiness_output["pass_count"]
    assert "first_next_action" in readiness_artifact["metadata"]
    assert any(item["check_id"] == "workspace_manifest" for item in readiness_payload["checks"])
    strategy_readiness_check = next(
        item for item in readiness_payload["checks"] if item["check_id"] == "adaptive_strategy_context"
    )
    assert strategy_readiness_check["status"] == "pass"

    readiness_report_preview_response = client.get(
        f"/api/artifacts/{readiness_output['agent_task_readiness_report_artifact_id']}/preview"
    )
    assert readiness_report_preview_response.status_code == 200
    assert "Agent Task Readiness Review" in readiness_report_preview_response.json()["preview"]

    planned_stub_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_output['agent_task_contract_artifact_id']}/run-local-stub"
    )
    assert planned_stub_response.status_code == 200, planned_stub_response.text
    planned_stub_job = planned_stub_response.json()
    assert planned_stub_job["status"] == "queued"
    planned_stub_output = run_queued_job(client, planned_stub_job["id"])
    assert planned_stub_output["agent_status"] == "succeeded"
    assert planned_stub_output["readiness_status"] in {"ready", "ready_with_warnings"}
    assert planned_stub_output["auto_prepared_workspace"] is False
    assert len(planned_stub_output["ingested_artifact_ids"]) == 9
    assert planned_stub_output["report_id"]
    assert planned_stub_output["evidence_id"]
    assert planned_stub_output["experiment_run_id"]
    assert planned_stub_output["agent_metrics_artifact_id"]
    assert planned_stub_output["agent_feature_recipe_artifact_id"]
    assert planned_stub_output["approach_decision_trace_artifact_id"]
    assert planned_stub_output["source_citation_manifest_artifact_id"]
    assert planned_stub_output["citation_audit_report_id"]
    assert planned_stub_output["citation_audit_report_artifact_id"]
    assert planned_stub_output["citation_evidence_id"]
    assert planned_stub_output["citation_visualization_id"]
    assert planned_stub_output["citation_visualization_artifact_id"]
    assert len(planned_stub_output["visualization_ids"]) == 1
    assert planned_stub_output["requires_human_review"] is True

    planned_trace_download_response = client.get(
        f"/api/artifacts/{planned_stub_output['approach_decision_trace_artifact_id']}/download"
    )
    assert planned_trace_download_response.status_code == 200
    planned_trace = planned_trace_download_response.json()
    assert planned_trace["context_used"]["adaptive_strategy_brief_artifact_id"] == strategy_brief_output[
        "adaptive_strategy_brief_artifact_id"
    ]
    assert planned_trace["adaptive_strategy_guidance"]["fixed_recipe_policy"] == "advisory_candidates_only"
    assert planned_trace["adaptive_strategy_guidance"]["must_emit_approach_decision_trace"] is True

    planned_citation_preview_response = client.get(
        f"/api/artifacts/{planned_stub_output['citation_audit_report_artifact_id']}/preview"
    )
    assert planned_citation_preview_response.status_code == 200
    planned_citation_preview = planned_citation_preview_response.json()["preview"]
    assert "Citation Audit Report" in planned_citation_preview
    assert "External network accessed: false" in planned_citation_preview

    planned_stub_job_artifacts_response = client.get(f"/api/jobs/{planned_stub_job['id']}/artifacts")
    assert planned_stub_job_artifacts_response.status_code == 200
    planned_stub_job_artifacts = planned_stub_job_artifacts_response.json()
    planned_stub_asset_types = {item["asset_type"] for item in planned_stub_job_artifacts["artifacts"]}
    assert {
        "agent_task_report",
        "agent_result",
        "visualization_spec",
        "feature_recipe",
        "experiment_metrics",
        "approach_decision_trace",
        "source_citation_manifest",
        "citation_audit_report",
    }.issubset(planned_stub_asset_types)

    planned_stub_runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert planned_stub_runs_response.status_code == 200
    assert any(
        run["id"] == planned_stub_output["experiment_run_id"] and run["status"] == "not_executed"
        for run in planned_stub_runs_response.json()
    )

    planned_agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert planned_agent_results_response.status_code == 200
    planned_agent_results = planned_agent_results_response.json()
    planned_result = next(item for item in planned_agent_results if item["job_id"] == planned_stub_job["id"])
    assert planned_result["source"]["type"] == "agent_task_contract"
    assert planned_result["artifacts"]["source_citation_manifest"]["id"] == planned_stub_output[
        "source_citation_manifest_artifact_id"
    ]
    assert planned_result["reports"]["citation_audit_report"]["id"] == planned_stub_output[
        "citation_audit_report_id"
    ]
    assert planned_result["artifacts"]["approach_decision_trace"]["id"] == planned_stub_output[
        "approach_decision_trace_artifact_id"
    ]
    assert planned_result["approach_decision_trace"]["policy"] == "open_ended_with_harness_constraints"
    assert planned_result["citation_audit"]["citation_count"] >= 1
    assert planned_result["citation_audit"]["external_network_accessed"] is False

    research_response = client.post(
        f"/api/projects/{project_id}/approach/research-briefs",
        json={"question": "What flexible approaches should be considered?"},
    )
    assert research_response.status_code == 200, research_response.text
    research_job = research_response.json()
    assert research_job["status"] == "queued"
    research_output = run_queued_job(client, research_job["id"])
    assert research_output["research_brief_id"]

    briefs_response = client.get(f"/api/projects/{project_id}/approach/research-briefs")
    assert briefs_response.status_code == 200
    brief = briefs_response.json()[0]
    assert "controlled web" in brief["summary_md"].lower() or "web" in brief["summary_md"].lower()
    assert len(brief["recommended_approaches"]) >= 2
    assert any(source["source_type"] == "research_plan" for source in brief["sources"])
    assert any(source["source_type"] == "research_finding_synthesis" for source in brief["sources"])
    assert not any(str(source["source_type"]).endswith("_placeholder") for source in brief["sources"])

    ideas_response = client.post(f"/api/projects/{project_id}/approach/ideas/generate")
    assert ideas_response.status_code == 200, ideas_response.text
    ideas_job = ideas_response.json()
    assert ideas_job["status"] == "queued"
    ideas_output = run_queued_job(client, ideas_job["id"])
    assert len(ideas_output["idea_ids"]) >= 2

    ideas_list_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert ideas_list_response.status_code == 200
    idea = ideas_list_response.json()[0]
    assert idea["status"] == "proposed"
    contract_inputs = idea["agent_task_contract"]["inputs"]
    assert contract_inputs["must_respect_split_manifest"] is True
    assert contract_inputs["research_plan_artifact_id"] == research_plan_artifact_id
    assert (
        contract_inputs["research_finding_synthesis"]["artifact_id"]
        == research_synthesis_output["research_finding_synthesis_artifact_id"]
    )
    assert len(contract_inputs["recommended_asset_ids"]) >= 4
    assert len(contract_inputs["recommended_asset_version_ids"]) >= 4
    assert contract_inputs["research_source_policy"]["network_default"] == "disabled_until_runner_policy_allows"
    assert any("secrets" in item for item in idea["agent_task_contract"]["forbidden_actions"])

    assets_response = client.get("/api/assets")
    assert assets_response.status_code == 200
    assert any(item["name"] == skill_asset["name"] for item in assets_response.json())

    versions_response = client.get(f"/api/assets/{skill_asset['id']}/versions")
    assert versions_response.status_code == 200
    skill_version = versions_response.json()[0]
    assert skill_version["asset_id"] == skill_asset["id"]

    custom_skill_response = client.post(
        "/api/assets",
        json={
            "asset_type": "skill",
            "name": "custom_credit_review_skill",
            "description": "Project-specific credit review guidance.",
            "content": {
                "schema_version": "tablex_skill.v1",
                "instructions": ["Review credit-risk evidence without forcing a fixed recipe."],
            },
            "tags": ["credit", "eda"],
            "semantic_tags": ["skill", "credit_risk"],
        },
    )
    assert custom_skill_response.status_code == 200, custom_skill_response.text
    custom_skill = custom_skill_response.json()
    assert "credit_risk" in custom_skill["semantic_tags"]
    custom_skill_versions_response = client.get(f"/api/assets/{custom_skill['id']}/versions")
    assert custom_skill_versions_response.status_code == 200

    project_ref_response = client.post(
        f"/api/projects/{project_id}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_research",
        },
    )
    assert project_ref_response.status_code == 200, project_ref_response.text
    assert project_ref_response.json()["asset"]["asset_type"] == "skill"

    idea_ref_response = client.post(
        f"/api/ideas/{idea['id']}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_agent_task",
        },
    )
    assert idea_ref_response.status_code == 200, idea_ref_response.text
    assert idea_ref_response.json()["source_type"] == "idea"

    project_refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert project_refs_response.status_code == 200
    assert project_refs_response.json()[0]["asset"]["name"] == skill_asset["name"]

    skill_preview_response = client.get(f"/api/artifacts/{skill_version['artifact_id']}/preview")
    assert skill_preview_response.status_code == 200
    assert skill_preview_response.json()["preview_available"] is True

    context_response = client.post(f"/api/ideas/{idea['id']}/prepare-agent-context")
    assert context_response.status_code == 200, context_response.text
    context_job = context_response.json()
    assert context_job["status"] == "queued"
    context_output = run_queued_job(client, context_job["id"])
    assert context_output["schema_version"] == "agent_context_pack.v1"
    assert context_output["artifact_id"]
    assert context_output["asset_recommendation_count"] >= 4
    assert context_output["materialized_library_asset_count"] >= 4

    context_packs_response = client.get(f"/api/ideas/{idea['id']}/context-packs")
    assert context_packs_response.status_code == 200
    context_artifact = context_packs_response.json()[0]
    assert context_artifact["id"] == context_output["artifact_id"]

    context_preview_response = client.get(f"/api/artifacts/{context_artifact['id']}/preview")
    assert context_preview_response.status_code == 200
    context_download_response = client.get(f"/api/artifacts/{context_artifact['id']}/download")
    assert context_download_response.status_code == 200
    context_payload = context_download_response.json()
    assert context_payload["schema_version"] == "agent_context_pack.v1"
    assert "controlled_web_search" in context_payload["research_policy"]["allowed_modes"]
    assert context_payload["safety_controls"]["connector_credentials"] == "never passed to the agent"
    assert context_payload["evaluation_context"]["split_manifest_id"]
    assert context_payload["quality_gate_context"]["status"] == "available"
    assert context_payload["quality_gate_context"]["quality_check_scope"] in {"full", "sample"}
    assert context_payload["research_plan_context"]["artifact_id"] == research_plan_artifact_id
    assert (
        context_payload["research_synthesis_context"]["artifact_id"]
        == research_synthesis_output["research_finding_synthesis_artifact_id"]
    )
    assert context_payload["research_synthesis_context"]["citation_audit"]["external_network_accessed"] is False
    assert len(context_payload["asset_recommendations"]) >= 4
    assert len(context_payload["materialized_library_assets"]) >= 4
    assert any(
        item["context_path"].startswith(".harness/context/library_assets/")
        for item in context_payload["materialized_library_assets"]
    )
    assert any(item["name"] == "xgboost_mixed_type_baseline" for item in context_payload["asset_recommendations"])

    experiment_plan_response = client.post(f"/api/ideas/{idea['id']}/experiment-plan")
    assert experiment_plan_response.status_code == 200, experiment_plan_response.text
    experiment_plan_job = experiment_plan_response.json()
    assert experiment_plan_job["status"] == "queued"
    experiment_plan_output = run_queued_job(client, experiment_plan_job["id"])
    assert experiment_plan_output["plan_id"]
    assert experiment_plan_output["artifact_id"]
    assert experiment_plan_output["readiness"]["status"] == "ready_for_runner"

    experiment_plans_response = client.get(f"/api/ideas/{idea['id']}/experiment-plans")
    assert experiment_plans_response.status_code == 200
    experiment_plan_artifact = experiment_plans_response.json()[0]
    assert experiment_plan_artifact["id"] == experiment_plan_output["artifact_id"]

    experiment_plan_preview_response = client.get(f"/api/artifacts/{experiment_plan_artifact['id']}/preview")
    assert experiment_plan_preview_response.status_code == 200
    assert "experiment_plan.v1" in experiment_plan_preview_response.json()["preview"]
    assert "source_policy" in experiment_plan_preview_response.json()["preview"]

    agent_task_response = client.post(f"/api/ideas/{idea['id']}/run-agent-task")
    assert agent_task_response.status_code == 200, agent_task_response.text
    agent_task_job = agent_task_response.json()
    assert agent_task_job["status"] == "queued"
    agent_task_output = run_queued_job(client, agent_task_job["id"])
    assert agent_task_output["idea_id"] == idea["id"]
    assert agent_task_output["agent_status"] == "succeeded"
    assert agent_task_output["requires_human_review"] is True
    assert len(agent_task_output["artifact_ids"]) >= 4
    assert agent_task_output["workspace_artifact_id"]
    assert len(agent_task_output["ingested_artifact_ids"]) == 9
    assert agent_task_output["report_id"]
    assert agent_task_output["evidence_id"]
    assert agent_task_output["experiment_run_id"]
    assert agent_task_output["agent_metrics_artifact_id"]
    assert agent_task_output["agent_feature_recipe_artifact_id"]
    assert agent_task_output["approach_decision_trace_artifact_id"]
    assert agent_task_output["source_citation_manifest_artifact_id"]
    assert agent_task_output["citation_audit_report_id"]
    assert agent_task_output["citation_audit_report_artifact_id"]
    assert agent_task_output["citation_evidence_id"]
    assert agent_task_output["citation_visualization_id"]
    assert len(agent_task_output["visualization_ids"]) == 1

    citation_manifest_response = client.get(
        f"/api/artifacts/{agent_task_output['source_citation_manifest_artifact_id']}/download"
    )
    assert citation_manifest_response.status_code == 200
    citation_manifest = citation_manifest_response.json()
    assert citation_manifest["schema_version"] == "source_citation_manifest.v1"
    assert citation_manifest["connector_credentials_materialized"] is False

    idea_decision_trace_response = client.get(
        f"/api/artifacts/{agent_task_output['approach_decision_trace_artifact_id']}/download"
    )
    assert idea_decision_trace_response.status_code == 200
    idea_decision_trace = idea_decision_trace_response.json()
    assert idea_decision_trace["schema_version"] == "approach_decision_trace.v1"
    assert any(
        item["approach"] == "fixed_predefined_recipe_execution"
        for item in idea_decision_trace["rejected_or_deferred_approaches"]
    )

    citation_report_response = client.get(
        f"/api/reports/{agent_task_output['citation_audit_report_id']}/preview"
    )
    assert citation_report_response.status_code == 200
    assert "Citation Audit Report" in citation_report_response.json()["preview"]

    agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert agent_results_response.status_code == 200
    agent_results = agent_results_response.json()
    assert len(agent_results) >= 2
    idea_result = next(item for item in agent_results if item["job_id"] == agent_task_job["id"])
    assert idea_result["source"] == {"type": "idea", "id": idea["id"]}
    assert idea_result["experiment_run"]["id"] == agent_task_output["experiment_run_id"]
    assert idea_result["artifacts"]["agent_task_report"]["asset_type"] == "agent_task_report"
    assert idea_result["artifacts"]["citation_audit_report"]["asset_type"] == "citation_audit_report"
    assert idea_result["artifacts"]["approach_decision_trace"]["id"] == agent_task_output[
        "approach_decision_trace_artifact_id"
    ]
    assert idea_result["approach_decision_trace"]["deferred_or_rejected_count"] >= 1
    assert idea_result["evidence"]["citation_audit"]["id"] == agent_task_output["citation_evidence_id"]

    updated_ideas_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert updated_ideas_response.status_code == 200
    assert updated_ideas_response.json()[0]["status"] == "agent_stub_completed"

    agent_task_runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert agent_task_runs_response.status_code == 200
    assert any(
        run["id"] == agent_task_output["experiment_run_id"] and run["runner_type"] == "local_stub"
        for run in agent_task_runs_response.json()
    )

    visualization_response = client.post(f"/api/projects/{project_id}/visualizations/generate")
    assert visualization_response.status_code == 200, visualization_response.text
    visualization_job = visualization_response.json()
    assert visualization_job["status"] == "queued"
    assert visualization_job["job_type"] == "create_visualization_spec"
    assert visualization_job["policy"]["execution"] == "queued_worker"
    visualization_output = run_queued_job(client, visualization_job["id"])
    assert len(visualization_output["visualization_ids"]) >= 4

    visualizations_response = client.get(f"/api/projects/{project_id}/visualizations")
    assert visualizations_response.status_code == 200
    visualizations = visualizations_response.json()
    chart_types = {item["chart_type"] for item in visualizations}
    assert {"metric_cards", "category_bars", "stage_status", "leaderboard_bar"}.issubset(chart_types)
    leaderboard_visualization = next(item for item in visualizations if item["chart_type"] == "leaderboard_bar")
    assert leaderboard_visualization["spec"]["schema_version"] == "visualization_spec.v1"

    insights_response = client.post(f"/api/projects/{project_id}/insights/generate")
    assert insights_response.status_code == 200, insights_response.text
    insights_job = insights_response.json()
    assert insights_job["status"] == "queued"
    assert insights_job["job_type"] == "generate_insights"
    assert insights_job["policy"]["execution"] == "queued_worker"
    insights_output = run_queued_job(client, insights_job["id"])
    assert len(insights_output["insight_ids"]) >= 5
    assert len(insights_output["evidence_ids"]) >= 5

    insights_list_response = client.get(f"/api/projects/{project_id}/insights")
    assert insights_list_response.status_code == 200
    insight = insights_list_response.json()[0]
    assert insight["artifact_id"] == insights_output["artifact_id"]
    assert insight["evidence_ids"]

    insight_preview_response = client.get(f"/api/artifacts/{insight['artifact_id']}/preview")
    assert insight_preview_response.status_code == 200
    assert "insight_set.v1" in insight_preview_response.json()["preview"]

    report_response = client.post(
        f"/api/projects/{project_id}/reports/draft",
        json={"title": "Integration report", "report_type": "project_summary"},
    )
    assert report_response.status_code == 200, report_response.text
    report_job = report_response.json()
    assert report_job["status"] == "queued"
    report_output = run_queued_job(client, report_job["id"])

    reports_response = client.get(f"/api/projects/{project_id}/reports")
    assert reports_response.status_code == 200
    report = reports_response.json()[0]
    assert report["artifact_id"] == report_output["artifact_id"]

    report_preview_response = client.get(f"/api/artifacts/{report['artifact_id']}/preview")
    assert report_preview_response.status_code == 200
    assert "Project Report" in report_preview_response.json()["preview"]
    assert "## Insights" in report_preview_response.json()["preview"]

    report_preview_by_id_response = client.get(f"/api/reports/{report['id']}/preview")
    assert report_preview_by_id_response.status_code == 200
    assert "## Visualizations" in report_preview_by_id_response.json()["preview"]

    artifact_translation_response = client.post(
        f"/api/artifacts/{report['artifact_id']}/translate",
        json={"target_locale": "Japanese", "source_locale": "en-US"},
    )
    assert artifact_translation_response.status_code == 200, artifact_translation_response.text
    artifact_translation_job = artifact_translation_response.json()
    assert artifact_translation_job["status"] == "queued"
    assert artifact_translation_job["policy"]["execution"] == "queued_worker"
    artifact_translation_output = run_queued_job(client, artifact_translation_job["id"])
    artifact_translation = artifact_translation_output["translation"]
    assert artifact_translation["source_type"] == "artifact"
    assert artifact_translation["target_locale"] == "Japanese"
    assert artifact_translation["artifact"]["asset_type"] == "translated_artifact_preview"
    assert artifact_translation_output["codex_translation_contract_artifact_id"]
    assert "Codex" in artifact_translation["preview"]["preview"]

    report_translation_response = client.post(
        f"/api/reports/{report['id']}/translate",
        json={"target_locale": "ja-JP", "source_locale": "en-US"},
    )
    assert report_translation_response.status_code == 200, report_translation_response.text
    report_translation_job = report_translation_response.json()
    assert report_translation_job["status"] == "queued"
    assert report_translation_job["policy"]["execution"] == "queued_worker"
    report_translation_output = run_queued_job(client, report_translation_job["id"])
    report_translation = report_translation_output["translation"]
    assert report_translation["source_type"] == "report"
    assert report_translation["report"]["status"] == "draft_translation"
    assert report_translation["artifact"]["asset_type"] == "translated_report"
    assert report_translation_output["codex_translation_contract_artifact_id"]

    decision_response = client.post(f"/api/projects/{project_id}/decision-dashboard/generate")
    assert decision_response.status_code == 200, decision_response.text
    decision_job = decision_response.json()
    assert decision_job["status"] == "queued"
    assert decision_job["job_type"] == "generate_decision_dashboard"
    assert decision_job["policy"]["execution"] == "queued_worker"
    decision_output = run_queued_job(client, decision_job["id"])
    assert decision_output["schema_version"] == "decision_dashboard.v1"
    assert decision_output["decision_dashboard_artifact_id"]
    assert decision_output["decision_report_artifact_id"]
    assert decision_output["report_id"]
    assert len(decision_output["visualization_ids"]) == 3

    decision_dashboard_preview_response = client.get(
        f"/api/artifacts/{decision_output['decision_dashboard_artifact_id']}/preview"
    )
    assert decision_dashboard_preview_response.status_code == 200
    assert decision_dashboard_preview_response.json()["preview_available"] is True
    decision_dashboard_download_response = client.get(
        f"/api/artifacts/{decision_output['decision_dashboard_artifact_id']}/download"
    )
    assert decision_dashboard_download_response.status_code == 200
    decision_dashboard_payload = decision_dashboard_download_response.json()
    assert decision_dashboard_payload["schema_version"] == "decision_dashboard.v1"
    assert "readiness_stages" in decision_dashboard_payload

    decision_report_preview_response = client.get(f"/api/reports/{decision_output['report_id']}/preview")
    assert decision_report_preview_response.status_code == 200
    decision_report_preview = decision_report_preview_response.json()["preview"]
    assert "Decision Report" in decision_report_preview
    assert "## Readiness Stages" in decision_report_preview

    current_decision_report_empty_response = client.get(f"/api/projects/{project_id}/decision-report/current")
    assert current_decision_report_empty_response.status_code == 200
    assert current_decision_report_empty_response.json()["available"] is False

    decision_report_v1_response = client.post(f"/api/projects/{project_id}/decision-report/generate")
    assert decision_report_v1_response.status_code == 200, decision_report_v1_response.text
    decision_report_v1_job = decision_report_v1_response.json()
    assert decision_report_v1_job["status"] == "queued"
    assert decision_report_v1_job["job_type"] == "generate_decision_report"
    assert decision_report_v1_job["policy"]["execution"] == "queued_worker"
    decision_report_v1_output = run_queued_job(client, decision_report_v1_job["id"])
    assert decision_report_v1_output["schema_version"] == "decision_report_bundle.v1"
    assert decision_report_v1_output["decision_report_bundle_artifact_id"]
    assert decision_report_v1_output["decision_report_artifact_id"]
    assert decision_report_v1_output["decision_report_evidence_id"]
    assert decision_report_v1_output["source_asset_count"] > 0

    decision_report_bundle_response = client.get(
        f"/api/artifacts/{decision_report_v1_output['decision_report_bundle_artifact_id']}/download"
    )
    assert decision_report_bundle_response.status_code == 200
    decision_report_bundle = decision_report_bundle_response.json()
    assert decision_report_bundle["schema_version"] == "decision_report_bundle.v1"
    assert decision_report_bundle["safety"]["external_dashboards_required"] is False
    assert decision_report_bundle["safety"]["secret_values_included"] is False
    assert "data_review" in decision_report_bundle["sections"]
    assert "evaluation" in decision_report_bundle["sections"]
    assert "notebooks" in decision_report_bundle["sections"]
    assert "experiments" in decision_report_bundle["sections"]
    assert "runner_results" in decision_report_bundle["sections"]
    assert "citations" in decision_report_bundle["sections"]
    assert any(row["area"] == "Data Review" for row in decision_report_bundle["evidence_map"])
    assert decision_report_bundle["next_actions"]

    decision_report_v1_preview_response = client.get(
        f"/api/reports/{decision_report_v1_output['report_id']}/preview"
    )
    assert decision_report_v1_preview_response.status_code == 200
    decision_report_v1_preview = decision_report_v1_preview_response.json()["preview"]
    assert "## Evidence Map" in decision_report_v1_preview
    assert "## Data Review" in decision_report_v1_preview
    assert "## Evaluation Design" in decision_report_v1_preview
    assert "## Experiments And Model Evidence" in decision_report_v1_preview
    assert "## Notebook Evidence" in decision_report_v1_preview
    assert "## Runner Results And Citations" in decision_report_v1_preview
    assert "## Next Actions" in decision_report_v1_preview

    current_decision_report_response = client.get(f"/api/projects/{project_id}/decision-report/current")
    assert current_decision_report_response.status_code == 200
    current_decision_report = current_decision_report_response.json()
    assert current_decision_report["available"] is True
    assert current_decision_report["report"]["id"] == decision_report_v1_output["report_id"]
    assert current_decision_report["bundle"]["schema_version"] == "decision_report_bundle.v1"

    post_run_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert post_run_readout_response.status_code == 200, post_run_readout_response.text
    post_run_readout = post_run_readout_response.json()
    assert post_run_readout["decision_report"]["available"] is True
    assert post_run_readout["next_action"]["target_anchor"] == "result-readout"
    assert post_run_readout["safety"]["leaderboard_is_decision"] is False

    runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert runs_response.status_code == 200
    baseline_run = next(run for run in runs_response.json() if run["model_version_id"] == model_version["id"])
    assert baseline_run["runner_type"] == "local_baseline"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()[0]["primary_metric_value"] is not None

    diagnostics_response = client.post(f"/api/runs/{baseline_run['id']}/diagnostics")
    assert diagnostics_response.status_code == 200, diagnostics_response.text
    diagnostics_job = diagnostics_response.json()
    assert diagnostics_job["status"] == "queued"
    assert diagnostics_job["job_type"] == "analyze_evaluation_diagnostics"
    assert diagnostics_job["policy"]["execution"] == "queued_worker"
    diagnostics_output = run_queued_job(client, diagnostics_job["id"])
    assert len(diagnostics_output["artifact_ids"]) == 3
    diagnostics_payload = diagnostics_output["diagnostics"]
    assert diagnostics_payload["schema_version"] == "evaluation_diagnostics.v1"
    assert diagnostics_payload["task_kind"] == "classification"
    assert diagnostics_payload["summary"]["count"] > 0
    assert diagnostics_output["insight_id"]
    assert diagnostics_output["evidence_id"]

    model_evidence_response = client.post(f"/api/runs/{baseline_run['id']}/model-diagnostics-artifacts")
    assert model_evidence_response.status_code == 200, model_evidence_response.text
    model_evidence_job = model_evidence_response.json()
    assert model_evidence_job["status"] == "queued"
    assert model_evidence_job["job_type"] == "materialize_model_diagnostics_artifacts"
    assert model_evidence_job["policy"]["execution"] == "queued_worker"
    model_evidence_output = run_queued_job(client, model_evidence_job["id"])
    assert model_evidence_output["feature_importance_artifact_id"]
    assert model_evidence_output["permutation_importance_artifact_id"]
    assert model_evidence_output["partial_dependence_artifact_id"]
    assert model_evidence_output["shap_summary_artifact_id"]
    assert model_evidence_output["model_diagnostics_artifact_pack_id"]
    assert model_evidence_output["model_diagnostics_report_artifact_id"]
    assert model_evidence_output["availability"]["native_feature_importance"] == "ready"
    assert model_evidence_output["availability"]["partial_dependence"] == "ready"
    assert model_evidence_output["availability"]["shap"] in {"ready", "blocked"}
    assert model_evidence_output["availability"]["prediction_review"] == "ready"
    leaderboard_with_model_diagnostics_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_with_model_diagnostics_response.status_code == 200
    leaderboard_with_model_diagnostics = leaderboard_with_model_diagnostics_response.json()
    diagnostics_row = next(row for row in leaderboard_with_model_diagnostics if row["run_id"] == baseline_run["id"])
    assert diagnostics_row["model_diagnostics"]["status"] == "ready"
    assert diagnostics_row["model_diagnostics"]["standard_checks"]["permutation_importance"]["artifact_id"] == (
        model_evidence_output["permutation_importance_artifact_id"]
    )
    assert diagnostics_row["model_diagnostics"]["standard_checks"]["native_feature_importance"]["artifact_id"] == (
        model_evidence_output["feature_importance_artifact_id"]
    )
    assert diagnostics_row["model_diagnostics"]["standard_checks"]["partial_dependence"]["artifact_id"] == (
        model_evidence_output["partial_dependence_artifact_id"]
    )
    assert diagnostics_row["model_diagnostics"]["standard_checks"]["shap"]["artifact_id"] == (
        model_evidence_output["shap_summary_artifact_id"]
    )
    model_evidence_report_response = client.get(
        f"/api/artifacts/{model_evidence_output['model_diagnostics_report_artifact_id']}/preview"
    )
    assert model_evidence_report_response.status_code == 200
    model_evidence_report = model_evidence_report_response.json()["preview"]
    assert "Model Diagnostics Artifact Pack" in model_evidence_report
    assert "Top Native Features" in model_evidence_report

    model_notebook_response = client.post(f"/api/runs/{baseline_run['id']}/analysis-notebook")
    assert model_notebook_response.status_code == 200, model_notebook_response.text
    model_notebook_job = model_notebook_response.json()
    assert model_notebook_job["status"] == "queued"
    assert model_notebook_job["job_type"] == "prepare_model_diagnostics_notebook_authoring"
    model_notebook_output = run_queued_job(client, model_notebook_job["id"])
    assert model_notebook_output["notebook_kind"] == "model_diagnostics"
    assert model_notebook_output["run_id"] == baseline_run["id"]
    assert model_notebook_output["analysis_notebook_artifact_id"] is None
    assert model_notebook_output["notebook_report_id"] is None
    assert model_notebook_output["visualization_id"] is None
    assert model_notebook_output["visualization_artifact_id"] is None
    assert model_notebook_output["execution_status"] == "awaiting_agent_authored_notebook"
    assert model_notebook_output["notebook_authoring_brief_artifact_id"]

    notebook_index_response = client.get(f"/api/projects/{project_id}/analysis-notebooks")
    assert notebook_index_response.status_code == 200, notebook_index_response.text
    notebook_index = notebook_index_response.json()
    assert notebook_index["schema_version"] == "analysis_notebook_index.v1"
    assert notebook_index["counts"]["total"] == 0
    assert notebook_index["recommended_notebook"] is None

    guidance_after_notebook_response = client.get(f"/api/projects/{project_id}/guidance")
    assert guidance_after_notebook_response.status_code == 200
    guidance_after_notebook = guidance_after_notebook_response.json()
    guidance_journey = {stage["id"]: stage for stage in guidance_after_notebook["journey_stages"]}
    assert guidance_journey["notebooks"]["status"] in {"todo", "next", "doing", "current"}
    assert guidance_after_notebook["supporting_counts"]["analysis_notebooks"] == 0

    run_report_response = client.post(f"/api/runs/{baseline_run['id']}/report")
    assert run_report_response.status_code == 200, run_report_response.text
    run_report_job = run_report_response.json()
    assert run_report_job["status"] == "queued"
    assert run_report_job["job_type"] == "draft_run_report"
    assert run_report_job["policy"]["execution"] == "queued_worker"
    run_report_output = run_queued_job(client, run_report_job["id"])
    assert run_report_output["report_id"]
    assert run_report_output["artifact_id"]

    comparison_response = client.post(f"/api/projects/{project_id}/experiments/compare")
    assert comparison_response.status_code == 200, comparison_response.text
    comparison_job = comparison_response.json()
    assert comparison_job["status"] == "queued"
    assert comparison_job["job_type"] == "compare_experiments"
    assert comparison_job["policy"]["execution"] == "queued_worker"
    comparison_output = run_queued_job(client, comparison_job["id"])
    assert comparison_output["comparison"]["schema_version"] == "experiment_comparison.v1"
    assert comparison_output["comparison"]["decision"]["best_run_id"] == baseline_run["id"]
    assert len(comparison_output["artifact_ids"]) >= 2
    assert comparison_output["report_id"]
    assert comparison_output["insight_id"]

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "baseline_plan",
        "baseline_strategy_plan",
        "feature_recipe",
        "model_package",
        "model_validation_report",
        "model_validation_metrics",
        "prediction_replay",
        "data_quality_gate",
        "data_quality_report",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "research_plan",
        "agent_task_contract",
        "research_brief",
        "approach_candidate",
        "report",
        "visualization_spec",
        "insight_set",
        "evaluation_diagnostics",
        "evaluation_diagnostics_report",
        "experiment_plan",
        "experiment_comparison",
        "experiment_comparison_report",
        "run_report",
        "decision_dashboard",
        "decision_report",
        "agent_workspace_manifest",
        "agent_task_readiness_review",
        "agent_task_readiness_report",
        "agent_context_pack",
        "agent_task_report",
        "agent_result",
        "notebook_authoring_brief",
        "notebook_authoring_report",
        "eda_review_bundle",
        "eda_review_svg",
        "eda_review_report",
    }.issubset(asset_types)
    artifacts = artifacts_response.json()
    validation_report = next(item for item in artifacts if item["asset_type"] == "model_validation_report")
    model_package = next(item for item in artifacts if item["asset_type"] == "model_package")
    diagnostics_report = next(item for item in artifacts if item["asset_type"] == "evaluation_diagnostics_report")
    run_report = next(item for item in artifacts if item["asset_type"] == "run_report")
    experiment_comparison = next(item for item in artifacts if item["asset_type"] == "experiment_comparison")
    approval_review = next(item for item in artifacts if item["asset_type"] == "evaluation_approval_review")
    workspace_manifest = next(item for item in artifacts if item["asset_type"] == "agent_workspace_manifest")

    preview_response = client.get(f"/api/artifacts/{validation_report['id']}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["preview_available"] is True
    assert "Model Package Validation Report" in preview_response.json()["preview"]

    diagnostics_preview_response = client.get(f"/api/artifacts/{diagnostics_report['id']}/preview")
    assert diagnostics_preview_response.status_code == 200
    assert "Evaluation Diagnostics" in diagnostics_preview_response.json()["preview"]

    run_report_preview_response = client.get(f"/api/artifacts/{run_report['id']}/preview")
    assert run_report_preview_response.status_code == 200
    assert "Run Report" in run_report_preview_response.json()["preview"]

    comparison_preview_response = client.get(f"/api/artifacts/{experiment_comparison['id']}/preview")
    assert comparison_preview_response.status_code == 200
    assert "experiment_comparison.v1" in comparison_preview_response.json()["preview"]

    approval_review_late_preview_response = client.get(f"/api/artifacts/{approval_review['id']}/preview")
    assert approval_review_late_preview_response.status_code == 200
    assert "evaluation_approval_review.v1" in approval_review_late_preview_response.json()["preview"]

    workspace_preview_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/preview")
    assert workspace_preview_response.status_code == 200
    workspace_download_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/download")
    assert workspace_download_response.status_code == 200
    workspace_payload = workspace_download_response.json()
    assert workspace_payload["schema_version"] == "agent_workspace_manifest.v1"
    assert workspace_payload["safety"]["connector_credentials"] == "not_materialized"
    materialized_paths = [item["context_path"] for item in workspace_payload["materialized_sources"]]
    assert any("research_plan.json" in path for path in materialized_paths)
    assert any("baseline_metrics.json" in path for path in materialized_paths)
    assert any("baseline_report.md" in path for path in materialized_paths)
    assert any(path.startswith(".harness/context/library_assets/") for path in materialized_paths)
    assert any(item.get("asset_name") == "xgboost_mixed_type_baseline" for item in workspace_payload["materialized_sources"])

    package_preview_response = client.get(f"/api/artifacts/{model_package['id']}/preview")
    assert package_preview_response.status_code == 200
    assert package_preview_response.json()["preview_available"] is False

    download_response = client.get(f"/api/artifacts/{validation_report['id']}/download")
    assert download_response.status_code == 200
    assert b"Model Package Validation Report" in download_response.content

    lineage_response = client.get(f"/api/projects/{project_id}/lineage")
    assert lineage_response.status_code == 200
    assert any(item["to_asset_type"] == "model_version" for item in lineage_response.json())

    schema_response = client.get(f"/api/datasets/{dataset_id}/schema")
    assert schema_response.status_code == 200
    assert len(schema_response.json()["columns"]) == 5


def test_bounded_profile_quality_gate_uses_sample_scope(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Wide", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
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
    csv_bytes = (",".join(header) + "\n" + "\n".join(rows) + "\n").encode("utf-8")

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("wide.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    profile_artifact = next(item for item in artifacts_response.json() if item["asset_type"] == "eda_profile")
    assert profile_artifact["metadata"]["profile_mode"] == "bounded_sample"

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "queued"
    gate = run_queued_job(client, quality_job["id"])["gate"]
    assert gate["profile_boundary"]["quality_check_scope"] == "sample"
    assert any(check["check_id"] == "profile_statistics_sampled" for check in gate["checks"])
    duplicate_check = next(check for check in gate["checks"] if check["check_id"] == "duplicate_rows")
    assert duplicate_check["status"] == "pass"
    assert duplicate_check["evidence"]["duplicate_row_count"] == 0

    latest_quality_response = client.get(f"/api/datasets/{dataset_id}/quality/latest")
    assert latest_quality_response.status_code == 200
    assert latest_quality_response.json()["metadata"]["quality_check_scope"] == "sample"


def test_planned_agent_task_stub_rejects_blocked_readiness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Blocked planned task", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert plan_response.status_code == 200, plan_response.text
    plan_job = plan_response.json()
    assert plan_job["status"] == "queued"
    plan_output = run_queued_job(client, plan_job["id"])
    contract_artifact_id = plan_output["agent_task_contract_artifact_id"]

    run_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/run-local-stub")
    assert run_response.status_code == 200
    run_job = run_response.json()
    assert run_job["status"] == "queued"
    completed, _ = run_queued_job_expect_status(client, run_job["id"], "failed")
    assert completed.error_message is not None
    assert "readiness has blockers" in completed.error_message


def test_evaluation_approval_blocks_required_unanswered_question(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Missing target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("features.csv", b"feature_a,feature_b\n1,10\n2,20\n3,30\n4,40\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    assert any(item["fallback_policy"] == "block_until_answered" for item in questions_response.json())

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    assert design_response.json()["status"] == "queued"
    run_queued_job(client, design_response.json()["id"])
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidate = candidates_response.json()[0]

    promote_response = client.post(f"/api/evaluation-candidates/{candidate['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]

    review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert review_response.status_code == 200, review_response.text
    review_job = review_response.json()
    assert review_job["status"] == "queued"
    review_output = run_queued_job(client, review_job["id"])
    assert review_output["review_status"] == "blocked"
    assert review_output["blocker_count"] >= 1

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 409
    assert "block_until_answered" in approve_response.text

    spec_response = client.get(f"/api/evaluation-specs/{spec_id}")
    assert spec_response.status_code == 200
    assert spec_response.json()["status"] == "draft"


def test_benchmark_catalog_and_local_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    benchmarks_response = client.get("/api/benchmarks")
    assert benchmarks_response.status_code == 200, benchmarks_response.text
    benchmarks = benchmarks_response.json()
    assert any(item["id"] == "kaggle_home_credit_default_risk" for item in benchmarks)
    assert any(item["id"] == "uci_wine_quality" for item in benchmarks)
    assert any(item["id"] == "openml_credit_g" for item in benchmarks)
    home_credit_benchmark = next(item for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk")
    assert home_credit_benchmark["source_card"]["access"]["requires_account"] is True
    assert home_credit_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "user_managed_outside_tablex"
    assert home_credit_benchmark["source_card"]["credential_probe"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_probe"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["credential_inventory"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_inventory"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["credential_download"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_download"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["table_bundle"]["supporting_table_count"] >= 1
    assert home_credit_benchmark["source_card"]["source_verification"]["source_count"] >= 1
    uci_benchmark = next(item for item in benchmarks if item["id"] == "uci_bank_marketing")
    assert uci_benchmark["local_status"]["ready"] is False
    assert uci_benchmark["fixture_available"] is True
    assert uci_benchmark["source_card"]["access"]["supports_direct_download"] is True
    assert uci_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "not_required"
    assert uci_benchmark["source_card"]["credential_probe"]["supported"] is False
    assert uci_benchmark["source_card"]["credential_inventory"]["supported"] is False
    assert uci_benchmark["source_card"]["credential_download"]["supported"] is False
    assert uci_benchmark["scenario"]["kind"] == "single_table_categorical_smoke"
    openml_benchmark = next(item for item in benchmarks if item["id"] == "openml_credit_g")
    assert openml_benchmark["source_card"]["table_bundle"]["kind"] == "single_table_bundle"
    assert openml_benchmark["source_card"]["source_verification"]["access_checked"]["requires_account"] is False
    assert "Do not paste Kaggle credentials" in next(
        item["download_instructions"] for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk"
    )

    source_card_response = client.get("/api/benchmarks/uci_bank_marketing/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["schema_version"] == "benchmark_source_card.v1"
    assert source_card["access"]["kind"] == "public_direct_download"
    assert "bank+marketing.zip" in str(source_card["download"]["download_urls"])

    readiness_response = client.get("/api/benchmarks/uci_bank_marketing/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is False
    assert any("fixture" in item.lower() for item in readiness_response.json()["next_actions"])

    project_response = client.post(
        "/api/projects",
        json={"name": "Benchmark import", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    collection_response = client.post(f"/api/projects/{project_id}/benchmarks/collection-plan")
    assert collection_response.status_code == 200, collection_response.text
    collection_job = collection_response.json()
    assert collection_job["status"] == "queued"
    assert collection_job["policy"]["execution"] == "queued_worker"
    collection_output = run_queued_job(client, collection_job["id"])
    assert collection_output["schema_version"] == "benchmark_collection_plan.v1"
    assert collection_output["benchmark_collection_plan_artifact_id"]
    assert collection_output["benchmark_collection_report_artifact_id"]
    assert collection_output["credentialed_count"] >= 1
    assert collection_output["public_direct_count"] >= 1
    assert collection_output["multitable_count"] >= 1

    collection_plan_response = client.get(
        f"/api/artifacts/{collection_output['benchmark_collection_plan_artifact_id']}/download"
    )
    assert collection_plan_response.status_code == 200
    collection_plan = collection_plan_response.json()
    assert collection_plan["credential_policy"]["secret_access"] == "forbidden"
    home_credit_plan = next(
        item for item in collection_plan["benchmarks"] if item["benchmark_id"] == "kaggle_home_credit_default_risk"
    )
    assert "credentialed_manual_download_required" in home_credit_plan["collection_status"]
    openml_plan = next(item for item in collection_plan["benchmarks"] if item["benchmark_id"] == "openml_credit_g")
    assert "public_workflow_available" in openml_plan["collection_status"]

    collection_report_response = client.get(
        f"/api/artifacts/{collection_output['benchmark_collection_report_artifact_id']}/preview"
    )
    assert collection_report_response.status_code == 200
    collection_report = collection_report_response.json()["preview"]
    assert "Benchmark Collection Plan" in collection_report
    assert "Home Credit Default Risk" in collection_report

    import_missing_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_missing_response.status_code == 200
    import_missing_job = import_missing_response.json()
    assert import_missing_job["status"] == "queued"
    assert import_missing_job["policy"]["execution"] == "queued_worker"
    failed_import_job, _ = run_queued_job_expect_status(client, import_missing_job["id"], "failed")
    assert failed_import_job.error_message is not None
    assert "Missing required benchmark files" in failed_import_job.error_message

    fixture_response = client.post("/api/benchmarks/uci_bank_marketing/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["schema_version"] == "benchmark_fixture.v1"
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "bank-full.csv" for item in fixture["generated_files"])

    status_response = client.get("/api/benchmarks/uci_bank_marketing/local-status")
    assert status_response.status_code == 200
    assert status_response.json()["ready"] is True

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_response.status_code == 200, import_response.text
    import_job = import_response.json()
    assert import_job["status"] == "queued"
    assert import_job["policy"]["execution"] == "queued_worker"
    payload = run_queued_job(client, import_job["id"])
    assert payload["primary_file"] == "bank-full.csv"
    assert payload["dataset_snapshot"]["source_type"] == "benchmark_catalog"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_bank_marketing:bank-full.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_bank_marketing"
    assert payload["import_manifest_artifact"]["asset_type"] == "benchmark_import_manifest"
    assert payload["relational_catalog_artifact"]["asset_type"] == "relational_catalog"
    assert payload["supporting_table_artifacts"] == []

    project_after_import = client.get(f"/api/projects/{project_id}")
    assert project_after_import.status_code == 200
    assert project_after_import.json()["target_column"] == "y"

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    assert "benchmark_import_manifest.v1" in manifest_preview_response.json()["preview"]
    assert "not_stored_or_passed_to_agent" in manifest_preview_response.json()["preview"]

    relational_preview_response = client.get(f"/api/artifacts/{payload['relational_catalog_artifact']['id']}/preview")
    assert relational_preview_response.status_code == 200
    assert "relational_catalog.v1" in relational_preview_response.json()["preview"]

    scenario_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack")
    assert scenario_response.status_code == 200, scenario_response.text
    scenario_job = scenario_response.json()
    assert scenario_job["status"] == "queued"
    assert scenario_job["policy"]["execution"] == "queued_worker"
    scenario_output = run_queued_job(client, scenario_job["id"])
    assert scenario_output["scenario_kind"] == "single_table_categorical_smoke"
    assert scenario_output["benchmark_scenario_pack_artifact_id"]
    scenario_preview_response = client.get(
        f"/api/artifacts/{scenario_output['benchmark_scenario_report_artifact_id']}/preview"
    )
    assert scenario_preview_response.status_code == 200
    assert "Benchmark Scenario Report" in scenario_preview_response.json()["preview"]


def test_public_uci_wine_fixture_source_card_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    source_card_response = client.get("/api/benchmarks/uci_wine_quality/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["access"]["requires_account"] is False
    assert source_card["access"]["supports_direct_download"] is True
    assert "wine+quality.zip" in str(source_card["download"]["download_urls"])
    assert source_card["import_readiness"]["can_import_now"] is False

    fixture_response = client.post("/api/benchmarks/uci_wine_quality/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "winequality-red.csv" for item in fixture["generated_files"])

    readiness_response = client.get("/api/benchmarks/uci_wine_quality/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is True

    project_response = client.post(
        "/api/projects",
        json={"name": "Wine quality public smoke", "task_type": "regression"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_wine_quality/import", json={})
    assert import_response.status_code == 200, import_response.text
    import_job = import_response.json()
    assert import_job["status"] == "queued"
    assert import_job["policy"]["execution"] == "queued_worker"
    payload = run_queued_job(client, import_job["id"])
    assert payload["primary_file"] == "winequality-red.csv"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_wine_quality:winequality-red.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert payload["relational_catalog_artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert len(payload["supporting_table_artifacts"]) == 1

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    manifest_preview = manifest_preview_response.json()["preview"]
    assert "benchmark_import_manifest.v1" in manifest_preview
    assert "public_direct_download" in manifest_preview


def test_public_benchmark_download_extracts_expected_files(tmp_path: Path, monkeypatch: Any) -> None:
    archive_dir = tmp_path / "served"
    archive_dir.mkdir()
    archive_path = archive_dir / "public.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/public.csv", "feature,target\n1,0\n2,1\n")
        archive.writestr("../evil.csv", "feature,target\n9,9\n")
        archive.writestr("ignored.txt", "ignore me\n")

    handler = partial(SimpleHTTPRequestHandler, directory=str(archive_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/public.zip"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_zip_smoke",
                            "name": "Public Zip Smoke",
                            "source_kind": "public_test_archive",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "zip",
                                        "expected_files": ["public.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "public.csv", "target_column": "target"},
                            "required_files": [
                                {"path": "public.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_archive",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "zip", "expected_files": ["public.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        readiness_response = client.get("/api/benchmarks/public_zip_smoke/import-readiness")
        assert readiness_response.status_code == 200
        assert readiness_response.json()["can_import_now"] is False

        download_response = client.post("/api/benchmarks/public_zip_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "queued"
        assert job["policy"]["execution"] == "queued_worker"
        output = run_queued_job(client, job["id"])
        assert output["extracted_file_count"] == 1
        assert output["local_ready"] is True
        assert output["artifact_id"]

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_zip_smoke"
        assert (benchmark_root / "public.csv").read_text(encoding="utf-8").startswith("feature,target")
        assert not (benchmark_root / "evil.csv").exists()

        status_response = client.get("/api/benchmarks/public_zip_smoke/local-status")
        assert status_response.status_code == 200
        assert status_response.json()["ready"] is True

        manifest_preview_response = client.get(f"/api/artifacts/{output['artifact_id']}/preview")
        assert manifest_preview_response.status_code == 200
        manifest_preview = manifest_preview_response.json()["preview"]
        assert "benchmark_public_download_manifest.v1" in manifest_preview
        assert "unsafe_path" in manifest_preview
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_download_places_direct_csv(tmp_path: Path, monkeypatch: Any) -> None:
    served_dir = tmp_path / "served_direct"
    served_dir.mkdir()
    (served_dir / "credit.csv").write_text("feature,class\n1,good\n2,bad\n", encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/credit.csv"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_csv_smoke",
                            "name": "Public CSV Smoke",
                            "source_kind": "public_test_file",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "csv",
                                        "expected_files": ["credit.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "credit.csv", "target_column": "class"},
                            "required_files": [
                                {"path": "credit.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_direct_file",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "csv", "expected_files": ["credit.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        download_response = client.post("/api/benchmarks/public_csv_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "queued"
        assert job["policy"]["execution"] == "queued_worker"
        output = run_queued_job(client, job["id"])
        assert output["extracted_file_count"] == 1
        assert output["local_ready"] is True

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_csv_smoke"
        assert (benchmark_root / "credit.csv").read_text(encoding="utf-8").startswith("feature,class")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_workflow_runs_baseline_and_reports(tmp_path: Path, monkeypatch: Any) -> None:
    served_dir = tmp_path / "served_workflow"
    served_dir.mkdir()
    rows = ["feature_num,feature_cat,note,class"]
    for index in range(40):
        label = "good" if index % 2 == 0 else "bad"
        category = "low" if index % 3 == 0 else "high"
        note = "steady payer" if label == "good" else "late payment"
        rows.append(f"{index},{category},{note},{label}")
    (served_dir / "workflow.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/workflow.csv"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_workflow_smoke",
                            "name": "Public Workflow Smoke",
                            "source_kind": "public_test_file",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "csv",
                                        "expected_files": ["workflow.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "scenario": {
                                "kind": "single_table_public_workflow_smoke",
                                "validation_focus": "stratified_split",
                                "feature_focus": ["numeric_imputation", "categorical_encoding", "text_tfidf"],
                                "report_focus": ["baseline_sanity", "leaderboard"],
                            },
                            "primary_table": {"path": "workflow.csv", "target_column": "class"},
                            "required_files": [
                                {"path": "workflow.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_direct_file",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "csv", "expected_files": ["workflow.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)
        project_response = client.post(
            "/api/projects",
            json={"name": "Public benchmark workflow", "task_type": "binary_classification"},
        )
        assert project_response.status_code == 200
        project_id = project_response.json()["id"]

        workflow_response = client.post(
            f"/api/projects/{project_id}/benchmarks/public_workflow_smoke/public-workflow",
            json={"overwrite": False},
        )
        assert workflow_response.status_code == 200, workflow_response.text
        workflow_job = workflow_response.json()
        assert workflow_job["status"] == "queued"
        assert workflow_job["policy"]["execution"] == "queued_worker"
        output = run_queued_job(client, workflow_job["id"])
        assert output["download_manifest_artifact_id"]
        assert output["dataset_snapshot_id"]
        assert output["evaluation_spec_id"]
        assert output["split_manifest_id"]
        assert output["baseline_strategy_plan_artifact_id"]
        assert output["experiment_run_id"]
        assert output["metrics"]["model_baseline_attempted"] is True
        assert output["run_report_artifact_id"]
        assert output["decision_dashboard_artifact_id"]
        assert output["decision_report_artifact_id"]
        assert output["benchmark_scenario_pack_artifact_id"]
        assert len(output["visualization_ids"]) >= 4
        assert len(output["artifact_ids"]) >= 20

        job_artifacts_response = client.get(f"/api/jobs/{workflow_job['id']}/artifacts")
        assert job_artifacts_response.status_code == 200
        job_artifacts = job_artifacts_response.json()
        assert job_artifacts["summary"]["benchmark_id"] == "public_workflow_smoke"
        assert job_artifacts["summary"]["experiment_run_id"] == output["experiment_run_id"]
        assert job_artifacts["summary"]["artifact_count"] >= 20
        assert job_artifacts["missing_artifact_ids"] == []
        assert any(item["asset_type"] == "decision_report" for item in job_artifacts["artifacts"])

        runs_response = client.get(f"/api/projects/{project_id}/runs")
        assert runs_response.status_code == 200
        assert runs_response.json()[0]["id"] == output["experiment_run_id"]

        artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
        assert artifacts_response.status_code == 200
        asset_types = {item["asset_type"] for item in artifacts_response.json()}
        assert {
            "benchmark_import_manifest",
            "relational_catalog",
            "baseline_strategy_plan",
            "baseline_report",
            "baseline_metrics",
            "evaluation_diagnostics",
            "evaluation_diagnostics_report",
            "run_report",
            "visualization_spec",
            "insight_set",
            "decision_dashboard",
            "decision_report",
            "benchmark_scenario_pack",
        }.issubset(asset_types)

        decision_preview_response = client.get(f"/api/artifacts/{output['decision_report_artifact_id']}/preview")
        assert decision_preview_response.status_code == 200
        assert "Decision Report" in decision_preview_response.json()["preview"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_workflow_rejects_credentialed_source(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Credentialed benchmark workflow", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/public-workflow",
        json={"overwrite": False},
    )
    assert response.status_code == 400
    assert "credential-free" in response.text


def test_benchmark_evidence_pack_empty_project(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Empty benchmark evidence", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    evidence_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_response.status_code == 200, evidence_response.text
    evidence_job = evidence_response.json()
    assert evidence_job["status"] == "queued"
    assert evidence_job["policy"]["execution"] == "queued_worker"
    evidence_output = run_queued_job(client, evidence_job["id"])
    assert evidence_output["benchmark_count"] == 0
    assert evidence_output["benchmark_evidence_pack_artifact_id"]
    assert evidence_output["benchmark_evidence_report_artifact_id"]
    assert evidence_output["visualization_artifact_id"]
    assert evidence_output["evidence_id"]

    report_preview_response = client.get(
        f"/api/artifacts/{evidence_output['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert report_preview_response.status_code == 200
    assert "No benchmark evidence exists yet" in report_preview_response.json()["preview"]


def test_home_credit_fixture_smoke_harness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit fixture smoke", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    smoke_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke",
        json={"overwrite": True},
    )
    assert smoke_response.status_code == 200, smoke_response.text
    smoke_job = smoke_response.json()
    assert smoke_job["status"] == "queued"
    assert smoke_job["policy"]["execution"] == "queued_worker"
    output = run_queued_job(client, smoke_job["id"])
    assert output["fixture"]["local_status"]["ready"] is True
    assert output["fixture"]["fixture_matches_expected"] is True
    assert output["dataset_snapshot_id"]
    assert output["quality_gate"]["schema_version"] == "data_quality_gate.v1"
    assert output["evaluation_scenario_comparison_artifact_id"]
    assert output["approval_review_artifact_id"]
    assert output["split_manifest_id"]
    assert output["baseline_strategy_plan_artifact_id"]
    assert output["research_plan_artifact_id"]
    assert output["benchmark_scenario_pack_artifact_id"]
    assert output["benchmark_scenario_report_artifact_id"]
    assert len(output["artifact_ids"]) >= 16

    strategy_preview_response = client.get(f"/api/artifacts/{output['baseline_strategy_plan_artifact_id']}/preview")
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "adaptive_baseline_planning" in strategy_preview
    assert "relational_aggregation_features" in strategy_preview
    assert "reporting_plan" in strategy_preview

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "benchmark_import_manifest",
        "relational_catalog",
        "data_quality_gate",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "split_manifest",
        "baseline_strategy_plan",
        "research_plan",
        "benchmark_supporting_table",
        "benchmark_scenario_pack",
        "benchmark_scenario_report",
    }.issubset(asset_types)

    scenario_report_preview_response = client.get(f"/api/artifacts/{output['benchmark_scenario_report_artifact_id']}/preview")
    assert scenario_report_preview_response.status_code == 200
    scenario_report_preview = scenario_report_preview_response.json()["preview"]
    assert "multi_table_credit_risk" in scenario_report_preview
    assert "Fixture results are product smoke checks" in scenario_report_preview

    evidence_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_response.status_code == 200, evidence_response.text
    evidence_job = evidence_response.json()
    assert evidence_job["status"] == "queued"
    assert evidence_job["policy"]["execution"] == "queued_worker"
    evidence_output = run_queued_job(client, evidence_job["id"])
    assert evidence_output["benchmark_count"] == 1
    assert evidence_output["benchmark_ids"] == ["kaggle_home_credit_default_risk"]
    assert evidence_output["benchmark_evidence_pack_artifact_id"]
    assert evidence_output["benchmark_evidence_report_id"]
    assert evidence_output["benchmark_evidence_report_artifact_id"]
    assert evidence_output["visualization_id"]
    assert evidence_output["visualization_artifact_id"]
    assert evidence_output["evidence_id"]
    assert len(evidence_output["artifact_ids"]) == 3

    evidence_job_artifacts_response = client.get(f"/api/jobs/{evidence_job['id']}/artifacts")
    assert evidence_job_artifacts_response.status_code == 200
    evidence_job_artifacts = evidence_job_artifacts_response.json()
    assert evidence_job_artifacts["summary"]["benchmark_count"] == 1
    assert evidence_job_artifacts["summary"]["benchmark_evidence_pack_artifact_id"]
    evidence_asset_types = {item["asset_type"] for item in evidence_job_artifacts["artifacts"]}
    assert {"benchmark_evidence_pack", "benchmark_evidence_report", "visualization_spec"}.issubset(
        evidence_asset_types
    )

    evidence_pack_preview_response = client.get(
        f"/api/artifacts/{evidence_output['benchmark_evidence_pack_artifact_id']}/preview"
    )
    assert evidence_pack_preview_response.status_code == 200
    evidence_pack_preview = evidence_pack_preview_response.json()["preview"]
    assert "benchmark_evidence_pack.v1" in evidence_pack_preview
    assert "benchmark_supporting_table" in evidence_pack_preview

    evidence_report_preview_response = client.get(
        f"/api/artifacts/{evidence_output['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert evidence_report_preview_response.status_code == 200
    evidence_report_preview = evidence_report_preview_response.json()["preview"]
    assert "Benchmark Evidence Pack" in evidence_report_preview
    assert "Home Credit Default Risk" in evidence_report_preview


def test_benchmark_relational_catalog_infers_shared_keys(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit tiny", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    benchmark_dir = tmp_path / "data" / "benchmarks" / "kaggle_home_credit_default_risk"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "application_train.csv").write_text(
        "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL\n"
        "100001,1,120000\n"
        "100002,0,90000\n"
        "100003,0,110000\n",
        encoding="utf-8",
    )
    (benchmark_dir / "bureau.csv").write_text(
        "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE\n"
        "100001,200001,Active\n"
        "100001,200002,Closed\n"
        "100002,200003,Closed\n",
        encoding="utf-8",
    )

    import_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/import",
        json={},
    )
    assert import_response.status_code == 200, import_response.text
    import_job_response = import_response.json()
    assert import_job_response["status"] == "queued"
    assert import_job_response["policy"]["execution"] == "queued_worker"
    import_output = run_queued_job(client, import_job_response["id"])
    assert len(import_output["supporting_table_artifacts"]) == 1
    assert import_output["supporting_table_artifacts"][0]["asset_type"] == "benchmark_supporting_table"
    output_job_response = client.get(f"/api/projects/{project_id}/jobs")
    assert output_job_response.status_code == 200
    import_job = next(item for item in output_job_response.json() if item["job_type"] == "import_benchmark_dataset")
    assert import_job["output"]["table_count"] == 2
    assert import_job["output"]["relationship_count"] >= 1

    relational_artifact_id = import_output["relational_catalog_artifact"]["id"]
    relational_preview_response = client.get(f"/api/artifacts/{relational_artifact_id}/preview")
    assert relational_preview_response.status_code == 200
    preview = relational_preview_response.json()["preview"]
    assert "relational_catalog.v1" in preview
    assert "SK_ID_CURR" in preview
    assert "shared_key_name" in preview

    seed_assets_response = client.post("/api/assets/seed-defaults")
    assert seed_assets_response.status_code == 200
    collection_response = client.post(f"/api/projects/{project_id}/benchmarks/collection-plan")
    assert collection_response.status_code == 200, collection_response.text
    collection_job = collection_response.json()
    assert collection_job["status"] == "queued"
    assert collection_job["policy"]["execution"] == "queued_worker"
    collection_output = run_queued_job(client, collection_job["id"])

    relational_plan_response = client.post(f"/api/projects/{project_id}/features/relational-plan")
    assert relational_plan_response.status_code == 200, relational_plan_response.text
    relational_plan_job = relational_plan_response.json()
    assert relational_plan_job["status"] == "queued"
    assert relational_plan_job["policy"]["execution"] == "queued_worker"
    relational_plan_output = run_queued_job(client, relational_plan_job["id"])
    assert relational_plan_output["schema_version"] == "relational_feature_plan.v1"
    assert relational_plan_output["relational_feature_plan_artifact_id"]
    assert relational_plan_output["relational_feature_report_artifact_id"]
    assert relational_plan_output["visualization_id"]
    assert relational_plan_output["evidence_id"]
    assert relational_plan_output["supporting_table_count"] == 1
    assert relational_plan_output["relationship_count"] >= 1
    assert relational_plan_output["aggregation_candidate_count"] >= 1

    relational_plan_download_response = client.get(
        f"/api/artifacts/{relational_plan_output['relational_feature_plan_artifact_id']}/download"
    )
    assert relational_plan_download_response.status_code == 200
    relational_plan = relational_plan_download_response.json()
    assert relational_plan["schema_version"] == "relational_feature_plan.v1"
    assert relational_plan["source_summary"]["benchmark_id"] == "kaggle_home_credit_default_risk"
    assert relational_plan["source_summary"]["benchmark_collection_plan_artifact_id"] == collection_output[
        "benchmark_collection_plan_artifact_id"
    ]
    assert relational_plan["agent_task_handoff"]["fit_aggregations_on_training_folds_only"] is True
    assert any(item["risk_level"] == "high" for item in relational_plan["risk_register"])

    relational_report_response = client.get(
        f"/api/artifacts/{relational_plan_output['relational_feature_report_artifact_id']}/preview"
    )
    assert relational_report_response.status_code == 200
    assert "Relational Feature Plan" in relational_report_response.json()["preview"]

    relational_recipe_response = client.post(f"/api/projects/{project_id}/features/relational-recipe/build")
    assert relational_recipe_response.status_code == 200, relational_recipe_response.text
    relational_recipe_job = relational_recipe_response.json()
    assert relational_recipe_job["status"] == "queued"
    assert relational_recipe_job["policy"]["execution"] == "queued_worker"
    relational_recipe_output = run_queued_job(client, relational_recipe_job["id"])
    assert relational_recipe_output["schema_version"] == "relational_feature_recipe.v1"
    assert relational_recipe_output["relational_feature_recipe_artifact_id"]
    assert relational_recipe_output["relational_feature_preview_artifact_id"]
    assert relational_recipe_output["relational_feature_preview_profile_artifact_id"]
    assert relational_recipe_output["relational_feature_recipe_report_artifact_id"]
    assert relational_recipe_output["generated_feature_count"] >= 1
    assert relational_recipe_output["executed_step_count"] >= 1
    assert relational_recipe_output["preview_row_count"] > 0

    relational_recipe_download_response = client.get(
        f"/api/artifacts/{relational_recipe_output['relational_feature_recipe_artifact_id']}/download"
    )
    assert relational_recipe_download_response.status_code == 200
    relational_recipe = relational_recipe_download_response.json()
    assert relational_recipe["schema_version"] == "relational_feature_recipe.v1"
    assert relational_recipe["source_summary"]["benchmark_id"] == "kaggle_home_credit_default_risk"
    assert (
        relational_recipe["source_summary"]["relational_feature_plan_artifact_id"]
        == relational_plan_output["relational_feature_plan_artifact_id"]
    )
    assert relational_recipe["execution_scope"]["mode"] == "preview_only"
    assert relational_recipe["safety"]["target_column_excluded"] == "TARGET"
    assert relational_recipe["safety"]["fit_on_training_folds_only"] is True
    assert all("TARGET" not in item.get("columns", []) for item in relational_recipe["steps"])

    relational_recipe_preview_response = client.get(
        f"/api/artifacts/{relational_recipe_output['relational_feature_preview_artifact_id']}/download"
    )
    assert relational_recipe_preview_response.status_code == 200
    assert "bureau_categorical_summaries__row_count" in relational_recipe_preview_response.text

    relational_recipe_report_response = client.get(
        f"/api/artifacts/{relational_recipe_output['relational_feature_recipe_report_artifact_id']}/preview"
    )
    assert relational_recipe_report_response.status_code == 200
    assert "Relational Feature Recipe" in relational_recipe_report_response.json()["preview"]

    relational_diagnostics_response = client.post(
        f"/api/projects/{project_id}/features/relational-scenarios/diagnose"
    )
    assert relational_diagnostics_response.status_code == 200, relational_diagnostics_response.text
    relational_diagnostics_job = relational_diagnostics_response.json()
    assert relational_diagnostics_job["status"] == "queued"
    assert relational_diagnostics_job["policy"]["execution"] == "queued_worker"
    relational_diagnostics_output = run_queued_job(client, relational_diagnostics_job["id"])
    assert relational_diagnostics_output["schema_version"] == "relational_feature_scenario_diagnostics.v1"
    assert relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
    assert relational_diagnostics_output["relational_feature_scenario_report_artifact_id"]
    assert relational_diagnostics_output["generated_feature_count"] >= 1
    assert relational_diagnostics_output["usable_feature_count"] >= 1
    assert relational_diagnostics_output["scenario_count"] >= 3

    relational_diagnostics_download_response = client.get(
        "/api/artifacts/"
        f"{relational_diagnostics_output['relational_feature_scenario_diagnostics_artifact_id']}/download"
    )
    assert relational_diagnostics_download_response.status_code == 200
    relational_diagnostics = relational_diagnostics_download_response.json()
    assert relational_diagnostics["schema_version"] == "relational_feature_scenario_diagnostics.v1"
    assert relational_diagnostics["safety"]["model_training_performed"] is False
    assert relational_diagnostics["safety"]["fixed_model_strategy"] is False
    assert relational_diagnostics["split_compatibility"]["status"] == "missing_evaluation_spec"
    assert any(item["scenario"] == "safe_relational_preview" for item in relational_diagnostics["scenario_comparison"])

    relational_diagnostics_report_response = client.get(
        f"/api/artifacts/{relational_diagnostics_output['relational_feature_scenario_report_artifact_id']}/preview"
    )
    assert relational_diagnostics_report_response.status_code == 200
    assert "Relational Feature Scenario Diagnostics" in relational_diagnostics_report_response.json()["preview"]

    evidence_pack_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_pack_response.status_code == 200, evidence_pack_response.text
    evidence_pack_job = evidence_pack_response.json()
    assert evidence_pack_job["status"] == "queued"
    assert evidence_pack_job["policy"]["execution"] == "queued_worker"
    evidence_pack_output = run_queued_job(client, evidence_pack_job["id"])
    evidence_pack_download_response = client.get(
        f"/api/artifacts/{evidence_pack_output['benchmark_evidence_pack_artifact_id']}/download"
    )
    assert evidence_pack_download_response.status_code == 200
    evidence_pack = evidence_pack_download_response.json()
    assert evidence_pack["summary"]["relational_recipe_count"] >= 1
    assert evidence_pack["summary"]["relational_diagnostics_count"] >= 1
    evidence_entry = evidence_pack["benchmarks"][0]
    assert (
        evidence_entry["relational_features"]["diagnostics_artifact_id"]
        == relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
    )
    assert any(stage["stage"] == "Relational diagnostics" for stage in evidence_entry["stages"])
    evidence_report_response = client.get(
        f"/api/artifacts/{evidence_pack_output['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert evidence_report_response.status_code == 200
    assert "Relational scenarios" in evidence_report_response.json()["preview"]

    decision_response = client.post(f"/api/projects/{project_id}/decision-dashboard/generate")
    assert decision_response.status_code == 200, decision_response.text
    decision_job = decision_response.json()
    assert decision_job["status"] == "queued"
    assert decision_job["job_type"] == "generate_decision_dashboard"
    assert decision_job["policy"]["execution"] == "queued_worker"
    decision_output = run_queued_job(client, decision_job["id"])
    decision_download_response = client.get(
        f"/api/artifacts/{decision_output['decision_dashboard_artifact_id']}/download"
    )
    assert decision_download_response.status_code == 200
    decision_dashboard = decision_download_response.json()
    assert (
        decision_dashboard["relational_context"]["diagnostics_artifact_id"]
        == relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
    )
    assert any(stage["stage"] == "Relational" for stage in decision_dashboard["readiness_stages"])
    decision_report_response = client.get(f"/api/reports/{decision_output['report_id']}/preview")
    assert decision_report_response.status_code == 200
    assert "Relational Feature Context" in decision_report_response.json()["preview"]

    project_report_response = client.post(f"/api/projects/{project_id}/reports/draft", json={})
    assert project_report_response.status_code == 200, project_report_response.text
    project_report_job = project_report_response.json()
    assert project_report_job["status"] == "queued"
    project_report_output = run_queued_job(client, project_report_job["id"])
    project_report_preview_response = client.get(f"/api/reports/{project_report_output['report_id']}/preview")
    assert project_report_preview_response.status_code == 200
    assert "Relational Feature Context" in project_report_preview_response.json()["preview"]

    evaluation_design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert evaluation_design_response.status_code == 200, evaluation_design_response.text
    assert evaluation_design_response.json()["status"] == "queued"
    run_queued_job(client, evaluation_design_response.json()["id"])
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    random_candidate = next(item for item in candidates_response.json() if item["split_type"] == "random")
    promote_response = client.post(f"/api/evaluation-candidates/{random_candidate['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]
    approval_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approval_response.status_code == 200, approval_response.text
    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    assert split_response.json()["status"] == "queued"
    run_queued_job(client, split_response.json()["id"])

    agent_task_plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert agent_task_plan_response.status_code == 200, agent_task_plan_response.text
    agent_task_plan_job = agent_task_plan_response.json()
    assert agent_task_plan_job["status"] == "queued"
    agent_task_plan_output = run_queued_job(client, agent_task_plan_job["id"])
    agent_contract_response = client.get(
        f"/api/artifacts/{agent_task_plan_output['agent_task_contract_artifact_id']}/download"
    )
    assert agent_contract_response.status_code == 200
    assert (
        agent_contract_response.json()["inputs"]["relational_feature_plan"]["artifact_id"]
        == relational_plan_output["relational_feature_plan_artifact_id"]
    )
    assert agent_contract_response.json()["inputs"]["relational_feature_recipe"]["artifact_id"] == (
        relational_recipe_output["relational_feature_recipe_artifact_id"]
    )
    assert agent_contract_response.json()["inputs"]["relational_feature_scenario_diagnostics"]["artifact_id"] == (
        relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
    )

    contract_artifact_id = agent_task_plan_output["agent_task_contract_artifact_id"]
    workspace_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/prepare-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_job = workspace_response.json()
    assert workspace_job["status"] == "queued"
    workspace_output = run_queued_job(client, workspace_job["id"])
    assert workspace_output["materialized_relational_context_count"] >= 6
    workspace_download_response = client.get(
        f"/api/artifacts/{workspace_output['agent_workspace_manifest_artifact_id']}/download"
    )
    assert workspace_download_response.status_code == 200
    workspace_manifest = workspace_download_response.json()
    relational_sources = [
        item
        for item in workspace_manifest["materialized_sources"]
        if item["source_kind"] == "relational_context_artifact"
    ]
    assert len(relational_sources) >= 6
    relational_paths = [item["context_path"] for item in relational_sources]
    assert all(path.startswith(".harness/context/relational/") for path in relational_paths)
    assert any("relational_feature_plan" in path and path.endswith(".json") for path in relational_paths)
    assert any("relational_feature_recipe" in path and path.endswith(".json") for path in relational_paths)
    assert any("relational_feature_preview" in path and path.endswith(".csv") for path in relational_paths)
    assert any(
        "relational_feature_preview_profile" in path and path.endswith(".json") for path in relational_paths
    )
    assert any(
        "relational_feature_scenario_diagnostics" in path and path.endswith(".json")
        for path in relational_paths
    )
    assert any(
        "relational_feature_scenario_report" in path and path.endswith(".md") for path in relational_paths
    )
    assert all(item["artifact_id"] and item["content_hash"] for item in relational_sources)
    assert all(isinstance(item["size_bytes"], int) for item in relational_sources)
    assert any(
        item["artifact_id"] == relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
        for item in relational_sources
    )

    readiness_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/readiness-review")
    assert readiness_response.status_code == 200, readiness_response.text
    readiness_job = readiness_response.json()
    assert readiness_job["status"] == "queued"
    readiness_output = run_queued_job(client, readiness_job["id"])
    readiness_download_response = client.get(
        f"/api/artifacts/{readiness_output['agent_task_readiness_review_artifact_id']}/download"
    )
    assert readiness_download_response.status_code == 200
    readiness = readiness_download_response.json()
    relational_check = next(item for item in readiness["checks"] if item["check_id"] == "relational_context")
    assert relational_check["status"] == "pass"
    assert "relational context artifact" in relational_check["summary"]

    stub_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/run-local-stub")
    assert stub_response.status_code == 200, stub_response.text
    stub_job = stub_response.json()
    assert stub_job["status"] == "queued"
    stub_output = run_queued_job(client, stub_job["id"])
    assert stub_output["relational_context_source_count"] >= 6
    assert stub_output["relational_context_summary_artifact_id"]
    assert stub_output["approach_decision_trace_artifact_id"]
    assert len(stub_output["visualization_ids"]) >= 2

    stub_report_response = client.get(
        f"/api/artifacts/{stub_output['ingested_artifact_ids'][0]}/download"
    )
    assert stub_report_response.status_code == 200
    assert "Relational Runner Context" in stub_report_response.text

    relational_summary_response = client.get(
        f"/api/artifacts/{stub_output['relational_context_summary_artifact_id']}/download"
    )
    assert relational_summary_response.status_code == 200
    relational_summary = relational_summary_response.json()
    assert relational_summary["schema_version"] == "relational_runner_context_summary.v1"
    assert relational_summary["status"] == "available"
    assert relational_summary["source_count"] >= 6
    assert relational_summary["coverage"]["has_scenario_report"] is True
    assert relational_summary["deferred_safety_checks"]
    assert relational_summary["recommended_agent_task_scenarios"]

    decision_trace_response = client.get(
        f"/api/artifacts/{stub_output['approach_decision_trace_artifact_id']}/download"
    )
    assert decision_trace_response.status_code == 200
    decision_trace = decision_trace_response.json()
    assert decision_trace["schema_version"] == "approach_decision_trace.v1"
    assert decision_trace["autonomy_policy"]["approach_selection"] == "open_ended_with_harness_constraints"
    assert "propose_new_feature_families" in decision_trace["autonomy_policy"]["runner_may"]
    assert any(
        item["approach"] == "fixed_predefined_recipe_execution"
        and item["status"] == "rejected_as_product_default"
        for item in decision_trace["rejected_or_deferred_approaches"]
    )
    assert decision_trace["context_used"]["relational_context_available"] is True

    agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert agent_results_response.status_code == 200
    agent_results = agent_results_response.json()
    relational_result = next(item for item in agent_results if item["job_id"] == stub_job["id"])
    assert relational_result["relational_context"]["source_count"] >= 6
    assert relational_result["relational_context"]["usable_feature_count"] >= 1
    assert relational_result["relational_context"]["summary_artifact_id"] == stub_output[
        "relational_context_summary_artifact_id"
    ]
    assert relational_result["artifacts"]["relational_context_summary"]["id"] == stub_output[
        "relational_context_summary_artifact_id"
    ]
    assert relational_result["artifacts"]["approach_decision_trace"]["id"] == stub_output[
        "approach_decision_trace_artifact_id"
    ]
    assert relational_result["approach_decision_trace"]["policy"] == "open_ended_with_harness_constraints"
    assert relational_result["approach_decision_trace"]["relational_context_available"] is True

    ideas_response = client.post(f"/api/projects/{project_id}/approach/ideas/generate")
    assert ideas_response.status_code == 200, ideas_response.text
    ideas_job = ideas_response.json()
    assert ideas_job["status"] == "queued"
    run_queued_job(client, ideas_job["id"])
    ideas_list_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert ideas_list_response.status_code == 200
    idea = ideas_list_response.json()[0]
    context_response = client.post(f"/api/ideas/{idea['id']}/prepare-agent-context")
    assert context_response.status_code == 200, context_response.text
    context_job = context_response.json()
    assert context_job["status"] == "queued"
    context_output = run_queued_job(client, context_job["id"])
    context_payload_response = client.get(f"/api/artifacts/{context_output['artifact_id']}/download")
    assert context_payload_response.status_code == 200
    assert (
        context_payload_response.json()["relational_feature_plan_context"]["artifact_id"]
        == relational_plan_output["relational_feature_plan_artifact_id"]
    )
    assert context_payload_response.json()["relational_feature_recipe_context"]["artifact_id"] == (
        relational_recipe_output["relational_feature_recipe_artifact_id"]
    )
    assert context_payload_response.json()["relational_feature_scenario_diagnostics_context"]["artifact_id"] == (
        relational_diagnostics_output["relational_feature_scenario_diagnostics_artifact_id"]
    )
