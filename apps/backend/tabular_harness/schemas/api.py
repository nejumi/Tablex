from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_type: str | None = None
    target_column: str | None = None
    autonomy_mode: Literal["approval_based", "full_auto"] | None = "full_auto"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_type: str | None = None
    target_column: str | None = None
    autonomy_mode: Literal["approval_based", "full_auto"] | None = None
    locale: str | None = None


class ProjectCloneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mode: Literal["data_only", "full"]


class ProjectCloneRead(BaseModel):
    schema_version: Literal["project_clone.v1"]
    mode: Literal["data_only", "full"]
    source_project_id: str
    project: ProjectRead
    copied_counts: dict[str, int]


class AutonomyStartCreate(BaseModel):
    runner_mode: Literal["harness_only", "codex_cli", "codex_cli_if_available"] = "codex_cli_if_available"
    autonomy_mode: Literal["approval_based", "full_auto"] = "full_auto"
    locale: str | None = None
    agent_model: str | None = None
    utility_model: str | None = None


class AutonomyStopCreate(BaseModel):
    locale: str | None = None


class DataUnderstandingNotebookCreate(BaseModel):
    locale: str | None = None


class ResearchPlanRevisionCommitCreate(BaseModel):
    document: dict[str, Any]
    reason: str = Field(default="", max_length=2000)
    parent_revision_id: str | None = None
    author_type: str = Field(default="codex", max_length=80)
    author_id: str | None = Field(default=None, max_length=160)
    source_artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchPlanCurrentWorkCreate(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=4000)
    status: Literal["active", "pending", "blocked", "waiting", "done", "skipped"] = "active"
    expected_outputs: list[str] = Field(default_factory=list, max_length=40)
    revision_id: str | None = None
    updated_by_type: str = Field(default="codex", max_length=80)
    updated_by: str | None = Field(default=None, max_length=160)


class ResearchPlanArtifactAttachCreate(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    artifact_id: str
    role: str = Field(default="evidence", max_length=80)
    revision_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchPlanHumanAttentionCreate(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    why_it_matters: str = Field(default="", max_length=4000)
    node_id: str | None = Field(default=None, max_length=160)
    provisional_assumption: str | None = Field(default=None, max_length=4000)
    impact_if_wrong: str | None = Field(default=None, max_length=4000)
    urgency: Literal["low", "medium", "high", "critical"] = "medium"
    fallback_policy: str = Field(default="infer_and_continue", max_length=120)
    blocks_next_phase: bool = False
    revision_id: str | None = None


class AgentSessionRead(BaseModel):
    id: str
    project_id: str
    session_type: str
    status: str
    autonomy_mode: str
    runner_kind: str
    goal_text: str
    workspace_path: str | None
    codex_thread_id: str | None
    pid: int | None
    pid_is_observed_codex_process: bool | None = None
    observed_runner_state: str | None = None
    observed_codex_process_count: int = 0
    observed_codex_processes: list[dict[str, Any]] = Field(default_factory=list)
    turn_index: int
    last_heartbeat_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    ended_at: str | None


class AgentTranscriptEventRead(BaseModel):
    id: str
    project_id: str
    session_id: str
    event_index: int
    source: str
    event_type: str
    role: str | None
    title: str | None
    content: str | None
    payload: dict[str, Any]
    artifact_id: str | None
    job_id: str | None
    created_at: str


class AgentRawTranscriptLineRead(BaseModel):
    line_number: int
    text: str
    parsed: dict[str, Any] | None = None
    truncated: bool = False
    original_length: int | None = None


class AgentRawTranscriptRead(BaseModel):
    session_id: str | None
    stdout_path: str | None
    stderr_path: str | None
    stdout_download_url: str | None
    stderr_download_url: str | None
    stdout_line_count: int
    stderr_line_count: int
    stdout_tail: list[str]
    stderr_tail: list[str]
    stdout_tail_lines: list[AgentRawTranscriptLineRead]
    stderr_tail_lines: list[AgentRawTranscriptLineRead]
    updated_at: str | None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    name: str
    description: str | None
    task_type: str | None
    target_column: str | None
    primary_dataset_snapshot_id: str | None
    current_phase: str
    status: str
    autonomy_mode: Literal["approval_based", "full_auto"]
    created_by: str
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


class ProjectGuidanceAction(BaseModel):
    id: str
    label: str
    target_tab: str
    action_type: Literal["navigate", "run_endpoint", "agent_task_prompt"]
    method: str | None = None
    endpoint: str | None = None
    request_body: dict[str, Any] | None = None
    prompt: str | None = None
    disabled: bool = False
    disabled_reason: str | None = None


class ProjectGuidanceFocus(BaseModel):
    focus_key: str
    target_tab: str
    title: str
    reason: str
    risk_level: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    primary_action: ProjectGuidanceAction
    secondary_actions: list[ProjectGuidanceAction] = Field(default_factory=list)
    suggested_agent_prompt: str | None = None


class ProjectGuidanceJourneyStage(BaseModel):
    id: str
    label: str
    target_tab: str
    status: Literal["done", "current", "next", "blocked", "waiting"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    action: ProjectGuidanceAction | None = None


class ProjectGuidanceRead(BaseModel):
    schema_version: Literal["project_guidance.v1"]
    project_id: str
    generated_at: str
    attention_budget: int
    overview_mode: Literal["guided"]
    recommended_focus: ProjectGuidanceFocus
    journey_stages: list[ProjectGuidanceJourneyStage]
    current_stage_id: str | None = None
    state_summary: dict[str, Any]
    supporting_counts: dict[str, int]
    hidden_detail_groups: list[dict[str, Any]]
    agent_guidance: list[str]
    autonomous_navigation: dict[str, Any]


class ArtifactRead(BaseModel):
    id: str
    project_id: str | None
    asset_type: str
    surface_role: str = "primary"
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
    lineage: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    reason: str | None = None


class TranslationCreate(BaseModel):
    target_locale: str = Field(default="en-US", min_length=2, max_length=64)
    source_locale: str = Field(default="en-US", min_length=2, max_length=64)


class AvatarCandidateCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=1200)
    count: int = Field(default=3, ge=1, le=4)


class AvatarCandidateRead(BaseModel):
    id: str
    data_url: str
    model: str
    revised_prompt: str | None = None


class AvatarCandidateResponse(BaseModel):
    candidates: list[AvatarCandidateRead]


class AuthLoginCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class AuthRegisterCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=1024)
    display_name: str | None = Field(default=None, max_length=120)


class UserSettingsUpdate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class UserRead(BaseModel):
    id: str
    email: str
    display_name: str | None
    auth_provider: str
    is_admin: bool
    settings: dict[str, Any]
    created_at: str
    updated_at: str


class AuthStatusRead(BaseModel):
    auth_enabled: bool
    authenticated: bool
    password_auth_enabled: bool
    google_auth_enabled: bool
    bootstrap_required: bool
    user: UserRead | None = None


class TranslationRead(BaseModel):
    source_type: str
    source_id: str
    source_artifact_id: str
    target_locale: str
    source_locale: str
    provider_status: str
    translation_status: str
    artifact: ArtifactRead
    report: dict[str, Any] | None = None
    preview: ArtifactPreviewRead
    job: dict[str, Any]


class AssetCreate(BaseModel):
    asset_type: Literal["skill", "feature_recipe", "evaluation_pattern", "prompt_template", "visualization_template"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    semantic_tags: list[str] = Field(default_factory=list)
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
    is_primary: bool = False
    created_at: str


class DatasetUploadResponse(BaseModel):
    dataset_snapshot: DatasetSnapshotRead
    artifact: ArtifactRead
    profile_job_id: str


class ProjectPrimaryDatasetUpdate(BaseModel):
    dataset_snapshot_id: str | None = None
    artifact_id: str | None = None
    target_column: str | None = None
    locale: str | None = None


class BenchmarkImportRequest(BaseModel):
    local_path: str | None = None
    primary_file: str | None = None
    target_column: str | None = None


class BenchmarkFixtureRequest(BaseModel):
    overwrite: bool = False


class BenchmarkPublicDownloadRequest(BaseModel):
    overwrite: bool = False


class KaggleSelectiveDownloadRequest(BaseModel):
    selected_files: list[str] = Field(default_factory=list)
    include_required: bool = True
    include_recommended: bool = False
    include_holdout: bool = False
    overwrite: bool = False
    max_total_bytes: int = Field(default=500 * 1024 * 1024, gt=0)


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
    credential_probe: dict[str, Any]
    credential_inventory: dict[str, Any]
    credential_download: dict[str, Any]
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
    credential_probe: dict[str, Any] = Field(default_factory=dict)
    credential_inventory: dict[str, Any] = Field(default_factory=dict)
    credential_download: dict[str, Any] = Field(default_factory=dict)
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


class AssumptionReviewAction(BaseModel):
    id: str
    label: str
    action_type: Literal["confirm_assumption", "challenge_assumption", "answer_question", "navigate"]
    method: str | None = None
    endpoint: str | None = None
    request_body: dict[str, Any] | None = None


class AssumptionReviewItem(BaseModel):
    item_type: Literal["assumption", "question"]
    id: str
    title: str
    body: str
    why_it_matters: str | None = None
    status: str
    risk_level: str
    fallback_policy: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    priority_score: float
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)
    primary_actions: list[AssumptionReviewAction] = Field(default_factory=list)


class AssumptionReviewQueueRead(BaseModel):
    schema_version: Literal["assumption_review_queue.v1"]
    project_id: str
    generated_at: str
    next_item: AssumptionReviewItem | None = None
    queue: list[AssumptionReviewItem]
    counts: dict[str, int]
    guidance: list[str]


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
        "diagnose_relational_feature_scenarios",
        "start_autonomous_loop",
        "continue_autonomous_session",
        "stop_autonomous_loop",
        "run_baseline",
        "train_model_candidates",
        "plan_baseline_strategy",
        "create_notebook_authoring_brief",
        "materialize_model_diagnostics_artifacts",
        "run_planned_agent_task_codex",
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
        "generate_decision_report",
        "prepare_agent_context",
        "prepare_planned_agent_workspace",
        "review_agent_task_readiness",
        "analyze_evaluation_diagnostics",
        "create_experiment_plan",
        "compare_experiments",
        "draft_run_report",
        "post_run_reading_workflow",
        "analyze_data_quality",
        "probe_kaggle_benchmark_access",
        "fetch_kaggle_competition_inventory",
        "download_kaggle_selected_files",
        "import_benchmark_dataset",
        "create_benchmark_scenario_pack",
        "upload_relational_schema_hint",
        "translate_tier3_content",
        "run_agent_task",
        "agent_chat_turn",
        "prepare_result_notebook_evidence",
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


class AgentChatCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    locale: str | None = None
    agent_model: str | None = None
    utility_model: str | None = None


class AgentConsoleMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    locale: str | None = None


class PipelineBundleBuildCreate(BaseModel):
    locale: str | None = None


class AgentConsoleMessageRead(BaseModel):
    schema_version: str
    project_id: str
    session_id: str
    status: str
    delivered: bool
    woke_session: bool
    transcript_event_id: str
    transcript_event_index: int
    inbox_delivery: str
    message: str


class AgentChatHistoryTurnRead(BaseModel):
    schema_version: str
    project_id: str
    user_message: str
    assistant_message: str
    intent: dict[str, Any]
    actions: list[dict[str, Any]]
    action_summary: dict[str, Any]
    response_brief: dict[str, Any] | None = None
    response_composer: dict[str, Any] | None = None
    worker_events: list[dict[str, Any]]
    token_usage: dict[str, Any]
    next_focus: dict[str, Any]
    artifact_id: str
    job_id: str | None
    created_at: str


class LeaderboardMetricPreferenceCreate(BaseModel):
    metric: str = Field(min_length=1, max_length=80)


class ModelCandidatesRunCreate(BaseModel):
    models: list[str] = Field(min_length=1, max_length=8)


class PortalIdeaCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PortalIdeaRead(BaseModel):
    id: str
    artifact_id: str
    text: str
    status: str
    source: str
    created_at: str


class PortalOverviewRead(BaseModel):
    schema_version: str
    generated_at: str
    summary: dict[str, Any]
    projects: list[dict[str, Any]]
    recent_updates: list[dict[str, Any]]
    agent_activity: list[dict[str, Any]]
    ideas: list[PortalIdeaRead]


class AgentActivityRead(BaseModel):
    schema_version: str
    project_id: str
    generated_at: str
    active_count: int
    turn_state: dict[str, Any]
    workers: list[dict[str, Any]]


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


class AgentChatRead(BaseModel):
    schema_version: str
    project_id: str
    user_message: str
    assistant_message: str
    intent: dict[str, Any]
    actions: list[dict[str, Any]]
    action_summary: dict[str, Any]
    response_brief: dict[str, Any] | None = None
    response_composer: dict[str, Any] | None = None
    worker_events: list[dict[str, Any]]
    token_usage: dict[str, Any]
    next_focus: dict[str, Any]
    artifact_id: str
    job: JobRead | None = None


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


class AdaptiveStrategyBriefRead(BaseModel):
    schema_version: str
    response_locale: str | None = None
    project: dict[str, Any]
    summary: dict[str, Any]
    recommended_next_action: dict[str, Any]
    candidate_lanes: list[dict[str, Any]]
    codex_handoff: dict[str, Any]
    reporting_plan: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    risk_register: list[dict[str, Any]]
    latest_artifact_id: str | None = None
    generated_at: str


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


class DecisionReportCurrentRead(BaseModel):
    schema_version: str
    project_id: str
    available: bool
    generated_at: str | None
    report: dict[str, Any] | None
    report_artifact: dict[str, Any] | None
    bundle_artifact: dict[str, Any] | None
    bundle: dict[str, Any] | None
    action_endpoint: str


class ResultReadoutRead(BaseModel):
    schema_version: Literal["result_readout.v1"]
    project_id: str
    status: str
    headline: str
    summary: str
    top_run: dict[str, Any] | None
    metric_story: str
    evaluation_contract: dict[str, Any]
    comparison: dict[str, Any]
    diagnostics: dict[str, Any]
    notebook: dict[str, Any]
    decision_report: dict[str, Any]
    read_order: list[dict[str, Any]]
    next_action: dict[str, Any]
    evidence_gaps: list[dict[str, Any]]
    safety: dict[str, Any]


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
    status: Literal["succeeded", "failed", "needs_approval", "gave_up"]
    final_message: str
    outputs: dict[str, Any]
    artifacts: list[dict[str, Any]]
    warnings: list[str]
    failure_reason: str | None = None
    give_up_reason: str | None = None
    required_next_inputs: list[str] = Field(default_factory=list)
    patch_summary: str | None = None
    proposed_assumption_updates: list[dict[str, Any]] = Field(default_factory=list)
    proposed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    evidence_sources: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    report_citations: list[dict[str, Any]] = Field(default_factory=list)
    proposed_questions: list[dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool = False
