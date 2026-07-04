from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Job,
    Project,
    Question,
    Report,
    SplitManifest,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.locales import locale_is_japanese


@dataclass(frozen=True)
class AdaptiveStrategyBriefResult:
    brief: dict[str, Any]
    artifact: Artifact
    report: Report
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


STRATEGY_SOURCE_TYPES = [
    "eda_profile",
    "semantic_catalog",
    "data_quality_gate",
    "evaluation_scenario_comparison",
    "evaluation_approval_review",
    "evaluation_spec",
    "split_manifest",
    "research_plan",
    "research_source_pack",
    "research_finding_synthesis",
    "baseline_strategy_plan",
    "agent_task_contract",
    "approach_candidate",
    "relational_catalog",
    "relational_feature_plan",
    "relational_feature_recipe",
    "relational_feature_scenario_diagnostics",
    "decision_dashboard",
    "baseline_report",
    "run_report",
    "visualization_spec",
    "adaptive_strategy_brief",
]


def build_adaptive_strategy_brief(db: Session, *, project: Project, locale: str | None = None) -> dict[str, Any]:
    dataset = latest_dataset(db, project.id)
    evaluation_spec = latest_approved_spec(db, project.id)
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    latest_artifacts = latest_artifacts_by_type(db, project.id, STRATEGY_SOURCE_TYPES)
    ideas = list_project_ideas(db, project.id)
    runs = list_project_runs(db, project.id)
    assumptions = list_open_assumptions(db, project.id)
    questions = list_open_questions(db, project.id)
    lanes = build_candidate_lanes(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        latest_artifacts=latest_artifacts,
        ideas=ideas,
        runs=runs,
        assumptions=assumptions,
        questions=questions,
    )
    recommended_next_action = choose_next_action(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        latest_artifacts=latest_artifacts,
        ideas=ideas,
        runs=runs,
        assumptions=assumptions,
        questions=questions,
    )
    artifact_refs = [artifact_ref(artifact) for artifact in latest_artifacts.values()]
    risk_register = build_risk_register(assumptions=assumptions, questions=questions, latest_artifacts=latest_artifacts)
    profile_summary = profile_summary_from_artifact(latest_artifacts.get("eda_profile"))
    latest_brief_artifact = latest_artifacts.get("adaptive_strategy_brief")
    brief = {
        "schema_version": "adaptive_strategy_brief.v1",
        "response_locale": locale,
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "summary": {
            "dataset_snapshot_id": dataset.id if dataset else None,
            "row_count": dataset.row_count if dataset else None,
            "column_count": dataset.column_count if dataset else None,
            "approved_evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
            "idea_count": len(ideas),
            "experiment_run_count": len(runs),
            "open_assumption_count": len(assumptions),
            "open_question_count": len(questions),
            "artifact_count": len(latest_artifacts),
            "profile": profile_summary,
            "strategy_mode": "adaptive_codex_guided",
            "fixed_recipe_policy": "advisory_candidates_only",
        },
        "recommended_next_action": recommended_next_action,
        "candidate_lanes": lanes,
        "codex_handoff": build_codex_handoff(
            project=project,
            dataset=dataset,
            evaluation_spec=evaluation_spec,
            split_manifest=split_manifest,
            latest_artifacts=latest_artifacts,
            ideas=ideas,
            recommended_next_action=recommended_next_action,
            profile_summary=profile_summary,
        ),
        "reporting_plan": build_reporting_plan(latest_artifacts=latest_artifacts, runs=runs),
        "artifact_refs": artifact_refs,
        "risk_register": risk_register,
        "latest_artifact_id": latest_brief_artifact.id if latest_brief_artifact else None,
        "generated_at": utc_now().isoformat(),
    }
    return with_strategy_display_locale(brief, locale=locale)


def create_adaptive_strategy_brief(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
    locale: str | None = None,
) -> AdaptiveStrategyBriefResult:
    brief = build_adaptive_strategy_brief(db, project=project, locale=locale)
    source_artifact_ids = [str(item["artifact_id"]) for item in brief["artifact_refs"] if item.get("artifact_id")]
    name_suffix = job.id if job else new_id("strategy")
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="adaptive_strategy_brief",
        name=f"adaptive_strategy_brief_{name_suffix}",
        filename="adaptive_strategy_brief.json",
        payload=brief,
        metadata={
            "project_id": project.id,
            "recommended_action_type": brief["recommended_next_action"]["action_type"],
            "recommended_label": brief["recommended_next_action"]["label"],
            "lane_count": len(brief["candidate_lanes"]),
            "source_artifact_count": len(source_artifact_ids),
            "open_assumption_count": brief["summary"]["open_assumption_count"],
            "open_question_count": brief["summary"]["open_question_count"],
        },
    )
    report_md = render_strategy_report(brief)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="adaptive_strategy_report",
        name=f"adaptive_strategy_report_{name_suffix}",
        filename="adaptive_strategy_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "adaptive_strategy_brief_artifact_id": artifact.id,
            "recommended_action_type": brief["recommended_next_action"]["action_type"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="adaptive_strategy_report",
        title=f"{project.name} Adaptive Strategy Report",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": artifact.id}]),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_strategy_visualization_spec(brief)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"adaptive_strategy_visualization_{name_suffix}",
        filename="adaptive_strategy_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "source_artifact_id": artifact.id,
            "chart_type": visualization_payload["chart_type"],
            "visualization_scope": "adaptive_strategy",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title=visualization_payload["title"],
        chart_type=visualization_payload["chart_type"],
        spec_json=dumps_json(visualization_payload["spec"]),
        source_artifact_id=artifact.id,
        artifact_id=visualization_artifact.id,
        status="draft",
        created_by_type="system",
    )
    db.add(visualization)
    db.flush()
    create_lineage_edges(
        db,
        project=project,
        strategy_artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        source_artifact_ids=source_artifact_ids,
    )
    artifact_ids = [artifact.id, report_artifact.id, visualization_artifact.id]
    return AdaptiveStrategyBriefResult(
        brief=brief,
        artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def build_candidate_lanes(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    latest_artifacts: dict[str, Artifact],
    ideas: list[Idea],
    runs: list[ExperimentRun],
    assumptions: list[Assumption],
    questions: list[Question],
) -> list[dict[str, Any]]:
    has_blocking_review = any(assumption.fallback_policy == "block_until_answered" for assumption in assumptions) or any(
        question.fallback_policy == "block_until_answered" for question in questions
    )
    return [
        lane(
            lane_id="data_understanding",
            title="Understand data before choosing the task shape",
            status="ready" if dataset and latest_artifacts.get("eda_profile") else "needs_context",
            why=(
                "Profile and semantic artifacts are available."
                if dataset and latest_artifacts.get("eda_profile")
                else "Upload data or run profiling before selecting a task objective and approach."
            ),
            evidence_artifacts=[latest_artifacts.get("eda_profile"), latest_artifacts.get("semantic_catalog")],
            next_action="Inspect Data and Understanding",
            agent_role="Summarize task ambiguity, possible objectives, prediction units, and data meaning gaps.",
        ),
        lane(
            lane_id="assumption_review",
            title="Review assumptions without blocking exploration",
            status="needs_review" if assumptions or questions else "ready",
            why=(
                "Some assumptions or questions can affect leakage, objective definition, or deployment fit."
                if assumptions or questions
                else "No open assumption or question currently needs attention."
            ),
            evidence_artifacts=[latest_artifacts.get("data_quality_gate"), latest_artifacts.get("evaluation_approval_review")],
            next_action="Review the prioritized queue",
            agent_role="Keep uncertainty explicit and use fallback policies rather than waiting indefinitely.",
            extra={"blocking_review": has_blocking_review, "open_items": len(assumptions) + len(questions)},
        ),
        lane(
            lane_id="evaluation_lock",
            title="Lock evaluation before comparing approaches",
            status="ready" if evaluation_spec and split_manifest else "needs_decision",
            why=(
                "Approved EvaluationSpec and SplitManifest are available."
                if evaluation_spec and split_manifest
                else "Candidate approaches should not be trusted until a primary evaluation design exists."
            ),
            evidence_artifacts=[
                latest_artifacts.get("evaluation_scenario_comparison"),
                latest_artifacts.get("evaluation_spec"),
                latest_artifacts.get("split_manifest"),
            ],
            next_action="Adopt or generate EvaluationSpec and SplitManifest",
            agent_role="Treat the split manifest as immutable input for implementation work.",
        ),
        lane(
            lane_id="research_and_skills",
            title="Use Skills and controlled research as context, not a gate",
            status="ready" if latest_artifacts.get("research_plan") else "needs_context",
            why=(
                "Research planning artifacts exist for Codex handoff."
                if latest_artifacts.get("research_plan")
                else "Generate a ResearchPlan so Codex can use project artifacts, Skills, and controlled source slots."
            ),
            evidence_artifacts=[
                latest_artifacts.get("research_plan"),
                latest_artifacts.get("research_source_pack"),
                latest_artifacts.get("research_finding_synthesis"),
            ],
            next_action="Create or refresh ResearchPlan",
            agent_role="Use source-backed findings when available; otherwise mark claims as assumptions.",
        ),
        lane(
            lane_id="adaptive_baseline",
            title="Plan a strong but non-prescriptive baseline",
            status="ready" if latest_artifacts.get("baseline_strategy_plan") else "needs_plan",
            why=(
                "Baseline strategy exists and can inform, not constrain, Codex."
                if latest_artifacts.get("baseline_strategy_plan")
                else "Plan candidate baseline families after the objective and evaluation are known."
            ),
            evidence_artifacts=[latest_artifacts.get("baseline_strategy_plan"), latest_artifacts.get("baseline_report")],
            next_action="Plan baseline strategy or run baseline",
            agent_role=(
                "Consider XGBoost, categorical encodings, TF-IDF, temporal features, and sanity floors when evidence supports them; "
                "replace them with a better justified approach when warranted."
            ),
        ),
        lane(
            lane_id="codex_approach_space",
            title="Ask Codex for the next project-specific approach",
            status="ready" if latest_artifacts.get("agent_task_contract") or ideas else "needs_handoff",
            why=(
                "AgentTaskContracts or Ideas exist for controlled runner handoff."
                if latest_artifacts.get("agent_task_contract") or ideas
                else "Create a harness-owned AgentTaskContract before asking Codex to implement or revise an approach."
            ),
            evidence_artifacts=[latest_artifacts.get("agent_task_contract"), latest_artifacts.get("approach_candidate")],
            next_action="Plan AgentTaskContract",
            agent_role="Propose, reject, or revise approaches with a decision trace; do not execute a fixed catalog blindly.",
        ),
        lane(
            lane_id="reporting_and_visuals",
            title="Make results explainable inside the product",
            status="ready" if runs and latest_artifacts.get("visualization_spec") else "needs_outputs",
            why=(
                "Runs and visualization specs are available for in-product reporting."
                if runs and latest_artifacts.get("visualization_spec")
                else "Every experiment should emit report, metrics, feature recipe, evidence, and visualization outputs."
            ),
            evidence_artifacts=[latest_artifacts.get("run_report"), latest_artifacts.get("visualization_spec")],
            next_action="Generate reports and visualizations after the next run",
            agent_role="Return report-ready summaries, chart specs, error slices, and limitations.",
        ),
    ]


def choose_next_action(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    latest_artifacts: dict[str, Artifact],
    ideas: list[Idea],
    runs: list[ExperimentRun],
    assumptions: list[Assumption],
    questions: list[Question],
) -> dict[str, Any]:
    blocking_count = len([item for item in assumptions if item.fallback_policy == "block_until_answered"]) + len(
        [item for item in questions if item.fallback_policy == "block_until_answered"]
    )
    if dataset is None:
        return action("navigate", "Upload data", "Data", "A project-specific strategy needs at least one DatasetSnapshot.")
    if not project.target_column:
        return action(
            "agent_task",
            "Explore objective candidates",
            "Understanding",
            "The objective may be supervised, derived by aggregation, unsupervised, inverse-problem oriented, or otherwise project-specific; ask Codex for an objective-definition review.",
            prompt=target_review_prompt(project),
        )
    if assumptions and blocking_count:
        return action(
            "navigate",
            "Resolve blocking assumptions",
            "Assumptions",
            "Some fallback policies require answers before deployment-sensitive work proceeds.",
        )
    if evaluation_spec is None or split_manifest is None:
        return action(
            "navigate",
            "Lock evaluation design",
            "Evaluation",
            "Flexible approaches need an approved EvaluationSpec and SplitManifest before performance claims.",
        )
    if latest_artifacts.get("research_plan") is None:
        return action(
            "api",
            "Create ResearchPlan",
            "Approach",
            "Codex should receive project context, Skill hooks, and controlled research slots before strategy work.",
            endpoint=f"/api/projects/{project.id}/approach/research-plan",
        )
    if latest_artifacts.get("baseline_strategy_plan") is None:
        return action(
            "api",
            "Plan adaptive baseline",
            "Experiments",
            "Create the strong-baseline strategy artifact as evidence, while keeping it advisory rather than mandatory.",
            endpoint=f"/api/projects/{project.id}/baseline/strategy-plan",
        )
    if latest_artifacts.get("agent_task_contract") is None and not ideas:
        return action(
            "api",
            "Plan Codex AgentTask",
            "Approach",
            "The next implementation should be a harness-owned contract with open-ended approach space and explicit outputs.",
            endpoint=f"/api/projects/{project.id}/approach/agent-task-plan",
        )
    if not runs:
        return action(
            "agent_task",
            "Run or prepare the first approach",
            "Approach",
            "There are strategy artifacts but no run evidence yet; use Codex or the local baseline to generate reportable results.",
            prompt=implementation_prompt(project),
        )
    return action(
        "api",
        "Refresh decision report",
        "Overview",
        "Runs exist; synthesize metrics, risks, visuals, and next experiments for an in-product decision view.",
        endpoint=f"/api/projects/{project.id}/decision-dashboard/generate",
    )


def with_strategy_display_locale(brief: dict[str, Any], *, locale: str | None) -> dict[str, Any]:
    if not locale_is_japanese(locale):
        return brief
    for lane_payload in brief.get("candidate_lanes", []):
        if isinstance(lane_payload, dict):
            lane_payload.update(strategy_lane_display_ja(lane_payload))
    action_payload = brief.get("recommended_next_action")
    if isinstance(action_payload, dict):
        action_payload.update(strategy_action_display_ja(action_payload))
    return brief


def strategy_lane_display_ja(lane_payload: dict[str, Any]) -> dict[str, Any]:
    lane_id = str(lane_payload.get("lane_id") or "")
    status = str(lane_payload.get("status") or "")
    copy: dict[str, dict[str, str]] = {
        "data_understanding": {
            "title": "データ理解を先に固める",
            "why_ready": "プロファイルとセマンティックカタログが利用できます。",
            "why_other": "目的やアプローチ選定の前に、データ投入またはプロファイル作成が必要です。",
            "next_action": "DataとUnderstandingを確認する",
            "agent_role": "タスクの曖昧さ、目的候補、予測単位、データ意味の不足を整理します。",
        },
        "assumption_review": {
            "title": "探索を止めずに仮定を見直す",
            "why_ready": "現時点で優先確認すべき仮定や質問はありません。",
            "why_other": "一部の仮定や質問が、漏洩、目的定義、運用適合性に影響し得ます。",
            "next_action": "優先確認キューを見る",
            "agent_role": "不確実性を明示し、無期限停止ではなくfallback policyで前に進めます。",
        },
        "evaluation_lock": {
            "title": "アプローチ比較の前に評価を固定する",
            "why_ready": "採用済みEvaluationSpecとSplitManifestがあります。",
            "why_other": "primary評価設計がないまま候補アプローチの性能を信用すべきではありません。",
            "next_action": "EvaluationSpecとSplitManifestを採用または生成する",
            "agent_role": "SplitManifestを実装作業の不変入力として扱います。",
        },
        "research_and_skills": {
            "title": "Skillと調査を文脈として使う",
            "why_ready": "Codexへ渡す調査計画のartifactがあります。",
            "why_other": "CodexがProject artifact、Skill、制御された情報源を使えるようResearchPlanが必要です。",
            "next_action": "ResearchPlanを作成または更新する",
            "agent_role": "根拠付き知見を使い、根拠が薄い主張は仮定として扱います。",
        },
        "adaptive_baseline": {
            "title": "固定recipeではない強いベースラインを計画する",
            "why_ready": "ベースライン戦略はCodexを縛らず、判断材料として使えます。",
            "why_other": "目的と評価が見えた後に、候補となるベースライン群を計画します。",
            "next_action": "ベースライン戦略を計画または実行する",
            "agent_role": "根拠があればXGBoost、カテゴリ変換、TF-IDF、時系列特徴、sanity floorを検討し、より妥当な案があれば置き換えます。",
        },
        "codex_approach_space": {
            "title": "Project固有の次アプローチをCodexに考えさせる",
            "why_ready": "AgentTaskContractまたはIdeaがrunner handoff用に存在します。",
            "why_other": "実装や改良をCodexに頼む前に、ハーネス所有のAgentTaskContractが必要です。",
            "next_action": "AgentTaskContractを計画する",
            "agent_role": "固定カタログを盲目的に実行せず、提案・却下・修正を判断履歴つきで進めます。",
        },
        "reporting_and_visuals": {
            "title": "結果をプロダクト内で説明可能にする",
            "why_ready": "プロダクト内レポートに使えるRunと可視化仕様があります。",
            "why_other": "各実験はreport、metric、feature recipe、evidence、visualizationを出すべきです。",
            "next_action": "次のRun後にレポートと可視化を生成する",
            "agent_role": "レポート可能な要約、図表仕様、誤差slice、限界を返します。",
        },
    }
    lane_copy = copy.get(lane_id)
    if not lane_copy:
        return {}
    why_key = "why_ready" if status == "ready" else "why_other"
    return {
        "display_title": lane_copy["title"],
        "display_why": lane_copy[why_key],
        "display_next_action": lane_copy["next_action"],
        "display_agent_role": lane_copy["agent_role"],
        "display": {
            "title": lane_copy["title"],
            "why": lane_copy[why_key],
            "next_action": lane_copy["next_action"],
            "agent_role": lane_copy["agent_role"],
        },
    }


def strategy_action_display_ja(action_payload: dict[str, Any]) -> dict[str, Any]:
    label = str(action_payload.get("label") or "")
    copy: dict[str, tuple[str, str]] = {
        "Upload data": (
            "データをアップロードする",
            "Project固有の戦略には、少なくとも1つのデータスナップショットが必要です。",
        ),
        "Explore objective candidates": (
            "目的候補を探索する",
            "目的は列、派生集計、教師なし、逆問題などもあり得るため、Codexに目的定義レビューを依頼します。",
        ),
        "Resolve blocking assumptions": (
            "ブロッキング仮定を確認する",
            "一部のfallback policyは、デプロイに近い判断の前に確認が必要です。",
        ),
        "Lock evaluation design": (
            "評価設計を固定する",
            "柔軟なアプローチでも、性能主張の前にEvaluationSpecとSplitManifestが必要です。",
        ),
        "Create ResearchPlan": (
            "ResearchPlanを作成する",
            "戦略作業の前に、CodexへProject context、Skill hook、制御された調査枠を渡します。",
        ),
        "Plan adaptive baseline": (
            "適応的ベースラインを計画する",
            "強いベースライン戦略を証拠として作成します。ただしCodexを縛る必須recipeにはしません。",
        ),
        "Plan Codex AgentTask": (
            "Codex AgentTaskを計画する",
            "次の実装は、開かれたアプローチ空間と明示的な出力を持つハーネス所有contractにします。",
        ),
        "Run or prepare the first approach": (
            "最初のアプローチを走らせる",
            "戦略artifactはありますがRun evidenceがまだないため、Codexまたはローカルbaselineで報告可能な結果を作ります。",
        ),
        "Refresh decision report": (
            "意思決定レポートを更新する",
            "既存Runからmetric、risk、visual、次実験を統合し、プロダクト内で判断できる形にします。",
        ),
    }
    localized = copy.get(label)
    if not localized:
        return {}
    display_label, display_reason = localized
    return {
        "display_label": display_label,
        "display_reason": display_reason,
        "display": {"label": display_label, "reason": display_reason},
    }


def build_codex_handoff(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    latest_artifacts: dict[str, Artifact],
    ideas: list[Idea],
    recommended_next_action: dict[str, Any],
    profile_summary: dict[str, Any],
) -> dict[str, Any]:
    suggested_prompt = recommended_next_action.get("prompt") or implementation_prompt(project)
    candidate_signals = {
        "has_text": bool(profile_summary.get("has_text")),
        "has_datetime": bool(profile_summary.get("has_datetime")),
        "has_relational_context": bool(latest_artifacts.get("relational_catalog")),
        "has_research_synthesis": bool(latest_artifacts.get("research_finding_synthesis")),
        "has_baseline_strategy_plan": bool(latest_artifacts.get("baseline_strategy_plan")),
        "idea_count": len(ideas),
    }
    return {
        "runner_role": "AgentRunner implementation engine, not product owner",
        "suggested_objective": suggested_prompt,
        "allowed_research_modes": ["project_artifacts", "skill_library", "controlled_web_search"],
        "autonomy_policy": {
            "can_propose_new_approach_classes": True,
            "can_reject_advisory_candidates": True,
            "must_explain_replacement_approach": True,
            "must_emit_approach_decision_trace": True,
            "must_register_artifacts": True,
            "must_respect_split_manifest": split_manifest is not None,
            "network_default": "disabled_until_runner_policy_allows",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
        "candidate_signals": candidate_signals,
        "context_artifact_ids": {
            key: artifact.id for key, artifact in latest_artifacts.items() if key in STRATEGY_SOURCE_TYPES
        },
        "contract_readiness": {
            "dataset_ready": dataset is not None,
            "evaluation_ready": evaluation_spec is not None and split_manifest is not None,
            "research_ready": latest_artifacts.get("research_plan") is not None,
            "strategy_ready": latest_artifacts.get("baseline_strategy_plan") is not None
            or latest_artifacts.get("agent_task_contract") is not None
            or bool(ideas),
        },
    }


def build_reporting_plan(*, latest_artifacts: dict[str, Artifact], runs: list[ExperimentRun]) -> dict[str, Any]:
    return {
        "required_outputs": [
            "approach_report.md",
            "feature_recipe.json",
            "experiment_metrics.json",
            "visualization_spec.json",
            "evidence.json",
            "approach_decision_trace.json",
        ],
        "in_product_surfaces": ["Leaderboard", "Experiments", "Reports", "Lineage", "Decision Dashboard"],
        "current_state": {
            "has_run_report": latest_artifacts.get("run_report") is not None
            or latest_artifacts.get("baseline_report") is not None,
            "has_visualization_spec": latest_artifacts.get("visualization_spec") is not None,
            "run_count": len(runs),
        },
        "guidance": (
            "Prefer concise, visual, report-ready outputs over raw metric dumps. "
            "Every runner result should explain why the approach was chosen, what was rejected, and what remains uncertain."
        ),
    }


def build_risk_register(
    *,
    assumptions: list[Assumption],
    questions: list[Question],
    latest_artifacts: dict[str, Artifact],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for assumption in assumptions[:8]:
        risks.append(
            {
                "risk_type": "assumption",
                "id": assumption.id,
                "summary": assumption.statement,
                "risk_level": assumption.risk_level,
                "status": assumption.status,
                "fallback_policy": assumption.fallback_policy,
            }
        )
    for question in questions[:8]:
        risks.append(
            {
                "risk_type": "question",
                "id": question.id,
                "summary": question.question,
                "risk_level": question.risk_level,
                "status": question.status,
                "fallback_policy": question.fallback_policy,
            }
        )
    quality = latest_artifacts.get("data_quality_gate")
    if quality:
        metadata = loads_json(quality.metadata_json, {})
        severity = metadata.get("severity") or metadata.get("gate_severity")
        if severity in {"warning", "fail", "blocked"}:
            risks.append(
                {
                    "risk_type": "data_quality",
                    "id": quality.id,
                    "summary": "Data quality gate has warnings; inspect leakage and availability evidence before trusting metrics.",
                    "risk_level": str(severity),
                    "status": "needs_review",
                    "fallback_policy": "scenario_compare",
                }
            )
    return risks


def render_strategy_report(brief: dict[str, Any]) -> str:
    action_payload = brief["recommended_next_action"]
    lanes = brief["candidate_lanes"]
    lane_lines = "\n".join(
        f"- **{lane['title']}**: {lane['status']} - {lane['why']}" for lane in lanes
    )
    risks = brief.get("risk_register", [])
    risk_lines = "\n".join(
        f"- {risk['risk_type']}: {risk['summary']} ({risk.get('risk_level', 'unknown')})" for risk in risks[:8]
    )
    if not risk_lines:
        risk_lines = "- No open high-signal strategy risks are currently registered."
    return f"""# Adaptive Strategy Brief

## Recommended Next Action

**{action_payload['label']}**
{action_payload['reason']}

Target tab: `{action_payload.get('target_tab') or '-'}`

## Strategy Position

- Mode: `{brief['summary']['strategy_mode']}`
- Fixed recipe policy: `{brief['summary']['fixed_recipe_policy']}`
- Dataset: `{brief['summary'].get('dataset_snapshot_id') or '-'}`
- EvaluationSpec: `{brief['summary'].get('approved_evaluation_spec_id') or '-'}`
- SplitManifest: `{brief['summary'].get('split_manifest_id') or '-'}`
- Ideas: `{brief['summary']['idea_count']}`
- Runs: `{brief['summary']['experiment_run_count']}`

## Lanes

{lane_lines}

## Codex Handoff

{brief['codex_handoff']['suggested_objective']}

Codex may propose or reject approach classes, but must preserve EvaluationSpec, SplitManifest, artifact registration,
reporting outputs, and the secret/connector boundary.

## Reporting Plan

Required outputs: {', '.join(brief['reporting_plan']['required_outputs'])}

## Risks

{risk_lines}
"""


def build_strategy_visualization_spec(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Adaptive Strategy Lane Readiness",
        "chart_type": "strategy_lane_strip",
        "spec": {
            "marks": [
                {
                    "lane_id": lane["lane_id"],
                    "label": lane["title"],
                    "status": lane["status"],
                    "evidence_count": len(lane.get("evidence_artifact_ids", [])),
                    "next_action": lane["next_action"],
                }
                for lane in brief["candidate_lanes"]
            ],
            "encoding": {
                "x": "lane_id",
                "color": "status",
                "tooltip": ["label", "status", "next_action", "evidence_count"],
            },
        },
    }


def create_lineage_edges(
    db: Session,
    *,
    project: Project,
    strategy_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
    source_artifact_ids: list[str],
) -> None:
    for source_id in source_artifact_ids[:24]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_id,
            to_asset_type="artifact",
            to_asset_id=strategy_artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=strategy_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=strategy_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarizes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="visualization_spec",
        from_asset_id=visualization.id,
        to_asset_type="artifact",
        to_asset_id=visualization_artifact.id,
        relation_type="materializes",
    )


def lane(
    *,
    lane_id: str,
    title: str,
    status: str,
    why: str,
    evidence_artifacts: list[Artifact | None],
    next_action: str,
    agent_role: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "lane_id": lane_id,
        "title": title,
        "status": status,
        "why": why,
        "evidence_artifact_ids": [artifact.id for artifact in evidence_artifacts if artifact is not None],
        "next_action": next_action,
        "agent_role": agent_role,
    }
    if extra:
        payload.update(extra)
    return payload


def action(
    action_type: str,
    label: str,
    target_tab: str,
    reason: str,
    *,
    endpoint: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "label": label,
        "target_tab": target_tab,
        "reason": reason,
        "endpoint": endpoint,
        "method": "POST" if endpoint else None,
        "prompt": prompt,
    }


def artifact_ref(artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "created_at": artifact.created_at.isoformat(),
        "metadata": {
            key: metadata.get(key)
            for key in [
                "dataset_snapshot_id",
                "evaluation_spec_id",
                "split_manifest_id",
                "strategy_count",
                "recommended_action_type",
                "query_count",
                "finding_count",
                "chart_type",
            ]
            if key in metadata
        },
    }


def profile_summary_from_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"available": False}
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "available": True,
        "row_count": metadata.get("row_count"),
        "column_count": metadata.get("column_count"),
        "has_text": bool(metadata.get("has_text")),
        "has_datetime": bool(metadata.get("has_datetime")),
        "profile_mode": metadata.get("profile_mode"),
        "artifact_id": artifact.id,
    }


def target_review_prompt(project: Project) -> str:
    return (
        f"For project `{project.name}`, review the profiled data and propose task-objective options. "
        "The objective may be an existing supervised target, a derived aggregate outcome, a distributional or time-to-event target, "
        "an unsupervised objective such as clustering/anomaly detection, or an inverse-problem/optimization workflow. "
        "Return assumptions, required evidence, rejected objective options, and a recommended next evaluation design. "
        "Do not read secrets or connector credentials."
    )


def implementation_prompt(project: Project) -> str:
    return (
        f"For project `{project.name}`, propose the next project-specific prediction approach. "
        "Use current DatasetSnapshot, SemanticCatalog, Assumptions, EvaluationSpec, SplitManifest, Skill assets, "
        "and controlled research artifacts. Consider strong tabular baselines such as gradient boosting, categorical "
        "encoding, TF-IDF for available text, temporal features, or relational aggregation only when evidence supports "
        "them. You may reject advisory candidates and propose another approach, but explain the decision trace and "
        "produce report, metrics, feature recipe, visualization spec, and evidence artifacts."
    )


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest)
        .where(SplitManifest.evaluation_spec_id == spec_id)
        .order_by(SplitManifest.created_at.desc())
    )


def latest_artifacts_by_type(db: Session, project_id: str, asset_types: list[str]) -> dict[str, Artifact]:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type.in_(asset_types))
        .order_by(Artifact.created_at.desc())
    ).all()
    by_type: dict[str, Artifact] = {}
    for artifact in artifacts:
        by_type.setdefault(artifact.asset_type, artifact)
    return by_type


def list_project_ideas(db: Session, project_id: str) -> list[Idea]:
    return list(
        db.scalars(select(Idea).where(Idea.project_id == project_id).order_by(Idea.priority.desc(), Idea.created_at.desc())).all()
    )


def list_project_runs(db: Session, project_id: str) -> list[ExperimentRun]:
    return list(
        db.scalars(
            select(ExperimentRun).where(ExperimentRun.project_id == project_id).order_by(ExperimentRun.started_at.desc())
        ).all()
    )


def list_open_assumptions(db: Session, project_id: str) -> list[Assumption]:
    closed_statuses = {"confirmed", "challenged", "rejected", "resolved", "retired"}
    return list(
        db.scalars(
            select(Assumption)
            .where(Assumption.project_id == project_id, Assumption.status.not_in(closed_statuses))
            .order_by(Assumption.created_at.desc())
        ).all()
    )


def list_open_questions(db: Session, project_id: str) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .where(Question.project_id == project_id, Question.status == "open")
            .order_by(Question.created_at.desc())
        ).all()
    )
