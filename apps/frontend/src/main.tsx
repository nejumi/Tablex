import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
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
  portal: "Portal",
  backToPortal: "Back to Portal",
  portalTitle: "Team prediction portal",
  portalSubtitle: "Cross-project health, recent activity, and ideas captured for follow-up.",
  projectPortfolio: "Project portfolio",
  recentUpdates: "Recent updates",
  olderUpdates: "older updates",
  ideaInbox: "Idea inbox",
  ideaInboxHint: "Capture product or analysis ideas here; promote them into project work when ready.",
  ideaInboxPlaceholder: "Drop a UX, modeling, data, or reporting idea for later follow-up",
  addIdea: "Add idea",
  noIdeasYet: "No captured ideas yet.",
  openProject: "Open project",
  totalProjects: "Projects",
  activeProjects: "Active",
  totalJobs: "Jobs",
  totalArtifacts: "Artifacts",
  moreTabs: "More",
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
  tabNotebooks: "Notebooks",
  tabLeaderboard: "Leaderboard",
  tabReports: "Reports",
  tabAssets: "Assets",
  tabLibrary: "Library",
  tabJobs: "Jobs",
  tabLineage: "Lineage",
  focusGuideTitle: "Focus Guide",
  focusNow: "Now",
  focusWhy: "Why",
  focusDo: "Do",
  journeyMap: "Journey map",
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
  focusNotebooks: "Review notebook evidence",
  focusNotebooksReason: "Notebook previews and safe captures turn run evidence into inspectable findings before final reporting.",
  focusReports: "Read the decision report",
  focusReportsReason: "Reports summarize readiness, risks, evidence, and next actions without requiring raw artifact inspection.",
  showAllAssumptionsEvidence: "Show all assumptions and evidence",
  guidedJourneyTitle: "Guided Journey",
  guidedJourneySubtitle: "One visible path through the harness, with approach choices left open for Codex, Skills, and evidence.",
  journeyEvidence: "Evidence",
  journeyOpenStage: "Open stage",
  journeySaveSnapshot: "Save snapshot",
  journeyStatusDone: "Done",
  journeyStatusCurrent: "Current",
  journeyStatusNext: "Next",
  journeyStatusBlocked: "Blocked",
  journeyStatusWaiting: "Waiting",
  journeyData: "Data",
  journeyUnderstanding: "Understanding",
  journeyAssumptions: "Assumptions",
  journeyEvaluation: "Evaluation",
  journeyApproach: "Approach",
  journeyExperiments: "Experiments",
  journeyNotebooks: "Notebooks",
  journeyReports: "Reports",
  autonomousNavigator: "Autonomous Navigator",
  oneDecisionAtATime: "one decision at a time",
  showMapOnlyIfNeeded: "Show the map only if needed",
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
  agentChatSubtitle: "Talk to Tablee; actions stay inside the harness",
  agentChatPlaceholder: "Try: set metric to ROC-AUC, explain the next step, generate a diagnostic notebook",
  createAgentTaskContract: "Send",
  downloadLatestAgentTaskContract: "Download latest AgentTaskContract",
  agentTaskContractCreated: "AgentTaskContract created.",
  chatActionOpen: "Open",
  chatActionReview: "Review",
  agentActivityTitle: "Agent Activity",
  agentActivitySubtitle: "Workers, actions, and token telemetry",
  estimatedTokens: "Estimated tokens",
  telemetryEstimate: "estimate until runner telemetry",
  workerChatPlaceholder: "Message this worker",
  noAgentActivity: "Agent activity will appear after chat, jobs, or runner work starts.",
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
  portal: "ポータル",
  backToPortal: "ポータルに戻る",
  portalTitle: "Team prediction portal",
  portalSubtitle: "Project横断の状態、最近の更新、追っかけ対応するideaを確認します。",
  projectPortfolio: "Project portfolio",
  recentUpdates: "最近の更新",
  olderUpdates: "件の過去更新",
  ideaInbox: "Idea inbox",
  ideaInboxHint: "UX、modeling、data、reportingの思いつきをここに残し、後でproject workへ昇格します。",
  ideaInboxPlaceholder: "後で対応したいUX、モデリング、データ、レポート案を書く",
  addIdea: "Ideaを追加",
  noIdeasYet: "まだideaはありません。",
  openProject: "Projectを開く",
  totalProjects: "Projects",
  activeProjects: "Active",
  totalJobs: "Jobs",
  totalArtifacts: "Artifacts",
  moreTabs: "その他",
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
  tabNotebooks: "ノートブック",
  tabLeaderboard: "リーダーボード",
  tabReports: "レポート",
  tabAssets: "アセット",
  tabLibrary: "ライブラリ",
  tabJobs: "ジョブ",
  tabLineage: "リネージ",
  focusGuideTitle: "Focus Guide",
  focusNow: "今",
  focusWhy: "理由",
  focusDo: "実行",
  journeyMap: "全体の流れ",
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
  focusNotebooks: "notebook evidenceを確認する",
  focusNotebooksReason: "Notebook previewとsafe captureで、最終report前にrun evidenceを検査可能なfindingへ変換します。",
  focusReports: "decision reportを読む",
  focusReportsReason: "raw artifactを追わなくても、readiness、risk、evidence、next actionを把握できます。",
  showAllAssumptionsEvidence: "すべての仮定と根拠を表示",
  guidedJourneyTitle: "Guided Journey",
  guidedJourneySubtitle: "ハーネス内の現在地を一つの流れで示し、アプローチ選択はCodex、Skill、証拠に開いたままにします。",
  journeyEvidence: "根拠",
  journeyOpenStage: "ステージを開く",
  journeySaveSnapshot: "Snapshotを保存",
  journeyStatusDone: "完了",
  journeyStatusCurrent: "現在",
  journeyStatusNext: "次",
  journeyStatusBlocked: "要確認",
  journeyStatusWaiting: "待機",
  journeyData: "データ",
  journeyUnderstanding: "理解",
  journeyAssumptions: "仮定",
  journeyEvaluation: "評価",
  journeyApproach: "アプローチ",
  journeyExperiments: "実験",
  journeyNotebooks: "ノートブック",
  journeyReports: "レポート",
  autonomousNavigator: "Autonomous Navigator",
  oneDecisionAtATime: "次の一手だけ",
  showMapOnlyIfNeeded: "必要な時だけ全体地図を開く",
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
  agentChatSubtitle: "Tableeに話す。アクションはハーネス内で管理されます",
  agentChatPlaceholder: "例: metricはROC-AUCにして、次に見るべきことを説明して、診断Notebookを生成して",
  createAgentTaskContract: "送信",
  downloadLatestAgentTaskContract: "最新のAgentTaskContractをダウンロード",
  agentTaskContractCreated: "AgentTaskContractを作成しました。",
  chatActionOpen: "開く",
  chatActionReview: "確認",
  agentActivityTitle: "Agent Activity",
  agentActivitySubtitle: "Worker、action、token telemetry",
  estimatedTokens: "推定tokens",
  telemetryEstimate: "runner telemetryが入るまで推定",
  workerChatPlaceholder: "このworkerにメッセージ",
  noAgentActivity: "chat、job、runner workが始まるとagent activityが表示されます。",
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

type NotebookIndexItem = {
  notebook_artifact_id: string;
  notebook_kind: string;
  title: string;
  status: string;
  created_at: string;
  dataset_snapshot_id: string | null;
  run_id: string | null;
  model_version_id: string | null;
  artifact_ids: {
    notebook: string;
    html_preview: string | null;
    manifest: string | null;
    report_artifact: string | null;
    visualization_artifact: string | null;
    execution_plan: string | null;
    agent_task_contract: string | null;
    execution_manifest: string | null;
    execution_report: string | null;
    execution_html: string | null;
    figure_manifest: string | null;
    execution_source: string | null;
  };
  report_id: string | null;
  visualization_id: string | null;
  coverage: Record<string, unknown>;
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

type NotebookIndex = {
  schema_version: string;
  project_id: string;
  generated_at: string;
  counts: {
    total: number;
    by_kind: Record<string, number>;
    with_html_preview: number;
    with_report: number;
    with_visualization: number;
    with_execution_plan: number;
    with_execution_capture: number;
  };
  recommended_notebook: NotebookIndexItem | null;
  groups: Array<{ notebook_kind: string; title: string; count: number; latest_created_at: string; items: NotebookIndexItem[] }>;
  items: NotebookIndexItem[];
  next_actions: Array<{ label: string; endpoint: string | null; reason: string }>;
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

type JobArtifactsResponse = {
  job: Job;
  summary: Record<string, unknown>;
  artifact_ids: string[];
  missing_artifact_ids: string[];
  artifacts: Artifact[];
};

type TokenSeriesPoint = {
  step: string;
  tokens: number;
};

type AgentWorkerEvent = {
  worker_id: string;
  display_name: string;
  status: string;
  headline: string;
  detail: string;
  job_id: string;
  project_id?: string | null;
  target_tab: string | null;
  created_at?: string;
  updated_at?: string;
  active?: boolean;
  token_usage: {
    source: string;
    is_estimate: boolean;
    series: TokenSeriesPoint[];
  };
};

type AgentChatAction = {
  type: string;
  status: string;
  label: string;
  target_tab: string | null;
  detail: string;
  artifact_id?: string;
  artifact_ids?: string[];
  entity_ids?: string[];
};

type AgentChatResponse = {
  schema_version: "agent_chat_turn.v1";
  project_id: string;
  user_message: string;
  assistant_message: string;
  intent: Record<string, unknown>;
  actions: AgentChatAction[];
  worker_events: AgentWorkerEvent[];
  token_usage: { source: string; is_estimate: boolean; series: TokenSeriesPoint[] };
  next_focus: Record<string, unknown>;
  artifact_id: string;
  job: Job;
};

type AgentChatMessage = {
  role: "user" | "system";
  text: string;
  actions?: AgentChatAction[];
};

type PortalIdea = {
  id: string;
  artifact_id?: string;
  text: string;
  status?: string;
  source?: string;
  created_at: string;
};

type PortalUpdate = {
  type: string;
  project_id: string | null;
  title: string;
  summary: string;
  created_at: string;
  target_tab: string | null;
};

type PortalOverview = {
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

type AgentActivityResponse = {
  schema_version: "agent_activity.v1";
  project_id: string;
  generated_at: string;
  active_count: number;
  workers: AgentWorkerEvent[];
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

type DecisionReportBundle = {
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

type DecisionReportCurrent = {
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
  { id: "Notebooks", labelKey: "tabNotebooks" },
  { id: "Leaderboard", labelKey: "tabLeaderboard" },
  { id: "Reports", labelKey: "tabReports" },
  { id: "Assets", labelKey: "tabAssets" },
  { id: "Library", labelKey: "tabLibrary" },
  { id: "Jobs", labelKey: "tabJobs" },
  { id: "Lineage", labelKey: "tabLineage" }
] as const satisfies ReadonlyArray<{ id: string; labelKey: keyof LocaleMessages }>;
type Tab = (typeof tabItems)[number]["id"];
const secondaryTabIds = new Set<Tab>(["Leaderboard", "Assets", "Library", "Jobs", "Lineage"]);
const primaryTabItems = tabItems.filter((item) => !secondaryTabIds.has(item.id));
const secondaryTabItems = tabItems.filter((item) => secondaryTabIds.has(item.id));

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
  const match = tabItems.find((item) => item.id === value);
  return match ? match.id : fallback;
}

function firstAgentChatTargetTab(actions: AgentChatAction[]): Tab | null {
  const action = actions.find((candidate) => candidate.target_tab && tabItems.some((item) => item.id === candidate.target_tab));
  return action ? tabFromString(action.target_tab, "Approach") : null;
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

type ProjectGuidanceJourneyStage = {
  id: string;
  label: string;
  target_tab: string;
  status: "done" | "current" | "next" | "blocked" | "waiting";
  summary: string;
  evidence: string[];
  action: ProjectGuidanceAction | null;
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
  journey_stages: ProjectGuidanceJourneyStage[];
  current_stage_id: string | null;
  state_summary: Record<string, unknown>;
  supporting_counts: Record<string, number>;
  hidden_detail_groups: Array<Record<string, unknown>>;
  agent_guidance: string[];
  autonomous_navigation: Record<string, unknown>;
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
  if (focusKey === "notebooks") return { title: text.focusNotebooks, reason: text.focusNotebooksReason };
  if (focusKey === "reports") return { title: text.focusReports, reason: text.focusReportsReason };
  return null;
}

function journeyStageLabel(stage: ProjectGuidanceJourneyStage, text: LocaleMessages) {
  if (stage.id === "data_intake") return text.journeyData;
  if (stage.id === "understanding") return text.journeyUnderstanding;
  if (stage.id === "assumptions") return text.journeyAssumptions;
  if (stage.id === "evaluation") return text.journeyEvaluation;
  if (stage.id === "approach") return text.journeyApproach;
  if (stage.id === "experiments") return text.journeyExperiments;
  if (stage.id === "notebooks") return text.journeyNotebooks;
  if (stage.id === "reports") return text.journeyReports;
  return stage.label;
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
      secondaryTabs: ["Experiments", "Notebooks", "Assets"],
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
      secondaryTabs: ["Notebooks", "Leaderboard", "Reports"],
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
    secondaryTabs: ["Notebooks", "Leaderboard", "Lineage"],
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
  const [viewMode, setViewMode] = React.useState<"portal" | "project">("portal");
  const [tab, setTab] = React.useState<Tab>("Overview");
  const [userSettings, setUserSettings] = React.useState<UserSettings>(() => loadUserSettings());
  const [dynamicLocalePacks, setDynamicLocalePacks] = React.useState<LocalePack[]>(() => loadDynamicLocalePacks());
  const [portalOverview, setPortalOverview] = React.useState<PortalOverview | null>(null);
  const [portalIdeas, setPortalIdeas] = React.useState<PortalIdea[]>([]);
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
      const [data, portalData] = await Promise.all([
        api<Project[]>("/api/projects"),
        api<PortalOverview>("/api/portal/overview").catch(() => null)
      ]);
      setProjects(data);
      setPortalOverview(portalData);
      setPortalIdeas(portalData?.ideas ?? []);
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
  const activeProject = viewMode === "project" ? selectedProject : null;

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

  async function addPortalIdea(textValue: string) {
    const idea = await api<PortalIdea>("/api/portal/ideas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: textValue })
    });
    setPortalIdeas((current) => [idea, ...current].slice(0, 40));
    setPortalOverview((current) => {
      if (!current) return current;
      const previousCount = typeof current.summary.idea_count === "number" ? current.summary.idea_count : current.ideas.length;
      return {
        ...current,
        summary: { ...current.summary, idea_count: previousCount + 1 },
        ideas: [idea, ...current.ideas].slice(0, 40)
      };
    });
  }

  return (
    <LocaleContext.Provider value={{ text, locale: activeLocale.locale }}>
      <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="brand-mascot" />
          </div>
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
              className={project.id === selectedProjectId && viewMode === "project" ? "project-item active" : "project-item"}
              onClick={() => {
                setSelectedProjectId(project.id);
                setViewMode("project");
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
            <div className="topbar-kicker">
              {activeProject ? (
                <button className="text-button" onClick={() => setViewMode("portal")} type="button">
                  <ArrowLeft size={15} />
                  {text.backToPortal}
                </button>
              ) : (
                <span>{text.portal}</span>
              )}
            </div>
            <h1>{activeProject ? activeProject.name : text.portalTitle}</h1>
            <p>{activeProject ? activeProject.description || text.projectDescription : text.portalSubtitle}</p>
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
        {!loading && projects.length === 0 ? (
          <EmptyState
            icon={<img src="/mascot/tablee-empty.svg" alt="" aria-hidden="true" className="empty-state-mascot" />}
            title={text.createFirstProject}
            body={text.createFirstProjectBody}
          />
        ) : null}
        {!loading && !activeProject && projects.length > 0 ? (
          <PortalView
            projects={projects}
            overview={portalOverview}
            ideas={portalIdeas}
            text={text}
            onOpenProject={(projectId) => {
              setSelectedProjectId(projectId);
              setViewMode("project");
              setTab("Overview");
            }}
            onAddIdea={addPortalIdea}
          />
        ) : null}
        {activeProject ? (
          <>
            <nav className="tabs">
              {primaryTabItems.map((item) => (
                <button
                  key={item.id}
                  className={item.id === tab ? "tab active" : "tab"}
                  onClick={() => setTab(item.id)}
                >
                  {text[item.labelKey]}
                </button>
              ))}
              <details className="tab-more" open={secondaryTabItems.some((item) => item.id === tab)}>
                <summary className={secondaryTabItems.some((item) => item.id === tab) ? "tab active" : "tab"}>
                  {text.moreTabs}
                </summary>
                <div className="tab-menu">
                  {secondaryTabItems.map((item) => (
                    <button
                      key={item.id}
                      className={item.id === tab ? "tab-menu-item active" : "tab-menu-item"}
                      onClick={() => setTab(item.id)}
                      type="button"
                    >
                      {text[item.labelKey]}
                    </button>
                  ))}
                </div>
              </details>
            </nav>
            <ProjectDetail
              project={activeProject}
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

function numberFromSummary(value: unknown, fallback: number | string): number | string {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function PortalView({
  projects,
  overview,
  ideas,
  text,
  onOpenProject,
  onAddIdea
}: {
  projects: Project[];
  overview: PortalOverview | null;
  ideas: PortalIdea[];
  text: LocaleMessages;
  onOpenProject: (projectId: string) => void;
  onAddIdea: (text: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const summary = overview?.summary ?? {};
  const activeCount = numberFromSummary(summary.active_project_count, projects.filter((project) => project.status !== "archived").length);
  const projectCount = numberFromSummary(summary.project_count, projects.length);
  const jobCount = numberFromSummary(summary.job_count, "Project tabs");
  const artifactCount = numberFromSummary(summary.artifact_count, "Workbench");
  const recentProjects = [...projects]
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))
    .slice(0, 6);
  const recentUpdates =
    overview?.recent_updates?.length
      ? overview.recent_updates
      : recentProjects.map((project) => ({
          type: "project",
          project_id: project.id,
          title: project.name,
          summary: formatWorkflowState(project.current_phase),
          created_at: project.updated_at,
          target_tab: "Overview"
        }));
  const primaryUpdates = recentUpdates.slice(0, 3);
  const secondaryUpdates = recentUpdates.slice(3, 10);

  async function addIdea(event: React.FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await onAddIdea(value);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="portal-grid">
      <div className="portal-hero">
        <div>
          <div className="eyebrow">{text.portal}</div>
          <h2>{text.projectPortfolio}</h2>
          <p>{text.portalSubtitle}</p>
        </div>
        <img src="/mascot/tablee-success.svg" alt="" aria-hidden="true" className="portal-mascot" />
      </div>

      <section className="metric-grid compact" aria-label={text.atAGlance}>
        <Metric label={text.totalProjects} value={projectCount} />
        <Metric label={text.activeProjects} value={activeCount} />
        <Metric label={text.totalJobs} value={jobCount} />
        <Metric label={text.totalArtifacts} value={artifactCount} />
      </section>

      <section className="two-column">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <BarChart3 size={17} />
              <h2>{text.recentUpdates}</h2>
            </div>
          </div>
          <div className="portal-project-list">
            {primaryUpdates.map((update, index) => (
              <button
                key={`${update.type}-${update.project_id ?? "cross"}-${index}-${update.created_at}`}
                className="portal-project-card"
                onClick={() => {
                  if (update.project_id) onOpenProject(update.project_id);
                }}
                type="button"
                disabled={!update.project_id}
              >
                <span>
                  <strong>{update.title}</strong>
                  <small>{update.summary} · {new Date(update.created_at).toLocaleString()}</small>
                </span>
                {update.project_id ? <span className="secondary-button">{text.openProject}</span> : null}
              </button>
            ))}
          </div>
          {secondaryUpdates.length ? (
            <details className="supporting-details portal-update-more">
              <summary>
                <span>{text.viewDetails}</span>
                <small>{secondaryUpdates.length} {text.olderUpdates}</small>
              </summary>
              <div className="portal-project-list compact">
                {secondaryUpdates.map((update, index) => (
                  <button
                    key={`${update.type}-${update.project_id ?? "cross"}-${index + 3}-${update.created_at}`}
                    className="portal-project-card"
                    onClick={() => {
                      if (update.project_id) onOpenProject(update.project_id);
                    }}
                    type="button"
                    disabled={!update.project_id}
                  >
                    <span>
                      <strong>{update.title}</strong>
                      <small>{update.summary} · {new Date(update.created_at).toLocaleString()}</small>
                    </span>
                    {update.project_id ? <span className="secondary-button">{text.openProject}</span> : null}
                  </button>
                ))}
              </div>
            </details>
          ) : null}
        </div>

        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Lightbulb size={17} />
              <h2>{text.ideaInbox}</h2>
            </div>
          </div>
          <p className="muted-copy">{text.ideaInboxHint}</p>
          {error ? <div className="banner danger">{error}</div> : null}
          <form className="portal-idea-form" onSubmit={addIdea}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={text.ideaInboxPlaceholder}
              rows={4}
            />
            <button className="primary-button" disabled={busy || !draft.trim()}>
              {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
              {text.addIdea}
            </button>
          </form>
          <div className="portal-idea-list">
            {ideas.length ? (
              ideas.slice(0, 8).map((idea) => (
                <div className="portal-idea" key={idea.id}>
                  <p>{idea.text}</p>
                  <small>{new Date(idea.created_at).toLocaleString()}</small>
                </div>
              ))
            ) : (
              <EmptyInline text={text.noIdeasYet} />
            )}
          </div>
        </div>
      </section>
    </section>
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
  const [decisionReport, setDecisionReport] = React.useState<DecisionReportCurrent | null>(null);
  const [visualizations, setVisualizations] = React.useState<VisualizationSpec[]>([]);
  const [notebookIndex, setNotebookIndex] = React.useState<NotebookIndex | null>(null);
  const [agentTaskResults, setAgentTaskResults] = React.useState<AgentTaskResult[]>([]);
  const [insights, setInsights] = React.useState<Insight[]>([]);
  const [libraryAssets, setLibraryAssets] = React.useState<LibraryAsset[]>([]);
  const [projectAssetReferences, setProjectAssetReferences] = React.useState<AssetReference[]>([]);
  const [lineage, setLineage] = React.useState<LineageEdge[]>([]);
  const [understanding, setUnderstanding] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [agentChatMessages, setAgentChatMessages] = React.useState<AgentChatMessage[]>([]);
  const [agentWorkerEvents, setAgentWorkerEvents] = React.useState<AgentWorkerEvent[]>([]);
  const [agentActivity, setAgentActivity] = React.useState<AgentActivityResponse | null>(null);
  const [activityTick, setActivityTick] = React.useState(0);
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
        decisionReportData,
        visualizationsData,
        notebookIndexData,
        agentTaskResultsData,
        insightsData,
        libraryAssetsData,
        projectAssetReferencesData,
        lineageData,
        agentActivityData,
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
        api<DecisionReportCurrent>(`/api/projects/${project.id}/decision-report/current`).catch(() => null),
        api<VisualizationSpec[]>(`/api/projects/${project.id}/visualizations`),
        api<NotebookIndex>(`/api/projects/${project.id}/analysis-notebooks`).catch(() => null),
        api<AgentTaskResult[]>(`/api/projects/${project.id}/agent-task-results`),
        api<Insight[]>(`/api/projects/${project.id}/insights`),
        api<LibraryAsset[]>(`/api/assets`),
        api<AssetReference[]>(`/api/projects/${project.id}/asset-references`),
        api<LineageEdge[]>(`/api/projects/${project.id}/lineage`),
        api<AgentActivityResponse>(`/api/projects/${project.id}/agent-activity`).catch(() => null),
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
      setDecisionReport(decisionReportData);
      setVisualizations(visualizationsData);
      setNotebookIndex(notebookIndexData);
      setAgentTaskResults(agentTaskResultsData);
      setInsights(insightsData);
      setLibraryAssets(libraryAssetsData);
      setProjectAssetReferences(projectAssetReferencesData);
      setAgentActivity(agentActivityData);
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

  const refreshAgentActivity = React.useCallback(async () => {
    try {
      const data = await api<AgentActivityResponse>(`/api/projects/${project.id}/agent-activity`);
      setAgentActivity(data);
    } catch {
      // The activity overlay is opportunistic; project refresh still surfaces hard errors.
    }
  }, [project.id]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    const interval = window.setInterval(
      () => {
        setActivityTick((current) => current + 1);
        void refreshAgentActivity();
      },
      busy ? 900 : 2400
    );
    return () => window.clearInterval(interval);
  }, [busy, refreshAgentActivity]);

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

  async function submitAgentChat(objective: string): Promise<AgentChatResponse | void> {
    const trimmed = objective.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    const pendingWorker = optimisticWorkerEvent(project.id, trimmed);
    setAgentChatMessages((current) => [...current.slice(-3), { role: "user", text: trimmed }]);
    setAgentWorkerEvents((current) => [pendingWorker, ...current].slice(0, 8));
    try {
      const result = await api<AgentChatResponse>(`/api/projects/${project.id}/agent-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed })
      });
      setAgentChatMessages((current) => [
        ...current.slice(-4),
        {
          role: "system",
          text: result.assistant_message,
          actions: result.actions
        }
      ]);
      setAgentWorkerEvents((current) =>
        [...result.worker_events, ...current.filter((event) => event.job_id !== pendingWorker.job_id)].slice(0, 8)
      );
      const targetTab = firstAgentChatTargetTab(result.actions);
      if (targetTab) onTabChange(targetTab);
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setAgentChatMessages((current) => [...current.slice(-4), { role: "system", text: message }]);
      setAgentWorkerEvents((current) => current.filter((event) => event.job_id !== pendingWorker.job_id));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function submitAgentChatWithoutResponse(objective: string): Promise<void> {
    await submitAgentChat(objective);
  }

  function openAgentChatAction(action: AgentChatAction) {
    const targetTab = tabFromString(action.target_tab, "Approach");
    onTabChange(targetTab);
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

  async function saveGuidedJourneySnapshot() {
    await runAction(() => api(`/api/projects/${project.id}/guidance/snapshot`, { method: "POST" }));
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
      <AutonomousNavigator
        guidance={guidance}
        recommendation={focusRecommendation}
        currentTab={tab}
        busy={busy}
        text={text}
        onTabChange={onTabChange}
        onAction={(action) => void runFocusAction(action)}
        onSaveSnapshot={() => void saveGuidedJourneySnapshot()}
      />
      <AgentChatDock
        busy={busy}
        text={text}
        messages={agentChatMessages}
        latestContract={artifacts.find((artifact) => artifact.asset_type === "agent_task_contract") ?? null}
        onSubmit={submitAgentChatWithoutResponse}
        onActionOpen={openAgentChatAction}
      />
      <AgentActivityRail
        text={text}
        jobs={jobs}
        events={agentWorkerEvents}
        activity={agentActivity}
        tick={activityTick}
        onWorkerMessage={submitAgentChatWithoutResponse}
      />
      {tab === "Overview" && (
        <OverviewTab
          overview={overview}
          assumptions={assumptions}
          jobs={jobs}
          artifacts={artifacts}
          text={text}
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
          text={text}
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
      {tab === "Notebooks" && (
        <NotebooksTab
          project={project}
          datasets={datasets}
          runs={runs}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          busy={busy}
          runAction={runAction}
          onAskAgent={submitAgentChat}
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
          decisionReport={decisionReport}
          artifacts={artifacts}
          visualizations={visualizations}
          notebookIndex={notebookIndex}
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

function AutonomousNavigator({
  guidance,
  recommendation,
  currentTab,
  busy,
  text,
  onTabChange,
  onAction,
  onSaveSnapshot
}: {
  guidance: ProjectGuidance | null;
  recommendation: FocusRecommendation;
  currentTab: Tab;
  busy: boolean;
  text: LocaleMessages;
  onTabChange: (tab: Tab) => void;
  onAction: (action: FocusAction | null) => void;
  onSaveSnapshot: () => void;
}) {
  const navigation = guidance?.autonomous_navigation ?? {};
  const headline = textField(navigation.headline) ?? recommendation.title;
  const why = textField(navigation.why) ?? recommendation.reason;
  const status = textField(navigation.status) ?? recommendation.riskLevel ?? "ready_to_act";
  const evidence = Array.isArray(navigation.evidence)
    ? navigation.evidence.map((item) => String(item)).slice(0, 3)
    : recommendation.evidence.slice(0, 3);
  const journeyProgress =
    navigation.journey_progress && typeof navigation.journey_progress === "object"
      ? (navigation.journey_progress as Record<string, unknown>)
      : {};
  const doneCount = Number(journeyProgress.done_count ?? 0);
  const totalCount = Number(journeyProgress.total_count ?? guidance?.journey_stages.length ?? 0);
  const stages = guidance?.journey_stages ?? [];
  const isCurrent = currentTab === recommendation.tab;
  const navigationPrimaryAction =
    guidance?.recommended_focus.primary_action && navigation.primary_action && typeof navigation.primary_action === "object"
      ? guidanceActionToFocusAction(guidance.recommended_focus.primary_action)
      : null;
  const primaryAction =
    navigationPrimaryAction ??
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
  const primaryDisabled = primaryAction.disabled || (primaryAction.actionType === "navigate" && isCurrent);

  return (
    <section className="autonomous-navigator" aria-label={text.autonomousNavigator}>
      <div className="autonomous-main">
        <div className="autonomous-copy">
          <div className="eyebrow">{text.autonomousNavigator}</div>
          <h2>{headline}</h2>
          <p>{why}</p>
          <div className="badge-row">
            <span className={navigatorStatusClass(status)}>{status.replace(/_/g, " ")}</span>
            {totalCount ? <span className="badge muted">{doneCount}/{totalCount} journey</span> : null}
            <span className="badge muted">{text.oneDecisionAtATime}</span>
          </div>
        </div>
        <button
          className="primary-button autonomous-action"
          disabled={primaryDisabled}
          onClick={() => onAction(primaryAction)}
          type="button"
        >
          {primaryAction.actionType === "navigate" ? <Search size={16} /> : <Play size={16} />}
          <span>
            <small>{text.focusDo}</small>
            {primaryAction.label}
          </span>
        </button>
      </div>
      {evidence.length ? (
        <div className="autonomous-evidence">
          {evidence.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}
      <details className="autonomous-details">
        <summary>
          <span>{text.showMapOnlyIfNeeded}</span>
          <small>{text.journeyMap}</small>
        </summary>
        <div className="autonomous-map">
          {stages.map((stage, index) => (
            <button
              className={`autonomous-stage ${stage.status}`}
              key={stage.id}
              onClick={() => (stage.action ? onAction(guidanceActionToFocusAction(stage.action)) : onTabChange(normalizeTab(stage.target_tab)))}
              title={stage.summary}
              type="button"
            >
              <span>{stage.status === "done" ? <Check size={13} /> : index + 1}</span>
              <strong>{journeyStageLabel(stage, text)}</strong>
            </button>
          ))}
          <button className="secondary-button" disabled={busy} type="button" onClick={onSaveSnapshot}>
            {busy ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
            {text.journeySaveSnapshot}
          </button>
        </div>
      </details>
    </section>
  );
}

function navigatorStatusClass(status: string) {
  if (["ready_to_act", "ready", "low"].includes(status)) return "badge success";
  if (["blocked", "high", "needs_attention"].includes(status)) return "badge risk";
  if (["recover", "medium"].includes(status)) return "badge warning";
  return "badge muted";
}

function agentChatActionLabel(action: AgentChatAction, text: LocaleMessages) {
  const targetTab = tabFromString(action.target_tab, "Approach");
  const verb = ["needs_review", "created", "recorded", "explained"].includes(action.status)
    ? text.chatActionReview
    : text.chatActionOpen;
  return `${verb} ${tabLabel(targetTab, text)}`;
}

function AgentChatDock({
  busy,
  text,
  messages,
  latestContract,
  onSubmit,
  onActionOpen
}: {
  busy: boolean;
  text: LocaleMessages;
  messages: AgentChatMessage[];
  latestContract: Artifact | null;
  onSubmit: (objective: string) => Promise<void>;
  onActionOpen: (action: AgentChatAction) => void;
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
        <div className="agent-chat-heading">
          <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="agent-chat-avatar" />
          <div>
            <div className="agent-chat-title">
              <MessageSquare size={16} />
              {text.agentChatTitle}
            </div>
            <small>{text.agentChatSubtitle}</small>
          </div>
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
              <p>{message.text}</p>
              {message.actions?.length ? (
                <div className="agent-chat-actions">
                  {message.actions.slice(0, 3).map((action) => (
                    <button
                      className="agent-chat-action-button"
                      key={`${action.type}-${action.label}`}
                      onClick={() => onActionOpen(action)}
                      type="button"
                    >
                      <span>{action.status.replace(/_/g, " ")}</span>
                      <strong>{agentChatActionLabel(action, text)}</strong>
                    </button>
                  ))}
                </div>
              ) : null}
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

function AgentActivityRail({
  text,
  jobs,
  events,
  activity,
  tick,
  onWorkerMessage
}: {
  text: LocaleMessages;
  jobs: Job[];
  events: AgentWorkerEvent[];
  activity: AgentActivityResponse | null;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
}) {
  const workerEvents = React.useMemo(() => {
    const now = Date.now() + tick;
    const fromActivity = activity?.workers ?? [];
    const fromJobs = jobs.flatMap((job) => workerEventsFromJob(job));
    const merged = [...events, ...fromActivity, ...fromJobs];
    const byKey = new Map<string, AgentWorkerEvent>();
    merged.forEach((event) => {
      byKey.set(`${event.worker_id}-${event.job_id}`, event);
    });
    return [...byKey.values()].filter((event) => isVisibleWorkerEvent(event, now)).slice(0, 8);
  }, [activity, events, jobs, tick]);

  if (!workerEvents.length) {
    return null;
  }

  return (
    <aside className="agent-activity-rail" aria-label={text.agentActivityTitle}>
      <div className="agent-activity-header">
        <div>
          <div className="agent-activity-title">
            <Activity size={16} />
            {text.agentActivityTitle}
          </div>
          <small>{text.agentActivitySubtitle}</small>
        </div>
      </div>
      {workerEvents.length ? (
        <div className="agent-worker-list">
          {workerEvents.map((event) => (
            <AgentWorkerCard
              key={`${event.worker_id}-${event.job_id}`}
              event={event}
              text={text}
              tick={tick}
              onWorkerMessage={onWorkerMessage}
            />
          ))}
        </div>
      ) : null}
    </aside>
  );
}

function AgentWorkerCard({
  event,
  text,
  tick,
  onWorkerMessage
}: {
  event: AgentWorkerEvent;
  text: LocaleMessages;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");
  const displaySeries = animatedTokenSeries(event, tick);
  const maxTokens = Math.max(...displaySeries.map((point) => point.tokens), 1);

  async function submit(eventSubmit: React.FormEvent) {
    eventSubmit.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setDraft("");
    await onWorkerMessage(`[worker:${event.worker_id}] ${value}`);
  }

  return (
    <section className={`agent-worker-card ${event.status} ${event.active ? "active" : ""}`}>
      <div className="agent-worker-topline">
        <strong>{event.display_name}</strong>
        <span>{event.status}</span>
      </div>
      <p>{event.headline}</p>
      <small>{event.detail}</small>
      <div className={`token-sparkline ${event.active || isRunningWorkerStatus(event.status) ? "live" : ""}`} aria-label={text.estimatedTokens}>
        {displaySeries.map((point, index) => (
          <span
            key={`${point.step}-${index}`}
            title={`${point.step}: ${point.tokens}`}
            style={{
              height: `${Math.max(12, (point.tokens / maxTokens) * 54)}px`,
              animationDelay: `${index * 120}ms`
            }}
          />
        ))}
      </div>
      <div className="agent-worker-meta">
        <span>{text.estimatedTokens}</span>
        <strong>{displaySeries[displaySeries.length - 1]?.tokens ?? 0}</strong>
      </div>
      <small className="agent-worker-estimate">{text.telemetryEstimate}</small>
      <form className="agent-worker-chat" onSubmit={(submitEvent) => void submit(submitEvent)}>
        <input
          value={draft}
          onChange={(changeEvent) => setDraft(changeEvent.target.value)}
          placeholder={text.workerChatPlaceholder}
        />
        <button className="icon-button" disabled={!draft.trim()} title={text.workerChatPlaceholder}>
          <Send size={14} />
        </button>
      </form>
    </section>
  );
}

function optimisticWorkerEvent(projectId: string, message: string): AgentWorkerEvent {
  const now = new Date().toISOString();
  const base = Math.max(32, Math.min(160, message.length));
  return {
    worker_id: "agent-chat-orchestrator",
    display_name: "Tablee Orchestrator",
    status: "running",
    headline: "Reading your request and checking project context.",
    detail: message,
    job_id: `local-${Date.now()}`,
    project_id: projectId,
    target_tab: "Approach",
    created_at: now,
    updated_at: now,
    active: true,
    token_usage: {
      source: "estimated_until_runner_telemetry",
      is_estimate: true,
      series: [
        { step: "request", tokens: base },
        { step: "context", tokens: base * 3 },
        { step: "action", tokens: base * 5 }
      ]
    }
  };
}

function isRunningWorkerStatus(status: string) {
  return ["queued", "running", "approval_required", "needs_review"].includes(status);
}

function isVisibleWorkerEvent(event: AgentWorkerEvent, now: number) {
  const timestamp = Date.parse(event.updated_at ?? event.created_at ?? "");
  if (event.job_id.startsWith("local-") && Number.isFinite(timestamp) && now - timestamp > 15000) return false;
  if (event.active || isRunningWorkerStatus(event.status)) return true;
  return Number.isFinite(timestamp) && now - timestamp < 9000;
}

function animatedTokenSeries(event: AgentWorkerEvent, tick: number): TokenSeriesPoint[] {
  if (!event.active && !isRunningWorkerStatus(event.status)) return event.token_usage.series;
  return event.token_usage.series.map((point, index) => ({
    ...point,
    tokens: Math.max(1, Math.round(point.tokens + ((tick + index) % 3) * Math.max(4, Math.round(point.tokens * 0.035))))
  }));
}

function workerEventsFromJob(job: Job): AgentWorkerEvent[] {
  const outputEvents = job.output.worker_events;
  if (Array.isArray(outputEvents)) {
    return outputEvents
      .map((event, index) => coerceWorkerEvent(event, job, index))
      .filter((event): event is AgentWorkerEvent => event !== null);
  }
  if (!job.job_type.includes("agent") && !job.job_type.includes("notebook") && !job.job_type.includes("research")) {
    return [];
  }
  return [
    {
      worker_id: `job-${job.job_type}`,
      display_name: workerDisplayName(job.job_type),
      status: job.status,
      headline: jobHeadline(job),
      detail: job.error_message ?? `Job ${job.id}`,
      job_id: job.id,
      project_id: job.project_id,
      target_tab: targetTabForJob(job.job_type),
      created_at: job.created_at,
      updated_at: job.updated_at,
      active: isRunningWorkerStatus(job.status),
      token_usage: {
        source: "estimated_until_runner_telemetry",
        is_estimate: true,
        series: estimatedJobTokens(job)
      }
    }
  ];
}

function coerceWorkerEvent(raw: unknown, job: Job, index: number): AgentWorkerEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const usage = record.token_usage;
  const series =
    usage && typeof usage === "object" && Array.isArray((usage as Record<string, unknown>).series)
      ? ((usage as Record<string, unknown>).series as unknown[])
          .map(coerceTokenPoint)
          .filter((item): item is TokenSeriesPoint => item !== null)
      : estimatedJobTokens(job);
  return {
    worker_id: typeof record.worker_id === "string" ? record.worker_id : `worker-${index}`,
    display_name: typeof record.display_name === "string" ? record.display_name : workerDisplayName(job.job_type),
    status: typeof record.status === "string" ? record.status : job.status,
    headline: typeof record.headline === "string" ? record.headline : jobHeadline(job),
    detail: typeof record.detail === "string" ? record.detail : `Job ${job.id}`,
    job_id: typeof record.job_id === "string" ? record.job_id : job.id,
    project_id: typeof record.project_id === "string" ? record.project_id : job.project_id,
    target_tab: typeof record.target_tab === "string" ? record.target_tab : targetTabForJob(job.job_type),
    created_at: typeof record.created_at === "string" ? record.created_at : job.created_at,
    updated_at: typeof record.updated_at === "string" ? record.updated_at : job.updated_at,
    active: typeof record.active === "boolean" ? record.active : isRunningWorkerStatus(job.status),
    token_usage: {
      source:
        usage && typeof usage === "object" && typeof (usage as Record<string, unknown>).source === "string"
          ? String((usage as Record<string, unknown>).source)
          : "estimated_until_runner_telemetry",
      is_estimate:
        usage && typeof usage === "object" && typeof (usage as Record<string, unknown>).is_estimate === "boolean"
          ? Boolean((usage as Record<string, unknown>).is_estimate)
          : true,
      series
    }
  };
}

function coerceTokenPoint(raw: unknown): TokenSeriesPoint | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  if (typeof record.step !== "string" || typeof record.tokens !== "number") return null;
  return { step: record.step, tokens: record.tokens };
}

function estimatedJobTokens(job: Job): TokenSeriesPoint[] {
  const base = Math.max(24, job.job_type.length * 3);
  const multiplier = job.status === "running" ? 4 : job.status === "failed" ? 2 : 3;
  return [
    { step: "queued", tokens: base },
    { step: "context", tokens: base * 3 },
    { step: job.status, tokens: base * multiplier }
  ];
}

function workerDisplayName(jobType: string) {
  if (jobType.includes("notebook")) return "Notebook Worker";
  if (jobType.includes("research")) return "Research Worker";
  if (jobType.includes("agent")) return "Agent Runner";
  return "Harness Worker";
}

function targetTabForJob(jobType: string): string | null {
  if (jobType.includes("notebook")) return "Notebooks";
  if (jobType.includes("research") || jobType.includes("agent")) return "Approach";
  return null;
}

function jobHeadline(job: Job) {
  if (typeof job.output.assistant_message === "string") return job.output.assistant_message;
  return `${job.job_type.replace(/_/g, " ")} is ${job.status}`;
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

function isHtmlArtifactPreview(preview: ArtifactPreview | null): boolean {
  if (!preview?.preview_available) return false;
  const filename = preview.filename.toLowerCase();
  return (
    preview.content_type === "text/html" ||
    preview.content_type === "image/svg+xml" ||
    filename.endsWith(".html") ||
    filename.endsWith(".htm") ||
    filename.endsWith(".svg")
  );
}

function HtmlArtifactPreview({ preview }: { preview: ArtifactPreview }) {
  const previewType = preview.content_type === "image/svg+xml" || preview.filename.toLowerCase().endsWith(".svg") ? "SVG" : "HTML";
  return (
    <div className="preview-block">
      <div className="preview-toolbar">
        <div className="preview-meta">
          <span className="badge">{previewType} preview</span>
          <span className="badge muted">{preview.filename}</span>
          {preview.truncated ? <span className="badge risk">truncated</span> : null}
        </div>
      </div>
      {preview.truncated ? (
        <div className="banner warning">This preview is truncated. Download the artifact for the full notebook preview.</div>
      ) : null}
      <div className="html-preview-shell">
        <iframe
          className="html-preview-frame"
          srcDoc={preview.preview ?? ""}
          sandbox="allow-scripts"
          title={`${preview.name} preview`}
        />
      </div>
    </div>
  );
}

function OverviewTab({
  overview,
  assumptions,
  jobs,
  artifacts,
  text
}: {
  overview: Overview | null;
  assumptions: Assumption[];
  jobs: Job[];
  artifacts: Artifact[];
  text: LocaleMessages;
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
  const autoLoadedRelationalCatalogRef = React.useRef<string | null>(null);
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
  const latestRelationalCatalog = relationalArtifacts[0] ?? null;

  React.useEffect(() => {
    if (!latestRelationalCatalog) return;
    if (relationalPreview?.id === latestRelationalCatalog.id) return;
    if (autoLoadedRelationalCatalogRef.current === latestRelationalCatalog.id) return;
    autoLoadedRelationalCatalogRef.current = latestRelationalCatalog.id;
    setRelationalPreviewLoadingId(latestRelationalCatalog.id);
    setRelationalPreviewError(null);
    api<ArtifactPreview>(`/api/artifacts/${latestRelationalCatalog.id}/preview`)
      .then((preview) => {
        setRelationalPreview(preview);
      })
      .catch((err: unknown) => {
        setRelationalPreviewError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setRelationalPreviewLoadingId(null);
      });
  }, [latestRelationalCatalog, relationalPreview?.id]);

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
      <Panel title="Relational Preview" icon={<GitBranch size={18} />}>
        {relationalPreviewError ? <div className="banner danger">{relationalPreviewError}</div> : null}
        {relationalPreviewLoadingId ? (
          <div className="banner muted">
            <Loader2 className="spin" size={16} />
            Loading relational map...
          </div>
        ) : null}
        {relationalPreview?.preview_available ? (
          isRelationalCatalogPreview(relationalPreview) ? (
            <RelationalCatalogPreview preview={relationalPreview} />
          ) : isHtmlArtifactPreview(relationalPreview) ? (
            <HtmlArtifactPreview preview={relationalPreview} />
          ) : (
            <TranslatablePreview preview={relationalPreview} />
          )
        ) : (
          <EmptyInline text={relationalPreview?.reason ?? "Import a multi-table benchmark to see the relationship map here. Advanced JSON stays folded under the ER diagram."} />
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
  text,
  applyFallbacks,
  runAction
}: {
  assumptions: Assumption[];
  reviewQueue: AssumptionReviewQueue | null;
  questions: Question[];
  busy: boolean;
  text: LocaleMessages;
  applyFallbacks: () => Promise<void>;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const highRiskCount = assumptions.filter(isHighRiskAssumption).length;
  const evidenceCount = assumptions.reduce((count, assumption) => count + assumption.evidence.length, 0);

  return (
    <div className="stack">
      <AssumptionReviewQueuePanel queue={reviewQueue} busy={busy} runAction={runAction} />
      <details className="supporting-details">
        <summary>
          <span>{text.showAllAssumptionsEvidence}</span>
          <small>
            {assumptions.length} assumptions / {highRiskCount} high risk / {evidenceCount} evidence links
          </small>
        </summary>
        <div className="supporting-details-body single-column">
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
            {evidenceCount ? (
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
      </details>
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
        <div className="strategy-hero-copy">
          <img src="/mascot/tablee-hero.png" alt="" aria-hidden="true" className="strategy-hero-mascot" />
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

function ApproachDetailGroup({
  title,
  subtitle,
  countLabel,
  defaultOpen,
  children
}: {
  title: string;
  subtitle: string;
  countLabel: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  return (
    <details className="approach-detail-group" open={defaultOpen}>
      <summary>
        <span>
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </span>
        <span className="badge muted">{countLabel}</span>
      </summary>
      <div className="approach-detail-body">{children}</div>
    </details>
  );
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
  const researchContextCount = researchPlanArtifacts.length + researchSourceArtifacts.length + researchSynthesisArtifacts.length;
  const runnerHandoffCount = agentTaskContractArtifacts.length + researchBriefs.length + ideas.length;
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
  const previewCount = [contextPreview, planPreview, workspacePreview].filter(Boolean).length;

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
      <div className="approach-detail-groups">
        <ApproachDetailGroup
          title="Research context"
          subtitle="Controlled research planning, source slots, and synthesis artifacts for evidence-backed approach selection."
          countLabel={`${researchContextCount} artifacts`}
          defaultOpen={!strategyBrief}
        >
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
        </ApproachDetailGroup>
        <ApproachDetailGroup
          title="Runner handoff"
          subtitle="AgentTaskContracts, research briefs, and Ideas that Codex can use or reject with a decision trace."
          countLabel={`${runnerHandoffCount} items`}
          defaultOpen={!strategyBrief}
        >
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
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-codex`, {
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
                  title="Run Codex CLI"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
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
        </ApproachDetailGroup>
        <ApproachDetailGroup
          title="Previews and manifests"
          subtitle="Inspect materialized context packs, experiment plans, and controlled workspaces after creating them."
          countLabel={`${previewCount} previews`}
          defaultOpen={previewCount > 0 && !strategyBrief}
        >
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
        </ApproachDetailGroup>
      </div>
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
      "draft_run_report",
      "analyze_evaluation_diagnostics",
      "generate_model_diagnostics_notebook"
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
      "run_report",
      "analysis_notebook",
      "notebook_html",
      "notebook_run_manifest",
      "notebook_report"
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
              <div className="row-actions" key={run.id}>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => api(`/api/runs/${run.id}/report`, { method: "POST" }))}
                  title="Draft run report"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => api(`/api/runs/${run.id}/diagnostics`, { method: "POST" }))}
                  title="Run evaluation diagnostics"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/runs/${run.id}/analysis-notebook`, { method: "POST" });
                      const htmlArtifactId = job.output.notebook_html_artifact_id;
                      if (typeof htmlArtifactId === "string") {
                        await loadPreview(htmlArtifactId);
                      }
                      return job;
                    })
                  }
                  title="Generate model diagnostics notebook"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                </button>
              </div>
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
          isHtmlArtifactPreview(preview) ? (
            <HtmlArtifactPreview preview={preview} />
          ) : (
            <TranslatablePreview preview={preview} />
          )
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

function NotebooksTab({
  project,
  datasets,
  runs,
  artifacts,
  notebookIndex,
  busy,
  runAction,
  onAskAgent
}: {
  project: Project;
  datasets: DatasetSnapshot[];
  runs: Run[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  busy: boolean;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (message: string) => Promise<AgentChatResponse | void>;
}) {
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [guideDraft, setGuideDraft] = React.useState("");
  const [guideResponse, setGuideResponse] = React.useState<string | null>(null);
  const [guideBusy, setGuideBusy] = React.useState(false);
  const latestDataset = datasets[0] ?? null;
  const latestRun = runs[0] ?? null;
  const notebookItems = notebookIndex?.items ?? [];
  const recommendedNotebook = notebookIndex?.recommended_notebook ?? null;
  const fallbackDataNotebook = notebookItems.find((item) => item.notebook_kind === "data_understanding") ?? null;
  const divertedFromEmptyDiagnostics = isEmptyDiagnosticsNotebook(recommendedNotebook) && fallbackDataNotebook !== null;
  const reviewNotebook = divertedFromEmptyDiagnostics ? fallbackDataNotebook : recommendedNotebook;
  const executionArtifacts = artifacts.filter(
    (artifact) =>
      [
        "notebook_execution_plan",
        "notebook_execution_manifest",
        "notebook_execution_report",
        "notebook_execution_html",
        "notebook_figure_manifest",
        "notebook_execution_source",
        "notebook_evidence_bundle",
        "notebook_evidence_html",
        "notebook_evidence_svg"
      ].includes(artifact.asset_type) ||
      (artifact.asset_type === "agent_task_contract" && typeof artifact.metadata.notebook_artifact_id === "string")
  );
  const edaReviewArtifacts = artifacts.filter((artifact) =>
    ["eda_review_html", "eda_review_bundle", "eda_review_svg", "eda_review_report"].includes(artifact.asset_type)
  );
  const latestEdaReviewHtml =
    edaReviewArtifacts.find(
      (artifact) =>
        artifact.asset_type === "eda_review_html" &&
        (!latestDataset || artifact.metadata.dataset_snapshot_id === latestDataset.id)
    ) ?? null;
  const latestEdaReviewFigures = edaReviewArtifacts.filter(
    (artifact) =>
      artifact.asset_type === "eda_review_svg" &&
      (!latestDataset || artifact.metadata.dataset_snapshot_id === latestDataset.id)
  );
  const reviewArtifacts = [...edaReviewArtifacts, ...executionArtifacts];

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

  async function generateDataNotebook() {
    const job = await api<Job>(`/api/projects/${project.id}/analysis-notebooks/data-understanding`, {
      method: "POST"
    });
    const htmlArtifactId = job.output.notebook_html_artifact_id;
    if (typeof htmlArtifactId === "string") {
      await loadPreview(htmlArtifactId);
    }
    return job;
  }

  async function generateModelNotebook(run: Run) {
    const job = await api<Job>(`/api/runs/${run.id}/analysis-notebook`, { method: "POST" });
    const htmlArtifactId = job.output.notebook_html_artifact_id;
    if (typeof htmlArtifactId === "string") {
      await loadPreview(htmlArtifactId);
    }
    return job;
  }

  async function runEdaReview(dataset: DatasetSnapshot) {
    const job = await api<Job>(`/api/datasets/${dataset.id}/eda-review`, { method: "POST" });
    const htmlArtifactId = job.output.eda_review_html_artifact_id;
    if (typeof htmlArtifactId === "string") {
      await loadPreview(htmlArtifactId);
    }
    return job;
  }

  async function planNotebookExecution(item: NotebookIndexItem) {
    const job = await api<Job>(`/api/analysis-notebooks/${item.artifact_ids.notebook}/execution-plan`, {
      method: "POST"
    });
    const planArtifactId = job.output.notebook_execution_plan_artifact_id;
    if (typeof planArtifactId === "string") {
      await loadPreview(planArtifactId);
    }
    return job;
  }

  async function captureNotebookExecution(item: NotebookIndexItem) {
    const job = await api<Job>(`/api/analysis-notebooks/${item.artifact_ids.notebook}/execution-capture`, {
      method: "POST"
    });
    const htmlArtifactId = job.output.notebook_evidence_html_artifact_id ?? job.output.notebook_execution_html_artifact_id;
    if (typeof htmlArtifactId === "string") {
      await loadPreview(htmlArtifactId);
    }
    return job;
  }

  function artifactsForNotebook(item: NotebookIndexItem, assetTypes: string[]) {
    return executionArtifacts.filter(
      (artifact) => assetTypes.includes(artifact.asset_type) && artifact.metadata.notebook_artifact_id === item.notebook_artifact_id
    );
  }

  function latestArtifactForNotebook(item: NotebookIndexItem, assetTypes: string[]) {
    return assetTypes
      .map((assetType) => artifactsForNotebook(item, [assetType])[0])
      .find((artifact): artifact is Artifact => Boolean(artifact));
  }

  function notebookArtifactDisplayName(assetType: string) {
    const labels: Record<string, string> = {
      notebook_evidence_html: "Evidence narrative",
      notebook_evidence_svg: "Evidence figure",
      notebook_evidence_bundle: "Evidence bundle",
      notebook_execution_manifest: "Capture manifest",
      notebook_execution_report: "Capture report",
      notebook_execution_html: "Capture preview",
      notebook_figure_manifest: "Figure manifest",
      notebook_execution_plan: "Runner plan",
      notebook_execution_source: "Captured source",
      eda_review_html: "Data Review",
      eda_review_bundle: "Data Review bundle",
      eda_review_svg: "Data Review figure",
      eda_review_report: "Data Review report",
      agent_task_contract: "Agent contract"
    };
    return labels[assetType] ?? assetType.replace(/_/g, " ");
  }

  const reviewEvidenceHtml = reviewNotebook
    ? latestArtifactForNotebook(reviewNotebook, ["notebook_evidence_html", "notebook_execution_html"])
    : null;
  const reviewEvidenceBundle = reviewNotebook
    ? latestArtifactForNotebook(reviewNotebook, ["notebook_evidence_bundle"])
    : null;
  const reviewEvidenceFigures = reviewNotebook ? artifactsForNotebook(reviewNotebook, ["notebook_evidence_svg"]) : [];
  const reviewSafetyArtifact = reviewNotebook
    ? latestArtifactForNotebook(reviewNotebook, [
        "notebook_execution_manifest",
        "notebook_execution_report",
        "notebook_figure_manifest",
        "notebook_execution_plan",
        "agent_task_contract"
      ])
    : null;
  const readablePreviewArtifactId = reviewEvidenceHtml?.id ?? (reviewNotebook ? notebookPreviewArtifactId(reviewNotebook) : null);
  const hasExecutionPlan = Boolean(reviewNotebook?.coverage.has_execution_plan);
  const hasEvidenceCapture = Boolean(reviewNotebook?.coverage.has_execution_capture || reviewEvidenceHtml);
  const hasEvidenceFigures = reviewEvidenceFigures.length > 0;

  async function askNotebookGuide(message: string) {
    const trimmed = message.trim();
    if (!trimmed || !reviewNotebook) return;
    setGuideBusy(true);
    try {
      const response = await onAskAgent(
        `[notebook:${reviewNotebook.notebook_artifact_id}] ${trimmed}. Reply as an interactive notebook guide: name the exact section, artifact, or figure I should inspect next, why it matters, and what action Tablex should take.`
      );
      if (response && typeof response.assistant_message === "string") {
        setGuideResponse(response.assistant_message);
      }
    } finally {
      setGuideBusy(false);
    }
  }

  return (
    <div className="stack notebook-workbench">
      <Panel title="Notebook Review" icon={<BarChart3 size={18} />}>
        {reviewNotebook ? (
          <div className="notebook-review-grid">
            <div className="notebook-start-card">
              <div className="notebook-start-copy">
                <div className="eyebrow">Start here</div>
                <h3>{reviewNotebook.title}</h3>
                <p>{reviewNotebook.recommendation_reason}</p>
                {divertedFromEmptyDiagnostics ? (
                  <div className="banner warning compact">
                    A model diagnostics notebook exists, but it has no useful metric or prediction evidence yet. Tablex is routing you back to Data Understanding first.
                  </div>
                ) : null}
                <div className="badge-row">
                  <span className="badge">{reviewNotebook.notebook_kind.replace(/_/g, " ")}</span>
                  <span className="badge muted">{notebookSourceLabel(reviewNotebook)}</span>
                  <span className={notebookReadinessClass(reviewNotebook)}>{notebookReadinessLabel(reviewNotebook)}</span>
                  <span className={hasEvidenceCapture ? "badge" : "badge risk"}>
                    {hasEvidenceCapture ? "evidence captured" : "needs evidence capture"}
                  </span>
                </div>
              </div>
              <div className="notebook-primary-actions">
                <button
                  className="primary-button"
                  disabled={busy || latestDataset === null}
                  onClick={() => {
                    if (latestDataset) void runAction(() => runEdaReview(latestDataset));
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Run EDA Review
                </button>
                <button
                  className="secondary-button"
                  disabled={!readablePreviewArtifactId || previewLoadingId === readablePreviewArtifactId}
                  onClick={() => {
                    if (readablePreviewArtifactId) void loadPreview(readablePreviewArtifactId);
                  }}
                >
                  {readablePreviewArtifactId && previewLoadingId === readablePreviewArtifactId ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <Eye size={16} />
                  )}
                  Open Review
                </button>
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => void runAction(() => captureNotebookExecution(reviewNotebook))}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                  Capture Evidence
                </button>
              </div>
            </div>
            <div className="notebook-guide-card">
              <div>
                <div className="eyebrow">Interactive guide</div>
                <h3>Ask what to inspect next</h3>
                <p>Use Codex as a reading guide for this notebook. The response appears here and is also recorded in Agent Chat.</p>
              </div>
              <div className="notebook-guide-prompts">
                {[
                  "What should I read first in this notebook?",
                  "Which figure or evidence artifact matters most right now?",
                  "What should Codex investigate next before modeling?"
                ].map((prompt) => (
                  <button
                    className="secondary-button"
                    disabled={busy || guideBusy}
                    key={prompt}
                    onClick={() => void askNotebookGuide(prompt)}
                  >
                    {guideBusy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
                    {prompt}
                  </button>
                ))}
              </div>
              <form
                className="notebook-guide-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const message = guideDraft.trim();
                  if (!message) return;
                  setGuideDraft("");
                  void askNotebookGuide(message);
                }}
              >
                <input
                  value={guideDraft}
                  onChange={(event) => setGuideDraft(event.target.value)}
                  placeholder="Ask about this notebook review..."
                />
                <button className="icon-button" disabled={busy || guideBusy || !guideDraft.trim()} title="Ask notebook guide">
                  {guideBusy ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
                </button>
              </form>
              {guideResponse ? <div className="notebook-guide-response">{guideResponse}</div> : null}
            </div>
            <div className="notebook-steps" aria-label="Notebook evidence state">
              <div className="notebook-step done">
                <span>
                  <Check size={14} />
                </span>
                <strong>Notebook draft</strong>
                <small>{formatDate(reviewNotebook.created_at)}</small>
              </div>
              <div className={`notebook-step ${hasExecutionPlan ? "done" : "pending"}`}>
                <span>{hasExecutionPlan ? <Check size={14} /> : <ListChecks size={14} />}</span>
                <strong>Runner plan</strong>
                <small>{hasExecutionPlan ? "Contract ready" : "Optional before runner execution"}</small>
              </div>
              <div className={`notebook-step ${hasEvidenceCapture ? "done" : "pending"}`}>
                <span>{hasEvidenceCapture ? <Check size={14} /> : <Play size={14} />}</span>
                <strong>Evidence capture</strong>
                <small>{hasEvidenceFigures ? `${reviewEvidenceFigures.length} figures rendered` : "Profile evidence not rendered yet"}</small>
              </div>
            </div>
            <div className="metric-grid compact">
              <Metric label="Notebooks" value={notebookIndex?.counts.total ?? 0} />
              <Metric label="Captured" value={notebookIndex?.counts.with_execution_capture ?? 0} />
              <Metric label="Figures" value={reviewEvidenceFigures.length} />
              <Metric label="Data Review" value={latestEdaReviewHtml ? "ready" : "not run"} />
            </div>
          </div>
        ) : (
          <div className="notebook-start-card">
            <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="notebook-start-mascot" />
            <div className="notebook-start-copy">
              <div className="eyebrow">Start here</div>
              <h3>Create a Data Understanding notebook</h3>
              <p>Use the current profile and assumptions to create the first narrative review. Model diagnostics become available after a run exists.</p>
              <div className="row-actions">
                <button
                  className="primary-button"
                  disabled={busy || latestDataset === null}
                  onClick={() => {
                    if (latestDataset) void runAction(() => runEdaReview(latestDataset));
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Run EDA Review
                </button>
                <button className="secondary-button" disabled={busy} onClick={() => void runAction(generateDataNotebook)}>
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Data Notebook
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => {
                    if (latestRun) void runAction(() => generateModelNotebook(latestRun));
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
                  Model Notebook
                </button>
              </div>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Current Review" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {preview?.preview_available ? (
          isHtmlArtifactPreview(preview) ? (
            <HtmlArtifactPreview preview={preview} />
          ) : (
            <TranslatablePreview preview={preview} />
          )
        ) : (
          <EmptyInline text="Open Review to read the recommended notebook review here. Figures, evidence bundles, and runner records open in this same place so the result stays next to the action." />
        )}
      </Panel>

      <Panel title="Evidence Outputs" icon={<ListChecks size={18} />}>
        {reviewNotebook ? (
          <div className="stack">
            <div className="card-grid notebook-evidence-grid">
              <div className="mini-card notebook-evidence-card primary">
                <div className="mini-card-title">Data Review</div>
                <p>Controlled DuckDB EDA over the uploaded dataset: distributions, target relationships, findings, figures, and Codex next prompts.</p>
                <div className="badge-row">
                  <span className={latestEdaReviewHtml ? "badge" : "badge risk"}>
                    {latestEdaReviewHtml ? "ready" : "not run"}
                  </span>
                  {latestEdaReviewFigures.length ? <span className="badge muted">{latestEdaReviewFigures.length} figures</span> : null}
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={!latestEdaReviewHtml || previewLoadingId === latestEdaReviewHtml.id}
                    onClick={() => {
                      if (latestEdaReviewHtml) void loadPreview(latestEdaReviewHtml.id);
                    }}
                  >
                    {latestEdaReviewHtml && previewLoadingId === latestEdaReviewHtml.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <FileText size={16} />
                    )}
                    Open
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy || latestDataset === null}
                    onClick={() => {
                      if (latestDataset) void runAction(() => runEdaReview(latestDataset));
                    }}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    Run
                  </button>
                </div>
              </div>
              <div className="mini-card notebook-evidence-card primary">
                <div className="mini-card-title">Review narrative</div>
                <p>Target readiness, findings, guardrails, and rendered profile evidence in one readable page.</p>
                <div className="badge-row">
                  <span className={reviewEvidenceHtml ? "badge" : "badge risk"}>
                    {reviewEvidenceHtml ? "ready" : "not captured"}
                  </span>
                  {reviewEvidenceBundle ? <span className="badge muted">bundle saved</span> : null}
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={!reviewEvidenceHtml || previewLoadingId === reviewEvidenceHtml.id}
                    onClick={() => {
                      if (reviewEvidenceHtml) void loadPreview(reviewEvidenceHtml.id);
                    }}
                  >
                    {reviewEvidenceHtml && previewLoadingId === reviewEvidenceHtml.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <FileText size={16} />
                    )}
                    Preview
                  </button>
                </div>
              </div>
              <div className="mini-card notebook-evidence-card">
                <div className="mini-card-title">Figures</div>
                <p>Profile-backed SVG charts for missingness, semantic mix, target profile, and feature review queues.</p>
                <div className="badge-row">
                  <span className={hasEvidenceFigures ? "badge" : "badge muted"}>{reviewEvidenceFigures.length} rendered</span>
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={!reviewEvidenceFigures[0] || previewLoadingId === reviewEvidenceFigures[0]?.id}
                    onClick={() => {
                      if (reviewEvidenceFigures[0]) void loadPreview(reviewEvidenceFigures[0].id);
                    }}
                  >
                    {reviewEvidenceFigures[0] && previewLoadingId === reviewEvidenceFigures[0].id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <BarChart3 size={16} />
                    )}
                    First Figure
                  </button>
                </div>
              </div>
              <div className="mini-card notebook-evidence-card">
                <div className="mini-card-title">Runner record</div>
                <p>Plan, manifest, source, and safety policy for controlled runner handoff.</p>
                <div className="badge-row">
                  <span className={reviewSafetyArtifact ? "badge" : "badge muted"}>
                    {reviewSafetyArtifact ? notebookArtifactDisplayName(reviewSafetyArtifact.asset_type) : "not planned"}
                  </span>
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={!reviewSafetyArtifact || previewLoadingId === reviewSafetyArtifact.id}
                    onClick={() => {
                      if (reviewSafetyArtifact) void loadPreview(reviewSafetyArtifact.id);
                    }}
                  >
                    {reviewSafetyArtifact && previewLoadingId === reviewSafetyArtifact.id ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <ListChecks size={16} />
                    )}
                    Inspect
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void runAction(() => planNotebookExecution(reviewNotebook))}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    Plan
                  </button>
                </div>
              </div>
            </div>
            {reviewArtifacts.length ? (
              <details className="artifact-shelf">
                <summary>Artifact shelf ({reviewArtifacts.length})</summary>
                <Table
                  headers={["Artifact", "Status", "Created", "Actions"]}
                  rows={reviewArtifacts.slice(0, 12).map((artifact) => [
                    <div className="cell-stack" key={`${artifact.id}-label`}>
                      <span>{notebookArtifactDisplayName(artifact.asset_type)}</span>
                      <small>{String(artifact.metadata.figure_id ?? artifact.metadata.notebook_kind ?? artifact.id)}</small>
                    </div>,
                    String(artifact.metadata.execution_status ?? artifact.metadata.capture_mode ?? "ready"),
                    formatDate(artifact.created_at),
                    <div className="row-actions" key={artifact.id}>
                      <button
                        className="icon-button"
                        disabled={previewLoadingId === artifact.id}
                        onClick={() => void loadPreview(artifact.id)}
                        title="Preview artifact"
                      >
                        {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                      </button>
                      <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download artifact">
                        <Download size={16} />
                      </a>
                    </div>
                  ])}
                />
              </details>
            ) : null}
          </div>
        ) : (
          <EmptyInline text="Notebook evidence will appear after a Data Understanding or Model Diagnostics notebook is generated." />
        )}
      </Panel>

      <Panel title="Notebook Library" icon={<FileText size={18} />}>
        {notebookItems.length ? (
          <Table
            headers={["Notebook", "State", "Actions"]}
            rows={notebookItems.slice(0, 8).map((item) => [
              <div className="cell-stack" key={`${item.notebook_artifact_id}-title`}>
                <span>{item.title}</span>
                <small>
                  {item.notebook_kind.replace(/_/g, " ")} | {notebookSourceLabel(item)}
                </small>
              </div>,
              <div className="badge-row" key={`${item.notebook_artifact_id}-state`}>
                <span className="badge muted">{notebookCoverageLabel(item)}</span>
                <span className={notebookReadinessClass(item)}>{notebookReadinessLabel(item)}</span>
                {item.notebook_artifact_id === reviewNotebook?.notebook_artifact_id ? <span className="badge">current</span> : null}
              </div>,
              <div className="row-actions" key={`${item.notebook_artifact_id}-actions`}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === notebookPreviewArtifactId(item)}
                  onClick={() => void loadPreview(notebookPreviewArtifactId(item))}
                  title="Preview notebook"
                >
                  {previewLoadingId === notebookPreviewArtifactId(item) ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => captureNotebookExecution(item))}
                  title="Capture evidence"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${item.artifact_ids.notebook}/download`} title="Download marimo source">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Notebook history will appear here after Data Understanding or run-level diagnostics notebooks are generated." />
        )}
      </Panel>

    </div>
  );
}

function ReportsTab({
  project,
  reports,
  decisionReport,
  artifacts,
  visualizations,
  notebookIndex,
  insights,
  busy,
  runAction
}: {
  project: Project;
  reports: Report[];
  decisionReport: DecisionReportCurrent | null;
  artifacts: Artifact[];
  visualizations: VisualizationSpec[];
  notebookIndex: NotebookIndex | null;
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
  const analysisNotebookArtifacts = artifacts.filter((artifact) =>
    [
      "analysis_notebook",
      "notebook_html",
      "notebook_run_manifest",
      "notebook_report",
      "notebook_execution_plan",
      "notebook_execution_manifest",
      "notebook_execution_report",
      "notebook_execution_html",
      "notebook_figure_manifest",
      "notebook_execution_source",
      "notebook_evidence_bundle",
      "notebook_evidence_html",
      "notebook_evidence_svg"
    ].includes(artifact.asset_type) ||
    (artifact.asset_type === "agent_task_contract" && typeof artifact.metadata.notebook_artifact_id === "string")
  );
  const guidedJourneyArtifacts = artifacts.filter((artifact) =>
    [
      "guided_journey_snapshot",
      "guided_journey_report",
      "guided_journey_comparison",
      "guided_journey_comparison_report"
    ].includes(artifact.asset_type)
  );
  const guidedJourneySnapshots = guidedJourneyArtifacts.filter((artifact) => artifact.asset_type === "guided_journey_snapshot");
  const guidedJourneyComparisons = guidedJourneyArtifacts.filter((artifact) => artifact.asset_type === "guided_journey_comparison");
  const recommendedNotebook = notebookIndex?.recommended_notebook ?? null;
  const currentDecisionBundle = decisionReport?.bundle ?? null;
  const currentDecisionReportId = textField(decisionReport?.report?.id);
  const readiness = currentDecisionBundle?.readiness ?? {};
  const coverage = currentDecisionBundle?.coverage_summary ?? {};
  const evidenceMap = currentDecisionBundle?.evidence_map ?? [];
  const nextActions = currentDecisionBundle?.next_actions ?? [];
  const provenEvidence = evidenceMap.filter((row) => textField(row.status) === "ready").slice(0, 5);
  const attentionEvidence = evidenceMap.filter((row) => textField(row.status) !== "ready").slice(0, 5);
  const readinessStatus = textField(readiness.status) ?? (decisionReport?.available ? "ready" : "missing");
  const readinessHeadline =
    textField(readiness.headline) ??
    (decisionReport?.available
      ? "Decision report is available for review."
      : "Generate a decision report to synthesize the current project evidence.");
  const autoPreviewedReportRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (currentDecisionReportId && autoPreviewedReportRef.current !== currentDecisionReportId) {
      autoPreviewedReportRef.current = currentDecisionReportId;
      void loadReportPreview(currentDecisionReportId);
    }
  }, [currentDecisionReportId]);

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

  async function planNotebookExecution(item: NotebookIndexItem) {
    const job = await api<Job>(`/api/analysis-notebooks/${item.artifact_ids.notebook}/execution-plan`, {
      method: "POST"
    });
    const planArtifactId = job.output.notebook_execution_plan_artifact_id;
    if (typeof planArtifactId === "string") {
      await loadArtifactPreview(planArtifactId);
    }
    return job;
  }

  async function generateDecisionReport() {
    const job = await api<Job>(`/api/projects/${project.id}/decision-report/generate`, { method: "POST" });
    const reportId = textField(job.output.report_id);
    if (reportId) {
      autoPreviewedReportRef.current = reportId;
      await loadReportPreview(reportId);
    }
    return job;
  }

  return (
    <div className="stack">
      <section className="decision-report-hero">
        <div className="decision-report-copy">
          <div className="eyebrow">Current decision report</div>
          <h3>{readinessHeadline}</h3>
          <p>
            Tablex synthesizes Data Review, assumptions, evaluation design, notebooks, experiments, runner outputs,
            citation audits, lineage, and next actions into one in-product report.
          </p>
          <div className="badge-row">
            <span className={decisionReportStatusClass(readinessStatus)}>{readinessStatus.replace(/_/g, " ")}</span>
            {decisionReport?.generated_at ? <span className="badge muted">{formatDate(decisionReport.generated_at)}</span> : null}
            {currentDecisionBundle ? <span className="badge muted">{currentDecisionBundle.schema_version}</span> : null}
          </div>
          <div className="row-actions">
            <button className="primary-button" disabled={busy} onClick={() => void runAction(generateDecisionReport)}>
              {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
              Generate Decision Report
            </button>
            <button
              className="secondary-button"
              disabled={!currentDecisionReportId || previewLoadingId === currentDecisionReportId}
              onClick={() => currentDecisionReportId && void loadReportPreview(currentDecisionReportId)}
            >
              {previewLoadingId === currentDecisionReportId ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
              Open Current
            </button>
            {currentDecisionReportId ? (
              <a className="icon-link" href={`${apiBase}/api/reports/${currentDecisionReportId}/download`} title="Download decision report">
                <Download size={16} />
              </a>
            ) : null}
          </div>
        </div>
        <div className="decision-report-score">
          <Metric label="Ready" value={String(coverage.ready_count ?? 0)} />
          <Metric label="Needs attention" value={String(coverage.attention_count ?? 0)} />
          <Metric label="Missing" value={String(coverage.missing_count ?? 0)} />
          <Metric label="Sources" value={String(currentDecisionBundle?.source_assets.length ?? 0)} />
        </div>
        <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="decision-report-mascot" />
      </section>
      {currentDecisionBundle ? (
        <Panel title="Read This First" icon={<FileText size={18} />}>
          <div className="decision-read-grid">
            <div className="decision-read-column">
              <h3>What is proven</h3>
              {provenEvidence.length ? (
                provenEvidence.map((row) => (
                  <div className="decision-read-item" key={`proven-${textField(row.area) ?? JSON.stringify(row)}`}>
                    <strong>{textField(row.area) ?? "Evidence"}</strong>
                    <p>{textField(row.summary) ?? "No summary recorded."}</p>
                  </div>
                ))
              ) : (
                <EmptyInline text="No evidence area is ready yet." />
              )}
            </div>
            <div className="decision-read-column">
              <h3>What needs attention</h3>
              {attentionEvidence.length ? (
                attentionEvidence.map((row) => (
                  <div className="decision-read-item" key={`attention-${textField(row.area) ?? JSON.stringify(row)}`}>
                    <strong>{textField(row.area) ?? "Evidence"}</strong>
                    <p>{textField(row.summary) ?? "No summary recorded."}</p>
                  </div>
                ))
              ) : (
                <EmptyInline text="No attention item was generated." />
              )}
            </div>
          </div>
        </Panel>
      ) : null}
      {nextActions.length ? (
        <Panel title="Next Actions" icon={<ListChecks size={18} />}>
          <div className="decision-next-list">
            {nextActions.slice(0, 5).map((item, index) => (
              <div className="decision-next-item" key={`${textField(item.title) ?? "action"}-${index}`}>
                <span>{String(item.priority ?? index + 1)}</span>
                <div>
                  <strong>{textField(item.title) ?? "Review next action"}</strong>
                  <p>{textField(item.reason) ?? "No reason was recorded."}</p>
                  <small>{textField(item.target_tab) ?? "Reports"}</small>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
      <Panel title="Evidence Coverage" icon={<ListChecks size={18} />}>
        {evidenceMap.length ? (
          <div className="decision-evidence-grid">
            {evidenceMap.map((row) => (
              <div className="decision-evidence-row" key={textField(row.area) ?? JSON.stringify(row)}>
                <div>
                  <strong>{textField(row.area) ?? "Evidence"}</strong>
                  <p>{textField(row.summary) ?? "No summary recorded."}</p>
                </div>
                <span className={decisionReportStatusClass(textField(row.status) ?? "missing")}>
                  {(textField(row.status) ?? "missing").replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text="Evidence coverage will appear after the decision report bundle is generated." />
        )}
      </Panel>
      <Panel title="Full Report Text" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {reportPreview?.preview_available ? (
          isHtmlArtifactPreview(reportPreview) ? (
            <HtmlArtifactPreview preview={reportPreview} />
          ) : (
            <TranslatablePreview
              preview={reportPreview}
              sourceType={reportPreviewSource?.type ?? "artifact"}
              sourceId={reportPreviewSource?.id ?? reportPreview.id}
            />
          )
        ) : (
          <EmptyInline text={reportPreview?.reason ?? "Generate a decision report to read the current project state here."} />
        )}
      </Panel>
      <details className="report-supporting-details">
        <summary>
          <span>Supporting report shelves</span>
          <small>Notebooks, insights, prior reports, visualizations, and debug artifacts</small>
        </summary>
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
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/analysis-notebooks/data-understanding`, {
                method: "POST"
              });
              const htmlArtifactId = job.output.notebook_html_artifact_id;
              if (typeof htmlArtifactId === "string") {
                await loadArtifactPreview(htmlArtifactId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
          Analysis Notebook
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
        <button
          className="secondary-button"
          disabled={busy || guidedJourneySnapshots.length < 2}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/guidance/snapshots/compare`, { method: "POST" });
              const reportId = job.output.guided_journey_comparison_report_id;
              if (typeof reportId === "string") {
                await loadReportPreview(reportId);
              }
              return job;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <GitBranch size={16} />}
          Compare Journey
        </button>
        </div>
      <Panel title="Notebook Center" icon={<BarChart3 size={18} />}>
        {notebookIndex && notebookIndex.counts.total > 0 ? (
          <div className="stack">
            {recommendedNotebook ? (
              <div className="focus-card">
                <div>
                  <div className="eyebrow">Recommended notebook</div>
                  <h3>{recommendedNotebook.title}</h3>
                  <p>{recommendedNotebook.recommendation_reason}</p>
                  <div className="badge-row">
                    <span className="badge">{recommendedNotebook.notebook_kind.replace(/_/g, " ")}</span>
                    <span className="badge muted">{notebookCoverageLabel(recommendedNotebook)}</span>
                    {recommendedNotebook.run_id ? <span className="badge muted">run {recommendedNotebook.run_id}</span> : null}
                  </div>
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    disabled={previewLoadingId === notebookPreviewArtifactId(recommendedNotebook)}
                    onClick={() => void loadArtifactPreview(notebookPreviewArtifactId(recommendedNotebook))}
                  >
                    {previewLoadingId === notebookPreviewArtifactId(recommendedNotebook) ? (
                      <Loader2 className="spin" size={16} />
                    ) : (
                      <Eye size={16} />
                    )}
                    Preview
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void runAction(() => planNotebookExecution(recommendedNotebook))}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                    Plan Execution
                  </button>
                  <a
                    className="icon-link"
                    href={`${apiBase}/api/artifacts/${recommendedNotebook.artifact_ids.notebook}/download`}
                    title="Download marimo source"
                  >
                    <Download size={16} />
                  </a>
                </div>
              </div>
            ) : null}
            <div className="metric-grid compact">
              <Metric label="Notebooks" value={notebookIndex.counts.total} />
              <Metric label="HTML previews" value={notebookIndex.counts.with_html_preview} />
              <Metric label="Reports" value={notebookIndex.counts.with_report} />
              <Metric label="Captured" value={notebookIndex.counts.with_execution_capture} />
            </div>
            <Table
              headers={["Notebook", "Source", "Coverage", "Created", "Actions"]}
              rows={notebookIndex.items.slice(0, 8).map((item) => [
                <div className="cell-stack" key={`${item.notebook_artifact_id}-title`}>
                  <span>{item.title}</span>
                  <small>{item.notebook_kind.replace(/_/g, " ")}</small>
                </div>,
                notebookSourceLabel(item),
                notebookCoverageLabel(item),
                formatDate(item.created_at),
                <div className="row-actions" key={`${item.notebook_artifact_id}-actions`}>
                  <button
                    className="icon-button"
                    disabled={previewLoadingId === notebookPreviewArtifactId(item)}
                    onClick={() => void loadArtifactPreview(notebookPreviewArtifactId(item))}
                    title="Preview notebook"
                  >
                    {previewLoadingId === notebookPreviewArtifactId(item) ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => planNotebookExecution(item))}
                    title="Plan controlled notebook execution"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                  </button>
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${item.artifact_ids.notebook}/download`} title="Download marimo source">
                    <Download size={16} />
                  </a>
                </div>
              ])}
            />
          </div>
        ) : (
          <EmptyInline text="Generate a Data Understanding notebook or a run-level Model Diagnostics notebook to create a guided notebook history here." />
        )}
      </Panel>
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
      <Panel title="Analysis Notebooks" icon={<BarChart3 size={18} />}>
        {analysisNotebookArtifacts.length ? (
          <Table
            headers={["Type", "Kind", "Status", "Artifact", "Created", "Actions"]}
            rows={analysisNotebookArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.notebook_kind ?? "-"),
              String(artifact.metadata.execution_status ?? artifact.metadata.render_mode ?? "ready"),
              artifact.id,
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadArtifactPreview(artifact.id)}
                  title="Preview notebook artifact"
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download notebook artifact">
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Analysis notebooks will appear here as marimo source, in-product HTML preview, run manifest, and Markdown report artifacts. They are generated from current data understanding and can later be extended with experiment diagnostics." />
        )}
      </Panel>
      <Panel title="Guidance History" icon={<GitBranch size={18} />}>
        {guidedJourneyArtifacts.length ? (
          <div className="stack">
            <Table
              headers={["Type", "Stage", "Focus", "Version", "Created", "Actions"]}
              rows={guidedJourneyArtifacts.slice(0, 10).map((artifact) => [
                artifact.asset_type,
                String(artifact.metadata.current_stage_id ?? "-"),
                String(
                  artifact.metadata.recommended_focus_key ??
                    artifact.metadata.recommended_focus_changed ??
                    artifact.metadata.changed_stage_count ??
                    "-"
                ),
                `v${artifact.version}`,
                formatDate(artifact.created_at),
                <div className="row-actions" key={artifact.id}>
                  <button
                    className="icon-button"
                    disabled={previewLoadingId === artifact.id}
                    onClick={() => void loadArtifactPreview(artifact.id)}
                    title="Preview guidance artifact"
                  >
                    {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                  </button>
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download guidance artifact">
                    <Download size={16} />
                  </a>
                </div>
              ])}
            />
            <div className="metric-grid compact">
              <Metric label="Snapshots" value={guidedJourneySnapshots.length} />
              <Metric label="Comparisons" value={guidedJourneyComparisons.length} />
              <Metric
                label="Latest stage"
                value={String(guidedJourneySnapshots[0]?.metadata.current_stage_id ?? "-")}
              />
              <Metric
                label="Latest focus"
                value={String(guidedJourneySnapshots[0]?.metadata.recommended_focus_key ?? "-")}
              />
            </div>
          </div>
        ) : (
          <EmptyInline text="Saved Guided Journey snapshots and comparisons will appear here with previews, downloads, and lineage-backed reports." />
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
      </details>
    </div>
  );
}

function decisionReportStatusClass(status: string) {
  if (["ready", "ready_for_review", "ready_for_agent_review"].includes(status)) return "badge success";
  if (["blocked", "needs_attention", "needs_feature_review"].includes(status)) return "badge risk";
  if (["partial", "missing", "needs_plan", "needs_recipe", "needs_diagnostics"].includes(status)) return "badge warning";
  return "badge muted";
}

function notebookPreviewArtifactId(item: NotebookIndexItem) {
  return item.artifact_ids.html_preview ?? item.artifact_ids.report_artifact ?? item.artifact_ids.notebook;
}

function notebookCoverageLabel(item: NotebookIndexItem) {
  const flags = [
    item.coverage.has_html_preview ? "preview" : null,
    item.coverage.has_report ? "report" : null,
    item.coverage.has_visualization ? "visual" : null,
    item.coverage.has_manifest ? "manifest" : null,
    item.coverage.has_execution_plan ? "plan" : null,
    item.coverage.has_execution_capture ? "capture" : null
  ].filter(Boolean);
  return flags.length ? flags.join(" / ") : "source only";
}

function isEmptyDiagnosticsNotebook(item: NotebookIndexItem | null) {
  if (!item || item.notebook_kind !== "model_diagnostics") return false;
  return String(item.content?.readiness ?? item.coverage.content_readiness ?? "") === "not_ready";
}

function notebookReadinessLabel(item: NotebookIndexItem) {
  const readiness = String(item.content?.readiness ?? item.coverage.content_readiness ?? "unknown");
  const labels: Record<string, string> = {
    evidence_ready: "evidence ready",
    narrative_ready: "narrative ready",
    partial_review: "partial review",
    not_ready: "not ready",
    source_only: "source only",
    unknown: "unknown"
  };
  return labels[readiness] ?? readiness.replace(/_/g, " ");
}

function notebookReadinessClass(item: NotebookIndexItem) {
  const readiness = String(item.content?.readiness ?? item.coverage.content_readiness ?? "unknown");
  if (readiness === "evidence_ready" || readiness === "narrative_ready") return "badge";
  if (readiness === "not_ready") return "badge risk";
  return "badge muted";
}

function notebookSourceLabel(item: NotebookIndexItem) {
  if (item.run_id) return `run ${item.run_id}`;
  if (item.dataset_snapshot_id) return `dataset ${item.dataset_snapshot_id}`;
  return "project";
}

type RelationalCatalogTable = {
  table_name?: string;
  path?: string;
  role?: string;
  is_primary?: boolean;
  row_count?: number;
  column_count?: number;
  status?: string;
  target_column_present?: boolean;
  key_candidates?: Array<{ column?: string; reason?: string; uniqueness_ratio?: number }>;
};

type RelationalCatalogRelationship = {
  left_table?: string;
  right_table?: string;
  left_column?: string;
  right_column?: string;
  relation_type?: string;
  confidence?: number;
  evidence?: string;
};

type RelationalCatalogPayload = {
  schema_version?: string;
  benchmark_name?: string;
  table_count?: number;
  relationship_count?: number;
  tables?: RelationalCatalogTable[];
  relationships?: RelationalCatalogRelationship[];
  risk_notes?: string[];
};

function isRelationalCatalogPreview(preview: ArtifactPreview | null): boolean {
  return Boolean(
    preview?.preview_available &&
      preview.asset_type === "relational_catalog" &&
      preview.preview &&
      preview.preview.includes("relational_catalog.v1")
  );
}

function parseRelationalCatalogPreview(preview: ArtifactPreview): RelationalCatalogPayload | null {
  if (!preview.preview) return null;
  try {
    const parsed = JSON.parse(preview.preview) as RelationalCatalogPayload;
    return parsed && parsed.schema_version === "relational_catalog.v1" ? parsed : null;
  } catch {
    return null;
  }
}

function RelationalCatalogPreview({ preview }: { preview: ArtifactPreview }) {
  const catalog = React.useMemo(() => parseRelationalCatalogPreview(preview), [preview]);
  if (!catalog) return <TranslatablePreview preview={preview} />;
  const tables = Array.isArray(catalog.tables) ? catalog.tables.slice(0, 12) : [];
  const relationships = Array.isArray(catalog.relationships) ? catalog.relationships.slice(0, 24) : [];
  const tableNames = new Set(tables.map((table) => table.table_name).filter(Boolean));
  const visibleRelationships = relationships.filter(
    (relationship) => relationship.left_table && relationship.right_table && tableNames.has(relationship.left_table) && tableNames.has(relationship.right_table)
  );
  return (
    <div className="relational-preview">
      <div className="relational-preview-header">
        <div>
          <div className="eyebrow">ER-style preview</div>
          <h3>{catalog.benchmark_name ?? preview.name}</h3>
          <p>Tables and inferred relationship candidates from the RelationalCatalog. Treat edges as review prompts until join semantics are confirmed.</p>
        </div>
        <div className="badge-row">
          <span className="badge">{catalog.table_count ?? tables.length} tables</span>
          <span className="badge muted">{relationships.length} relationships</span>
          <span className="badge risk">inferred</span>
        </div>
      </div>
      <RelationalErSvg tables={tables} relationships={visibleRelationships} />
      <div className="relational-summary-grid">
        {tables.slice(0, 6).map((table) => (
          <div className="relational-table-card" key={table.table_name ?? table.path}>
            <div className="mini-card-title">{table.table_name ?? table.path ?? "table"}</div>
            <div className="badge-row">
              {table.is_primary ? <span className="badge">primary</span> : <span className="badge muted">{table.role ?? "support"}</span>}
              {table.target_column_present ? <span className="badge risk">target present</span> : null}
            </div>
            <dl className="facts">
              <div>
                <dt>Rows</dt>
                <dd>{table.row_count?.toLocaleString() ?? "-"}</dd>
              </div>
              <div>
                <dt>Columns</dt>
                <dd>{table.column_count ?? "-"}</dd>
              </div>
              <div>
                <dt>Keys</dt>
                <dd>{table.key_candidates?.slice(0, 3).map((key) => key.column).join(", ") || "-"}</dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
      {catalog.risk_notes?.length ? (
        <div className="relational-risk-strip">
          {catalog.risk_notes.slice(0, 4).map((note) => (
            <span key={note}>{note}</span>
          ))}
        </div>
      ) : null}
      <details className="artifact-shelf">
        <summary>Advanced JSON catalog</summary>
        <TranslatablePreview preview={preview} />
      </details>
    </div>
  );
}

function RelationalErSvg({
  tables,
  relationships
}: {
  tables: RelationalCatalogTable[];
  relationships: RelationalCatalogRelationship[];
}) {
  const visibleTables = tables.slice(0, 10);
  if (!visibleTables.length) return <EmptyInline text="No tables are available in this relational catalog." />;
  const columns = Math.min(3, Math.max(1, visibleTables.length));
  const cardWidth = 220;
  const cardHeight = 104;
  const gapX = 62;
  const gapY = 72;
  const padding = 32;
  const rows = Math.ceil(visibleTables.length / columns);
  const width = padding * 2 + columns * cardWidth + (columns - 1) * gapX;
  const height = padding * 2 + rows * cardHeight + (rows - 1) * gapY;
  const positions = new Map<string, { x: number; y: number }>();
  visibleTables.forEach((table, index) => {
    const x = padding + (index % columns) * (cardWidth + gapX);
    const y = padding + Math.floor(index / columns) * (cardHeight + gapY);
    if (table.table_name) positions.set(table.table_name, { x, y });
  });
  return (
    <div className="relational-svg-shell">
      <svg className="relational-er-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Relational catalog ER diagram">
        <defs>
          <marker id="er-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
        </defs>
        {relationships.slice(0, 32).map((relationship, index) => {
          const left = relationship.left_table ? positions.get(relationship.left_table) : undefined;
          const right = relationship.right_table ? positions.get(relationship.right_table) : undefined;
          if (!left || !right) return null;
          const x1 = left.x + cardWidth / 2;
          const y1 = left.y + cardHeight / 2;
          const x2 = right.x + cardWidth / 2;
          const y2 = right.y + cardHeight / 2;
          return (
            <g className="er-edge" key={`${relationship.left_table}-${relationship.right_table}-${index}`}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} markerEnd="url(#er-arrow)" />
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6}>
                {relationship.left_column ?? relationship.right_column ?? "key"}
              </text>
            </g>
          );
        })}
        {visibleTables.map((table, index) => {
          const position = table.table_name ? positions.get(table.table_name) : undefined;
          if (!position) return null;
          const keyNames = table.key_candidates?.slice(0, 2).map((key) => key.column).filter(Boolean).join(", ") || "no key hint";
          return (
            <g className={`er-node ${table.is_primary ? "primary" : ""}`} key={`${table.table_name}-${index}`}>
              <rect x={position.x} y={position.y} width={cardWidth} height={cardHeight} rx="8" />
              <text className="er-node-title" x={position.x + 14} y={position.y + 28}>
                {truncateLabel(table.table_name ?? table.path ?? "table", 24)}
              </text>
              <text x={position.x + 14} y={position.y + 52}>
                {table.is_primary ? "primary table" : table.role ?? "supporting table"}
              </text>
              <text x={position.x + 14} y={position.y + 74}>
                {`${table.row_count?.toLocaleString() ?? "-"} rows / ${table.column_count ?? "-"} cols`}
              </text>
              <text x={position.x + 14} y={position.y + 94}>
                {truncateLabel(keyNames, 30)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function truncateLabel(value: string, length: number) {
  return value.length > length ? `${value.slice(0, Math.max(0, length - 1))}...` : value;
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
