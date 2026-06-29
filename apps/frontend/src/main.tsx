import React from "react";
import ReactDOM from "react-dom/client";
import {
  AlertTriangle,
  BarChart3,
  Check,
  Database,
  Download,
  Eye,
  FileText,
  KeyRound,
  GitBranch,
  Layers,
  Library,
  Lightbulb,
  ListChecks,
  Loader2,
  MessageSquare,
  Moon,
  PieChart,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings as SettingsIcon,
  Sun,
  Upload
} from "lucide-react";
import "./styles.css";

type DisplayTheme = "light" | "dark";
type LocaleDirection = "ltr" | "rtl";
type LocaleSource = "built_in" | "dynamic";

type UserSettings = {
  locale: string;
  requestedLocale: string;
  dynamicLanguageRequest: string;
  displayTheme: DisplayTheme;
};

const userSettingsStorageKey = "tablex.userSettings.v1";
const dynamicLocaleStorageKey = "tablex.dynamicLocalePacks.v1";

const defaultUserSettings: UserSettings = {
  locale: "en-US",
  requestedLocale: "",
  dynamicLanguageRequest: "",
  displayTheme: "light"
};

const englishMessages = {
  predictionWorkbench: "Prediction workbench",
  projects: "Projects",
  refreshProjects: "Refresh projects",
  loadingProjects: "Loading projects",
  projectDescription: "Evaluation-first workspace for tabular prediction tasks.",
  createFirstProject: "Create the first prediction project",
  createFirstProjectBody:
    "Projects hold dataset snapshots, assumptions, evaluation designs, artifacts, jobs, and lineage for one prediction task.",
  newProjectName: "New project name",
  create: "Create",
  tabOverview: "Overview",
  tabData: "Data",
  tabUnderstanding: "Understanding",
  tabAssumptions: "Assumptions",
  tabEvaluation: "Evaluation",
  tabApproach: "Approach",
  tabExperiments: "Experiments",
  tabLeaderboard: "Leaderboard",
  tabReports: "Reports",
  tabAssets: "Assets",
  tabLibrary: "Library",
  tabJobs: "Jobs",
  tabLineage: "Lineage",
  focusGuideTitle: "Focus Guide",
  recommendedFocus: "Recommended focus",
  whyThisMatters: "Why this matters",
  goToFocus: "Go to focus",
  focusEvidence: "Signals",
  otherUsefulViews: "Useful next views",
  viewDetails: "Show supporting detail",
  hideDetails: "Hide supporting detail",
  atAGlance: "At a glance",
  focusUploadData: "Upload or import a dataset",
  focusUploadDataReason: "The project cannot build understanding, assumptions, evaluation, or agent tasks until a DatasetSnapshot exists.",
  focusUnderstandData: "Understand the data before choosing a target or evaluation",
  focusUnderstandDataReason: "The next useful decision depends on schema, target candidates, leakage risk, missingness, and semantic assumptions.",
  focusAssumptions: "Resolve risky assumptions",
  focusAssumptionsReason: "High-risk assumptions can silently invalidate evaluation or feature design if they are not reviewed.",
  focusEvaluation: "Lock a reliable evaluation design",
  focusEvaluationReason: "Modeling and agent work should stay downstream of EvaluationSpec and SplitManifest constraints.",
  focusApproach: "Plan the next flexible agent approach",
  focusApproachReason: "The harness has enough context to ask Codex for a scoped approach without forcing a fixed recipe.",
  focusExperiments: "Run or inspect experiments",
  focusExperimentsReason: "The project needs run evidence, diagnostics, and reports before comparing approaches.",
  focusReports: "Read the decision report",
  focusReportsReason: "Reports summarize readiness, risks, evidence, and next actions without requiring raw artifact inspection.",
  settings: "User Settings",
  settingsHint: "Language, locale packs, and display preferences are stored locally for this workbench.",
  language: "Language",
  localeCatalog: "Locale catalog",
  localePack: "Locale pack",
  activeLocale: "Active locale",
  english: "English",
  japanese: "Japanese",
  dynamic: "Dynamic / generated",
  requestedLocale: "Other locale or language",
  requestedLocalePlaceholder: "e.g. fr-FR, es-ES, Korean, pt-BR",
  addDynamicLocale: "Use dynamic locale",
  localeFallbackHint: "Missing translations fall back to English until a generated pack is reviewed.",
  dynamicLanguageRequest: "Dynamic language request",
  localizationRequestPlaceholder: "Tone, terminology, audience, or locale-specific formatting",
  appearance: "Appearance",
  lightTheme: "Light",
  darkTheme: "Dark",
  createLocalizationTask: "Create AgentTask",
  localizationTaskHint:
    "Creates a harness-owned AgentTaskContract so Codex can later generate or revise a locale pack.",
  localizationTaskCreated: "Localization AgentTaskContract created.",
  noProjectForLocalization: "Select a project before creating a localization AgentTask.",
  agentChatTitle: "Agent Chat",
  agentChatSubtitle: "Codex-ready runner channel",
  agentChatPlaceholder: "Ask for the next experiment, feature idea, diagnosis, or report",
  createAgentTaskContract: "Create AgentTaskContract",
  downloadLatestAgentTaskContract: "Download latest AgentTaskContract",
  agentTaskContractCreated: "AgentTaskContract created.",
  strategyBriefTitle: "Adaptive Strategy Brief",
  strategyBriefSubtitle: "One guided next step without forcing a fixed modeling recipe.",
  strategyRecommendedAction: "Recommended action",
  strategyCodexHandoff: "Codex handoff",
  strategyLaneMap: "Strategy lanes",
  strategySaveSnapshot: "Save brief",
  strategyRunAction: "Run action",
  strategyNoBrief: "Strategy guidance will appear here after the backend summarizes project artifacts, assumptions, evaluation, research, and runner handoff state.",
  strategyArtifacts: "Artifacts",
  strategyOpenItems: "Open items",
  strategyIdeas: "Ideas",
  strategyRuns: "Runs",
  translate: "Translate",
  translating: "Translating",
  translatedDraft: "Translated draft",
  originalSource: "Original source",
  codexTranslationPending: "Codex translation task planned; showing the available draft artifact.",
  close: "Close"
};

type LocaleMessages = typeof englishMessages;

const japaneseMessages: LocaleMessages = {
  predictionWorkbench: "予測ワークベンチ",
  projects: "プロジェクト",
  refreshProjects: "プロジェクトを更新",
  loadingProjects: "プロジェクトを読み込み中",
  projectDescription: "表データ予測課題のためのEvaluation-firstワークスペースです。",
  createFirstProject: "最初の予測プロジェクトを作成",
  createFirstProjectBody:
    "ProjectにはDatasetSnapshot、Assumption、評価設計、artifact、job、lineageを保持します。",
  newProjectName: "新しいプロジェクト名",
  create: "作成",
  tabOverview: "概要",
  tabData: "データ",
  tabUnderstanding: "理解",
  tabAssumptions: "仮定",
  tabEvaluation: "評価",
  tabApproach: "アプローチ",
  tabExperiments: "実験",
  tabLeaderboard: "リーダーボード",
  tabReports: "レポート",
  tabAssets: "アセット",
  tabLibrary: "ライブラリ",
  tabJobs: "ジョブ",
  tabLineage: "リネージ",
  focusGuideTitle: "Focus Guide",
  recommendedFocus: "推奨フォーカス",
  whyThisMatters: "なぜ重要か",
  goToFocus: "移動",
  focusEvidence: "判断シグナル",
  otherUsefulViews: "次に役立つ画面",
  viewDetails: "補足詳細を表示",
  hideDetails: "補足詳細を隠す",
  atAGlance: "概況",
  focusUploadData: "データをuploadまたはimportする",
  focusUploadDataReason: "DatasetSnapshotがないと、data understanding、仮定、評価設計、agent taskを進められません。",
  focusUnderstandData: "targetや評価を決める前にデータを理解する",
  focusUnderstandDataReason: "schema、target候補、leakage risk、missingness、semantic assumptionsを見てから次の意思決定をします。",
  focusAssumptions: "リスクの高い仮定を確認する",
  focusAssumptionsReason: "高リスクの仮定を放置すると、評価や特徴量設計が静かに壊れる可能性があります。",
  focusEvaluation: "信頼できる評価設計を固定する",
  focusEvaluationReason: "modelingやagent作業はEvaluationSpecとSplitManifestの制約の下に置くべきです。",
  focusApproach: "次の柔軟なagent approachを計画する",
  focusApproachReason: "固定recipeにせず、現時点の証拠を渡してCodexにスコープ付きで考えさせられます。",
  focusExperiments: "実験を実行または確認する",
  focusExperimentsReason: "approachを比較する前に、run evidence、diagnostics、reportが必要です。",
  focusReports: "decision reportを読む",
  focusReportsReason: "raw artifactを追わなくても、readiness、risk、evidence、next actionを把握できます。",
  settings: "ユーザー設定",
  settingsHint: "言語、locale pack、表示設定をこのworkbenchのlocal設定として保存します。",
  language: "言語",
  localeCatalog: "Locale catalog",
  localePack: "Locale pack",
  activeLocale: "現在のlocale",
  english: "英語",
  japanese: "日本語",
  dynamic: "動的 / 生成",
  requestedLocale: "その他のlocaleまたは言語",
  requestedLocalePlaceholder: "例: fr-FR, es-ES, Korean, pt-BR",
  addDynamicLocale: "動的localeを使う",
  localeFallbackHint: "未翻訳キーは、生成packがreviewされるまで英語fallbackで表示します。",
  dynamicLanguageRequest: "動的言語リクエスト",
  localizationRequestPlaceholder: "トーン、用語、対象ユーザー、locale固有の表記など",
  appearance: "表示",
  lightTheme: "Light",
  darkTheme: "Dark",
  createLocalizationTask: "AgentTaskを作成",
  localizationTaskHint:
    "Codexが将来locale packを生成・更新できるよう、Tablex管理のAgentTaskContractを作成します。",
  localizationTaskCreated: "Localization AgentTaskContractを作成しました。",
  noProjectForLocalization: "Localization AgentTaskを作成する前にProjectを選択してください。",
  agentChatTitle: "Agent Chat",
  agentChatSubtitle: "Codex対応runnerチャネル",
  agentChatPlaceholder: "次の実験、特徴量案、診断、レポートを依頼する",
  createAgentTaskContract: "AgentTaskContractを作成",
  downloadLatestAgentTaskContract: "最新のAgentTaskContractをダウンロード",
  agentTaskContractCreated: "AgentTaskContractを作成しました。",
  strategyBriefTitle: "Adaptive Strategy Brief",
  strategyBriefSubtitle: "固定recipeにせず、次の一手だけをガイドします。",
  strategyRecommendedAction: "推奨アクション",
  strategyCodexHandoff: "Codexへの引き渡し",
  strategyLaneMap: "Strategy lanes",
  strategySaveSnapshot: "Briefを保存",
  strategyRunAction: "実行",
  strategyNoBrief: "project artifacts、assumptions、evaluation、research、runner handoff stateをbackendが要約すると、ここにstrategy guidanceが表示されます。",
  strategyArtifacts: "Artifacts",
  strategyOpenItems: "Open items",
  strategyIdeas: "Ideas",
  strategyRuns: "Runs",
  translate: "翻訳",
  translating: "翻訳中",
  translatedDraft: "翻訳ドラフト",
  originalSource: "原文",
  codexTranslationPending: "Codex翻訳タスクを計画しました。利用可能なドラフトartifactを表示しています。",
  close: "閉じる"
};

type LocalePack = {
  locale: string;
  label: string;
  nativeLabel: string;
  direction: LocaleDirection;
  source: LocaleSource;
  fallbackLocale: string;
  messages: Partial<LocaleMessages>;
};

const builtinLocalePacks: LocalePack[] = [
  {
    locale: "en-US",
    label: "English",
    nativeLabel: "English",
    direction: "ltr",
    source: "built_in",
    fallbackLocale: "en-US",
    messages: englishMessages
  },
  {
    locale: "ja-JP",
    label: "Japanese",
    nativeLabel: "日本語",
    direction: "ltr",
    source: "built_in",
    fallbackLocale: "en-US",
    messages: japaneseMessages
  }
];

function loadUserSettings(): UserSettings {
  try {
    const raw = window.localStorage.getItem(userSettingsStorageKey);
    if (!raw) return defaultUserSettings;
    const parsed = JSON.parse(raw) as Partial<UserSettings> & {
      language?: string;
      customLanguage?: string;
    };
    const migratedLocale =
      typeof parsed.locale === "string"
        ? normalizeLocale(parsed.locale)
        : parsed.language === "ja"
          ? "ja-JP"
          : parsed.language === "dynamic" && typeof parsed.customLanguage === "string" && parsed.customLanguage.trim()
            ? normalizeLocale(parsed.customLanguage)
            : "en-US";
    return {
      locale: migratedLocale,
      requestedLocale:
        typeof parsed.requestedLocale === "string"
          ? parsed.requestedLocale
          : typeof parsed.customLanguage === "string"
            ? parsed.customLanguage
            : "",
      dynamicLanguageRequest:
        typeof parsed.dynamicLanguageRequest === "string" ? parsed.dynamicLanguageRequest : "",
      displayTheme: parsed.displayTheme === "dark" ? "dark" : "light"
    };
  } catch {
    return defaultUserSettings;
  }
}

function normalizeLocale(value: string) {
  return value.trim().replace("_", "-") || "en-US";
}

function localeLabel(locale: string) {
  return normalizeLocale(locale)
    .split("-")
    .filter(Boolean)
    .map((part, index) => (index === 0 ? part.toLowerCase() : part.toUpperCase()))
    .join("-");
}

function loadDynamicLocalePacks(): LocalePack[] {
  try {
    const raw = window.localStorage.getItem(dynamicLocaleStorageKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<LocalePack>[];
    return parsed
      .map((pack) => ({
        locale: typeof pack.locale === "string" ? normalizeLocale(pack.locale) : "",
        label: typeof pack.label === "string" ? pack.label : "",
        nativeLabel: typeof pack.nativeLabel === "string" ? pack.nativeLabel : "",
        direction: pack.direction === "rtl" ? ("rtl" as const) : ("ltr" as const),
        source: "dynamic" as const,
        fallbackLocale: "en-US",
        messages: typeof pack.messages === "object" && pack.messages ? pack.messages : {}
      }))
      .filter((pack) => pack.locale && !builtinLocalePacks.some((builtin) => builtin.locale === pack.locale));
  } catch {
    return [];
  }
}

function mergeLocalePacks(dynamicLocalePacks: LocalePack[]) {
  const seen = new Set<string>();
  return [...builtinLocalePacks, ...dynamicLocalePacks].filter((pack) => {
    if (seen.has(pack.locale)) return false;
    seen.add(pack.locale);
    return true;
  });
}

function copyForLocale(locale: string, localePacks: LocalePack[]): LocaleMessages {
  const pack = localePacks.find((candidate) => candidate.locale === locale);
  return { ...englishMessages, ...(pack?.messages ?? {}) };
}

function resolveLocalePack(locale: string, localePacks: LocalePack[]) {
  return localePacks.find((pack) => pack.locale === locale) ?? builtinLocalePacks[0];
}

function createDynamicLocalePack(localeInput: string): LocalePack {
  const locale = localeLabel(localeInput);
  return {
    locale,
    label: locale,
    nativeLabel: locale,
    direction: "ltr",
    source: "dynamic",
    fallbackLocale: "en-US",
    messages: {}
  };
}

const LocaleContext = React.createContext<{ text: LocaleMessages; locale: string }>({
  text: englishMessages,
  locale: "en-US"
});

function useLocale() {
  return React.useContext(LocaleContext);
}

type Project = {
  id: string;
  name: string;
  description: string | null;
  task_type: string | null;
  target_column: string | null;
  current_phase: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type DatasetSnapshot = {
  id: string;
  project_id: string;
  artifact_id: string;
  source_type: string;
  source_ref: string | null;
  row_count: number | null;
  column_count: number | null;
  schema_hash: string;
  created_at: string;
};

type Artifact = {
  id: string;
  asset_type: string;
  name: string;
  version: number;
  size_bytes: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

type ArtifactPreview = {
  id: string;
  asset_type: string;
  name: string;
  filename: string;
  content_type: string;
  preview_available: boolean;
  preview: string | null;
  truncated: boolean;
  size_bytes: number | null;
  reason: string | null;
};

type TranslationResult = {
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

type BenchmarkDataset = {
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

type BenchmarkSourceCard = {
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

type BenchmarkLocalStatus = {
  root_path: string;
  exists: boolean;
  ready: boolean;
  required_found_count: number;
  required_missing_count: number;
  recommended_found_count: number;
  recommended_missing_count: number;
  missing_required: Array<{ expected: string[]; role: string | null; description: string | null }>;
};

type LibraryAsset = {
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

type AssetReference = {
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

type Question = {
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

type Assumption = {
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

type AssumptionReviewAction = {
  id: string;
  label: string;
  action_type: "confirm_assumption" | "challenge_assumption" | "answer_question" | "navigate";
  method: string | null;
  endpoint: string | null;
  request_body: Record<string, unknown> | null;
};

type AssumptionReviewItem = {
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

type AssumptionReviewQueue = {
  schema_version: "assumption_review_queue.v1";
  project_id: string;
  generated_at: string;
  next_item: AssumptionReviewItem | null;
  queue: AssumptionReviewItem[];
  counts: Record<string, number>;
  guidance: string[];
};

type EvaluationCandidate = {
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

type EvaluationSpec = {
  id: string;
  name: string;
  split_type: string;
  primary_metric: string;
  status: string;
  risk_level: string;
  source_evaluation_candidate_id: string | null;
};

type Job = {
  id: string;
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
  started_at: string | null;
  ended_at: string | null;
  output: Record<string, unknown>;
};

type JobArtifactsResponse = {
  job: Job;
  summary: Record<string, unknown>;
  artifact_ids: string[];
  missing_artifact_ids: string[];
  artifacts: Artifact[];
};

type Run = {
  id: string;
  project_id: string;
  dataset_snapshot_id: string | null;
  evaluation_spec_id: string | null;
  split_manifest_id: string | null;
  model_version_id: string | null;
  runner_type: string;
  status: string;
  metrics: Record<string, unknown>;
  summary_md: string | null;
  started_at: string | null;
  ended_at: string | null;
};

type LeaderboardEntry = {
  rank: number;
  run_id: string;
  status: string;
  runner_type: string;
  primary_metric_name: string | null;
  primary_metric_value: number | null;
  metrics: Record<string, unknown>;
  evaluation_spec_id: string | null;
  split_manifest_id: string | null;
  model_version_id: string | null;
};

type ModelVersion = {
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

type ModelValidation = {
  job: Job;
  model_version_id: string;
  validation_status: string | null;
  max_abs_metric_delta: number | null;
  metrics: Record<string, unknown>;
  artifacts: Artifact[];
  created_at: string;
  ended_at: string | null;
};

type ResearchBrief = {
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

type StrategyAction = {
  action_type: "navigate" | "api" | "agent_task";
  label: string;
  target_tab: string;
  reason: string;
  endpoint: string | null;
  method: string | null;
  prompt: string | null;
};

type StrategyLane = {
  lane_id: string;
  title: string;
  status: string;
  why: string;
  evidence_artifact_ids: string[];
  next_action: string;
  agent_role: string;
};

type AdaptiveStrategyBrief = {
  schema_version: string;
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

type Idea = {
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

type Report = {
  id: string;
  report_type: string;
  title: string;
  summary: string;
  artifact_id: string;
  status: string;
  created_at: string;
};

type VisualizationSpec = {
  id: string;
  title: string;
  chart_type: string;
  spec: Record<string, unknown>;
  artifact_id: string;
  status: string;
  created_at: string;
};

type AgentTaskResultArtifact = {
  id: string;
  asset_type: string;
  name: string;
  version: number;
  metadata: Record<string, unknown>;
  created_at: string;
};

type AgentTaskResultReport = {
  id: string;
  report_type: string;
  title: string;
  artifact_id: string;
  status: string;
  created_at: string;
};

type AgentTaskResult = {
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

type Insight = {
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

type Overview = {
  project: Project;
  counts: Record<string, number>;
  next_actions: string[];
  latest_dataset_snapshot_id: string | null;
  high_risk_assumptions: Assumption[];
  recent_artifacts: Artifact[];
  recent_jobs: Job[];
};

type LineageEdge = {
  id: string;
  from_asset_type: string;
  from_asset_id: string;
  to_asset_type: string;
  to_asset_id: string;
  relation_type: string;
};

const apiBase = import.meta.env.VITE_API_BASE ?? "";
const tabItems = [
  { id: "Overview", labelKey: "tabOverview" },
  { id: "Data", labelKey: "tabData" },
  { id: "Understanding", labelKey: "tabUnderstanding" },
  { id: "Assumptions", labelKey: "tabAssumptions" },
  { id: "Evaluation", labelKey: "tabEvaluation" },
  { id: "Approach", labelKey: "tabApproach" },
  { id: "Experiments", labelKey: "tabExperiments" },
  { id: "Leaderboard", labelKey: "tabLeaderboard" },
  { id: "Reports", labelKey: "tabReports" },
  { id: "Assets", labelKey: "tabAssets" },
  { id: "Library", labelKey: "tabLibrary" },
  { id: "Jobs", labelKey: "tabJobs" },
  { id: "Lineage", labelKey: "tabLineage" }
] as const satisfies ReadonlyArray<{ id: string; labelKey: keyof LocaleMessages }>;
type Tab = (typeof tabItems)[number]["id"];

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
  const match = tabItems.find((item) => item.id === value);
  return match ? match.id : fallback;
}

type FocusRecommendation = {
  tab: Tab;
  title: string;
  reason: string;
  evidence: string[];
  secondaryTabs: Tab[];
  primaryAction: FocusAction | null;
  secondaryActions: FocusAction[];
  riskLevel: string | null;
  confidence: number | null;
  suggestedAgentPrompt: string | null;
  source: "api" | "local";
};

type FocusAction = {
  id: string;
  label: string;
  targetTab: Tab;
  actionType: "navigate" | "run_endpoint" | "agent_task_prompt";
  method: string | null;
  endpoint: string | null;
  requestBody: Record<string, unknown> | null;
  prompt: string | null;
  disabled: boolean;
  disabledReason: string | null;
};

type ProjectGuidanceAction = {
  id: string;
  label: string;
  target_tab: string;
  action_type: "navigate" | "run_endpoint" | "agent_task_prompt";
  method: string | null;
  endpoint: string | null;
  request_body: Record<string, unknown> | null;
  prompt: string | null;
  disabled: boolean;
  disabled_reason: string | null;
};

type ProjectGuidance = {
  schema_version: "project_guidance.v1";
  project_id: string;
  generated_at: string;
  attention_budget: number;
  overview_mode: "guided";
  recommended_focus: {
    focus_key: string;
    target_tab: string;
    title: string;
    reason: string;
    risk_level: string;
    confidence: number;
    evidence: string[];
    primary_action: ProjectGuidanceAction;
    secondary_actions: ProjectGuidanceAction[];
    suggested_agent_prompt: string | null;
  };
  state_summary: Record<string, unknown>;
  supporting_counts: Record<string, number>;
  hidden_detail_groups: Array<Record<string, unknown>>;
  agent_guidance: string[];
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

function tabLabel(tab: Tab, text: LocaleMessages) {
  const item = tabItems.find((candidate) => candidate.id === tab);
  return item ? text[item.labelKey] : tab;
}

function normalizeTab(value: string | null | undefined): Tab {
  return tabItems.some((item) => item.id === value) ? (value as Tab) : "Overview";
}

function guidanceActionToFocusAction(action: ProjectGuidanceAction): FocusAction {
  return {
    id: action.id,
    label: action.label,
    targetTab: normalizeTab(action.target_tab),
    actionType: action.action_type,
    method: action.method,
    endpoint: action.endpoint,
    requestBody: action.request_body,
    prompt: action.prompt,
    disabled: action.disabled,
    disabledReason: action.disabled_reason
  };
}

function focusFromGuidance(guidance: ProjectGuidance, text: LocaleMessages): FocusRecommendation {
  const focus = guidance.recommended_focus;
  const fallback = localizedFocusCopy(focus.focus_key, text);
  const primaryAction = guidanceActionToFocusAction(focus.primary_action);
  const secondaryActions = focus.secondary_actions.map(guidanceActionToFocusAction);
  return {
    tab: normalizeTab(focus.target_tab),
    title: fallback?.title ?? focus.title,
    reason: fallback?.reason ?? focus.reason,
    evidence: focus.evidence,
    secondaryTabs: secondaryActions.map((action) => action.targetTab),
    primaryAction,
    secondaryActions,
    riskLevel: focus.risk_level,
    confidence: focus.confidence,
    suggestedAgentPrompt: focus.suggested_agent_prompt,
    source: "api"
  };
}

function localizedFocusCopy(focusKey: string, text: LocaleMessages) {
  if (focusKey === "upload_data") return { title: text.focusUploadData, reason: text.focusUploadDataReason };
  if (focusKey === "understand_data") return { title: text.focusUnderstandData, reason: text.focusUnderstandDataReason };
  if (focusKey === "assumptions") return { title: text.focusAssumptions, reason: text.focusAssumptionsReason };
  if (focusKey === "evaluation") return { title: text.focusEvaluation, reason: text.focusEvaluationReason };
  if (focusKey === "approach") return { title: text.focusApproach, reason: text.focusApproachReason };
  if (focusKey === "experiments") return { title: text.focusExperiments, reason: text.focusExperimentsReason };
  if (focusKey === "reports") return { title: text.focusReports, reason: text.focusReportsReason };
  return null;
}

function isHighRiskAssumption(assumption: Assumption) {
  return ["high", "blocking", "deployment_blocking"].includes(assumption.risk_level);
}

function buildFocusRecommendation({
  text,
  project,
  datasets,
  understanding,
  assumptions,
  candidates,
  specs,
  runs,
  reports,
  jobs,
  artifacts
}: {
  text: LocaleMessages;
  project: Project;
  datasets: DatasetSnapshot[];
  understanding: string | null;
  assumptions: Assumption[];
  candidates: EvaluationCandidate[];
  specs: EvaluationSpec[];
  runs: Run[];
  reports: Report[];
  jobs: Job[];
  artifacts: Artifact[];
}): FocusRecommendation {
  const highRiskAssumptions = assumptions.filter(isHighRiskAssumption);
  const approvedSpecs = specs.filter((spec) => spec.status === "approved");
  const succeededJobs = jobs.filter((job) => job.status === "succeeded");

  if (!datasets.length) {
    return {
      tab: "Data",
      title: text.focusUploadData,
      reason: text.focusUploadDataReason,
      evidence: [`0 DatasetSnapshots`, `phase: ${formatWorkflowState(project.current_phase)}`],
      secondaryTabs: ["Understanding", "Approach"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "blocking",
      confidence: 0.8,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  if (!understanding) {
    return {
      tab: "Understanding",
      title: text.focusUnderstandData,
      reason: text.focusUnderstandDataReason,
      evidence: [`${datasets.length} DatasetSnapshots`, "understanding report missing"],
      secondaryTabs: ["Data", "Assumptions"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "high",
      confidence: 0.75,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  if (highRiskAssumptions.length) {
    return {
      tab: "Assumptions",
      title: text.focusAssumptions,
      reason: text.focusAssumptionsReason,
      evidence: [`${highRiskAssumptions.length} high-risk assumptions`, `${assumptions.length} total assumptions`],
      secondaryTabs: ["Understanding", "Evaluation"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "high",
      confidence: 0.75,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  if (!approvedSpecs.length) {
    return {
      tab: "Evaluation",
      title: text.focusEvaluation,
      reason: text.focusEvaluationReason,
      evidence: [`${candidates.length} candidates`, `${approvedSpecs.length} approved specs`],
      secondaryTabs: ["Assumptions", "Approach"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "high",
      confidence: 0.72,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  if (!runs.length) {
    return {
      tab: "Approach",
      title: text.focusApproach,
      reason: text.focusApproachReason,
      evidence: [`${approvedSpecs.length} approved specs`, `${succeededJobs.length} succeeded jobs`],
      secondaryTabs: ["Experiments", "Assets"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "medium",
      confidence: 0.7,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  if (!reports.length) {
    return {
      tab: "Experiments",
      title: text.focusExperiments,
      reason: text.focusExperimentsReason,
      evidence: [`${runs.length} experiment runs`, `${artifacts.length} artifacts`],
      secondaryTabs: ["Leaderboard", "Reports"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "medium",
      confidence: 0.68,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  return {
    tab: "Reports",
    title: text.focusReports,
    reason: text.focusReportsReason,
    evidence: [`${reports.length} reports`, `${runs.length} experiment runs`],
    secondaryTabs: ["Leaderboard", "Lineage"],
    primaryAction: null,
    secondaryActions: [],
    riskLevel: "low",
    confidence: 0.65,
    suggestedAgentPrompt: null,
    source: "local"
  };
}

function App() {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<Tab>("Overview");
  const [userSettings, setUserSettings] = React.useState<UserSettings>(() => loadUserSettings());
  const [dynamicLocalePacks, setDynamicLocalePacks] = React.useState<LocalePack[]>(() => loadDynamicLocalePacks());
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const localePacks = React.useMemo(() => mergeLocalePacks(dynamicLocalePacks), [dynamicLocalePacks]);
  const activeLocale = resolveLocalePack(userSettings.locale, localePacks);
  const text = copyForLocale(activeLocale.locale, localePacks);

  React.useEffect(() => {
    window.localStorage.setItem(userSettingsStorageKey, JSON.stringify(userSettings));
    window.localStorage.setItem(dynamicLocaleStorageKey, JSON.stringify(dynamicLocalePacks));
    document.documentElement.lang = activeLocale.locale;
    document.documentElement.dir = activeLocale.direction;
    document.documentElement.dataset.theme = userSettings.displayTheme;
  }, [activeLocale.direction, activeLocale.locale, dynamicLocalePacks, userSettings]);

  const refreshProjects = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api<Project[]>("/api/projects");
      setProjects(data);
      if (!selectedProjectId && data[0]) {
        setSelectedProjectId(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId]);

  React.useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;

  async function createLocalizationTask(settings: UserSettings) {
    if (!selectedProjectId) {
      throw new Error(text.noProjectForLocalization);
    }
    const targetLocale = resolveLocalePack(settings.locale, localePacks);
    const extraRequest = settings.dynamicLanguageRequest.trim();
    await api<Job>(`/api/projects/${selectedProjectId}/approach/agent-task-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_type: "generate_locale_pack",
        objective: [
          `Design a Tablex UI locale pack for ${targetLocale.locale} (${targetLocale.label}).`,
          "Preserve PRODUCT_NAME neutrality, harness-owned safety controls, and existing AgentTask terminology.",
          `Use ${targetLocale.fallbackLocale} as fallback and keep missing keys safe to render.`,
          "Return translation keys, copy guidance, locale metadata, fallback behavior, and implementation notes as artifacts.",
          extraRequest ? `Additional user request: ${extraRequest}` : null
        ]
          .filter(Boolean)
          .join(" ")
      })
    });
    setError(null);
    await refreshProjects();
  }

  function ensureDynamicLocale(localeInput: string) {
    const nextPack = createDynamicLocalePack(localeInput);
    setDynamicLocalePacks((current) => {
      if (localePacks.some((pack) => pack.locale === nextPack.locale)) return current;
      return [...current, nextPack];
    });
    setUserSettings((current) => ({
      ...current,
      locale: nextPack.locale,
      requestedLocale: nextPack.locale
    }));
  }

  return (
    <LocaleContext.Provider value={{ text, locale: activeLocale.locale }}>
      <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">T</div>
          <div>
            <div className="brand-name">Tablex</div>
            <div className="brand-subtitle">{text.predictionWorkbench}</div>
          </div>
        </div>
        <div className="nav-label">{text.projects}</div>
        <div className="project-list">
          {projects.map((project) => (
            <button
              key={project.id}
              className={project.id === selectedProjectId ? "project-item active" : "project-item"}
              onClick={() => {
                setSelectedProjectId(project.id);
                setTab("Overview");
              }}
            >
              <span>{project.name}</span>
              <small>{formatWorkflowState(project.current_phase)}</small>
            </button>
          ))}
        </div>
        <CreateProjectForm text={text} onCreated={refreshProjects} />
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <h1>{selectedProject ? selectedProject.name : text.projects}</h1>
            <p>{selectedProject?.description || text.projectDescription}</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => void refreshProjects()} title={text.refreshProjects}>
              <RefreshCw size={18} />
            </button>
            <button className="icon-button" onClick={() => setSettingsOpen(true)} title={text.settings}>
              <SettingsIcon size={18} />
            </button>
          </div>
        </header>
        {settingsOpen ? (
          <UserSettingsPanel
            settings={userSettings}
            text={text}
            activeLocale={activeLocale}
            localePacks={localePacks}
            onChange={setUserSettings}
            onEnsureDynamicLocale={ensureDynamicLocale}
            onClose={() => setSettingsOpen(false)}
            onCreateLocalizationTask={createLocalizationTask}
          />
        ) : null}
        {error ? <div className="banner danger">{error}</div> : null}
        {loading ? <LoadingBlock label={text.loadingProjects} /> : null}
        {!loading && !selectedProject ? (
          <EmptyState
            icon={<Database size={28} />}
            title={text.createFirstProject}
            body={text.createFirstProjectBody}
          />
        ) : null}
        {selectedProject ? (
          <>
            <nav className="tabs">
              {tabItems.map((item) => (
                <button
                  key={item.id}
                  className={item.id === tab ? "tab active" : "tab"}
                  onClick={() => setTab(item.id)}
                >
                  {text[item.labelKey]}
                </button>
              ))}
            </nav>
            <ProjectDetail
              project={selectedProject}
              tab={tab}
              text={text}
              onTabChange={setTab}
              onProjectChanged={refreshProjects}
            />
          </>
        ) : null}
      </main>
      </div>
    </LocaleContext.Provider>
  );
}

function UserSettingsPanel({
  settings,
  text,
  activeLocale,
  localePacks,
  onChange,
  onEnsureDynamicLocale,
  onClose,
  onCreateLocalizationTask
}: {
  settings: UserSettings;
  text: LocaleMessages;
  activeLocale: LocalePack;
  localePacks: LocalePack[];
  onChange: (settings: UserSettings) => void;
  onEnsureDynamicLocale: (localeInput: string) => void;
  onClose: () => void;
  onCreateLocalizationTask: (settings: UserSettings) => Promise<void>;
}) {
  const [busy, setBusy] = React.useState(false);
  const [status, setStatus] = React.useState<string | null>(null);

  function update(patch: Partial<UserSettings>) {
    setStatus(null);
    onChange({ ...settings, ...patch });
  }

  function addDynamicLocale() {
    const localeInput = settings.requestedLocale.trim();
    if (!localeInput) return;
    onEnsureDynamicLocale(localeInput);
    setStatus(`${text.activeLocale}: ${localeLabel(localeInput)}`);
  }

  async function createTask() {
    setBusy(true);
    setStatus(null);
    try {
      await onCreateLocalizationTask(settings);
      setStatus(text.localizationTaskCreated);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="settings-panel" aria-label={text.settings}>
      <div className="settings-panel-header">
        <div>
          <h2>{text.settings}</h2>
          <p>{text.settingsHint}</p>
        </div>
        <button className="icon-button" onClick={onClose} title={text.close}>
          <Check size={16} />
        </button>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.localeCatalog}</span>
          <strong>{activeLocale.source === "built_in" ? text.localePack : text.dynamic}</strong>
        </div>
        <label>
          <span>{text.language}</span>
          <select value={settings.locale} onChange={(event) => update({ locale: event.target.value })}>
            {localePacks.map((pack) => (
              <option key={pack.locale} value={pack.locale}>
                {pack.nativeLabel} ({pack.locale})
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{text.requestedLocale}</span>
          <input
            value={settings.requestedLocale}
            onChange={(event) => update({ requestedLocale: event.target.value })}
            placeholder={text.requestedLocalePlaceholder}
          />
        </label>
        <button className="secondary-button" disabled={!settings.requestedLocale.trim()} onClick={addDynamicLocale}>
          {text.addDynamicLocale}
        </button>
        <p className="settings-hint">{text.localeFallbackHint}</p>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.appearance}</span>
          <strong>{settings.displayTheme === "dark" ? text.darkTheme : text.lightTheme}</strong>
        </div>
        <div className="segmented-control" role="group" aria-label={text.appearance}>
          <button
            className={settings.displayTheme === "light" ? "active" : ""}
            onClick={() => update({ displayTheme: "light" })}
            type="button"
          >
            <Sun size={15} />
            {text.lightTheme}
          </button>
          <button
            className={settings.displayTheme === "dark" ? "active" : ""}
            onClick={() => update({ displayTheme: "dark" })}
            type="button"
          >
            <Moon size={15} />
            {text.darkTheme}
          </button>
        </div>
      </div>

      <div className="settings-section">
        <label>
          <span>{text.dynamicLanguageRequest}</span>
          <textarea
            value={settings.dynamicLanguageRequest}
            onChange={(event) => update({ dynamicLanguageRequest: event.target.value })}
            placeholder={text.localizationRequestPlaceholder}
            rows={4}
          />
        </label>
        <p className="settings-hint">{text.localizationTaskHint}</p>
        <button className="primary-button" disabled={busy} onClick={() => void createTask()}>
          {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
          {text.createLocalizationTask}
        </button>
        {status ? <div className="settings-status">{status}</div> : null}
      </div>
    </aside>
  );
}

function CreateProjectForm({ text, onCreated }: { text: LocaleMessages; onCreated: () => Promise<void> }) {
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    await api<Project>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() })
    });
    setName("");
    setBusy(false);
    await onCreated();
  }

  return (
    <form className="create-form" onSubmit={(event) => void submit(event)}>
      <input value={name} onChange={(event) => setName(event.target.value)} placeholder={text.newProjectName} />
      <button className="primary-button" disabled={busy || !name.trim()}>
        {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
        {text.create}
      </button>
    </form>
  );
}

function ProjectDetail({
  project,
  tab,
  text,
  onTabChange,
  onProjectChanged
}: {
  project: Project;
  tab: Tab;
  text: LocaleMessages;
  onTabChange: (tab: Tab) => void;
  onProjectChanged: () => Promise<void>;
}) {
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [guidance, setGuidance] = React.useState<ProjectGuidance | null>(null);
  const [datasets, setDatasets] = React.useState<DatasetSnapshot[]>([]);
  const [questions, setQuestions] = React.useState<Question[]>([]);
  const [assumptions, setAssumptions] = React.useState<Assumption[]>([]);
  const [assumptionReviewQueue, setAssumptionReviewQueue] = React.useState<AssumptionReviewQueue | null>(null);
  const [candidates, setCandidates] = React.useState<EvaluationCandidate[]>([]);
  const [specs, setSpecs] = React.useState<EvaluationSpec[]>([]);
  const [artifacts, setArtifacts] = React.useState<Artifact[]>([]);
  const [benchmarks, setBenchmarks] = React.useState<BenchmarkDataset[]>([]);
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [leaderboard, setLeaderboard] = React.useState<LeaderboardEntry[]>([]);
  const [modelVersions, setModelVersions] = React.useState<ModelVersion[]>([]);
  const [validationsByModelVersion, setValidationsByModelVersion] = React.useState<Record<string, ModelValidation[]>>({});
  const [strategyBrief, setStrategyBrief] = React.useState<AdaptiveStrategyBrief | null>(null);
  const [researchBriefs, setResearchBriefs] = React.useState<ResearchBrief[]>([]);
  const [ideas, setIdeas] = React.useState<Idea[]>([]);
  const [reports, setReports] = React.useState<Report[]>([]);
  const [visualizations, setVisualizations] = React.useState<VisualizationSpec[]>([]);
  const [agentTaskResults, setAgentTaskResults] = React.useState<AgentTaskResult[]>([]);
  const [insights, setInsights] = React.useState<Insight[]>([]);
  const [libraryAssets, setLibraryAssets] = React.useState<LibraryAsset[]>([]);
  const [projectAssetReferences, setProjectAssetReferences] = React.useState<AssetReference[]>([]);
  const [lineage, setLineage] = React.useState<LineageEdge[]>([]);
  const [understanding, setUnderstanding] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [agentChatMessages, setAgentChatMessages] = React.useState<Array<{ role: "user" | "system"; text: string }>>([]);
  const focusRecommendation = React.useMemo(
    () => {
      if (guidance) return focusFromGuidance(guidance, text);
      return buildFocusRecommendation({
        text,
        project,
        datasets,
        understanding,
        assumptions,
        candidates,
        specs,
        runs,
        reports,
        jobs,
        artifacts
      });
    },
    [guidance, text, project, datasets, understanding, assumptions, candidates, specs, runs, reports, jobs, artifacts]
  );

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const [
        overviewData,
        guidanceData,
        datasetsData,
        questionsData,
        assumptionsData,
        assumptionReviewQueueData,
        candidatesData,
        specsData,
        artifactsData,
        benchmarksData,
        jobsData,
        runsData,
        leaderboardData,
        modelVersionsData,
        strategyBriefData,
        researchBriefsData,
        ideasData,
        reportsData,
        visualizationsData,
        agentTaskResultsData,
        insightsData,
        libraryAssetsData,
        projectAssetReferencesData,
        lineageData,
        understandingData
      ] = await Promise.all([
        api<Overview>(`/api/projects/${project.id}/overview`),
        api<ProjectGuidance>(`/api/projects/${project.id}/guidance`).catch(() => null),
        api<DatasetSnapshot[]>(`/api/projects/${project.id}/datasets`),
        api<Question[]>(`/api/projects/${project.id}/questions`),
        api<Assumption[]>(`/api/projects/${project.id}/assumptions`),
        api<AssumptionReviewQueue>(`/api/projects/${project.id}/assumptions/review-queue`).catch(() => null),
        api<EvaluationCandidate[]>(`/api/projects/${project.id}/evaluation/candidates`),
        api<EvaluationSpec[]>(`/api/projects/${project.id}/evaluation/specs`),
        api<Artifact[]>(`/api/projects/${project.id}/artifacts`),
        api<BenchmarkDataset[]>(`/api/benchmarks`),
        api<Job[]>(`/api/projects/${project.id}/jobs`),
        api<Run[]>(`/api/projects/${project.id}/runs`),
        api<LeaderboardEntry[]>(`/api/projects/${project.id}/leaderboard`),
        api<ModelVersion[]>(`/api/projects/${project.id}/model-versions`),
        api<AdaptiveStrategyBrief>(`/api/projects/${project.id}/approach/strategy-brief`).catch(() => null),
        api<ResearchBrief[]>(`/api/projects/${project.id}/approach/research-briefs`),
        api<Idea[]>(`/api/projects/${project.id}/approach/ideas`),
        api<Report[]>(`/api/projects/${project.id}/reports`),
        api<VisualizationSpec[]>(`/api/projects/${project.id}/visualizations`),
        api<AgentTaskResult[]>(`/api/projects/${project.id}/agent-task-results`),
        api<Insight[]>(`/api/projects/${project.id}/insights`),
        api<LibraryAsset[]>(`/api/assets`),
        api<AssetReference[]>(`/api/projects/${project.id}/asset-references`),
        api<LineageEdge[]>(`/api/projects/${project.id}/lineage`),
        api<{ markdown: string | null }>(`/api/projects/${project.id}/understanding/latest`)
      ]);
      setOverview(overviewData);
      setGuidance(guidanceData);
      setDatasets(datasetsData);
      setQuestions(questionsData);
      setAssumptions(assumptionsData);
      setAssumptionReviewQueue(assumptionReviewQueueData);
      setCandidates(candidatesData);
      setSpecs(specsData);
      setArtifacts(artifactsData);
      setBenchmarks(benchmarksData);
      setJobs(jobsData);
      setRuns(runsData);
      setLeaderboard(leaderboardData);
      setModelVersions(modelVersionsData);
      setStrategyBrief(strategyBriefData);
      setResearchBriefs(researchBriefsData);
      setIdeas(ideasData);
      setReports(reportsData);
      setVisualizations(visualizationsData);
      setAgentTaskResults(agentTaskResultsData);
      setInsights(insightsData);
      setLibraryAssets(libraryAssetsData);
      setProjectAssetReferences(projectAssetReferencesData);
      const validationEntries = await Promise.all(
        modelVersionsData.map(async (modelVersion) => {
          const validations = await api<ModelValidation[]>(`/api/model-versions/${modelVersion.id}/validations`);
          return [modelVersion.id, validations] as const;
        })
      );
      setValidationsByModelVersion(Object.fromEntries(validationEntries));
      setLineage(lineageData);
      setUnderstanding(understandingData.markdown);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project.id]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitAgentChat(objective: string) {
    const trimmed = objective.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    setAgentChatMessages((current) => [...current.slice(-3), { role: "user", text: trimmed }]);
    try {
      const job = await api<Job>(`/api/projects/${project.id}/approach/agent-task-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective: trimmed, task_type: "implement_prediction_approach" })
      });
      const artifactId = job.output.agent_task_contract_artifact_id ?? job.output.artifact_id;
      setAgentChatMessages((current) => [
        ...current.slice(-4),
        {
          role: "system",
          text:
            typeof artifactId === "string"
              ? `${text.agentTaskContractCreated} ${artifactId}`
              : text.agentTaskContractCreated
        }
      ]);
      await refresh();
      await onProjectChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setAgentChatMessages((current) => [...current.slice(-4), { role: "system", text: message }]);
    } finally {
      setBusy(false);
    }
  }

  async function runFocusAction(action: FocusAction | null) {
    if (!action || action.disabled) {
      if (action?.disabledReason) setError(action.disabledReason);
      return;
    }
    if (action.actionType === "navigate") {
      onTabChange(action.targetTab);
      return;
    }
    if (action.actionType === "agent_task_prompt") {
      await submitAgentChat(action.prompt ?? action.label);
      onTabChange(action.targetTab);
      return;
    }
    if (action.actionType === "run_endpoint" && action.endpoint) {
      await runAction(() =>
        api(action.endpoint as string, {
          method: action.method ?? "POST",
          headers: action.requestBody ? { "Content-Type": "application/json" } : undefined,
          body: action.requestBody ? JSON.stringify(action.requestBody) : undefined
        })
      );
      onTabChange(action.targetTab);
      return;
    }
    onTabChange(action.targetTab);
  }

  async function runStrategyAction(action: StrategyAction) {
    const targetTab = tabFromString(action.target_tab, "Approach");
    if (action.action_type === "navigate") {
      onTabChange(targetTab);
      return;
    }
    if (action.action_type === "agent_task") {
      await submitAgentChat(action.prompt ?? action.reason ?? action.label);
      onTabChange(targetTab);
      return;
    }
    if (action.action_type === "api" && action.endpoint) {
      await runAction(() => api(action.endpoint as string, { method: action.method ?? "POST" }));
      onTabChange(targetTab);
      return;
    }
    onTabChange(targetTab);
  }

  return (
    <section className="detail">
      {error ? <div className="banner danger">{error}</div> : null}
      <FocusGuide
        recommendation={focusRecommendation}
        currentTab={tab}
        text={text}
        onTabChange={onTabChange}
        onAction={(action) => void runFocusAction(action)}
      />
      <AgentChatDock
        busy={busy}
        text={text}
        messages={agentChatMessages}
        latestContract={artifacts.find((artifact) => artifact.asset_type === "agent_task_contract") ?? null}
        onSubmit={submitAgentChat}
      />
      {tab === "Overview" && (
        <OverviewTab
          overview={overview}
          assumptions={assumptions}
          jobs={jobs}
          artifacts={artifacts}
          text={text}
          focusRecommendation={focusRecommendation}
          onTabChange={onTabChange}
        />
      )}
      {tab === "Data" && (
        <DataTab
          project={project}
          datasets={datasets}
          artifacts={artifacts}
          benchmarks={benchmarks}
          jobs={jobs}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Understanding" && (
        <UnderstandingTab
          understanding={understanding}
          questions={questions}
          busy={busy}
          runAction={() => runAction(() => api(`/api/projects/${project.id}/understanding/run`, { method: "POST" }))}
          answerQuestion={(questionId, answerValue, answerText) =>
            runAction(() =>
              api(`/api/questions/${questionId}/answer`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ answer_value: answerValue, answer_text: answerText || null })
              })
            )
          }
        />
      )}
      {tab === "Assumptions" && (
        <AssumptionsTab
          assumptions={assumptions}
          reviewQueue={assumptionReviewQueue}
          questions={questions}
          busy={busy}
          applyFallbacks={() => runAction(() => api(`/api/projects/${project.id}/assumptions/infer`, { method: "POST" }))}
          runAction={runAction}
        />
      )}
      {tab === "Evaluation" && (
        <EvaluationTab
          project={project}
          candidates={candidates}
          specs={specs}
          artifacts={artifacts}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Approach" && (
        <ApproachTab
          project={project}
          strategyBrief={strategyBrief}
          researchBriefs={researchBriefs}
          ideas={ideas}
          artifacts={artifacts}
          busy={busy}
          text={text}
          runAction={runAction}
          onStrategyAction={(action) => void runStrategyAction(action)}
        />
      )}
      {tab === "Experiments" && (
        <ExperimentsTab
          project={project}
          jobs={jobs}
          runs={runs}
          agentTaskResults={agentTaskResults}
          artifacts={artifacts}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Leaderboard" && (
        <LeaderboardTab
          specs={specs}
          artifacts={artifacts}
          leaderboard={leaderboard}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Reports" && (
        <ReportsTab
          project={project}
          reports={reports}
          artifacts={artifacts}
          visualizations={visualizations}
          insights={insights}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Assets" && (
        <AssetsTab
          artifacts={artifacts}
          modelVersions={modelVersions}
          validationsByModelVersion={validationsByModelVersion}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Library" && (
        <LibraryTab
          project={project}
          assets={libraryAssets}
          references={projectAssetReferences}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Jobs" && <JobsTab jobs={jobs} busy={busy} runAction={runAction} />}
      {tab === "Lineage" && <LineageTab lineage={lineage} />}
    </section>
  );
}

function FocusGuide({
  recommendation,
  currentTab,
  text,
  onTabChange,
  onAction
}: {
  recommendation: FocusRecommendation;
  currentTab: Tab;
  text: LocaleMessages;
  onTabChange: (tab: Tab) => void;
  onAction: (action: FocusAction | null) => void;
}) {
  const isCurrent = currentTab === recommendation.tab;
  const primaryAction =
    recommendation.primaryAction ??
    ({
      id: "navigate_recommended_focus",
      label: isCurrent ? text.recommendedFocus : `${text.goToFocus}: ${tabLabel(recommendation.tab, text)}`,
      targetTab: recommendation.tab,
      actionType: "navigate",
      method: null,
      endpoint: null,
      requestBody: null,
      prompt: null,
      disabled: isCurrent,
      disabledReason: null
    } satisfies FocusAction);
  const secondaryActions = recommendation.secondaryActions.length
    ? recommendation.secondaryActions
    : recommendation.secondaryTabs.map(
        (tab) =>
          ({
            id: `navigate_${tab}`,
            label: tabLabel(tab, text),
            targetTab: tab,
            actionType: "navigate",
            method: null,
            endpoint: null,
            requestBody: null,
            prompt: null,
            disabled: false,
            disabledReason: null
          }) satisfies FocusAction
      );
  const primaryDisabled = primaryAction.disabled || (primaryAction.actionType === "navigate" && isCurrent);

  return (
    <section className="focus-guide" aria-label={text.focusGuideTitle}>
      <div className="focus-guide-copy">
        <div className="focus-guide-eyebrow">
          <Lightbulb size={16} />
          {text.focusGuideTitle}
        </div>
        <h2>{recommendation.title}</h2>
        <p>{recommendation.reason}</p>
        <div className="focus-evidence" aria-label={text.focusEvidence}>
          <span>{text.focusEvidence}</span>
          {recommendation.evidence.slice(0, 3).map((item) => (
            <strong key={item}>{item}</strong>
          ))}
        </div>
      </div>
      <div className="focus-guide-actions">
        <button
          className="primary-button"
          disabled={primaryDisabled}
          onClick={() => onAction(primaryAction)}
          type="button"
        >
          {primaryAction.actionType === "navigate" ? <Search size={16} /> : <Play size={16} />}
          {primaryAction.label}
        </button>
        <div className="focus-secondary">
          <span>{text.otherUsefulViews}</span>
          <div>
            {secondaryActions.map((action) => (
              <button
                className="secondary-button"
                disabled={action.disabled}
                key={action.id}
                onClick={() => (action.actionType === "navigate" ? onTabChange(action.targetTab) : onAction(action))}
                type="button"
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentChatDock({
  busy,
  text,
  messages,
  latestContract,
  onSubmit
}: {
  busy: boolean;
  text: LocaleMessages;
  messages: Array<{ role: "user" | "system"; text: string }>;
  latestContract: Artifact | null;
  onSubmit: (objective: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const objective = draft.trim();
    if (!objective) return;
    setDraft("");
    await onSubmit(objective);
  }

  return (
    <div className="agent-chat-dock">
      <div className="agent-chat-header">
        <div>
          <div className="agent-chat-title">
            <MessageSquare size={16} />
            {text.agentChatTitle}
          </div>
          <small>{text.agentChatSubtitle}</small>
        </div>
        {latestContract ? (
          <a
            className="icon-link"
            href={`${apiBase}/api/artifacts/${latestContract.id}/download`}
            title={text.downloadLatestAgentTaskContract}
          >
            <Download size={16} />
          </a>
        ) : null}
      </div>
      {messages.length ? (
        <div className="agent-chat-log">
          {messages.slice(-4).map((message, index) => (
            <div className={`agent-chat-message ${message.role}`} key={`${message.role}-${index}-${message.text}`}>
              {message.text}
            </div>
          ))}
        </div>
      ) : null}
      <form className="agent-chat-form" onSubmit={(event) => void submit(event)}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={text.agentChatPlaceholder}
          rows={4}
        />
        <button className="primary-button icon-only" disabled={busy || !draft.trim()} title={text.createAgentTaskContract}>
          {busy ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
        </button>
      </form>
    </div>
  );
}

function TranslatablePreview({
  preview,
  sourceType = "artifact",
  sourceId
}: {
  preview: ArtifactPreview;
  sourceType?: "artifact" | "report";
  sourceId?: string;
}) {
  const { text, locale } = useLocale();
  const [translation, setTranslation] = React.useState<TranslationResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const effectiveSourceId = sourceId ?? preview.id;
  const isSourceLocale = locale.toLowerCase().startsWith("en");
  const shownPreview = translation?.preview.preview_available ? translation.preview.preview : preview.preview;

  async function translate() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<TranslationResult>(
        sourceType === "report"
          ? `/api/reports/${effectiveSourceId}/translate`
          : `/api/artifacts/${effectiveSourceId}/translate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_locale: "en-US", target_locale: locale })
        }
      );
      setTranslation(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="preview-block">
      <div className="preview-toolbar">
        <div className="preview-meta">
          <span className="badge">{translation ? text.translatedDraft : text.originalSource}</span>
          <span className="badge muted">{translation?.target_locale ?? "en-US"}</span>
          {translation ? <span className="badge muted">{translation.provider_status}</span> : null}
        </div>
        <button
          className="secondary-button"
          disabled={busy || isSourceLocale || !preview.preview_available}
          onClick={() => void translate()}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
          {busy ? text.translating : text.translate}
        </button>
      </div>
      {translation ? <p className="translation-note">{text.codexTranslationPending}</p> : null}
      {error ? <div className="banner danger">{error}</div> : null}
      <pre className="markdown-preview">{shownPreview}</pre>
    </div>
  );
}

function OverviewTab({
  overview,
  assumptions,
  jobs,
  artifacts,
  text,
  focusRecommendation,
  onTabChange
}: {
  overview: Overview | null;
  assumptions: Assumption[];
  jobs: Job[];
  artifacts: Artifact[];
  text: LocaleMessages;
  focusRecommendation: FocusRecommendation;
  onTabChange: (tab: Tab) => void;
}) {
  if (!overview) return <LoadingBlock label="Loading overview" />;
  const highRiskAssumptions = assumptions.filter(isHighRiskAssumption);
  const recentJobs = jobs.slice(0, 5);
  const recentArtifacts = artifacts.slice(0, 8);

  return (
    <div className="stack">
      <Panel title={text.atAGlance} icon={<BarChart3 size={18} />}>
        <div className="metric-grid compact">
          <Metric label="Phase" value={formatWorkflowState(overview.project.current_phase)} />
          <Metric label="Datasets" value={overview.counts.datasets ?? 0} />
          <Metric label="Assumptions" value={overview.counts.assumptions ?? 0} />
          <Metric label="Runs" value={overview.counts.experiment_runs ?? 0} />
        </div>
      </Panel>
      <Panel title="Next Actions" icon={<ListChecks size={18} />}>
        <ul className="clean-list">
          <li>
            <button className="inline-action" onClick={() => onTabChange(focusRecommendation.tab)} type="button">
              {text.recommendedFocus}: {focusRecommendation.title}
            </button>
          </li>
          {overview.next_actions.slice(0, 3).map((action) => (
            <li key={action}>{action}</li>
          ))}
        </ul>
      </Panel>
      <details className="supporting-details">
        <summary>
          <span>{text.viewDetails}</span>
          <small>
            {highRiskAssumptions.length} risks / {recentJobs.length} jobs / {recentArtifacts.length} artifacts
          </small>
        </summary>
        <div className="supporting-details-body">
          <Panel title="High Risk Assumptions" icon={<AlertTriangle size={18} />}>
            {highRiskAssumptions.length ? (
              <Table
                headers={["Statement", "Risk", "Policy", "Status"]}
                rows={highRiskAssumptions.map((item) => [
                  item.statement,
                  item.risk_level,
                  item.fallback_policy,
                  item.status
                ])}
              />
            ) : (
              <EmptyInline text="High-risk assumptions will appear here after dataset understanding runs." />
            )}
          </Panel>
          <Panel title="Recent Activity" icon={<Play size={18} />}>
            {recentJobs.length ? (
              <Table headers={["Job", "Status"]} rows={recentJobs.map((job) => [job.job_type, job.status])} />
            ) : (
              <EmptyInline text="Jobs from profiling, evaluation design, split generation, and agent tasks will appear here." />
            )}
          </Panel>
          <Panel title="Recent Artifacts" icon={<FileText size={18} />}>
            {recentArtifacts.length ? (
              <Table
                headers={["Type", "Name", "Version"]}
                rows={recentArtifacts.map((artifact) => [artifact.asset_type, artifact.name, `v${artifact.version}`])}
              />
            ) : (
              <EmptyInline text="Dataset snapshots, profiles, reports, evaluation specs, and split manifests will be registered here." />
            )}
          </Panel>
        </div>
      </details>
    </div>
  );
}

function DataTab({
  project,
  datasets,
  artifacts,
  benchmarks,
  jobs,
  busy,
  runAction
}: {
  project: Project;
  datasets: DatasetSnapshot[];
  artifacts: Artifact[];
  benchmarks: BenchmarkDataset[];
  jobs: Job[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [target, setTarget] = React.useState(project.target_column ?? "");
  const [benchmarkPaths, setBenchmarkPaths] = React.useState<Record<string, string>>({});
  const [qualityPreview, setQualityPreview] = React.useState<ArtifactPreview | null>(null);
  const [qualityPreviewError, setQualityPreviewError] = React.useState<string | null>(null);
  const [qualityPreviewLoadingId, setQualityPreviewLoadingId] = React.useState<string | null>(null);
  const [relationalPreview, setRelationalPreview] = React.useState<ArtifactPreview | null>(null);
  const [relationalPreviewError, setRelationalPreviewError] = React.useState<string | null>(null);
  const [relationalPreviewLoadingId, setRelationalPreviewLoadingId] = React.useState<string | null>(null);
  const [scenarioPreview, setScenarioPreview] = React.useState<ArtifactPreview | null>(null);
  const [scenarioPreviewError, setScenarioPreviewError] = React.useState<string | null>(null);
  const [scenarioPreviewLoadingId, setScenarioPreviewLoadingId] = React.useState<string | null>(null);
  const [workflowPreview, setWorkflowPreview] = React.useState<ArtifactPreview | null>(null);
  const [workflowPreviewError, setWorkflowPreviewError] = React.useState<string | null>(null);
  const [workflowPreviewLoadingId, setWorkflowPreviewLoadingId] = React.useState<string | null>(null);
  const [evidencePreview, setEvidencePreview] = React.useState<ArtifactPreview | null>(null);
  const [evidencePreviewError, setEvidencePreviewError] = React.useState<string | null>(null);
  const [evidencePreviewLoadingId, setEvidencePreviewLoadingId] = React.useState<string | null>(null);
  const [collectionPreview, setCollectionPreview] = React.useState<ArtifactPreview | null>(null);
  const [collectionPreviewError, setCollectionPreviewError] = React.useState<string | null>(null);
  const [collectionPreviewLoadingId, setCollectionPreviewLoadingId] = React.useState<string | null>(null);
  const [kaggleProbeResults, setKaggleProbeResults] = React.useState<Record<string, Record<string, unknown>>>({});
  const [kaggleInventoryResults, setKaggleInventoryResults] = React.useState<Record<string, Record<string, unknown>>>({});
  const [kaggleDownloadResults, setKaggleDownloadResults] = React.useState<Record<string, Record<string, unknown>>>({});

  async function uploadDataset() {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    if (target.trim()) body.append("target_column", target.trim());
    await runAction(() =>
      api(`/api/projects/${project.id}/datasets/upload`, {
        method: "POST",
        body
      })
    );
    setFile(null);
  }

  async function importBenchmark(benchmark: BenchmarkDataset) {
    const configuredPath = benchmarkPaths[benchmark.id] ?? benchmark.default_local_path;
    const benchmarkTarget = textField(benchmark.primary_table.target_column);
    const effectiveTarget = benchmarkTarget ?? (target.trim() || undefined);
    await runAction(() =>
      api(`/api/projects/${project.id}/benchmarks/${benchmark.id}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          local_path: configuredPath.trim() || undefined,
          target_column: effectiveTarget
        })
      })
    );
  }

  async function generateBenchmarkFixture(benchmark: BenchmarkDataset) {
    await runAction(() =>
      api(`/api/benchmarks/${benchmark.id}/fixtures/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overwrite: false })
      })
    );
  }

  async function downloadPublicBenchmark(benchmark: BenchmarkDataset) {
    await runAction(() =>
      api(`/api/benchmarks/${benchmark.id}/public-download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overwrite: false })
      })
    );
  }

  async function probeKaggleBenchmark(benchmark: BenchmarkDataset) {
    await runAction(async () => {
      const job = await api<Job>(`/api/benchmarks/${benchmark.id}/kaggle/probe`, {
        method: "POST"
      });
      setKaggleProbeResults((current) => ({ ...current, [benchmark.id]: job.output }));
      return job;
    });
  }

  async function fetchKaggleInventory(benchmark: BenchmarkDataset) {
    await runAction(async () => {
      const job = await api<Job>(`/api/benchmarks/${benchmark.id}/kaggle/inventory`, {
        method: "POST"
      });
      setKaggleInventoryResults((current) => ({ ...current, [benchmark.id]: job.output }));
      return job;
    });
  }

  async function downloadKaggleRequiredFiles(benchmark: BenchmarkDataset) {
    await runAction(async () => {
      const job = await api<Job>(`/api/benchmarks/${benchmark.id}/kaggle/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          include_required: true,
          include_recommended: false,
          include_holdout: false,
          overwrite: false,
          max_total_bytes: 500 * 1024 * 1024
        })
      });
      setKaggleDownloadResults((current) => ({ ...current, [benchmark.id]: job.output }));
      return job;
    });
  }

  async function runBenchmarkFixtureSmoke(benchmark: BenchmarkDataset) {
    await runAction(() =>
      api(`/api/projects/${project.id}/benchmarks/${benchmark.id}/fixture-smoke`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overwrite: false })
      })
    );
  }

  async function runPublicBenchmarkWorkflow(benchmark: BenchmarkDataset) {
    await runAction(() =>
      api(`/api/projects/${project.id}/benchmarks/${benchmark.id}/public-workflow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overwrite: false })
      })
    );
  }

  async function createBenchmarkScenarioPack(benchmark: BenchmarkDataset) {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/benchmarks/${benchmark.id}/scenario-pack`, {
        method: "POST"
      });
      const reportArtifactId = job.output.benchmark_scenario_report_artifact_id;
      if (typeof reportArtifactId === "string") {
        await loadScenarioPreview(reportArtifactId);
      }
      return job;
    });
  }

  async function createBenchmarkEvidencePack() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/benchmarks/evidence-pack`, {
        method: "POST"
      });
      const reportArtifactId = textField(job.output.benchmark_evidence_report_artifact_id);
      if (reportArtifactId) {
        await loadEvidencePreview(reportArtifactId);
      }
      return job;
    });
  }

  async function createRelationalFeaturePlan() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-plan`, {
        method: "POST"
      });
      const reportArtifactId = textField(job.output.relational_feature_report_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      }
      return job;
    });
  }

  async function createRelationalFeatureRecipe() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-recipe/build`, {
        method: "POST"
      });
      const reportArtifactId = textField(job.output.relational_feature_recipe_report_artifact_id);
      const previewArtifactId = textField(job.output.relational_feature_preview_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      } else if (previewArtifactId) {
        await loadRelationalPreview(previewArtifactId);
      }
      return job;
    });
  }

  async function diagnoseRelationalFeatureScenarios() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-scenarios/diagnose`, {
        method: "POST"
      });
      const reportArtifactId = textField(job.output.relational_feature_scenario_report_artifact_id);
      const diagnosticsArtifactId = textField(job.output.relational_feature_scenario_diagnostics_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      } else if (diagnosticsArtifactId) {
        await loadRelationalPreview(diagnosticsArtifactId);
      }
      return job;
    });
  }

  async function createBenchmarkCollectionPlan() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/benchmarks/collection-plan`, {
        method: "POST"
      });
      const reportArtifactId = textField(job.output.benchmark_collection_report_artifact_id);
      if (reportArtifactId) {
        await loadCollectionPreview(reportArtifactId);
      }
      return job;
    });
  }

  async function loadQualityPreview(artifactId: string) {
    setQualityPreviewLoadingId(artifactId);
    setQualityPreviewError(null);
    try {
      setQualityPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setQualityPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setQualityPreviewLoadingId(null);
    }
  }

  async function loadRelationalPreview(artifactId: string) {
    setRelationalPreviewLoadingId(artifactId);
    setRelationalPreviewError(null);
    try {
      setRelationalPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setRelationalPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setRelationalPreviewLoadingId(null);
    }
  }

  async function loadScenarioPreview(artifactId: string) {
    setScenarioPreviewLoadingId(artifactId);
    setScenarioPreviewError(null);
    try {
      setScenarioPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setScenarioPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setScenarioPreviewLoadingId(null);
    }
  }

  async function loadWorkflowPreview(artifactId: string) {
    setWorkflowPreviewLoadingId(artifactId);
    setWorkflowPreviewError(null);
    try {
      setWorkflowPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setWorkflowPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorkflowPreviewLoadingId(null);
    }
  }

  async function loadEvidencePreview(artifactId: string) {
    setEvidencePreviewLoadingId(artifactId);
    setEvidencePreviewError(null);
    try {
      setEvidencePreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setEvidencePreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setEvidencePreviewLoadingId(null);
    }
  }

  async function loadCollectionPreview(artifactId: string) {
    setCollectionPreviewLoadingId(artifactId);
    setCollectionPreviewError(null);
    try {
      setCollectionPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setCollectionPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setCollectionPreviewLoadingId(null);
    }
  }

  const datasetArtifacts = artifacts.filter((artifact) => artifact.asset_type === "dataset_snapshot");
  const profileArtifacts = artifacts.filter((artifact) => artifact.asset_type === "eda_profile");
  const collectionArtifacts = artifacts.filter((artifact) =>
    ["benchmark_collection_plan", "benchmark_collection_report"].includes(artifact.asset_type)
  );
  const scenarioArtifacts = artifacts.filter((artifact) =>
    ["benchmark_scenario_pack", "benchmark_scenario_report"].includes(artifact.asset_type)
  );
  const evidenceArtifacts = artifacts.filter((artifact) =>
    ["benchmark_evidence_pack", "benchmark_evidence_report"].includes(artifact.asset_type)
  );
  const relationalArtifacts = artifacts.filter((artifact) => artifact.asset_type === "relational_catalog");
  const relationalFeatureArtifacts = artifacts.filter((artifact) =>
    ["relational_feature_plan", "relational_feature_report"].includes(artifact.asset_type)
  );
  const relationalRecipeArtifacts = artifacts.filter((artifact) =>
    [
      "relational_feature_recipe",
      "relational_feature_preview",
      "relational_feature_preview_profile",
      "relational_feature_recipe_report"
    ].includes(artifact.asset_type)
  );
  const relationalScenarioArtifacts = artifacts.filter((artifact) =>
    ["relational_feature_scenario_diagnostics", "relational_feature_scenario_report"].includes(artifact.asset_type)
  );
  const qualityArtifacts = artifacts.filter((artifact) =>
    ["data_quality_gate", "data_quality_report"].includes(artifact.asset_type)
  );
  const publicWorkflowJobs = jobs.filter((job) => job.job_type === "run_public_benchmark_workflow");
  const latestDataset = datasets[0] ?? null;
  return (
    <div className="stack">
      <Panel title="Dataset Upload" icon={<Upload size={18} />}>
        <div className="upload-row">
          <input type="file" accept=".csv,.parquet" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Target column" />
          <button className="primary-button" disabled={!file || busy} onClick={() => void uploadDataset()}>
            {busy ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
            Upload
          </button>
          <button
            className="secondary-button"
            disabled={!latestDataset || busy}
            onClick={() =>
              latestDataset
                ? void runAction(() => api(`/api/datasets/${latestDataset.id}/quality/run`, { method: "POST" }))
                : undefined
            }
          >
            {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
            Analyze Quality
          </button>
        </div>
      </Panel>
      <Panel title="Benchmark Collection Plan" icon={<Database size={18} />}>
        <div className="toolbar">
          <button className="secondary-button" disabled={busy} onClick={() => void createBenchmarkCollectionPlan()}>
            {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
            Collection Plan
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => void createBenchmarkEvidencePack()}>
            {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
            Evidence Pack
          </button>
        </div>
        {collectionArtifacts.length ? (
          <Table
            headers={["Type", "Benchmarks", "Credentialed", "Public", "Fixtures", "Local Ready", "Created", "Actions"]}
            rows={collectionArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.benchmark_count ?? "-"),
              String(artifact.metadata.credentialed_count ?? "-"),
              String(artifact.metadata.public_direct_count ?? "-"),
              String(artifact.metadata.fixture_available_count ?? "-"),
              String(artifact.metadata.local_ready_count ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={collectionPreviewLoadingId === artifact.id}
                  onClick={() => void loadCollectionPreview(artifact.id)}
                  title="Preview benchmark collection plan"
                >
                  {collectionPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download benchmark collection plan">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Benchmark collection plans will rank credentialed Kaggle competitions, credential-free public datasets, fixtures, local readiness, and recommended smoke workflows without storing credentials." />
        )}
        {collectionPreviewError ? <div className="banner danger">{collectionPreviewError}</div> : null}
        {collectionPreview?.preview_available ? (
          <TranslatablePreview preview={collectionPreview} />
        ) : (
          <EmptyInline text={collectionPreview?.reason ?? "Create or select a benchmark collection plan to inspect source readiness, credential policy, and recommended benchmark suite order."} />
        )}
      </Panel>
      <Panel title="Benchmark Dataset Catalog" icon={<Database size={18} />}>
        {benchmarks.length ? (
          <div className="benchmark-grid">
            {benchmarks.map((benchmark) => {
              const status = benchmark.local_status;
              const benchmarkPath = benchmarkPaths[benchmark.id] ?? benchmark.default_local_path;
              const targetColumn = textField(benchmark.primary_table.target_column) ?? "-";
              const scenarioKind = textField(benchmark.scenario?.kind) ?? "-";
              const access = benchmark.source_card?.access ?? benchmark.access ?? {};
              const accessKind = textField(access.kind) ?? benchmark.source_kind;
              const verification = benchmark.source_card?.source_verification ?? {};
              const tableBundle = benchmark.source_card?.table_bundle ?? {};
              const requiresAccount = access.requires_account === true;
              const directDownload = access.supports_direct_download === true;
              const credentialProbe = benchmark.source_card?.credential_probe;
              const canProbeKaggle = credentialProbe?.supported === true;
              const credentialInventory = benchmark.source_card?.credential_inventory;
              const canFetchInventory = credentialInventory?.supported === true;
              const credentialDownload = benchmark.source_card?.credential_download;
              const canDownloadKaggle = credentialDownload?.supported === true;
              const probeResult = kaggleProbeResults[benchmark.id];
              const inventoryResult = kaggleInventoryResults[benchmark.id];
              const downloadResult = kaggleDownloadResults[benchmark.id];
              const probeStatus = textField(probeResult?.probe_status) ?? credentialProbe?.status ?? "not_run";
              const inventoryStatus = textField(inventoryResult?.inventory_status) ?? credentialInventory?.status ?? "not_fetched";
              const downloadStatus = textField(downloadResult?.download_status) ?? credentialDownload?.status ?? "not_started";
              const credentialAvailable = probeResult?.credential_available === true;
              const canAccessFiles = probeResult?.can_access_competition_files === true;
              const inventoryFileCount = numberField(inventoryResult?.file_count);
              const inventoryRequiredMissing = numberField(inventoryResult?.required_missing_count);
              const inventorySize = numberField(inventoryResult?.total_size_bytes);
              const downloadedCount = numberField(downloadResult?.downloaded_count);
              const downloadedBytes = numberField(downloadResult?.downloaded_bytes);
              const downloadLocalReady = downloadResult?.local_ready === true;
              const nextActions = benchmark.source_card?.import_readiness.next_actions.slice(0, 2) ?? [];
              return (
                <div className="benchmark-card" key={benchmark.id}>
                  <div className="benchmark-card-header">
                    <div>
                      <div className="mini-card-title">{benchmark.name}</div>
                      <div className="badge-row">
                        <span className="badge muted">{benchmark.source_kind}</span>
                        {benchmark.scale ? <span className="badge muted">{benchmark.scale}</span> : null}
                        <span className={status?.ready ? "badge" : "badge risk"}>
                          {status?.ready ? "ready" : `${status?.required_missing_count ?? 0} missing`}
                        </span>
                        {benchmark.fixture_available ? <span className="badge">fixture</span> : null}
                        <span className={requiresAccount ? "badge risk" : "badge"}>
                          {requiresAccount ? "credentialed" : "credential-free"}
                        </span>
                        {canProbeKaggle ? <span className="badge energized">probe-ready</span> : null}
                        {directDownload ? <span className="badge">public archive</span> : null}
                      </div>
                    </div>
                    <a className="icon-link" href={benchmark.source_url} target="_blank" rel="noreferrer" title="Open source">
                      <FileText size={16} />
                    </a>
                  </div>
                  <div className="badge-row">
                    {benchmark.modality_tags.slice(0, 5).map((tag) => (
                      <span className="badge muted" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                  <dl className="facts">
                    <div>
                      <dt>Primary</dt>
                      <dd>{primaryTableLabel(benchmark)}</dd>
                    </div>
                    <div>
                      <dt>Target</dt>
                      <dd>{targetColumn}</dd>
                    </div>
                    <div>
                      <dt>Scenario</dt>
                      <dd>{scenarioKind.replace(/_/g, " ")}</dd>
                    </div>
                    <div>
                      <dt>Access</dt>
                      <dd>{accessKind.replace(/_/g, " ")}</dd>
                    </div>
                    <div>
                      <dt>Sources</dt>
                      <dd>{benchmark.source_card?.official_sources.length ?? 1} official refs</dd>
                    </div>
                    <div>
                      <dt>Verified</dt>
                      <dd>{textField(verification.verified_at) ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>Required</dt>
                      <dd>
                        {status?.required_found_count ?? 0}/{benchmark.required_files.length} files
                      </dd>
                    </div>
                    <div>
                      <dt>Bundle</dt>
                      <dd>
                        {Number(tableBundle.supporting_table_count ?? 0)} support / {Number(tableBundle.holdout_table_count ?? 0)} holdout
                      </dd>
                    </div>
                  </dl>
                  {canProbeKaggle ? (
                    <div className="credential-strip">
                      <div className="credential-strip-header">
                        <span>
                          <KeyRound size={15} />
                          Kaggle gate
                        </span>
                        <strong className={canAccessFiles ? "status-good" : probeStatus === "not_run" ? "status-muted" : "status-warn"}>
                          {probeStatus.replace(/_/g, " ")}
                        </strong>
                      </div>
                      <div className="credential-pulse">
                        <span className={credentialAvailable ? "on" : ""}>credential</span>
                        <span className={probeStatus !== "not_run" ? "on" : ""}>probe</span>
                        <span className={inventoryStatus !== "not_fetched" || canAccessFiles ? "on" : ""}>files</span>
                        <span className={downloadedCount !== null || downloadLocalReady ? "on" : ""}>local</span>
                      </div>
                      <div className="inventory-meter">
                        <span>{inventoryStatus.replace(/_/g, " ")}</span>
                        <strong>{inventoryFileCount !== null ? `${inventoryFileCount} files` : "inventory pending"}</strong>
                        <span>{inventoryRequiredMissing !== null ? `${inventoryRequiredMissing} required missing` : "role map pending"}</span>
                        <strong>{inventorySize !== null ? formatBytes(inventorySize) : "-"}</strong>
                        <span>{downloadStatus.replace(/_/g, " ")}</span>
                        <strong>{downloadedCount !== null ? `${downloadedCount} downloaded` : "download pending"}</strong>
                        <span>{downloadLocalReady ? "import ready" : "local not ready"}</span>
                        <strong>{downloadedBytes !== null ? formatBytes(downloadedBytes) : "-"}</strong>
                      </div>
                    </div>
                  ) : null}
                  {nextActions.length ? (
                    <ul className="source-actions">
                      {nextActions.map((action) => (
                        <li key={action}>{action}</li>
                      ))}
                    </ul>
                  ) : null}
                  <input
                    value={benchmarkPath}
                    onChange={(event) =>
                      setBenchmarkPaths((current) => ({ ...current, [benchmark.id]: event.target.value }))
                    }
                    aria-label={`${benchmark.name} local path`}
                  />
                  <div className="button-row">
                    <button className="primary-button" disabled={busy} onClick={() => void importBenchmark(benchmark)}>
                      {busy ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
                      Import
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy || !benchmark.fixture_available}
                      onClick={() => void generateBenchmarkFixture(benchmark)}
                    >
                      <Database size={16} />
                      Fixture
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy || requiresAccount || !directDownload}
                      onClick={() => void downloadPublicBenchmark(benchmark)}
                    >
                      <Download size={16} />
                      Public
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy || requiresAccount || !directDownload}
                      onClick={() => void runPublicBenchmarkWorkflow(benchmark)}
                    >
                      <Play size={16} />
                      Flow
                    </button>
                    <button
                      className="secondary-button probe-button"
                      disabled={busy || !canProbeKaggle}
                      onClick={() => void probeKaggleBenchmark(benchmark)}
                    >
                      <KeyRound size={16} />
                      Probe
                    </button>
                    <button
                      className="secondary-button probe-button"
                      disabled={busy || !canFetchInventory}
                      onClick={() => void fetchKaggleInventory(benchmark)}
                    >
                      <ListChecks size={16} />
                      Inventory
                    </button>
                    <button
                      className="secondary-button probe-button"
                      disabled={busy || !canDownloadKaggle}
                      onClick={() => void downloadKaggleRequiredFiles(benchmark)}
                    >
                      <Download size={16} />
                      Required
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy || !benchmark.fixture_available}
                      onClick={() => void runBenchmarkFixtureSmoke(benchmark)}
                    >
                      <Play size={16} />
                      Smoke
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => void createBenchmarkScenarioPack(benchmark)}
                    >
                      <Layers size={16} />
                      Scenario
                    </button>
                    <a className="secondary-button text-link-button" href={benchmark.source_url} target="_blank" rel="noreferrer">
                      Source
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyInline text="Benchmark dataset entries will appear here with local import status, source links, and primary-table metadata." />
        )}
      </Panel>
      <Panel title="Public Workflow Results" icon={<ListChecks size={18} />}>
        {publicWorkflowJobs.length ? (
          <Table
            headers={["Benchmark", "Status", "Run", "Model", "Metric", "Artifacts", "Ended", "Actions"]}
            rows={publicWorkflowJobs.slice(0, 6).map((job) => {
              const metrics = job.output.metrics;
              const metricText =
                metrics && typeof metrics === "object" && !Array.isArray(metrics)
                  ? formatMetric(metrics as Record<string, unknown>)
                  : "-";
              const runReportArtifactId = textField(job.output.run_report_artifact_id);
              const decisionReportArtifactId = textField(job.output.decision_report_artifact_id);
              const scenarioReportArtifactId = textField(job.output.benchmark_scenario_report_artifact_id);
              const artifactCount = Array.isArray(job.output.artifact_ids) ? job.output.artifact_ids.length : 0;
              return [
                String(job.output.benchmark_id ?? "-"),
                formatJobStatus(job),
                String(job.output.experiment_run_id ?? "-"),
                String(job.output.model_version_id ?? "-"),
                metricText,
                String(artifactCount),
                formatDate(job.ended_at),
                <div className="row-actions" key={job.id}>
                  <button
                    className="icon-button"
                    disabled={!runReportArtifactId || workflowPreviewLoadingId === runReportArtifactId}
                    onClick={() => {
                      if (runReportArtifactId) void loadWorkflowPreview(runReportArtifactId);
                    }}
                    title="Preview run report"
                  >
                    {workflowPreviewLoadingId === runReportArtifactId ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!decisionReportArtifactId || workflowPreviewLoadingId === decisionReportArtifactId}
                    onClick={() => {
                      if (decisionReportArtifactId) void loadWorkflowPreview(decisionReportArtifactId);
                    }}
                    title="Preview decision report"
                  >
                    {workflowPreviewLoadingId === decisionReportArtifactId ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!scenarioReportArtifactId || workflowPreviewLoadingId === scenarioReportArtifactId}
                    onClick={() => {
                      if (scenarioReportArtifactId) void loadWorkflowPreview(scenarioReportArtifactId);
                    }}
                    title="Preview benchmark scenario"
                  >
                    {workflowPreviewLoadingId === scenarioReportArtifactId ? <Loader2 className="spin" size={16} /> : <Layers size={16} />}
                  </button>
                </div>
              ];
            })}
          />
        ) : (
          <EmptyInline text="Credential-free public benchmark workflow results will appear here with run metrics, reports, decision artifacts, and scenario summaries." />
        )}
        {workflowPreviewError ? <div className="banner danger">{workflowPreviewError}</div> : null}
        {workflowPreview?.preview_available ? (
          <TranslatablePreview preview={workflowPreview} />
        ) : (
          <EmptyInline text={workflowPreview?.reason ?? "Run a public workflow or select a report action to preview results."} />
        )}
      </Panel>
      <Panel title="Benchmark Evidence Packs" icon={<BarChart3 size={18} />}>
        <div className="toolbar">
          <button className="secondary-button" disabled={busy} onClick={() => void createBenchmarkEvidencePack()}>
            {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
            Generate Evidence Pack
          </button>
        </div>
        {evidenceArtifacts.length ? (
          <Table
            headers={["Type", "Benchmarks", "Ready", "Created", "Actions"]}
            rows={evidenceArtifacts.map((artifact) => {
              const benchmarkIds = Array.isArray(artifact.metadata.benchmark_ids)
                ? artifact.metadata.benchmark_ids.map((item) => String(item)).join(", ")
                : "-";
              return [
                artifact.asset_type,
                benchmarkIds || "-",
                String(artifact.metadata.ready_benchmark_count ?? artifact.metadata.benchmark_count ?? "-"),
                formatDate(artifact.created_at),
                <div className="row-actions" key={artifact.id}>
                  <button
                    className="icon-button"
                    disabled={evidencePreviewLoadingId === artifact.id}
                    onClick={() => void loadEvidencePreview(artifact.id)}
                    title="Preview benchmark evidence"
                  >
                    {evidencePreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                  </button>
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download benchmark evidence">
                    <Download size={16} />
                  </a>
                </div>
              ];
            })}
          />
        ) : (
          <EmptyInline text="Benchmark evidence packs will collect source cards, local status, scenario packs, workflow results, reports, visualizations, and AgentTask handoff state into one in-product report." />
        )}
        {evidencePreviewError ? <div className="banner danger">{evidencePreviewError}</div> : null}
        {evidencePreview?.preview_available ? (
          <TranslatablePreview preview={evidencePreview} />
        ) : (
          <EmptyInline text={evidencePreview?.reason ?? "Generate or select an evidence pack to inspect benchmark readiness and next actions."} />
        )}
      </Panel>
      <Panel title="Dataset Snapshots" icon={<Database size={18} />}>
        {datasets.length ? (
          <Table
            headers={["Snapshot", "Source", "Rows", "Columns", "Schema Hash"]}
            rows={datasets.map((dataset) => [
              dataset.id,
              <div className="cell-stack" key={`${dataset.id}-source`}>
                <span>{dataset.source_type}</span>
                <small>{dataset.source_ref ?? "-"}</small>
              </div>,
              dataset.row_count ?? "-",
              dataset.column_count ?? "-",
              dataset.schema_hash.slice(0, 12)
            ])}
          />
        ) : (
          <EmptyInline text="Uploaded CSV or Parquet files will become DatasetSnapshot assets with schema, row count, and lineage." />
        )}
      </Panel>
      <Panel title="Profile Readiness" icon={<BarChart3 size={18} />}>
        {profileArtifacts.length ? (
          <Table
            headers={["Profile", "Mode", "Sample Rows", "Deferred", "Created", "Actions"]}
            rows={profileArtifacts.map((artifact) => [
              artifact.name,
              String(artifact.metadata.profile_mode ?? "full").replace(/_/g, " "),
              artifact.metadata.sample_row_count ? String(artifact.metadata.sample_row_count) : "-",
              artifact.metadata.deep_profile_recommended
                ? `${String(artifact.metadata.deferred_column_count ?? "-")} columns`
                : "No",
              formatDate(artifact.created_at),
              <a className="icon-link" key={artifact.id} href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download profile artifact">
                <Download size={16} />
              </a>
            ])}
          />
        ) : (
          <EmptyInline text="Data profiles will show full or bounded-sample mode, sample coverage, target profile, and any deferred deep-profile columns after upload or benchmark import." />
        )}
      </Panel>
      <Panel title="Source Artifacts" icon={<FileText size={18} />}>
        {datasetArtifacts.length ? (
          <Table
            headers={["Artifact", "Version", "Size"]}
            rows={datasetArtifacts.map((artifact) => [artifact.name, `v${artifact.version}`, formatBytes(artifact.size_bytes)])}
          />
        ) : (
          <EmptyInline text="Raw uploaded files are stored in the local artifact store with content hashes." />
        )}
      </Panel>
      <Panel title="Relational Catalogs" icon={<GitBranch size={18} />}>
        <div className="toolbar">
          <button className="secondary-button" disabled={busy} onClick={() => void createRelationalFeaturePlan()}>
            {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
            Feature Plan
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => void createRelationalFeatureRecipe()}>
            {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            Build Recipe
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => void diagnoseRelationalFeatureScenarios()}>
            {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
            Diagnose
          </button>
        </div>
        {relationalArtifacts.length ? (
          <Table
            headers={["Benchmark", "Tables", "Relationships", "Actions"]}
            rows={relationalArtifacts.map((artifact) => [
              String(artifact.metadata.benchmark_id ?? artifact.name),
              String(artifact.metadata.table_count ?? "-"),
              String(artifact.metadata.relationship_count ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={relationalPreviewLoadingId === artifact.id}
                  onClick={() => void loadRelationalPreview(artifact.id)}
                  title="Preview relational catalog"
                >
                  {relationalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download relational catalog">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Benchmark imports with supporting tables will register relational catalogs with table profiles and inferred join keys." />
        )}
        {relationalFeatureArtifacts.length ? (
          <Table
            headers={["Plan", "Benchmark", "Tables", "Candidates", "High Risk", "Created", "Actions"]}
            rows={relationalFeatureArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.benchmark_id ?? "-"),
              String(artifact.metadata.table_count ?? "-"),
              String(artifact.metadata.aggregation_candidate_count ?? "-"),
              String(artifact.metadata.high_risk_count ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={relationalPreviewLoadingId === artifact.id}
                  onClick={() => void loadRelationalPreview(artifact.id)}
                  title="Preview relational feature plan"
                >
                  {relationalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download relational feature plan">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Relational feature plans will turn table profiles and inferred joins into train-fold-safe aggregation candidates, leakage risks, and AgentTask handoff notes." />
        )}
        {relationalRecipeArtifacts.length ? (
          <Table
            headers={["Recipe Artifact", "Features", "Steps", "Deferred", "Preview Rows", "Created", "Actions"]}
            rows={relationalRecipeArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.generated_feature_count ?? "-"),
              String(artifact.metadata.executed_step_count ?? "-"),
              String(artifact.metadata.deferred_step_count ?? "-"),
              String(artifact.metadata.preview_row_count ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={relationalPreviewLoadingId === artifact.id}
                  onClick={() => void loadRelationalPreview(artifact.id)}
                  title="Preview relational feature recipe"
                >
                  {relationalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download relational feature recipe">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Relational feature recipe previews will materialize safe aggregation steps, deferred checks, generated feature columns, reports, and visualization specs for later AgentRunner implementation." />
        )}
        {relationalScenarioArtifacts.length ? (
          <Table
            headers={["Scenario Artifact", "Usable", "Constant", "High Missing", "Deferred", "Scenarios", "Actions"]}
            rows={relationalScenarioArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.usable_feature_count ?? "-"),
              String(artifact.metadata.constant_feature_count ?? "-"),
              String(artifact.metadata.high_missing_feature_count ?? "-"),
              String(artifact.metadata.deferred_step_count ?? "-"),
              String(artifact.metadata.scenario_count ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={relationalPreviewLoadingId === artifact.id}
                  onClick={() => void loadRelationalPreview(artifact.id)}
                  title="Preview relational scenario diagnostics"
                >
                  {relationalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download relational scenario diagnostics">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Relational scenario diagnostics will compare primary-only, safe relational preview, deferred feature, and evaluation-readiness scenarios without running a fixed model strategy." />
        )}
      </Panel>
      <Panel title="Relational Preview" icon={<FileText size={18} />}>
        {relationalPreviewError ? <div className="banner danger">{relationalPreviewError}</div> : null}
        {relationalPreview?.preview_available ? (
          <TranslatablePreview preview={relationalPreview} />
        ) : (
          <EmptyInline text={relationalPreview?.reason ?? "Select a relational catalog, feature plan, recipe, or scenario diagnostics artifact to inspect table profiles, key candidates, generated preview features, scenario comparisons, and guardrails."} />
        )}
      </Panel>
      <Panel title="Benchmark Scenario Packs" icon={<Layers size={18} />}>
        {scenarioArtifacts.length ? (
          <Table
            headers={["Type", "Benchmark", "Scenario", "Dataset", "Actions"]}
            rows={scenarioArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.benchmark_id ?? artifact.name),
              String(artifact.metadata.scenario_kind ?? "-").replace(/_/g, " "),
              String(artifact.metadata.dataset_snapshot_id ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={scenarioPreviewLoadingId === artifact.id}
                  onClick={() => void loadScenarioPreview(artifact.id)}
                  title="Preview benchmark scenario"
                >
                  {scenarioPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download benchmark scenario">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Benchmark scenario packs will summarize intended use, local fixture status, relational context, evaluation readiness, ResearchPlan handoff, reporting expectations, and runner guardrails." />
        )}
        {scenarioPreviewError ? <div className="banner danger">{scenarioPreviewError}</div> : null}
        {scenarioPreview?.preview_available ? (
          <TranslatablePreview preview={scenarioPreview} />
        ) : (
          <EmptyInline text={scenarioPreview?.reason ?? "Generate or select a benchmark scenario artifact to inspect workflow and runner handoff context."} />
        )}
      </Panel>
      <Panel title="Data Quality Gates" icon={<ListChecks size={18} />}>
        {qualityArtifacts.length ? (
          <Table
            headers={["Type", "Name", "Severity", "Scope", "Dataset", "Actions"]}
            rows={qualityArtifacts.map((artifact) => [
              artifact.asset_type,
              artifact.name,
              String(artifact.metadata.severity ?? "-"),
              String(artifact.metadata.quality_check_scope ?? "-"),
              String(artifact.metadata.dataset_snapshot_id ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={qualityPreviewLoadingId === artifact.id}
                  onClick={() => void loadQualityPreview(artifact.id)}
                  title="Preview data quality artifact"
                >
                  {qualityPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download data quality artifact">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Data quality gates will summarize leakage, missingness, identity, time/group, duplicate, and evaluation readiness risks for each DatasetSnapshot." />
        )}
      </Panel>
      <Panel title="Data Quality Preview" icon={<FileText size={18} />}>
        {qualityPreviewError ? <div className="banner danger">{qualityPreviewError}</div> : null}
        {qualityPreview?.preview_available ? (
          <TranslatablePreview preview={qualityPreview} />
        ) : (
          <EmptyInline text={qualityPreview?.reason ?? "Analyze quality or select a quality artifact to inspect gates, guidance, and agent-context notes."} />
        )}
      </Panel>
    </div>
  );
}

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function primaryTableLabel(benchmark: BenchmarkDataset): string {
  const path = textField(benchmark.primary_table.path);
  if (path) return path;
  const candidates = benchmark.primary_table.path_candidates;
  if (Array.isArray(candidates) && candidates.length) {
    return candidates
      .slice(0, 2)
      .map((item) => String(item))
      .join(" | ");
  }
  return "-";
}

function UnderstandingTab({
  understanding,
  questions,
  busy,
  runAction,
  answerQuestion
}: {
  understanding: string | null;
  questions: Question[];
  busy: boolean;
  runAction: () => Promise<void>;
  answerQuestion: (questionId: string, answerValue: string, answerText: string) => Promise<void>;
}) {
  return (
    <div className="stack">
      <div className="toolbar">
        <button className="secondary-button" disabled={busy} onClick={() => void runAction()}>
          {busy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          Run Understanding
        </button>
      </div>
      <Panel title="Data Understanding Report" icon={<FileText size={18} />}>
        {understanding ? (
          <pre className="markdown-preview">{understanding}</pre>
        ) : (
          <EmptyInline text="Executive summary, target profile, data quality findings, leakage risks, recommended evaluation direction, questions, and assumptions will appear here." />
        )}
      </Panel>
      <Panel title="Questions For Human" icon={<ListChecks size={18} />}>
        {questions.length ? (
          <div className="question-list">
            {questions.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                busy={busy}
                answerQuestion={answerQuestion}
              />
            ))}
          </div>
        ) : (
          <EmptyInline text="Questions about target definition, row semantics, prediction-time availability, time structure, group structure, and metrics will appear here." />
        )}
      </Panel>
    </div>
  );
}

function QuestionCard({
  question,
  busy,
  answerQuestion
}: {
  question: Question;
  busy: boolean;
  answerQuestion: (questionId: string, answerValue: string, answerText: string) => Promise<void>;
}) {
  const [answerValue, setAnswerValue] = React.useState(question.choices[0] ?? "");
  const [answerText, setAnswerText] = React.useState("");

  return (
    <div className="question-card">
      <div>
        <div className="question-title">{question.question}</div>
        <div className="question-meta">
          <span className="badge risk">{question.risk_level}</span>
          <span className="badge muted">{question.value_of_answer}</span>
          <span className="badge muted">{question.fallback_policy}</span>
          <span className="badge">{question.status}</span>
        </div>
        <p>{question.why_it_matters}</p>
      </div>
      <div className="answer-row">
        <select value={answerValue} onChange={(event) => setAnswerValue(event.target.value)} disabled={question.status === "answered"}>
          {question.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
        <input
          value={answerText}
          onChange={(event) => setAnswerText(event.target.value)}
          placeholder="Answer note"
          disabled={question.status === "answered"}
        />
        <button
          className="secondary-button"
          disabled={busy || question.status === "answered" || !answerValue}
          onClick={() => void answerQuestion(question.id, answerValue, answerText)}
        >
          <Check size={16} />
          Answer
        </button>
      </div>
    </div>
  );
}

function AssumptionsTab({
  assumptions,
  reviewQueue,
  questions,
  busy,
  applyFallbacks,
  runAction
}: {
  assumptions: Assumption[];
  reviewQueue: AssumptionReviewQueue | null;
  questions: Question[];
  busy: boolean;
  applyFallbacks: () => Promise<void>;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <div className="stack">
      <AssumptionReviewQueuePanel queue={reviewQueue} busy={busy} runAction={runAction} />
      <div className="toolbar">
        <button className="secondary-button" disabled={busy} onClick={() => void applyFallbacks()}>
          {busy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          Apply Fallbacks
        </button>
      </div>
      <Panel title="Assumptions" icon={<AlertTriangle size={18} />}>
        {assumptions.length ? (
          <Table
            headers={["Statement", "Confidence", "Risk", "Fallback", "Status", "Actions"]}
            rows={assumptions.map((assumption) => [
              assumption.statement,
              `${Math.round(assumption.confidence * 100)}%`,
              assumption.risk_level,
              assumption.fallback_policy,
              assumption.status,
              <div className="row-actions" key={assumption.id}>
                <button
                  className="icon-button"
                  disabled={busy || assumption.status === "confirmed"}
                  onClick={() => void runAction(() => api(`/api/assumptions/${assumption.id}/confirm`, { method: "POST" }))}
                  title="Confirm assumption"
                >
                  <Check size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || assumption.status === "challenged"}
                  onClick={() => void runAction(() => api(`/api/assumptions/${assumption.id}/reject`, { method: "POST" }))}
                  title="Challenge assumption"
                >
                  <AlertTriangle size={16} />
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Inferred, adopted, confirmed, challenged, and deployment-blocking assumptions will be tracked with confidence, risk, fallback policy, and evidence." />
        )}
      </Panel>
      <Panel title="Evidence Links" icon={<GitBranch size={18} />}>
        {assumptions.some((assumption) => assumption.evidence.length) ? (
          <Table
            headers={["Assumption", "Evidence", "Strength"]}
            rows={assumptions.flatMap((assumption) =>
              assumption.evidence.map((evidence) => [assumption.id, evidence.summary, evidence.strength])
            )}
          />
        ) : (
          <EmptyInline text={`Open questions: ${questions.length}. Evidence supporting or contradicting assumptions will appear here.`} />
        )}
      </Panel>
    </div>
  );
}

function AssumptionReviewQueuePanel({
  queue,
  busy,
  runAction
}: {
  queue: AssumptionReviewQueue | null;
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const item = queue?.next_item ?? null;
  const [answerValue, setAnswerValue] = React.useState("");
  const [answerText, setAnswerText] = React.useState("");

  React.useEffect(() => {
    setAnswerValue(item?.choices[0] ?? "");
    setAnswerText("");
  }, [item?.id, item?.choices]);

  async function runReviewAction(action: AssumptionReviewAction) {
    if (!action.endpoint) return;
    if (action.action_type === "answer_question") {
      if (!answerValue.trim()) return;
      await runAction(() =>
        api(action.endpoint as string, {
          method: action.method ?? "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer_value: answerValue, answer_text: answerText || null })
        })
      );
      return;
    }
    await runAction(() =>
      api(action.endpoint as string, {
        method: action.method ?? "POST",
        headers: action.request_body ? { "Content-Type": "application/json" } : undefined,
        body: action.request_body ? JSON.stringify(action.request_body) : undefined
      })
    );
  }

  return (
    <Panel title="Review Queue" icon={<ListChecks size={18} />}>
      {item ? (
        <div className="review-card">
          <div className="review-card-main">
            <div>
              <div className="review-card-eyebrow">
                {item.item_type === "question" ? "Question" : "Assumption"} · priority {Math.round(item.priority_score)}
              </div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </div>
            <div className="badge-row">
              <span className={item.risk_level === "high" || item.risk_level === "blocking" ? "badge risk" : "badge muted"}>
                {item.risk_level}
              </span>
              <span className="badge muted">{item.fallback_policy}</span>
              <span className="badge">{item.status}</span>
              {item.confidence !== null ? <span className="badge muted">{Math.round(item.confidence * 100)}%</span> : null}
            </div>
            {item.why_it_matters ? <p className="review-reason">{item.why_it_matters}</p> : null}
            {item.evidence.length ? (
              <ul className="review-evidence">
                {item.evidence.slice(0, 3).map((evidence) => (
                  <li key={`${item.id}-${evidence.summary}`}>
                    <strong>{evidence.strength}</strong>
                    {evidence.summary}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          {item.item_type === "question" ? (
            <div className="answer-row">
              <select value={answerValue} onChange={(event) => setAnswerValue(event.target.value)} disabled={busy}>
                {item.choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
              <input
                value={answerText}
                onChange={(event) => setAnswerText(event.target.value)}
                placeholder="Answer note"
                disabled={busy}
              />
              {item.primary_actions.map((action) => (
                <button
                  className="primary-button"
                  disabled={busy || !answerValue.trim()}
                  key={action.id}
                  onClick={() => void runReviewAction(action)}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                  {action.label}
                </button>
              ))}
            </div>
          ) : (
            <div className="button-row">
              {item.primary_actions.map((action) => (
                <button
                  className={action.action_type === "confirm_assumption" ? "primary-button" : "secondary-button"}
                  disabled={busy}
                  key={action.id}
                  onClick={() => void runReviewAction(action)}
                >
                  {action.action_type === "confirm_assumption" ? <Check size={16} /> : <AlertTriangle size={16} />}
                  {action.label}
                </button>
              ))}
            </div>
          )}
          <div className="review-queue-strip">
            <span>{queue ? `${queue.counts.reviewable_assumptions ?? 0} assumptions` : "0 assumptions"}</span>
            <span>{queue ? `${queue.counts.open_questions ?? 0} questions` : "0 questions"}</span>
            <span>{queue ? `${queue.queue.length} queued` : "0 queued"}</span>
          </div>
        </div>
      ) : (
        <EmptyInline text="No assumption or question needs review right now. Confirmed, challenged, and answered items stay available in the supporting table." />
      )}
    </Panel>
  );
}

function EvaluationTab({
  project,
  candidates,
  specs,
  artifacts,
  busy,
  runAction
}: {
  project: Project;
  candidates: EvaluationCandidate[];
  specs: EvaluationSpec[];
  artifacts: Artifact[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const latestQualityGate = artifacts.find((artifact) => artifact.asset_type === "data_quality_gate") ?? null;
  const scenarioComparisonArtifacts = artifacts.filter((artifact) => artifact.asset_type === "evaluation_scenario_comparison");
  const approvalReviewArtifacts = artifacts.filter((artifact) => artifact.asset_type === "evaluation_approval_review");
  const [scenarioPreview, setScenarioPreview] = React.useState<ArtifactPreview | null>(null);
  const [scenarioPreviewError, setScenarioPreviewError] = React.useState<string | null>(null);
  const [scenarioPreviewLoadingId, setScenarioPreviewLoadingId] = React.useState<string | null>(null);
  const [approvalPreview, setApprovalPreview] = React.useState<ArtifactPreview | null>(null);
  const [approvalPreviewError, setApprovalPreviewError] = React.useState<string | null>(null);
  const [approvalPreviewLoadingId, setApprovalPreviewLoadingId] = React.useState<string | null>(null);

  async function loadScenarioPreview(artifactId: string) {
    setScenarioPreviewError(null);
    setScenarioPreviewLoadingId(artifactId);
    try {
      setScenarioPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setScenarioPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setScenarioPreviewLoadingId(null);
    }
  }

  async function loadApprovalPreview(artifactId: string) {
    setApprovalPreviewError(null);
    setApprovalPreviewLoadingId(artifactId);
    try {
      setApprovalPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setApprovalPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setApprovalPreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api(`/api/projects/${project.id}/evaluation/design`, { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
          Design Candidates
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/evaluation/compare`, { method: "POST" });
              const artifactId = job.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadScenarioPreview(artifactId);
              }
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Compare Scenarios
        </button>
      </div>
      <Panel title="Evaluation Candidates" icon={<BarChart3 size={18} />}>
        {candidates.length ? (
          <div className="card-grid">
            {candidates.map((candidate) => (
              <div key={candidate.id} className="mini-card">
                <div className="mini-card-title">{candidate.name}</div>
                <div className="badge-row">
                  <span className="badge">{candidate.status}</span>
                  <span className="badge muted">{candidate.split_type}</span>
                  <span className="badge risk">{candidate.risk_level}</span>
                </div>
                <p>{candidate.rationale_md}</p>
                <dl className="facts">
                  <div>
                    <dt>Metric</dt>
                    <dd>{candidate.primary_metric}</dd>
                  </div>
                  <div>
                    <dt>Stratify</dt>
                    <dd>{candidate.stratify_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>Time</dt>
                    <dd>{candidate.time_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>Group</dt>
                    <dd>{candidate.group_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>Excluded</dt>
                    <dd>{candidate.excluded_columns.length || "-"}</dd>
                  </div>
                </dl>
                <button
                  className="secondary-button"
                  disabled={busy || candidate.status === "promoted_to_spec"}
                  onClick={() =>
                    void runAction(() =>
                      api(`/api/evaluation-candidates/${candidate.id}/promote`, { method: "POST" })
                    )
                  }
                >
                  <Check size={16} />
                  Promote
                </button>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text="Primary, alternative, reference random, time-aware, and group-aware evaluation candidates will appear here before any EvaluationSpec is adopted." />
        )}
      </Panel>
      <Panel title="Scenario Comparisons" icon={<ListChecks size={18} />}>
        {scenarioComparisonArtifacts.length ? (
          <Table
            headers={["Comparison", "Recommended", "Candidates", "Created", "Actions"]}
            rows={scenarioComparisonArtifacts.map((artifact) => [
              `${artifact.name} v${artifact.version}`,
              String(artifact.metadata.recommended_candidate_id ?? "-"),
              String(artifact.metadata.candidate_count ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={scenarioPreviewLoadingId === artifact.id}
                  onClick={() => void loadScenarioPreview(artifact.id)}
                  title="Preview scenario comparison"
                >
                  {scenarioPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download scenario comparison">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Scenario comparisons will summarize split feasibility, target distribution sanity, temporal/group leakage concerns, open questions, assumptions, and adoption risks before an EvaluationSpec is promoted." />
        )}
        {scenarioPreviewError ? <div className="banner danger">{scenarioPreviewError}</div> : null}
        {scenarioPreview?.preview_available ? (
          <TranslatablePreview preview={scenarioPreview} />
        ) : (
          <EmptyInline text={scenarioPreview?.reason ?? "Generate or select a comparison artifact to inspect decision support before adopting the primary EvaluationSpec."} />
        )}
      </Panel>
      <Panel title="Quality Gate Context" icon={<AlertTriangle size={18} />}>
        {latestQualityGate ? (
          <Table
            headers={["Gate", "Severity", "Dataset", "Preview"]}
            rows={[
              [
                latestQualityGate.name,
                String(latestQualityGate.metadata.severity ?? "-"),
                String(latestQualityGate.metadata.dataset_snapshot_id ?? "-"),
                <a className="icon-link" key={latestQualityGate.id} href={`${apiBase}/api/artifacts/${latestQualityGate.id}/download`} title="Download quality gate">
                  <Download size={16} />
                </a>
              ]
            ]}
          />
        ) : (
          <EmptyInline text="Run data quality analysis from the Data tab to expose leakage, availability, missingness, identity, time/group, duplicate, and evaluation readiness findings before adopting an EvaluationSpec." />
        )}
      </Panel>
      <Panel title="Evaluation Specs" icon={<Check size={18} />}>
        {specs.length ? (
          <Table
            headers={["Spec", "Split", "Metric", "Status", "Actions"]}
            rows={specs.map((spec) => [
              spec.id,
              spec.split_type,
              spec.primary_metric,
              spec.status,
              <div className="row-actions" key={spec.id}>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/evaluation-specs/${spec.id}/approval-review`, { method: "POST" });
                      const artifactId = job.output.artifact_id;
                      if (typeof artifactId === "string") {
                        await loadApprovalPreview(artifactId);
                      }
                    })
                  }
                  title="Create approval review"
                >
                  <ListChecks size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || spec.status === "approved"}
                  onClick={() => void runAction(() => api(`/api/evaluation-specs/${spec.id}/approve`, { method: "POST" }))}
                  title="Approve EvaluationSpec"
                >
                  <Check size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || spec.status !== "approved" || !["random", "stratified", "time", "group"].includes(spec.split_type)}
                  onClick={() =>
                    void runAction(() => api(`/api/evaluation-specs/${spec.id}/generate-split`, { method: "POST" }))
                  }
                  title="Generate SplitManifest"
                >
                  <GitBranch size={16} />
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Adopted primary EvaluationSpecs will appear here. Baselines should use an approved spec and generated SplitManifest." />
        )}
      </Panel>
      <Panel title="Approval Reviews" icon={<FileText size={18} />}>
        {approvalReviewArtifacts.length ? (
          <Table
            headers={["Spec", "Status", "Blockers", "Warnings", "Created", "Actions"]}
            rows={approvalReviewArtifacts.map((artifact) => [
              String(artifact.metadata.evaluation_spec_id ?? artifact.name),
              String(artifact.metadata.review_status ?? "-"),
              String(artifact.metadata.blocker_count ?? "-"),
              String(artifact.metadata.warning_count ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={approvalPreviewLoadingId === artifact.id}
                  onClick={() => void loadApprovalPreview(artifact.id)}
                  title="Preview approval review"
                >
                  {approvalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download approval review">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Approval reviews will capture blockers, assumption-backed proceed decisions, quality context, scenario comparison context, and lineage before EvaluationSpec approval." />
        )}
        {approvalPreviewError ? <div className="banner danger">{approvalPreviewError}</div> : null}
        {approvalPreview?.preview_available ? (
          <TranslatablePreview preview={approvalPreview} />
        ) : (
          <EmptyInline text={approvalPreview?.reason ?? "Create or select an approval review to inspect blockers and assumption-backed proceed notes."} />
        )}
      </Panel>
    </div>
  );
}

function StrategyBriefPanel({
  project,
  brief,
  busy,
  text,
  onAction,
  onSave
}: {
  project: Project;
  brief: AdaptiveStrategyBrief | null;
  busy: boolean;
  text: LocaleMessages;
  onAction: (action: StrategyAction) => void;
  onSave: () => Promise<void>;
}) {
  if (!brief) {
    return (
      <section className="strategy-brief-panel">
        <div>
          <div className="eyebrow">{text.strategyBriefTitle}</div>
          <h2>{project.name}</h2>
          <p>{text.strategyNoBrief}</p>
        </div>
        <button className="secondary-button" disabled={busy} onClick={() => void onSave()}>
          {busy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          {text.strategySaveSnapshot}
        </button>
      </section>
    );
  }

  const action = brief.recommended_next_action;
  const handoffObjective = textField(brief.codex_handoff.suggested_objective) ?? action.prompt ?? action.reason;
  const openItems =
    numericSummary(brief.summary.open_assumption_count) + numericSummary(brief.summary.open_question_count);
  const metrics = [
    { label: text.strategyArtifacts, value: numericSummary(brief.summary.artifact_count) },
    { label: text.strategyOpenItems, value: openItems },
    { label: text.strategyIdeas, value: numericSummary(brief.summary.idea_count) },
    { label: text.strategyRuns, value: numericSummary(brief.summary.experiment_run_count) }
  ];

  return (
    <section className="strategy-brief-panel">
      <div className="strategy-hero">
        <div>
          <div className="eyebrow">{text.strategyBriefTitle}</div>
          <h2>{action.label}</h2>
          <p>{action.reason}</p>
          <div className="button-row">
            <button className="primary-button" disabled={busy} onClick={() => onAction(action)}>
              {busy ? <Loader2 className="spin" size={16} /> : strategyActionIcon(action.action_type)}
              {text.strategyRunAction}
            </button>
            <button className="secondary-button" disabled={busy} onClick={() => void onSave()}>
              {busy ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
              {text.strategySaveSnapshot}
            </button>
          </div>
        </div>
        <div className="strategy-metrics" aria-label={text.strategyRecommendedAction}>
          {metrics.map((metric) => (
            <div key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="strategy-lane-strip" aria-label={text.strategyLaneMap}>
        {brief.candidate_lanes.map((lane) => (
          <div key={lane.lane_id} className={`strategy-lane ${strategyLaneTone(lane.status)}`} title={lane.why}>
            <span>{lane.title}</span>
            <strong>{formatStrategyStatus(lane.status)}</strong>
          </div>
        ))}
      </div>
      <div className="strategy-handoff">
        <div>
          <div className="eyebrow">{text.strategyCodexHandoff}</div>
          <p>{handoffObjective}</p>
        </div>
        <div className="badge-row">
          <span className="badge">open-ended</span>
          <span className="badge muted">split locked: {formatBooleanPath(brief.codex_handoff, ["autonomy_policy", "must_respect_split_manifest"])}</span>
          <span className="badge muted">network: {formatNestedPath(brief.codex_handoff, ["autonomy_policy", "network_default"])}</span>
        </div>
      </div>
    </section>
  );
}

function strategyActionIcon(actionType: StrategyAction["action_type"]) {
  if (actionType === "api") return <Play size={16} />;
  if (actionType === "agent_task") return <Send size={16} />;
  return <ArrowLikeIcon />;
}

function ArrowLikeIcon() {
  return <Layers size={16} />;
}

function numericSummary(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function strategyLaneTone(status: string) {
  if (status === "ready") return "ready";
  if (status.includes("review") || status.includes("decision")) return "warn";
  return "pending";
}

function formatStrategyStatus(status: string) {
  return status.replace(/_/g, " ");
}

function formatNestedPath(payload: Record<string, unknown>, path: string[]) {
  let current: unknown = payload;
  for (const key of path) {
    if (!current || typeof current !== "object" || !(key in current)) return "-";
    current = (current as Record<string, unknown>)[key];
  }
  return String(current ?? "-");
}

function formatBooleanPath(payload: Record<string, unknown>, path: string[]) {
  const value = formatNestedPath(payload, path);
  return value === "true" ? "yes" : value === "false" ? "no" : value;
}

function ApproachTab({
  project,
  strategyBrief,
  researchBriefs,
  ideas,
  artifacts,
  busy,
  text,
  runAction,
  onStrategyAction
}: {
  project: Project;
  strategyBrief: AdaptiveStrategyBrief | null;
  researchBriefs: ResearchBrief[];
  ideas: Idea[];
  artifacts: Artifact[];
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onStrategyAction: (action: StrategyAction) => void;
}) {
  const latestBrief = researchBriefs[0] ?? null;
  const researchPlanArtifacts = artifacts.filter((artifact) => artifact.asset_type === "research_plan");
  const researchSourceArtifacts = artifacts.filter((artifact) =>
    ["research_source_pack", "research_source_report"].includes(artifact.asset_type)
  );
  const researchSynthesisArtifacts = artifacts.filter((artifact) =>
    ["research_finding_synthesis", "research_finding_synthesis_report"].includes(artifact.asset_type)
  );
  const agentTaskContractArtifacts = artifacts.filter((artifact) => artifact.asset_type === "agent_task_contract");
  const [researchPlanPreview, setResearchPlanPreview] = React.useState<ArtifactPreview | null>(null);
  const [researchPlanPreviewError, setResearchPlanPreviewError] = React.useState<string | null>(null);
  const [researchPlanPreviewLoadingId, setResearchPlanPreviewLoadingId] = React.useState<string | null>(null);
  const [researchSourcePreview, setResearchSourcePreview] = React.useState<ArtifactPreview | null>(null);
  const [researchSourcePreviewError, setResearchSourcePreviewError] = React.useState<string | null>(null);
  const [researchSourcePreviewLoadingId, setResearchSourcePreviewLoadingId] = React.useState<string | null>(null);
  const [researchSynthesisPreview, setResearchSynthesisPreview] = React.useState<ArtifactPreview | null>(null);
  const [researchSynthesisPreviewError, setResearchSynthesisPreviewError] = React.useState<string | null>(null);
  const [researchSynthesisPreviewLoadingId, setResearchSynthesisPreviewLoadingId] = React.useState<string | null>(null);
  const [taskContractPreview, setTaskContractPreview] = React.useState<ArtifactPreview | null>(null);
  const [taskContractPreviewError, setTaskContractPreviewError] = React.useState<string | null>(null);
  const [taskContractPreviewLoadingId, setTaskContractPreviewLoadingId] = React.useState<string | null>(null);
  const [contextPreview, setContextPreview] = React.useState<ArtifactPreview | null>(null);
  const [contextPreviewError, setContextPreviewError] = React.useState<string | null>(null);
  const [contextPreviewLoadingId, setContextPreviewLoadingId] = React.useState<string | null>(null);
  const [planPreview, setPlanPreview] = React.useState<ArtifactPreview | null>(null);
  const [planPreviewError, setPlanPreviewError] = React.useState<string | null>(null);
  const [planPreviewLoadingId, setPlanPreviewLoadingId] = React.useState<string | null>(null);
  const [workspacePreview, setWorkspacePreview] = React.useState<ArtifactPreview | null>(null);
  const [workspacePreviewError, setWorkspacePreviewError] = React.useState<string | null>(null);
  const [workspacePreviewLoadingId, setWorkspacePreviewLoadingId] = React.useState<string | null>(null);

  async function loadContextPreview(artifactId: string) {
    setContextPreviewLoadingId(artifactId);
    setContextPreviewError(null);
    try {
      setContextPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setContextPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setContextPreviewLoadingId(null);
    }
  }

  async function loadResearchPlanPreview(artifactId: string) {
    setResearchPlanPreviewLoadingId(artifactId);
    setResearchPlanPreviewError(null);
    try {
      setResearchPlanPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setResearchPlanPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setResearchPlanPreviewLoadingId(null);
    }
  }

  async function loadResearchSourcePreview(artifactId: string) {
    setResearchSourcePreviewLoadingId(artifactId);
    setResearchSourcePreviewError(null);
    try {
      setResearchSourcePreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setResearchSourcePreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setResearchSourcePreviewLoadingId(null);
    }
  }

  async function loadResearchSynthesisPreview(artifactId: string) {
    setResearchSynthesisPreviewLoadingId(artifactId);
    setResearchSynthesisPreviewError(null);
    try {
      setResearchSynthesisPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setResearchSynthesisPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setResearchSynthesisPreviewLoadingId(null);
    }
  }

  async function loadTaskContractPreview(artifactId: string) {
    setTaskContractPreviewLoadingId(artifactId);
    setTaskContractPreviewError(null);
    try {
      setTaskContractPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setTaskContractPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setTaskContractPreviewLoadingId(null);
    }
  }

  async function loadPlanPreview(artifactId: string) {
    setPlanPreviewLoadingId(artifactId);
    setPlanPreviewError(null);
    try {
      setPlanPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setPlanPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlanPreviewLoadingId(null);
    }
  }

  async function loadWorkspacePreview(artifactId: string) {
    setWorkspacePreviewLoadingId(artifactId);
    setWorkspacePreviewError(null);
    try {
      setWorkspacePreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setWorkspacePreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorkspacePreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <StrategyBriefPanel
        project={project}
        brief={strategyBrief}
        busy={busy}
        text={text}
        onAction={onStrategyAction}
        onSave={() => runAction(() => api(`/api/projects/${project.id}/approach/strategy-brief`, { method: "POST" }))}
      />
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/research-plan`, { method: "POST" });
              const artifactId = job.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchPlanPreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
          Research Plan
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/research-source-pack`, { method: "POST" });
              const artifactId = job.output.research_source_report_artifact_id ?? job.output.research_source_pack_artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchSourcePreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Library size={16} />}
          Source Pack
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/research-synthesis`, { method: "POST" });
              const artifactId =
                job.output.research_finding_synthesis_report_artifact_id ??
                job.output.research_finding_synthesis_artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchSynthesisPreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <GitBranch size={16} />}
          Synthesize Research
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/agent-task-plan`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({})
              });
              const artifactId = job.output.agent_task_contract_artifact_id ?? job.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadTaskContractPreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Plan Agent Task
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() =>
              api(`/api/projects/${project.id}/approach/research-briefs`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({})
              })
            )
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
          Research Brief
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() => api(`/api/projects/${project.id}/approach/ideas/generate`, { method: "POST" }))
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Lightbulb size={16} />}
          Generate Ideas
        </button>
      </div>
      <Panel title="Research Plans" icon={<Search size={18} />}>
        {researchPlanArtifacts.length ? (
          <Table
            headers={["Plan", "Queries", "Assets", "Network", "Created", "Actions"]}
            rows={researchPlanArtifacts.map((artifact) => [
              artifact.name,
              String(artifact.metadata.query_count ?? "-"),
              String(artifact.metadata.recommended_asset_count ?? "-"),
              String(artifact.metadata.network_default ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={researchPlanPreviewLoadingId === artifact.id}
                  onClick={() => void loadResearchPlanPreview(artifact.id)}
                  title="Preview research plan"
                >
                  {researchPlanPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download research plan">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Research plans will turn project context, evaluation constraints, quality gates, benchmark context, and library assets into controlled query candidates, Skill references, source policy, expected evidence, and report outputs." />
        )}
        {researchPlanPreviewError ? <div className="banner danger">{researchPlanPreviewError}</div> : null}
        {researchPlanPreview?.preview_available ? (
          <TranslatablePreview preview={researchPlanPreview} />
        ) : (
          <EmptyInline text={researchPlanPreview?.reason ?? "Generate or select a ResearchPlan to inspect controlled search candidates, Skill references, source policy, evidence expectations, and reporting requirements."} />
        )}
      </Panel>
      <Panel title="Research Source Packs" icon={<Library size={18} />}>
        {researchSourceArtifacts.length ? (
          <Table
            headers={["Type", "Queries", "Project Sources", "Library Sources", "Network", "Created", "Actions"]}
            rows={researchSourceArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.query_count ?? "-"),
              String(artifact.metadata.project_source_count ?? "-"),
              String(artifact.metadata.library_source_count ?? "-"),
              String(artifact.metadata.network_default ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={researchSourcePreviewLoadingId === artifact.id}
                  onClick={() => void loadResearchSourcePreview(artifact.id)}
                  title="Preview research source pack"
                >
                  {researchSourcePreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download research source pack">
                  <Download size={16} />
                </a>
                <button
                  className="icon-button"
                  disabled={busy || artifact.asset_type !== "research_source_pack"}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/research-source-packs/${artifact.id}/run-local-stub`, {
                        method: "POST"
                      });
                      const reportArtifactId = job.output.research_findings_report_artifact_id;
                      if (typeof reportArtifactId === "string") {
                        await loadResearchSourcePreview(reportArtifactId);
                      }
                      return job;
                    })
                  }
                  title="Run controlled research stub"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Research source packs will turn ResearchPlan query candidates, project artifacts, benchmark context, Skill assets, source policy, freshness expectations, and citation requirements into runner-ready evidence slots." />
        )}
        {researchSourcePreviewError ? <div className="banner danger">{researchSourcePreviewError}</div> : null}
        {researchSourcePreview?.preview_available ? (
          <TranslatablePreview preview={researchSourcePreview} />
        ) : (
          <EmptyInline text={researchSourcePreview?.reason ?? "Generate or select a Research Source Pack to inspect citation requirements, controlled queries, source policy, and runner handoff expectations."} />
        )}
      </Panel>
      <Panel title="Research Syntheses" icon={<GitBranch size={18} />}>
        {researchSynthesisArtifacts.length ? (
          <Table
            headers={["Type", "Findings", "Citations", "External", "Stub", "Created", "Actions"]}
            rows={researchSynthesisArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.finding_count ?? "-"),
              String(artifact.metadata.citation_count ?? "-"),
              String(artifact.metadata.external_network_accessed ?? "-"),
              String(artifact.metadata.has_only_stub_findings ?? "-"),
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={researchSynthesisPreviewLoadingId === artifact.id}
                  onClick={() => void loadResearchSynthesisPreview(artifact.id)}
                  title="Preview research synthesis"
                >
                  {researchSynthesisPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download research synthesis">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Research syntheses will consolidate controlled runner findings, citation audit state, follow-up requirements, and AgentTask handoff notes for flexible approach planning." />
        )}
        {researchSynthesisPreviewError ? <div className="banner danger">{researchSynthesisPreviewError}</div> : null}
        {researchSynthesisPreview?.preview_available ? (
          <TranslatablePreview preview={researchSynthesisPreview} />
        ) : (
          <EmptyInline text={researchSynthesisPreview?.reason ?? "Synthesize current source packs and runner findings to inspect citation audit status, open requirements, and handoff guidance."} />
        )}
      </Panel>
      <Panel title="Agent Task Contracts" icon={<ListChecks size={18} />}>
        {agentTaskContractArtifacts.length ? (
          <Table
            headers={["Task", "Dataset", "Spec", "Approaches", "Queries", "Assets", "Actions"]}
            rows={agentTaskContractArtifacts.map((artifact) => [
              String(artifact.metadata.task_id ?? artifact.name),
              String(artifact.metadata.dataset_snapshot_id ?? "-"),
              String(artifact.metadata.evaluation_spec_id ?? "-"),
              String(artifact.metadata.recommended_approach_count ?? "-"),
              String(artifact.metadata.research_query_count ?? "-"),
              String(artifact.metadata.recommended_asset_count ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={taskContractPreviewLoadingId === artifact.id}
                  onClick={() => void loadTaskContractPreview(artifact.id)}
                  title="Preview agent task contract"
                >
                  {taskContractPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download agent task contract">
                  <Download size={16} />
                </a>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/prepare-workspace`, {
                        method: "POST"
                      });
                      const workspaceArtifactId = job.output.agent_workspace_manifest_artifact_id ?? job.output.artifact_id;
                      if (typeof workspaceArtifactId === "string") {
                        await loadWorkspacePreview(workspaceArtifactId);
                      }
                      return job;
                    })
                  }
                  title="Prepare controlled workspace"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Layers size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/readiness-review`, {
                        method: "POST"
                      });
                      const reportArtifactId = job.output.agent_task_readiness_report_artifact_id ?? job.output.artifact_id;
                      if (typeof reportArtifactId === "string") {
                        await loadTaskContractPreview(reportArtifactId);
                      }
                      return job;
                    })
                  }
                  title="Review runner readiness"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-local-stub`, {
                        method: "POST"
                      });
                      const ingested = job.output.ingested_artifact_ids;
                      const reportArtifactId = Array.isArray(ingested) ? textField(ingested[0]) : null;
                      if (reportArtifactId) {
                        await loadTaskContractPreview(reportArtifactId);
                      }
                      return job;
                    })
                  }
                  title="Run local stub"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="AgentTaskContracts will combine dataset context, approved evaluation constraints, assumptions, Skill/library recommendations, research queries, reporting requirements, and artifact expectations for future runners." />
        )}
        {taskContractPreviewError ? <div className="banner danger">{taskContractPreviewError}</div> : null}
        {taskContractPreview?.preview_available ? (
          <TranslatablePreview preview={taskContractPreview} />
        ) : (
          <EmptyInline text={taskContractPreview?.reason ?? "Plan or select an AgentTaskContract to inspect the exact flexible runner contract before execution."} />
        )}
      </Panel>
      <Panel title="Research Briefs" icon={<FileText size={18} />}>
        {researchBriefs.length ? (
          <div className="stack">
            <Table
              headers={["Brief", "Status", "Sources", "Recommendations", "Artifact"]}
              rows={researchBriefs.map((brief) => [
                brief.title,
                brief.status,
                brief.sources.length,
                brief.recommended_approaches.length,
                brief.artifact_id ?? "-"
              ])}
            />
            {latestBrief ? <pre className="markdown-preview">{latestBrief.summary_md}</pre> : null}
          </div>
        ) : (
          <EmptyInline text="Research briefs will summarize project artifacts, evaluation constraints, Skill hooks, and future controlled web or literature search requirements before proposing approaches." />
        )}
      </Panel>
      <Panel title="Approach Candidates" icon={<Lightbulb size={18} />}>
        {ideas.length ? (
          <div className="card-grid">
            {ideas.map((idea) => (
              <div key={idea.id} className="mini-card">
                <div className="mini-card-title">{idea.title}</div>
                <div className="badge-row">
                  <span className="badge">{idea.status}</span>
                  <span className="badge muted">{idea.approach_type.replace(/_/g, " ")}</span>
                  <span className="badge risk">{idea.risk_level}</span>
                </div>
                <p>{idea.hypothesis}</p>
                <dl className="facts">
                  <div>
                    <dt>Confidence</dt>
                    <dd>{Math.round(idea.confidence * 100)}%</dd>
                  </div>
                  <div>
                    <dt>Priority</dt>
                    <dd>{idea.priority}</dd>
                  </div>
                  <div>
                    <dt>Research</dt>
                    <dd>{formatContractModes(idea)}</dd>
                  </div>
                  <div>
                    <dt>ResearchPlan</dt>
                    <dd>{formatContractResearchPlan(idea)}</dd>
                  </div>
                  <div>
                    <dt>Artifact</dt>
                    <dd>{idea.artifact_id ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>Context</dt>
                    <dd>{latestContextPackArtifact(artifacts, idea.id)?.id ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>Plan</dt>
                    <dd>{latestExperimentPlanArtifact(artifacts, idea.id)?.id ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>Workspace</dt>
                    <dd>{latestAgentWorkspaceArtifact(artifacts, idea.id)?.id ?? "-"}</dd>
                  </div>
                </dl>
                <pre className="compact-json">{truncateJson(idea.agent_task_contract)}</pre>
                <div className="button-row">
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() =>
                      void runAction(() => api(`/api/ideas/${idea.id}/prepare-agent-context`, { method: "POST" }))
                    }
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
                    Prepare Context
                  </button>
                  <button
                    className="icon-button"
                    disabled={!latestContextPackArtifact(artifacts, idea.id) || contextPreviewLoadingId === latestContextPackArtifact(artifacts, idea.id)?.id}
                    onClick={() => {
                      const contextArtifact = latestContextPackArtifact(artifacts, idea.id);
                      if (contextArtifact) void loadContextPreview(contextArtifact.id);
                    }}
                    title="Preview context pack"
                  >
                    {contextPreviewLoadingId === latestContextPackArtifact(artifacts, idea.id)?.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() =>
                      void runAction(() => api(`/api/ideas/${idea.id}/experiment-plan`, { method: "POST" }))
                    }
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                    Plan
                  </button>
                  <button
                    className="icon-button"
                    disabled={!latestExperimentPlanArtifact(artifacts, idea.id) || planPreviewLoadingId === latestExperimentPlanArtifact(artifacts, idea.id)?.id}
                    onClick={() => {
                      const planArtifact = latestExperimentPlanArtifact(artifacts, idea.id);
                      if (planArtifact) void loadPlanPreview(planArtifact.id);
                    }}
                    title="Preview experiment plan"
                  >
                    {planPreviewLoadingId === latestExperimentPlanArtifact(artifacts, idea.id)?.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() =>
                      void runAction(() => api(`/api/ideas/${idea.id}/run-agent-task`, { method: "POST" }))
                    }
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    Run Stub Task
                  </button>
                  <button
                    className="icon-button"
                    disabled={!latestAgentWorkspaceArtifact(artifacts, idea.id) || workspacePreviewLoadingId === latestAgentWorkspaceArtifact(artifacts, idea.id)?.id}
                    onClick={() => {
                      const workspaceArtifact = latestAgentWorkspaceArtifact(artifacts, idea.id);
                      if (workspaceArtifact) void loadWorkspacePreview(workspaceArtifact.id);
                    }}
                    title="Preview workspace manifest"
                  >
                    {workspacePreviewLoadingId === latestAgentWorkspaceArtifact(artifacts, idea.id)?.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text="Flexible candidate approaches will appear here as evidence-backed Ideas with AgentTaskContract payloads for Codex, Skills, and controlled research." />
        )}
      </Panel>
      <Panel title="Agent Context Pack Preview" icon={<FileText size={18} />}>
        {contextPreviewError ? <div className="banner danger">{contextPreviewError}</div> : null}
        {contextPreview?.preview_available ? (
          <TranslatablePreview preview={contextPreview} />
        ) : (
          <EmptyInline text={contextPreview?.reason ?? "Prepare and preview an AgentContextPack to inspect the exact harness-owned context before agent execution."} />
        )}
      </Panel>
      <Panel title="Experiment Plan Preview" icon={<ListChecks size={18} />}>
        {planPreviewError ? <div className="banner danger">{planPreviewError}</div> : null}
        {planPreview?.preview_available ? (
          <TranslatablePreview preview={planPreview} />
        ) : (
          <EmptyInline text={planPreview?.reason ?? "Create and preview an ExperimentPlan to inspect runner-ready approach choices, scenario comparisons, evaluation locks, and research governance."} />
        )}
      </Panel>
      <Panel title="Agent Workspace Preview" icon={<Layers size={18} />}>
        {workspacePreviewError ? <div className="banner danger">{workspacePreviewError}</div> : null}
        {workspacePreview?.preview_available ? (
          <TranslatablePreview preview={workspacePreview} />
        ) : (
          <EmptyInline text={workspacePreview?.reason ?? "Run the stub task to materialize a controlled workspace manifest with copied context, execution policy, and safety controls."} />
        )}
      </Panel>
    </div>
  );
}

function ExperimentsTab({
  project,
  jobs,
  runs,
  agentTaskResults,
  artifacts,
  busy,
  runAction
}: {
  project: Project;
  jobs: Job[];
  runs: Run[];
  agentTaskResults: AgentTaskResult[];
  artifacts: Artifact[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const experimentJobs = jobs.filter((job) =>
    [
      "plan_baseline_strategy",
      "plan_agent_task",
      "run_baseline",
      "run_public_benchmark_workflow",
      "run_agent_task",
      "create_experiment_plan",
      "compare_experiments",
      "draft_run_report"
    ].includes(job.job_type)
  );
  const experimentArtifacts = artifacts.filter((artifact) =>
    [
      "baseline_strategy_plan",
      "baseline_plan",
      "feature_recipe",
      "baseline_report",
      "baseline_metrics",
      "agent_task_contract",
      "agent_result",
      "agent_task_report",
      "source_citation_manifest",
      "citation_audit_report",
      "experiment_plan",
      "experiment_comparison",
      "experiment_comparison_report",
      "run_report"
    ].includes(artifact.asset_type)
  );
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);

  async function loadPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    try {
      setPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/baseline/strategy-plan`, { method: "POST" });
              const artifactId = job.output.baseline_strategy_plan_artifact_id;
              if (typeof artifactId === "string") {
                await loadPreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Plan Baseline
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/agent-task-plan`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({})
              });
              const artifactId = job.output.agent_task_contract_artifact_id ?? job.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadPreview(artifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Plan Agent Task
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api(`/api/projects/${project.id}/baseline/run`, { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          Run Baseline
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api(`/api/projects/${project.id}/experiments/compare`, { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
          Compare Runs
        </button>
      </div>
      <Panel title="Experiment Runs" icon={<Play size={18} />}>
        {runs.length ? (
          <Table
            headers={["Run", "Runner", "Status", "Model", "ModelVersion", "Features", "Primary Metric", "Spec", "Split", "Actions"]}
            rows={runs.map((run) => [
              run.id,
              run.runner_type,
              run.status,
              formatBaseline(run.metrics),
              run.model_version_id ?? "-",
              formatFeatureCount(run.metrics),
              formatMetric(run.metrics),
              run.evaluation_spec_id ?? "-",
              run.split_manifest_id ?? "-",
              <button
                className="icon-button"
                disabled={busy}
                key={run.id}
                onClick={() => void runAction(() => api(`/api/runs/${run.id}/report`, { method: "POST" }))}
                title="Draft run report"
              >
                {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
              </button>
            ])}
          />
        ) : (
          <EmptyInline text="Baseline runs, agent task runs, failed repair attempts, metrics, parameters, and linked artifacts will appear here." />
        )}
      </Panel>
      <Panel title="Agent Task Results" icon={<FileText size={18} />}>
        {agentTaskResults.length ? (
          <Table
            headers={["Job", "Source", "Agent", "Readiness", "Experiment", "Strategy", "Relational", "Citations", "Reports", "Actions"]}
            rows={agentTaskResults.map((result) => {
              const reportArtifact = result.artifacts.agent_task_report;
              const citationReportArtifact = result.artifacts.citation_audit_report;
              const manifestArtifact = result.artifacts.source_citation_manifest;
              const relationalArtifact = result.artifacts.relational_context_summary;
              const decisionTraceArtifact = result.artifacts.approach_decision_trace;
              return [
                <div className="cell-stack" key={`${result.job_id}-job`}>
                  <span>{result.job_type.replace(/_/g, " ")}</span>
                  <small>{formatDate(result.created_at)}</small>
                </div>,
                <div className="cell-stack" key={`${result.job_id}-source`}>
                  <span>{result.source.type.replace(/_/g, " ")}</span>
                  <small>{result.source.id ?? "-"}</small>
                </div>,
                <div className="cell-stack" key={`${result.job_id}-agent`}>
                  <span className={result.agent_status === "succeeded" ? "badge" : "badge risk"}>
                    {result.agent_status ?? result.job_status}
                  </span>
                  <small>{result.requires_human_review ? "human review" : "review not required"}</small>
                </div>,
                result.readiness_status ?? "-",
                result.experiment_run?.id ?? "-",
                <div className="cell-stack" key={`${result.job_id}-strategy`}>
                  <span className="badge">{result.approach_decision_trace.policy ?? "open ended"}</span>
                  <small>
                    {result.approach_decision_trace.approach_considered_count} considered / {result.approach_decision_trace.deferred_or_rejected_count} deferred
                  </small>
                </div>,
                <div className="cell-stack" key={`${result.job_id}-relational`}>
                  <span className={result.relational_context.source_count ? "badge" : "badge muted"}>
                    {result.relational_context.source_count} context files
                  </span>
                  <small>
                    {result.relational_context.usable_feature_count} usable / {result.relational_context.deferred_safety_check_count} checks
                  </small>
                </div>,
                <div className="cell-stack" key={`${result.job_id}-citations`}>
                  <span>
                    {result.citation_audit.source_count} sources / {result.citation_audit.citation_count} citations
                  </span>
                  <small>
                    {result.citation_audit.external_network_accessed ? "external access recorded" : "network off"}
                  </small>
                </div>,
                <div className="cell-stack" key={`${result.job_id}-reports`}>
                  <span>{result.reports.agent_task_report?.id ?? "-"}</span>
                  <small>{result.reports.citation_audit_report?.id ?? "no citation report"}</small>
                </div>,
                <div className="row-actions" key={`${result.job_id}-actions`}>
                  <button
                    className="icon-button"
                    disabled={!reportArtifact || previewLoadingId === reportArtifact.id}
                    onClick={() => {
                      if (reportArtifact) void loadPreview(reportArtifact.id);
                    }}
                    title="Preview agent task report"
                  >
                    {reportArtifact && previewLoadingId === reportArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <FileText size={16} />
                    )}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!citationReportArtifact || previewLoadingId === citationReportArtifact.id}
                    onClick={() => {
                      if (citationReportArtifact) void loadPreview(citationReportArtifact.id);
                    }}
                    title="Preview citation audit report"
                  >
                    {citationReportArtifact && previewLoadingId === citationReportArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!manifestArtifact || previewLoadingId === manifestArtifact.id}
                    onClick={() => {
                      if (manifestArtifact) void loadPreview(manifestArtifact.id);
                    }}
                    title="Preview source citation manifest"
                  >
                    {manifestArtifact && previewLoadingId === manifestArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <ListChecks size={16} />
                    )}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!decisionTraceArtifact || previewLoadingId === decisionTraceArtifact.id}
                    onClick={() => {
                      if (decisionTraceArtifact) void loadPreview(decisionTraceArtifact.id);
                    }}
                    title="Preview approach decision trace"
                  >
                    {decisionTraceArtifact && previewLoadingId === decisionTraceArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Lightbulb size={16} />
                    )}
                  </button>
                  <button
                    className="icon-button"
                    disabled={!relationalArtifact || previewLoadingId === relationalArtifact.id}
                    onClick={() => {
                      if (relationalArtifact) void loadPreview(relationalArtifact.id);
                    }}
                    title="Preview relational context summary"
                  >
                    {relationalArtifact && previewLoadingId === relationalArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Layers size={16} />
                    )}
                  </button>
                  {manifestArtifact ? (
                    <a
                      className="icon-link"
                      href={`${apiBase}/api/artifacts/${manifestArtifact.id}/download`}
                      title="Download source citation manifest"
                    >
                      <Download size={16} />
                    </a>
                  ) : null}
                  {decisionTraceArtifact ? (
                    <a
                      className="icon-link"
                      href={`${apiBase}/api/artifacts/${decisionTraceArtifact.id}/download`}
                      title="Download approach decision trace"
                    >
                      <Download size={16} />
                    </a>
                  ) : null}
                  {relationalArtifact ? (
                    <a
                      className="icon-link"
                      href={`${apiBase}/api/artifacts/${relationalArtifact.id}/download`}
                      title="Download relational context summary"
                    >
                      <Download size={16} />
                    </a>
                  ) : null}
                </div>
              ];
            })}
          />
        ) : (
          <EmptyInline text="Agent task outputs, experiment registrations, citation audits, reports, and workspace/readiness artifacts will appear here after a planned or Idea-backed runner task completes." />
        )}
      </Panel>
      <Panel title="Experiment Lifecycle Artifacts" icon={<ListChecks size={18} />}>
        {experimentArtifacts.length ? (
          <Table
            headers={["Type", "Name", "Version", "Strategy", "Source", "Actions"]}
            rows={experimentArtifacts.map((artifact) => [
              artifact.asset_type,
              artifact.name,
              `v${artifact.version}`,
              formatStrategyArtifact(artifact),
              String(artifact.metadata.run_id ?? artifact.metadata.idea_id ?? artifact.metadata.best_run_id ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadPreview(artifact.id)}
                  title="Preview experiment artifact"
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download experiment artifact">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Experiment plans, run reports, comparison artifacts, and comparison reports will appear here as the agentic experiment loop progresses." />
        )}
      </Panel>
      <Panel title="Experiment Artifact Preview" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {preview?.preview_available ? (
          <TranslatablePreview preview={preview} />
        ) : (
          <EmptyInline text={preview?.reason ?? "Select an experiment lifecycle artifact to inspect plans, run reports, or comparisons inside the workbench."} />
        )}
      </Panel>
      <Panel title="Recent Experiment Jobs" icon={<ListChecks size={18} />}>
        {experimentJobs.length ? (
          <Table headers={["Job", "Status", "Output"]} rows={experimentJobs.map((job) => [job.job_type, job.status, JSON.stringify(job.output)])} />
        ) : (
          <EmptyInline text="Baseline and agent task job status will appear here." />
        )}
      </Panel>
    </div>
  );
}

function ReportsTab({
  project,
  reports,
  artifacts,
  visualizations,
  insights,
  busy,
  runAction
}: {
  project: Project;
  reports: Report[];
  artifacts: Artifact[];
  visualizations: VisualizationSpec[];
  insights: Insight[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [reportPreview, setReportPreview] = React.useState<ArtifactPreview | null>(null);
  const [reportPreviewSource, setReportPreviewSource] = React.useState<{ type: "report" | "artifact"; id: string } | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const decisionArtifacts = artifacts.filter((artifact) =>
    ["decision_dashboard", "decision_report"].includes(artifact.asset_type)
  );

  async function loadReportPreview(reportId: string) {
    setPreviewLoadingId(reportId);
    setPreviewError(null);
    try {
      setReportPreview(await api<ArtifactPreview>(`/api/reports/${reportId}/preview`));
      setReportPreviewSource({ type: "report", id: reportId });
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  async function loadArtifactPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    try {
      setReportPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
      setReportPreviewSource({ type: "artifact", id: artifactId });
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() =>
              api(`/api/projects/${project.id}/reports/draft`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ report_type: "project_summary" })
              })
            )
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
          Draft Report
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() => api(`/api/projects/${project.id}/visualizations/generate`, { method: "POST" }))
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
          Visualization Dashboard
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() => api(`/api/projects/${project.id}/insights/generate`, { method: "POST" }))
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Lightbulb size={16} />}
          Generate Insights
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/decision-dashboard/generate`, { method: "POST" });
              const reportId = job.output.report_id;
              if (typeof reportId === "string") {
                await loadReportPreview(reportId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Decision Dashboard
        </button>
      </div>
      <Panel title="Insights" icon={<Lightbulb size={18} />}>
        {insights.length ? (
          <div className="card-grid">
            {insights.map((insight) => (
              <div key={insight.id} className="mini-card insight-card">
                <div className="mini-card-title">{insight.title}</div>
                <div className="badge-row">
                  <span className="badge">{insight.status}</span>
                  <span className="badge muted">{insight.insight_type.replace(/_/g, " ")}</span>
                  <span className="badge risk">{insight.severity}</span>
                </div>
                <p>{insight.summary}</p>
                <dl className="facts">
                  <div>
                    <dt>Confidence</dt>
                    <dd>{Math.round(insight.confidence * 100)}%</dd>
                  </div>
                  <div>
                    <dt>Sources</dt>
                    <dd>{insight.source_asset_ids.length}</dd>
                  </div>
                  <div>
                    <dt>Evidence</dt>
                    <dd>{insight.evidence_ids.length}</dd>
                  </div>
                  <div>
                    <dt>Artifact</dt>
                    <dd>{insight.artifact_id}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text="Generated insights will summarize data readiness, assumption risk, evaluation readiness, approach progress, and experiment signals with evidence and lineage." />
        )}
      </Panel>
      <Panel title="Reports" icon={<FileText size={18} />}>
        {reports.length ? (
          <Table
            headers={["Title", "Type", "Status", "Artifact", "Created", "Actions"]}
            rows={reports.map((report) => [
              report.title,
              report.report_type,
              report.status,
              report.artifact_id,
              formatDate(report.created_at),
              <div className="row-actions" key={report.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === report.id}
                  onClick={() => void loadReportPreview(report.id)}
                  title="Preview report"
                >
                  {previewLoadingId === report.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/reports/${report.id}/download`} title="Download report">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Project reports will summarize data understanding, assumptions, evaluation design, approach candidates, runs, visualizations, and next decisions." />
        )}
      </Panel>
      <Panel title="Decision Artifacts" icon={<ListChecks size={18} />}>
        {decisionArtifacts.length ? (
          <Table
            headers={["Type", "Status", "Risks", "Questions", "Artifact", "Actions"]}
            rows={decisionArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.readiness_status ?? "-"),
              String(artifact.metadata.high_risk_assumption_count ?? "-"),
              String(artifact.metadata.open_question_count ?? "-"),
              artifact.id,
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadArtifactPreview(artifact.id)}
                  title="Preview decision artifact"
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download decision artifact">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Decision dashboard artifacts will summarize readiness stages, artifact completeness, risks, next actions, benchmark fixture policy, and visualization specs." />
        )}
      </Panel>
      <Panel title="Report Preview" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {reportPreview?.preview_available ? (
          <TranslatablePreview
            preview={reportPreview}
            sourceType={reportPreviewSource?.type ?? "artifact"}
            sourceId={reportPreviewSource?.id ?? reportPreview.id}
          />
        ) : (
          <EmptyInline text={reportPreview?.reason ?? "Select a report preview action to inspect the Markdown report inside the workbench."} />
        )}
      </Panel>
      <Panel title="Visualization Dashboard" icon={<BarChart3 size={18} />}>
        {visualizations.length ? (
          <div className="stack">
            <Table
              headers={["Title", "Type", "Status", "Rows", "Artifact"]}
              rows={visualizations.map((visualization) => [
                visualization.title,
                visualization.chart_type,
                visualization.status,
                visualizationDataRows(visualization).length,
                visualization.artifact_id
              ])}
            />
            <div className="viz-grid">
              {visualizations.slice(0, 6).map((visualization) => (
                <div key={visualization.id} className="viz-card">
                  <div className="mini-card-title">{visualization.title}</div>
                  <VisualizationPreview visualization={visualization} />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyInline text="Portable visualization specs for leaderboard, diagnostics, slices, and report figures will appear here." />
        )}
      </Panel>
    </div>
  );
}

function VisualizationPreview({ visualization }: { visualization: VisualizationSpec }) {
  if (visualization.chart_type === "metric_cards") {
    const rows = visualizationDataRows(visualization);
    if (!rows.length) return <EmptyInline text={visualizationEmptyState(visualization)} />;
    return (
      <div className="metric-grid compact">
        {rows.map((row, index) => (
          <Metric
            key={`${String(row.label ?? "metric")}-${index}`}
            label={String(row.label ?? "Metric")}
            value={formatVizValue(row.value)}
          />
        ))}
      </div>
    );
  }

  if (visualization.chart_type === "category_bars") {
    return <BarVisualization visualization={visualization} fallbackLabelField="label" fallbackValueField="count" />;
  }

  if (visualization.chart_type === "stage_status") {
    const rows = visualizationDataRows(visualization);
    if (!rows.length) return <EmptyInline text={visualizationEmptyState(visualization)} />;
    return (
      <Table
        headers={["Stage", "Status", "Count", "Detail"]}
        rows={rows.map((row) => [
          String(row.stage ?? "-"),
          <span className={String(row.status) === "ready" ? "badge" : "badge risk"} key={String(row.stage)}>
            {String(row.status ?? "-")}
          </span>,
          String(row.count ?? "-"),
          String(row.detail ?? "-")
        ])}
      />
    );
  }

  if (visualization.chart_type === "artifact_checklist") {
    const rows = visualizationDataRows(visualization);
    if (!rows.length) return <EmptyInline text={visualizationEmptyState(visualization)} />;
    return (
      <Table
        headers={["Output", "Schema", "Status"]}
        rows={rows.map((row) => [
          String(row.path ?? "-"),
          String(row.schema ?? "-"),
          <span className={String(row.status) === "planned" ? "badge muted" : "badge"} key={String(row.path)}>
            {String(row.status ?? "-")}
          </span>
        ])}
      />
    );
  }

  if (hasBarEncoding(visualization)) {
    return <BarVisualization visualization={visualization} fallbackLabelField="run_id" fallbackValueField="primary_metric_value" />;
  }

  const rows = visualizationDataRows(visualization);
  if (!rows.length) return <EmptyInline text={visualizationEmptyState(visualization)} />;
  return (
    <Table
      headers={Object.keys(rows[0]).slice(0, 4)}
      rows={rows.slice(0, 8).map((row) => Object.keys(rows[0]).slice(0, 4).map((key) => formatVizValue(row[key])))}
    />
  );
}

function BarVisualization({
  visualization,
  fallbackLabelField,
  fallbackValueField
}: {
  visualization: VisualizationSpec;
  fallbackLabelField: string;
  fallbackValueField: string;
}) {
  const rows = visualizationDataRows(visualization);
  const encoding = visualizationEncoding(visualization);
  const labelField = encodingField(encoding.x, fallbackLabelField);
  const valueField = encodingField(encoding.y, fallbackValueField);
  const colorField = encodingField(encoding.color, "");
  const values = rows.map((row) => numberValue(row[valueField])).filter((value): value is number => value !== null);
  const maxValue = Math.max(...values.map((value) => Math.abs(value)), 0);
  if (!rows.length || maxValue <= 0) return <EmptyInline text={visualizationEmptyState(visualization)} />;
  return (
    <div className="viz-preview">
      {rows.map((row, index) => {
        const label = String(row[labelField] ?? row.label ?? row.run_id ?? row.stage ?? `row ${index + 1}`);
        const value = numberValue(row[valueField]) ?? 0;
        const width = maxValue > 0 ? Math.max(4, (Math.abs(value) / maxValue) * 100) : 4;
        const colorValue = colorField ? row[colorField] : null;
        return (
          <div key={`${label}-${index}`} className="viz-row">
            <div className="viz-label">
              <span>{label}</span>
              {colorValue != null ? <small>{String(colorValue)}</small> : null}
            </div>
            <div className="viz-bar-track">
              <div className="viz-bar" style={{ width: `${width}%` }} />
            </div>
            <div className="viz-value">{formatVizValue(value)}</div>
          </div>
        );
      })}
    </div>
  );
}

function LeaderboardTab({
  specs,
  artifacts,
  leaderboard,
  busy,
  runAction
}: {
  specs: EvaluationSpec[];
  artifacts: Artifact[];
  leaderboard: LeaderboardEntry[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const splitManifests = artifacts.filter((artifact) => artifact.asset_type === "split_manifest");
  const diagnosticArtifacts = artifacts.filter((artifact) =>
    ["evaluation_diagnostics", "evaluation_diagnostics_report"].includes(artifact.asset_type)
  );
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);

  async function loadPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    try {
      setPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <Panel title="Leaderboard" icon={<BarChart3 size={18} />}>
        {leaderboard.length ? (
          <Table
            headers={["Rank", "Run", "Runner", "Model", "ModelVersion", "Metric", "Value", "Spec", "Split", "Actions"]}
            rows={leaderboard.map((entry) => [
              entry.rank,
              entry.run_id,
              entry.runner_type,
              formatBaseline(entry.metrics),
              entry.model_version_id ?? "-",
              entry.primary_metric_name ?? "-",
              entry.primary_metric_value == null ? "-" : entry.primary_metric_value.toFixed(6),
              entry.evaluation_spec_id ?? "-",
              entry.split_manifest_id ?? "-",
              <button
                className="icon-button"
                disabled={busy}
                key={entry.run_id}
                onClick={() => void runAction(() => api(`/api/runs/${entry.run_id}/diagnostics`, { method: "POST" }))}
                title="Analyze evaluation diagnostics"
              >
                {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
              </button>
            ])}
          />
        ) : (
          <EmptyInline text="Runs will be ranked here with primary metric, secondary metrics, evaluation spec version, split manifest version, and decision status." />
        )}
      </Panel>
      <Panel title="Evaluation Context" icon={<Layers size={18} />}>
        <Table
          headers={["Approved Specs", "Split Manifests"]}
          rows={[[specs.filter((spec) => spec.status === "approved").length, splitManifests.length]]}
        />
      </Panel>
      <Panel title="Evaluation Diagnostics" icon={<ListChecks size={18} />}>
        {diagnosticArtifacts.length ? (
          <Table
            headers={["Type", "Name", "Version", "Run", "Actions"]}
            rows={diagnosticArtifacts.map((artifact) => [
              artifact.asset_type,
              artifact.name,
              `v${artifact.version}`,
              String(artifact.metadata.run_id ?? "-"),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadPreview(artifact.id)}
                  title="Preview diagnostics"
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a
                  className="icon-link"
                  href={`${apiBase}/api/artifacts/${artifact.id}/download`}
                  title="Download diagnostics"
                >
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Evaluation diagnostics, slice metrics, error bins, worst examples, and split sanity checks will appear here after analyzing a run." />
        )}
      </Panel>
      <Panel title="Diagnostics Preview" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {preview?.preview_available ? (
          <TranslatablePreview preview={preview} />
        ) : (
          <EmptyInline text={preview?.reason ?? "Select a diagnostics artifact to preview JSON or Markdown inside the workbench."} />
        )}
      </Panel>
    </div>
  );
}

function formatMetric(metrics: Record<string, unknown>) {
  const name = metrics.primary_metric_name;
  const value = metrics.primary_metric_value;
  if (typeof name !== "string" || typeof value !== "number") return "-";
  return `${name}: ${value.toFixed(6)}`;
}

function formatJobSummaryMetric(summary: Record<string, unknown>) {
  const name = summary.primary_metric_name;
  const value = summary.primary_metric_value;
  if (typeof name !== "string" || typeof value !== "number") return "-";
  return `${name}: ${value.toFixed(6)}`;
}

function formatAgentTaskPlanningSummary(summary: Record<string, unknown>) {
  const approaches = summary.recommended_approach_count;
  const queries = summary.research_query_count;
  const assets = summary.recommended_asset_count;
  const contexts = summary.materialized_context_count;
  const libraryAssets = summary.materialized_library_asset_count;
  const readiness = summary.readiness_status;
  const blockers = summary.blocker_count;
  const warnings = summary.warning_count;
  const parts = [
    typeof approaches === "number" ? `${approaches} approaches` : null,
    typeof queries === "number" ? `${queries} queries` : null,
    typeof assets === "number" ? `${assets} assets` : null,
    typeof contexts === "number" ? `${contexts} ctx` : null,
    typeof libraryAssets === "number" ? `${libraryAssets} library` : null,
    typeof readiness === "string" ? readiness.replace(/_/g, " ") : null,
    typeof blockers === "number" || typeof warnings === "number"
      ? `${typeof blockers === "number" ? blockers : 0} blockers / ${typeof warnings === "number" ? warnings : 0} warnings`
      : null
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "-";
}

function formatBaseline(metrics: Record<string, unknown>) {
  const baselineType = metrics.baseline_type;
  if (typeof baselineType !== "string") return "-";
  return baselineType.replace(/_/g, " ");
}

function formatFeatureCount(metrics: Record<string, unknown>) {
  const featureCount = metrics.feature_count;
  if (typeof featureCount !== "number") return "-";
  return featureCount.toString();
}

function formatStrategyArtifact(artifact: Artifact) {
  const mode = textField(artifact.metadata.strategy_mode);
  const planningSource = textField(artifact.metadata.planning_source);
  const resourceGuard = textField(artifact.metadata.resource_guard_level);
  const assetCount = artifact.metadata.matched_asset_count;
  const agentTaskCount = artifact.metadata.agent_task_count;
  const parts = [
    mode ? mode.replace(/_/g, " ") : null,
    planningSource ? planningSource.replace(/_/g, " ") : null,
    resourceGuard ? resourceGuard.replace(/_/g, " ") : null,
    typeof assetCount === "number" ? `${assetCount} assets` : null,
    typeof agentTaskCount === "number" && agentTaskCount > 0 ? `${agentTaskCount} agent tasks` : null
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "-";
}

function formatContractModes(idea: Idea) {
  const inputs = idea.agent_task_contract.inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) return "-";
  const modes = (inputs as Record<string, unknown>).allowed_research_modes;
  if (!Array.isArray(modes)) return "-";
  return modes.map(String).join(", ");
}

function formatContractResearchPlan(idea: Idea) {
  const inputs = idea.agent_task_contract.inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) return "-";
  const artifactId = (inputs as Record<string, unknown>).research_plan_artifact_id;
  return typeof artifactId === "string" && artifactId.length ? artifactId : "-";
}

function latestContextPackArtifact(artifacts: Artifact[], ideaId: string) {
  return latestIdeaArtifact(artifacts, ideaId, "agent_context_pack");
}

function latestExperimentPlanArtifact(artifacts: Artifact[], ideaId: string) {
  return latestIdeaArtifact(artifacts, ideaId, "experiment_plan");
}

function latestAgentWorkspaceArtifact(artifacts: Artifact[], ideaId: string) {
  return latestIdeaArtifact(artifacts, ideaId, "agent_workspace_manifest");
}

function latestIdeaArtifact(artifacts: Artifact[], ideaId: string, assetType: string) {
  return artifacts.find((artifact) => {
    const metadataIdeaId = artifact.metadata.idea_id;
    return artifact.asset_type === assetType && metadataIdeaId === ideaId;
  });
}

function visualizationDataRows(visualization: VisualizationSpec): Array<Record<string, unknown>> {
  const rows = visualization.spec.data;
  if (!Array.isArray(rows)) return [];
  return rows.filter(
    (row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row)
  );
}

function visualizationEmptyState(visualization: VisualizationSpec) {
  const emptyState = visualization.spec.empty_state;
  return typeof emptyState === "string"
    ? emptyState
    : "Visualization spec is ready; run more workflow steps to render this view.";
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function visualizationEncoding(visualization: VisualizationSpec): Record<string, unknown> {
  const encoding = visualization.spec.encoding;
  return encoding && typeof encoding === "object" && !Array.isArray(encoding) ? (encoding as Record<string, unknown>) : {};
}

function encodingField(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function hasBarEncoding(visualization: VisualizationSpec) {
  const encoding = visualizationEncoding(visualization);
  return typeof encoding.x === "string" && typeof encoding.y === "string";
}

function formatVizValue(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(4);
  if (typeof value === "string") return value;
  return "-";
}

function AssetsTab({
  artifacts,
  modelVersions,
  validationsByModelVersion,
  busy,
  runAction
}: {
  artifacts: Artifact[];
  modelVersions: ModelVersion[];
  validationsByModelVersion: Record<string, ModelValidation[]>;
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const validationRows = modelVersions.flatMap((modelVersion) =>
    (validationsByModelVersion[modelVersion.id] ?? []).map((validation) => ({
      modelVersion,
      validation
    }))
  );

  async function loadPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    try {
      setPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  return (
    <div className="stack">
      <Panel title="Model Versions" icon={<Layers size={18} />}>
        {modelVersions.length ? (
          <Table
            headers={["Name", "Version", "Type", "Metric", "Latest Validation", "Package", "Actions"]}
            rows={modelVersions.map((modelVersion) => {
              const latestValidation = getLatestValidation(validationsByModelVersion[modelVersion.id] ?? []);
              return [
                modelVersion.name,
                `v${modelVersion.version}`,
                modelVersion.model_type.replace(/_/g, " "),
                formatModelMetric(modelVersion),
                formatValidationSummary(latestValidation),
                modelVersion.artifact_id,
                <button
                  className="icon-button"
                  disabled={busy}
                  key={modelVersion.id}
                  onClick={() =>
                    void runAction(() =>
                      api(`/api/model-versions/${modelVersion.id}/validate`, { method: "POST" })
                    )
                  }
                  title="Validate model package replay"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                </button>
              ];
            })}
          />
        ) : (
          <EmptyInline text="Trained model versions, package artifacts, evaluation context, and selected metrics will appear here." />
        )}
      </Panel>
      <Panel title="Model Package Validation History" icon={<ListChecks size={18} />}>
        {validationRows.length ? (
          <Table
            headers={["ModelVersion", "Job", "Status", "Max Delta", "Artifacts", "Ended"]}
            rows={validationRows.map(({ modelVersion, validation }) => [
              `${modelVersion.name} v${modelVersion.version}`,
              validation.job.id,
              validation.validation_status ?? validation.job.status,
              formatDelta(validation.max_abs_metric_delta),
              validation.artifacts.map((artifact) => `${artifact.asset_type}:${artifact.id}`).join(", ") || "-",
              formatDate(validation.ended_at)
            ])}
          />
        ) : (
          <EmptyInline text="Model package replay validations will appear here with metric deltas, replay prediction artifacts, and validation reports." />
        )}
      </Panel>
      <Panel title="Project Assets" icon={<Library size={18} />}>
        {artifacts.length ? (
          <Table
            headers={["Type", "Name", "Version", "Size", "Actions"]}
            rows={artifacts.map((artifact) => [
              artifact.asset_type,
              artifact.name,
              `v${artifact.version}`,
              formatBytes(artifact.size_bytes),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadPreview(artifact.id)}
                  title="Preview artifact"
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a
                  className="icon-link"
                  href={`${apiBase}/api/artifacts/${artifact.id}/download`}
                  title="Download artifact"
                >
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Project artifacts and cross-project asset references for Skills, EvaluationPatterns, PromptTemplates, and VisualizationTemplates will appear here." />
        )}
      </Panel>
      <Panel title="Artifact Preview" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {preview ? (
          preview.preview_available ? (
            <div className="preview-block">
              <div className="preview-meta">
                <span className="badge">{preview.content_type}</span>
                <span className="badge muted">{formatBytes(preview.size_bytes)}</span>
                {preview.truncated ? <span className="badge risk">truncated</span> : null}
              </div>
              <TranslatablePreview preview={preview} />
            </div>
          ) : (
            <EmptyInline text={preview.reason ?? "Preview is not available for this artifact."} />
          )
        ) : (
          <EmptyInline text="Select an artifact preview action to inspect JSON, Markdown, CSV, or text outputs without leaving the workbench." />
        )}
      </Panel>
    </div>
  );
}

function formatModelMetric(modelVersion: ModelVersion) {
  if (!modelVersion.primary_metric_name || modelVersion.primary_metric_value == null) return "-";
  return `${modelVersion.primary_metric_name}: ${modelVersion.primary_metric_value.toFixed(6)}`;
}

function JobsTab({
  jobs,
  busy,
  runAction
}: {
  jobs: Job[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [jobArtifacts, setJobArtifacts] = React.useState<JobArtifactsResponse | null>(null);
  const [artifactPreview, setArtifactPreview] = React.useState<ArtifactPreview | null>(null);
  const [artifactError, setArtifactError] = React.useState<string | null>(null);
  const [loadingJobId, setLoadingJobId] = React.useState<string | null>(null);
  const [loadingArtifactId, setLoadingArtifactId] = React.useState<string | null>(null);

  async function loadJobArtifacts(jobId: string) {
    setLoadingJobId(jobId);
    setArtifactError(null);
    try {
      setJobArtifacts(await api<JobArtifactsResponse>(`/api/jobs/${jobId}/artifacts`));
      setArtifactPreview(null);
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingJobId(null);
    }
  }

  async function loadArtifactPreview(artifactId: string) {
    setLoadingArtifactId(artifactId);
    setArtifactError(null);
    try {
      setArtifactPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
    } catch (err) {
      setArtifactError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingArtifactId(null);
    }
  }

  return (
    <div className="stack">
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api("/api/worker/run-once", { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          Run Worker Once
        </button>
      </div>
      <Panel title="Job History" icon={<ListChecks size={18} />}>
        {jobs.length ? (
          <Table
            headers={["Job", "Type", "Status", "Attempts", "Priority", "Started", "Ended", "Actions"]}
            rows={jobs.map((job) => [
              job.id,
              job.job_type,
              formatJobStatus(job),
              `${job.attempt_count}/${job.max_attempts}`,
              job.priority,
              formatDate(job.started_at),
              formatDate(job.ended_at),
              <div className="row-actions" key={job.id}>
                <button
                  className="icon-button"
                  disabled={busy || job.status !== "approval_required"}
                  onClick={() => void runAction(() => api(`/api/jobs/${job.id}/approve`, { method: "POST" }))}
                  title="Approve job"
                >
                  <Check size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || isTerminalJob(job)}
                  onClick={() => void runAction(() => api(`/api/jobs/${job.id}/cancel`, { method: "POST" }))}
                  title="Cancel job"
                >
                  <AlertTriangle size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || !canRetryJob(job)}
                  onClick={() => void runAction(() => api(`/api/jobs/${job.id}/retry`, { method: "POST" }))}
                  title="Retry job"
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={loadingJobId === job.id}
                  onClick={() => void loadJobArtifacts(job.id)}
                  title="Inspect job artifacts"
                >
                  {loadingJobId === job.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Profiling, assumption inference, evaluation design, split generation, baseline, validation, agent task, and queued worker jobs will appear here." />
        )}
      </Panel>
      <Panel title="Job Detail Context" icon={<FileText size={18} />}>
        {jobs.length ? (
          <Table
            headers={["Job", "Dependencies", "Policy", "Input", "Output"]}
            rows={jobs.slice(0, 8).map((job) => [
              job.id,
              job.dependency_job_ids.join(", ") || "-",
              truncateJson(job.policy),
              truncateJson(job.input),
              job.error_message ? job.error_message : truncateJson(job.output)
            ])}
          />
        ) : (
          <EmptyInline text="Queued jobs will expose dependency, policy, input, and output context here." />
        )}
      </Panel>
      <Panel title="Job Result Artifacts" icon={<Layers size={18} />}>
        {artifactError ? <div className="banner danger">{artifactError}</div> : null}
        {jobArtifacts ? (
          <div className="stack">
            <Table
              headers={["Job", "Benchmark", "Task", "Run", "Model", "Metric", "Plan", "Artifacts", "Missing"]}
              rows={[
                [
                  jobArtifacts.job.id,
                  String(jobArtifacts.summary.benchmark_id ?? "-"),
                  String(jobArtifacts.summary.task_id ?? "-"),
                  String(jobArtifacts.summary.experiment_run_id ?? "-"),
                  String(jobArtifacts.summary.model_version_id ?? "-"),
                  formatJobSummaryMetric(jobArtifacts.summary),
                  formatAgentTaskPlanningSummary(jobArtifacts.summary),
                  String(jobArtifacts.artifacts.length),
                  String(jobArtifacts.missing_artifact_ids.length)
                ]
              ]}
            />
            {jobArtifacts.artifacts.length ? (
              <Table
                headers={["Type", "Name", "Version", "Size", "Actions"]}
                rows={jobArtifacts.artifacts.map((artifact) => [
                  artifact.asset_type,
                  artifact.name,
                  `v${artifact.version}`,
                  formatBytes(artifact.size_bytes),
                  <div className="row-actions" key={artifact.id}>
                    <button
                      className="icon-button"
                      disabled={loadingArtifactId === artifact.id}
                      onClick={() => void loadArtifactPreview(artifact.id)}
                      title="Preview artifact"
                    >
                      {loadingArtifactId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                    </button>
                    <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download artifact">
                      <Download size={16} />
                    </a>
                  </div>
                ])}
              />
            ) : (
              <EmptyInline text="This job has no artifact ids in its output." />
            )}
            {artifactPreview?.preview_available ? (
              <TranslatablePreview preview={artifactPreview} />
            ) : (
              <EmptyInline text={artifactPreview?.reason ?? "Select an artifact to preview its text, JSON, Markdown, or CSV content."} />
            )}
          </div>
        ) : (
          <EmptyInline text="Inspect a completed workflow job to see produced artifacts, reports, metrics, and downloads without reading raw JSON." />
        )}
      </Panel>
    </div>
  );
}

function formatJobStatus(job: Job) {
  const status = job.error_message ? `${job.status}: ${job.error_message}` : job.status;
  if (job.approval_required && job.status === "queued") return `${status} / approved`;
  if (job.approval_required) return `${status} / approval required`;
  return status;
}

function formatWorkflowState(value: string | null) {
  if (!value) return "-";
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function isTerminalJob(job: Job) {
  return ["succeeded", "failed", "cancelled", "timed_out"].includes(job.status);
}

function canRetryJob(job: Job) {
  return ["failed", "cancelled", "timed_out"].includes(job.status) && job.attempt_count < job.max_attempts;
}

function LibraryTab({
  project,
  assets,
  references,
  busy,
  runAction
}: {
  project: Project;
  assets: LibraryAsset[];
  references: AssetReference[];
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const referencedAssetIds = new Set(references.map((reference) => reference.target_asset_id));
  return (
    <div className="stack">
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api("/api/assets/seed-defaults", { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Library size={16} />}
          Seed Library
        </button>
      </div>
      <Panel title="Cross-project Asset Library" icon={<Library size={18} />}>
        {assets.length ? (
          <Table
            headers={["Type", "Name", "Tags", "Semantic", "Latest Version", "Status", "Actions"]}
            rows={assets.map((asset) => [
              asset.asset_type.replace(/_/g, " "),
              asset.name,
              asset.tags.join(", ") || "-",
              asset.semantic_tags.slice(0, 5).join(", ") || "-",
              asset.latest_version_id ?? "-",
              referencedAssetIds.has(asset.id) ? "referenced" : asset.status,
              <button
                className="icon-button"
                disabled={busy || !asset.latest_version_id || referencedAssetIds.has(asset.id)}
                key={asset.id}
                onClick={() =>
                  void runAction(() =>
                    api(`/api/projects/${project.id}/asset-references`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        target_asset_id: asset.id,
                        target_asset_version_id: asset.latest_version_id,
                        relation_type: "uses"
                      })
                    })
                  )
                }
                title="Reference from project"
              >
                <Plus size={16} />
              </button>
            ])}
          />
        ) : (
          <EmptyInline text="Reusable Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates will appear here after seeding or registration." />
        )}
      </Panel>
      <Panel title="Project Asset References" icon={<GitBranch size={18} />}>
        {references.length ? (
          <Table
            headers={["Asset", "Type", "Relation", "Locked", "Version"]}
            rows={references.map((reference) => [
              reference.asset?.name ?? reference.target_asset_id,
              reference.asset?.asset_type ?? "-",
              reference.relation_type,
              reference.locked ? "yes" : "no",
              reference.target_asset_version_id
            ])}
          />
        ) : (
          <EmptyInline text="Project-level locked references to cross-project assets will appear here." />
        )}
      </Panel>
    </div>
  );
}

function getLatestValidation(validations: ModelValidation[]) {
  return validations[0] ?? null;
}

function formatValidationSummary(validation: ModelValidation | null) {
  if (!validation) return "-";
  const status = validation.validation_status ?? validation.job.status;
  return `${status} / delta ${formatDelta(validation.max_abs_metric_delta)}`;
}

function formatDelta(value: number | null) {
  if (value == null) return "-";
  return value.toExponential(2);
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function truncateJson(value: Record<string, unknown>) {
  const serialized = JSON.stringify(value);
  if (serialized.length <= 180) return serialized;
  return `${serialized.slice(0, 177)}...`;
}

function LineageTab({ lineage }: { lineage: LineageEdge[] }) {
  return (
    <Panel title="Lineage Edges" icon={<GitBranch size={18} />}>
      {lineage.length ? (
        <Table
          headers={["From", "Relation", "To"]}
          rows={lineage.map((edge) => [
            `${edge.from_asset_type}:${edge.from_asset_id}`,
            edge.relation_type,
            `${edge.to_asset_type}:${edge.to_asset_id}`
          ])}
        />
      ) : (
        <EmptyInline text="DatasetSnapshot, SemanticCatalog, EvaluationSpec, SplitManifest, ExperimentRun, Report, AssetReference, and artifact lineage will appear here." />
      )}
    </Panel>
  );
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">
          {icon}
          <h2>{title}</h2>
        </div>
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: Array<Array<React.ReactNode>> }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="empty-state">
      {icon}
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="loading">
      <Loader2 className="spin" size={18} />
      {label}
    </div>
  );
}

function formatBytes(value: number | null) {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
