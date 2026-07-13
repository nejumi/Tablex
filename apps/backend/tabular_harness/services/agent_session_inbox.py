from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    DatasetSnapshot,
    Project,
    ResearchPlanRevision,
    utc_now,
)
from tabular_harness.services.agent_inbox import latest_inbox_entry_path, write_inbox_entry
from tabular_harness.services.agent_notebook_quality import notebook_quality_feedback_from_metadata
from tabular_harness.services.locales import locale_is_japanese


def user_instructions_inbox_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="user_instruction", kind="user_instruction")


def latest_user_instruction_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="user_instruction", kind="user_instruction")


def progress_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="progress_request", kind="request")


def research_plan_current_work_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="research_plan_current_work_request", kind="request")


def research_plan_contract_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="research_plan_contract_request", kind="request")


def task_spec_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="task_spec_request", kind="request")


def data_framing_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="data_framing_request", kind="request")


def research_plan_artifact_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="research_plan_artifact_rejection", kind="rejection")


def research_plan_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="research_plan_request_rejection", kind="rejection")


def notebook_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="notebook_request_rejection", kind="rejection")


def notebook_runtime_failure_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="notebook_runtime_failure", kind="observation")


def notebook_context_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="notebook_context_request", kind="request")


def notebook_quality_repair_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="notebook_quality_repair", kind="request")


def session_output_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="session_output_rejection", kind="rejection")


def build_default_goal_text(db: Session, project: Project) -> str:
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc()).limit(8)
        ).all()
    )
    target_text = project.target_column or "not fixed; infer or construct the prediction objective from evidence"
    dataset_lines = [
        f"- {dataset.id}: rows={dataset.row_count}, columns={dataset.column_count}, source={dataset.source_ref or dataset.artifact_id}"
        for dataset in datasets
    ]
    return "\n".join(
        [
            f"Run the main Tablex autonomous data-science session for project `{project.name}` ({project.id}).",
            "",
            "You are Codex acting as the execution engine inside Tablex. Tablex must not constrain you to fixed recipes.",
            "Use the provided assets, Skills, and data-science workflow as context and guardrails, then decide the project-specific approach yourself.",
            "",
            "Primary objective:",
            f"- Current target/objective hint: {target_text}",
            "- Understand the data deeply, including relational structure when present.",
            "- Define or refine the prediction/analysis objective. It may be supervised, derived, aggregate, time-dependent, distributional, unsupervised, or optimization-coupled if the evidence supports it.",
            "- Design reliable evaluation before trusting modeling results.",
            "- Reason about the data-generating world before treating the dataset as a matrix: which people, organizations, machines, markets, policies, physical processes, incentives, constraints, and decisions produced the records; what is knowable at prediction time; and how the prediction will be used.",
            "- Use imagination to form mechanisms that generic AutoML would miss, while clearly separating measured facts, source-backed knowledge, plausible hypotheses, and unverified assumptions. Turn promising mechanisms into falsifiable, prediction-time-safe feature and evaluation work.",
            "- Build strong evidence-backed baselines, then pursue material project-specific improvements without forcing a predefined recipe.",
            "- Treat modeling as an iterative investigation, not a one-pass table merge and boosted-tree fit. Use domain knowledge and measured data behavior to form feature hypotheses; inspect raw entity histories or representative errors when the data supports it; test feature families with fold-consistent ablations; and let the results determine the next analysis.",
            "- Treat relational rows as domain events and states rather than only DataFrame columns. When possible, reconstruct entity timelines, intervals, ordering, overlap or concurrency, state transitions, recurrence, and changes in behavior, and turn the resulting mechanisms into testable features.",
            "- Treat global group-by count/mean/min/max followed by a flat merge as a lossy relational baseline. Use domain hypotheses to decide when conditional distributions, tails, recency windows, period deltas, trends, change points, event spacing, durations, sequences, nested histories, or cross-table consistency preserve important signal.",
            "- Go beyond generic counts and global aggregates when the evidence supports richer structure. Consider prediction-time-safe ratios, differences, recency, frequency, trend, volatility, sequence/state-transition, cross-table consistency, missingness-as-process, and interaction hypotheses, choosing only those that make sense for this project.",
            "- Compare serious modeling and feature-set alternatives under the same evaluation contract. Diagnose where gains and failures come from with out-of-fold predictions, slices, calibration, stability, and error analysis before declaring the modeling work complete.",
            "- Run hypothesis iterations autonomously: state a mechanism, test the smallest coherent feature family on unchanged folds, quantify the out-of-fold delta and uncertainty, inspect affected slices or errors, record support/rejection/revision, and choose the next hypothesis from that evidence. Do not substitute routine hyperparameter search for this loop.",
            "- Keep disposable ablations in a structured experiment ledger; promote serious distinct candidates to registered runs and complete their UI prediction runtimes. Do not register every probe as a Leaderboard row, and never drop a run after registration.",
            "- Build and surface the foundation incrementally. Sanity models, application/main-table baselines, standard relational or temporal baselines, and material evidence-ladder steps are serious candidates, not disposable probes. Finish and register each candidate with its own smoke-tested prediction runtime as soon as its comparable evaluation is ready; do not leave the Leaderboard empty while batching the entire modeling study, final notebook, diagnostics, or optional export packaging.",
            "- Keep each serious candidate vertically complete before moving far ahead: evaluation evidence, ExperimentRun, prediction runtime, and isolated smoke validation. Diagnostics, narrative, and downloadable local training bundles may mature afterward without hiding a usable model. Do not back-load every registration and runtime to the end of a long turn.",
            "- Do not stop merely because one non-trivial model beats an application-only or constant baseline. Stop when further reversible work has low expected information or value, and record the evidence and remaining high-value hypotheses that justify that judgment.",
            "- Do not mark the plan or session complete while your own report, notebook, experiment ledger, diagnostics, or final message identifies a concrete next evidence-driven iteration with material expected information and no hard boundary blocks it. Execute it, revise it from evidence, or show why its expected value became low.",
            "- When prior knowledge could change target definition, validation, features, leakage controls, or modeling choices, do real source-backed research and register findings through Tablex's research request channel, or explicitly register a no-findings decision after searching.",
            "- Produce useful marimo notebooks and reports for humans, not placeholder summaries.",
            "- Keep the human deliverables distinct: author a dedicated data-understanding/EDA notebook before modeling; author one run-specific model notebook for every serious Leaderboard candidate; and author a project-level solution writeup after the evidence and stopping judgment are synthesized.",
            "- A model-comparison notebook is useful supplementary evidence, but it does not replace each model's own notebook. Each run-specific model notebook must explain that run's feature engineering and preprocessing, training configuration, unchanged-fold/OOF evaluation, diagnostics and error behavior, prediction input contract, and limitations from registered evidence.",
            "- The solution writeup must connect objective and data semantics, evaluation design, the feature/model evidence ladder, accepted and rejected hypotheses, final selection, inference behavior, limitations, and reproducible next steps. It must be authored from project evidence rather than a harness template.",
            "- Save every important output under `outputs/`, `reports/`, `notebooks/`, or `artifacts/` so Tablex can register it.",
            "- Keep moving in Full Auto. Ask questions when useful, but if no answer is available, record reversible assumptions and continue. Do not wait for formal approval before doing non-destructive analysis, evaluation design, modeling experiments, diagnostics, notebooks, research, or reports. Defer only destructive, production-write, deployment-grade, secret-exposing, or evaluation-integrity-breaking actions. Use Give Up only as a last resort.",
            "",
            "Current datasets:",
            *(dataset_lines or ["- No dataset snapshot is registered yet; wait for data or explain the missing input."]),
        ]
    )


def write_workspace_inbox_text(
    workspace: Path,
    *,
    kind: str,
    entry_type: str,
    lines: list[str],
    payload: dict[str, Any] | None = None,
    title: str | None = None,
) -> Path | None:
    try:
        return write_inbox_entry(
            workspace,
            kind=kind,
            entry_type=entry_type,
            payload=payload or {},
            content="\n".join(lines).strip() + "\n",
            title=title,
        )
    except (OSError, ValueError):
        return None


def append_user_instruction_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    message: str,
    locale: str | None,
    channel: str = "chat",
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    payload = {
        "schema_version": "tablex_user_instruction.v1",
        "session_id": session.id,
        "project_id": session.project_id,
        "event_id": event.id,
        "event_index": event.event_index,
        "created_at": event.created_at.isoformat(),
        "locale": locale,
        "channel": channel,
        "message": message,
    }
    try:
        write_inbox_entry(
            workspace,
            kind="user_instruction",
            entry_type="user_instruction",
            payload=payload,
            content=message.strip() + "\n",
            title="User instruction",
        )
    except OSError:
        return


def write_progress_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    trigger: str = "stale_progress_update",
    user_message: str | None = None,
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    japanese = locale_is_japanese(locale)
    user_message_excerpt = user_message.strip()[:1200] if isinstance(user_message, str) and user_message.strip() else None
    if trigger == "user_chat_message":
        if japanese:
            message = (
                "ユーザーがAgent Chatで返答を待っています。"
                "`reports/chat_update.md` をユーザーの言語で可能なタイミングですぐ更新してください。"
                "内部の再開処理、inbox/ack確認、プロトコル確認ではなく、今の状況、実際に進めていること、未確定事項、次に見るべき場所を人間にわかる言葉で説明してください。"
            )
        else:
            message = (
                "The user is waiting in Agent Chat. "
                "Update `reports/chat_update.md` in the user's locale as soon as practical. "
                "Do not discuss resume plumbing, inbox/ack checks, or protocol checks; explain the current situation, what is actually moving, remaining uncertainty, and where to look next."
            )
    elif japanese:
        message = (
            "人間向けの進捗説明がしばらく更新されていません。"
            "数分以上かかるコマンドや一括処理をこれから始める場合は実行前に、すでに実行中なら次に制御が戻った時点で、"
            "`reports/chat_update.md` をユーザーの言語で短く更新してください。"
            "複数候補を検証している場合は、全体の完了を待たず、重要な候補と再現可能な推論パイプラインが完成・棄却された節目でも更新してください。"
            "内部の再開処理、inbox/ack確認、プロトコル確認ではなく、ユーザーに見える変更、残る不確実性、次にどこを見るべきかを説明してください。"
        )
    else:
        message = (
            "The human-facing progress update has been quiet for a while. "
            "If a command or batch likely to take several minutes is about to start, update `reports/chat_update.md` concisely in the user's locale before launching it; "
            "if it is already running, update as soon as control returns. "
            "For multi-candidate work, do not wait for the whole batch: update when a meaningful candidate and its reproducible prediction pipeline are completed or rejected. "
            "Do not discuss resume plumbing, inbox/ack checks, or protocol checks; explain visible changes, remaining uncertainty, and where the user should look next."
        )
    lines = [
        "schema_version: tablex_progress_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"trigger: {trigger}",
        "",
        message,
        "",
        *(
            [
                "latest_user_message:",
                user_message_excerpt,
                "",
            ]
            if user_message_excerpt
            else []
        ),
    ]
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="progress_request",
        lines=lines,
        payload={
            "schema_version": "tablex_progress_request.v1",
            "event_index": event.event_index,
            "locale": locale,
            "trigger": trigger,
            "latest_user_message": user_message_excerpt,
        },
        title="Progress update requested",
    )


def write_research_plan_current_work_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    revision: ResearchPlanRevision,
    reason: str = "missing",
    current_node_id: str | None = None,
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    path = research_plan_current_work_request_path(workspace)
    japanese = locale_is_japanese(locale)
    if japanese:
        headline = (
            "Codexの出力が進んでいますが、Research Planの現在地申告が古くなっています。"
            if reason == "stale_after_codex_output"
            else "Codexは動作中ですが、Research Planの現在地がまだ申告されていません。"
        )
        action = (
            "現在取り組んでいる章をCodex自身で判断し、`.tablex/requests/research_plan/` の "
            "`set_current_work` を送ってください。既存の章に合わない場合は、まず `commit_revision` で章を追加・整理し、"
            "その後 `set_current_work` を送ってください。作業は止めずに続けてください。"
        )
    else:
        headline = (
            "Codex output has advanced, but the current Research Plan declaration is stale."
            if reason == "stale_after_codex_output"
            else "Codex is working, but the current Research Plan position has not been declared."
        )
        action = (
            "Decide which chapter you are actually working on and submit `set_current_work` under "
            "`.tablex/requests/research_plan/`. If no existing chapter fits, first submit `commit_revision` "
            "to add or reorganize the chapter, then submit `set_current_work`. Keep working; do not stop."
        )
    lines = [
        "schema_version: tablex_research_plan_current_work_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"research_plan_revision_id: {revision.id}",
        f"research_plan_revision_index: {revision.revision_index}",
        f"reason: {reason}",
        f"current_node_id: {current_node_id or ''}",
        "",
        headline,
        "",
        action,
        "",
        "Tool request path:",
        ".tablex/requests/research_plan/<new_request_id>.json",
        "",
        "Expected operation:",
        "set_current_work",
        "",
        "If a revised chapter structure is needed first:",
        "commit_revision",
        "",
        "After writing the request, read the matching ack under `.tablex/acks/research_plan/`. "
        "If the ack fails, revise the JSON and resubmit with a new request_id.",
    ]
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="research_plan_current_work_request",
        lines=lines,
        payload={
            "schema_version": "tablex_research_plan_current_work_request.v1",
            "event_index": event.event_index,
            "locale": locale,
            "research_plan_revision_id": revision.id,
            "research_plan_revision_index": revision.revision_index,
            "reason": reason,
            "current_node_id": current_node_id,
        },
        title="ResearchPlan current work requested",
    )


def write_task_spec_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    project_id: str,
    primary_dataset_snapshot_id: str,
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    lines = [
        "schema_version: tablex_task_spec_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"project_id: {project_id}",
        f"primary_dataset_snapshot_id: {primary_dataset_snapshot_id}",
        "",
        "A primary DatasetSnapshot is registered, but no TaskSpec artifact is registered for this project yet.",
        "After data understanding, submit a fixed JSON request under `.tablex/requests/data/` with operation `commit_task_spec`.",
        "",
        "Required TaskSpec contents:",
        "- objective_text: the project objective as a user statement or a provisional Codex assumption",
        "- task_shape: one of the protocol enum values",
        "- granularity: row_unit and optional aggregation",
        "- targets: an array; use `targets: []` for clustering, anomaly detection, exploratory analysis, or other no-explicit-target work",
        "- status: provisional or user_confirmed",
        "",
        "Do not stop reversible analysis while preparing this request.",
        "Do not infer the task solely from column names.",
        "If the first TaskSpec is provisional, keep assumptions explicit and continue until a user answer or stronger project evidence revises it.",
    ]
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="task_spec_request",
        lines=lines,
        payload={
            "schema_version": "tablex_task_spec_request.v1",
            "event_index": event.event_index,
            "locale": locale,
            "project_id": project_id,
            "primary_dataset_snapshot_id": primary_dataset_snapshot_id,
            "requested_operation": "commit_task_spec",
            "targets_empty_allowed": True,
        },
        title="TaskSpec request",
    )


def write_data_framing_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    project_id: str,
    dataset_snapshot_ids: list[str],
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    dataset_line = ", ".join(dataset_snapshot_ids)
    lines = [
        "schema_version: tablex_data_framing_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"project_id: {project_id}",
        f"dataset_snapshot_ids: {dataset_line}",
        "",
        "DatasetSnapshot records are available, but the project has no primary DatasetSnapshot and no TaskSpec yet.",
        "After data understanding, submit fixed JSON requests under `.tablex/requests/data/` for the registered data framing.",
        "",
        "Use these operations when warranted by the evidence:",
        "- set_primary_table: if one existing DatasetSnapshot is the row-grain table",
        "- register_derived_table: if the row-grain table should be derived before becoming primary",
        "- commit_task_spec: when the objective, granularity, and task shape are ready to register",
        "",
        "For non-supervised or exploratory task shapes, `targets: []` is valid.",
        "Do not stop reversible analysis while preparing these requests.",
        "Do not infer the task solely from column names.",
    ]
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="data_framing_request",
        lines=lines,
        payload={
            "schema_version": "tablex_data_framing_request.v1",
            "event_index": event.event_index,
            "locale": locale,
            "project_id": project_id,
            "dataset_snapshot_ids": dataset_snapshot_ids,
            "requested_operations": ["set_primary_table", "register_derived_table", "commit_task_spec"],
            "targets_empty_allowed": True,
        },
        title="Data framing request",
    )


def research_plan_contract_issue_hash(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    stable_issues = [
        {
            "code": str(issue.get("code") or ""),
            "path": str(issue.get("path") or ""),
            "message": str(issue.get("message") or ""),
            "severity": str(issue.get("severity") or "error"),
        }
        for issue in issues
        if isinstance(issue, dict)
    ]
    return hashlib.sha1(dumps_json(stable_issues).encode("utf-8")).hexdigest()


def latest_research_plan_contract_request_event(
    db: Session,
    *,
    session_id: str,
    issue_hash: str,
) -> AgentTranscriptEvent | None:
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "research_plan_contract_revision_requested",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(50)
        ).all()
    )
    for event in events:
        payload = loads_json(event.payload_json, {})
        if payload.get("issue_hash") == issue_hash:
            return event
    return None


def write_research_plan_contract_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    validation: dict[str, Any],
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    path = research_plan_contract_request_path(workspace)
    japanese = locale_is_japanese(locale)
    issues = [issue for issue in validation.get("issues", []) if isinstance(issue, dict)]
    if japanese:
        headline = (
            "現在のResearchPlanは表示できますが、構造化された実行台帳としては再申告が必要です。"
            "作業を止めず、`.tablex/requests/research_plan/` の `commit_revision` で章粒度のplanを再commitしてください。"
        )
        action = (
            "トップレベルは最大7件のchapter/phase/milestoneにまとめ、個別分析、モデル試行、診断、"
            "Notebookやレポート断片はsubtasks、completion_evidence、ExperimentRun、artifact linkへ移してください。"
        )
    else:
        headline = (
            "The current ResearchPlan is visible, but it needs a validated re-commit as the structured execution ledger. "
            "Do not stop the project; submit a chapter-level plan with `.tablex/requests/research_plan/` `commit_revision`."
        )
        action = (
            "Keep at most 7 top-level chapter/phase/milestone nodes. Move individual analyses, model attempts, diagnostics, "
            "notebook/report sections, and detailed comparisons into subtasks, completion_evidence, ExperimentRuns, or artifact links."
        )
    lines = [
        "schema_version: tablex_research_plan_contract_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"issue_count: {validation.get('issue_count', 0)}",
        f"error_count: {validation.get('error_count', 0)}",
        f"warning_count: {validation.get('warning_count', 0)}",
        "",
        headline,
        "",
        action,
        "",
        "Tool request path:",
        ".tablex/requests/research_plan/<new_request_id>.json",
        "",
        "Expected operation:",
        "commit_revision",
        "",
        "After writing the request, read the matching ack under `.tablex/acks/research_plan/`. "
        "If the ack fails, revise the JSON and resubmit with a new request_id.",
        "",
        "Top issues:",
    ]
    for issue in issues[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="research_plan_contract_request",
        lines=lines,
        payload={
            "schema_version": "tablex_research_plan_contract_request.v1",
            "event_index": event.event_index,
            "locale": locale,
            "validation": validation,
        },
        title="ResearchPlan contract revision requested",
    )


def write_research_plan_artifact_rejection_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    artifact: Artifact,
    workspace_relative_path: str,
    issues: list[dict[str, Any]],
) -> None:
    if not session.workspace_path:
        return
    workspace = resolve_runtime_data_path(session.workspace_path)
    path = research_plan_artifact_rejection_path(workspace)
    lines = [
        "schema_version: tablex_research_plan_artifact_rejection.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"artifact_id: {artifact.id}",
        f"workspace_relative_path: {workspace_relative_path}",
        "",
        "The ResearchPlan artifact was registered, but it was not accepted as the canonical ResearchPlan revision.",
        "Revise the plan through the validated request channel instead of assuming this file is the visible plan.",
        "",
        "Tool request path:",
        ".tablex/requests/research_plan/<new_request_id>.json",
        "",
        "Expected operation:",
        "commit_revision",
        "",
        "After writing the request, read the matching ack under `.tablex/acks/research_plan/`. "
        "If the ack fails, revise the JSON and resubmit with a new request_id.",
        "",
        "Top issues:",
    ]
    for issue in issues[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="research_plan_artifact_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_research_plan_artifact_rejection.v1",
            "event_index": event.event_index,
            "artifact_id": artifact.id,
            "workspace_relative_path": workspace_relative_path,
            "issues": issues,
        },
        title="ResearchPlan artifact rejected",
    )


def write_research_plan_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
    issues: list[dict[str, Any]] | None = None,
) -> None:
    path = research_plan_request_rejection_path(workspace)
    lines = [
        "schema_version: tablex_research_plan_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The ResearchPlan request was rejected by Tablex validation and did not change the canonical plan.",
        "Read the ack JSON, repair the fixed request payload, and resubmit with a new request_id.",
        "",
        "Important:",
        "- Do not continue as if the rejected ResearchPlan was accepted.",
        "- If a done node claims notebook/report/artifact outputs, first register the asset and reference its artifact_id or ingested workspace_path.",
        "- If a done node claims experiment_run or leaderboard_entry outputs, first register runs through `.tablex/requests/experiments/` and reference a registered experiment_run_id.",
        "",
        "Error:",
        error_message,
        "",
        "Top issues:",
    ]
    for issue in (issues or [])[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="research_plan_request_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_research_plan_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
            "issues": issues or [],
        },
        title="ResearchPlan request rejected",
    )



def write_notebook_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
    issues: list[dict[str, Any]] | None = None,
) -> None:
    path = notebook_request_rejection_path(workspace)
    lines = [
        "schema_version: tablex_notebook_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The Notebook request was rejected by Tablex validation and did not update Chat links, ResearchPlan evidence, or contextual Data/Leaderboard/Assets links.",
        "Read the ack JSON, repair the fixed request payload or the notebook source, and resubmit under `.tablex/requests/notebooks/` with a new request_id.",
        "",
        "Use this request channel after saving a marimo notebook so Tablex can register it as an asset, attach lineage, and make it open through native marimo from the related Chat, ResearchPlan node, Dataset, Run, Model, and Assets views.",
        "",
        "Error:",
        error_message,
    ]
    if issues:
        lines.extend(["", "Top issues:"])
        for issue in issues[:8]:
            lines.extend(
                [
                    f"- code: {issue.get('code')}",
                    f"  pointer: {issue.get('pointer')}",
                    f"  message: {issue.get('message')}",
                    f"  fix: {issue.get('fix')}",
                ]
            )
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="notebook_request_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_notebook_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
            "issues": issues or [],
        },
        title="Notebook request rejected",
    )


def write_notebook_runtime_failure_to_workspace_inbox(
    workspace: Path,
    *,
    notebook_artifact: Artifact,
    error_message: str,
) -> None:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    workspace_path = metadata.get("workspace_relative_path")
    if not isinstance(workspace_path, str) or not workspace_path.strip():
        workspace_path = metadata.get("source_path") if isinstance(metadata.get("source_path"), str) else ""
    path = notebook_runtime_failure_path(workspace)
    lines = [
        "schema_version: tablex_notebook_runtime_failure.v1",
        f"notebook_artifact_id: {notebook_artifact.id}",
        f"notebook_name: {notebook_artifact.name}",
        f"workspace_path: {workspace_path or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        "",
        "Tablex registered the Codex-authored marimo notebook source, but native marimo reported a runtime problem. The source remains the canonical artifact.",
        "Repair the notebook source if native marimo reports a runtime error, then write a fixed request under `.tablex/requests/notebooks/` with `schema_version: \"tablex_notebook_request.v1\"` and operation `register_notebook`.",
        "",
        "Error:",
        error_message,
    ]
    write_workspace_inbox_text(
        workspace,
        kind="observation",
        entry_type="notebook_runtime_failure",
        lines=lines,
        payload={
            "schema_version": "tablex_notebook_runtime_failure.v1",
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_name": notebook_artifact.name,
            "workspace_path": workspace_path,
            "error_message": error_message,
        },
        title="Notebook runtime failure",
    )


def write_notebook_context_request_to_workspace_inbox(
    workspace: Path,
    *,
    notebook_artifacts: list[Artifact],
) -> None:
    if not notebook_artifacts:
        return
    path = notebook_context_request_path(workspace)
    lines = [
        "schema_version: tablex_notebook_context_request.v1",
        f"created_at: {utc_now().isoformat()}",
        "",
        "These native marimo notebook sources are visible in Tablex, but Tablex has not received a validated notebook registration request that declares their project context.",
        "Write fixed JSON requests under `.tablex/requests/notebooks/` with `schema_version: \"tablex_notebook_request.v1\"` and operation `register_notebook`.",
        "Include `artifact_id` or `workspace_path`, `notebook_kind`, and the relevant `research_plan_node_id`, `dataset_snapshot_id`, `run_id`, or `model_version_id`.",
        "Read each ack under `.tablex/acks/notebooks/` before marking the related ResearchPlan node done.",
        "",
        "Pending notebooks:",
    ]
    for artifact in notebook_artifacts[:12]:
        metadata = loads_json(artifact.metadata_json, {})
        workspace_path = str(metadata.get("workspace_relative_path") or "").strip()
        notebook_kind = str(metadata.get("notebook_kind") or "").strip()
        lines.extend(
            [
                f"- artifact_id: {artifact.id}",
                f"  name: {artifact.name}",
                f"  workspace_path: {workspace_path or '<unknown>'}",
                f"  current_notebook_kind: {notebook_kind or '<unknown>'}",
            ]
        )
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="notebook_context_request",
        lines=lines,
        payload={
            "schema_version": "tablex_notebook_context_request.v1",
            "notebook_artifact_ids": [artifact.id for artifact in notebook_artifacts[:12]],
        },
        title="Notebook context registration requested",
    )


def write_notebook_quality_repair_to_workspace_inbox(
    workspace: Path,
    *,
    notebook_artifacts: list[Artifact],
) -> None:
    if not notebook_artifacts:
        return
    path = notebook_quality_repair_path(workspace)
    lines = [
        "schema_version: tablex_notebook_quality_repair.v1",
        f"created_at: {utc_now().isoformat()}",
        "",
        "These native marimo notebook sources are registered in Tablex, but their fixed quality_manifest says they are not ready as human-facing analysis deliverables.",
        "Do not mark the related ResearchPlan node complete on notebook evidence alone until the notebook has useful visual diagnostics.",
        "",
        "Repair contract:",
        "- Keep the notebook as native marimo Python source.",
        "- Add meaningful figures or visual diagnostics generated from Tablex dataset_access links or registered artifacts.",
        "- Resubmit a fixed `.tablex/requests/notebooks/` register_notebook request with `schema_version: \"tablex_notebook_request.v1\"`.",
        "- Include a `quality_manifest` with `figure_count > 0`, non-empty `key_findings`, `read_order`, `data_sources_used`, and `limitations`.",
        "- For model-diagnostics notebooks, include `quality_manifest.model_diagnostics.checks` for permutation_importance, native_feature_importance, partial_dependence, and shap. Use `included` with evidence when present; otherwise use not_applicable, needs_model_artifact, needs_dependency, or deferred with a reason.",
        "- Read the matching ack before treating the notebook as ready.",
        "",
        "Notebooks needing repair:",
    ]
    for artifact in notebook_artifacts[:12]:
        metadata = loads_json(artifact.metadata_json, {})
        quality = notebook_quality_feedback_from_metadata(artifact)
        workspace_path = str(metadata.get("workspace_relative_path") or "").strip()
        notebook_kind = str(metadata.get("notebook_kind") or "").strip()
        lines.extend(
            [
                f"- artifact_id: {artifact.id}",
                f"  name: {artifact.name}",
                f"  workspace_path: {workspace_path or '<unknown>'}",
                f"  notebook_kind: {notebook_kind or '<unknown>'}",
                f"  quality_status: {quality.get('status')}",
                f"  declared_figure_count: {quality.get('figure_count')}",
                f"  declared_key_finding_count: {quality.get('key_finding_count')}",
                f"  declared_read_order_count: {quality.get('read_order_count')}",
                f"  message: {quality.get('message') or ''}",
            ]
        )
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="notebook_quality_repair",
        lines=lines,
        payload={
            "schema_version": "tablex_notebook_quality_repair.v1",
            "notebook_artifact_ids": [artifact.id for artifact in notebook_artifacts[:12]],
        },
        title="Notebook quality repair requested",
    )


def write_session_output_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    workspace_relative_path: str,
    reason: str,
) -> None:
    path = session_output_rejection_path(workspace)
    lines = [
        "schema_version: tablex_session_output_rejection.v1",
        f"workspace_relative_path: {workspace_relative_path}",
        f"reason: {reason}",
        f"created_at: {utc_now().isoformat()}",
        "",
        "Tablex rejected this workspace output and did not register it as a project artifact.",
        "Do not continue as if this file is available in the UI, Chat, Assets, ResearchPlan, or Notebook surfaces.",
        "",
        "If this was meant to be a notebook, save a native marimo Python source file under `notebooks/` or `outputs/notebooks/`, then register it with `.tablex/requests/notebooks/`.",
        "If this was meant to be model comparison evidence, register runs through `.tablex/requests/experiments/` or write structured `model_results.v1` JSON.",
        "",
        "Rejected output:",
        workspace_relative_path,
    ]
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="session_output_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_session_output_rejection.v1",
            "workspace_relative_path": workspace_relative_path,
            "reason": reason,
        },
        title="Workspace output rejected",
    )
