from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, default="local-org", nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str | None] = mapped_column(String)
    target_column: Mapped[str | None] = mapped_column(String)
    current_phase: Mapped[str] = mapped_column(String, default="DRAFT", nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    created_by: Mapped[str] = mapped_column(String, default="local-user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("project_id", "asset_type", "name", "version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, default="local-org", nullable=False)
    project_id: Mapped[str | None] = mapped_column(String, ForeignKey("projects.id"))
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_count: Mapped[int | None] = mapped_column(Integer)
    schema_hash: Mapped[str] = mapped_column(String, nullable=False)
    data_hash: Mapped[str | None] = mapped_column(String)
    parent_snapshot_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SemanticCatalog(Base):
    __tablename__ = "semantic_catalogs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    dataset_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("dataset_snapshots.id"), nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"))
    columns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    question_set_id: Mapped[str] = mapped_column(String, nullable=False)
    topic: Mapped[str | None] = mapped_column(String)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    default_assumption: Mapped[str | None] = mapped_column(Text)
    impact_if_wrong: Mapped[str | None] = mapped_column(Text)
    choices_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, default="medium", nullable=False)
    value_of_answer: Mapped[str] = mapped_column(String, default="medium", nullable=False)
    can_proceed_without_answer: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fallback_policy: Mapped[str] = mapped_column(String, default="conservative_default", nullable=False)
    related_assumption_id: Mapped[str | None] = mapped_column(String)
    blocks_next_phase: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(String, ForeignKey("questions.id"), nullable=False)
    answered_by: Mapped[str] = mapped_column(String, default="local-user", nullable=False)
    answer_value: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Assumption(Base):
    __tablename__ = "assumptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String)
    subject_ref: Mapped[str | None] = mapped_column(String)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    fallback_policy: Mapped[str] = mapped_column(String, nullable=False)
    requires_user_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str] = mapped_column(String, nullable=False)
    source_artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"))
    source_run_id: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AssumptionEvidenceLink(Base):
    __tablename__ = "assumption_evidence_links"
    __table_args__ = (UniqueConstraint("assumption_id", "evidence_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    assumption_id: Mapped[str] = mapped_column(String, ForeignKey("assumptions.id"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, ForeignKey("evidence.id"), nullable=False)
    effect: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EvaluationCandidate(Base):
    __tablename__ = "evaluation_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    dataset_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("dataset_snapshots.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(String)
    split_type: Mapped[str] = mapped_column(String, nullable=False)
    primary_metric: Mapped[str] = mapped_column(String, nullable=False)
    secondary_metrics_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    time_column: Mapped[str | None] = mapped_column(String)
    group_column: Mapped[str | None] = mapped_column(String)
    stratify_column: Mapped[str | None] = mapped_column(String)
    excluded_columns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    assumption_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EvaluationSpec(Base):
    __tablename__ = "evaluation_specs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    dataset_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("dataset_snapshots.id"), nullable=False
    )
    source_evaluation_candidate_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("evaluation_candidates.id")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    split_type: Mapped[str] = mapped_column(String, nullable=False)
    primary_metric: Mapped[str] = mapped_column(String, nullable=False)
    secondary_metrics_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    time_column: Mapped[str | None] = mapped_column(String)
    group_column: Mapped[str | None] = mapped_column(String)
    stratify_column: Mapped[str | None] = mapped_column(String)
    excluded_columns_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    assumption_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SplitManifest(Base):
    __tablename__ = "split_manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    evaluation_spec_id: Mapped[str] = mapped_column(
        String, ForeignKey("evaluation_specs.id"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    train_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    test_count: Mapped[int | None] = mapped_column(Integer)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    idea_id: Mapped[str | None] = mapped_column(String)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String, ForeignKey("dataset_snapshots.id"))
    evaluation_spec_id: Mapped[str | None] = mapped_column(String, ForeignKey("evaluation_specs.id"))
    evaluation_candidate_id: Mapped[str | None] = mapped_column(String, ForeignKey("evaluation_candidates.id"))
    split_manifest_id: Mapped[str | None] = mapped_column(String, ForeignKey("split_manifests.id"))
    feature_set_id: Mapped[str | None] = mapped_column(String)
    model_version_id: Mapped[str | None] = mapped_column(String)
    runner_type: Mapped[str] = mapped_column(String, default="local_stub", nullable=False)
    status: Mapped[str] = mapped_column(String, default="created", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    summary_md: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")


class ResearchBrief(Base):
    __tablename__ = "research_briefs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String, ForeignKey("dataset_snapshots.id"))
    evaluation_spec_id: Mapped[str | None] = mapped_column(String, ForeignKey("evaluation_specs.id"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    key_findings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    recommended_approaches_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"))
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String, ForeignKey("dataset_snapshots.id"))
    evaluation_spec_id: Mapped[str | None] = mapped_column(String, ForeignKey("evaluation_specs.id"))
    research_brief_id: Mapped[str | None] = mapped_column(String, ForeignKey("research_briefs.id"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    approach_type: Mapped[str] = mapped_column(String, nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    feature_strategy_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    modeling_strategy_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    evaluation_notes_md: Mapped[str | None] = mapped_column(Text)
    expected_artifacts_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    agent_task_contract_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String, default="proposed", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"))
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    source_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VisualizationSpec(Base):
    __tablename__ = "visualization_specs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    chart_type: Mapped[str] = mapped_column(String, nullable=False)
    spec_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_artifact_id: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"))
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    insight_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String, default="info", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    source_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    created_by_type: Mapped[str] = mapped_column(String, default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("project_id", "name", "version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    experiment_run_id: Mapped[str] = mapped_column(String, ForeignKey("experiment_runs.id"), nullable=False)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String, ForeignKey("dataset_snapshots.id"))
    evaluation_spec_id: Mapped[str | None] = mapped_column(String, ForeignKey("evaluation_specs.id"))
    split_manifest_id: Mapped[str | None] = mapped_column(String, ForeignKey("split_manifests.id"))
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_family: Mapped[str] = mapped_column(String, nullable=False)
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    target_column: Mapped[str | None] = mapped_column(String)
    primary_metric_name: Mapped[str | None] = mapped_column(String)
    primary_metric_value: Mapped[float | None] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String, default="created", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, default="local-org", nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String, default="organization", nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    semantic_tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    latest_version_id: Mapped[str | None] = mapped_column(String)
    visibility: Mapped[str] = mapped_column(String, default="private", nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AssetVersion(Base):
    __tablename__ = "asset_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(String, ForeignKey("assets.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, ForeignKey("artifacts.id"), nullable=False)
    digest: Mapped[str] = mapped_column(String, nullable=False)
    inputs_schema_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    outputs_schema_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    runtime_requirements_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_from_project_id: Mapped[str | None] = mapped_column(String)
    created_from_run_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AssetReference(Base):
    __tablename__ = "asset_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    target_asset_id: Mapped[str] = mapped_column(String, ForeignKey("assets.id"), nullable=False)
    target_asset_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("asset_versions.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, default="local-org", nullable=False)
    project_id: Mapped[str | None] = mapped_column(String, ForeignKey("projects.id"))
    from_asset_type: Mapped[str] = mapped_column(String, nullable=False)
    from_asset_id: Mapped[str] = mapped_column(String, nullable=False)
    to_asset_type: Mapped[str] = mapped_column(String, nullable=False)
    to_asset_id: Mapped[str] = mapped_column(String, nullable=False)
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String, ForeignKey("projects.id"))
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    policy_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    dependency_job_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(String)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
