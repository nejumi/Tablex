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
from tabular_harness.services.eda_review import create_dataset_eda_review
from tabular_harness.services.evaluation import (
    spec_to_dict,
    write_candidates_artifact,
    write_spec_artifact,
)
from tabular_harness.services.notebook_authoring import create_notebook_authoring_brief
from tabular_harness.services.project_guidance import build_project_guidance

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

    assistant_message = render_assistant_message(intent, actions)
    token_series = estimate_token_series(message, actions)
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": message,
        "assistant_message": assistant_message,
        "intent": intent,
        "actions": actions,
        "action_summary": build_action_summary(intent, actions),
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
    notebook_id = extract_notebook_artifact_id(message)
    story_ref = extract_analysis_story_ref(message)
    if is_notebook_authoring_request(normalized):
        return {
            "type": "author_analysis_notebook",
            "metric": None,
            "confidence": 0.88,
            "summary": "User wants Codex to write or revise a high-quality analysis notebook from current evidence.",
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
    comparable = normalized.replace("_", " ").replace("-", " ")
    for metric, config in SUPPORTED_METRICS.items():
        for alias in config["aliases"]:
            comparable_alias = alias.replace("_", " ").replace("-", " ")
            if comparable_alias in comparable:
                return metric
    return None


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
    if not has_scoped_source and not any(word in normalized for word in ["notebook", "ノートブック", "analysis story"]):
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


def append_decision_note(existing: str, note: str) -> str:
    if note in existing:
        return existing
    return f"{existing.rstrip()}\n\nDecision note: {note}".strip()


def render_assistant_message(intent: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    applied = [action for action in actions if action["status"] == "applied"]
    review = [action for action in actions if action["status"] == "needs_review"]
    created = [action for action in actions if action["status"] == "created"]
    recorded = [action for action in actions if action["status"] == "recorded"]
    if intent["type"] == "set_evaluation_metric":
        metric = SUPPORTED_METRICS[str(intent["metric"])]["label"]
        parts = [f"Understood: use {metric} as the evaluation metric."]
        if applied:
            parts.append("I updated mutable evaluation design objects now.")
        if review:
            parts.append("I did not change approved EvaluationSpecs; I created a review artifact instead.")
        if recorded:
            parts.append("There is no evaluation design to edit yet, so I recorded this as a preference for the next design step.")
        if created:
            parts.append("I also prepared a controlled AgentTaskContract for a runner to revise the design safely.")
        parts.append("Next: open Evaluation and review the metric state before running experiments.")
        return " ".join(parts)
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
        return (
            "I turned that notebook follow-up into a controlled diagnostics task, not just a note. "
            f"{action['detail']} Open Approach to review the runner handoff. When executed, Codex should produce "
            "a concise report, figures or visualization specs, evidence bundle, and notebook update only from "
            "available artifacts; if prediction or model evidence is missing, it must say exactly what is missing."
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
    boundaries = [
        "Tablex keeps artifacts, lineage, safety policy, and approvals in the harness.",
    ]
    intent_type = str(intent.get("type") or "")
    if intent_type == "set_evaluation_metric":
        boundaries.append("Approved EvaluationSpecs and SplitManifests are not destructively changed by chat.")
    if intent_type == "show_relational_map":
        boundaries.append("Uploaded or inferred ER edges are evidence, not confirmed join contracts.")
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
    for action in actions:
        if action.get("target_tab"):
            return {
                "target_tab": action["target_tab"],
                "target_anchor": action.get("target_anchor"),
                "label": action["label"],
                "status": action["status"],
            }
    return {"target_tab": "Approach", "label": "Review Agent activity", "status": "created"}
