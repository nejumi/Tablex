export const tabItems = [
  { id: "Home", labelKey: "tabHome" },
  { id: "Overview", labelKey: "tabOverview" },
  { id: "Data", labelKey: "tabData" },
  { id: "Insight", labelKey: "tabInsight" },
  { id: "Understanding", labelKey: "tabUnderstanding" },
  { id: "Assumptions", labelKey: "tabAssumptions" },
  { id: "Evaluation", labelKey: "tabEvaluation" },
  { id: "Approach", labelKey: "tabApproach" },
  { id: "Experiments", labelKey: "tabExperiments" },
  { id: "Notebooks", labelKey: "tabNotebooks" },
  { id: "Leaderboard", labelKey: "tabLeaderboard" },
  { id: "Raw", labelKey: "agentModeRaw" },
  { id: "Reports", labelKey: "tabReports" },
  { id: "Assets", labelKey: "tabAssets" },
  { id: "Library", labelKey: "tabLibrary" },
  { id: "Jobs", labelKey: "tabJobs" },
  { id: "Lineage", labelKey: "tabLineage" }
] as const;

export type Tab = (typeof tabItems)[number]["id"];

export type AutonomyMode = "approval_based" | "full_auto";
export type TableeMotionState = "idle" | "awake" | "working";

export type Project = {
  id: string;
  name: string;
  description: string | null;
  task_type: string | null;
  target_column: string | null;
  primary_dataset_snapshot_id: string | null;
  current_phase: string;
  status: string;
  autonomy_mode: AutonomyMode;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type DatasetSnapshot = {
  id: string;
  project_id: string;
  artifact_id: string;
  source_type: string;
  source_ref: string | null;
  row_count: number | null;
  column_count: number | null;
  schema_hash: string;
  is_primary?: boolean;
  created_at: string;
};

export type SemanticCatalog = {
  id: string;
  project_id: string;
  dataset_snapshot_id: string;
  artifact_id: string | null;
  columns: Array<Record<string, unknown> | string>;
  created_at: string;
};

export type ProjectColumnCatalog = {
  schema_version: "project_column_catalog.v1";
  project_id: string;
  tables: Array<{
    dataset_snapshot_id: string;
    artifact_id: string | null;
    source_ref: string | null;
    row_count: number | null;
    column_count: number | null;
    is_primary: boolean;
    columns: string[];
    column_details?: Array<{
      name: string;
      physical_type?: string;
      missing_count?: number;
      missing_rate?: number;
      unique_count?: number;
    }>;
  }>;
};

export type Artifact = {
  id: string;
  asset_type: string;
  surface_role?: "primary" | "supporting" | "notebook" | "hidden" | string;
  name: string;
  version: number;
  size_bytes: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RunnerReadinessFeedback = {
  contractArtifactId: string;
  status: string;
  blockerCount: number;
  warningCount: number;
  passCount: number;
  nextActions: string[];
  source: "latest_artifact" | "current_review";
};

export type ArtifactPreview = {
  id: string;
  asset_type: string;
  name: string;
  filename: string;
  content_type: string;
  preview_available: boolean;
  preview: string | null;
  truncated: boolean;
  size_bytes: number | null;
  lineage?: {
    inputs?: ArtifactPreviewLineageEdge[];
    outputs?: ArtifactPreviewLineageEdge[];
  };
  reason: string | null;
};

export type ArtifactPreviewLineageEdge = {
  edge_id: string;
  relation_type: string;
  asset_type: string;
  asset_id: string;
  label: string;
  endpoint_asset_type: string;
  created_at: string;
};

export type NativeMarimoSession = {
  schema_version: string;
  session_id: string;
  artifact_id: string;
  project_id: string | null;
  proxy_url: string;
  base_url: string;
  status: string;
  started_at: string;
  last_accessed_at: string;
  source_hash: string;
  runtime?: {
    has_error: boolean;
    error_excerpt: string | null;
  };
};

export type EvidenceReaderMetric = {
  label: string;
  value: React.ReactNode;
  tone?: "ready" | "warning" | "risk" | "muted";
};

export type NotebookIndexItem = {
  notebook_artifact_id: string;
  notebook_kind: string;
  title: string;
  status: string;
  created_at: string;
  dataset_snapshot_id: string | null;
  run_id: string | null;
  model_version_id: string | null;
  research_plan_id?: string | null;
  research_plan_node_id?: string | null;
  related_run_ids?: string[];
  related_context?: {
    dataset_snapshot_id?: string | null;
    run_id?: string | null;
    model_version_id?: string | null;
    context_link_source?: string | null;
    research_plan_id?: string | null;
    research_plan_node_id?: string | null;
    related_run_ids?: string[];
  } | null;
  artifact_ids: {
    notebook: string;
    source?: string | null;
    preview?: string | null;
    manifest: string | null;
    report_artifact: string | null;
    visualization_artifact: string | null;
    execution_plan: string | null;
    agent_task_contract: string | null;
    figure_manifest: string | null;
    evidence_bundle: string | null;
    evidence_figures: string[];
  };
  source_artifact_id?: string | null;
  preview_artifact_id?: string | null;
  report_id: string | null;
  visualization_id: string | null;
  coverage: Record<string, unknown>;
  quality_manifest?: {
    schema_version?: string;
    figure_count?: number;
    table_count?: number;
    key_findings?: string[];
    read_order?: Array<{ label?: string; anchor?: string; detail?: string }>;
    data_sources_used?: string[];
    limitations?: string[];
    visual_summary?: string;
    notebook_purpose?: string;
  } | null;
  content: {
    readiness?: string;
    quality_score?: number;
    read_order_count?: number;
    story_card_count?: number;
    playbook_count?: number;
    primary_metric_available?: boolean;
    prediction_rows?: number;
    has_predictions?: boolean;
  };
  recommendation_score: number;
  recommendation_reason: string;
};

export type NotebookIndex = {
  schema_version: string;
  project_id: string;
  generated_at: string;
  counts: {
    total: number;
    by_kind: Record<string, number>;
    with_native_source: number;
    with_report: number;
    with_visualization: number;
    with_execution_plan: number;
  };
  recommended_notebook: NotebookIndexItem | null;
  groups: Array<{ notebook_kind: string; title: string; count: number; latest_created_at: string; items: NotebookIndexItem[] }>;
  items: NotebookIndexItem[];
  next_actions: Array<{ label: string; endpoint: string | null; reason: string }>;
};

export type AnalysisStorySurface = {
  schema_version: string;
  project_id: string;
  generated_at: string;
  available: boolean;
  story: AnalysisStory | null;
  empty_state: {
    headline?: string;
    reason?: string;
    primary_action?: Record<string, unknown>;
  } | null;
  notebook_index: NotebookIndex;
};

export type AnalysisStory = {
  source_type: string;
  headline: string;
  deck: string;
  why_this_story: string;
    selected_source: {
      source_type: string;
    title: string;
    artifact_id: string;
    source_artifact_id?: string | null;
    preview_artifact_id?: string | null;
    report_id: string | null;
    notebook_kind: string | null;
    status: string | null;
    created_at: string | null;
    reason: string | null;
  };
  read_order: Array<Record<string, unknown>>;
  visual_story_cards: Array<Record<string, unknown>>;
  evidence_cards: Array<Record<string, unknown>>;
  playbook: Array<Record<string, unknown>>;
  caveats: string[];
  codex_prompts: string[];
  primary_action: Record<string, unknown>;
  figure_refs: Array<Record<string, unknown>>;
  raw_artifacts: Array<Record<string, unknown>>;
  supporting_sources: Array<Record<string, unknown>>;
  metrics: Record<string, unknown>;
};

export type TranslationResult = {
  source_type: string;
  source_id: string;
  source_artifact_id: string;
  target_locale: string;
  source_locale: string;
  provider_status: string;
  translation_status: string;
  artifact: Artifact;
  report: Report | null;
  preview: ArtifactPreview;
  job: Job;
};

export type TranslationJobOutput = {
  translation?: Omit<TranslationResult, "job">;
};

export type BenchmarkDataset = {
  id: string;
  name: string;
  source_kind: string;
  source_url: string;
  task_types: string[];
  modality_tags: string[];
  scale: string | null;
  recommended_uses: string[];
  scenario: Record<string, unknown> | null;
  access: Record<string, unknown>;
  source_card: BenchmarkSourceCard | null;
  primary_table: Record<string, unknown>;
  required_files: Array<Record<string, unknown>>;
  recommended_files: Array<Record<string, unknown>>;
  download: Record<string, unknown>;
  evaluation_notes: string | null;
  risk_notes: string[];
  default_local_path: string;
  download_instructions: string;
  fixture_available: boolean;
  fixture_notes: string | null;
  local_status: BenchmarkLocalStatus | null;
};

export type BenchmarkSourceCard = {
  schema_version: string;
  benchmark_id: string;
  access: Record<string, unknown>;
  source_verification: Record<string, unknown>;
  official_sources: Array<Record<string, unknown>>;
  table_bundle: Record<string, unknown>;
  import_readiness: {
    local_ready: boolean;
    can_import_now: boolean;
    missing_required_count: number;
    next_actions: string[];
    credential_policy: Record<string, unknown>;
  };
  fixture: Record<string, unknown>;
  credential_probe: {
    supported: boolean;
    status: string;
    endpoint: string | null;
    secret_boundary: string;
    credential_values_returned: boolean;
    agent_receives_credentials: boolean;
    artifact_contains_secret_values: boolean;
  };
  credential_inventory: {
    supported: boolean;
    status: string;
    endpoint: string | null;
    latest_endpoint: string | null;
    secret_boundary: string;
    stores_file_names_and_sizes: boolean;
    credential_values_returned: boolean;
    agent_receives_credentials: boolean;
    artifact_contains_secret_values: boolean;
  };
  credential_download: {
    supported: boolean;
    status: string;
    endpoint: string | null;
    default_policy: string | null;
    secret_boundary: string;
    credential_values_returned: boolean;
    agent_receives_credentials: boolean;
    artifact_contains_secret_values: boolean;
  };
  credential_policy: Record<string, unknown>;
  safety_notes: string[];
};

export type BenchmarkLocalStatus = {
  root_path: string;
  exists: boolean;
  ready: boolean;
  required_found_count: number;
  required_missing_count: number;
  recommended_found_count: number;
  recommended_missing_count: number;
  missing_required: Array<{ expected: string[]; role: string | null; description: string | null }>;
};

export type LibraryAsset = {
  id: string;
  asset_type: string;
  name: string;
  description: string | null;
  scope: string;
  tags: string[];
  semantic_tags: string[];
  latest_version_id: string | null;
  visibility: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type AssetReference = {
  id: string;
  source_type: string;
  source_id: string;
  target_asset_id: string;
  target_asset_version_id: string;
  relation_type: string;
  locked: boolean;
  created_at: string;
  asset: LibraryAsset | null;
};

export type Question = {
  id: string;
  topic: string | null;
  question: string;
  why_it_matters: string;
  default_assumption: string | null;
  choices: string[];
  risk_level: string;
  value_of_answer: string;
  fallback_policy: string;
  status: string;
};

export type Assumption = {
  id: string;
  topic: string;
  statement: string;
  status: string;
  confidence: number;
  risk_level: string;
  fallback_policy: string;
  requires_user_confirmation: boolean;
  evidence: Array<{ summary: string; strength: string }>;
};

export type AssumptionReviewAction = {
  id: string;
  label: string;
  action_type: "confirm_assumption" | "challenge_assumption" | "answer_question" | "navigate";
  method: string | null;
  endpoint: string | null;
  request_body: Record<string, unknown> | null;
};

export type AssumptionReviewItem = {
  item_type: "assumption" | "question";
  id: string;
  title: string;
  body: string;
  why_it_matters: string | null;
  status: string;
  risk_level: string;
  fallback_policy: string;
  confidence: number | null;
  priority_score: number;
  evidence: Array<{ summary: string; strength: string; evidence_type?: string; source_artifact_id?: string | null }>;
  choices: string[];
  primary_actions: AssumptionReviewAction[];
};

export type AssumptionReviewQueue = {
  schema_version: "assumption_review_queue.v1";
  project_id: string;
  generated_at: string;
  next_item: AssumptionReviewItem | null;
  queue: AssumptionReviewItem[];
  counts: Record<string, number>;
  guidance: string[];
};

export type EvaluationCandidate = {
  id: string;
  name: string;
  split_type: string;
  primary_metric: string;
  status: string;
  risk_level: string;
  confidence: number;
  rationale_md: string;
  excluded_columns: string[];
  time_column: string | null;
  group_column: string | null;
  stratify_column: string | null;
};

export type EvaluationSpec = {
  id: string;
  name: string;
  split_type: string;
  primary_metric: string;
  status: string;
  risk_level: string;
  source_evaluation_candidate_id: string | null;
};

export type Job = {
  id: string;
  project_id: string | null;
  job_type: string;
  status: string;
  priority: number;
  attempt_count: number;
  max_attempts: number;
  input: Record<string, unknown>;
  context: Record<string, unknown>;
  policy: Record<string, unknown>;
  dependency_job_ids: string[];
  error_message: string | null;
  approval_required: boolean;
  approved_by: string | null;
  approved_at: string | null;
  cancelled_by: string | null;
  run_after: string | null;
  locked_by: string | null;
  locked_at: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  ended_at: string | null;
  output: Record<string, unknown>;
};

export type AutonomyIntervention = {
  schema_version?: string;
  kind: string;
  mode?: string;
  continued?: boolean;
  question_id?: string;
  assumption_id?: string;
  title?: string;
  message?: string;
  default_action?: string;
  target_column?: string | null;
  dataset_snapshot_id?: string | null;
  source_ref?: string | null;
  risk_level?: string | null;
  confidence?: number | null;
  fallback_policy?: string | null;
};

export type PendingAutonomyIntervention = {
  payload: AutonomyIntervention;
  startedAt: number;
  durationSeconds: number;
};

export type JobArtifactsResponse = {
  job: Job;
  summary: Record<string, unknown>;
  artifact_ids: string[];
  missing_artifact_ids: string[];
  artifacts: Artifact[];
};

export type TokenSeriesPoint = {
  step: string;
  tokens: number;
};

export type AgentRetryState = {
  event_type?: string;
  event_index?: number;
  created_at?: string;
  retry_delay_seconds?: number;
  failure_kind?: string;
  exit_code?: number;
  idle_timeout_seconds?: number;
};

export type AgentWorkerEvent = {
  worker_id: string;
  display_name: string;
  status: string;
  headline: string;
  detail: string;
  job_id: string | null;
  job_type?: string;
  project_id?: string | null;
  project_name?: string | null;
  agent_session_id?: string | null;
  target_tab: string | null;
  target_anchor?: string | null;
  artifact_id?: string | null;
  artifact_ids?: string[];
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  ended_at?: string | null;
  run_after?: string | null;
  active?: boolean;
  human_description?: {
    title?: string;
    summary?: string;
    source?: string;
  } | null;
  token_usage: {
    source: string;
    is_estimate: boolean;
    series: TokenSeriesPoint[];
  };
  retry_state?: AgentRetryState | null;
};

export type AgentSession = {
  id: string;
  project_id: string;
  session_type: string;
  status: string;
  autonomy_mode: string;
  runner_kind: string;
  goal_text: string;
  workspace_path: string | null;
  codex_thread_id: string | null;
  pid: number | null;
  pid_is_observed_codex_process?: boolean | null;
  observed_runner_state?: string | null;
  observed_codex_process_count?: number | null;
  observed_codex_processes?: Record<string, unknown>[];
  turn_index: number;
  last_heartbeat_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  ended_at: string | null;
};

export type AgentTranscriptEvent = {
  id: string;
  project_id: string;
  session_id: string;
  event_index: number;
  source: string;
  event_type: string;
  role: string | null;
  title: string | null;
  content: string | null;
  payload: Record<string, unknown>;
  artifact_id: string | null;
  job_id: string | null;
  created_at: string;
};

export type AgentRawTranscript = {
  session_id: string | null;
  stdout_path: string | null;
  stderr_path: string | null;
  stdout_download_url: string | null;
  stderr_download_url: string | null;
  stdout_line_count: number;
  stderr_line_count: number;
  stdout_tail: string[];
  stderr_tail: string[];
  stdout_tail_lines: AgentRawTranscriptLine[];
  stderr_tail_lines: AgentRawTranscriptLine[];
  updated_at: string | null;
};

export type AgentConsoleMessageResponse = {
  schema_version: "agent_console_message.v1";
  project_id: string;
  session_id: string;
  status: string;
  delivered: boolean;
  woke_session: boolean;
  transcript_event_id: string;
  transcript_event_index: number;
  inbox_delivery: string;
  message: string;
};

export type AgentRawTranscriptLine = {
  line_number: number;
  text: string;
  parsed: Record<string, unknown> | null;
  truncated?: boolean;
  original_length?: number | null;
};

export type AgentRawTranscriptViewLine = AgentRawTranscriptLine & {
  stream: "stdout" | "stderr";
};

export type RequiredHumanDescription = {
  title: string;
  summary: string;
  source?: string;
};

export type AgentChatAction = {
  type: string;
  status: string;
  label: string;
  target_tab: string | null;
  target_anchor?: string | null;
  detail: string;
  job_id?: string;
  auto_start_worker?: boolean;
  queued_models?: string[];
  failures?: Array<Record<string, unknown>>;
  results?: Array<Record<string, unknown>>;
  artifact_id?: string;
  artifact_ids?: string[];
  asset_type?: string;
  entity_ids?: string[];
  run_id?: string;
};

export type AgentActionSummary = {
  schema_version: string;
  outcome: string;
  headline: string;
  what_changed: string[];
  what_needs_review: string[];
  next_step: { label?: string | null; target_tab?: string | null; target_anchor?: string | null; status?: string | null };
  boundaries: string[];
  actions: Array<Record<string, unknown>>;
};

export type AgentChatResponse = {
  schema_version: "agent_chat_turn.v1";
  project_id: string;
  user_message: string;
  assistant_message: string;
  intent: Record<string, unknown>;
  actions: AgentChatAction[];
  action_summary?: AgentActionSummary;
  response_brief?: Record<string, unknown> | null;
  response_composer?: Record<string, unknown> | null;
  worker_events: AgentWorkerEvent[];
  token_usage: { source: string; is_estimate: boolean; series: TokenSeriesPoint[] };
  next_focus: Record<string, unknown>;
  artifact_id: string;
  job?: Job | null;
};

export type AgentChatHistoryTurn = Omit<AgentChatResponse, "job"> & {
  job_id: string | null;
  created_at: string;
};

export type AgentChatMessage = {
  id?: string;
  role: "user" | "system";
  text: string;
  actions?: AgentChatAction[];
  actionSummary?: AgentActionSummary;
  responseBrief?: Record<string, unknown> | null;
  responseComposer?: Record<string, unknown> | null;
  createdAt?: string;
  transient?: boolean;
};

export type AgentConversationTurn = {
  id: string;
  user?: AgentChatMessage;
  assistant?: AgentChatMessage;
  createdAt?: string;
};

export const AGENT_CHAT_MESSAGE_HISTORY_LIMIT = 240;

export type ArtifactPreviewRequest = {
  artifactId: string;
  targetTab: Tab;
  anchor?: string | null;
  nonce: number;
};

export type HomeMemoryItem = {
  id: string;
  kind: "idea" | "finding";
  title: string;
  summary: string;
  meta: string;
  cta: string;
  target_tab: string;
  target_anchor: string;
  artifact_id?: string | null;
  created_at: string;
  signal_priority: number;
};

export type EquippedSkillItem = {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  relation_type: string;
};

export type SkillDraft = {
  name: string;
  description: string;
  instructions: string;
  tags: string;
};

export type RawAgentEvent = {
  id: string;
  timestamp: string;
  source: string;
  level: string;
  title: string;
  active?: boolean;
  body?: string | null;
  details?: Array<{ label: string; value: unknown }>;
  payload: Record<string, unknown>;
};

export type UploadFileProgress = {
  key: string;
  name: string;
  kind: string;
  size: number;
  progress: number;
};

export type UploadBundleProgress = {
  active: boolean;
  phase?: "transferring" | "server_processing" | "complete";
  overall: number;
  loadedBytes: number;
  totalBytes: number;
  files: UploadFileProgress[];
};

export type PortalIdea = {
  id: string;
  artifact_id?: string;
  text: string;
  status?: string;
  source?: string;
  created_at: string;
};

export type PortalUpdate = {
  type: string;
  project_id: string | null;
  title: string;
  summary: string;
  created_at: string;
  target_tab: string | null;
};

export type PortalOverview = {
  schema_version: "portal_overview.v1";
  generated_at: string;
  summary: Record<string, unknown>;
  projects: Array<{
    id: string;
    name: string;
    description: string | null;
    status: string;
    current_phase: string;
    updated_at: string;
  }>;
  recent_updates: PortalUpdate[];
  agent_activity: AgentWorkerEvent[];
  ideas: PortalIdea[];
};

export function filterDeletedProjects(projects: Project[], deletedProjectIds: Set<string>): Project[] {
  if (!deletedProjectIds.size) return projects;
  return projects.filter((project) => !deletedProjectIds.has(project.id));
}

export function filterDeletedProjectsFromPortalOverview(
  overview: PortalOverview | null,
  deletedProjectIds: Set<string>
): PortalOverview | null {
  if (!overview || !deletedProjectIds.size) return overview;
  return {
    ...overview,
    projects: overview.projects.filter((project) => !deletedProjectIds.has(project.id)),
    recent_updates: overview.recent_updates.filter(
      (update) => !update.project_id || !deletedProjectIds.has(update.project_id)
    ),
    agent_activity: overview.agent_activity.filter(
      (event) => !event.project_id || !deletedProjectIds.has(event.project_id)
    )
  };
}

export type AgentActivityResponse = {
  schema_version: "agent_activity.v1";
  project_id: string;
  generated_at: string;
  active_count: number;
  turn_state: TurnState;
  workers: AgentWorkerEvent[];
};

export type TurnState = {
  schema_version?: string;
  state: string;
  owner: "agent" | "user" | "system" | string;
  label: string;
  detail: string;
  observed_at?: string;
  input_attention?: boolean;
  confidence?: string;
  active_count?: number;
  active_job_id?: string | null;
  active_job_type?: string | null;
  active_codex_process_count?: number;
  last_output_at?: string | null;
  last_output_seconds_ago?: number | null;
  raw_transcript?: {
    session_id?: string | null;
    stdout_line_count?: number;
    stderr_line_count?: number;
    updated_at?: string | null;
  } | null;
  retry_state?: AgentRetryState | null;
  sources?: string[];
};

export type Run = {
  id: string;
  project_id: string;
  dataset_snapshot_id: string | null;
  evaluation_spec_id: string | null;
  split_manifest_id: string | null;
  evaluation_grade?: "formal" | "provisional";
  evaluation_grade_reason?: string | null;
  model_version_id: string | null;
  runner_type: string;
  status: string;
  metrics: Record<string, unknown>;
  summary_md: string | null;
  started_at: string | null;
  ended_at: string | null;
};

export type LeaderboardEntry = {
  rank: number;
  run_id: string;
  status: string;
  runner_type: string;
  model_id: string | null;
  model_label: string | null;
  model_family?: string | null;
  model_description?: string | null;
  features_used?: string[];
  feature_summary?: string | null;
  summary_md?: string | null;
  primary_metric_name: string | null;
  primary_metric_value: number | null;
  display_metric_name: string | null;
  display_metric_value: number | null;
  display_metric_available: boolean;
  display_metric_source: string;
  metrics: Record<string, unknown>;
  evaluation_spec_id: string | null;
  split_manifest_id: string | null;
  evaluation_grade?: "formal" | "provisional";
  evaluation_grade_reason?: string | null;
  model_version_id: string | null;
  pipeline_artifact_id: string;
  pipeline_input_contract?: {
    columns: Array<{ name: string; dtype?: string | null; required?: boolean }>;
    required_tables: Array<{
      name: string;
      role?: string | null;
      columns: Array<{ name: string; dtype?: string | null; required?: boolean }>;
      join_keys?: string[];
      as_of_column?: string | null;
      history_window?: string | null;
      optional?: boolean;
    }>;
    history_requirements?: Record<string, unknown> | null;
  } | null;
  pipeline_smoke_validation?: {
    status?: string | null;
    input_mode?: string | null;
    input_source?: string | null;
    input_rows?: number | null;
    output_rows?: number | null;
    runtime_isolated?: boolean;
  } | null;
  pipeline_runtime?: {
    last_run_status: "never_run" | "succeeded" | "failed" | string;
    last_job_id?: string | null;
    last_failed_job_id?: string | null;
    last_failure_at?: string | null;
    repair_observation_delivered?: boolean;
    superseded_by_artifact_id?: string | null;
  } | null;
  deliverable_expectations?: Array<{
    id: string;
    kind: string;
    subject_ref: string;
    status: string;
    created_from: string;
    fulfilled_by_artifact_id?: string | null;
    waived_rationale?: string | null;
    metadata?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
  }>;
  model_diagnostics?: {
    schema_version: string;
    status: string;
    standard_checks?: Record<string, { status: string; artifact_id?: string | null }>;
    availability?: Record<string, unknown>;
    artifact_refs?: Record<
      string,
      {
        artifact_id: string;
        asset_type: string;
        name?: string | null;
        download_url?: string | null;
        preview_url?: string | null;
      }
    >;
  };
  related_notebook_artifact_ids?: string[];
  related_notebooks?: Array<{
    artifact_id: string;
    title?: string | null;
    notebook_kind?: string | null;
    status?: string | null;
    native_marimo_status?: string | null;
    needs_attention?: boolean;
    openable?: boolean;
    run_id?: string | null;
    model_version_id?: string | null;
    related_run_ids?: string[];
    recommendation_score?: number | null;
  }>;
};

export type PilotDeploymentIndex = {
  schema_version: string;
  project_id: string;
  deployments: PilotDeploymentRead[];
};

export type PilotDeploymentRead = {
  id: string;
  project_id: string;
  pipeline_artifact_id: string;
  model_version_id: string | null;
  experiment_run_id: string | null;
  status: string;
  started_at: string;
  notes: string | null;
  prediction_batches: PilotPredictionBatchRead[];
  outcome_batches: PilotOutcomeBatchRead[];
  scoring_reports: PilotScoringReportRead[];
  validation_audits: PilotValidationAuditRead[];
};

export type PilotPredictionBatchRead = {
  id: string;
  deployment_id: string;
  as_of: string;
  input_artifact_id: string;
  predictions_artifact_id: string;
  row_count: number | null;
  created_at: string;
};

export type PilotOutcomeBatchRead = {
  id: string;
  deployment_id: string;
  outcomes_artifact_id: string;
  join_keys: string[];
  matched_rows: number | null;
  ingested_at: string;
};

export type PilotScoringReportRead = {
  artifact: Artifact;
  deployment_id: string | null;
  prediction_batch_id: string | null;
  outcome_batch_id: string | null;
  metrics: Record<string, unknown>;
  matched_rows: number | null;
  metric_count: number | null;
  as_of_violations: Record<string, unknown>;
};

export type PilotValidationAuditRead = {
  artifact: Artifact;
  deployment_id: string | null;
  scheme_verdict: string | null;
  next_iteration_focus: string | null;
  gap_decomposition: Array<Record<string, unknown>>;
  scoring_report_artifact_ids: string[];
};

export type ModelVersion = {
  id: string;
  name: string;
  version: number;
  model_family: string;
  model_type: string;
  task_type: string;
  artifact_id: string;
  experiment_run_id: string;
  primary_metric_name: string | null;
  primary_metric_value: number | null;
  status: string;
  created_at: string;
};

export type ModelValidation = {
  job: Job;
  model_version_id: string;
  validation_status: string | null;
  max_abs_metric_delta: number | null;
  metrics: Record<string, unknown>;
  artifacts: Artifact[];
  created_at: string;
  ended_at: string | null;
};

export type ResearchBrief = {
  id: string;
  title: string;
  question: string;
  summary_md: string;
  sources: Array<Record<string, unknown>>;
  key_findings: string[];
  recommended_approaches: Array<Record<string, unknown>>;
  artifact_id: string | null;
  status: string;
  created_at: string;
};

export type StrategyAction = {
  action_type: "navigate" | "api" | "agent_task";
  label: string;
  display_label?: string;
  target_tab: string;
  reason: string;
  display_reason?: string;
  endpoint: string | null;
  method: string | null;
  prompt: string | null;
  display?: {
    label?: string;
    reason?: string;
  };
};

export type StrategyLane = {
  lane_id: string;
  title: string;
  display_title?: string;
  status: string;
  why: string;
  display_why?: string;
  evidence_artifact_ids: string[];
  next_action: string;
  display_next_action?: string;
  agent_role: string;
  display_agent_role?: string;
  display?: {
    title?: string;
    why?: string;
    next_action?: string;
    agent_role?: string;
  };
};

export type AdaptiveStrategyBrief = {
  schema_version: string;
  response_locale?: string | null;
  project: Record<string, unknown>;
  summary: Record<string, unknown>;
  recommended_next_action: StrategyAction;
  candidate_lanes: StrategyLane[];
  codex_handoff: Record<string, unknown>;
  reporting_plan: Record<string, unknown>;
  artifact_refs: Array<Record<string, unknown>>;
  risk_register: Array<Record<string, unknown>>;
  latest_artifact_id: string | null;
  generated_at: string;
};

export type ResearchPlanBlockStatus = "done" | "active" | "pending" | "blocked" | "waiting" | "skipped";

export type PendingAnchorNavigation = {
  anchor: string;
  nonce: number;
};

export type ResearchPlanSubtask = {
  id: string;
  title: string;
  detail: string;
  status: ResearchPlanBlockStatus;
  evidence: string | null;
  targetTab?: Tab | null;
  targetAnchor?: string | null;
  onClick?: () => void;
};

export type ResearchPlanEvidenceLinkItem = {
  id: string;
  artifactId?: string | null;
  outputKind?: "notebook" | "report" | "run" | "pipeline" | "research" | "artifact";
  title: string;
  detail: string;
  evidence: string | null;
  targetTab?: Tab | null;
  targetAnchor?: string | null;
  onClick?: () => void;
};

export type ResearchPlanBlock = {
  id: string;
  title: string;
  subtitle: string;
  status: ResearchPlanBlockStatus;
  eyebrow: string;
  evidence: string | null;
  subtasks?: ResearchPlanSubtask[];
  evidenceLinks?: ResearchPlanEvidenceLinkItem[];
  isCurrentWork?: boolean;
  onClick?: () => void;
};

export type ResearchPlanArtifactLink = {
  id: string;
  link_type?: string | null;
  revision_id?: string | null;
  node_id: string;
  role: string;
  artifact_id?: string | null;
  run_id?: string | null;
  artifact_name?: string | null;
  asset_type?: string | null;
  artifact_version?: number | null;
  target_tab?: string | null;
  target_anchor?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
};

export type ResearchPlanCurrentWork = {
  id: string;
  project_id: string;
  research_plan_id: string;
  revision_id?: string | null;
  node_id: string;
  status: ResearchPlanBlockStatus;
  summary: string;
  expected_outputs: string[];
  updated_by_type: string;
  updated_by?: string | null;
  updated_at: string;
  source?: string | null;
  activity_state?: "active" | "scheduled" | "paused" | "inactive" | string;
  is_live?: boolean;
  agent_session_id?: string | null;
  agent_session_status?: string | null;
};

export type ResearchPlanTimelineBlock = {
  id: string;
  title: string;
  subtitle: string;
  status: ResearchPlanBlockStatus;
  evidence: string | null;
  target_tab: string | null;
  target_anchor: string | null;
  phase?: string | null;
  next_action?: string | null;
  done_criteria?: string | null;
  blockers?: string[];
  supporting_artifacts?: Array<{
    path: string;
    exists: boolean | null;
  }>;
  missing_supporting_artifact_count?: number;
  status_adjustment_reason?: string | null;
  attached_artifacts?: ResearchPlanArtifactLink[];
  subtasks: Array<{
    id: string;
    title: string;
    detail: string;
    status: ResearchPlanBlockStatus;
    evidence: string | null;
    target_tab: string | null;
    target_anchor: string | null;
  }>;
};

export type ResearchPlanContractValidation = {
  schema_version: "research_plan_contract_validation.v1";
  status: "ok" | "needs_revision";
  issue_count: number;
  error_count: number;
  warning_count: number;
  issues: Array<{
    code?: string;
    path?: string;
    message?: string;
    fix?: string;
    severity?: "error" | "warning" | string;
  }>;
};

export type ResearchPlanTimelineResponse = {
  schema_version: "research_plan_timeline.v1";
  project_id: string;
  source_artifact_id: string | null;
  response_locale?: string | null;
  requested_locale?: string | null;
  authored_locale?: string | null;
  generated_at: string;
  contract_validation?: ResearchPlanContractValidation;
  ignored_source_artifact?: {
    schema_version: "ignored_research_plan_source.v1";
    status: "needs_revision";
    source_artifact_id: string;
    artifact_name?: string | null;
    artifact_version?: number | null;
    reason?: string | null;
    contract_validation: ResearchPlanContractValidation;
  } | null;
  current_work?: ResearchPlanCurrentWork | null;
  artifact_links?: ResearchPlanArtifactLink[];
  blocks: ResearchPlanTimelineBlock[];
};

export type Idea = {
  id: string;
  title: string;
  hypothesis: string;
  approach_type: string;
  rationale_md: string;
  feature_strategy: Record<string, unknown>;
  modeling_strategy: Record<string, unknown>;
  evaluation_notes_md: string | null;
  expected_artifacts: string[];
  agent_task_contract: Record<string, unknown>;
  confidence: number;
  risk_level: string;
  status: string;
  priority: number;
  artifact_id: string | null;
  created_at: string;
};

export type Report = {
  id: string;
  report_type: string;
  title: string;
  summary: string;
  artifact_id: string;
  status: string;
  created_at: string;
};

export type DecisionReportBundle = {
  schema_version: string;
  generated_at: string;
  project: Record<string, unknown>;
  readiness: Record<string, unknown>;
  recommended_next_action: Record<string, unknown>;
  next_actions: Array<Record<string, unknown>>;
  coverage_summary: Record<string, unknown>;
  evidence_map: Array<Record<string, unknown>>;
  sections: Record<string, unknown>;
  counts: Record<string, unknown>;
  source_assets: Array<Record<string, unknown>>;
  safety: Record<string, unknown>;
};

export type DecisionReportCurrent = {
  schema_version: string;
  project_id: string;
  available: boolean;
  generated_at: string | null;
  report: Record<string, unknown> | null;
  report_artifact: Record<string, unknown> | null;
  bundle_artifact: Record<string, unknown> | null;
  bundle: DecisionReportBundle | null;
  action_endpoint: string;
};

export type ResultReadout = {
  schema_version: "result_readout.v1";
  project_id: string;
  status: string;
  headline: string;
  summary: string;
  top_run: Record<string, unknown> | null;
  metric_story: string;
  evaluation_contract: Record<string, unknown>;
  comparison: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  notebook: Record<string, unknown>;
  decision_report: Record<string, unknown>;
  read_order: Array<Record<string, unknown>>;
  next_action: Record<string, unknown>;
  evidence_gaps: Array<Record<string, unknown>>;
  safety: Record<string, unknown>;
};

export type VisualizationSpec = {
  id: string;
  title: string;
  chart_type: string;
  spec: Record<string, unknown>;
  artifact_id: string;
  status: string;
  created_at: string;
};

export type AgentTaskResultArtifact = {
  id: string;
  asset_type: string;
  name: string;
  version: number;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type AgentTaskResultReport = {
  id: string;
  report_type: string;
  title: string;
  artifact_id: string;
  status: string;
  created_at: string;
};

export type AgentTaskResult = {
  job_id: string;
  job_type: string;
  job_status: string;
  created_at: string;
  source: { type: string; id: string | null };
  task_id: string | null;
  agent_status: string | null;
  agent_final_message: string | null;
  readiness_status: string | null;
  requires_human_review: boolean | null;
  experiment_run: { id: string; status: string; runner_type: string } | null;
  metrics: Record<string, unknown>;
  reports: Record<string, AgentTaskResultReport | null>;
  evidence: Record<string, { id: string; summary: string; strength: string } | null>;
  visualizations: Record<string, { id: string; title: string; chart_type: string; artifact_id: string } | null>;
  artifacts: Record<string, AgentTaskResultArtifact | null>;
  artifact_ids: string[];
  citation_audit: {
    source_count: number;
    citation_count: number;
    external_network_accessed: boolean;
    connector_credentials_materialized: boolean;
    research_source_pack_artifact_id: string | null;
  };
  relational_context: {
    status: string;
    source_count: number;
    roles: unknown[];
    summary_artifact_id: string | null;
    usable_feature_count: number;
    generated_feature_count: number;
    deferred_safety_check_count: number;
    scenario_count: number;
    recommendation_count: number;
    coverage: Record<string, unknown>;
    runner_guidance: unknown[];
  };
  approach_decision_trace: {
    status: string;
    artifact_id: string | null;
    policy: string | null;
    recommended_approach_count: number;
    recommended_asset_count: number;
    research_query_count: number;
    relational_context_available: boolean;
    approach_considered_count: number;
    deferred_or_rejected_count: number;
    new_hypothesis_count: number;
    runner_may: unknown[];
  };
};

export type Insight = {
  id: string;
  insight_type: string;
  title: string;
  summary: string;
  severity: string;
  confidence: number;
  status: string;
  source_asset_ids: Array<{ asset_type: string; asset_id: string }>;
  evidence_ids: string[];
  artifact_id: string;
  created_at: string;
};

export type Overview = {
  project: Project;
  counts: Record<string, number>;
  next_actions: string[];
  latest_dataset_snapshot_id: string | null;
  high_risk_assumptions: Assumption[];
  recent_artifacts: Artifact[];
  recent_jobs: Job[];
};

export type LineageEdge = {
  id: string;
  from_asset_type: string;
  from_asset_id: string;
  to_asset_type: string;
  to_asset_id: string;
  relation_type: string;
};
