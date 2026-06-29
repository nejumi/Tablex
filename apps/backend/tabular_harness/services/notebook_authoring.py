from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, DatasetSnapshot, Project, Report
from tabular_harness.services.approach import (
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge


@dataclass(frozen=True)
class NotebookAuthoringBriefResult:
    brief: dict[str, Any]
    brief_artifact: Artifact
    report: Report
    report_artifact: Artifact
    artifact_ids: list[str]


def create_notebook_authoring_brief(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    objective: str | None = None,
) -> NotebookAuthoringBriefResult:
    dataset = latest_dataset(db, project.id)
    context_artifacts = notebook_authoring_context_artifacts(db, project.id)
    brief = build_notebook_authoring_brief(
        project=project,
        dataset=dataset,
        context_artifacts=context_artifacts,
        objective=objective,
    )
    suffix = new_id("nab")
    brief_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_authoring_brief",
        name=f"notebook_authoring_brief_{suffix}",
        filename="notebook_authoring_brief.json",
        payload=brief,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "source_card_count": len(brief["source_inspirations"]),
            "principle_count": len(brief["authoring_principles"]),
            "context_artifact_count": len(brief["context_artifacts"]),
        },
    )
    report_text = render_notebook_authoring_report(brief, brief_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_authoring_report",
        name=f"notebook_authoring_report_{suffix}",
        filename="notebook_authoring_report.md",
        text=report_text,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "notebook_authoring_brief_artifact_id": brief_artifact.id,
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="notebook_authoring_brief",
        title="Notebook Authoring Brief",
        summary=str(brief["objective"]),
        artifact_id=report_artifact.id,
        source_asset_ids_json="[]",
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    for artifact in [artifact for artifact in context_artifacts.values() if artifact is not None]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=brief_artifact.id,
            relation_type="summarized_for_notebook_authoring",
        )
    return NotebookAuthoringBriefResult(
        brief=brief,
        brief_artifact=brief_artifact,
        report=report,
        report_artifact=report_artifact,
        artifact_ids=[brief_artifact.id, report_artifact.id],
    )


def build_notebook_authoring_brief(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    context_artifacts: dict[str, Artifact | None],
    objective: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "notebook_authoring_brief.v1",
        "project_id": project.id,
        "objective": objective
        or (
            "Write or revise a human-facing Tablex analysis notebook from current evidence. "
            "Use the source-backed craft principles as inspiration, not a fixed template."
        ),
        "dataset_context": {
            "dataset_snapshot_id": dataset.id if dataset else None,
            "row_count": dataset.row_count if dataset else None,
            "column_count": dataset.column_count if dataset else None,
            "target_column": project.target_column,
        },
        "source_inspirations": gm_source_cards(),
        "authoring_principles": authoring_principles(),
        "sample_moves": notebook_sample_moves(project),
        "context_artifacts": context_artifact_refs(context_artifacts),
        "codex_contract": {
            "role": "author_the_notebook_on_the_fly",
            "do_not": [
                "Do not merely restyle Tablex static HTML.",
                "Do not copy public notebook text or structure verbatim.",
                "Do not hide missing evidence behind decorative charts.",
                "Do not change EvaluationSpec or SplitManifest.",
            ],
            "must": [
                "Open the latest EDA/Data Review evidence bundle first.",
                "Use current project artifacts as the source of truth.",
                "Write an analyst-readable narrative with findings, evidence, uncertainty, and next actions.",
                "Generate or request real figures/tables where claims need support.",
                "Return notebook source, rendered HTML, figure manifest, and report artifacts.",
            ],
        },
    }


def gm_source_cards() -> list[dict[str, Any]]:
    return [
        {
            "source_id": "kaggle_blog_heads_or_tails",
            "title": "Kaggle interview: Heads or Tails, Kernels Grandmaster",
            "url": "https://medium.com/kaggle-blog/profiling-top-kagglers-martin-henze-aka-heads-or-tails-worlds-first-kernels-grandmaster-b158421f70dc",
            "why_it_matters": (
                "Use detailed EDA before modeling, keep feature engineering tied to observed patterns, "
                "and make the notebook educational rather than just a result dump."
            ),
            "runner_use": "Treat as craft guidance for narrative depth, EDA-before-modeling, and transparent iteration.",
        },
        {
            "source_id": "heads_or_tails_hidden_gems_design",
            "title": "Heads or Tails: Hidden Gems competition design",
            "url": "https://heads0rtai1s.github.io/2022/04/19/gems-comp-design/",
            "why_it_matters": (
                "Notebook quality is judged through visual quality, storytelling, structure, insight quality, "
                "and originality. Tablex notebook authoring should optimize for those properties inside the workbench."
            ),
            "runner_use": "Use as a quality rubric for human-facing analysis, not as a UI skin.",
        },
        {
            "source_id": "kaggle_notebook_grandmaster_pattern",
            "title": "Public Kaggle Grandmaster notebook pattern",
            "url": "https://www.kaggle.com/code/headsortails",
            "why_it_matters": (
                "Strong notebooks are usually not linear chart dumps; they build context, ask questions, "
                "show evidence, explain why it matters, and then decide the next experiment."
            ),
            "runner_use": "Use as inspiration for question-driven analysis flow and high-signal visualization captions.",
        },
    ]


def authoring_principles() -> list[dict[str, str]]:
    return [
        {
            "principle": "Start with a decision-oriented reader brief",
            "implementation": "Tell the user what to read first, what the current evidence can support, and what is blocked.",
        },
        {
            "principle": "EDA is an argument, not a gallery",
            "implementation": "Every chart must answer a question and end with an interpretation or next action.",
        },
        {
            "principle": "Separate observed evidence from assumptions",
            "implementation": "Use Tablex Assumption/Question context instead of pretending semantic uncertainty is resolved.",
        },
        {
            "principle": "Make target and evaluation constraints visible",
            "implementation": "Before discussing lift, show target definition, metric, SplitManifest, and leakage guardrails.",
        },
        {
            "principle": "Prefer progressive disclosure",
            "implementation": "Lead with concise story cards and findings; keep raw tables and manifests in appendices.",
        },
        {
            "principle": "Let Codex propose approach-specific sections",
            "implementation": "If text/time/relational/high-cardinality signals exist, add sections dynamically from evidence.",
        },
    ]


def notebook_sample_moves(project: Project) -> list[dict[str, str]]:
    return [
        {
            "move": "Hook",
            "example_instruction": "Open with the practical prediction question and current confidence, not a generic dataset summary.",
        },
        {
            "move": "Question ladder",
            "example_instruction": "For each section, write the question, show the artifact/plot/table, then write the implication.",
        },
        {
            "move": "Evidence caption",
            "example_instruction": "Caption each figure with what changed the analyst's belief and what remains uncertain.",
        },
        {
            "move": "Dynamic sectioning",
            "example_instruction": (
                f"Because target is `{project.target_column or 'not selected'}`, decide whether to emphasize target readiness, "
                "target relationships, or target-definition blockers."
            ),
        },
        {
            "move": "Next task handoff",
            "example_instruction": "End with one or two Codex tasks that can create new artifacts, not vague recommendations.",
        },
    ]


def notebook_authoring_context_artifacts(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "eda_review_bundle": latest_project_artifact(db, project_id, "eda_review_bundle"),
        "eda_review_html": latest_project_artifact(db, project_id, "eda_review_html"),
        "eda_profile": latest_project_artifact(db, project_id, "eda_profile"),
        "data_quality_gate": latest_project_artifact(db, project_id, "data_quality_gate"),
        "notebook_evidence_bundle": latest_project_artifact(db, project_id, "notebook_evidence_bundle"),
        "evaluation_scenario_comparison": latest_project_artifact(db, project_id, "evaluation_scenario_comparison"),
        "baseline_strategy_plan": latest_project_artifact(db, project_id, "baseline_strategy_plan"),
        "evaluation_diagnostics": latest_project_artifact(db, project_id, "evaluation_diagnostics"),
        "run_report": latest_project_artifact(db, project_id, "run_report"),
        "relational_catalog": latest_project_artifact(db, project_id, "relational_catalog"),
    }


def context_artifact_refs(context_artifacts: dict[str, Artifact | None]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for role, artifact in context_artifacts.items():
        if artifact is None:
            continue
        refs.append(
            {
                "role": role,
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "name": artifact.name,
                "metadata": loads_json(artifact.metadata_json, {}),
                "preview_url": f"/api/artifacts/{artifact.id}/preview",
                "download_url": f"/api/artifacts/{artifact.id}/download",
            }
        )
    return refs


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def render_notebook_authoring_report(brief: dict[str, Any], brief_artifact_id: str) -> str:
    principles = cast(list[dict[str, str]], brief["authoring_principles"])
    sources = cast(list[dict[str, Any]], brief["source_inspirations"])
    return "\n".join(
        [
            "# Notebook Authoring Brief",
            "",
            str(brief["objective"]),
            "",
            f"- Brief artifact: `{brief_artifact_id}`",
            f"- Context artifacts: `{len(brief['context_artifacts'])}`",
            "",
            "## Source Inspirations",
            "",
            *[f"- {item['title']}: {item['url']}" for item in sources],
            "",
            "## Principles",
            "",
            *[f"- **{item['principle']}**: {item['implementation']}" for item in principles],
        ]
    )
