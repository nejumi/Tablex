from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_type: str | None = None
    target_column: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_type: str | None = None
    target_column: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    name: str
    description: str | None
    task_type: str | None
    target_column: str | None
    current_phase: str
    status: str
    created_at: str
    updated_at: str


class ProjectOverview(BaseModel):
    project: ProjectRead
    counts: dict[str, int]
    next_actions: list[str]
    latest_dataset_snapshot_id: str | None
    high_risk_assumptions: list[dict[str, Any]]
    recent_artifacts: list[dict[str, Any]]
    recent_jobs: list[dict[str, Any]]


class ArtifactRead(BaseModel):
    id: str
    project_id: str | None
    asset_type: str
    name: str
    version: int
    uri: str
    content_hash: str
    size_bytes: int | None
    metadata: dict[str, Any]
    created_at: str


class ArtifactPreviewRead(BaseModel):
    id: str
    asset_type: str
    name: str
    filename: str
    content_type: str
    preview_available: bool
    preview: str | None
    truncated: bool
    size_bytes: int | None
    reason: str | None = None


class AssetCreate(BaseModel):
    asset_type: Literal["skill", "feature_recipe", "evaluation_pattern", "prompt_template", "visualization_template"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    visibility: str = "private"


class AssetRead(BaseModel):
    id: str
    asset_type: str
    name: str
    description: str | None
    scope: str
    tags: list[str]
    semantic_tags: list[str]
    latest_version_id: str | None
    visibility: str
    status: str
    created_at: str
    updated_at: str


class AssetVersionRead(BaseModel):
    id: str
    asset_id: str
    version: str
    artifact_id: str
    digest: str
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    runtime_requirements: dict[str, Any]
    created_from_project_id: str | None
    created_from_run_id: str | None
    status: str
    created_at: str


class AssetReferenceCreate(BaseModel):
    target_asset_id: str
    target_asset_version_id: str
    relation_type: str = "uses"


class AssetReferenceRead(BaseModel):
    id: str
    source_type: str
    source_id: str
    target_asset_id: str
    target_asset_version_id: str
    relation_type: str
    locked: bool
    created_at: str
    asset: AssetRead | None = None
    version: AssetVersionRead | None = None


class DatasetSnapshotRead(BaseModel):
    id: str
    project_id: str
    artifact_id: str
    source_type: str
    source_ref: str | None
    row_count: int | None
    column_count: int | None
    schema_hash: str
    data_hash: str | None
    created_at: str


class DatasetUploadResponse(BaseModel):
    dataset_snapshot: DatasetSnapshotRead
    artifact: ArtifactRead
    profile_job_id: str


class BenchmarkImportRequest(BaseModel):
    local_path: str | None = None
    primary_file: str | None = None
    target_column: str | None = None


class BenchmarkFixtureRequest(BaseModel):
    overwrite: bool = False


class BenchmarkPublicDownloadRequest(BaseModel):
    overwrite: bool = False


class BenchmarkDatasetRead(BaseModel):
    id: str
    name: str
    source_kind: str
    source_url: str
    competition_slug: str | None = None
    license_note: str | None = None
    task_types: list[str]
    modality_tags: list[str]
    scale: str | None = None
    recommended_uses: list[str] = Field(default_factory=list)
    scenario: dict[str, Any] | None = None
    access: dict[str, Any] = Field(default_factory=dict)
    source_card: dict[str, Any] | None = None
    primary_table: dict[str, Any]
    required_files: list[dict[str, Any]]
    recommended_files: list[dict[str, Any]] = Field(default_factory=list)
    download: dict[str, Any]
    evaluation_notes: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    default_local_path: str
    download_instructions: str
    fixture_available: bool = False
    fixture_notes: str | None = None
    local_status: dict[str, Any] | None = None


class BenchmarkSourceCardRead(BaseModel):
    schema_version: str
    benchmark_id: str
    name: str
    source_kind: str
    source_url: str
    access: dict[str, Any]
    source_verification: dict[str, Any]
    official_sources: list[dict[str, Any]]
    download: dict[str, Any]
    table_bundle: dict[str, Any]
    local_layout: dict[str, Any]
    import_readiness: dict[str, Any]
    fixture: dict[str, Any]
    credential_policy: dict[str, Any]
    safety_notes: list[str]


class BenchmarkImportReadinessRead(BaseModel):
    benchmark_id: str
    benchmark_name: str
    root_path: str
    local_ready: bool
    can_import_now: bool
    missing_required_count: int
    missing_recommended_count: int
    required_files: list[dict[str, Any]]
    recommended_files: list[dict[str, Any]]
    next_actions: list[str]
    credential_policy: dict[str, Any]


class BenchmarkLocalStatusRead(BaseModel):
    root_path: str
    exists: bool
    ready: bool
    required_found_count: int
    required_missing_count: int
    recommended_found_count: int
    recommended_missing_count: int
    found_required: list[dict[str, Any]]
    missing_required: list[dict[str, Any]]
    found_recommended: list[dict[str, Any]]
    missing_recommended: list[dict[str, Any]]


class BenchmarkImportResponse(BaseModel):
    benchmark: BenchmarkDatasetRead
    dataset_snapshot: DatasetSnapshotRead
    artifact: ArtifactRead
    import_manifest_artifact: ArtifactRead
    relational_catalog_artifact: ArtifactRead
    supporting_table_artifacts: list[ArtifactRead] = Field(default_factory=list)
    skipped_supporting_tables: list[dict[str, Any]] = Field(default_factory=list)
    profile_job_id: str
    primary_file: str


class BenchmarkFixtureResponse(BaseModel):
    schema_version: str
    benchmark_id: str
    benchmark_name: str
    root_path: str
    overwrite: bool
    generated_files: list[dict[str, Any]]
    skipped_files: list[dict[str, Any]]
    fixture_matches_expected: bool
    local_status: dict[str, Any]
    credential_policy: dict[str, Any]
    notes: str | None = None


class SemanticCatalogRead(BaseModel):
    id: str
    project_id: str
    dataset_snapshot_id: str
    artifact_id: str | None
    columns: list[dict[str, Any]]
    created_at: str


class QuestionRead(BaseModel):
    id: str
    project_id: str
    question_set_id: str
    topic: str | None
    question: str
    why_it_matters: str
    default_assumption: str | None
    impact_if_wrong: str | None
    choices: list[str]
    status: str
    priority: int
    risk_level: str
    value_of_answer: str
    can_proceed_without_answer: bool
    fallback_policy: str
    related_assumption_id: str | None
    blocks_next_phase: bool
    created_at: str


class QuestionAnswerCreate(BaseModel):
    answer_value: str = Field(min_length=1)
    answer_text: str | None = None


class AnswerRead(BaseModel):
    id: str
    question_id: str
    answered_by: str
    answer_value: str
    answer_text: str | None
    created_at: str


class AssumptionRead(BaseModel):
    id: str
    project_id: str
    topic: str
    subject_type: str | None
    subject_ref: str | None
    statement: str
    status: str
    confidence: float
    risk_level: str
    fallback_policy: str
    requires_user_confirmation: bool
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


class EvidenceCreate(BaseModel):
    evidence_type: str
    summary: str
    strength: Literal["weak", "medium", "strong", "decisive"] = "medium"
    source_artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationCandidateRead(BaseModel):
    id: str
    project_id: str
    dataset_snapshot_id: str
    name: str
    scenario_id: str | None
    split_type: str
    primary_metric: str
    secondary_metrics: list[str]
    time_column: str | None
    group_column: str | None
    stratify_column: str | None
    excluded_columns: list[str]
    assumption_ids: list[str]
    rationale_md: str
    confidence: float
    risk_level: str
    status: str
    created_at: str


class EvaluationSpecRead(BaseModel):
    id: str
    project_id: str
    dataset_snapshot_id: str
    source_evaluation_candidate_id: str | None
    name: str
    split_type: str
    primary_metric: str
    secondary_metrics: list[str]
    time_column: str | None
    group_column: str | None
    stratify_column: str | None
    excluded_columns: list[str]
    assumption_ids: list[str]
    rationale_md: str
    risk_level: str
    status: str
    created_at: str


class SplitManifestRead(BaseModel):
    id: str
    project_id: str
    evaluation_spec_id: str
    artifact_id: str
    train_count: int
    valid_count: int
    test_count: int | None
    summary: dict[str, Any]
    created_at: str


class ModelVersionRead(BaseModel):
    id: str
    project_id: str
    experiment_run_id: str
    dataset_snapshot_id: str | None
    evaluation_spec_id: str | None
    split_manifest_id: str | None
    artifact_id: str
    name: str
    version: int
    model_family: str
    model_type: str
    task_type: str
    target_column: str | None
    primary_metric_name: str | None
    primary_metric_value: float | None
    metrics: dict[str, Any]
    params: dict[str, Any]
    status: str
    created_at: str


class JobCreate(BaseModel):
    job_type: Literal[
        "profile_dataset",
        "infer_assumptions",
        "design_evaluation_candidates",
        "compare_evaluation_scenarios",
        "review_evaluation_approval",
        "build_split_manifest",
        "run_benchmark_fixture_smoke",
        "create_benchmark_collection_plan",
        "create_benchmark_evidence_pack",
        "create_relational_feature_plan",
        "build_relational_feature_recipe",
        "run_baseline",
        "plan_baseline_strategy",
        "run_planned_agent_task_stub",
        "validate_model_package",
        "plan_agent_task",
        "plan_research",
        "create_research_source_pack",
        "run_research_source_pack_stub",
        "create_research_synthesis",
        "generate_research_brief",
        "generate_approach_candidates",
        "draft_project_report",
        "create_visualization_spec",
        "generate_insights",
        "generate_decision_dashboard",
        "prepare_agent_context",
        "prepare_planned_agent_workspace",
        "review_agent_task_readiness",
        "analyze_evaluation_diagnostics",
        "create_experiment_plan",
        "compare_experiments",
        "draft_run_report",
        "analyze_data_quality",
        "import_benchmark_dataset",
        "create_benchmark_scenario_pack",
        "run_agent_task",
    ]
    project_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    dependency_job_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=1, ge=1, le=10)
    approval_required: bool = False


class AgentTaskPlanCreate(BaseModel):
    objective: str | None = None
    task_type: str = "implement_prediction_approach"


class JobRead(BaseModel):
    id: str
    project_id: str | None
    job_type: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    input: dict[str, Any]
    output: dict[str, Any]
    context: dict[str, Any]
    policy: dict[str, Any]
    dependency_job_ids: list[str]
    error_message: str | None
    approval_required: bool
    approved_by: str | None
    approved_at: str | None
    cancelled_by: str | None
    run_after: str | None
    locked_by: str | None
    locked_at: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    ended_at: str | None


class ModelValidationRead(BaseModel):
    job: JobRead
    model_version_id: str
    validation_status: str | None
    max_abs_metric_delta: float | None
    metrics: dict[str, Any]
    artifacts: list[ArtifactRead]
    created_at: str
    ended_at: str | None


class ResearchBriefCreate(BaseModel):
    question: str | None = None


class ResearchBriefRead(BaseModel):
    id: str
    project_id: str
    dataset_snapshot_id: str | None
    evaluation_spec_id: str | None
    title: str
    question: str
    summary_md: str
    sources: list[dict[str, Any]]
    key_findings: list[str]
    recommended_approaches: list[dict[str, Any]]
    artifact_id: str | None
    status: str
    created_by_type: str
    created_at: str


class IdeaRead(BaseModel):
    id: str
    project_id: str
    dataset_snapshot_id: str | None
    evaluation_spec_id: str | None
    research_brief_id: str | None
    title: str
    hypothesis: str
    approach_type: str
    rationale_md: str
    feature_strategy: dict[str, Any]
    modeling_strategy: dict[str, Any]
    evaluation_notes_md: str | None
    expected_artifacts: list[str]
    agent_task_contract: dict[str, Any]
    confidence: float
    risk_level: str
    status: str
    priority: int
    artifact_id: str | None
    created_by_type: str
    created_at: str
    updated_at: str


class ReportCreate(BaseModel):
    title: str | None = None
    report_type: str = "project_summary"


class ReportRead(BaseModel):
    id: str
    project_id: str
    report_type: str
    title: str
    summary: str
    artifact_id: str
    source_asset_ids: list[dict[str, str]]
    status: str
    created_by_type: str
    created_at: str


class VisualizationSpecRead(BaseModel):
    id: str
    project_id: str
    title: str
    chart_type: str
    spec: dict[str, Any]
    source_artifact_id: str | None
    artifact_id: str
    status: str
    created_by_type: str
    created_at: str


class InsightRead(BaseModel):
    id: str
    project_id: str
    insight_type: str
    title: str
    summary: str
    severity: str
    confidence: float
    status: str
    source_asset_ids: list[dict[str, str]]
    evidence_ids: list[str]
    artifact_id: str
    created_by_type: str
    created_at: str


class AgentRequiredOutput(BaseModel):
    path: str
    schema_: str = Field(alias="schema")
    description: str | None = None


class AgentTaskContract(BaseModel):
    task_id: str
    task_type: str
    project_id: str
    objective: str
    inputs: dict[str, Any]
    required_outputs: list[AgentRequiredOutput]
    quality_checks: list[str]
    forbidden_actions: list[str]
    context_files: list[str] = Field(default_factory=list)
    output_schema_path: str | None = None
    assumption_context: dict[str, Any] | None = None
    autonomy_level: int | None = Field(default=None, ge=0, le=5)


class AgentResult(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "needs_approval"]
    final_message: str
    outputs: dict[str, Any]
    artifacts: list[dict[str, Any]]
    warnings: list[str]
    failure_reason: str | None = None
    patch_summary: str | None = None
    proposed_assumption_updates: list[dict[str, Any]] = Field(default_factory=list)
    proposed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    evidence_sources: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    report_citations: list[dict[str, Any]] = Field(default_factory=list)
    proposed_questions: list[dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool = False
