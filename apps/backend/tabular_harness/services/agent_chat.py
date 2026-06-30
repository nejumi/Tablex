from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    ExperimentRun,
    Job,
    Project,
    SplitManifest,
)
from tabular_harness.services.agent_task_planner import AgentTaskPlanResult, plan_project_agent_task
from tabular_harness.services.analysis_notebooks import (
    build_project_notebook_index,
    create_data_understanding_notebook,
)
from tabular_harness.services.approach import latest_project_artifact, store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.baseline import (
    create_baseline_strategy_plan,
    normalize_model_candidate_name,
)
from tabular_harness.services.data_quality import analyze_dataset_quality
from tabular_harness.services.decision_reporting import create_decision_report_v1
from tabular_harness.services.diagnostics import analyze_run_diagnostics
from tabular_harness.services.eda_review import create_dataset_eda_review
from tabular_harness.services.evaluation import (
    create_default_evaluation_candidates,
    create_evaluation_scenario_comparison,
    spec_to_dict,
    write_candidates_artifact,
    write_spec_artifact,
)
from tabular_harness.services.experiment_lifecycle import (
    compare_project_experiments,
    draft_run_report,
)
from tabular_harness.services.jobs import (
    create_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)
from tabular_harness.services.metric_preferences import (
    normalize_metric_name,
    record_metric_preference,
)
from tabular_harness.services.model_diagnostics_artifacts import (
    materialize_model_diagnostics_artifacts,
)
from tabular_harness.services.notebook_authoring import create_notebook_authoring_brief
from tabular_harness.services.project_guidance import build_project_guidance
from tabular_harness.services.agent_response_composer import compose_agent_chat_response
from tabular_harness.services.reporting import leaderboard_sort_key
from tabular_harness.services.result_notebook_evidence import (
    prepare_result_notebook_evidence,
    result_notebook_evidence_job_output,
)

SUPPORTED_METRICS = {
    "roc_auc": {"aliases": ["roc auc", "roc-auc", "roc_auc", "auc"], "label": "ROC-AUC"},
    "pr_auc": {"aliases": ["pr auc", "pr-auc", "pr_auc", "average precision"], "label": "PR-AUC"},
    "accuracy": {"aliases": ["accuracy"], "label": "accuracy"},
    "macro_f1": {"aliases": ["macro f1", "macro-f1", "macro_f1"], "label": "macro F1"},
    "f1": {"aliases": ["f1", "f1 score"], "label": "F1"},
    "log_loss": {"aliases": ["log loss", "log-loss", "log_loss"], "label": "log loss"},
    "rmse": {"aliases": ["rmse"], "label": "RMSE"},
    "mae": {"aliases": ["mae"], "label": "MAE"},
    "r2": {"aliases": ["r2", "r squared", "r-squared"], "label": "R2"},
}


@dataclass(frozen=True)
class AgentChatTurnResult:
    response: dict[str, Any]
    job: Job
    artifact: Artifact
    planned_agent_task: AgentTaskPlanResult | None = None


def handle_agent_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    message: str,
    locale: str | None = None,
    agent_model: str | None = None,
    utility_model: str | None = None,
) -> AgentChatTurnResult:
    intent = infer_chat_intent(message)
    actions: list[dict[str, Any]] = []
    planned_agent_task: AgentTaskPlanResult | None = None

    if intent["type"] == "set_evaluation_metric":
        actions.extend(apply_metric_preference(db, store=store, project=project, metric=str(intent["metric"])))
        if not any(action["status"] == "applied" for action in actions):
            planned_agent_task = plan_metric_agent_task(
                db,
                store=store,
                project=project,
                job=job,
                message=message,
                metric=str(intent["metric"]),
            )
            actions.append(agent_task_action(planned_agent_task))
    elif intent["type"] == "generate_data_understanding_notebook":
        actions.append(generate_data_understanding_notebook_action(db, store=store, project=project))
    elif intent["type"] == "run_eda_review":
        actions.append(run_eda_review_action(db, store=store, project=project))
    elif intent["type"] == "show_relational_map":
        actions.append(show_relational_map_action(db, project=project))
    elif intent["type"] == "run_data_quality":
        actions.append(run_data_quality_action(db, store=store, project=project))
    elif intent["type"] == "compare_evaluation_scenarios":
        actions.append(compare_evaluation_scenarios_action(db, store=store, project=project))
    elif intent["type"] == "design_evaluation":
        actions.append(design_evaluation_action(db, store=store, project=project))
    elif intent["type"] == "plan_baseline_strategy":
        actions.append(plan_baseline_strategy_action(db, store=store, project=project))
    elif intent["type"] == "run_model_candidates":
        actions.append(
            run_model_candidates_action(
                db,
                store=store,
                project=project,
                model_candidates=[str(item) for item in list_value(intent.get("model_candidates"))],
            )
        )
    elif intent["type"] == "generate_decision_report":
        actions.append(generate_decision_report_action(db, store=store, project=project))
    elif intent["type"] == "show_leaderboard":
        actions.append(show_leaderboard_action(db, project=project))
    elif intent["type"] == "compare_top_runs":
        actions.append(compare_top_runs_action(db, store=store, project=project))
    elif intent["type"] == "post_run_reading_workflow":
        actions.append(post_run_reading_workflow_action(db, store=store, project=project))
    elif intent["type"] == "prepare_result_notebook_evidence":
        actions.append(prepare_result_notebook_evidence_action(db, store=store, project=project))
    elif intent["type"] == "author_analysis_notebook":
        authoring_action = create_notebook_authoring_action(db, store=store, project=project, message=message)
        actions.append(authoring_action)
        planned_agent_task = plan_project_agent_task(
            db,
            store=store,
            project=project,
            job=job,
            objective=(
                f"The user asked: {message}. Write or revise a high-quality, human-facing Tablex analysis notebook "
                "on the fly. Use the latest notebook_authoring_brief, Data Review evidence, project artifacts, "
                "and the tablex-notebook-quality Skill. Do not use a fixed template; choose the narrative and "
                "sections from the evidence."
            ),
            task_type="author_analysis_notebook",
        )
        actions.append(agent_task_action(planned_agent_task))
    elif intent["type"] == "plan_notebook_followup_task":
        planned_agent_task = plan_notebook_followup_agent_task(
            db,
            store=store,
            project=project,
            job=job,
            message=message,
            focus_areas=[str(item) for item in list_value(intent.get("focus_areas"))],
            source_ref=dict_value(intent.get("source_ref")),
        )
        actions.append(notebook_followup_task_action(planned_agent_task, intent))
        if any(
            focus in {"feature_importance", "permutation_importance", "calibration", "threshold", "score_bins", "slice_metrics", "worst_examples"}
            for focus in list_value(intent.get("focus_areas"))
        ):
            actions.append(materialize_top_model_evidence_action(db, store=store, project=project))
    elif intent["type"] == "guide_notebook_review":
        actions.append(
            guide_notebook_review_action(
                db,
                project=project,
                notebook_artifact_id=str(intent["notebook_artifact_id"]) if intent.get("notebook_artifact_id") else None,
            )
        )
    elif intent["type"] == "explain_next_step":
        actions.append(explain_next_step_action(db, project=project))
    else:
        planned_agent_task = plan_project_agent_task(
            db,
            store=store,
            project=project,
            job=job,
            objective=message,
            task_type="implement_prediction_approach",
        )
        actions.append(agent_task_action(planned_agent_task))

    response_locale = response_locale_for_chat(locale, message)
    action_summary = build_action_summary(intent, actions)
    fallback_message = render_assistant_message(intent, actions)
    composition = compose_agent_chat_response(
        project=project,
        user_message=message,
        intent=intent,
        actions=actions,
        action_summary=action_summary,
        locale=response_locale,
        fallback_message=fallback_message,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    token_series = estimate_token_series(message, actions)
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": message,
        "assistant_message": composition.message,
        "intent": intent,
        "actions": actions,
        "action_summary": action_summary,
        "response_brief": composition.brief,
        "response_composer": composition.composer,
        "worker_events": build_worker_events(job, intent, actions, token_series),
        "token_usage": {
            "source": "estimated_until_runner_telemetry",
            "is_estimate": True,
            "series": token_series,
        },
        "next_focus": next_focus_from_actions(actions),
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_chat_turn_{job.id}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "intent_type": intent["type"],
            "action_count": len(actions),
            "token_usage_source": "estimated_until_runner_telemetry",
            "response_locale": response_locale,
            "agent_model": agent_model,
            "utility_model": utility_model,
            "response_composer_mode": composition.composer.get("mode"),
        },
    )
    response["artifact_id"] = artifact.id
    for action in actions:
        target_id = action.get("artifact_id")
        if isinstance(target_id, str):
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact.id,
                to_asset_type="artifact",
                to_asset_id=target_id,
                relation_type="records_chat_action",
            )
    return AgentChatTurnResult(
        response=response,
        job=job,
        artifact=artifact,
        planned_agent_task=planned_agent_task,
    )


def infer_chat_intent(message: str) -> dict[str, Any]:
    normalized = normalize_text(message)
    metric = extract_metric(normalized)
    metric_words = any(word in normalized for word in ["metric", "score", "評価", "指標"])
    set_words = any(word in normalized for word in ["set", "use", "make", "change", "して", "にして", "使"])
    if metric and (metric_words or set_words):
        return {
            "type": "set_evaluation_metric",
            "metric": metric,
            "confidence": 0.9,
            "summary": f"User wants the evaluation metric to be {SUPPORTED_METRICS[metric]['label']}.",
        }
    model_candidates = extract_model_candidates(normalized)
    if model_candidates and is_model_candidate_run_request(normalized):
        labels = ", ".join(model_candidates)
        return {
            "type": "run_model_candidates",
            "metric": None,
            "model_candidates": model_candidates,
            "confidence": 0.88,
            "summary": f"User wants Tablex to train model candidates and add them to the leaderboard: {labels}.",
        }
    notebook_id = extract_notebook_artifact_id(message)
    story_ref = extract_analysis_story_ref(message)
    if is_notebook_authoring_request(normalized):
        return {
            "type": "author_analysis_notebook",
            "metric": None,
            "confidence": 0.88,
            "summary": "User wants Codex to write or revise a high-quality analysis notebook from current evidence.",
        }
    if is_result_notebook_evidence_request(normalized):
        return {
            "type": "prepare_result_notebook_evidence",
            "metric": None,
            "confidence": 0.86,
            "summary": "User wants result-level notebook evidence prepared from the top run.",
        }
    followup_focuses = notebook_followup_focus_areas(normalized)
    if is_notebook_followup_task_request(normalized, has_scoped_source=bool(notebook_id or story_ref)):
        return {
            "type": "plan_notebook_followup_task",
            "metric": None,
            "notebook_artifact_id": notebook_id,
            "source_ref": story_ref or {"source_type": "notebook", "artifact_id": notebook_id},
            "focus_areas": followup_focuses,
            "confidence": 0.86,
            "summary": "User wants a notebook follow-up converted into a controlled diagnostics AgentTaskContract.",
        }
    if notebook_id or story_ref or is_notebook_guide_request(normalized):
        return {
            "type": "guide_notebook_review",
            "metric": None,
            "notebook_artifact_id": notebook_id,
            "confidence": 0.82,
            "summary": "User wants interactive guidance for reading notebook evidence.",
        }
    if is_notebook_request(normalized):
        return {
            "type": "generate_data_understanding_notebook",
            "metric": None,
            "confidence": 0.78,
            "summary": "User wants Tablex to generate notebook evidence inside the workbench.",
        }
    if is_eda_review_request(normalized):
        return {
            "type": "run_eda_review",
            "metric": None,
            "confidence": 0.84,
            "summary": "User wants Tablex to run a controlled EDA/Data Review inside the workbench.",
        }
    if is_relational_map_request(normalized):
        return {
            "type": "show_relational_map",
            "metric": None,
            "confidence": 0.82,
            "summary": "User wants Tablex to show or collect relational/ER diagram evidence inside the workbench.",
        }
    if is_data_quality_request(normalized):
        return {
            "type": "run_data_quality",
            "metric": None,
            "confidence": 0.82,
            "summary": "User wants Tablex to review data quality and risk inside the harness.",
        }
    if is_evaluation_compare_request(normalized):
        return {
            "type": "compare_evaluation_scenarios",
            "metric": None,
            "confidence": 0.82,
            "summary": "User wants Tablex to compare evaluation scenarios before locking a split.",
        }
    if is_evaluation_design_request(normalized):
        return {
            "type": "design_evaluation",
            "metric": None,
            "confidence": 0.8,
            "summary": "User wants Tablex to draft evaluation candidates.",
        }
    if is_baseline_strategy_request(normalized):
        return {
            "type": "plan_baseline_strategy",
            "metric": None,
            "confidence": 0.8,
            "summary": "User wants a flexible baseline strategy plan, not a fixed AutoML recipe.",
        }
    if is_post_run_workflow_request(normalized):
        return {
            "type": "post_run_reading_workflow",
            "metric": None,
            "confidence": 0.84,
            "summary": "User wants Tablex to turn top-run evidence into diagnostics, reports, and a decision-readable post-run summary.",
        }
    if is_decision_report_request(normalized):
        return {
            "type": "generate_decision_report",
            "metric": None,
            "confidence": 0.78,
            "summary": "User wants Tablex to synthesize the current project evidence into a decision report.",
        }
    if is_compare_top_runs_request(normalized):
        return {
            "type": "compare_top_runs",
            "metric": None,
            "confidence": 0.82,
            "summary": "User wants Tablex to compare current run evidence before reading leaderboard claims.",
        }
    if is_leaderboard_request(normalized):
        return {
            "type": "show_leaderboard",
            "metric": None,
            "confidence": 0.78,
            "summary": "User wants Tablex to show the leaderboard reading surface.",
        }
    if is_next_step_request(normalized):
        return {
            "type": "explain_next_step",
            "metric": None,
            "confidence": 0.76,
            "summary": "User wants guidance on what to inspect or do next.",
        }
    return {
        "type": "plan_agent_task",
        "metric": None,
        "confidence": 0.62,
        "summary": "User request should be handled as a scoped AgentTaskContract until a safer direct action is available.",
    }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def extract_metric(normalized: str) -> str | None:
    comparable = normalized.replace("ー", "-").replace("_", " ").replace("-", " ")
    for metric, config in SUPPORTED_METRICS.items():
        for alias in config["aliases"]:
            comparable_alias = alias.replace("_", " ").replace("-", " ")
            if comparable_alias in comparable:
                return metric
    normalized_metric = normalize_metric_name(normalized)
    if normalized_metric in SUPPORTED_METRICS:
        return normalized_metric
    return None


def extract_model_candidates(normalized: str) -> list[str]:
    candidates: list[str] = []
    comparable = normalized.replace("ー", "-").replace("_", " ").replace("-", " ")
    checks = [
        ("lightgbm", ["lightgbm", "lgbm", "light gbm"]),
        ("logistic_regression", ["logisticregression", "logistic regression", "logistic", "logreg"]),
        ("xgboost", ["xgboost", "xgb", "xg boost"]),
    ]
    for canonical, aliases in checks:
        if any(alias in comparable for alias in aliases) and canonical not in candidates:
            candidates.append(canonical)
    normalized_candidate = normalize_model_candidate_name(normalized)
    if normalized_candidate and normalized_candidate not in candidates:
        candidates.append(normalized_candidate)
    return candidates


def is_model_candidate_run_request(normalized: str) -> bool:
    return any(
        word in normalized
        for word in [
            "train",
            "fit",
            "run",
            "add",
            "leaderboard",
            "リーダーボード",
            "学習",
            "訓練",
            "回し",
            "回して",
            "追加",
        ]
    )


def is_notebook_request(normalized: str) -> bool:
    return ("notebook" in normalized or "ノートブック" in normalized) and any(
        word in normalized for word in ["generate", "create", "make", "作", "生成", "出し", "作って"]
    )


def is_eda_review_request(normalized: str) -> bool:
    has_eda_word = any(
        word in normalized
        for word in [
            "eda",
            "data review",
            "data understanding review",
            "visualization",
            "visualize",
            "plot",
            "chart",
            "可視化",
            "データレビュー",
            "分析レビュー",
            "探索",
            "探索的",
        ]
    )
    has_action_word = any(
        word in normalized
        for word in ["run", "generate", "create", "make", "show", "作", "生成", "出し", "やって", "して", "見せ"]
    )
    return has_eda_word and has_action_word


def is_relational_map_request(normalized: str) -> bool:
    has_relational_word = any(
        word in normalized
        for word in [
            "er diagram",
            "erd",
            "relationship map",
            "relational map",
            "schema diagram",
            "join graph",
            "table graph",
            "relational preview",
            "relationships",
            "relationship",
            "リレーション",
            "関係図",
            "er図",
            "er 図",
            "スキーマ図",
        ]
    )
    has_action_word = any(
        word in normalized
        for word in ["show", "view", "visualize", "preview", "upload", "import", "見せ", "表示", "可視化", "アップロード", "取り込"]
    )
    return has_relational_word and has_action_word


def is_data_quality_request(normalized: str) -> bool:
    has_quality_word = any(
        word in normalized
        for word in [
            "data quality",
            "quality gate",
            "quality check",
            "check quality",
            "missingness",
            "leakage risk",
            "品質",
            "データ品質",
            "欠損",
            "リーク",
        ]
    )
    has_action_word = any(
        word in normalized
        for word in ["run", "check", "review", "analyze", "analyse", "検査", "確認", "見て", "レビュー", "して"]
    )
    return has_quality_word and has_action_word


def is_evaluation_compare_request(normalized: str) -> bool:
    has_evaluation_word = any(word in normalized for word in ["evaluation", "split", "validation", "評価", "分割"])
    has_compare_word = any(
        word in normalized
        for word in ["compare", "scenario", "random", "stratified", "time split", "group split", "比較", "シナリオ"]
    )
    has_action_word = any(word in normalized for word in ["compare", "design", "review", "作", "生成", "比較", "見て", "して"])
    return has_evaluation_word and has_compare_word and has_action_word


def is_evaluation_design_request(normalized: str) -> bool:
    has_evaluation_word = any(
        word in normalized
        for word in ["evaluation design", "evaluation", "validation design", "split design", "評価設計", "評価", "分割設計"]
    )
    has_action_word = any(
        word in normalized
        for word in ["design", "create", "generate", "draft", "plan", "作", "生成", "設計", "考えて", "して"]
    )
    return has_evaluation_word and has_action_word


def is_baseline_strategy_request(normalized: str) -> bool:
    has_baseline_word = any(
        word in normalized
        for word in [
            "baseline",
            "xgboost",
            "modeling strategy",
            "model strategy",
            "strong baseline",
            "ベースライン",
            "モデル戦略",
            "モデリング",
        ]
    )
    has_action_word = any(
        word in normalized
        for word in ["plan", "design", "create", "generate", "run", "作", "生成", "設計", "考えて", "して"]
    )
    return has_baseline_word and has_action_word


def is_decision_report_request(normalized: str) -> bool:
    has_report_word = any(
        word in normalized
        for word in ["decision report", "project report", "report", "summary", "synthesize", "レポート", "サマリ", "まとめ"]
    )
    has_action_word = any(
        word in normalized
        for word in ["generate", "create", "draft", "write", "make", "show", "作", "生成", "書", "まとめ", "見せ", "して"]
    )
    return has_report_word and has_action_word


def is_leaderboard_request(normalized: str) -> bool:
    has_leaderboard_word = any(
        word in normalized
        for word in ["leaderboard", "leader board", "ranking", "rankings", "リーダーボード", "ランキング", "順位"]
    )
    has_action_word = any(
        word in normalized for word in ["show", "open", "read", "inspect", "見せ", "表示", "開", "見る", "見たい", "確認"]
    )
    return has_leaderboard_word and has_action_word


def is_compare_top_runs_request(normalized: str) -> bool:
    has_run_word = any(
        word in normalized
        for word in ["run", "runs", "experiment", "experiments", "leaderboard", "実験", "run", "上位", "トップ"]
    )
    has_compare_word = any(
        word in normalized for word in ["compare", "comparison", "best", "top", "rank", "比較", "比べ", "上位", "トップ"]
    )
    return has_run_word and has_compare_word


def is_post_run_workflow_request(normalized: str) -> bool:
    has_run_or_result_word = any(
        word in normalized
        for word in [
            "post-run",
            "post run",
            "top run",
            "leaderboard",
            "diagnostics",
            "diagnostic",
            "result",
            "results",
            "run",
            "上位run",
            "結果",
            "診断",
            "リーダーボード",
        ]
    )
    has_report_or_decision_word = any(
        word in normalized
        for word in ["decision report", "report", "summary", "まとめ", "レポート", "判断", "意思決定"]
    )
    has_action_word = any(
        word in normalized
        for word in ["generate", "create", "make", "summarize", "作", "生成", "まとめ", "して", "見せ"]
    )
    return has_run_or_result_word and has_report_or_decision_word and has_action_word


def is_result_notebook_evidence_request(normalized: str) -> bool:
    has_notebook_word = any(word in normalized for word in ["notebook", "ノートブック"])
    has_result_word = any(
        word in normalized
        for word in [
            "result",
            "results",
            "top run",
            "leaderboard",
            "model evidence",
            "model diagnostics",
            "diagnostics",
            "結果",
            "上位run",
            "トップrun",
            "リーダーボード",
            "診断",
        ]
    )
    has_evidence_word = any(
        word in normalized
        for word in [
            "evidence",
            "capture",
            "preview",
            "review",
            "readout",
            "証拠",
            "エビデンス",
            "プレビュー",
            "レビュー",
            "読める",
        ]
    )
    has_action_word = any(
        word in normalized
        for word in ["prepare", "build", "generate", "create", "make", "show", "open", "作", "生成", "準備", "表示", "見せ"]
    )
    return has_notebook_word and has_result_word and has_evidence_word and has_action_word


def is_notebook_authoring_request(normalized: str) -> bool:
    has_notebook = any(word in normalized for word in ["notebook", "ノートブック", "分析", "eda"])
    has_authoring = any(
        word in normalized
        for word in [
            "write",
            "revise",
            "improve",
            "author",
            "draft",
            "quality",
            "heads or tails",
            "grandmaster",
            "書",
            "改稿",
            "改善",
            "本気",
            "良い",
            "高品質",
            "kaggle",
        ]
    )
    return has_notebook and has_authoring


def is_next_step_request(normalized: str) -> bool:
    return any(phrase in normalized for phrase in ["next", "次", "見るべき", "何を見", "what should"]) and any(
        word in normalized for word in ["step", "見る", "do", "すべき", "focus", "フォーカス"]
    )


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_notebook_artifact_id(message: str) -> str | None:
    match = re.search(r"\[notebook:([^\]]+)\]", message)
    return match.group(1).strip() if match else None


def extract_analysis_story_ref(message: str) -> dict[str, str | None] | None:
    match = re.search(r"\[analysis-story(?::([^:\]]+))?(?::([^\]]+))?\]", message)
    if not match:
        return None
    return {
        "source_type": match.group(1).strip() if match.group(1) else None,
        "artifact_id": match.group(2).strip() if match.group(2) else None,
    }


def notebook_followup_focus_areas(normalized: str) -> list[str]:
    focus_map = {
        "feature_importance": ["feature importance", "importance", "重要度", "変数重要度", "特徴量重要度"],
        "permutation_importance": ["permutation", "permutation importance"],
        "partial_dependence": ["partial dependence", "pdp", "dependence"],
        "calibration": ["calibration", "calibrate", "キャリブレーション", "較正"],
        "threshold": ["threshold", "閾値", "しきい値"],
        "score_bins": ["score-bin", "score bin", "score bins", "bin interpretation", "スコア"],
        "slice_metrics": ["slice", "slices", "segment", "group", "スライス", "セグメント"],
        "worst_examples": ["worst", "failure", "error example", "bad example", "失敗", "誤分類", "ワースト"],
        "diagnostics": ["diagnostic", "diagnostics", "診断"],
    }
    focuses = [
        focus
        for focus, aliases in focus_map.items()
        if any(alias in normalized for alias in aliases)
    ]
    if len(focuses) > 1:
        focuses = [focus for focus in focuses if focus != "diagnostics"]
    return focuses


def is_notebook_followup_task_request(normalized: str, *, has_scoped_source: bool) -> bool:
    has_model_evidence_context = bool(notebook_followup_focus_areas(normalized)) and any(
        word in normalized
        for word in [
            "model",
            "run",
            "top run",
            "result",
            "evidence",
            "diagnostic",
            "diagnostics",
            "モデル",
            "run",
            "結果",
            "根拠",
            "診断",
        ]
    )
    if (
        not has_scoped_source
        and not has_model_evidence_context
        and not any(word in normalized for word in ["notebook", "ノートブック", "analysis story"])
    ):
        return False
    has_followup_focus = bool(notebook_followup_focus_areas(normalized))
    asks_for_materialization = any(
        word in normalized
        for word in [
            "add",
            "create",
            "generate",
            "materialize",
            "build",
            "inspect",
            "review",
            "agenttask",
            "agent task",
            "contract",
            "追加",
            "作",
            "生成",
            "出し",
            "見て",
            "調べ",
            "レビュー",
        ]
    )
    return has_followup_focus and asks_for_materialization


def is_notebook_guide_request(normalized: str) -> bool:
    if "notebook" not in normalized and "ノートブック" not in normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "read first",
            "inspect",
            "guide",
            "review",
            "figure",
            "evidence",
            "見る",
            "どこ",
            "何を見",
            "ガイド",
        ]
    )


def generate_data_understanding_notebook_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> dict[str, Any]:
    result = create_data_understanding_notebook(db, store=store, project=project)
    return {
        "type": "generate_data_understanding_notebook",
        "status": "applied",
        "label": "Generated a Data Understanding notebook",
        "target_tab": "Notebooks",
        "target_anchor": "analysis-story",
        "detail": "Created notebook source, HTML preview, report, manifest, and lineage inside Tablex.",
        "artifact_id": result.notebook_artifact.id,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [result.report.id],
    }


def run_eda_review_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> dict[str, Any]:
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        return {
            "type": "run_eda_review",
            "status": "needs_review",
            "label": "Upload a dataset before running Data Review",
            "target_tab": "Data",
            "target_anchor": "dataset-upload",
            "detail": "Tablex needs a DatasetSnapshot before it can compute EDA figures, findings, and target relationships.",
        }
    result = create_dataset_eda_review(db, store=store, dataset=dataset)
    return {
        "type": "run_eda_review",
        "status": "applied",
        "label": "Ran a controlled Data Review",
        "target_tab": "Notebooks",
        "target_anchor": "analysis-story",
        "detail": (
            "Created a Data Review with DuckDB-derived distributions, target relationships, findings, "
            "SVG figures, an HTML narrative, report, evidence, insight, lineage, and Codex next prompts."
        ),
        "artifact_id": result.html_artifact.id,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [result.report.id, result.evidence.id, result.insight.id],
    }


def show_relational_map_action(db: Session, *, project: Project) -> dict[str, Any]:
    relational_catalog = latest_project_artifact(db, project.id, "relational_catalog")
    schema_hint = latest_project_artifact(db, project.id, "relational_schema_hint")
    report = latest_project_artifact(db, project.id, "relational_schema_hint_report")
    if relational_catalog:
        return {
            "type": "show_relational_map",
            "status": "explained",
            "label": "Open the relational map",
            "target_tab": "Data",
            "target_anchor": "relational-map",
            "detail": (
                "A RelationalCatalog is available. The Data tab shows the ER-style map first, with raw catalog JSON "
                "folded as supporting detail."
            ),
            "artifact_id": relational_catalog.id,
            "artifact_ids": [artifact.id for artifact in [relational_catalog, schema_hint, report] if artifact],
        }
    if schema_hint:
        return {
            "type": "show_relational_map",
            "status": "explained",
            "label": "Review the uploaded ER evidence",
            "target_tab": "Data",
            "target_anchor": "relational-map",
            "detail": (
                "An uploaded ER/schema hint is available. The Data tab shows the diagram or structured JSON evidence, "
                "then keeps validation guardrails visible."
            ),
            "artifact_id": schema_hint.id,
            "artifact_ids": [artifact.id for artifact in [schema_hint, report] if artifact],
        }
    return {
        "type": "show_relational_map",
        "status": "needs_review",
        "label": "Upload an ER diagram or import a multi-table benchmark",
        "target_tab": "Data",
        "target_anchor": "relational-map",
        "detail": (
            "No relational catalog or ER diagram evidence exists yet. Upload a PNG/JPEG/SVG/PDF/JSON ER hint, "
            "or import a benchmark with supporting tables."
        ),
    }


def run_data_quality_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        return needs_dataset_action(
            action_type="run_data_quality",
            label="Upload a dataset before checking quality",
            detail="Data quality review needs a DatasetSnapshot so Tablex can inspect missingness, leakage risk, duplicates, target status, and availability assumptions.",
        )
    action_job = create_job(
        db,
        job_type="analyze_data_quality",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id, "triggered_by": "agent_chat"},
    )
    try:
        mark_job_running(action_job)
        result = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
        mark_job_succeeded(
            action_job,
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_ids": result.artifact_ids,
                "gate": result.gate,
                "evidence_ids": result.evidence_ids,
                "assumption_ids": result.assumption_ids,
                "question_ids": result.question_ids,
                "insight_id": result.insight_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="run_data_quality",
            label="Data quality review needs attention",
            target_tab="Data",
            target_anchor="data-focus",
            detail=str(exc),
            job_id=action_job.id,
        )
    severity = str(result.gate.get("summary", {}).get("severity") or "recorded")
    return {
        "type": "run_data_quality",
        "status": "applied",
        "label": f"Ran Data Quality Gate ({severity})",
        "target_tab": "Data",
        "target_anchor": "data-focus",
        "detail": "Created data_quality_gate, data_quality_report, visualization, Evidence, Assumptions/Questions when needed, Insight, and lineage.",
        "artifact_id": result.artifact_ids[0] if result.artifact_ids else None,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [result.insight_id, *result.evidence_ids],
        "job_id": action_job.id,
    }


def design_evaluation_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        return needs_dataset_action(
            action_type="design_evaluation",
            label="Upload a dataset before drafting evaluation",
            detail="Evaluation design needs row count, target status, schema, and profile context from a DatasetSnapshot.",
        )
    action_job = create_job(
        db,
        job_type="design_evaluation_candidates",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id, "triggered_by": "agent_chat"},
    )
    try:
        mark_job_running(action_job)
        candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
        mark_job_succeeded(action_job, {"evaluation_candidate_ids": [candidate.id for candidate in candidates]})
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="design_evaluation",
            label="Evaluation design needs attention",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail=str(exc),
            job_id=action_job.id,
        )
    return {
        "type": "design_evaluation",
        "status": "applied",
        "label": f"Drafted {len(candidates)} evaluation candidate(s)",
        "target_tab": "Evaluation",
        "target_anchor": "evaluation-design",
        "detail": "Created or refreshed EvaluationCandidates. No EvaluationSpec was approved or destructively changed by chat.",
        "entity_ids": [candidate.id for candidate in candidates],
        "job_id": action_job.id,
    }


def compare_evaluation_scenarios_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        return needs_dataset_action(
            action_type="compare_evaluation_scenarios",
            label="Upload a dataset before comparing evaluation scenarios",
            detail="Scenario comparison needs a DatasetSnapshot so Tablex can compare random, stratified, time, and group-aware options against actual data evidence.",
        )
    action_job = create_job(
        db,
        job_type="compare_evaluation_scenarios",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id, "triggered_by": "agent_chat"},
    )
    try:
        mark_job_running(action_job)
        candidates = list(create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset))
        artifact = create_evaluation_scenario_comparison(
            db,
            store=store,
            project=project,
            dataset=dataset,
            candidates=candidates,
        )
        metadata = loads_json(artifact.metadata_json, {})
        mark_job_succeeded(
            action_job,
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_id": artifact.id,
                "candidate_count": len(candidates),
                "recommended_candidate_id": metadata.get("recommended_candidate_id"),
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="compare_evaluation_scenarios",
            label="Evaluation scenario comparison needs attention",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail=str(exc),
            job_id=action_job.id,
        )
    return {
        "type": "compare_evaluation_scenarios",
        "status": "applied",
        "label": "Compared evaluation scenarios",
        "target_tab": "Evaluation",
        "target_anchor": "evaluation-design",
        "detail": "Created an evaluation_scenario_comparison artifact from current candidates, assumptions, quality risk, and dataset evidence.",
        "artifact_id": artifact.id,
        "artifact_ids": [artifact.id],
        "entity_ids": [candidate.id for candidate in candidates],
        "job_id": action_job.id,
    }


def plan_baseline_strategy_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    spec = latest_approved_spec_for_project(db, project.id)
    if spec is None:
        return needs_review_action(
            action_type="plan_baseline_strategy",
            label="Approve an EvaluationSpec before baseline strategy planning",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail="Tablex can propose baseline strategy only after the primary evaluation design is approved. Ask for evaluation design or scenario comparison first.",
        )
    split = latest_split_for_spec_id(db, spec.id)
    if split is None:
        return needs_review_action(
            action_type="plan_baseline_strategy",
            label="Generate a SplitManifest before baseline strategy planning",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail="Baseline strategy planning must respect the approved EvaluationSpec and SplitManifest before discussing model tactics.",
        )
    action_job = create_job(
        db,
        job_type="plan_baseline_strategy",
        project_id=project.id,
        input_payload={
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
            "triggered_by": "agent_chat",
        },
    )
    try:
        mark_job_running(action_job)
        result = create_baseline_strategy_plan(
            db,
            store=store,
            project=project,
            evaluation_spec=spec,
            split_manifest=split,
        )
        mark_job_succeeded(
            action_job,
            {
                "baseline_strategy_plan_artifact_id": result.artifact.id,
                "strategy_count": len(result.plan.get("candidate_strategies", [])),
                "next_agent_task_count": len(result.plan.get("next_agent_tasks", [])),
                "selected_baseline_type": result.plan["selected_execution"].get("baseline_type"),
                "strategy_mode": result.plan.get("context", {}).get("strategy_mode"),
                "planning_source": result.plan.get("context", {}).get("current_baseline_plan", {}).get("planning_source"),
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="plan_baseline_strategy",
            label="Baseline strategy planning needs attention",
            target_tab="Experiments",
            target_anchor=None,
            detail=str(exc),
            job_id=action_job.id,
        )
    selected = str(result.plan.get("selected_execution", {}).get("baseline_type") or "adaptive baseline")
    return {
        "type": "plan_baseline_strategy",
        "status": "applied",
        "label": "Planned a flexible baseline strategy",
        "target_tab": "Experiments",
        "target_anchor": None,
        "detail": (
            f"Created a baseline_strategy_plan artifact. Selected execution starts with {selected}, but the plan remains "
            "evidence-backed and open to Codex/Skill runner alternatives."
        ),
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "job_id": action_job.id,
    }


def run_model_candidates_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    model_candidates: list[str],
) -> dict[str, Any]:
    del store
    spec = latest_approved_spec_for_project(db, project.id)
    if spec is None:
        return needs_review_action(
            action_type="run_model_candidates",
            label="Approve an EvaluationSpec before training models",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail="Model candidates can only be compared after the evaluation contract is approved.",
        )
    split = latest_split_for_spec_id(db, spec.id)
    if split is None:
        return needs_review_action(
            action_type="run_model_candidates",
            label="Generate a SplitManifest before training models",
            target_tab="Evaluation",
            target_anchor="evaluation-design",
            detail="Training must respect the approved SplitManifest so leaderboard rows are comparable.",
        )
    normalized_models: list[str] = []
    unsupported_models: list[str] = []
    for model in model_candidates:
        normalized = normalize_model_candidate_name(model)
        if normalized is None:
            unsupported_models.append(model)
            continue
        if normalized not in normalized_models:
            normalized_models.append(normalized)
    if not normalized_models:
        return needs_review_action(
            action_type="run_model_candidates",
            label="No supported model candidates were recognized",
            target_tab="Experiments",
            target_anchor=None,
            detail=f"Requested models were not recognized: {', '.join(unsupported_models) or 'none'}",
        )
    action_job = create_job(
        db,
        job_type="train_model_candidates",
        project_id=project.id,
        input_payload={
            "requested_models": model_candidates,
            "normalized_models": normalized_models,
            "unsupported_models": unsupported_models,
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
            "triggered_by": "agent_chat",
        },
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "dependency_changes": "approval_required_when_missing",
        },
    )
    failures: list[dict[str, Any]] = [
        {"model": model, "status": "unsupported", "reason": "Model candidate is not recognized by Tablex yet."}
        for model in unsupported_models
    ]
    return {
        "type": "run_model_candidates",
        "status": "applied" if not failures else "needs_review",
        "label": f"Started Training Worker for {len(normalized_models)} model candidate(s)",
        "target_tab": "Leaderboard",
        "target_anchor": "result-readout",
        "detail": (
            "Queued a Training Worker that will fit the requested model candidates under the approved "
            "EvaluationSpec and SplitManifest, then write comparable runs to the Leaderboard. "
            + (
                f"{len(failures)} requested candidate(s) need review: "
                + "; ".join(f"{item['model']}={item['status']}" for item in failures)
                if failures
                else "Dependency changes remain approval-gated if a package is missing."
            )
        ),
        "job_id": action_job.id,
        "queued_models": normalized_models,
        "failures": failures,
        "auto_start_worker": True,
    }


def generate_decision_report_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    action_job = create_job(
        db,
        job_type="generate_decision_report",
        project_id=project.id,
        input_payload={"triggered_by": "agent_chat"},
    )
    try:
        mark_job_running(action_job)
        result = create_decision_report_v1(db, store=store, project=project)
        mark_job_succeeded(
            action_job,
            {
                "schema_version": result.bundle["schema_version"],
                "readiness_status": result.bundle["readiness"]["status"],
                "report_id": result.report.id,
                "decision_report_artifact_id": result.report_artifact.id,
                "decision_report_bundle_artifact_id": result.bundle_artifact.id,
                "decision_report_evidence_id": result.evidence.id,
                "next_action_count": len(result.bundle["next_actions"]),
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="generate_decision_report",
            label="Decision report needs attention",
            target_tab="Reports",
            target_anchor="decision-report",
            detail=str(exc),
            job_id=action_job.id,
        )
    readiness = str(result.bundle.get("readiness", {}).get("status") or "recorded")
    return {
        "type": "generate_decision_report",
        "status": "applied",
        "label": "Generated a decision report",
        "target_tab": "Reports",
        "target_anchor": "decision-report",
        "detail": f"Created decision_report, decision_report_bundle, Evidence, Report, and lineage. Readiness status is {readiness}.",
        "artifact_id": result.report_artifact.id,
        "artifact_ids": [result.report_artifact.id, result.bundle_artifact.id],
        "entity_ids": [result.report.id, result.evidence.id],
        "job_id": action_job.id,
    }


def show_leaderboard_action(db: Session, *, project: Project) -> dict[str, Any]:
    runs = leaderboard_runs(db, project.id)
    if not runs:
        return needs_review_action(
            action_type="show_leaderboard",
            label="Run evidence is needed before reading the leaderboard",
            target_tab="Experiments",
            target_anchor=None,
            detail=(
                "No successful ExperimentRun exists yet. Open Experiments after approving EvaluationSpec and "
                "generating SplitManifest, then run a baseline or controlled agent task before ranking anything."
            ),
        )
    top_run = runs[0]
    metric = loads_json(top_run.metrics_json, {})
    primary_metric_name = str(metric.get("primary_metric_name") or "-")
    primary_metric_value = metric.get("primary_metric_value")
    value_text = f"{primary_metric_value:.6f}" if isinstance(primary_metric_value, int | float) else str(primary_metric_value or "-")
    return {
        "type": "show_leaderboard",
        "status": "explained",
        "label": "Open the Result Readout",
        "target_tab": "Leaderboard",
        "target_anchor": "result-readout",
        "detail": (
            f"Leaderboard has {len(runs)} successful run(s). Top run is {top_run.id} with "
            f"{primary_metric_name}={value_text}. Start with the result readout, then drill into diagnostics only when needed."
        ),
        "entity_ids": [run.id for run in runs[:5]],
    }


def compare_top_runs_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    runs = leaderboard_runs(db, project.id)
    if not runs:
        return needs_review_action(
            action_type="compare_top_runs",
            label="Successful runs are needed before comparing results",
            target_tab="Experiments",
            target_anchor=None,
            detail=(
                "No successful ExperimentRun exists yet. Run a baseline or controlled agent task under an approved "
                "EvaluationSpec and SplitManifest before comparing approaches."
            ),
        )
    action_job = create_job(
        db,
        job_type="compare_experiments",
        project_id=project.id,
        input_payload={"triggered_by": "agent_chat", "run_ids": [run.id for run in runs[:5]]},
    )
    try:
        mark_job_running(action_job)
        result = compare_project_experiments(db, store=store, project=project)
        mark_job_succeeded(
            action_job,
            {
                "artifact_ids": result.artifact_ids,
                "comparison": result.comparison,
                "visualization_id": result.visualization_id,
                "report_id": result.report_id,
                "evidence_id": result.evidence_id,
                "insight_id": result.insight_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="compare_top_runs",
            label="Run comparison needs attention",
            target_tab="Experiments",
            target_anchor=None,
            detail=str(exc),
            job_id=action_job.id,
        )
    comparison = dict_value(result.comparison)
    decision = dict_value(comparison.get("decision"))
    best_run_id = str(decision.get("best_run_id") or runs[0].id)
    return {
        "type": "compare_top_runs",
        "status": "applied",
        "label": "Compared current run evidence",
        "target_tab": "Leaderboard",
        "target_anchor": "result-readout",
        "detail": (
            f"Created experiment comparison evidence for {len(runs)} successful run(s). "
            f"Current best run is {best_run_id}; read the result readout and comparison report before treating rank as a decision."
        ),
        "artifact_id": result.artifact_ids[0] if result.artifact_ids else None,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [run.id for run in runs[:5]],
        "job_id": action_job.id,
    }


def post_run_reading_workflow_action(db: Session, *, store: LocalArtifactStore, project: Project) -> dict[str, Any]:
    runs = leaderboard_runs(db, project.id)
    if not runs:
        return needs_review_action(
            action_type="post_run_reading_workflow",
            label="Successful runs are needed before post-run reporting",
            target_tab="Experiments",
            target_anchor=None,
            detail=(
                "No successful ExperimentRun exists yet. Create a run under an approved EvaluationSpec and "
                "SplitManifest before asking Tablex to diagnose and summarize results."
            ),
        )
    top_run = runs[0]
    action_job = create_job(
        db,
        job_type="post_run_reading_workflow",
        project_id=project.id,
        input_payload={"triggered_by": "agent_chat", "top_run_id": top_run.id, "run_ids": [run.id for run in runs[:5]]},
    )
    diagnostics_ids: list[str] = []
    diagnostics_error: str | None = None
    run_report_artifact_id: str | None = None
    comparison_artifact_ids: list[str] = []
    decision_report_id: str | None = None
    decision_report_artifact_id: str | None = None
    try:
        mark_job_running(action_job)
        try:
            diagnostics_result = analyze_run_diagnostics(db, store=store, run=top_run)
            diagnostics_ids = diagnostics_result.artifact_ids
        except ValueError as exc:
            diagnostics_error = str(exc)
        run_report_result = draft_run_report(db, store=store, run=top_run)
        run_report_artifact_id = run_report_result.artifact.id
        comparison_result = compare_project_experiments(db, store=store, project=project)
        comparison_artifact_ids = comparison_result.artifact_ids
        decision_result = create_decision_report_v1(db, store=store, project=project)
        decision_report_id = decision_result.report.id
        decision_report_artifact_id = decision_result.report_artifact.id
        mark_job_succeeded(
            action_job,
            {
                "top_run_id": top_run.id,
                "diagnostics_artifact_ids": diagnostics_ids,
                "diagnostics_error": diagnostics_error,
                "run_report_artifact_id": run_report_artifact_id,
                "comparison_artifact_ids": comparison_artifact_ids,
                "decision_report_id": decision_report_id,
                "decision_report_artifact_id": decision_report_artifact_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="post_run_reading_workflow",
            label="Post-run reading workflow needs attention",
            target_tab="Leaderboard",
            target_anchor="result-readout",
            detail=str(exc),
            job_id=action_job.id,
        )
    artifact_ids = [*diagnostics_ids, *comparison_artifact_ids]
    if run_report_artifact_id:
        artifact_ids.append(run_report_artifact_id)
    if decision_report_artifact_id:
        artifact_ids.append(decision_report_artifact_id)
    diagnostics_note = (
        " Diagnostics were generated."
        if diagnostics_ids
        else f" Diagnostics could not be generated yet: {diagnostics_error}." if diagnostics_error else ""
    )
    return {
        "type": "post_run_reading_workflow",
        "status": "applied",
        "label": "Prepared post-run evidence for reading",
        "target_tab": "Reports",
        "target_anchor": "decision-report",
        "detail": (
            f"Top run {top_run.id} was converted into run report, experiment comparison, and decision report evidence."
            f"{diagnostics_note} Start with Reports, then return to the result readout if the rank needs diagnostics detail."
        ),
        "artifact_id": decision_report_artifact_id or run_report_artifact_id or (artifact_ids[0] if artifact_ids else None),
        "artifact_ids": artifact_ids,
        "entity_ids": [top_run.id],
        "job_id": action_job.id,
    }


def prepare_result_notebook_evidence_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> dict[str, Any]:
    action_job = create_job(
        db,
        job_type="prepare_result_notebook_evidence",
        project_id=project.id,
        input_payload={"triggered_by": "agent_chat"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "generate_and_safe_static_capture",
            "executes_notebook_code": False,
        },
    )
    try:
        mark_job_running(action_job)
        result = prepare_result_notebook_evidence(db, store=store, project=project)
        mark_job_succeeded(action_job, result_notebook_evidence_job_output(result))
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="prepare_result_notebook_evidence",
            label="Successful run evidence is needed before notebook evidence",
            target_tab="Experiments",
            target_anchor=None,
            detail=str(exc),
            job_id=action_job.id,
        )
    status_label = "prepared" if result.capture_created or result.notebook_generated else "already ready"
    return {
        "type": "prepare_result_notebook_evidence",
        "status": "applied",
        "label": f"Result notebook evidence is {status_label}",
        "target_tab": "Notebooks",
        "target_anchor": "notebook-focus",
        "detail": (
            f"Top run {result.top_run.id} is linked to a model diagnostics notebook and readable Evidence HTML. "
            "Start with the Notebook focus preview, then ask Codex for exactly one missing diagnostic such as "
            "feature importance, permutation importance, calibration, threshold, or slice review."
        ),
        "artifact_id": result.preview_artifact_id,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [result.top_run.id],
        "job_id": action_job.id,
    }


def needs_dataset_action(*, action_type: str, label: str, detail: str) -> dict[str, Any]:
    return needs_review_action(
        action_type=action_type,
        label=label,
        target_tab="Data",
        target_anchor="dataset-upload",
        detail=detail,
    )


def needs_review_action(
    *,
    action_type: str,
    label: str,
    target_tab: str,
    target_anchor: str | None,
    detail: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "type": action_type,
        "status": "needs_review",
        "label": label,
        "target_tab": target_tab,
        "target_anchor": target_anchor,
        "detail": detail,
    }
    if job_id:
        action["job_id"] = job_id
    return action


def create_notebook_authoring_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    message: str,
) -> dict[str, Any]:
    result = create_notebook_authoring_brief(
        db,
        store=store,
        project=project,
        objective=(
            f"Prepare Codex to write a high-quality Tablex analysis notebook for this request: {message}. "
            "Use source-backed notebook craft principles, current Data Review evidence, and project artifacts."
        ),
    )
    return {
        "type": "create_notebook_authoring_brief",
        "status": "applied",
        "label": "Prepared a GM-style notebook authoring brief",
        "target_tab": "Notebooks",
        "target_anchor": "notebook-focus",
        "detail": (
            "Created a source-backed brief with Kaggle Grandmaster-inspired craft principles, sample moves, "
            "context artifacts, and a Codex contract for on-the-fly notebook writing."
        ),
        "artifact_id": result.brief_artifact.id,
        "artifact_ids": result.artifact_ids,
        "entity_ids": [result.report.id],
    }


def explain_next_step_action(db: Session, *, project: Project) -> dict[str, Any]:
    guidance = build_project_guidance(db, project)
    focus = guidance["recommended_focus"]
    decision_brief = guidance["autonomous_navigation"]["decision_brief"]
    return {
        "type": "explain_next_step",
        "status": "explained",
        "label": str(focus["title"]),
        "target_tab": focus["target_tab"],
        "target_anchor": target_anchor_for_tab(str(focus["target_tab"])),
        "detail": str(focus["reason"]),
        "guidance": {
            "focus_key": focus["focus_key"],
            "risk_level": focus["risk_level"],
            "confidence": focus["confidence"],
            "evidence": focus["evidence"],
            "current_stage_id": guidance["current_stage_id"],
            "decision_brief": decision_brief,
        },
    }


def target_anchor_for_tab(tab: str) -> str:
    anchors = {
        "Data": "data-focus",
        "Understanding": "understanding-report",
        "Assumptions": "assumption-review",
        "Evaluation": "evaluation-design",
        "Approach": "approach-handoff",
        "Leaderboard": "result-readout",
        "Notebooks": "notebook-focus",
        "Reports": "decision-report",
    }
    return anchors.get(tab, "approach-handoff")


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec_for_project(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec_id(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest).where(SplitManifest.evaluation_spec_id == spec_id).order_by(SplitManifest.created_at.desc())
    )


def leaderboard_runs(db: Session, project_id: str) -> list[ExperimentRun]:
    runs = list(
        db.scalars(
            select(ExperimentRun).where(ExperimentRun.project_id == project_id, ExperimentRun.status == "succeeded")
        ).all()
    )
    return sorted(runs, key=leaderboard_sort_key)


def guide_notebook_review_action(
    db: Session,
    *,
    project: Project,
    notebook_artifact_id: str | None,
) -> dict[str, Any]:
    index = build_project_notebook_index(db, project)
    items = [cast(dict[str, Any], item) for item in list_value(index.get("items")) if isinstance(item, dict)]
    item = next(
        (
            candidate
            for candidate in items
            if isinstance(candidate, dict)
            and notebook_artifact_id
            and candidate.get("notebook_artifact_id") == notebook_artifact_id
        ),
        None,
    )
    if item is None:
        recommended = index.get("recommended_notebook")
        item = recommended if isinstance(recommended, dict) else None
    if item is None:
        return {
            "type": "guide_notebook_review",
            "status": "needs_review",
            "label": "Create a notebook review first",
            "target_tab": "Notebooks",
            "target_anchor": "notebook-focus",
            "detail": "No generated notebook exists yet. Generate a Data Understanding notebook, then ask me what to inspect.",
        }
    artifact_ids = dict_value(item.get("artifact_ids"))
    notebook_id = str(item.get("notebook_artifact_id") or "")
    evidence_html = latest_notebook_artifact(db, project.id, notebook_id, "notebook_evidence_html")
    evidence_bundle = latest_notebook_artifact(db, project.id, notebook_id, "notebook_evidence_bundle")
    evidence_figures = notebook_artifacts(db, project.id, notebook_id, "notebook_evidence_svg")
    coverage = dict_value(item.get("coverage"))
    if evidence_html is not None:
        label = "Open the Evidence narrative first"
        detail = (
            f"Read `{evidence_html.name}` before source or manifests. It combines the notebook review, "
            f"profile-backed figures, guardrails, and Codex follow-up prompts. Then inspect the first SVG figure "
            f"if a visual claim needs detail."
        )
        artifact_id = evidence_html.id
    elif coverage.get("has_execution_capture"):
        label = "Open the capture preview first"
        detail = "Evidence capture exists but the narrative evidence artifact is missing. Inspect the capture preview and figure manifest."
        artifact_id = str(artifact_ids.get("execution_html") or artifact_ids.get("figure_manifest") or item.get("notebook_artifact_id"))
    else:
        label = "Capture evidence before reading deeply"
        detail = (
            "The notebook draft exists, but profile-backed evidence has not been captured. Click Capture Evidence, "
            "then open the Evidence narrative so the result appears next to the action."
        )
        artifact_id = str(artifact_ids.get("html_preview") or item.get("notebook_artifact_id"))
    return {
        "type": "guide_notebook_review",
        "status": "explained",
        "label": label,
        "target_tab": "Notebooks",
        "target_anchor": "analysis-story",
        "detail": detail,
        "artifact_id": artifact_id,
        "artifact_ids": [
            artifact.id
            for artifact in [
                evidence_html,
                evidence_bundle,
                *evidence_figures[:4],
            ]
            if artifact is not None
        ],
        "guidance": {
            "notebook_artifact_id": notebook_id,
            "notebook_kind": item.get("notebook_kind"),
            "coverage": coverage,
            "evidence_figure_count": len(evidence_figures),
            "next_micro_steps": [
                "Open Review in the Notebook tab.",
                "Read the Read this first and Visual story cards sections.",
                "Inspect the most relevant SVG figure if a claim needs detail.",
                "Ask Codex for a targeted follow-up instead of scanning every artifact.",
            ],
        },
    }


def latest_notebook_artifact(db: Session, project_id: str, notebook_artifact_id: str, asset_type: str) -> Artifact | None:
    return next(iter(notebook_artifacts(db, project_id, notebook_artifact_id, asset_type)), None)


def notebook_artifacts(db: Session, project_id: str, notebook_artifact_id: str, asset_type: str) -> list[Artifact]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    return [
        artifact
        for artifact in artifacts
        if loads_json(artifact.metadata_json, {}).get("notebook_artifact_id") == notebook_artifact_id
    ]


def apply_metric_preference(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    metric: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    preference_artifact = record_metric_preference(
        db,
        store=store,
        project=project,
        metric=metric,
        source="agent_chat",
    )
    actions.append(
        {
            "type": "set_leaderboard_metric_view",
            "status": "applied",
            "label": f"Leaderboard now ranks by {SUPPORTED_METRICS[metric]['label']} when available",
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "detail": (
                "The visible leaderboard metric preference changed immediately. Existing runs will re-rank by this "
                "metric if it was already computed; otherwise the row shows the metric as unavailable until rerun."
            ),
            "artifact_id": preference_artifact.id,
        }
    )
    candidates = list(
        db.scalars(
            select(EvaluationCandidate)
            .where(EvaluationCandidate.project_id == project.id)
            .order_by(EvaluationCandidate.created_at.desc())
        ).all()
    )
    mutable_candidates = [
        candidate
        for candidate in candidates
        if candidate.status in {"primary_candidate", "alternative", "rejected", "draft", "recommended"}
    ]
    changed_candidates = []
    for candidate in mutable_candidates:
        if candidate.primary_metric == metric:
            continue
        previous = candidate.primary_metric
        secondary = list(loads_json(candidate.secondary_metrics_json, []))
        if previous and previous not in secondary:
            secondary.append(previous)
        candidate.primary_metric = metric
        candidate.secondary_metrics_json = dumps_json([item for item in secondary if item != metric])
        candidate.rationale_md = append_decision_note(
            candidate.rationale_md,
            f"Agent Chat metric preference recorded: primary_metric changed from `{previous}` to `{metric}`.",
        )
        changed_candidates.append(candidate)
    if changed_candidates:
        dataset_id = changed_candidates[0].dataset_snapshot_id
        write_candidates_artifact(db, store, project.id, candidates, dataset_id)
        actions.append(
            {
                "type": "update_evaluation_candidates",
                "status": "applied",
                "label": f"Set {len(changed_candidates)} evaluation candidate(s) to {SUPPORTED_METRICS[metric]['label']}",
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-design",
                "detail": "Updated mutable EvaluationCandidates only. Approved EvaluationSpecs are not destructively changed.",
                "entity_ids": [candidate.id for candidate in changed_candidates],
            }
        )

    draft_specs = list(
        db.scalars(
            select(EvaluationSpec)
            .where(EvaluationSpec.project_id == project.id, EvaluationSpec.status.in_(["draft", "pending_review"]))
            .order_by(EvaluationSpec.created_at.desc())
        ).all()
    )
    changed_specs = []
    for spec in draft_specs:
        if spec.primary_metric == metric:
            continue
        previous = spec.primary_metric
        secondary = list(loads_json(spec.secondary_metrics_json, []))
        if previous and previous not in secondary:
            secondary.append(previous)
        spec.primary_metric = metric
        spec.secondary_metrics_json = dumps_json([item for item in secondary if item != metric])
        spec.rationale_md = append_decision_note(
            spec.rationale_md,
            f"Agent Chat metric preference recorded: primary_metric changed from `{previous}` to `{metric}` before approval.",
        )
        artifact = write_spec_artifact(db, store, spec)
        changed_specs.append((spec, artifact))
    if changed_specs:
        actions.append(
            {
                "type": "update_draft_evaluation_specs",
                "status": "applied",
                "label": f"Set {len(changed_specs)} draft EvaluationSpec(s) to {SUPPORTED_METRICS[metric]['label']}",
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-design",
                "detail": "Draft specs were updated and new spec artifacts were written.",
                "entity_ids": [spec.id for spec, _artifact in changed_specs],
                "artifact_ids": [artifact.id for _spec, artifact in changed_specs],
            }
        )

    approved_specs = list(
        db.scalars(
            select(EvaluationSpec)
            .where(EvaluationSpec.project_id == project.id, EvaluationSpec.status == "approved")
            .order_by(EvaluationSpec.created_at.desc())
        ).all()
    )
    conflicting_approved = [spec for spec in approved_specs if spec.primary_metric != metric]
    if conflicting_approved:
        split_ids = list(
            db.scalars(
                select(SplitManifest.id).where(
                    SplitManifest.evaluation_spec_id.in_([spec.id for spec in conflicting_approved])
                )
            ).all()
        )
        payload = {
            "schema_version": "evaluation_metric_change_request.v1",
            "project_id": project.id,
            "requested_metric": metric,
            "requested_metric_label": SUPPORTED_METRICS[metric]["label"],
            "approved_specs": [spec_to_dict(spec) for spec in conflicting_approved],
            "split_manifest_ids": split_ids,
            "decision": "not_applied_to_approved_specs",
            "reason": "Approved EvaluationSpecs and SplitManifests are immutable by Agent Chat. Create a revised evaluation design if this change is intended.",
            "next_actions": [
                "Review the Evaluation tab before replacing the approved metric.",
                "Create or promote a revised EvaluationSpec if ROC-AUC is the desired primary metric.",
                "Regenerate SplitManifest and rerun experiments under the revised spec.",
            ],
        }
        artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="evaluation_metric_change_request",
            name=f"metric_change_request_{metric}",
            filename="evaluation_metric_change_request.json",
            payload=payload,
            metadata={
                "project_id": project.id,
                "requested_metric": metric,
                "approved_spec_count": len(conflicting_approved),
                "split_manifest_count": len(split_ids),
            },
        )
        for spec in conflicting_approved:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="evaluation_spec",
                from_asset_id=spec.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="change_requested",
            )
        actions.append(
            {
                "type": "record_metric_change_request",
                "status": "needs_review",
                "label": f"Recorded requested metric change to {SUPPORTED_METRICS[metric]['label']}",
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-design",
                "detail": "Approved EvaluationSpecs were left unchanged; a review artifact was created instead.",
                "artifact_id": artifact.id,
                "entity_ids": [spec.id for spec in conflicting_approved],
            }
        )

    if not actions:
        actions.append(
            {
                "type": "note_metric_preference",
                "status": "recorded",
                "label": f"Recorded preference for {SUPPORTED_METRICS[metric]['label']}",
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-design",
                "detail": "No evaluation candidates or draft specs exist yet. The metric preference is ready for the next evaluation design step.",
            }
        )
    return actions


def plan_metric_agent_task(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    message: str,
    metric: str,
) -> AgentTaskPlanResult:
    objective = (
        f"The user asked: {message}. Interpret this as a preference for {SUPPORTED_METRICS[metric]['label']} "
        "when designing or revising evaluation. Do not destructively modify approved EvaluationSpecs or "
        "SplitManifests; create a reviewable plan and required artifacts instead."
    )
    return plan_project_agent_task(
        db,
        store=store,
        project=project,
        job=job,
        objective=objective,
        task_type="revise_evaluation_design",
    )


def plan_notebook_followup_agent_task(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    message: str,
    focus_areas: list[str],
    source_ref: dict[str, Any],
) -> AgentTaskPlanResult:
    focus_text = ", ".join(focus_areas) if focus_areas else "targeted notebook diagnostics"
    source_type = source_ref.get("source_type") or "current_analysis_story"
    source_artifact_id = source_ref.get("artifact_id") or "latest_relevant_notebook_or_story"
    objective = (
        f"The user asked from the notebook surface: {message}. Convert this into a focused Tablex notebook "
        f"follow-up diagnostics task for {focus_text}. Start from source `{source_type}` / `{source_artifact_id}`, "
        "current Analysis Story, notebook evidence, run reports, prediction artifacts, EvaluationSpec, and "
        "SplitManifest. Materialize only artifact-backed diagnostics: feature importance, permutation importance, "
        "partial dependence, calibration, threshold/score-bin review, slice metrics, and worst-example analysis "
        "when the required artifacts exist. If required model, prediction, or split evidence is missing, write a "
        "clear evidence gap report and the narrow next artifact request instead of inventing charts or metrics. "
        "Do not destructively change EvaluationSpec or SplitManifest. Keep the output human-readable inside Tablex "
        "and concise enough to become the next Analysis Story."
    )
    return plan_project_agent_task(
        db,
        store=store,
        project=project,
        job=job,
        objective=objective,
        task_type="notebook_followup_diagnostics",
    )


def agent_task_action(result: AgentTaskPlanResult) -> dict[str, Any]:
    return {
        "type": "create_agent_task_contract",
        "status": "created",
        "label": "Prepared a controlled AgentTaskContract",
        "target_tab": "Approach",
        "target_anchor": "approach-handoff",
        "detail": "The contract carries current context, safety rules, artifact expectations, and open-ended runner autonomy.",
        "artifact_id": result.artifact.id,
        "entity_ids": [str(result.contract["task_id"])],
    }


def notebook_followup_task_action(result: AgentTaskPlanResult, intent: dict[str, Any]) -> dict[str, Any]:
    focus_areas = [str(item).replace("_", " ") for item in list_value(intent.get("focus_areas"))]
    focus_text = ", ".join(focus_areas[:4]) if focus_areas else "notebook diagnostics"
    return {
        "type": "create_notebook_followup_task",
        "status": "created",
        "label": "Prepared a targeted notebook follow-up task",
        "target_tab": "Approach",
        "target_anchor": "approach-handoff",
        "detail": (
            f"The task asks Codex to materialize {focus_text} as artifact-backed diagnostics, while respecting "
            "EvaluationSpec, SplitManifest, and existing notebook evidence."
        ),
        "artifact_id": result.artifact.id,
        "entity_ids": [str(result.contract["task_id"])],
    }


def materialize_top_model_evidence_action(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> dict[str, Any]:
    runs = leaderboard_runs(db, project.id)
    if not runs:
        return needs_review_action(
            action_type="materialize_model_diagnostics_artifacts",
            label="Model evidence needs a successful run",
            target_tab="Experiments",
            target_anchor=None,
            detail="No successful ExperimentRun exists yet, so Tablex cannot materialize model evidence artifacts.",
        )
    top_run = runs[0]
    action_job = create_job(
        db,
        job_type="materialize_model_diagnostics_artifacts",
        project_id=project.id,
        input_payload={"run_id": top_run.id, "triggered_by": "agent_chat"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "evaluation_spec_modified": False,
            "split_manifest_required": True,
        },
    )
    try:
        mark_job_running(action_job)
        result = materialize_model_diagnostics_artifacts(db, store=store, run=top_run)
        mark_job_succeeded(
            action_job,
            {
                "run_id": top_run.id,
                "model_version_id": top_run.model_version_id,
                "artifact_ids": result.artifact_ids,
                "feature_importance_artifact_id": result.artifact_ids[0],
                "permutation_importance_artifact_id": result.artifact_ids[1],
                "model_diagnostics_artifact_pack_id": result.artifact_ids[2],
                "model_diagnostics_report_artifact_id": result.artifact_ids[3],
                "visualization_artifact_id": result.artifact_ids[4],
                "availability": result.diagnostics.get("availability", {}),
            },
        )
    except ValueError as exc:
        mark_job_failed(action_job, str(exc))
        return needs_review_action(
            action_type="materialize_model_diagnostics_artifacts",
            label="Model evidence needs source artifacts",
            target_tab="Experiments",
            target_anchor=None,
            detail=str(exc),
            job_id=action_job.id,
        )
    availability = result.diagnostics.get("availability", {})
    return {
        "type": "materialize_model_diagnostics_artifacts",
        "status": "applied",
        "label": "Materialized model evidence artifacts",
        "target_tab": "Leaderboard",
        "target_anchor": "result-readout",
        "detail": (
            f"Created feature importance, permutation importance, model diagnostics pack, report, and visualization "
            f"for top run {top_run.id}. Availability: native={availability.get('native_feature_importance')}, "
            f"permutation={availability.get('permutation_importance')}, prediction_review={availability.get('prediction_review')}."
        ),
        "artifact_id": result.artifact_ids[3],
        "artifact_ids": result.artifact_ids,
        "entity_ids": [top_run.id, result.insight_id, result.evidence_id],
        "job_id": action_job.id,
    }


def append_decision_note(existing: str, note: str) -> str:
    if note in existing:
        return existing
    return f"{existing.rstrip()}\n\nDecision note: {note}".strip()


def response_locale_for_chat(locale: str | None, message: str) -> str:
    if contains_japanese_text(message):
        return "ja-JP"
    return locale or "en-US"


def contains_japanese_text(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value))


def render_assistant_message(intent: dict[str, Any], actions: list[dict[str, Any]], *, locale: str | None = None) -> str:
    _ = locale
    applied = [action for action in actions if action["status"] == "applied"]
    review = [action for action in actions if action["status"] == "needs_review"]
    created = [action for action in actions if action["status"] == "created"]
    recorded = [action for action in actions if action["status"] == "recorded"]
    if intent["type"] == "set_evaluation_metric":
        metric = SUPPORTED_METRICS[str(intent["metric"])]["label"]
        metric_view_applied = any(action.get("type") == "set_leaderboard_metric_view" for action in actions)
        design_applied = any(action.get("type") in {"update_evaluation_candidates", "update_draft_evaluation_specs"} for action in applied)
        parts = [f"Done: the leaderboard view is now set to {metric}."]
        if metric_view_applied:
            parts.append("Rows are ranked by that one metric when the run has it; missing scores stay blank instead of silently falling back to another metric.")
        if design_applied:
            parts.append("I updated mutable evaluation design objects now.")
        if review:
            parts.append("I did not change approved EvaluationSpecs; I created a review artifact instead.")
        if recorded:
            parts.append("There is no evaluation design to edit yet, so I recorded this as a preference for the next design step.")
        if created:
            parts.append("I also prepared a controlled AgentTaskContract for a runner to revise the design safely.")
        parts.append("Next: read the Leaderboard; open Evaluation only if you want to replace the approved evaluation contract.")
        return " ".join(parts)
    if intent["type"] == "run_model_candidates":
        action = actions[0]
        results = list_value(action.get("results"))
        queued_models = list_value(action.get("queued_models"))
        failures = list_value(action.get("failures"))
        if action.get("status") in {"applied", "needs_review"} and results:
            models = ", ".join(str(item.get("model")) for item in results if isinstance(item, dict))
            parts = [f"Done: trained {len(results)} model candidate(s): {models}."]
            parts.append("I added the completed runs to the Leaderboard under the approved EvaluationSpec and SplitManifest.")
            if failures:
                parts.append(
                    "Some candidates need review before they can run: "
                    + "; ".join(
                        f"{item.get('model')}={item.get('status')}" for item in failures if isinstance(item, dict)
                    )
                    + "."
                )
            parts.append("Next: read the Leaderboard; open a model row for diagnostics and threshold review.")
            return " ".join(parts)
        if action.get("status") in {"applied", "needs_review"} and queued_models:
            models = ", ".join(str(model) for model in queued_models)
            parts = [f"Started Training Worker for {models}."]
            parts.append("It will train under the approved EvaluationSpec and SplitManifest, then add completed runs to the Leaderboard.")
            if failures:
                parts.append(
                    "Some requested candidates need review: "
                    + "; ".join(
                        f"{item.get('model')}={item.get('status')}" for item in failures if isinstance(item, dict)
                    )
                    + "."
                )
            parts.append("Next: watch Training activity; when it finishes, read the Leaderboard as the ranked result table.")
            return " ".join(parts)
        return (
            "I could not train the requested model candidates yet. "
            f"{action.get('detail') or 'Check Experiments for the blocking condition.'}"
        )
    if intent["type"] == "generate_data_understanding_notebook":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I generated a Data Understanding notebook inside Tablex, including source, HTML preview, "
                "report, manifest, and lineage. Next: open Notebooks and review the reader brief, findings, "
                "and investigation queue."
            )
    if intent["type"] == "run_eda_review":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I ran a controlled Data Review inside Tablex. It created a human-readable HTML review, "
                "SVG figures, a JSON evidence bundle, a report, Evidence, Insight, and lineage. "
                "Next: open Notebooks, start with Data Review, read the verdict and findings, then ask me to turn the top finding into a focused action."
            )
        return (
            f"I cannot run Data Review yet: {action['detail']} "
            f"Open {action['target_tab']} and upload or select a dataset first."
        )
    if intent["type"] == "show_relational_map":
        action = actions[0]
        if action["status"] == "needs_review":
            return (
                "I do not see relational evidence yet. Open Data and upload an ER diagram or import a multi-table "
                "benchmark. I will treat the diagram as evidence, not a confirmed join contract, until keys, "
                "cardinality, and prediction-time availability are reviewed."
            )
        return (
            f"I found relational evidence and routed you to Data. {action['detail']} "
            "Start with the ER-style map, then inspect only the guardrails and supporting JSON if something looks wrong."
        )
    if intent["type"] == "run_data_quality":
        action = actions[0]
        if action["status"] == "applied":
            return (
                f"I ran the Data Quality Gate. {action['detail']} "
                "Next: open Data, read the current data evidence and any quality warnings, then let the Navigator decide whether assumptions or evaluation need attention."
            )
        return f"I cannot run the Data Quality Gate yet: {action['detail']} Open Data and resolve that first."
    if intent["type"] == "design_evaluation":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I drafted evaluation candidates inside Tablex. I did not approve an EvaluationSpec or change a SplitManifest. "
                f"{action['detail']} Next: open Evaluation, review the primary and alternatives, then approve only when the design is defensible."
            )
        return f"I cannot draft evaluation yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "compare_evaluation_scenarios":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I compared evaluation scenarios as decision support. "
                f"{action['detail']} Next: open Evaluation and read the comparison before promoting a primary spec."
            )
        return f"I cannot compare evaluation scenarios yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "plan_baseline_strategy":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I planned a flexible baseline strategy instead of forcing a fixed recipe. "
                f"{action['detail']} Next: open Experiments, inspect the strategy plan, then run or hand off only after EvaluationSpec and SplitManifest remain clear."
            )
        return f"I cannot plan the baseline strategy yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "generate_decision_report":
        action = actions[0]
        if action["status"] == "applied":
            return (
                "I generated a decision report inside Tablex. "
                f"{action['detail']} Next: open Reports and read the recommendation, coverage gaps, and next action before scanning raw artifacts."
            )
        return f"I cannot generate the decision report yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "show_leaderboard":
        action = actions[0]
        if action["status"] == "needs_review":
            return (
                f"The leaderboard is not ready yet: {action['detail']} "
                "Next: open Experiments and create comparable run evidence under the approved evaluation contract."
            )
        return (
            f"I routed you to the Result Readout. {action['detail']} "
            "Read the compact result first; the raw leaderboard is supporting evidence."
        )
    if intent["type"] == "compare_top_runs":
        action = actions[0]
        if action["status"] == "applied":
            return (
                f"I compared the current run evidence. {action['detail']} "
                "Next: open the Result Readout, then inspect diagnostics/report evidence only where the readout asks for it."
            )
        return f"I cannot compare runs yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "post_run_reading_workflow":
        action = actions[0]
        if action["status"] == "applied":
            return (
                f"I prepared the post-run reading workflow. {action['detail']} "
                "Next: open Reports and read the decision report first; use the Result Readout when you need rank-level detail."
            )
        return f"I cannot prepare post-run reading yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "prepare_result_notebook_evidence":
        action = actions[0]
        if action["status"] == "applied":
            return (
                f"I prepared readable notebook evidence for the current top run. {action['detail']} "
                "Next: open Notebooks. The preview should show Notebook Evidence Review, not raw source or JSON."
            )
        return f"I cannot prepare result notebook evidence yet: {action['detail']} Open {action['target_tab']} and resolve that first."
    if intent["type"] == "author_analysis_notebook":
        brief_action = next((action for action in actions if action["type"] == "create_notebook_authoring_brief"), None)
        task_action = next((action for action in actions if action["type"] == "create_agent_task_contract"), None)
        return (
            "I prepared the notebook authoring handoff instead of hardcoding another template. "
            f"{brief_action['detail'] if brief_action else ''} "
            f"{task_action['detail'] if task_action else ''} "
            "Next: run the controlled Codex notebook authoring task so it reads the brief, Data Review evidence, "
            "and project artifacts, then writes the notebook on the fly with source-backed narrative quality."
        )
    if intent["type"] == "plan_notebook_followup_task":
        action = actions[0]
        model_evidence_action = next(
            (item for item in actions if item.get("type") == "materialize_model_diagnostics_artifacts"),
            None,
        )
        model_evidence_sentence = (
            f" I also materialized in-harness model evidence now: {model_evidence_action['detail']} "
            "Read Leaderboard > Result Readout first, then open Notebook Evidence for the visual story. "
            "Use the Approach handoff only if you want Codex to extend this into a broader notebook or report update."
            if model_evidence_action and model_evidence_action.get("status") == "applied"
            else ""
        )
        return (
            "I turned that notebook follow-up into a controlled diagnostics task, not just a note. "
            f"{action['detail']} Open Approach to review the runner handoff. When executed, Codex should produce "
            "a concise report, figures or visualization specs, evidence bundle, and notebook update only from "
            "available artifacts; if prediction or model evidence is missing, it must say exactly what is missing."
            f"{model_evidence_sentence}"
        )
    if intent["type"] == "explain_next_step":
        action = actions[0]
        guidance = dict_value(action.get("guidance"))
        decision_brief = dict_value(guidance.get("decision_brief"))
        decision_question = str(decision_brief.get("decision_question") or action["label"])
        if_done = str(decision_brief.get("if_done") or "Refresh the Autonomous Navigator after the action.")
        return (
            f"Next decision: {decision_question}. {action['detail']} "
            f"Open {action['target_tab']} and use the Autonomous Navigator evidence. After that: {if_done}"
        )
    if intent["type"] == "guide_notebook_review":
        action = actions[0]
        guidance = dict_value(action.get("guidance"))
        micro_steps = list_value(guidance.get("next_micro_steps"))
        steps_text = " ".join(f"{index + 1}. {step}" for index, step in enumerate(micro_steps[:4]))
        return (
            f"Notebook guide: {action['label']}. {action['detail']} "
            f"{steps_text} "
            "I will keep notebook source, evidence, figures, and runner records separate so Preview is not confused with executed marimo output."
        )
    artifact = next((action.get("artifact_id") for action in actions if action.get("artifact_id")), None)
    artifact_note = f" It is registered as artifact `{artifact}` for lineage and review." if artifact else ""
    return (
        "I prepared a controlled runner task and put it in Approach. It carries the current data context, "
        "evaluation locks, safety boundaries, expected artifacts, and reporting requirements, while leaving the "
        "actual modeling approach open for Codex to choose from evidence and Skills."
        f"{artifact_note} Next: review the runner task in Approach, then run a controlled runner when you want it to act."
    )

def build_action_summary(intent: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    applied = [action for action in actions if action.get("status") == "applied"]
    review = [action for action in actions if action.get("status") == "needs_review"]
    planned = [action for action in actions if action.get("status") in {"created", "recorded", "explained"}]
    focus = next_focus_from_actions(actions)
    outcome = "needs_review" if review else "applied" if applied else "planned" if planned else "noted"
    headline = action_summary_headline(intent, outcome)
    what_changed = [
        str(action["label"])
        for action in actions
        if action.get("status") in {"applied", "recorded", "created", "explained"} and action.get("label")
    ]
    what_needs_review = [str(action["label"]) for action in review if action.get("label")]
    boundaries = action_summary_boundaries(intent, actions)
    return {
        "schema_version": "agent_action_summary.v1",
        "outcome": outcome,
        "headline": headline,
        "what_changed": what_changed[:4],
        "what_needs_review": what_needs_review[:4],
        "next_step": {
            "label": focus.get("label"),
            "target_tab": focus.get("target_tab"),
            "target_anchor": focus.get("target_anchor"),
            "status": focus.get("status"),
        },
        "boundaries": boundaries,
        "actions": [
            {
                "type": action.get("type"),
                "status": action.get("status"),
                "label": action.get("label"),
                "target_tab": action.get("target_tab"),
                "target_anchor": action.get("target_anchor"),
                "detail": action.get("detail"),
            }
            for action in actions[:5]
        ],
    }


def action_summary_headline(intent: dict[str, Any], outcome: str) -> str:
    intent_type = str(intent.get("type") or "")
    if intent_type == "set_evaluation_metric":
        metric = SUPPORTED_METRICS[str(intent["metric"])]["label"]
        if outcome == "needs_review":
            return f"{metric} request recorded for review"
        if outcome == "applied":
            return f"{metric} applied where it is safe"
        return f"{metric} preference recorded"
    if intent_type == "run_eda_review":
        return "Data Review is ready" if outcome == "applied" else "Data Review needs a dataset first"
    if intent_type == "show_relational_map":
        return "Relational map is ready" if outcome != "needs_review" else "Relational evidence is needed"
    if intent_type == "run_data_quality":
        return "Data quality gate is ready" if outcome == "applied" else "Data quality needs data first"
    if intent_type == "design_evaluation":
        return "Evaluation candidates are ready" if outcome == "applied" else "Evaluation design needs data first"
    if intent_type == "compare_evaluation_scenarios":
        return "Evaluation scenarios compared" if outcome == "applied" else "Evaluation comparison needs data first"
    if intent_type == "plan_baseline_strategy":
        return "Baseline strategy plan is ready" if outcome == "applied" else "Baseline strategy needs evaluation context"
    if intent_type == "run_model_candidates":
        return "Model training started" if outcome in {"applied", "needs_review"} else "Model training needs attention"
    if intent_type == "generate_decision_report":
        return "Decision report is ready" if outcome == "applied" else "Decision report needs review"
    if intent_type == "show_leaderboard":
        return "Result readout is ready" if outcome != "needs_review" else "Result readout needs run evidence"
    if intent_type == "compare_top_runs":
        return "Run evidence compared" if outcome == "applied" else "Run comparison needs successful runs"
    if intent_type == "post_run_reading_workflow":
        return "Post-run reading pack is ready" if outcome == "applied" else "Post-run reading needs successful runs"
    if intent_type == "prepare_result_notebook_evidence":
        return "Result notebook evidence is ready" if outcome == "applied" else "Result notebook evidence needs a successful run"
    if intent_type == "generate_data_understanding_notebook":
        return "Notebook evidence generated"
    if intent_type == "author_analysis_notebook":
        return "Notebook authoring handoff prepared"
    if intent_type == "plan_notebook_followup_task":
        return "Notebook follow-up task prepared"
    if intent_type == "explain_next_step":
        return "Next decision selected"
    if intent_type == "guide_notebook_review":
        return "Analysis reading path selected"
    return "Controlled runner task prepared"


def action_summary_boundaries(intent: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    boundaries = ["Tablex keeps artifacts, lineage, safety policy, and approvals in the harness."]
    intent_type = str(intent.get("type") or "")
    if intent_type == "set_evaluation_metric":
        boundaries.append("Approved EvaluationSpecs and SplitManifests are not destructively changed by chat.")
    if intent_type == "show_relational_map":
        boundaries.append("Uploaded or inferred ER edges are evidence, not confirmed join contracts.")
    if intent_type == "run_data_quality":
        boundaries.append("Quality gates create evidence and questions; they do not silently drop rows or features.")
    if intent_type in {"design_evaluation", "compare_evaluation_scenarios"}:
        boundaries.append("Evaluation Chat actions draft or compare designs; approval and SplitManifest generation remain explicit.")
    if intent_type == "plan_baseline_strategy":
        boundaries.append("Baseline strategy is an evidence-backed plan, not a fixed AutoML recipe or deployment approval.")
    if intent_type == "run_model_candidates":
        boundaries.append("Training uses the approved EvaluationSpec and SplitManifest; leaderboard rows remain comparable.")
        boundaries.append("Dependency changes require an explicit approval path instead of silent package installation.")
    if intent_type == "generate_decision_report":
        boundaries.append("Decision reports summarize current evidence; missing evidence remains visible instead of being invented.")
    if intent_type in {"show_leaderboard", "compare_top_runs", "post_run_reading_workflow", "prepare_result_notebook_evidence"}:
        boundaries.append("Leaderboard ranks are decision evidence only under the same EvaluationSpec and SplitManifest context.")
    if intent_type == "post_run_reading_workflow":
        boundaries.append("Post-run reports expose missing diagnostics instead of inventing model evidence.")
    if intent_type == "prepare_result_notebook_evidence":
        boundaries.append("Notebook evidence is generated and safely captured from harness-owned artifacts; cells are not executed by this action.")
    if intent_type == "plan_notebook_followup_task":
        boundaries.append("Notebook follow-up diagnostics must be artifact-backed and must not fake unavailable model evidence.")
        boundaries.append("EvaluationSpec and SplitManifest remain read-only constraints for the runner.")
    if any(action.get("type") in {"create_agent_task_contract", "create_notebook_followup_task"} for action in actions):
        boundaries.append("Codex runner autonomy starts inside the generated AgentTaskContract, not outside the workbench.")
    if any(action.get("target_tab") == "Notebooks" for action in actions):
        boundaries.append("Notebook previews are in-product artifacts; executed notebook claims still need captured evidence.")
    return boundaries[:4]


def estimate_token_series(message: str, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = max(12, len(message.split()) * 2)
    context = base + 180 + 30 * len(actions)
    plan = context + 120
    output = plan + 80 + 35 * len(actions)
    return [
        {"step": "read request", "tokens": base},
        {"step": "load context", "tokens": context},
        {"step": "plan action", "tokens": plan},
        {"step": "write response", "tokens": output},
    ]


def build_worker_events(
    job: Job,
    intent: dict[str, Any],
    actions: list[dict[str, Any]],
    token_series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status = "needs_review" if any(action["status"] == "needs_review" for action in actions) else "completed"
    return [
        {
            "worker_id": "agent-chat-orchestrator",
            "display_name": "Tablee Orchestrator",
            "status": status,
            "headline": intent["summary"],
            "detail": "; ".join(str(action["label"]) for action in actions[:3]),
            "job_id": job.id,
            "target_tab": next_focus_from_actions(actions).get("target_tab"),
            "target_anchor": next_focus_from_actions(actions).get("target_anchor"),
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "active": False,
            "token_usage": {
                "source": "estimated_until_runner_telemetry",
                "is_estimate": True,
                "series": token_series,
            },
        }
    ]


def next_focus_from_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    materialized_model_evidence = next(
        (
            action
            for action in actions
            if action.get("type") == "materialize_model_diagnostics_artifacts"
            and action.get("status") == "applied"
            and action.get("target_tab")
        ),
        None,
    )
    if materialized_model_evidence:
        return {
            "target_tab": materialized_model_evidence["target_tab"],
            "target_anchor": materialized_model_evidence.get("target_anchor"),
            "label": materialized_model_evidence["label"],
            "status": materialized_model_evidence["status"],
        }
    for action in actions:
        if action.get("target_tab"):
            return {
                "target_tab": action["target_tab"],
                "target_anchor": action.get("target_anchor"),
                "label": action["label"],
                "status": action["status"],
            }
    return {"target_tab": "Approach", "label": "Review Agent activity", "status": "created"}
