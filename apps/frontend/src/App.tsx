import React from "react";
import { englishMessages, japaneseMessages, type LocaleMessages } from "./copy";
import { LocaleContext, useLocale } from "./locale";
import { ResearchPlanTimeline, primaryResearchPlanFocusBlock, researchPlanBlockRuntimeAwareStatusLabel, researchPlanStatusLabel } from "./components/ResearchPlanTimeline";
import { AgentChatDock, TurnStateBar, UserAvatar, agentInputFormClassName, turnStateLabel } from "./components/AgentChatDock";
import { FocusedEvidenceReader, HtmlArtifactPreview, NativeMarimoFrame, NativeMarimoLoadingPanel, TranslatablePreview, VisualArtifactPreview, isHtmlArtifactPreview, isVisualArtifactPreview } from "./components/ArtifactPreview";
import { ArtifactLineagePanel } from "./components/ArtifactLineagePanel";
import { AgentActivityRail, hasLiveAgentOrModelActivity, humanizeLabel, jobActiveForActivity, optimisticWorkerEvent, workerEventsFromJob, workerStatusLabel } from "./components/AgentActivityRail";
import { LeaderboardTab, metricLabel } from "./components/LeaderboardTab";
import { RawAgentStream } from "./components/RawAgentStream";
import { RawTab } from "./components/RawTab";
import { buildRawAgentEvents, maxTranscriptEventIndex, mergeTranscriptEvents } from "./components/rawEvents";
import { AuthGate } from "./components/AuthGate";
import { ProjectDeleteDialog } from "./components/ProjectDeleteDialog";
import { PortalView } from "./components/PortalView";
import { EmptyInline, EmptyState, LoadingBlock, Metric, Panel, Table } from "./components/Primitives";
import {
  RelatedNotebookLinks,
  conciseNotebookTitle,
  notebookNeedsAttention,
  preferredNotebookForArtifact,
  preferredNotebookItems,
  sortRelatedNotebookItems
} from "./components/NotebookLinks";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  BookOpen,
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
  Minus,
  Moon,
  Maximize2,
  PieChart,
  Play,
  Plus,
  Power,
  RefreshCw,
  Search,
  Send,
  Settings as SettingsIcon,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  X
} from "lucide-react";
import "./styles.css";

type DisplayTheme = "light" | "dark" | "matrix";
type LocaleDirection = "ltr" | "rtl";
type LocaleSource = "built_in" | "dynamic";
type ChatSubmitShortcutSetting = "locale_default" | "enter" | "shift_enter";
type ChatSubmitShortcut = "enter" | "shift_enter";

type UserSettings = {
  locale: string;
  requestedLocale: string;
  dynamicLanguageRequest: string;
  displayTheme: DisplayTheme;
  showDetailedTabs: boolean;
  interventionCountdownSeconds: number;
  agentModel: string;
  utilityModel: string;
  chatSubmitShortcut: ChatSubmitShortcutSetting;
  userAvatarDataUrl: string | null;
};

type AuthUser = {
  id: string;
  email: string;
  display_name: string | null;
  auth_provider: string;
  is_admin: boolean;
  settings: Partial<UserSettings>;
  created_at: string;
  updated_at: string;
};

type AuthStatus = {
  auth_enabled: boolean;
  authenticated: boolean;
  password_auth_enabled: boolean;
  google_auth_enabled: boolean;
  bootstrap_required: boolean;
  user: AuthUser | null;
};

type AvatarCandidate = {
  id: string;
  data_url: string;
  model: string;
  revised_prompt: string | null;
};

type AvatarCandidateJobOutput = {
  candidates?: AvatarCandidate[];
};

type StorageUsage = {
  schema_version: string;
  total_bytes: number;
  categories: Record<string, number>;
};

const userSettingsStorageKey = "tablex.userSettings.v1";
const dynamicLocaleStorageKey = "tablex.dynamicLocalePacks.v1";

const defaultUserSettings: UserSettings = {
  locale: "en-US",
  requestedLocale: "",
  dynamicLanguageRequest: "",
  displayTheme: "light",
  showDetailedTabs: false,
  interventionCountdownSeconds: 15,
  agentModel: "codex-default",
  utilityModel: "utility-default",
  chatSubmitShortcut: "locale_default",
  userAvatarDataUrl: null
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
      displayTheme: isDisplayTheme(parsed.displayTheme) ? parsed.displayTheme : "light",
      showDetailedTabs: parsed.showDetailedTabs === true,
      interventionCountdownSeconds:
        typeof parsed.interventionCountdownSeconds === "number" && Number.isFinite(parsed.interventionCountdownSeconds)
          ? Math.max(0, Math.min(300, Math.round(parsed.interventionCountdownSeconds)))
          : defaultUserSettings.interventionCountdownSeconds,
      agentModel: typeof parsed.agentModel === "string" && parsed.agentModel.trim() ? parsed.agentModel : defaultUserSettings.agentModel,
      utilityModel:
        typeof parsed.utilityModel === "string" && parsed.utilityModel.trim()
          ? parsed.utilityModel
          : defaultUserSettings.utilityModel,
      chatSubmitShortcut: isChatSubmitShortcutSetting(parsed.chatSubmitShortcut)
        ? parsed.chatSubmitShortcut
        : defaultUserSettings.chatSubmitShortcut,
      userAvatarDataUrl:
        typeof parsed.userAvatarDataUrl === "string" && parsed.userAvatarDataUrl.startsWith("data:image/")
          ? parsed.userAvatarDataUrl
          : null
    };
  } catch {
    return defaultUserSettings;
  }
}

function mergeServerUserSettings(current: UserSettings, serverSettings: Partial<UserSettings>): UserSettings {
  return {
    ...current,
    locale: typeof serverSettings.locale === "string" ? serverSettings.locale : current.locale,
    requestedLocale:
      typeof serverSettings.requestedLocale === "string" ? serverSettings.requestedLocale : current.requestedLocale,
    dynamicLanguageRequest:
      typeof serverSettings.dynamicLanguageRequest === "string"
        ? serverSettings.dynamicLanguageRequest
        : current.dynamicLanguageRequest,
    displayTheme: isDisplayTheme(serverSettings.displayTheme) ? serverSettings.displayTheme : current.displayTheme,
    showDetailedTabs:
      typeof serverSettings.showDetailedTabs === "boolean" ? serverSettings.showDetailedTabs : current.showDetailedTabs,
    interventionCountdownSeconds:
      typeof serverSettings.interventionCountdownSeconds === "number" &&
      Number.isFinite(serverSettings.interventionCountdownSeconds)
        ? Math.max(0, Math.min(300, Math.round(serverSettings.interventionCountdownSeconds)))
        : current.interventionCountdownSeconds,
    agentModel:
      typeof serverSettings.agentModel === "string" && serverSettings.agentModel.trim()
        ? serverSettings.agentModel
        : current.agentModel,
    utilityModel:
      typeof serverSettings.utilityModel === "string" && serverSettings.utilityModel.trim()
        ? serverSettings.utilityModel
        : current.utilityModel,
    chatSubmitShortcut: isChatSubmitShortcutSetting(serverSettings.chatSubmitShortcut)
      ? serverSettings.chatSubmitShortcut
      : current.chatSubmitShortcut,
    userAvatarDataUrl:
      typeof serverSettings.userAvatarDataUrl === "string" && serverSettings.userAvatarDataUrl.startsWith("data:image/")
        ? serverSettings.userAvatarDataUrl
        : serverSettings.userAvatarDataUrl === null
          ? null
          : current.userAvatarDataUrl
  };
}

function isChatSubmitShortcutSetting(value: unknown): value is ChatSubmitShortcutSetting {
  return value === "locale_default" || value === "enter" || value === "shift_enter";
}

function isDisplayTheme(value: unknown): value is DisplayTheme {
  return value === "light" || value === "dark" || value === "matrix";
}

function displayThemeLabel(theme: DisplayTheme, text: LocaleMessages): string {
  if (theme === "dark") return text.darkTheme;
  if (theme === "matrix") return text.matrixTheme;
  return text.lightTheme;
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

function resolveChatSubmitShortcut(settings: UserSettings): ChatSubmitShortcut {
  if (settings.chatSubmitShortcut === "enter") return "enter";
  if (settings.chatSubmitShortcut === "shift_enter") return "shift_enter";
  return localePrefersShiftEnter(settings.locale) ? "shift_enter" : "enter";
}

function localePrefersShiftEnter(locale: string): boolean {
  const normalized = locale.trim().toLowerCase();
  return (
    normalized.startsWith("ja") ||
    normalized.startsWith("zh") ||
    normalized.startsWith("ko") ||
    normalized.startsWith("日本語") ||
    normalized.includes("japanese") ||
    normalized.includes("chinese") ||
    normalized.includes("korean")
  );
}

function localeLanguage(locale: string | null | undefined): string {
  const normalized = (locale ?? "").trim().toLowerCase().replace("_", "-");
  if (!normalized) return "";
  if (normalized.includes("japanese") || normalized.includes("日本語")) return "ja";
  return normalized.split("-", 1)[0];
}

function localeLooksJapanese(locale: string | null | undefined): boolean {
  const normalized = (locale ?? "").trim().toLowerCase().replace("_", "-");
  if (!normalized) return false;
  const language = normalized.split("-", 1)[0];
  return language === "ja" || normalized.includes("japanese") || normalized.includes("日本語");
}

function hasNonEmptyDisplayText(value: string | null | undefined): boolean {
  const text = (value ?? "").trim();
  return Boolean(text);
}

function displayTextOrFallback(value: string | null | undefined, locale: string | null | undefined, fallback: string): string {
  void locale;
  const text = (value ?? "").trim();
  if (hasNonEmptyDisplayText(text)) return text;
  return fallback;
}

function localizedObjectCount(
  count: number,
  englishSingular: string,
  englishPlural: string,
  japaneseLabel: string,
  locale: string | null | undefined
): string {
  if (localeLooksJapanese(locale)) return `${count}件の${japaneseLabel}`;
  return `${count} ${count === 1 ? englishSingular : englishPlural}`;
}

function resolveLocalePack(locale: string, localePacks: LocalePack[]) {
  const requested = normalizeLocale(locale);
  const requestedLower = requested.toLowerCase();
  const exactMatch = localePacks.find((pack) => normalizeLocale(pack.locale).toLowerCase() === requestedLower);
  if (exactMatch) return exactMatch;

  const requestedLanguage = localeLanguage(requested);
  if (requestedLanguage) {
    const languageMatch = localePacks.find((pack) =>
      [pack.locale, pack.label, pack.nativeLabel].some((value) => localeLanguage(value) === requestedLanguage)
    );
    if (languageMatch) return languageMatch;
  }

  return builtinLocalePacks[0];
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

import {
  AGENT_CHAT_MESSAGE_HISTORY_LIMIT,
  filterDeletedProjects,
  filterDeletedProjectsFromPortalOverview,
  tabItems
} from "./types";
import type {
  AutonomyMode,
  TableeMotionState,
  Project,
  DatasetSnapshot,
  SemanticCatalog,
  ProjectColumnCatalog,
  Artifact,
  RunnerReadinessFeedback,
  ArtifactPreview,
  NativeMarimoSession,
  EvidenceReaderMetric,
  NotebookIndexItem,
  NotebookIndex,
  AnalysisStorySurface,
  AnalysisStory,
  TranslationResult,
  TranslationJobOutput,
  BenchmarkDataset,
  BenchmarkSourceCard,
  BenchmarkLocalStatus,
  LibraryAsset,
  AssetReference,
  Question,
  Assumption,
  AssumptionReviewAction,
  AssumptionReviewItem,
  AssumptionReviewQueue,
  EvaluationCandidate,
  EvaluationSpec,
  Job,
  AutonomyIntervention,
  PendingAutonomyIntervention,
  JobArtifactsResponse,
  TokenSeriesPoint,
  AgentRetryState,
  AgentWorkerEvent,
  AgentSession,
  AgentTranscriptEvent,
  AgentRawTranscript,
  RequiredHumanDescription,
  AgentChatAction,
  AgentActionSummary,
  AgentChatResponse,
  AgentConsoleMessageResponse,
  AgentChatHistoryTurn,
  AgentChatMessage,
  AgentConversationTurn,
  ArtifactPreviewRequest,
  HomeMemoryItem,
  EquippedSkillItem,
  SkillDraft,
  UploadFileProgress,
  UploadBundleProgress,
  PortalIdea,
  PortalUpdate,
  PortalOverview,
  AgentActivityResponse,
  TurnState,
  Run,
  LeaderboardEntry,
  PilotDeploymentIndex,
  PilotDeploymentRead,
  PilotPredictionBatchRead,
  PilotOutcomeBatchRead,
  PilotScoringReportRead,
  ModelVersion,
  ModelValidation,
  ResearchBrief,
  StrategyAction,
  StrategyLane,
  AdaptiveStrategyBrief,
  ResearchPlanBlockStatus,
  PendingAnchorNavigation,
  ResearchPlanSubtask,
  ResearchPlanEvidenceLinkItem,
  ResearchPlanBlock,
  ResearchPlanArtifactLink,
  ResearchPlanCurrentWork,
  ResearchPlanTimelineBlock,
  ResearchPlanContractValidation,
  ResearchPlanTimelineResponse,
  Idea,
  Report,
  DecisionReportBundle,
  DecisionReportCurrent,
  ResultReadout,
  VisualizationSpec,
  AgentTaskResultArtifact,
  AgentTaskResultReport,
  AgentTaskResult,
  Insight,
  Overview,
  LineageEdge,
  Tab
} from "./types";
const apiBase = import.meta.env.VITE_API_BASE ?? "";
const topLevelTabIds = new Set<Tab>(["Home", "Data", "Insight", "Evaluation", "Leaderboard", "Assets"]);
const hiddenLegacyTabIds = new Set<Tab>(["Overview", "Approach", "Raw"]);
const primaryTabItems = tabItems.filter((item) => topLevelTabIds.has(item.id));
const supportingTabItems = tabItems.filter((item) => !topLevelTabIds.has(item.id) && !hiddenLegacyTabIds.has(item.id));
const supportingTabIdSet = new Set<Tab>(supportingTabItems.map((item) => item.id));
const NOTEBOOK_NATIVE_MARIMO_ANCHOR = "notebook-native-marimo-top";
const notebookNavigationAnchors = new Set(["notebook-preview-top", NOTEBOOK_NATIVE_MARIMO_ANCHOR]);

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
  if (value === "Overview" || value === "Approach") return "Home";
  if (value === "Raw") return "Home";
  if (value === "Reports") return "Insight";
  if (value === "Library" || value === "Lineage") return "Assets";
  const match = tabItems.find((item) => item.id === value);
  return match ? match.id : fallback;
}

function agentConsoleDisabledReason(agentSession: AgentSession | null, text: LocaleMessages): string | null {
  if (!agentSession) return text.rawAgentConsoleStartRequired;
  if (agentSession.status === "stopped") return text.rawAgentConsolePowerOff;
  if (agentSession.status === "failed" || agentSession.status === "gave_up") return text.rawAgentConsoleUnavailable;
  return null;
}

function normalizeNavigationTarget(targetTab: Tab, targetAnchor?: string | null): { targetTab: Tab; targetAnchor?: string | null } {
  if (targetAnchor && notebookNavigationAnchors.has(targetAnchor)) {
    return { targetTab: "Notebooks", targetAnchor: NOTEBOOK_NATIVE_MARIMO_ANCHOR };
  }
  return { targetTab, targetAnchor };
}

function autoStartWorkerJobIds(actions: AgentChatAction[]): string[] {
  return actions
    .filter((action) => action.auto_start_worker && action.job_id)
    .map((action) => action.job_id)
    .filter((jobId): jobId is string => Boolean(jobId));
}

function notebookChatMessageFromJob(result: unknown, text: LocaleMessages): AgentChatMessage | null {
  if (!isJobResult(result)) return null;
  const sourceArtifactId = notebookSourceArtifactIdFromJobOutput(result.output);
  if (!sourceArtifactId) return null;
  const notebookKind = textField(result.output.notebook_kind) ?? result.job_type.replace(/_/g, " ");
  const linkedContext = notebookLinkedContext(result.output);
  const action: AgentChatAction = {
    type: "open_artifact",
    status: "ready",
    label: text.openNotebookViewer,
    target_tab: "Notebooks",
    target_anchor: "notebook-native-marimo-top",
    detail: linkedContext || text.notebookLinkedAssetDetail,
    artifact_id: sourceArtifactId,
    artifact_ids: [sourceArtifactId]
  };
  return {
    id: `notebook-created:${result.id}:${sourceArtifactId}`,
    role: "system",
    text: `${text.notebookCreatedChatMessage}\n${notebookKind.replace(/_/g, " ")}${linkedContext ? ` · ${linkedContext}` : ""}`,
    actions: [action],
    createdAt: result.updated_at ?? new Date().toISOString()
  };
}

function isJobResult(value: unknown): value is Job {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.job_type === "string" && record.output !== null && typeof record.output === "object";
}

function notebookSourceArtifactIdFromJobOutput(output: Record<string, unknown>): string | null {
  const recommended = objectRecord(output.recommended_notebook);
  const recommendedArtifacts = objectRecord(recommended?.artifact_ids);
  return (
    textField(output.source_artifact_id) ??
    textField(output.analysis_notebook_artifact_id) ??
    textField(output.notebook_artifact_id) ??
    textField(recommended?.source_artifact_id) ??
    textField(recommended?.notebook_artifact_id) ??
    textField(recommendedArtifacts?.source) ??
    textField(recommendedArtifacts?.notebook)
  );
}

function notebookAuthoringBriefArtifactIdFromJobOutput(output: Record<string, unknown>): string | null {
  return textField(output.notebook_authoring_brief_artifact_id) ?? textField(output.authoring_brief_artifact_id);
}

async function openNotebookOrAskAgentToAuthor({
  completedJob,
  locale,
  projectName,
  notebookKind,
  onOpenNotebookArtifact,
  onAskAgent
}: {
  completedJob: Job;
  locale: string;
  projectName: string;
  notebookKind: string;
  onOpenNotebookArtifact: (artifactId: string) => void | Promise<void>;
  onAskAgent: (message: string) => Promise<AgentChatResponse | void>;
}) {
  const notebookArtifactId = notebookSourceArtifactIdFromJobOutput(completedJob.output);
  if (notebookArtifactId) {
    await onOpenNotebookArtifact(notebookArtifactId);
    return;
  }
  const authoringBriefArtifactId = notebookAuthoringBriefArtifactIdFromJobOutput(completedJob.output);
  if (!authoringBriefArtifactId) return;
  const japanese = locale.toLowerCase().startsWith("ja");
  const message = japanese
    ? [
        `${projectName} の ${notebookKind} 用 notebook_authoring_brief ${authoringBriefArtifactId} を読み、`,
        "native marimo Python notebookを作成してTablexに登録してください。",
        "生成後はNotebookを開けるリンクと、何を読むべきかを短く報告してください。"
      ].join("")
    : [
        `Read notebook_authoring_brief ${authoringBriefArtifactId} for ${projectName} ${notebookKind}, `,
        "author a native marimo Python notebook, and register it in Tablex. ",
        "After it is registered, reply with the notebook link and a short read-first summary."
      ].join("");
  await onAskAgent(message);
}

function isNativeNotebookSourceAssetType(assetType: string): boolean {
  return assetType === "analysis_notebook" || assetType === "marimo_notebook";
}

function notebookLinkedContext(output: Record<string, unknown>): string {
  const datasetId = textField(output.dataset_snapshot_id);
  const runId = textField(output.run_id);
  const modelVersionId = textField(output.model_version_id);
  const links = [
    datasetId ? `dataset ${datasetId}` : null,
    runId ? `run ${runId}` : null,
    modelVersionId ? `model ${modelVersionId}` : null
  ].filter(Boolean);
  return links.join(" / ");
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
  const response = await fetch(`${apiBase}${path}`, { credentials: "include", ...init });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(apiErrorMessage(detail, response.statusText));
  }
  return response.json() as Promise<T>;
}

async function apiOrFallback<T>(path: string, fallback: T, timeoutMs = 5000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await api<T>(path, { signal: controller.signal });
  } catch {
    return fallback;
  } finally {
    window.clearTimeout(timeout);
  }
}

function apiErrorMessage(body: string, fallback: string): string {
  if (!body) return fallback;
  try {
    const parsed = JSON.parse(body) as unknown;
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map((item) => String(item)).join("; ");
    }
  } catch {
    return body;
  }
  return body;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isMetadataBusyError(err: unknown): boolean {
  return err instanceof Error && err.message.toLowerCase().includes("metadata database is busy");
}

async function apiWithMetadataBusyRetry<T>(path: string, init?: RequestInit): Promise<T> {
  let latestError: unknown = null;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      return await api<T>(path, init);
    } catch (err) {
      latestError = err;
      if (!isMetadataBusyError(err) || attempt === 3) break;
      await sleep(250 * (attempt + 1));
    }
  }
  throw latestError instanceof Error ? latestError : new Error(String(latestError));
}

function avatarGenerationProgress(elapsedSeconds: number, text: LocaleMessages) {
  const percent = Math.min(92, 12 + Math.floor(elapsedSeconds * 0.7));
  let label = text.userAvatarProgressPreparing;
  if (elapsedSeconds >= 8) label = text.userAvatarProgressGenerating;
  if (elapsedSeconds >= 90) label = text.userAvatarProgressFinalizing;
  return { percent, label };
}

function formatElapsedSeconds(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes <= 0) return `${remainder}s`;
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

type JobWaitOptions = {
  timeoutMs?: number;
  pollMs?: number;
  label?: string;
};

type RunActionOptions = {
  refreshMode?: "full" | "data-intake" | "none";
};

type DataUploadDraft = {
  queuedFiles: File[];
  primaryFileName: string;
  uploadProgress: UploadBundleProgress | null;
  fileColumnHints: Record<string, string[]>;
  addFiles: (files: FileList | File[]) => void;
  removeFile: (file: File) => void;
  setPrimaryFileName: (fileName: string) => void;
  setUploadProgress: React.Dispatch<React.SetStateAction<UploadBundleProgress | null>>;
};

async function waitForJobCompletion(jobId: string, options: JobWaitOptions = {}): Promise<Job> {
  const timeoutMs = options.timeoutMs ?? 10 * 60_000;
  const pollMs = options.pollMs ?? 1000;
  const label = options.label ?? "Job";
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const job = await api<Job>(`/api/jobs/${jobId}`);
    if (job.status === "succeeded") return job;
    if (["failed", "cancelled", "timed_out"].includes(job.status)) {
      throw new Error(job.error_message ?? `${label} ${job.status}.`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, pollMs));
  }
  throw new Error(`${label} is still running. Check Agent Activity or try again shortly.`);
}

async function runQueuedJobAndWait(job: Job, options: JobWaitOptions = {}): Promise<Job> {
  await api<Job>(`/api/jobs/${job.id}/run`, { method: "POST" });
  return waitForJobCompletion(job.id, options);
}

async function waitForAvatarJob(jobId: string): Promise<Job> {
  return waitForJobCompletion(jobId, { timeoutMs: 12 * 60_000, label: "Avatar generation" });
}

function uploadFormData<T>(
  path: string,
  body: FormData,
  onProgress: (event: ProgressEvent<EventTarget>) => void,
  onTransferComplete?: () => void
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBase}${path}`);
    xhr.upload.onprogress = onProgress;
    xhr.upload.onload = () => onTransferComplete?.();
    xhr.onerror = () => reject(new Error("Upload failed before the server returned a response."));
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(xhr.responseText || xhr.statusText));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    };
    xhr.send(body);
  });
}

function tabLabel(tab: Tab, text: LocaleMessages) {
  const item = tabItems.find((candidate) => candidate.id === tab);
  return item ? text[item.labelKey] : tab;
}

function normalizeTab(value: string | null | undefined): Tab {
  return tabFromString(value, "Home");
}

function guidanceActionToFocusAction(action: ProjectGuidanceAction, labelOverride?: string | null): FocusAction {
  return {
    id: action.id,
    label: labelOverride ?? action.label,
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
  const primaryAction = guidanceActionToFocusAction(
    focus.primary_action,
    localizedFocusActionLabel(focus.focus_key, text)
  );
  const secondaryActions = focus.secondary_actions.map((action) => guidanceActionToFocusAction(action));
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

function localizedFocusActionLabel(focusKey: string, text: LocaleMessages): string | null {
  if (focusKey === "upload_data") return text.strategyActionUploadData;
  if (focusKey === "understand_data") return text.focusUnderstandData;
  if (focusKey === "assumptions") return text.strategyActionResolveAssumptions;
  if (focusKey === "evaluation") return text.strategyActionLockEvaluation;
  if (focusKey === "approach") return text.focusApproach;
  if (focusKey === "experiments") return text.focusExperiments;
  if (focusKey === "notebooks") return text.focusNotebooks;
  if (focusKey === "reports") return text.focusReports;
  return null;
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
      tab: "Home",
      title: text.focusApproach,
      reason: text.focusApproachReason,
      evidence: [`${approvedSpecs.length} approved specs`, `${succeededJobs.length} succeeded jobs`],
      secondaryTabs: ["Leaderboard", "Insight", "Assets"],
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
      tab: "Leaderboard",
      title: text.focusExperiments,
      reason: text.focusExperimentsReason,
      evidence: [`${runs.length} experiment runs`, `${artifacts.length} artifacts`],
      secondaryTabs: ["Insight", "Assets", "Evaluation"],
      primaryAction: null,
      secondaryActions: [],
      riskLevel: "medium",
      confidence: 0.68,
      suggestedAgentPrompt: null,
      source: "local"
    };
  }

  return {
    tab: "Insight",
    title: text.focusReports,
    reason: text.focusReportsReason,
    evidence: [`${reports.length} reports`, `${runs.length} experiment runs`],
    secondaryTabs: ["Leaderboard", "Assets", "Lineage"],
    primaryAction: null,
    secondaryActions: [],
    riskLevel: "low",
    confidence: 0.65,
    suggestedAgentPrompt: null,
    source: "local"
  };
}

type AppRoute = {
  viewMode: "portal" | "project";
  projectId: string | null;
};

function initialAppRoute(): AppRoute {
  if (typeof window === "undefined") return { viewMode: "portal", projectId: null };
  return routeFromLocationHash();
}

function routeFromLocationHash(): AppRoute {
  const hash = window.location.hash || "";
  const match = hash.match(/^#\/projects\/([^/?#]+)/);
  if (!match) return { viewMode: "portal", projectId: null };
  return { viewMode: "project", projectId: decodeURIComponent(match[1]) };
}

function writeAppRoute(route: AppRoute) {
  const nextHash = route.viewMode === "project" && route.projectId ? `#/projects/${encodeURIComponent(route.projectId)}` : "#/";
  if (window.location.hash === nextHash) return;
  window.history.pushState(null, "", nextHash);
}

export function App() {
  const initialRoute = initialAppRoute();
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = React.useState<string | null>(initialRoute.projectId);
  const [viewMode, setViewMode] = React.useState<"portal" | "project">(initialRoute.viewMode);
  const [tab, setTab] = React.useState<Tab>("Home");
  const [userSettings, setUserSettings] = React.useState<UserSettings>(() => loadUserSettings());
  const [dynamicLocalePacks, setDynamicLocalePacks] = React.useState<LocalePack[]>(() => loadDynamicLocalePacks());
  const [authStatus, setAuthStatus] = React.useState<AuthStatus | null>(null);
  const [authLoading, setAuthLoading] = React.useState(true);
  const [authError, setAuthError] = React.useState<string | null>(null);
  const [portalOverview, setPortalOverview] = React.useState<PortalOverview | null>(null);
  const [portalIdeas, setPortalIdeas] = React.useState<PortalIdea[]>([]);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [moreTabsOpen, setMoreTabsOpen] = React.useState(false);
  const [projectPendingDeletion, setProjectPendingDeletion] = React.useState<Project | null>(null);
  const [deletingProjectId, setDeletingProjectId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const hydratedUserIdRef = React.useRef<string | null>(null);
  const moreTabsRef = React.useRef<HTMLDivElement | null>(null);
  const deletedProjectIdsRef = React.useRef<Set<string>>(new Set());
  const localePacks = React.useMemo(() => mergeLocalePacks(dynamicLocalePacks), [dynamicLocalePacks]);
  const activeLocale = resolveLocalePack(userSettings.locale, localePacks);
  const text = copyForLocale(activeLocale.locale, localePacks);
  const authKnown = authStatus !== null;
  const authEnabled = Boolean(authStatus?.auth_enabled);
  const authAuthenticated = Boolean(authStatus?.authenticated);

  React.useEffect(() => {
    window.localStorage.setItem(userSettingsStorageKey, JSON.stringify(userSettings));
    window.localStorage.setItem(dynamicLocaleStorageKey, JSON.stringify(dynamicLocalePacks));
    document.documentElement.lang = activeLocale.locale;
    document.documentElement.dir = activeLocale.direction;
    document.documentElement.dataset.theme = userSettings.displayTheme;
  }, [activeLocale.direction, activeLocale.locale, dynamicLocalePacks, userSettings]);

  React.useEffect(() => {
    if (!moreTabsOpen) return;
    function closeOnOutsideInteraction(event: PointerEvent) {
      if (moreTabsRef.current && !moreTabsRef.current.contains(event.target as Node)) {
        setMoreTabsOpen(false);
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMoreTabsOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideInteraction);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideInteraction);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [moreTabsOpen]);

  React.useEffect(() => {
    function syncRouteFromHash() {
      const route = routeFromLocationHash();
      setSelectedProjectId(route.projectId);
      setViewMode(route.viewMode);
      if (route.viewMode === "project") setTab("Home");
    }
    window.addEventListener("hashchange", syncRouteFromHash);
    window.addEventListener("popstate", syncRouteFromHash);
    return () => {
      window.removeEventListener("hashchange", syncRouteFromHash);
      window.removeEventListener("popstate", syncRouteFromHash);
    };
  }, []);

  const refreshAuth = React.useCallback(async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const status = await api<AuthStatus>("/api/auth/status");
      setAuthStatus(status);
      if (status.user?.id && hydratedUserIdRef.current !== status.user.id) {
        hydratedUserIdRef.current = status.user.id;
        setUserSettings((current) => mergeServerUserSettings(current, status.user?.settings ?? {}));
      }
      if (!status.authenticated) {
        hydratedUserIdRef.current = null;
      }
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const refreshProjects = React.useCallback(async (preferredProjectId?: string | null, options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const [data, portalData] = await Promise.all([
        api<Project[]>("/api/projects"),
        api<PortalOverview>("/api/portal/overview").catch(() => null)
      ]);
      const visibleProjects = filterDeletedProjects(data, deletedProjectIdsRef.current);
      const visiblePortalData = filterDeletedProjectsFromPortalOverview(portalData, deletedProjectIdsRef.current);
      setProjects(visibleProjects);
      setPortalOverview(visiblePortalData);
      setPortalIdeas(visiblePortalData?.ideas ?? []);
      if (preferredProjectId) {
        setSelectedProjectId(preferredProjectId);
      } else if (preferredProjectId === null) {
        setSelectedProjectId(null);
      } else if (!selectedProjectId && visibleProjects[0]) {
        setSelectedProjectId(visibleProjects[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options?.silent) {
        setLoading(false);
      }
    }
  }, [selectedProjectId]);

  React.useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  React.useEffect(() => {
    if (authLoading || !authKnown) return;
    if (authEnabled && !authAuthenticated) {
      setLoading(false);
      return;
    }
    void refreshProjects();
  }, [authAuthenticated, authEnabled, authKnown, authLoading, refreshProjects]);

  React.useEffect(() => {
    if (!authEnabled || !authAuthenticated) return undefined;
    const handle = window.setTimeout(() => {
      void api<AuthUser>("/api/auth/me/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: userSettings })
      }).then((user) => {
        setAuthStatus((current) => (current ? { ...current, user } : current));
      });
    }, 600);
    return () => window.clearTimeout(handle);
  }, [authAuthenticated, authEnabled, userSettings]);

  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;
  const activeProject = viewMode === "project" ? selectedProject : null;
  const visiblePrimaryTabItems = userSettings.showDetailedTabs ? [...primaryTabItems, ...supportingTabItems] : primaryTabItems;
  const showMoreTabs = !userSettings.showDetailedTabs && supportingTabItems.length > 0;

  function openProject(projectId: string) {
    setSelectedProjectId(projectId);
    setViewMode("project");
    setTab("Home");
    writeAppRoute({ viewMode: "project", projectId });
  }

  function openPortal() {
    setViewMode("portal");
    setTab("Home");
    writeAppRoute({ viewMode: "portal", projectId: null });
  }

  async function loginOrBootstrap(email: string, password: string, displayName: string | null) {
    const endpoint = authStatus?.bootstrap_required ? "/api/auth/bootstrap" : "/api/auth/login";
    const status = await api<AuthStatus>(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        authStatus?.bootstrap_required
          ? { email, password, display_name: displayName }
          : { email, password }
      )
    });
    setAuthStatus(status);
    if (status.user?.settings) {
      hydratedUserIdRef.current = status.user.id;
      setUserSettings((current) => mergeServerUserSettings(current, status.user?.settings ?? {}));
    }
  }

  async function signOut() {
    await api<AuthStatus>("/api/auth/logout", { method: "POST" });
    setAuthStatus((current) => (current ? { ...current, authenticated: false, user: null } : current));
    setProjects([]);
    setPortalOverview(null);
    setPortalIdeas([]);
    setSelectedProjectId(null);
    setViewMode("portal");
    writeAppRoute({ viewMode: "portal", projectId: null });
    hydratedUserIdRef.current = null;
  }

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

  async function generateAvatarCandidates(prompt: string): Promise<AvatarCandidate[]> {
    const job = await api<Job>("/api/user/avatar-candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, count: 3 })
    });
    await api<Job>(`/api/jobs/${job.id}/run`, { method: "POST" });
    const completedJob = await waitForAvatarJob(job.id);
    const output = completedJob.output as AvatarCandidateJobOutput;
    if (!Array.isArray(output.candidates)) {
      throw new Error("Avatar generation completed without candidates.");
    }
    return output.candidates;
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

  async function deleteProject(project: Project) {
    setDeletingProjectId(project.id);
    setError(null);
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" });
      deletedProjectIdsRef.current.add(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
      setPortalOverview((current) => {
        if (!current) return current;
        return filterDeletedProjectsFromPortalOverview(current, deletedProjectIdsRef.current);
      });
      setProjectPendingDeletion(null);
      if (selectedProjectId === project.id) {
        setSelectedProjectId(null);
        setViewMode("portal");
        writeAppRoute({ viewMode: "portal", projectId: null });
      }
      void refreshProjects(null, { silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingProjectId(null);
    }
  }

  return (
    <LocaleContext.Provider value={{ text, locale: activeLocale.locale }}>
      <div className="app-shell">
      {authLoading || !authStatus ? (
        <main className="auth-shell">
          <LoadingBlock label={authError ?? text.loadingProjects} />
        </main>
      ) : authStatus.auth_enabled && !authStatus.authenticated ? (
        <AuthGate
          status={authStatus}
          text={text}
          error={authError}
          onSubmit={loginOrBootstrap}
        />
      ) : (
      <>
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
            <div
              key={project.id}
              className={project.id === selectedProjectId && viewMode === "project" ? "project-item active" : "project-item"}
            >
              <button className="project-item-main" onClick={() => openProject(project.id)} type="button">
                <span>{project.name}</span>
                <small>{formatWorkflowState(project.current_phase, text)}</small>
              </button>
              <button
                className="project-delete-button"
                onClick={(event) => {
                  event.stopPropagation();
                  setProjectPendingDeletion(project);
                }}
                disabled={deletingProjectId === project.id}
                title={text.deleteProject}
                type="button"
              >
                {deletingProjectId === project.id ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} />}
              </button>
            </div>
          ))}
        </div>
        <CreateProjectForm
          text={text}
          onCreated={async (project) => {
            deletedProjectIdsRef.current.delete(project.id);
            openProject(project.id);
            await refreshProjects(project.id);
          }}
        />
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <div className="topbar-kicker">
              {activeProject ? (
                <button className="text-button" onClick={openPortal} type="button">
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
            {authStatus.auth_enabled && authStatus.user ? (
              <div className="auth-user-chip">
                <UserAvatar src={userSettings.userAvatarDataUrl} />
                <span>
                  <small>{text.signedInAs}</small>
                  <strong>{authStatus.user.display_name ?? authStatus.user.email}</strong>
                </span>
              </div>
            ) : null}
            <button className="icon-button" onClick={() => void refreshProjects()} title={text.refreshProjects}>
              <RefreshCw size={18} />
            </button>
            <button className="icon-button" onClick={() => setSettingsOpen(true)} title={text.settings}>
              <SettingsIcon size={18} />
            </button>
            {authStatus.auth_enabled ? (
              <button className="icon-button" onClick={() => void signOut()} title={text.signOut}>
                <KeyRound size={18} />
              </button>
            ) : null}
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
            onGenerateAvatarCandidates={generateAvatarCandidates}
          />
        ) : null}
        {projectPendingDeletion ? (
          <ProjectDeleteDialog
            project={projectPendingDeletion}
            text={text}
            busy={deletingProjectId === projectPendingDeletion.id}
            onCancel={() => {
              if (!deletingProjectId) setProjectPendingDeletion(null);
            }}
            onConfirm={() => void deleteProject(projectPendingDeletion)}
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
            onOpenProject={openProject}
            onAddIdea={addPortalIdea}
          />
        ) : null}
        {activeProject ? (
          <>
            <nav className="tabs">
              {visiblePrimaryTabItems.map((item) => (
                <button
                  key={item.id}
                  className={item.id === tab ? "tab active" : "tab"}
                  onClick={() => {
                    setMoreTabsOpen(false);
                    setTab(item.id);
                  }}
                >
                  {text[item.labelKey]}
                </button>
              ))}
              {showMoreTabs ? (
              <div className="tab-more" ref={moreTabsRef}>
                <button
                  className={supportingTabIdSet.has(tab) ? "tab active" : "tab"}
                  type="button"
                  aria-haspopup="menu"
                  aria-expanded={moreTabsOpen}
                  onClick={() => setMoreTabsOpen((current) => !current)}
                >
                  {text.moreTabs}
                </button>
                {moreTabsOpen ? (
                  <div className="tab-menu" role="menu">
                    {supportingTabItems.map((item) => (
                      <button
                        key={item.id}
                        className={item.id === tab ? "tab-menu-item active" : "tab-menu-item"}
                        onClick={() => {
                          setMoreTabsOpen(false);
                          setTab(item.id);
                        }}
                        type="button"
                        role="menuitem"
                      >
                        {text[item.labelKey]}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              ) : null}
            </nav>
            <ProjectDetail
              project={activeProject}
              tab={tab}
              text={text}
              userSettings={userSettings}
              onTabChange={setTab}
              onProjectChanged={() => refreshProjects(undefined, { silent: true })}
              onProjectUpdated={(project) => {
                setProjects((current) => current.map((item) => (item.id === project.id ? project : item)));
              }}
            />
          </>
        ) : null}
      </main>
      </>
      )}
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
  onCreateLocalizationTask,
  onGenerateAvatarCandidates
}: {
  settings: UserSettings;
  text: LocaleMessages;
  activeLocale: LocalePack;
  localePacks: LocalePack[];
  onChange: (settings: UserSettings) => void;
  onEnsureDynamicLocale: (localeInput: string) => void;
  onClose: () => void;
  onCreateLocalizationTask: (settings: UserSettings) => Promise<void>;
  onGenerateAvatarCandidates: (prompt: string) => Promise<AvatarCandidate[]>;
}) {
  const [busy, setBusy] = React.useState(false);
  const [avatarBusy, setAvatarBusy] = React.useState(false);
  const [avatarPrompt, setAvatarPrompt] = React.useState("");
  const [avatarCandidates, setAvatarCandidates] = React.useState<AvatarCandidate[]>([]);
  const [localeStatus, setLocaleStatus] = React.useState<string | null>(null);
  const [avatarStatus, setAvatarStatus] = React.useState<string | null>(null);
  const [avatarStartedAt, setAvatarStartedAt] = React.useState<number | null>(null);
  const [avatarElapsedSeconds, setAvatarElapsedSeconds] = React.useState(0);
  const [storageUsage, setStorageUsage] = React.useState<StorageUsage | null>(null);
  const [storageBusy, setStorageBusy] = React.useState(false);
  const [storageStatus, setStorageStatus] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!avatarBusy || avatarStartedAt === null) return undefined;
    const tick = () => setAvatarElapsedSeconds(Math.max(0, Math.floor((Date.now() - avatarStartedAt) / 1000)));
    tick();
    const handle = window.setInterval(tick, 1000);
    return () => window.clearInterval(handle);
  }, [avatarBusy, avatarStartedAt]);

  React.useEffect(() => {
    void loadStorageUsage();
  }, []);

  function update(patch: Partial<UserSettings>) {
    setLocaleStatus(null);
    setAvatarStatus(null);
    onChange({ ...settings, ...patch });
  }

  async function loadStorageUsage() {
    setStorageBusy(true);
    setStorageStatus(null);
    try {
      setStorageUsage(await api<StorageUsage>("/api/admin/storage/usage"));
    } catch (err) {
      setStorageStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setStorageBusy(false);
    }
  }

  function addDynamicLocale() {
    const localeInput = settings.requestedLocale.trim();
    if (!localeInput) return;
    onEnsureDynamicLocale(localeInput);
    setLocaleStatus(`${text.activeLocale}: ${localeLabel(localeInput)}`);
  }

  async function createTask() {
    setBusy(true);
    setLocaleStatus(null);
    try {
      await onCreateLocalizationTask(settings);
      setLocaleStatus(text.localizationTaskCreated);
    } catch (err) {
      setLocaleStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function updateAvatar(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setAvatarStatus("Choose an image file.");
      return;
    }
    if (file.size > 1024 * 1024) {
      setAvatarStatus("Choose an image under 1 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      if (!result.startsWith("data:image/")) {
        setAvatarStatus("Could not read this image.");
        return;
      }
      update({ userAvatarDataUrl: result });
      setAvatarStatus(text.userAvatar);
    };
    reader.onerror = () => setAvatarStatus("Could not read this image.");
    reader.readAsDataURL(file);
  }

  async function generateAvatars() {
    const prompt = avatarPrompt.trim();
    if (!prompt) {
      setAvatarStatus(text.userAvatarPromptRequired);
      return;
    }
    setAvatarBusy(true);
    setAvatarStartedAt(Date.now());
    setAvatarElapsedSeconds(0);
    setAvatarStatus(text.userAvatarGenerating);
    try {
      const candidates = await onGenerateAvatarCandidates(prompt);
      setAvatarCandidates(candidates);
      setAvatarStatus(`${text.userAvatarCandidates}: ${candidates.length}`);
    } catch (err) {
      setAvatarCandidates([]);
      setAvatarStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setAvatarBusy(false);
      setAvatarStartedAt(null);
    }
  }

  const avatarProgress = avatarBusy ? avatarGenerationProgress(avatarElapsedSeconds, text) : null;

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
        <button className="primary-button" disabled={busy} onClick={() => void createTask()} type="button">
          {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
          {text.createLocalizationTask}
        </button>
        {localeStatus ? <div className="settings-status">{localeStatus}</div> : null}
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.appearance}</span>
          <strong>{displayThemeLabel(settings.displayTheme, text)}</strong>
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
          <button
            className={settings.displayTheme === "matrix" ? "active" : ""}
            onClick={() => update({ displayTheme: "matrix" })}
            type="button"
          >
            <Sparkles size={15} />
            {text.matrixTheme}
          </button>
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={settings.showDetailedTabs}
            onChange={(event) => update({ showDetailedTabs: event.target.checked })}
          />
          <span>{text.showDetailedTabs}</span>
        </label>
        <p className="settings-hint">{text.showDetailedTabsHint}</p>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.storageUsage}</span>
          <strong>{storageUsage ? formatBytes(storageUsage.total_bytes) : "-"}</strong>
        </div>
        <div className="metric-grid compact">
          {["datasets", "artifacts", "workspaces", "pipeline_envs", "marimo", "db"].map((key) => (
            <Metric key={key} label={storageCategoryLabel(key, text)} value={formatBytes(storageUsage?.categories[key] ?? null)} />
          ))}
        </div>
        <button className="secondary-button" disabled={storageBusy} onClick={() => void loadStorageUsage()} type="button">
          {storageBusy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          {text.storageUsageRefresh}
        </button>
        <p className="settings-hint">{text.storageUsageHint}</p>
        {storageStatus ? <div className="settings-status">{storageStatus}</div> : null}
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.userProfile}</span>
          <strong>{text.userAvatar}</strong>
        </div>
        <div className="settings-avatar-row">
          <UserAvatar src={settings.userAvatarDataUrl} />
          <div className="settings-avatar-actions">
            <label className="secondary-button avatar-upload-button">
              <Upload size={15} />
              {text.uploadUserAvatar}
              <input accept="image/*" type="file" onChange={updateAvatar} />
            </label>
            <button className="secondary-button" type="button" onClick={() => update({ userAvatarDataUrl: null })}>
              <X size={15} />
              {text.clearUserAvatar}
            </button>
          </div>
        </div>
        <p className="settings-hint">{text.userAvatarHint}</p>
        <label>
          <span>{text.userAvatarPrompt}</span>
          <textarea
            value={avatarPrompt}
            onChange={(event) => setAvatarPrompt(event.target.value)}
            placeholder={text.userAvatarPromptPlaceholder}
            rows={3}
          />
        </label>
        <button
          className="primary-button"
          disabled={avatarBusy}
          onClick={() => void generateAvatars()}
          type="button"
        >
          {avatarBusy ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
          {avatarBusy ? text.userAvatarGenerating : text.userAvatarGenerate}
        </button>
        {avatarProgress ? (
          <div className="avatar-generation-progress" role="status" aria-live="polite">
            <div className="avatar-progress-copy">
              <span>{avatarProgress.label}</span>
              <strong>
                {text.userAvatarElapsed} {formatElapsedSeconds(avatarElapsedSeconds)}
              </strong>
            </div>
            <div className="progress-track compact" aria-label={avatarProgress.label}>
              <div style={{ width: `${avatarProgress.percent}%` }} />
            </div>
          </div>
        ) : null}
        {avatarStatus ? <div className="settings-status">{avatarStatus}</div> : null}
        <p className="settings-hint">{text.userAvatarGenerationHint}</p>
        <div className="avatar-candidate-panel">
          <div className="settings-label-row">
            <span>{text.userAvatarCandidates}</span>
            <strong>{avatarCandidates.length ? `${avatarCandidates.length}` : "-"}</strong>
          </div>
          {avatarCandidates.length ? (
            <div className="avatar-candidate-grid">
              {avatarCandidates.map((candidate) => (
                <button
                  className="avatar-candidate-button"
                  key={candidate.id}
                  onClick={() => {
                    update({ userAvatarDataUrl: candidate.data_url });
                    setAvatarStatus(text.userAvatarUseCandidate);
                  }}
                  title={candidate.revised_prompt ?? text.userAvatarUseCandidate}
                  type="button"
                >
                  <img src={candidate.data_url} alt="" aria-hidden="true" />
                  <span>{text.userAvatarUseCandidate}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="settings-hint">{text.userAvatarNoCandidates}</p>
          )}
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.models}</span>
          <strong>{settings.utilityModel}</strong>
        </div>
        <label>
          <span>{text.agentModel}</span>
          <input
            value={settings.agentModel}
            onChange={(event) => update({ agentModel: event.target.value })}
            placeholder={text.modelPlaceholder}
          />
        </label>
        <p className="settings-hint">{text.agentModelHint}</p>
        <label>
          <span>{text.utilityModel}</span>
          <input
            value={settings.utilityModel}
            onChange={(event) => update({ utilityModel: event.target.value })}
            placeholder={text.modelPlaceholder}
          />
        </label>
        <p className="settings-hint">{text.utilityModelHint}</p>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.intervention}</span>
          <strong>
            {settings.interventionCountdownSeconds === 0
              ? text.autonomyInterventionDisabled
              : `${settings.interventionCountdownSeconds} ${text.seconds}`}
          </strong>
        </div>
        <label>
          <span>{text.interventionCountdown}</span>
          <input
            type="number"
            min={0}
            max={300}
            step={1}
            value={settings.interventionCountdownSeconds}
            onChange={(event) =>
              update({
                interventionCountdownSeconds: Math.max(0, Math.min(300, Math.round(Number(event.target.value) || 0)))
              })
            }
          />
        </label>
        <p className="settings-hint">{text.interventionCountdownHint}</p>
      </div>

      <div className="settings-section">
        <div className="settings-label-row">
          <span>{text.chatInput}</span>
          <strong>
            {resolveChatSubmitShortcut(settings) === "enter"
              ? text.submitShortcutEnter
              : text.submitShortcutShiftEnter}
          </strong>
        </div>
        <label>
          <span>{text.chatSubmitShortcut}</span>
          <select
            value={settings.chatSubmitShortcut}
            onChange={(event) =>
              update({
                chatSubmitShortcut: isChatSubmitShortcutSetting(event.target.value)
                  ? event.target.value
                  : "locale_default"
              })
            }
          >
            <option value="locale_default">{text.submitShortcutLocaleDefault}</option>
            <option value="enter">{text.submitShortcutEnter}</option>
            <option value="shift_enter">{text.submitShortcutShiftEnter}</option>
          </select>
        </label>
        <p className="settings-hint">{text.chatSubmitShortcutHint}</p>
      </div>
    </aside>
  );
}

function CreateProjectForm({ text, onCreated }: { text: LocaleMessages; onCreated: (project: Project) => Promise<void> }) {
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const project = await api<Project>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() })
      });
      setName("");
      await onCreated(project);
    } finally {
      setBusy(false);
    }
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

function DataIntakeStatusCard({
  jobs,
  text,
  compact = false,
  onOpenDataUpload
}: {
  jobs: Job[];
  text: LocaleMessages;
  compact?: boolean;
  onOpenDataUpload?: () => void;
}) {
  const dataJobs = jobs.filter(isDataIntakeJob).slice(0, 3);
  if (!dataJobs.length) return null;
  const activeJob = dataJobs.find((job) => !isTerminalJob(job)) ?? null;
  const leadJob = activeJob ?? dataJobs[0];
  const progressPercent = numberField(leadJob.output.progress_percent);
  const displayPercent = progressPercent === null ? null : Math.max(0, Math.min(100, progressPercent));
  const stage = textField(leadJob.output.progress_stage);
  const leadDetail = dataIntakeJobDetail(leadJob, text);
  const percentLabel = displayPercent === null ? "" : `${Math.round(displayPercent)}%`;
  const rows = compact ? dataJobs : dataJobs.slice(0, 2);

  return (
    <section className={`data-intake-status-card ${activeJob ? "active" : "complete"} ${compact ? "compact" : ""}`} role="status">
      <div className="data-intake-status-main">
        <span className="data-intake-status-icon">
          {activeJob ? <Loader2 className="spin" size={18} /> : <Check size={18} />}
        </span>
        <div>
          <div className="data-intake-status-title-row">
            <strong>{activeJob ? text.dataIntakeHomeTitle : text.intakeJobsTitle}</strong>
            <span className="badge muted">{formatWorkflowState(leadJob.status, text)}</span>
            {percentLabel ? <span className="badge ready">{percentLabel}</span> : null}
          </div>
          <p>{leadDetail}</p>
          {stage ? (
            <small>
              {text.dataIntakeCurrentStep}: {stage}
            </small>
          ) : null}
        </div>
        {onOpenDataUpload ? (
          <button className="secondary-button" type="button" onClick={onOpenDataUpload}>
            <Upload size={16} />
            {text.dataIntakeOpenData}
          </button>
        ) : null}
      </div>
      <div className={`progress-track ${displayPercent === null ? "indeterminate" : ""}`} aria-label={text.intakeJobsTitle}>
        <div style={{ width: `${displayPercent ?? 100}%` }} />
      </div>
      {rows.length > 1 ? (
        <div className="data-intake-status-rows">
          {rows.map((job) => {
            const rowPercent = numberField(job.output.progress_percent);
            const rowDisplayPercent = rowPercent === null ? null : Math.max(0, Math.min(100, rowPercent));
            return (
              <div className="data-intake-status-row" key={job.id}>
                <span>{formatWorkflowState(job.status, text)}</span>
                <small>{dataIntakeJobDetail(job, text)}</small>
                {rowDisplayPercent !== null ? <strong>{Math.round(rowDisplayPercent)}%</strong> : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function HomeDataUploadDropzone({
  draft,
  text,
  disabled,
  onFiles,
  onOpenDataUpload
}: {
  draft: DataUploadDraft;
  text: LocaleMessages;
  disabled: boolean;
  onFiles: (files: FileList | File[]) => void;
  onOpenDataUpload: () => void;
}) {
  const [isDragging, setIsDragging] = React.useState(false);
  const queuedTableFiles = draft.queuedFiles.filter(isTableUploadFile);
  const queuedErHintFiles = draft.queuedFiles.filter(isRelationalHintUploadFile);
  const queuedLabel = draft.queuedFiles.length
    ? text.homeUploadQueued
        .replace("{tables}", String(queuedTableFiles.length))
        .replace("{hints}", String(queuedErHintFiles.length))
    : text.homeUploadIdle;
  const active = disabled || draft.uploadProgress?.active === true;

  return (
    <section className={`home-upload-card ${active ? "active" : ""}`}>
      <label
        className={`data-dropzone home-data-dropzone ${isDragging ? "dragging" : ""} ${active ? "disabled" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!active) setIsDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!active) setIsDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setIsDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          if (!active) onFiles(event.dataTransfer.files);
        }}
      >
        <input
          className="data-dropzone-input"
          type="file"
          multiple
          disabled={active}
          accept=".csv,.parquet,.png,.jpg,.jpeg,.svg,.pdf,.json,image/png,image/jpeg,image/svg+xml,application/pdf,application/json"
          onChange={(event) => {
            if (event.target.files && !active) onFiles(event.target.files);
            event.currentTarget.value = "";
          }}
        />
        <span className="data-dropzone-icon">
          {active ? <Loader2 className="spin" size={24} /> : <Upload size={26} />}
        </span>
        <strong>{active ? text.homeUploadBusy : text.homeUploadTitle}</strong>
        <p>{text.homeUploadBody}</p>
        <small>{queuedLabel}</small>
      </label>
      <button className="secondary-button" type="button" onClick={onOpenDataUpload}>
        <Database size={16} />
        {text.dataIntakeOpenData}
      </button>
    </section>
  );
}

function ProjectDetail({
  project,
  tab,
  text,
  userSettings,
  onTabChange,
  onProjectChanged,
  onProjectUpdated
}: {
  project: Project;
  tab: Tab;
  text: LocaleMessages;
  userSettings: UserSettings;
  onTabChange: (tab: Tab) => void;
  onProjectChanged: () => Promise<void>;
  onProjectUpdated: (project: Project) => void;
}) {
  const { locale: displayLocale } = useLocale();
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
  const [pilotDeployments, setPilotDeployments] = React.useState<PilotDeploymentRead[]>([]);
  const [modelVersions, setModelVersions] = React.useState<ModelVersion[]>([]);
  const [validationsByModelVersion, setValidationsByModelVersion] = React.useState<Record<string, ModelValidation[]>>({});
  const [strategyBrief, setStrategyBrief] = React.useState<AdaptiveStrategyBrief | null>(null);
  const [researchBriefs, setResearchBriefs] = React.useState<ResearchBrief[]>([]);
  const [researchPlanTimeline, setResearchPlanTimeline] = React.useState<ResearchPlanTimelineResponse | null>(null);
  const [ideas, setIdeas] = React.useState<Idea[]>([]);
  const [reports, setReports] = React.useState<Report[]>([]);
  const [decisionReport, setDecisionReport] = React.useState<DecisionReportCurrent | null>(null);
  const [resultReadout, setResultReadout] = React.useState<ResultReadout | null>(null);
  const [visualizations, setVisualizations] = React.useState<VisualizationSpec[]>([]);
  const [notebookIndex, setNotebookIndex] = React.useState<NotebookIndex | null>(null);
  const [analysisStory, setAnalysisStory] = React.useState<AnalysisStorySurface | null>(null);
  const [agentTaskResults, setAgentTaskResults] = React.useState<AgentTaskResult[]>([]);
  const [insights, setInsights] = React.useState<Insight[]>([]);
  const [libraryAssets, setLibraryAssets] = React.useState<LibraryAsset[]>([]);
  const [projectAssetReferences, setProjectAssetReferences] = React.useState<AssetReference[]>([]);
  const [lineage, setLineage] = React.useState<LineageEdge[]>([]);
  const [understanding, setUnderstanding] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [agentChatMessages, setAgentChatMessages] = React.useState<AgentChatMessage[]>([]);
  const [pendingAgentChatMessages, setPendingAgentChatMessages] = React.useState<AgentChatMessage[]>([]);
  const [agentWorkerEvents, setAgentWorkerEvents] = React.useState<AgentWorkerEvent[]>([]);
  const [agentActivity, setAgentActivity] = React.useState<AgentActivityResponse | null>(null);
  const [agentSession, setAgentSession] = React.useState<AgentSession | null>(null);
  const [agentTranscriptEvents, setAgentTranscriptEvents] = React.useState<AgentTranscriptEvent[]>([]);
  const [agentRawTranscript, setAgentRawTranscript] = React.useState<AgentRawTranscript | null>(null);
  const transcriptSinceIndexRef = React.useRef<number | null>(null);
  const transcriptSessionIdRef = React.useRef<string | null>(null);
  const [activityTick, setActivityTick] = React.useState(0);
  const [pendingIntervention, setPendingIntervention] = React.useState<PendingAutonomyIntervention | null>(null);
  const seenInterventionKeysRef = React.useRef<Set<string>>(new Set());
  const [pendingAnchor, setPendingAnchor] = React.useState<PendingAnchorNavigation | null>(null);
  const [artifactPreviewRequest, setArtifactPreviewRequest] = React.useState<ArtifactPreviewRequest | null>(null);
  const artifactPreviewNonceRef = React.useRef(0);
  const [queuedUploadFiles, setQueuedUploadFiles] = React.useState<File[]>([]);
  const [queuedUploadPrimaryFileName, setQueuedUploadPrimaryFileName] = React.useState("");
  const [queuedUploadProgress, setQueuedUploadProgress] = React.useState<UploadBundleProgress | null>(null);
  const [queuedUploadFileColumnHints, setQueuedUploadFileColumnHints] = React.useState<Record<string, string[]>>({});
  const onProjectUpdatedRef = React.useRef(onProjectUpdated);
  React.useEffect(() => {
    onProjectUpdatedRef.current = onProjectUpdated;
  }, [onProjectUpdated]);
  const visibleAgentChatMessages = React.useMemo(
    () => mergeAgentChatMessages(agentChatMessages, pendingAgentChatMessages),
    [agentChatMessages, pendingAgentChatMessages]
  );
  const liveAgentOrModelActivity = hasLiveAgentOrModelActivity(jobs, agentWorkerEvents, agentActivity);
  const hasActiveDataIntakeJob = jobs.some((job) => isDataIntakeJob(job) && !isTerminalJob(job));
  const wasActiveDataIntakeJobRef = React.useRef(false);
  const effectiveProject = overview?.project ?? project;
  const datasetsRef = React.useRef<DatasetSnapshot[]>([]);
  const artifactsRef = React.useRef<Artifact[]>([]);
  const jobsRef = React.useRef<Job[]>([]);
  const tableeMotionState: TableeMotionState = liveAgentOrModelActivity
    ? "working"
    : effectiveProject.current_phase === "AUTONOMOUS_LOOP"
      ? "awake"
      : "idle";

  const setResearchPlanTimelineForCurrentLocale = React.useCallback((timeline: ResearchPlanTimelineResponse | null) => {
    setResearchPlanTimeline(timeline);
  }, []);

  const refreshResearchPlanTimeline = React.useCallback(async () => {
    const timeline = await api<ResearchPlanTimelineResponse>(
      `/api/projects/${project.id}/research-plan/timeline?locale=${encodeURIComponent(displayLocale)}`
    ).catch(() => null);
    setResearchPlanTimelineForCurrentLocale(timeline);
  }, [project.id, displayLocale, setResearchPlanTimelineForCurrentLocale]);

  const refreshAgentChatHistory = React.useCallback(async () => {
    const history = await apiOrFallback<AgentChatHistoryTurn[] | null>(
      `/api/projects/${project.id}/agent-chat/history`,
      null,
      12000
    );
    if (history !== null) {
      setAgentChatMessages((current) => mergeAgentChatMessages(agentChatHistoryToMessages(history), current));
    }
  }, [project.id]);

  React.useEffect(() => {
    setResearchPlanTimeline(null);
  }, [project.id, setResearchPlanTimelineForCurrentLocale]);
  React.useEffect(() => {
    datasetsRef.current = datasets;
    artifactsRef.current = artifacts;
    jobsRef.current = jobs;
  }, [datasets, artifacts, jobs]);
  const turnState = agentActivity?.turn_state ?? fallbackTurnState(effectiveProject);
  const focusRecommendation = React.useMemo(
    () => {
      if (guidance) return focusFromGuidance(guidance, text);
      return buildFocusRecommendation({
        text,
        project: effectiveProject,
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
    [guidance, text, effectiveProject, datasets, understanding, assumptions, candidates, specs, runs, reports, jobs, artifacts]
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
        pilotDeploymentIndexData,
        modelVersionsData,
        strategyBriefData,
        researchBriefsData,
        ideasData,
        reportsData,
        decisionReportData,
        resultReadoutData,
        visualizationsData,
        notebookIndexData,
        analysisStoryData,
        agentTaskResultsData,
        insightsData,
        libraryAssetsData,
        projectAssetReferencesData,
        lineageData,
        agentActivityData,
        agentSessionData,
        agentTranscriptData,
        agentRawTranscriptData,
        researchPlanTimelineData,
        understandingData
      ] = await Promise.all([
        api<Overview>(`/api/projects/${project.id}/overview`),
        apiOrFallback<ProjectGuidance | null>(`/api/projects/${project.id}/guidance`, null, 3500),
        apiOrFallback<DatasetSnapshot[]>(`/api/projects/${project.id}/datasets`, datasetsRef.current, 12000),
        apiOrFallback<Question[]>(`/api/projects/${project.id}/questions`, [], 3500),
        apiOrFallback<Assumption[]>(`/api/projects/${project.id}/assumptions`, [], 3500),
        apiOrFallback<AssumptionReviewQueue | null>(`/api/projects/${project.id}/assumptions/review-queue`, null, 3500),
        apiOrFallback<EvaluationCandidate[]>(`/api/projects/${project.id}/evaluation/candidates`, [], 3500),
        apiOrFallback<EvaluationSpec[]>(`/api/projects/${project.id}/evaluation/specs`, [], 3500),
        apiOrFallback<Artifact[]>(`/api/projects/${project.id}/artifacts?limit=1000`, artifactsRef.current, 12000),
        apiOrFallback<BenchmarkDataset[]>(`/api/benchmarks`, [], 3500),
        apiOrFallback<Job[]>(`/api/projects/${project.id}/jobs`, jobsRef.current, 8000),
        apiOrFallback<Run[]>(`/api/projects/${project.id}/runs`, [], 7000),
        apiOrFallback<LeaderboardEntry[]>(`/api/projects/${project.id}/leaderboard`, [], 7000),
        apiOrFallback<PilotDeploymentIndex>(`/api/projects/${project.id}/pilot-deployments`, {
          schema_version: "pilot_deployment_index.v1",
          project_id: project.id,
          deployments: []
        }, 5000),
        apiOrFallback<ModelVersion[]>(`/api/projects/${project.id}/model-versions`, [], 5000),
        apiOrFallback<AdaptiveStrategyBrief | null>(
          `/api/projects/${project.id}/approach/strategy-brief?locale=${encodeURIComponent(displayLocale)}`,
          null,
          3500
        ),
        apiOrFallback<ResearchBrief[]>(`/api/projects/${project.id}/approach/research-briefs`, [], 5000),
        apiOrFallback<Idea[]>(`/api/projects/${project.id}/approach/ideas`, [], 5000),
        apiOrFallback<Report[]>(`/api/projects/${project.id}/reports`, [], 5000),
        apiOrFallback<DecisionReportCurrent | null>(`/api/projects/${project.id}/decision-report/current`, null, 3500),
        apiOrFallback<ResultReadout | null>(`/api/projects/${project.id}/results/readout`, null, 5000),
        apiOrFallback<VisualizationSpec[]>(`/api/projects/${project.id}/visualizations`, [], 5000),
        apiOrFallback<NotebookIndex | null>(`/api/projects/${project.id}/analysis-notebooks`, null, 7000),
        apiOrFallback<AnalysisStorySurface | null>(`/api/projects/${project.id}/analysis-story`, null, 5000),
        apiOrFallback<AgentTaskResult[]>(`/api/projects/${project.id}/agent-task-results`, [], 3500),
        apiOrFallback<Insight[]>(`/api/projects/${project.id}/insights`, [], 5000),
        apiOrFallback<LibraryAsset[]>(`/api/assets`, [], 3500),
        apiOrFallback<AssetReference[]>(`/api/projects/${project.id}/asset-references`, [], 5000),
        apiOrFallback<LineageEdge[]>(`/api/projects/${project.id}/lineage`, [], 5000),
        Promise.resolve<AgentActivityResponse | null>(null),
        Promise.resolve<AgentSession | null>(null),
        Promise.resolve<AgentTranscriptEvent[]>([]),
        Promise.resolve<AgentRawTranscript | null>(null),
        apiOrFallback<ResearchPlanTimelineResponse | null>(
          `/api/projects/${project.id}/research-plan/timeline?locale=${encodeURIComponent(displayLocale)}`,
          null,
          3500
        ),
        apiOrFallback<{ markdown: string | null }>(`/api/projects/${project.id}/understanding/latest`, { markdown: null }, 3500)
      ]);
      setOverview(overviewData);
      onProjectUpdatedRef.current(overviewData.project);
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
      setPilotDeployments(pilotDeploymentIndexData.deployments);
      setModelVersions(modelVersionsData);
      setStrategyBrief(strategyBriefData);
      setResearchBriefs(researchBriefsData);
      setIdeas(ideasData);
      setReports(reportsData);
      setDecisionReport(decisionReportData);
      setResultReadout(resultReadoutData);
      setVisualizations(visualizationsData);
      setNotebookIndex(notebookIndexData);
      setAnalysisStory(analysisStoryData);
      setAgentTaskResults(agentTaskResultsData);
      setInsights(insightsData);
      setLibraryAssets(libraryAssetsData);
      setProjectAssetReferences(projectAssetReferencesData);
      setAgentActivity(agentActivityData);
      setAgentSession(agentSessionData);
      setAgentTranscriptEvents(agentTranscriptData);
      setAgentRawTranscript(agentRawTranscriptData);
      setResearchPlanTimelineForCurrentLocale(researchPlanTimelineData);
      transcriptSessionIdRef.current = agentSessionData?.id ?? null;
      transcriptSinceIndexRef.current = maxTranscriptEventIndex(agentTranscriptData);
      const validationEntries = await Promise.all(
        modelVersionsData.map(async (modelVersion) => {
          const validations = await apiOrFallback<ModelValidation[]>(`/api/model-versions/${modelVersion.id}/validations`, [], 3000);
          return [modelVersion.id, validations] as const;
        })
      );
      setValidationsByModelVersion(Object.fromEntries(validationEntries));
      setLineage(lineageData);
      setUnderstanding(understandingData.markdown);
      void refreshAgentChatHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project.id, setResearchPlanTimelineForCurrentLocale, displayLocale, refreshAgentChatHistory]);

  const refreshDataIntake = React.useCallback(async () => {
    try {
      const [datasetsData, jobsData, datasetArtifactsData, supportingTableArtifactsData] = await Promise.all([
        api<DatasetSnapshot[]>(`/api/projects/${project.id}/datasets`),
        api<Job[]>(`/api/projects/${project.id}/jobs`),
        api<Artifact[]>(`/api/projects/${project.id}/artifacts?asset_type=dataset_snapshot&limit=200`),
        api<Artifact[]>(`/api/projects/${project.id}/artifacts?asset_type=uploaded_supporting_table&limit=500`)
      ]);
      setDatasets(datasetsData);
      setJobs(jobsData);
      setArtifacts((current) => mergeArtifacts(current, [...datasetArtifactsData, ...supportingTableArtifactsData]));
    } catch {
      // Full project refresh still surfaces durable failures; intake polling stays lightweight.
    }
  }, [project.id]);

  const refreshAgentActivity = React.useCallback(async () => {
    try {
      const [data, sessionData, rawTranscriptData, researchPlanTimelineData, projectData] = await Promise.all([
        apiOrFallback<AgentActivityResponse | null>(`/api/projects/${project.id}/agent-activity`, null, 7000),
        apiOrFallback<AgentSession | null>(`/api/projects/${project.id}/agent-session/current`, null, 3000),
        apiOrFallback<AgentRawTranscript | null>(`/api/projects/${project.id}/agent-session/raw-transcript?limit=120`, null, 3000),
        apiOrFallback<ResearchPlanTimelineResponse | null>(
          `/api/projects/${project.id}/research-plan/timeline?locale=${encodeURIComponent(displayLocale)}`,
          null,
          3000
        ),
        apiOrFallback<Project | null>(`/api/projects/${project.id}`, null, 3000)
      ]);
      const sessionId = sessionData?.id ?? null;
      const canRequestDelta = sessionId !== null && sessionId === transcriptSessionIdRef.current;
      const sinceIndex = canRequestDelta ? transcriptSinceIndexRef.current : null;
      const transcriptUrl =
        sinceIndex === null
          ? `/api/projects/${project.id}/agent-session/transcript`
          : `/api/projects/${project.id}/agent-session/transcript?since_index=${sinceIndex}`;
      const transcriptData = await api<AgentTranscriptEvent[]>(transcriptUrl).catch(() => []);
      setAgentActivity(data);
      if (projectData) {
        onProjectUpdatedRef.current(projectData);
      }
      setAgentSession(sessionData);
      setAgentRawTranscript(rawTranscriptData);
      if (researchPlanTimelineData) {
        setResearchPlanTimelineForCurrentLocale(researchPlanTimelineData);
      }
      setAgentTranscriptEvents((current) => {
        const next = sinceIndex === null ? transcriptData : mergeTranscriptEvents(current, transcriptData);
        transcriptSessionIdRef.current = sessionId;
        transcriptSinceIndexRef.current = maxTranscriptEventIndex(next);
        return next;
      });
    } catch {
      // The activity overlay is opportunistic; project refresh still surfaces hard errors.
    }
  }, [project.id, setResearchPlanTimelineForCurrentLocale, displayLocale]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    void refreshAgentChatHistory();
    const interval = window.setInterval(() => {
      void refreshAgentChatHistory();
    }, 20000);
    return () => window.clearInterval(interval);
  }, [refreshAgentChatHistory]);

  React.useEffect(() => {
    if (!hasActiveDataIntakeJob) return;
    wasActiveDataIntakeJobRef.current = true;
    const interval = window.setInterval(() => {
      void refreshDataIntake();
    }, 2500);
    return () => window.clearInterval(interval);
  }, [hasActiveDataIntakeJob, refreshDataIntake]);

  React.useEffect(() => {
    if (hasActiveDataIntakeJob) return;
    if (!wasActiveDataIntakeJobRef.current) return;
    wasActiveDataIntakeJobRef.current = false;
    void refresh();
    void onProjectChanged();
  }, [hasActiveDataIntakeJob, refresh, onProjectChanged]);

  React.useEffect(() => {
    if (!pendingAnchor) return;
    const handles: number[] = [];
    const tryScroll = (attempt: number) => {
      const element = document.getElementById(pendingAnchor.anchor) ?? fallbackNavigationAnchor(pendingAnchor.anchor);
      if (element) {
        const top = Math.max(0, element.getBoundingClientRect().top + window.scrollY - 8);
        window.scrollTo({ top, behavior: attempt === 0 ? "smooth" : "auto" });
        element.classList.add("navigation-highlight");
        window.setTimeout(() => element.classList.remove("navigation-highlight"), 1400);
        setPendingAnchor(null);
        return;
      }
      if (attempt >= 10) {
        setPendingAnchor(null);
        return;
      }
      handles.push(window.setTimeout(() => tryScroll(attempt + 1), attempt < 3 ? 90 : 180));
    };
    handles.push(window.setTimeout(() => tryScroll(0), 90));
    return () => handles.forEach((handle) => window.clearTimeout(handle));
  }, [pendingAnchor, tab]);

  React.useEffect(() => {
    const intervalMs = busy || liveAgentOrModelActivity ? 2500 : effectiveProject.current_phase === "AUTONOMOUS_LOOP" ? 6000 : 12000;
    const interval = window.setInterval(
      () => {
        setActivityTick((current) => current + 1);
        void refreshAgentActivity();
      },
      intervalMs
    );
    return () => window.clearInterval(interval);
  }, [busy, liveAgentOrModelActivity, effectiveProject.current_phase, refreshAgentActivity]);

  React.useEffect(() => {
    if (pendingIntervention || userSettings.interventionCountdownSeconds <= 0) return;
    for (const job of jobs) {
      const intervention = firstAutonomyIntervention(job.output);
      if (!intervention) continue;
      const key = autonomyInterventionKey(intervention, job.id);
      if (seenInterventionKeysRef.current.has(key)) continue;
      seenInterventionKeysRef.current.add(key);
      setPendingIntervention({
        payload: intervention,
        startedAt: Date.now(),
        durationSeconds: userSettings.interventionCountdownSeconds
      });
      return;
    }
  }, [jobs, pendingIntervention, userSettings.interventionCountdownSeconds]);

  const addQueuedUploadFiles = React.useCallback(
    (files: FileList | File[]) => {
      if (queuedUploadProgress?.active) return;
      const incoming = Array.from(files);
      if (!incoming.length) return;
      const replaceCompletedQueue =
        queuedUploadProgress !== null && !queuedUploadProgress.active && queuedUploadProgress.overall >= 100;
      setQueuedUploadProgress(null);
      if (replaceCompletedQueue) {
        setQueuedUploadFileColumnHints({});
      }
      void readQueuedFileColumnHints(incoming, setQueuedUploadFileColumnHints);
      setQueuedUploadFiles((current) => {
        const base = replaceCompletedQueue ? [] : current;
        const seen = new Set(base.map(uploadFileKey));
        const next = [...base];
        for (const item of incoming) {
          const key = uploadFileKey(item);
          if (seen.has(key)) continue;
          seen.add(key);
          next.push(item);
        }
        return next;
      });
    },
    [queuedUploadProgress]
  );

  const removeQueuedUploadFile = React.useCallback(
    (fileToRemove: File) => {
      if (queuedUploadProgress?.active) return;
      const key = uploadFileKey(fileToRemove);
      setQueuedUploadProgress(null);
      setQueuedUploadFileColumnHints((current) => {
        const next = { ...current };
        delete next[fileToRemove.name];
        return next;
      });
      setQueuedUploadFiles((current) => current.filter((item) => uploadFileKey(item) !== key));
    },
    [queuedUploadProgress?.active]
  );

  React.useEffect(() => {
    setQueuedUploadPrimaryFileName((current) => {
      const tableNames = queuedUploadFiles.filter(isTableUploadFile).map((item) => item.name);
      if (!tableNames.length) return "";
      if (current && tableNames.includes(current)) return current;
      return "";
    });
  }, [queuedUploadFiles]);

  React.useEffect(() => {
    if (queuedUploadProgress?.active !== true) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [queuedUploadProgress?.active]);

  const dataUploadDraft = React.useMemo<DataUploadDraft>(
    () => ({
      queuedFiles: queuedUploadFiles,
      primaryFileName: queuedUploadPrimaryFileName,
      uploadProgress: queuedUploadProgress,
      fileColumnHints: queuedUploadFileColumnHints,
      addFiles: addQueuedUploadFiles,
      removeFile: removeQueuedUploadFile,
      setPrimaryFileName: setQueuedUploadPrimaryFileName,
      setUploadProgress: setQueuedUploadProgress
    }),
    [
      queuedUploadFiles,
      queuedUploadPrimaryFileName,
      queuedUploadProgress,
      queuedUploadFileColumnHints,
      addQueuedUploadFiles,
      removeQueuedUploadFile
    ]
  );

  function navigateToTarget(targetTab: Tab, targetAnchor?: string | null) {
    const normalized = normalizeNavigationTarget(targetTab, targetAnchor);
    if (normalized.targetAnchor) setPendingAnchor({ anchor: normalized.targetAnchor, nonce: Date.now() });
    onTabChange(normalized.targetTab);
  }

  function requestArtifactPreview(artifactId: string, targetTab: Tab, anchor?: string | null) {
    artifactPreviewNonceRef.current += 1;
    setArtifactPreviewRequest({
      artifactId,
      targetTab,
      anchor: anchor ?? null,
      nonce: artifactPreviewNonceRef.current
    });
  }

  function openNotebookArtifact(artifactId: string) {
    requestArtifactPreview(artifactId, "Notebooks", NOTEBOOK_NATIVE_MARIMO_ANCHOR);
    navigateToTarget("Notebooks", NOTEBOOK_NATIVE_MARIMO_ANCHOR);
  }

  async function runAction(action: () => Promise<unknown>, options: RunActionOptions = {}) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      const notebookMessage = notebookChatMessageFromJob(result, text);
      if (notebookMessage) {
        setAgentChatMessages((current) => upsertAgentChatMessages(current, [notebookMessage]));
      }
      if (options.refreshMode === "data-intake") {
        await refreshDataIntake();
      } else if (options.refreshMode !== "none") {
        await refresh();
        await onProjectChanged();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function uploadDataBundleFromHome(files: FileList | File[]) {
    const uploadFiles = Array.from(files);
    if (!uploadFiles.length || queuedUploadProgress?.active) return;
    addQueuedUploadFiles(uploadFiles);
    navigateToTarget("Data", "dataset-upload");
    const unsupportedFiles = uploadFiles.filter((item) => !isTableUploadFile(item) && !isRelationalHintUploadFile(item));
    if (unsupportedFiles.length) return;
    const uploadTotalBytes = uploadFiles.reduce((total, item) => total + item.size, 0);
    setQueuedUploadProgress(buildUploadProgress(uploadFiles, 0, uploadTotalBytes, true, "transferring"));
    const body = new FormData();
    uploadFiles.forEach((queuedFile) => body.append("files", queuedFile));
    body.append("locale", displayLocale);
    let uploaded = false;
    await runAction(async () => {
      const job = await uploadFormData<Job>(
        `/api/projects/${project.id}/datasets/upload-bundle`,
        body,
        (event) => {
          const requestTotal = event.lengthComputable && event.total > 0 ? event.total : uploadTotalBytes;
          const estimatedFileBytes =
            requestTotal > 0 ? Math.min(uploadTotalBytes, (event.loaded / requestTotal) * uploadTotalBytes) : 0;
          setQueuedUploadProgress(buildUploadProgress(uploadFiles, estimatedFileBytes, uploadTotalBytes, true, "transferring"));
        },
        () => {
          setQueuedUploadProgress(buildUploadProgress(uploadFiles, uploadTotalBytes, uploadTotalBytes, true, "server_processing"));
        }
      );
      uploaded = true;
      setQueuedUploadProgress(buildUploadProgress(uploadFiles, uploadTotalBytes, uploadTotalBytes, false, "complete"));
      setAgentChatMessages((current) =>
        upsertAgentChatMessages(current, [
          {
            id: `local-status-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            role: "system",
            text: text.uploadCompleteChatMessage,
            createdAt: new Date().toISOString()
          }
        ])
      );
      return job;
    }, { refreshMode: "data-intake" });
    if (!uploaded) {
      setQueuedUploadProgress((current) => (current ? { ...current, active: false } : current));
    }
  }

  async function startQueuedAgentJobs(jobIds: string[]) {
    if (!jobIds.length) return;
    const runs = jobIds.map((jobId) => api<Job>(`/api/jobs/${jobId}/run`, { method: "POST" }));
    await refreshAgentActivity();
    const results = await Promise.allSettled(runs);
    const failures = results.filter((result) => result.status === "rejected");
    if (failures.length) {
      const first = failures[0];
      setError(first.status === "rejected" && first.reason instanceof Error ? first.reason.message : "Worker failed to start.");
    }
    await refreshAgentActivity();
    await refresh();
    await onProjectChanged();
  }

  async function submitAgentChat(objective: string): Promise<AgentChatResponse | void> {
    const trimmed = objective.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    const createdAt = new Date().toISOString();
    const localTurnId = `local-chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const optimisticUser: AgentChatMessage = {
      id: `${localTurnId}:user`,
      role: "user",
      text: trimmed,
      createdAt,
      transient: true
    };
    const pendingAssistant: AgentChatMessage = {
      id: `${localTurnId}:assistant`,
      role: "system",
      text: text.agentReplyPending,
      responseComposer: {
        schema_version: "agent_response_composer.v1",
        mode: "codex_cli_if_available",
        status: "pending"
      },
      createdAt,
      transient: true
    };
    const pendingWorker = optimisticWorkerEvent(project.id, trimmed, text);
    setPendingAgentChatMessages([optimisticUser, pendingAssistant]);
    setAgentWorkerEvents((current) => [pendingWorker, ...current].slice(0, 8));
    try {
      const result = await api<AgentChatResponse>(`/api/projects/${project.id}/agent-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          locale: displayLocale,
          agent_model: userSettings.agentModel,
          utility_model: userSettings.utilityModel
        })
      });
      const responseCreatedAt = result.job?.updated_at ?? new Date().toISOString();
      const composerStatus = String(result.response_composer?.status ?? result.job?.status ?? "");
      const queuedForWorker =
        result.artifact_id.startsWith("pending_") || ["queued", "running", "pending", "in_progress", "waiting_for_agent"].includes(composerStatus);
      if (queuedForWorker) {
        const turnId = `turn:${result.job?.id ?? result.artifact_id}`;
        setPendingAgentChatMessages([
          { ...optimisticUser, id: `${turnId}:user`, transient: true },
          {
            ...pendingAssistant,
            id: `${turnId}:system`,
            text: result.assistant_message || pendingAssistant.text,
            actions: result.actions,
            actionSummary: result.action_summary,
            responseBrief: result.response_brief ?? null,
            responseComposer: result.response_composer ?? pendingAssistant.responseComposer,
            createdAt: responseCreatedAt,
            transient: true
          }
        ]);
        setAgentWorkerEvents((current) =>
          [...result.worker_events, ...current.filter((event) => event.job_id !== pendingWorker.job_id)].slice(0, 8)
        );
        await refreshAgentActivity();
        await refresh();
        await onProjectChanged();
        return result;
      }
      setPendingAgentChatMessages([]);
      const turnId = `turn:${result.job?.id ?? result.artifact_id}`;
      setAgentChatMessages((current) =>
        upsertAgentChatMessages(current, [
          {
            id: `${turnId}:user`,
            role: "user",
            text: result.user_message,
            createdAt: responseCreatedAt
          },
          {
            id: `${turnId}:system`,
            role: "system",
            text: result.assistant_message,
            actions: result.actions,
            actionSummary: result.action_summary,
            responseBrief: result.response_brief ?? null,
            responseComposer: result.response_composer ?? null,
            createdAt: responseCreatedAt
          }
        ])
      );
      setAgentWorkerEvents((current) =>
        [...result.worker_events, ...current.filter((event) => event.job_id !== pendingWorker.job_id)].slice(0, 8)
      );
      const workerJobIds = autoStartWorkerJobIds(result.actions);
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
      if (workerJobIds.length) void startQueuedAgentJobs(workerJobIds);
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setPendingAgentChatMessages([]);
      setAgentChatMessages((current) =>
        upsertAgentChatMessages(current, [
          optimisticUser,
          {
            id: pendingAssistant.id,
            role: "system",
            text: `${text.agentReplyFailed}\n${message}`,
            actionSummary: {
              schema_version: "agent_action_summary.v1",
              outcome: "failed",
              headline: "Request failed",
              what_changed: [],
              what_needs_review: [message],
              next_step: { label: text.agentChatTitle, target_tab: "Home", target_anchor: null, status: "failed" },
              boundaries: [],
              actions: []
            },
            createdAt: new Date().toISOString()
          }
        ])
      );
      setAgentWorkerEvents((current) => current.filter((event) => event.job_id !== pendingWorker.job_id));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function submitAgentChatWithoutResponse(objective: string): Promise<void> {
    await submitAgentChat(objective);
  }

  async function submitAgentConsoleMessage(message: string): Promise<void> {
    const trimmed = message.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      await api<AgentConsoleMessageResponse>(`/api/projects/${project.id}/agent-session/console-message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, locale: displayLocale })
      });
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeAutonomyMode(nextMode: AutonomyMode): Promise<void> {
    const currentMode = effectiveProject.autonomy_mode ?? "approval_based";
    if (nextMode === currentMode) return;
    setBusy(true);
    setError(null);
    const userText = nextMode === "full_auto" ? text.fullAutoMode : text.approvalBasedMode;
    const localTurnId = `local-mode-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setPendingAgentChatMessages([
      { id: `${localTurnId}:user`, role: "user", text: userText, createdAt: new Date().toISOString(), transient: true },
      {
        id: `${localTurnId}:assistant`,
        role: "system",
        text: text.agentReplyPending,
        createdAt: new Date().toISOString(),
        transient: true
      }
    ]);
    try {
      await apiWithMetadataBusyRetry<Project>(`/api/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autonomy_mode: nextMode, locale: displayLocale })
      });
      setPendingAgentChatMessages([]);
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setPendingAgentChatMessages([]);
      setAgentChatMessages((current) => upsertAgentChatMessages(current, [{ role: "system", text: message, transient: true }]));
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutonomyPower(): Promise<void> {
    const poweredOn = effectiveProject.current_phase === "AUTONOMOUS_LOOP";
    setBusy(true);
    setError(null);
    const userText = poweredOn ? text.stopAgentLoopUserMessage : text.startAgentLoopUserMessage;
    const localTurnId = `local-power-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setPendingAgentChatMessages([
      { id: `${localTurnId}:user`, role: "user", text: userText, createdAt: new Date().toISOString(), transient: true },
      {
        id: `${localTurnId}:assistant`,
        role: "system",
        text: text.agentReplyPending,
        createdAt: new Date().toISOString(),
        transient: true
      }
    ]);
    try {
      const job = await apiWithMetadataBusyRetry<Job>(`/api/projects/${project.id}/autonomy/${poweredOn ? "stop" : "start"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: poweredOn
          ? JSON.stringify({ locale: displayLocale })
          : JSON.stringify({
              autonomy_mode: effectiveProject.autonomy_mode,
              runner_mode: effectiveProject.autonomy_mode === "full_auto" ? "codex_cli_if_available" : "harness_only",
              locale: displayLocale,
              agent_model: userSettings.agentModel,
              utility_model: userSettings.utilityModel
            })
      });
      const workerEvents = workerEventsFromJob(job, Date.now(), text);
      const assistantMessage =
        typeof job.output.assistant_message === "string"
          ? job.output.assistant_message
          : poweredOn
            ? text.agentLoopStopped
            : text.agentLoopStarted;
      const chatArtifactId =
        typeof job.output.agent_chat_turn_artifact_id === "string" ? job.output.agent_chat_turn_artifact_id : null;
      setPendingAgentChatMessages([]);
      setAgentChatMessages((current) => [
        ...current.slice(-AGENT_CHAT_MESSAGE_HISTORY_LIMIT),
        ...(chatArtifactId
          ? [
              { id: `${chatArtifactId}:user`, role: "user" as const, text: userText, createdAt: job.updated_at },
              { id: `${chatArtifactId}:system`, role: "system" as const, text: assistantMessage, createdAt: job.updated_at }
            ]
          : [{ role: "system" as const, text: assistantMessage, transient: true }])
      ]);
      setAgentWorkerEvents((current) => [...workerEvents, ...current].slice(0, 8));
      const intervention = firstAutonomyIntervention(job.output);
      if (!poweredOn && intervention && userSettings.interventionCountdownSeconds > 0) {
        seenInterventionKeysRef.current.add(autonomyInterventionKey(intervention, job.id));
        setPendingIntervention({
          payload: intervention,
          startedAt: Date.now(),
          durationSeconds: userSettings.interventionCountdownSeconds
        });
      }
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setPendingAgentChatMessages([]);
      setAgentChatMessages((current) => upsertAgentChatMessages(current, [{ role: "system", text: message, transient: true }]));
    } finally {
      setBusy(false);
    }
  }

  async function cancelWorkerJob(jobId: string): Promise<void> {
    if (jobId.startsWith("local-")) return;
    setBusy(true);
    setError(null);
    setAgentWorkerEvents((current) => current.filter((event) => event.job_id !== jobId));
    try {
      await api<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      await refreshAgentActivity();
      await refresh();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await refreshAgentActivity();
    } finally {
      setBusy(false);
    }
  }

  function openAgentChatAction(action: AgentChatAction) {
    const artifactId = agentChatActionArtifactId(action, notebookIndex);
    const rawTargetTab = action.target_tab === "Notebooks" ? "Notebooks" : tabFromString(action.target_tab, "Home");
    const normalized = normalizeNavigationTarget(rawTargetTab, action.target_anchor ?? null);
    if (agentChatActionRequiresArtifactTarget(action, normalized.targetTab) && !artifactId) {
      setError(text.chatActionMissingArtifact);
      return;
    }
    if (artifactId) {
      requestArtifactPreview(artifactId, normalized.targetTab, normalized.targetAnchor ?? null);
    }
    navigateToTarget(normalized.targetTab, normalized.targetAnchor ?? null);
  }

  function openHomeMemoryItem(item: HomeMemoryItem) {
    const targetTab = tabFromString(item.target_tab, "Insight");
    if (item.artifact_id) {
      requestArtifactPreview(item.artifact_id, targetTab, item.target_anchor);
    }
    navigateToTarget(targetTab, item.target_anchor);
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
    const targetTab = tabFromString(action.target_tab, "Home");
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

  async function equipLibraryAsset(asset: LibraryAsset) {
    if (!asset.latest_version_id) throw new Error("Selected asset has no active version.");
    await api(`/api/projects/${project.id}/asset-references`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_asset_id: asset.id,
        target_asset_version_id: asset.latest_version_id,
        relation_type: asset.asset_type === "skill" ? "equipped_for_agent_context" : "uses"
      })
    });
  }

  async function createAndEquipSkill(draft: SkillDraft) {
    const name = draft.name.trim();
    if (!name) throw new Error("Skill name is required.");
    const tags = splitSkillTags(draft.tags);
    const instructions = draft.instructions
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const asset = await api<LibraryAsset>("/api/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_type: "skill",
        name,
        description: draft.description.trim() || null,
        tags,
        semantic_tags: Array.from(new Set(["skill", ...tags])),
        content: {
          schema_version: "tablex_skill.v1",
          creation_source: "tablex_skill_panel",
          instructions,
          guidance: "Use as Codex context and reusable craft knowledge, not as deterministic harness logic."
        }
      })
    });
    await equipLibraryAsset(asset);
    return asset;
  }

  async function catchPendingIntervention() {
    if (!pendingIntervention) return;
    setPendingIntervention(null);
    await changeAutonomyMode("approval_based");
    onTabChange("Assumptions");
  }

  return (
    <>
      <section className="detail">
        {error ? <div className="banner danger">{error}</div> : null}
        <AgentActivityRail
          text={text}
          projectName={effectiveProject.name}
          jobs={jobs}
          events={agentWorkerEvents}
          activity={agentActivity}
          tick={activityTick}
          onWorkerMessage={submitAgentChatWithoutResponse}
          onCancelWorker={cancelWorkerJob}
          onNavigateToTarget={navigateToTarget}
          onOpenArtifact={(artifactId, targetTab, anchor) => {
            requestArtifactPreview(artifactId, targetTab, anchor ?? null);
            navigateToTarget(targetTab, anchor ?? null);
          }}
        />
      {tab === "Home" && (
        <HomeTab
          project={effectiveProject}
          overview={overview}
          recommendation={focusRecommendation}
          strategyBrief={strategyBrief}
          researchBriefs={researchBriefs}
          researchPlanTimeline={researchPlanTimeline}
          ideas={ideas}
          artifacts={artifacts}
          jobs={jobs}
          runs={runs}
          assumptions={assumptions}
          insights={insights}
          reports={reports}
          leaderboard={leaderboard}
          notebookIndex={notebookIndex}
          libraryAssets={libraryAssets}
          projectAssetReferences={projectAssetReferences}
          busy={busy}
          text={text}
          locale={displayLocale}
          messages={visibleAgentChatMessages}
          submitShortcut={resolveChatSubmitShortcut(userSettings)}
          userAvatarSrc={userSettings.userAvatarDataUrl}
          latestContract={artifacts.find((artifact) => artifact.asset_type === "agent_task_contract") ?? null}
          tableeMotionState={tableeMotionState}
          turnState={turnState}
          agentSession={agentSession}
          agentTranscriptEvents={agentTranscriptEvents}
          agentRawTranscript={agentRawTranscript}
          dataUploadDraft={dataUploadDraft}
          onSubmitAgentChat={submitAgentChatWithoutResponse}
          onSubmitAgentConsole={submitAgentConsoleMessage}
          onActionOpen={openAgentChatAction}
          onOpenMemoryItem={openHomeMemoryItem}
          onTabChange={onTabChange}
          onNavigateToTarget={navigateToTarget}
          onHomeDataUpload={(files) => void uploadDataBundleFromHome(files)}
          onFocusAction={(action) => void runFocusAction(action)}
          onEquipSkill={(asset) => runAction(() => equipLibraryAsset(asset))}
          onCreateSkill={(draft) => runAction(() => createAndEquipSkill(draft))}
          onAutonomyModeChange={(mode) => void changeAutonomyMode(mode)}
          onAutonomyPowerToggle={() => void toggleAutonomyPower()}
        />
      )}
      {tab === "Raw" && (
        <RawTab
          busy={busy}
          text={text}
          locale={displayLocale}
          messages={visibleAgentChatMessages}
          jobs={jobs}
          agentSession={agentSession}
          agentTranscriptEvents={agentTranscriptEvents}
          agentRawTranscript={agentRawTranscript}
          submitShortcut={resolveChatSubmitShortcut(userSettings)}
          turnState={turnState}
          scrollResetKey={`${project.id}:${agentSession?.id ?? "no-agent-session"}`}
          consoleDisabledReason={agentConsoleDisabledReason(agentSession, text)}
          onSubmit={submitAgentConsoleMessage}
        />
      )}
      {tab === "Overview" && (
        <OverviewTab
          overview={overview}
          assumptions={assumptions}
          jobs={jobs}
          artifacts={artifacts}
          text={text}
        />
      )}
      {tab === "Insight" && (
        <ReportsTab
          project={effectiveProject}
          reports={reports}
          decisionReport={decisionReport}
          artifacts={artifacts}
          visualizations={visualizations}
          notebookIndex={notebookIndex}
          ideas={ideas}
          insights={insights}
          busy={busy}
          locale={displayLocale}
          text={text}
          runAction={runAction}
          onAskAgent={submitAgentChat}
          onOpenNotebookArtifact={openNotebookArtifact}
        />
      )}
      {tab === "Data" && (
        <DataTab
          project={effectiveProject}
          datasets={datasets}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          benchmarks={benchmarks}
          jobs={jobs}
          busy={busy}
          text={text}
          locale={displayLocale}
          runAction={runAction}
          uploadDraft={dataUploadDraft}
          onProjectChanged={onProjectChanged}
          onProjectUpdated={onProjectUpdated}
          onObjectiveChanged={refreshResearchPlanTimeline}
          onOpenNotebookArtifact={openNotebookArtifact}
          onStatusMessage={(message) =>
            setAgentChatMessages((current) =>
              upsertAgentChatMessages(current, [
                {
                  id: `local-status-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                  role: "system",
                  text: message,
                  createdAt: new Date().toISOString()
                }
              ])
            )
          }
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
          project={effectiveProject}
          candidates={candidates}
          specs={specs}
          artifacts={artifacts}
          busy={busy}
          runAction={runAction}
        />
      )}
      {tab === "Approach" && (
        <ApproachTab
          project={effectiveProject}
          strategyBrief={strategyBrief}
          researchBriefs={researchBriefs}
          ideas={ideas}
          artifacts={artifacts}
          busy={busy}
          locale={displayLocale}
          text={text}
          runAction={runAction}
          onStrategyAction={(action) => void runStrategyAction(action)}
        />
      )}
      {tab === "Experiments" && (
        <ExperimentsTab
          project={effectiveProject}
          jobs={jobs}
          runs={runs}
          agentTaskResults={agentTaskResults}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          busy={busy}
          locale={displayLocale}
          text={text}
          runAction={runAction}
          onAskAgent={submitAgentChat}
          onOpenNotebookArtifact={openNotebookArtifact}
        />
      )}
      {tab === "Notebooks" && (
        <NotebooksTab
          project={effectiveProject}
          datasets={datasets}
          runs={runs}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          analysisStory={analysisStory}
          previewRequest={artifactPreviewRequest}
          busy={busy}
          locale={displayLocale}
          runAction={runAction}
          onAskAgent={submitAgentChat}
        />
      )}
      {tab === "Leaderboard" && (
        <LeaderboardTab
          project={effectiveProject}
          specs={specs}
          datasets={datasets}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          leaderboard={leaderboard}
          pilotDeployments={pilotDeployments}
          resultReadout={resultReadout}
          busy={busy}
          locale={displayLocale}
          text={text}
          runAction={runAction}
          onAskAgent={submitAgentChat}
          onOpenNotebookArtifact={openNotebookArtifact}
        />
      )}
      {tab === "Reports" && (
        <ReportsTab
          project={effectiveProject}
          reports={reports}
          decisionReport={decisionReport}
          artifacts={artifacts}
          visualizations={visualizations}
          notebookIndex={notebookIndex}
          ideas={ideas}
          insights={insights}
          busy={busy}
          locale={displayLocale}
          text={text}
          runAction={runAction}
          onAskAgent={submitAgentChat}
          onOpenNotebookArtifact={openNotebookArtifact}
        />
      )}
      {tab === "Assets" && (
        <AssetsTab
          project={effectiveProject}
          artifacts={artifacts}
          modelVersions={modelVersions}
          validationsByModelVersion={validationsByModelVersion}
          notebookIndex={notebookIndex}
          researchPlanTimeline={researchPlanTimeline}
          libraryAssets={libraryAssets}
          projectAssetReferences={projectAssetReferences}
          previewRequest={artifactPreviewRequest}
          busy={busy}
          text={text}
          runAction={runAction}
          onEquipSkill={(asset) => runAction(() => equipLibraryAsset(asset))}
          onCreateSkill={(draft) => runAction(() => createAndEquipSkill(draft))}
          onOpenNotebookArtifact={openNotebookArtifact}
        />
      )}
      {tab === "Library" && (
        <LibraryTab
          project={effectiveProject}
          assets={libraryAssets}
          references={projectAssetReferences}
          busy={busy}
          text={text}
          runAction={runAction}
          onEquipSkill={(asset) => runAction(() => equipLibraryAsset(asset))}
          onCreateSkill={(draft) => runAction(() => createAndEquipSkill(draft))}
        />
      )}
      {tab === "Jobs" && <JobsTab jobs={jobs} busy={busy} runAction={runAction} />}
        {tab === "Lineage" && <LineageTab lineage={lineage} />}
      </section>
      {pendingIntervention ? (
        <AutonomyInterventionDialog
          intervention={pendingIntervention}
          text={text}
          tick={activityTick}
          onContinue={() => setPendingIntervention(null)}
          onCatch={() => void catchPendingIntervention()}
        />
      ) : null}
    </>
  );
}

function HomeTab({
  project,
  overview,
  recommendation,
  strategyBrief,
  researchBriefs,
  researchPlanTimeline,
  ideas,
  artifacts,
  jobs,
  runs,
  assumptions,
  insights,
  reports,
  leaderboard,
  notebookIndex,
  libraryAssets,
  projectAssetReferences,
  busy,
  text,
  locale,
  messages,
  submitShortcut,
  userAvatarSrc,
  latestContract,
  tableeMotionState,
  turnState,
  agentSession,
  agentTranscriptEvents,
  agentRawTranscript,
  dataUploadDraft,
  onSubmitAgentChat,
  onSubmitAgentConsole,
  onActionOpen,
  onOpenMemoryItem,
  onTabChange,
  onNavigateToTarget,
  onHomeDataUpload,
  onFocusAction,
  onEquipSkill,
  onCreateSkill,
  onAutonomyModeChange,
  onAutonomyPowerToggle
}: {
  project: Project;
  overview: Overview | null;
  recommendation: FocusRecommendation;
  strategyBrief: AdaptiveStrategyBrief | null;
  researchBriefs: ResearchBrief[];
  researchPlanTimeline: ResearchPlanTimelineResponse | null;
  ideas: Idea[];
  artifacts: Artifact[];
  jobs: Job[];
  runs: Run[];
  assumptions: Assumption[];
  insights: Insight[];
  reports: Report[];
  leaderboard: LeaderboardEntry[];
  notebookIndex: NotebookIndex | null;
  libraryAssets: LibraryAsset[];
  projectAssetReferences: AssetReference[];
  busy: boolean;
  text: LocaleMessages;
  locale: string;
  messages: AgentChatMessage[];
  submitShortcut: ChatSubmitShortcut;
  userAvatarSrc: string | null;
  latestContract: Artifact | null;
  tableeMotionState: TableeMotionState;
  turnState: TurnState;
  agentSession: AgentSession | null;
  agentTranscriptEvents: AgentTranscriptEvent[];
  agentRawTranscript: AgentRawTranscript | null;
  dataUploadDraft: DataUploadDraft;
  onSubmitAgentChat: (objective: string) => Promise<void>;
  onSubmitAgentConsole: (objective: string) => Promise<void>;
  onActionOpen: (action: AgentChatAction) => void;
  onOpenMemoryItem: (item: HomeMemoryItem) => void;
  onTabChange: (tab: Tab) => void;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
  onHomeDataUpload: (files: FileList | File[]) => void;
  onFocusAction: (action: FocusAction | null) => void;
  onEquipSkill: (asset: LibraryAsset) => Promise<void>;
  onCreateSkill: (draft: SkillDraft) => Promise<void>;
  onAutonomyModeChange: (mode: AutonomyMode) => void;
  onAutonomyPowerToggle: () => void;
}) {
  const planJobs = jobs.filter((job) => !isTerminalJob(job)).slice(0, 18);
  const highRiskAssumptions = assumptions.filter(isHighRiskAssumption);
  const latestResearchPlan = latestArtifactByType(artifacts, "research_plan");
  const latestBrief = researchBriefs[0] ?? null;
  const topRun = leaderboard[0] ?? null;
  const recommendedNotebook = notebookIndex?.recommended_notebook ?? null;
  const latestIdea = ideas[0] ?? null;
  const mode = project.autonomy_mode ?? "approval_based";
  const datasetCount = overview?.counts.datasets ?? 0;
  const totalArtifactCount = overview?.counts.artifacts ?? artifacts.length;
  const projectStateLoaded = overview !== null;
  const activeDataIntakeJobs = jobs.filter((job) => isDataIntakeJob(job) && !isTerminalJob(job));
  const showHomeDataUpload =
    datasetCount === 0 ||
    activeDataIntakeJobs.length > 0 ||
    dataUploadDraft.queuedFiles.length > 0 ||
    dataUploadDraft.uploadProgress !== null;
  const autonomyPoweredOn = project.current_phase === "AUTONOMOUS_LOOP";
  const canStartAutonomy = datasetCount > 0;
  const focusAction = recommendation.primaryAction;
  const [agentViewMode, setAgentViewMode] = React.useState<"chat" | "raw">("chat");
  const ideaFindingItems = buildIdeaFindingItems(ideas, insights, artifacts, text, locale);
  const equippedSkills = equippedSkillItems(projectAssetReferences, libraryAssets);
  const rawAgentEvents = buildRawAgentEvents(messages, jobs, agentTranscriptEvents, agentSession);
  const agentWorkspaceScrollResetKey = `${project.id}:${agentSession?.id ?? "no-agent-session"}`;
  const authoredResearchPlanBlocks = buildResearchPlanBlocks({
    project,
    datasetCount,
    artifacts,
    researchBriefs,
    researchPlanTimeline,
    notebookIndex,
    equippedSkills,
    jobs: planJobs,
    poweredOn: autonomyPoweredOn,
    text,
    locale,
    turnState,
    onTabChange,
    onNavigateToTarget,
    onOpenArtifact: (artifactId, targetTab, targetAnchor) =>
      onActionOpen({
        type: "open_artifact",
        status: "ready",
        label: text.openSurface,
        target_tab: targetTab,
        target_anchor: targetAnchor ?? null,
        detail: text.researchPlanDetailEvidence,
        artifact_id: artifactId
      })
  });
  const researchPlanBlocks = authoredResearchPlanBlocks;
  const researchPlanFocusBlock = primaryResearchPlanFocusBlock(researchPlanBlocks);
  const researchPlanCurrentWork = researchPlanTimeline?.current_work ?? null;
  const missionCurrentWorkUnreported =
    autonomyPoweredOn &&
    turnState.state === "agent_running" &&
    (!researchPlanCurrentWork?.node_id || researchPlanCurrentWork.source === "research_plan_revision_status");
  const missionUsesPlanFocus = Boolean(researchPlanFocusBlock) && !missionCurrentWorkUnreported;
  const missionTitle = missionCurrentWorkUnreported ? text.turnStateAgentRunning : (researchPlanFocusBlock?.title ?? recommendation.title);
  const missionReason = missionCurrentWorkUnreported
    ? turnState.detail || text.researchPlanCurrentWorkUnreported
    : (researchPlanFocusBlock?.subtitle ?? recommendation.reason);
  const missionPlanStatus = missionCurrentWorkUnreported ? "active" : (researchPlanFocusBlock?.status ?? recommendation.riskLevel ?? "ready");
  const missionPlanLabel =
    missionCurrentWorkUnreported
      ? text.researchPlanCurrentWorkUnreported
      : missionUsesPlanFocus && researchPlanFocusBlock
        ? researchPlanBlockRuntimeAwareStatusLabel(
            researchPlanFocusBlock,
            researchPlanCurrentWork,
            autonomyPoweredOn,
            turnState,
            text
          )
        : displayStatusLabel(missionPlanStatus, text);
  const missionRuntimeLabel = autonomyPoweredOn ? turnStateLabel(turnState, text, locale) : null;
  const missionFocusLabel = missionCurrentWorkUnreported || missionUsesPlanFocus ? text.openSurface : (focusAction?.label ?? text.recommendedFocus);
  const missionFocusDisabled = busy || (!missionCurrentWorkUnreported && !missionUsesPlanFocus && (!focusAction || focusAction.disabled));
  const handleMissionFocus = () => {
    if (missionCurrentWorkUnreported) {
      onNavigateToTarget("Home", "agent-workspace");
      return;
    }
    if (missionUsesPlanFocus) {
      researchPlanFocusBlock?.onClick?.();
      return;
    }
    onFocusAction(focusAction);
  };

  return (
    <div className="mission-home stack">
      <section className="mission-hero">
        <div className="mission-hero-copy">
          <div className="eyebrow">{text.missionControlTitle}</div>
          <h2>{missionTitle}</h2>
          <p>{missionReason}</p>
          <div className="badge-row">
            <span className={navigatorStatusClass(autonomyPoweredOn ? missionPlanStatus : "off")}>
              {text.planStateLabel}: {autonomyPoweredOn ? missionPlanLabel : text.agentPowerOff}
            </span>
            {missionRuntimeLabel ? <span className="badge muted">{text.executionStateLabel}: {missionRuntimeLabel}</span> : null}
            <span className="badge muted">
              {project.target_column ? `${text.targetLabelShort}: ${project.target_column}` : text.surfaceTargetOpen}
            </span>
          </div>
        </div>
        <div className="mission-hero-actions">
          <AutonomyPowerPanel
            poweredOn={autonomyPoweredOn}
            canStart={canStartAutonomy}
            busy={busy}
            mode={mode}
            targetColumn={project.target_column}
            text={text}
            onOpenDataUpload={() => onNavigateToTarget("Data", "dataset-upload")}
            onToggle={onAutonomyPowerToggle}
          />
          <AutonomyModePanel
            mode={mode}
            busy={busy}
            text={text}
            onChange={onAutonomyModeChange}
          />
          <button
            className="primary-button mission-focus-button"
            disabled={missionFocusDisabled}
            onClick={handleMissionFocus}
            type="button"
          >
            {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            {missionFocusLabel}
          </button>
        </div>
      </section>

      {showHomeDataUpload ? (
        <HomeDataUploadDropzone
          draft={dataUploadDraft}
          text={text}
          disabled={busy || activeDataIntakeJobs.length > 0}
          onFiles={onHomeDataUpload}
          onOpenDataUpload={() => onNavigateToTarget("Data", "dataset-upload")}
        />
      ) : null}

      {activeDataIntakeJobs.length ? (
        <DataIntakeStatusCard
          jobs={activeDataIntakeJobs}
          text={text}
          onOpenDataUpload={() => onNavigateToTarget("Data", "dataset-upload")}
        />
      ) : null}

      <div className="mission-grid">
        <section id="research-plan" className="mission-plan-panel">
          <div className="mission-panel-head">
            <div>
              <span>{text.researchPlanTitle}</span>
              <strong>
                {displayTextOrFallback(missionTitle, locale, text.researchPlanTimelineHint)}
              </strong>
            </div>
          </div>
          <ResearchPlanTimeline
              apiBase={apiBase}
            blocks={researchPlanBlocks}
            contractValidation={researchPlanTimeline?.contract_validation ?? null}
            currentWork={researchPlanCurrentWork}
            ignoredSourceArtifact={researchPlanTimeline?.ignored_source_artifact ?? null}
            latestResearchPlan={latestResearchPlan}
            locale={locale}
            poweredOn={autonomyPoweredOn}
            text={text}
            turnState={turnState}
          />
          <div className="mission-plan-facts">
            <Metric label={text.metricDatasets} value={projectStateLoaded ? datasetCount : "..."} />
            <Metric label={text.metricRuns} value={runs.length} />
            <Metric label={text.metricRisks} value={highRiskAssumptions.length} />
            <Metric label={text.metricArtifacts} value={projectStateLoaded ? totalArtifactCount : "..."} />
          </div>
        </section>
      </div>

      <section className="mission-memory-panel">
        <div className="mission-panel-head">
          <div>
            <span>{text.ideasAndFindingsTitle}</span>
            <strong>
              {ideaFindingItems.length
                ? `${ideaFindingItems.length} ${text.ideasAndFindingsReady}`
                : text.ideasAndFindingsEmpty}
            </strong>
          </div>
          <button className="secondary-button" type="button" onClick={() => onTabChange("Insight")}>
            <Lightbulb size={16} />
            {text.openSurface}
          </button>
        </div>
        {ideaFindingItems.length ? (
          <div className="mission-memory-list">
            {ideaFindingItems.slice(0, 5).map((item) => (
              <button
                className={`mission-memory-item ${item.kind}`}
                key={item.id}
                onClick={() => onOpenMemoryItem(item)}
                type="button"
              >
                <span>{item.meta}</span>
                <strong>{item.title}</strong>
                <p>{item.summary}</p>
                <small>{item.cta}</small>
              </button>
            ))}
          </div>
        ) : (
          <EmptyInline text={text.ideasAndFindingsEmpty} />
        )}
      </section>

      <div className="mission-agent-layout" id="agent-workspace">
        <div className="mission-agent-primary">
          <div className="mission-agent-head">
            <div className="mission-panel-title">
              <MessageSquare size={18} />
              <div>
                <strong>{text.agentWorkspaceTitle}</strong>
                <span>{text.missionControlSubtitle}</span>
              </div>
            </div>
            <div className="agent-view-toggle" aria-label={text.agentDisplayModeLabel}>
              <button className={agentViewMode === "chat" ? "active" : ""} onClick={() => setAgentViewMode("chat")} type="button">
                {text.agentModeChat}
              </button>
              <button className={agentViewMode === "raw" ? "active" : ""} onClick={() => setAgentViewMode("raw")} type="button">
                {text.agentModeRaw}
              </button>
            </div>
          </div>
          {agentViewMode === "chat" ? (
            <AgentChatDock
              apiBase={apiBase}
              busy={busy}
              text={text}
              locale={locale}
              messages={messages}
              submitShortcut={submitShortcut}
              userAvatarSrc={userAvatarSrc}
              latestContract={latestContract}
              tableeMotionState={tableeMotionState}
              turnState={turnState}
              scrollResetKey={agentWorkspaceScrollResetKey}
              onSubmit={onSubmitAgentChat}
              onActionOpen={onActionOpen}
            />
          ) : (
            <RawAgentStream
              busy={busy}
              text={text}
              locale={locale}
              events={rawAgentEvents}
              rawTranscript={agentRawTranscript}
              submitShortcut={submitShortcut}
              turnState={turnState}
              scrollResetKey={agentWorkspaceScrollResetKey}
              consoleDisabledReason={agentConsoleDisabledReason(agentSession, text)}
              onSubmit={onSubmitAgentConsole}
            />
          )}
        </div>
        <aside className="mission-evidence-stack">
          <MissionSurfaceButton
            icon={<Database size={17} />}
            label={text.tabData}
            detail={
              projectStateLoaded
                ? `${datasetCount} ${text.surfaceDatasets} / ${project.target_column ? text.surfaceTargetSet : text.surfaceTargetOpen}`
                : "..."
            }
            onClick={() => onTabChange("Data")}
          />
          <MissionSurfaceButton
            icon={<Lightbulb size={17} />}
            label={text.tabInsight}
            detail={`${insights.length} ${text.surfaceInsights} / ${reports.length} ${text.surfaceReports} / ${
              recommendedNotebook ? text.surfaceNotebookReady : text.surfaceNotebookOpen
            }`}
            onClick={() => onTabChange("Insight")}
          />
          <MissionSurfaceButton
            icon={<BarChart3 size={17} />}
            label={text.tabLeaderboard}
            detail={
              topRun
                ? `#1 ${leaderboardEntryModelLabel(topRun)} ${metricLabel(topRun.display_metric_name)}=${formatMaybeNumber(topRun.display_metric_value)}`
                : text.surfaceLeaderboardEmpty
            }
            onClick={() => onTabChange("Leaderboard")}
          />
          <MissionSurfaceButton
            icon={<Layers size={17} />}
            label={text.tabAssets}
            detail={
              projectStateLoaded
                ? `${totalArtifactCount} ${text.surfaceProjectArtifacts} / ${
                  latestContract ? text.surfaceRunnerContractReady : text.surfaceNoContractYet
                }`
                : "..."
            }
            onClick={() => onTabChange("Assets")}
          />
          <div className="mission-supporting">
            <span>{text.supportingSurfacesTitle}</span>
            <div className="button-row">
              {(["Understanding", "Assumptions", "Evaluation", "Experiments", "Jobs", "Lineage"] as Tab[]).map((targetTab) => (
                <button className="text-button" key={targetTab} onClick={() => onTabChange(targetTab)} type="button">
                  {tabLabel(targetTab, text)}
                </button>
              ))}
            </div>
          </div>
          {latestBrief ? (
            <div className="mission-note">
              <span>{text.latestBriefLabel}</span>
              <strong>{displayTextOrFallback(latestBrief.title, locale, text.memoryUntitledSignalTitle)}</strong>
              <small>
                {displayTextOrFallback(
                  latestBrief.key_findings.slice(0, 2).join(" / ") || latestBrief.status,
                  locale,
                  text.memoryNoSummary
                )}
              </small>
            </div>
          ) : null}
          {latestIdea ? (
            <div className="mission-note">
              <span>{text.latestIdeaLabel}</span>
              <strong>{displayTextOrFallback(latestIdea.title, locale, text.memoryUntitledSignalTitle)}</strong>
              <small>{displayTextOrFallback(latestIdea.hypothesis, locale, text.memoryNoSummary)}</small>
            </div>
          ) : null}
          <SkillManagerPanel
            assets={libraryAssets}
            busy={busy}
            compact
            equippedSkills={equippedSkills}
            references={projectAssetReferences}
            text={text}
            onCreateSkill={onCreateSkill}
            onEquipSkill={onEquipSkill}
          />
        </aside>
      </div>
    </div>
  );
}

function AutonomyInterventionDialog({
  intervention,
  text,
  tick,
  onContinue,
  onCatch
}: {
  intervention: PendingAutonomyIntervention;
  text: LocaleMessages;
  tick: number;
  onContinue: () => void;
  onCatch: () => void;
}) {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() + tick - intervention.startedAt) / 1000));
  const remainingSeconds = Math.max(0, intervention.durationSeconds - elapsedSeconds);
  const progress = intervention.durationSeconds > 0 ? Math.max(0, remainingSeconds / intervention.durationSeconds) : 0;

  React.useEffect(() => {
    if (remainingSeconds <= 0) onContinue();
  }, [remainingSeconds, onContinue]);

  const isObjectiveIntervention = intervention.payload.kind === "target_definition";
  const dialogTitle = isObjectiveIntervention
    ? text.autonomyObjectiveInterventionTitle
    : intervention.payload.title ?? text.autonomyInterventionTitle;
  const dialogBody = isObjectiveIntervention
    ? text.autonomyObjectiveInterventionBody
    : intervention.payload.message ?? text.autonomyInterventionBody;

  return (
    <div className="autonomy-intervention-backdrop" role="dialog" aria-modal="true">
      <section className="autonomy-intervention-dialog">
        <div className="agent-worker-topline">
          <strong>{dialogTitle}</strong>
          <span className="waiting">{text.workerStatusApproval}</span>
        </div>
        <p>{dialogBody}</p>
        <div className="agent-worker-context">
          {intervention.payload.target_column ? (
            <span>
              {text.autonomyInterventionTarget}: <strong>{intervention.payload.target_column}</strong>
            </span>
          ) : null}
          {intervention.payload.source_ref ? (
            <span>
              {text.autonomyInterventionDataset}: <strong>{intervention.payload.source_ref}</strong>
            </span>
          ) : null}
          {typeof intervention.payload.confidence === "number" ? (
            <span>
              confidence: <strong>{Math.round(intervention.payload.confidence * 100)}%</strong>
            </span>
          ) : null}
          {intervention.payload.risk_level ? (
            <span>
              risk: <strong>{intervention.payload.risk_level}</strong>
            </span>
          ) : null}
          {intervention.payload.fallback_policy ? (
            <span>
              fallback: <strong>{intervention.payload.fallback_policy}</strong>
            </span>
          ) : null}
        </div>
        <small>{intervention.payload.continued ? text.autonomyInterventionAssumed : text.autonomyInterventionBody}</small>
        <div className="autonomy-countdown">
          <div>
            <span>{text.autonomyInterventionTimeLeft}</span>
            <strong>{remainingSeconds}s</strong>
          </div>
          <span style={{ transform: `scaleX(${progress})` }} />
        </div>
        <div className="autonomy-intervention-actions">
          <button className="secondary-button" type="button" onClick={onContinue}>
            {text.autonomyInterventionContinue}
          </button>
          <button className="primary-button" type="button" onClick={onCatch}>
            {text.autonomyInterventionCatch}
          </button>
        </div>
      </section>
    </div>
  );
}

function AutonomyPowerPanel({
  poweredOn,
  canStart,
  busy,
  mode,
  targetColumn,
  text,
  onOpenDataUpload,
  onToggle
}: {
  poweredOn: boolean;
  canStart: boolean;
  busy: boolean;
  mode: AutonomyMode;
  targetColumn: string | null;
  text: LocaleMessages;
  onOpenDataUpload: () => void;
  onToggle: () => void;
}) {
  const needsUploadedDataset = !poweredOn && !canStart;
  return (
    <div className={`autonomy-power-panel ${poweredOn ? "on" : "off"}`}>
      <button
        className={`autonomy-power-button ${poweredOn ? "on" : "off"}`}
        disabled={busy || (!poweredOn && !canStart)}
        onClick={onToggle}
        type="button"
      >
        {busy ? <Loader2 className="spin" size={22} /> : <Power size={24} />}
        <span>{poweredOn ? text.stopAgent : text.startAgent}</span>
      </button>
      <div>
        <span>{text.autonomyPower}</span>
        <strong>{poweredOn ? text.agentPowerOn : canStart ? text.agentPowerReady : text.agentPowerNoDatasetStatus}</strong>
        <small>
          {needsUploadedDataset ? text.agentPowerNoDatasetDetail : mode === "full_auto" ? text.fullAutoMode : text.approvalBasedMode}
          {!needsUploadedDataset ? (
            <>
              {" · "}
              {targetColumn ? `${text.targetLabelShort}: ${targetColumn}` : text.targetCanWait}
            </>
          ) : null}
        </small>
        {needsUploadedDataset ? (
          <button className="secondary-button autonomy-power-inline-action" onClick={onOpenDataUpload} type="button">
            <Upload size={15} />
            {text.openDataUpload}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function AutonomyModePanel({
  mode,
  busy,
  text,
  onChange
}: {
  mode: AutonomyMode;
  busy: boolean;
  text: LocaleMessages;
  onChange: (mode: AutonomyMode) => void;
}) {
  return (
    <div className="autonomy-mode-panel">
      <span>{text.autonomyMode}</span>
      <div className="segmented-control">
        <button
          className={mode === "approval_based" ? "active" : ""}
          disabled={busy || mode === "approval_based"}
          onClick={() => onChange("approval_based")}
          type="button"
        >
          <Check size={15} />
          {text.approvalBasedMode}
        </button>
        <button
          className={mode === "full_auto" ? "active" : ""}
          disabled={busy || mode === "full_auto"}
          onClick={() => onChange("full_auto")}
          type="button"
        >
          <Play size={15} />
          {text.fullAutoMode}
        </button>
      </div>
      <small>{mode === "full_auto" ? text.fullAutoModeHint : text.approvalBasedModeHint}</small>
    </div>
  );
}

function SkillManagerPanel({
  assets,
  references,
  equippedSkills,
  busy,
  text,
  compact = false,
  onEquipSkill,
  onCreateSkill
}: {
  assets: LibraryAsset[];
  references: AssetReference[];
  equippedSkills: EquippedSkillItem[];
  busy: boolean;
  text: LocaleMessages;
  compact?: boolean;
  onEquipSkill: (asset: LibraryAsset) => Promise<void>;
  onCreateSkill: (draft: SkillDraft) => Promise<void>;
}) {
  const [selectedSkillId, setSelectedSkillId] = React.useState("");
  const [draft, setDraft] = React.useState<SkillDraft>({ name: "", description: "", instructions: "", tags: "" });
  const referencedAssetIds = React.useMemo(
    () => new Set(references.map((reference) => reference.target_asset_id)),
    [references]
  );
  const availableSkills = React.useMemo(
    () =>
      assets.filter(
        (asset) => asset.asset_type === "skill" && asset.latest_version_id && !referencedAssetIds.has(asset.id)
      ),
    [assets, referencedAssetIds]
  );
  const selectedSkill = availableSkills.find((asset) => asset.id === selectedSkillId) ?? null;
  const canCreateSkill = Boolean(draft.name.trim()) && Boolean(draft.instructions.trim() || draft.description.trim());

  async function equipSelectedSkill() {
    if (!selectedSkill) return;
    await onEquipSkill(selectedSkill);
    setSelectedSkillId("");
  }

  async function submitCreatedSkill(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canCreateSkill) return;
    await onCreateSkill(draft);
    setDraft({ name: "", description: "", instructions: "", tags: "" });
  }

  return (
    <section className={`mission-skills-panel ${compact ? "compact" : "full"}`}>
      <div className="skill-panel-head">
        <span>{text.equippedSkillsTitle}</span>
        <small>{text.skillPanelHint}</small>
      </div>
      {equippedSkills.length ? (
        <div className="equipped-skill-list">
          {equippedSkills.slice(0, compact ? 6 : 12).map((skill) => (
            <div className="equipped-skill" key={skill.id} title={skill.name}>
              <b>{text.equippedSkillBadge}</b>
              <div>
                <strong>{skill.name}</strong>
                <small>{skill.tags.slice(0, 2).join(" / ") || skill.relation_type}</small>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <small>{text.equippedSkillsEmpty}</small>
      )}
      <div className="skill-equip-row">
        <select value={selectedSkillId} onChange={(event) => setSelectedSkillId(event.target.value)}>
          <option value="">{text.skillSelectPlaceholder}</option>
          {availableSkills.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.name}
            </option>
          ))}
        </select>
        <button className="secondary-button" disabled={busy || !selectedSkill} onClick={() => void equipSelectedSkill()} type="button">
          {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
          {text.skillEquipExisting}
        </button>
      </div>
      {availableSkills.length ? null : <small>{text.skillNoAvailable}</small>}
      <details className="skill-create-details" open={!compact}>
        <summary>{text.skillCreateTitle}</summary>
        <form className="skill-create-form" onSubmit={(event) => void submitCreatedSkill(event)}>
          <label>
            <span>{text.skillName}</span>
            <input
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder={text.skillName}
            />
          </label>
          <label>
            <span>{text.skillDescription}</span>
            <input
              value={draft.description}
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              placeholder={text.skillDescription}
            />
          </label>
          <label>
            <span>{text.skillInstructions}</span>
            <textarea
              value={draft.instructions}
              onChange={(event) => setDraft((current) => ({ ...current, instructions: event.target.value }))}
              placeholder={text.skillInstructions}
              rows={compact ? 3 : 5}
            />
          </label>
          <label>
            <span>{text.skillTags}</span>
            <input
              value={draft.tags}
              onChange={(event) => setDraft((current) => ({ ...current, tags: event.target.value }))}
              placeholder="eda, credit-risk, reporting"
            />
          </label>
          <button className="primary-button" disabled={busy || !canCreateSkill} type="submit">
            {busy ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
            {text.skillCreateAndEquip}
          </button>
        </form>
      </details>
    </section>
  );
}

function MissionSurfaceButton({
  icon,
  label,
  detail,
  onClick
}: {
  icon: React.ReactNode;
  label: string;
  detail: string;
  onClick: () => void;
}) {
  return (
    <button className="mission-surface-button" onClick={onClick} type="button">
      <span>{icon}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </button>
  );
}

function buildResearchPlanBlocks({
  researchPlanTimeline,
  notebookIndex,
  poweredOn,
  text,
  locale,
  turnState,
  onNavigateToTarget,
  onOpenArtifact
}: {
  project: Project;
  datasetCount: number;
  artifacts: Artifact[];
  researchBriefs: ResearchBrief[];
  researchPlanTimeline: ResearchPlanTimelineResponse | null;
  notebookIndex: NotebookIndex | null;
  equippedSkills: EquippedSkillItem[];
  jobs: Job[];
  poweredOn: boolean;
  text: LocaleMessages;
  locale: string;
  turnState: TurnState;
  onTabChange: (tab: Tab) => void;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
  onOpenArtifact: (artifactId: string, targetTab: Tab, targetAnchor?: string | null) => void;
}): ResearchPlanBlock[] {
  const codexAuthoredBlocks = researchPlanBlocksFromTimeline(
    researchPlanTimeline,
    text,
    locale,
    onNavigateToTarget,
    onOpenArtifact,
    notebookIndex
  );
  const blocksWithCurrentWork = applyResearchPlanCurrentWork(
    codexAuthoredBlocks,
    researchPlanTimeline?.current_work ?? null,
    poweredOn,
    turnState
  );
  return renumberResearchPlanBlocks(blocksWithCurrentWork);
}

function applyResearchPlanCurrentWork(
  blocks: ResearchPlanBlock[],
  currentWork: ResearchPlanCurrentWork | null,
  poweredOn: boolean,
  turnState: TurnState
): ResearchPlanBlock[] {
  void poweredOn;
  if (!currentWork?.node_id) return blocks;
  if (currentWork.source === "research_plan_revision_status" && turnState.state === "agent_running") return blocks;
  let matched = false;
  const nextBlocks = blocks.map((block) => {
    if (block.id !== currentWork.node_id) return block;
    matched = true;
    return {
      ...block,
      isCurrentWork: true
    };
  });
  if (matched) return nextBlocks;
  return nextBlocks;
}

function renumberResearchPlanBlocks(blocks: ResearchPlanBlock[]): ResearchPlanBlock[] {
  return blocks.map((block, index) => ({ ...block, eyebrow: `${index + 1}`.padStart(2, "0") }));
}

function researchPlanBlocksFromTimeline(
  timeline: ResearchPlanTimelineResponse | null,
  text: LocaleMessages,
  locale: string,
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void,
  onOpenArtifact: (artifactId: string, targetTab: Tab, targetAnchor?: string | null) => void,
  notebookIndex: NotebookIndex | null
): ResearchPlanBlock[] {
  if (!timeline?.blocks.length) return [];
  const displayLocale = timeline.response_locale ?? timeline.requested_locale ?? timeline.authored_locale ?? locale;
  const blocks = timeline.blocks.map((block, index) => {
    const targetTab = block.target_tab ? tabFromString(block.target_tab, "Home") : null;
    const subtasks: ResearchPlanSubtask[] = block.subtasks.map((subtask) => {
      const subtaskTab = subtask.target_tab ? tabFromString(subtask.target_tab, targetTab ?? "Home") : targetTab;
      return {
        id: subtask.id,
        title: displayTextOrFallback(subtask.title, displayLocale, text.researchPlanDetailEvidence),
        detail: displayTextOrFallback(subtask.detail, displayLocale, ""),
        status: subtask.status,
        evidence: subtask.evidence,
        targetTab: subtaskTab,
        targetAnchor: subtask.target_anchor,
        onClick: subtaskTab ? () => onNavigateToTarget(subtaskTab, subtask.target_anchor) : undefined
      };
    });
    const evidenceLinks = researchPlanEvidenceLinks(block, text, displayLocale, onNavigateToTarget, onOpenArtifact, notebookIndex);
    return {
      id: block.id,
      title: displayTextOrFallback(block.title, displayLocale, text.researchPlanSummaryBlock),
      subtitle: displayTextOrFallback(block.subtitle, displayLocale, ""),
      status: block.status,
      eyebrow: `${index + 1}`.padStart(2, "0"),
      evidence: block.evidence,
      subtasks,
      evidenceLinks,
      onClick: targetTab ? () => onNavigateToTarget(targetTab, block.target_anchor) : undefined
    };
  });
  return blocks;
}

function researchPlanEvidenceLinks(
  block: ResearchPlanTimelineBlock,
  text: LocaleMessages,
  locale: string,
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void,
  onOpenArtifact: (artifactId: string, targetTab: Tab, targetAnchor?: string | null) => void,
  notebookIndex: NotebookIndex | null
): ResearchPlanEvidenceLinkItem[] {
  const links: ResearchPlanEvidenceLinkItem[] = [];
  const attachedArtifacts = block.attached_artifacts ?? [];
  if (attachedArtifacts.length) {
    for (const [index, artifact] of attachedArtifacts.slice(0, 8).entries()) {
      const action = researchPlanArtifactLinkAction(artifact, notebookIndex, onNavigateToTarget, onOpenArtifact);
      links.push({
        id: `${block.id}:attached_artifact:${artifact.id || artifact.artifact_id || artifact.run_id || index}`,
        artifactId: artifact.artifact_id ?? null,
        outputKind: researchPlanArtifactLinkKind(artifact),
        title: researchPlanArtifactLinkTitle(artifact, text),
        detail: researchPlanArtifactLinkDetail(artifact),
        evidence: researchPlanArtifactLinkEvidence(artifact),
        targetTab: action.targetTab,
        targetAnchor: action.targetAnchor,
        onClick: action.onClick
      });
    }
    if (attachedArtifacts.length > 8) {
      links.push({
        id: `${block.id}:attached_artifacts_more`,
        title: text.researchPlanDetailEvidence,
        detail: localizedObjectCount(attachedArtifacts.length - 8, "more evidence link", "more evidence links", "追加リンク", locale),
        evidence: `${attachedArtifacts.length}`,
        targetTab: "Assets",
        onClick: () => onNavigateToTarget("Assets")
      });
    }
  }
  return links;
}

function researchPlanArtifactLinkAction(
  link: ResearchPlanArtifactLink,
  notebookIndex: NotebookIndex | null,
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void,
  onOpenArtifact: (artifactId: string, targetTab: Tab, targetAnchor?: string | null) => void
): { targetTab: Tab; targetAnchor: string | null; onClick: () => void } {
  const runLike = researchPlanArtifactLinkIsRun(link);
  const notebookLike = researchPlanArtifactLinkIsNotebook(link);
  const explicitTarget = link.target_tab === "Notebooks" ? "Notebooks" : link.target_tab ? tabFromString(link.target_tab, "Assets") : null;
  const targetTab: Tab = explicitTarget ?? (runLike ? "Leaderboard" : notebookLike ? "Notebooks" : "Assets");
  const targetAnchor = link.target_anchor ?? (runLike ? "result-readout" : notebookLike ? "notebook-native-marimo-top" : null);
  const normalized = normalizeNavigationTarget(targetTab, targetAnchor);
  if (link.artifact_id) {
    const artifactId = notebookLike ? (notebookSourceArtifactIdForResearchPlanLink(link.artifact_id, notebookIndex) ?? link.artifact_id) : link.artifact_id;
    return {
      targetTab: normalized.targetTab,
      targetAnchor: normalized.targetAnchor ?? null,
      onClick: () => onOpenArtifact(artifactId, normalized.targetTab, normalized.targetAnchor ?? null)
    };
  }
  return {
    targetTab: normalized.targetTab,
    targetAnchor: normalized.targetAnchor ?? null,
    onClick: () => onNavigateToTarget(normalized.targetTab, normalized.targetAnchor ?? null)
  };
}

function researchPlanArtifactLinkIsNotebook(link: ResearchPlanArtifactLink) {
  const assetType = (link.asset_type ?? "").toLowerCase();
  const role = (link.role ?? "").toLowerCase();
  return assetType.includes("notebook") || role.includes("notebook");
}

function researchPlanArtifactLinkIsRun(link: ResearchPlanArtifactLink) {
  return link.link_type === "experiment_run" || Boolean(link.run_id) || link.asset_type === "experiment_run";
}

function researchPlanArtifactLinkKind(link: ResearchPlanArtifactLink): ResearchPlanEvidenceLinkItem["outputKind"] {
  const assetType = (link.asset_type ?? "").toLowerCase();
  if (researchPlanArtifactLinkIsNotebook(link)) return "notebook";
  if (researchPlanArtifactLinkIsRun(link)) return "run";
  const category = assetCategoryForAssetType(assetType);
  if (category === "model_prediction") return "pipeline";
  if (category === "research") return "research";
  if (category === "reports") return "report";
  return "artifact";
}

function researchPlanArtifactLinkTitle(link: ResearchPlanArtifactLink, text: LocaleMessages) {
  if (researchPlanArtifactLinkIsNotebook(link)) return text.relatedNotebooks;
  if (researchPlanArtifactLinkIsRun(link)) return text.metricRuns;
  if ((link.role ?? "").toLowerCase().includes("report")) return text.tabReports;
  return text.tabAssets;
}

function researchPlanArtifactLinkDetail(link: ResearchPlanArtifactLink) {
  return link.artifact_name || link.run_id || link.artifact_id || link.id;
}

function researchPlanArtifactLinkEvidence(link: ResearchPlanArtifactLink) {
  return link.asset_type?.replace(/_/g, " ") ?? link.role ?? link.link_type ?? null;
}

function notebookSourceArtifactIdForResearchPlanLink(artifactId: string, notebookIndex: NotebookIndex | null) {
  const item = preferredNotebookForArtifact(notebookIndex, artifactId);
  return item ? item.source_artifact_id ?? item.artifact_ids.source ?? item.artifact_ids.notebook : null;
}

function notebookItemReferencesArtifact(item: NotebookIndexItem, artifactId: string) {
  if (
    item.notebook_artifact_id === artifactId ||
    item.source_artifact_id === artifactId ||
    item.artifact_ids.source === artifactId ||
    item.preview_artifact_id === artifactId
  ) {
    return true;
  }
  return artifactIdInUnknown(item.artifact_ids, artifactId);
}

function artifactIdInUnknown(value: unknown, artifactId: string): boolean {
  if (typeof value === "string") return value === artifactId;
  if (Array.isArray(value)) return value.some((item) => artifactIdInUnknown(item, artifactId));
  if (value && typeof value === "object") return Object.values(value).some((item) => artifactIdInUnknown(item, artifactId));
  return false;
}

function agentSessionHasObservedCodexProcess(session: AgentSession | null): boolean {
  if (!session) return false;
  if (session.observed_runner_state === "running") return true;
  if (session.pid_is_observed_codex_process === true) return true;
  return (session.observed_codex_process_count ?? 0) > 0;
}

function fallbackNavigationAnchor(anchor: string) {
  if (anchor === "notebook-preview-top") {
    return document.getElementById(NOTEBOOK_NATIVE_MARIMO_ANCHOR) ?? document.getElementById("notebook-focus");
  }
  if (anchor === NOTEBOOK_NATIVE_MARIMO_ANCHOR) return document.getElementById("notebook-focus");
  return null;
}

function focusNavigationAnchor(anchor: string, delayMs = 90, attempts = 8) {
  window.setTimeout(() => {
    let element = document.getElementById(anchor);
    if (!element && attempts > 0) {
      focusNavigationAnchor(anchor, 120, attempts - 1);
      return;
    }
    element = element ?? fallbackNavigationAnchor(anchor);
    if (!element) return;
    const top = Math.max(0, element.getBoundingClientRect().top + window.scrollY - 8);
    window.scrollTo({ top, behavior: "smooth" });
    element.classList.add("navigation-highlight");
    window.setTimeout(() => element.classList.remove("navigation-highlight"), 1400);
  }, delayMs);
}

function latestArtifactByType(artifacts: Artifact[], assetType: string) {
  return artifacts
    .filter((artifact) => artifact.asset_type === assetType)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())[0] ?? null;
}

function conciseMemoryText(value: string | null | undefined, fallback: string, maxLength = 170) {
  const normalized = (value ?? "").replace(/\s+/g, " ").trim();
  const text = normalized || fallback;
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1).trim()}...`;
}

function memoryDisplayText(value: string | null | undefined, locale: string, fallback: string, maxLength = 170) {
  const normalized = (value ?? "").replace(/\s+/g, " ").trim();
  void locale;
  if (hasNonEmptyDisplayText(normalized)) return conciseMemoryText(normalized, fallback, maxLength);
  return fallback;
}

function memoryAnchor(prefix: "idea" | "finding", id: string) {
  return `${prefix}-${id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function confidenceLabel(value: number | null | undefined, text: LocaleMessages, locale: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) return text.memoryConfidenceUnavailable;
  const percentage = `${Math.round(value * 100)}%`;
  if (localeLooksJapanese(locale)) return `${text.memoryConfidenceSuffix}${percentage}`;
  return `${percentage} ${text.memoryConfidenceSuffix}`;
}

function insightDeepDiveAnchor(insight: Insight) {
  const assetTypes = insight.source_asset_ids.map((source) => source.asset_type.toLowerCase());
  if (assetTypes.some((assetType) => assetType.includes("notebook"))) return "notebook-focus";
  if (assetTypes.some((assetType) => assetType.includes("report"))) return "reports";
  return memoryAnchor("finding", insight.id);
}

function buildIdeaFindingItems(ideas: Idea[], insights: Insight[], artifacts: Artifact[], text: LocaleMessages, locale: string): HomeMemoryItem[] {
  const researchArtifacts = artifacts
    .filter((artifact) => artifact.asset_type === "research_findings_report")
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())
    .slice(0, 8);
  const items: HomeMemoryItem[] = [
    ...ideas.map((idea) => ({
      id: idea.id,
      kind: "idea" as const,
      title: memoryDisplayText(idea.title, locale, text.memoryUntitledSignalTitle, 90),
      summary: memoryDisplayText(
        idea.hypothesis || idea.rationale_md,
        locale,
        text.memoryNoSummary
      ),
      meta: text.memoryKindIdea,
      cta: text.memoryOpenIdea,
      target_tab: "Insight",
      target_anchor: memoryAnchor("idea", idea.id),
      created_at: idea.created_at,
      signal_priority: 82
    })),
    ...insights.map((insight) => ({
      id: insight.id,
      kind: "finding" as const,
      title: memoryDisplayText(insight.title, locale, text.memoryUntitledSignalTitle, 90),
      summary: memoryDisplayText(insight.summary, locale, text.memoryNoSummary),
      meta: `${text.memoryKindFinding} · ${confidenceLabel(insight.confidence, text, locale)}`,
      cta: insightDeepDiveAnchor(insight) === "notebook-focus" ? text.memoryOpenNotebookEvidence : text.memoryOpenFinding,
      target_tab: "Insight",
      target_anchor: insightDeepDiveAnchor(insight),
      created_at: insight.created_at,
      signal_priority: homeInsightSignalPriority(insight)
    })),
    ...researchArtifacts.map((artifact) => ({
      id: artifact.id,
      kind: "finding" as const,
      title: memoryDisplayText(textField(artifact.metadata.topic) ?? artifact.name, locale, text.memoryUntitledSignalTitle, 90),
      summary: researchFindingMemorySummary(artifact, text, locale),
      meta: text.memoryKindResearch,
      cta: text.memoryOpenResearch,
      target_tab: "Assets",
      target_anchor: "assets-artifact-preview",
      artifact_id: textField(artifact.metadata.rich_report_artifact_id) ?? artifact.id,
      created_at: artifact.created_at,
      signal_priority: 78
    }))
  ].sort((left, right) => {
    const priorityDelta = right.signal_priority - left.signal_priority;
    if (priorityDelta !== 0) return priorityDelta;
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
  return items;
}

function researchFindingMemorySummary(artifact: Artifact, text: LocaleMessages, locale: string): string {
  if (artifact.metadata.no_findings === true) return text.memoryResearchNoFindings;
  const sourceCount = numericSummary(artifact.metadata.source_count);
  const findingCount = numericSummary(artifact.metadata.finding_count);
  if (sourceCount || findingCount) {
    if (localeLooksJapanese(locale)) return `${sourceCount} source / ${findingCount} finding`;
    return `${sourceCount} source(s) / ${findingCount} finding(s)`;
  }
  return text.memoryResearchCounts;
}

function homeInsightSignalPriority(insight: Insight): number {
  const type = insight.insight_type.toLowerCase();
  const title = insight.title.toLowerCase();
  if (type.includes("evaluation") || type.includes("assumption") || type.includes("diagnostic")) return 84;
  if (type.includes("run") || type.includes("experiment") || type.includes("model")) return 76;
  if (type.includes("idea") || type.includes("finding")) return 70;
  if (type.includes("approach") || title.includes("approach progress")) return 42;
  if (type.includes("autonomous") || title.includes("full auto loop")) return 24;
  return 60;
}

function equippedSkillItems(references: AssetReference[], assets: LibraryAsset[]): EquippedSkillItem[] {
  const assetById = new Map(assets.map((asset) => [asset.id, asset]));
  return references
    .map((reference) => {
      const asset = reference.asset ?? assetById.get(reference.target_asset_id) ?? null;
      if (!asset || asset.asset_type !== "skill") return null;
      return {
        id: reference.id,
        name: asset.name,
        description: asset.description,
        tags: asset.semantic_tags.length ? asset.semantic_tags : asset.tags,
        relation_type: reference.relation_type
      };
    })
    .filter((item): item is EquippedSkillItem => item !== null);
}

function splitSkillTags(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[,\n]/)
        .map((item) =>
          item
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, "_")
            .replace(/^_+|_+$/g, "")
        )
        .filter(Boolean)
    )
  );
}

function agentChatHistoryToMessages(turns: AgentChatHistoryTurn[]): AgentChatMessage[] {
  return turns.flatMap((turn) => {
    const messages: AgentChatMessage[] = [];
    const turnId = turn.job_id ? `turn:${turn.job_id}` : `turn:${turn.artifact_id}`;
    const composerStatus = String(turn.response_composer?.status ?? "");
    const activeHistoryTurn =
      turn.artifact_id.startsWith("job_pending_") || ["queued", "running", "pending", "in_progress", "waiting_for_agent"].includes(composerStatus);
    if (turn.user_message.trim()) {
      messages.push({
        id: `${turnId}:user`,
        role: "user" as const,
        text: turn.user_message,
        createdAt: turn.created_at
      });
    }
    messages.push({
      id: `${turnId}:system`,
      role: "system" as const,
      text: turn.assistant_message,
      actions: turn.actions,
      actionSummary: agentActionSummaryOrUndefined(turn.action_summary),
      responseBrief: turn.response_brief ?? null,
      responseComposer: turn.response_composer ?? null,
      createdAt: turn.created_at,
      transient: activeHistoryTurn
    });
    return messages;
  });
}

function agentActionSummaryOrUndefined(summary: AgentActionSummary | undefined): AgentActionSummary | undefined {
  return summary?.schema_version ? summary : undefined;
}

function mergeAgentChatMessages(persisted: AgentChatMessage[], current: AgentChatMessage[]) {
  const merged: AgentChatMessage[] = [];
  const seen = new Set<string>();
  const persistedContent = new Set<string>();
  for (const message of persisted) {
    const key = message.id ?? `${message.role}:${message.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    persistedContent.add(`${message.role}:${message.text}`);
    merged.push(message);
  }
  for (const message of current.filter((item) => item.transient)) {
    const key = message.id ?? `${message.role}:${message.text}`;
    if (seen.has(key) || persistedContent.has(`${message.role}:${message.text}`)) continue;
    seen.add(key);
    merged.push(message);
  }
  return merged.slice(-AGENT_CHAT_MESSAGE_HISTORY_LIMIT);
}

function firstAutonomyIntervention(output: Record<string, unknown>): AutonomyIntervention | null {
  const interventions = output.interventions;
  if (!Array.isArray(interventions)) return null;
  for (const item of interventions) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    if (record.schema_version !== "autonomy_intervention.v1") continue;
    const kind = typeof record.kind === "string" ? record.kind : "";
    if (!kind) continue;
    return {
      schema_version: "autonomy_intervention.v1",
      kind,
      mode: typeof record.mode === "string" ? record.mode : undefined,
      continued: typeof record.continued === "boolean" ? record.continued : undefined,
      question_id: typeof record.question_id === "string" ? record.question_id : undefined,
      assumption_id: typeof record.assumption_id === "string" ? record.assumption_id : undefined,
      title: typeof record.title === "string" ? record.title : undefined,
      message: typeof record.message === "string" ? record.message : undefined,
      default_action: typeof record.default_action === "string" ? record.default_action : undefined,
      target_column: typeof record.target_column === "string" ? record.target_column : null,
      dataset_snapshot_id: typeof record.dataset_snapshot_id === "string" ? record.dataset_snapshot_id : null,
      source_ref: typeof record.source_ref === "string" ? record.source_ref : null,
      risk_level: typeof record.risk_level === "string" ? record.risk_level : null,
      confidence: typeof record.confidence === "number" ? record.confidence : null,
      fallback_policy: typeof record.fallback_policy === "string" ? record.fallback_policy : null
    };
  }
  return null;
}

function autonomyInterventionKey(intervention: AutonomyIntervention, jobId: string): string {
  return intervention.question_id ?? intervention.assumption_id ?? `${jobId}:${intervention.kind}`;
}

function upsertAgentChatMessages(
  current: AgentChatMessage[],
  nextMessages: AgentChatMessage[],
  removeIds: Array<string | undefined> = []
) {
  const idsToRemove = new Set(removeIds.filter((id): id is string => Boolean(id)));
  const merged = current.filter((message) => !message.id || !idsToRemove.has(message.id));
  for (const next of nextMessages) {
    const key = next.id ?? `${next.role}:${next.text}`;
    const existingIndex = merged.findIndex((message) => (message.id ?? `${message.role}:${message.text}`) === key);
    if (existingIndex >= 0) {
      merged[existingIndex] = { ...merged[existingIndex], ...next };
    } else {
      merged.push(next);
    }
  }
  return merged.slice(-AGENT_CHAT_MESSAGE_HISTORY_LIMIT);
}

function buildAgentConversationTurns(messages: AgentChatMessage[]): AgentConversationTurn[] {
  const turns: AgentConversationTurn[] = [];
  let pendingUser: AgentChatMessage | undefined;
  messages.forEach((message, index) => {
    if (message.role === "user") {
      if (pendingUser) {
        turns.push({
          id: pendingUser.id ?? `turn-user-${index}-${pendingUser.text.slice(0, 24)}`,
          user: pendingUser,
          createdAt: pendingUser.createdAt
        });
      }
      pendingUser = message;
      return;
    }
    if (pendingUser) {
      turns.push({
        id: message.id ?? pendingUser.id ?? `turn-${index}-${message.text.slice(0, 24)}`,
        user: pendingUser,
        assistant: message,
        createdAt: message.createdAt ?? pendingUser.createdAt
      });
      pendingUser = undefined;
      return;
    }
    turns.push({
      id: message.id ?? `turn-assistant-${index}-${message.text.slice(0, 24)}`,
      assistant: message,
      createdAt: message.createdAt
    });
  });
  if (pendingUser) {
    turns.push({
      id: pendingUser.id ?? `turn-user-final-${pendingUser.text.slice(0, 24)}`,
      user: pendingUser,
      createdAt: pendingUser.createdAt
    });
  }
  return turns;
}

function latestJobHeadline(job: Job) {
  const headline = textField(job.output.headline) ?? textField(job.context.headline) ?? textField(job.input.objective);
  return headline ?? `${job.status.replace(/_/g, " ")} since ${formatDate(job.created_at)}`;
}

function formatMaybeNumber(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(4);
}

function navigatorStatusClass(status: string) {
  if (["ready_to_act", "ready", "low"].includes(status)) return "badge success";
  if (["blocked", "high", "needs_attention"].includes(status)) return "badge risk";
  if (["recover", "medium"].includes(status)) return "badge warning";
  return "badge muted";
}

function displayStatusLabel(status: string, text: LocaleMessages): string {
  const normalized = status.toLowerCase().replace(/\s+/g, "_");
  if (normalized === "high") return text.statusHigh;
  if (normalized === "blocking" || normalized === "blocked") return text.statusBlocking;
  if (normalized === "active" || normalized === "running") return text.statusActive;
  if (normalized === "pending") return text.planStatusPending;
  if (normalized === "waiting" || normalized === "idle") return text.planStatusWaiting;
  if (normalized === "off" || normalized === "stopped") return text.agentPowerOff;
  if (normalized === "skipped" || normalized === "delegated") return text.planStatusSkipped;
  if (normalized === "done" || normalized === "completed") return text.planStatusDone;
  if (normalized === "ready" || normalized === "ready_to_act") return text.statusReady;
  if (normalized === "missing") return text.decisionMetricMissing;
  if (normalized === "low") return text.statusLow;
  if (normalized === "medium" || normalized === "recover") return text.statusMedium;
  if (normalized === "needs_attention") return text.statusNeedsAttention;
  return status.replace(/_/g, " ");
}

function agentChatActionLabel(action: AgentChatAction, text: LocaleMessages) {
  const targetTab = agentChatActionArtifactId(action) && action.target_tab === "Notebooks" ? "Notebooks" : tabFromString(action.target_tab, "Home");
  const verb = ["needs_review", "created", "recorded", "explained"].includes(action.status)
    ? text.chatActionReview
    : text.chatActionOpen;
  const anchorLabel = action.target_anchor ? ` · ${surfaceLabel(action.target_anchor)}` : "";
  return `${verb} ${tabLabel(targetTab, text)}${anchorLabel}`;
}

function agentChatActionKey(action: AgentChatAction, index: number) {
  const identityParts = [
    action.type,
    action.status,
    action.target_tab ?? "",
    action.target_anchor ?? "",
    action.artifact_id ?? "",
    action.asset_type ?? "",
    ...(action.artifact_ids ?? []),
    action.job_id ?? "",
    action.run_id ?? "",
    ...(action.entity_ids ?? []),
    action.label
  ];
  return `${identityParts.join("|")}|${index}`;
}

function agentChatActionArtifactId(action: AgentChatAction, notebookIndex: NotebookIndex | null = null): string | null {
  const artifactIds = [action.artifact_id, ...(action.artifact_ids ?? [])].filter((value): value is string => Boolean(value));
  if (action.target_tab === "Notebooks" && notebookIndex) {
    for (const artifactId of artifactIds) {
      const item = preferredNotebookForArtifact(notebookIndex, artifactId);
      if (item) return item.artifact_ids.notebook;
    }
  }
  return artifactIds[0] ?? null;
}

function agentChatActionRequiresArtifactTarget(action: AgentChatAction, targetTab: Tab): boolean {
  if (targetTab === "Notebooks") return true;
  if (targetTab !== "Assets") return false;
  const anchor = action.target_anchor ?? "";
  return anchor === "assets-artifact-preview" || anchor === "asset-notebooks";
}

function agentChatActionIsPrimaryLink(action: AgentChatAction) {
  const targetTab = tabFromString(action.target_tab, "Home");
  if (["Notebooks", "Leaderboard", "Assets", "Data"].includes(targetTab)) return true;
  if (action.artifact_id || (action.artifact_ids ?? []).length) return true;
  if ((action.entity_ids ?? []).length) return true;
  return false;
}

function visibleAgentChatActions(assistant: AgentChatMessage | undefined): AgentChatAction[] {
  const actions = assistant?.actions ?? [];
  if (!actions.length) return [];
  if (actions.every((action) => action.target_tab === "Notebooks" && agentChatActionArtifactId(action))) {
    return actions.slice(0, 12);
  }
  const hasPrimaryNext = Boolean(assistant?.actionSummary?.next_step?.target_tab);
  if (!hasPrimaryNext) return actions.slice(0, 3);
  return actions.filter(agentChatActionIsPrimaryLink).slice(0, 3);
}

function surfaceLabel(anchor: string) {
  const labels: Record<string, string> = {
    "dataset-upload": "Dataset Upload",
    "data-focus": "Data Evidence",
    "relational-map": "Relational Map",
    "research-plan": "Research Plan",
    "notebook-focus": "Notebook Focus",
    "notebook-center": "Notebook Center",
    "analysis-story": "Analysis Story",
    ideas: "Ideas",
    insights: "Insights",
    reports: "Reports",
    "evaluation-design": "Evaluation Design",
    "approach-handoff": "Runner Handoff",
    "assumption-review": "Review Queue"
  };
  return labels[anchor] ?? anchor.replace(/-/g, " ");
}

function agentChatOutcomeClass(outcome: string | null | undefined) {
  if (outcome === "applied") return "badge success";
  if (outcome === "needs_review") return "badge warning";
  if (outcome === "planned") return "badge muted";
  return "badge";
}

function agentChatOutcomeLabel(outcome: string | null | undefined) {
  const normalized = (outcome ?? "").trim().toLowerCase();
  if (!normalized) return null;
  if (["response", "answered", "persisted", "started", "stopped", "succeeded"].includes(normalized)) return null;
  return normalized.replace(/_/g, " ");
}

function isActiveAgentTurn(turn: AgentConversationTurn): boolean {
  if (!turn.assistant) return Boolean(turn.user?.transient);
  const status = String(turn.assistant.responseComposer?.status ?? "");
  return Boolean(turn.assistant.transient) && ["pending", "running", "queued", "in_progress", "waiting_for_agent"].includes(status);
}

function fallbackTurnState(project: Project): TurnState {
  if (project.current_phase === "AUTONOMOUS_LOOP") {
    return {
      schema_version: "turn_state.v1",
      state: "needs_attention",
      owner: "system",
      label: "Checking agent state",
      detail: "",
      input_attention: false,
      confidence: "fallback"
    };
  }
  return {
    schema_version: "turn_state.v1",
    state: "waiting_for_user",
    owner: "user",
    label: "Waiting for you",
    detail: "",
    input_attention: true,
    confidence: "fallback"
  };
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
  notebookIndex,
  benchmarks,
  jobs,
  busy,
  text,
  locale,
  runAction,
  uploadDraft,
  onProjectChanged,
  onProjectUpdated,
  onObjectiveChanged,
  onOpenNotebookArtifact,
  onStatusMessage
}: {
  project: Project;
  datasets: DatasetSnapshot[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  benchmarks: BenchmarkDataset[];
  jobs: Job[];
  busy: boolean;
  text: LocaleMessages;
  locale: string;
  runAction: (action: () => Promise<unknown>, options?: RunActionOptions) => Promise<void>;
  uploadDraft: DataUploadDraft;
  onProjectChanged: () => Promise<void>;
  onProjectUpdated: (project: Project) => void;
  onObjectiveChanged: () => Promise<void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
  onStatusMessage: (message: string) => void;
}) {
  const [isDraggingData, setIsDraggingData] = React.useState(false);
  const [target, setTarget] = React.useState(project.target_column ?? "");
  const [targetDirty, setTargetDirty] = React.useState(false);
  const [targetSaving, setTargetSaving] = React.useState(false);
  const [targetSavedNotice, setTargetSavedNotice] = React.useState<string | null>(null);
  const [targetSaveError, setTargetSaveError] = React.useState<string | null>(null);
  const [projectColumnCatalog, setProjectColumnCatalog] = React.useState<ProjectColumnCatalog | null>(null);
  const [erHintFile, setErHintFile] = React.useState<File | null>(null);
  const [erHintNote, setErHintNote] = React.useState("");
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
  const queuedFiles = uploadDraft.queuedFiles;
  const selectedPrimaryFileName = uploadDraft.primaryFileName;
  const uploadProgress = uploadDraft.uploadProgress;
  const fileColumnHints = uploadDraft.fileColumnHints;
  const addQueuedUploadFiles = uploadDraft.addFiles;
  const removeQueuedUploadFile = uploadDraft.removeFile;
  const setPrimaryFileName = uploadDraft.setPrimaryFileName;
  const setUploadProgress = uploadDraft.setUploadProgress;
  const queuedTableFiles = queuedFiles.filter(isTableUploadFile);
  const queuedErHintFiles = queuedFiles.filter(isRelationalHintUploadFile);
  const unsupportedQueuedFiles = queuedFiles.filter((item) => !isTableUploadFile(item) && !isRelationalHintUploadFile(item));
  const canUploadDataBundle = queuedFiles.length > 0 && unsupportedQueuedFiles.length === 0;
  const uploadProgressByKey = new Map((uploadProgress?.files ?? []).map((item) => [item.key, item]));
  const currentUploadComplete =
    uploadProgress !== null &&
    !uploadProgress.active &&
    uploadProgress.overall >= 100 &&
    queuedFiles.length > 0 &&
    queuedFiles.every((item) => uploadProgressByKey.get(uploadFileKey(item))?.progress === 100);
  const canSubmitDataBundle = canUploadDataBundle && !currentUploadComplete;
  const dataIntakeJobs = jobs.filter(isDataIntakeJob).slice(0, 3);
  const activeDataIntakeJob = dataIntakeJobs.find((job) => !isTerminalJob(job)) ?? null;
  const activeDataIntakePercent = activeDataIntakeJob ? numberField(activeDataIntakeJob.output.progress_percent) : null;
  const activeDataIntakeStage = activeDataIntakeJob ? textField(activeDataIntakeJob.output.progress_stage) : null;
  const displayDataIntakePercent =
    activeDataIntakePercent === null ? null : Math.max(0, Math.min(100, activeDataIntakePercent));
  const uploadQueueHasUnsupported = unsupportedQueuedFiles.length > 0;
  const uploadQueueIsActive = uploadProgress?.active === true;
  const uploadQueueStatusClass = uploadQueueHasUnsupported
    ? "blocked"
    : uploadQueueIsActive
      ? "active"
      : activeDataIntakeJob
        ? "active"
      : currentUploadComplete
        ? "complete"
        : "ready";
  const uploadQueueTitle = uploadQueueHasUnsupported
    ? text.uploadQueuedFilesBlockedTitle
    : uploadQueueIsActive
      ? text.uploadQueuedFilesUploadingTitle
      : activeDataIntakeJob
        ? text.uploadQueuedFilesServerProcessingTitle
      : currentUploadComplete
        ? text.uploadQueuedFilesCompleteTitle
        : text.uploadQueuedFilesReadyTitle;
  const uploadQueueDetail = uploadQueueHasUnsupported
    ? text.uploadQueuedFilesBlockedDetail
    : uploadQueueIsActive
      ? text.uploadQueuedFilesUploadingDetail
      : activeDataIntakeJob
        ? text.uploadQueuedFilesServerProcessingDetail
      : currentUploadComplete
        ? text.uploadQueuedFilesCompleteDetail
        : text.uploadQueuedFilesReadyDetail;
  const uploadOverallVisible = uploadProgress !== null || activeDataIntakeJob !== null;
  const uploadOverallIsActive = uploadProgress?.active === true || activeDataIntakeJob !== null;
  const uploadOverallPercent =
    activeDataIntakeJob !== null
      ? displayDataIntakePercent ?? 5
      : uploadProgress
        ? uploadProgress.overall
        : 0;
  const uploadOverallLabel =
    activeDataIntakeJob !== null
      ? textField(activeDataIntakeJob.output.assistant_message) ?? text.dataIntakeWorkingFallback
      : uploadProgress?.phase === "server_processing"
        ? text.uploadOverallServerProcessing
        : uploadProgress?.active
          ? text.uploadOverallActive
          : text.uploadOverallComplete;
  const uploadOverallDetail =
    activeDataIntakeJob !== null
      ? [formatWorkflowState(activeDataIntakeJob.status), activeDataIntakeStage].filter(Boolean).join(" · ")
      : uploadProgress
        ? `${formatBytes(uploadProgress.loadedBytes)} / ${formatBytes(uploadProgress.totalBytes)}`
        : "";
  const latestDataset = datasets[0] ?? null;
  const latestDatasetId = latestDataset?.id ?? null;
  const primaryDataset = datasets.find((dataset) => dataset.is_primary) ?? null;
  const tableArtifacts = React.useMemo(
    () =>
      artifacts.filter((artifact) => {
        if (!["dataset_snapshot", "uploaded_supporting_table"].includes(artifact.asset_type)) return false;
        const primaryPath = textField(artifact.metadata.primary_path);
        const source = textField(artifact.metadata.source_filename) ?? primaryPath ?? "";
        return [".csv", ".parquet"].some((suffix) => source.toLowerCase().endsWith(suffix));
      }),
    [artifacts]
  );
  const [selectedExistingPrimaryArtifactId, setSelectedExistingPrimaryArtifactId] = React.useState("");
  const selectedExistingPrimaryChanged =
    Boolean(selectedExistingPrimaryArtifactId) && selectedExistingPrimaryArtifactId !== (primaryDataset?.artifact_id ?? "");
  const dataIntakeColumnRefreshKey = dataIntakeJobs
    .map((job) => `${job.id}:${job.status}:${job.updated_at ?? job.created_at}`)
    .join("|");
  const dataIntakeBusy = uploadQueueIsActive || dataIntakeJobs.some((job) => !isTerminalJob(job));
  const datasetCatalogRefreshKey = React.useMemo(
    () => datasets.map((dataset) => `${dataset.id}:${dataset.schema_hash}:${dataset.is_primary ? "1" : "0"}`).join("|"),
    [datasets]
  );
  const queuedAvailableColumnItems = React.useMemo(
    () =>
      [...queuedTableFiles]
        .sort((left, right) => {
          const leftPrimary = left.name === selectedPrimaryFileName;
          const rightPrimary = right.name === selectedPrimaryFileName;
          if (leftPrimary !== rightPrimary) return leftPrimary ? -1 : 1;
          return left.name.localeCompare(right.name);
        })
        .flatMap((file) =>
          (fileColumnHints[file.name] ?? []).map((column) => ({
            key: `queued:${file.name}:${column}`,
            value: column,
            source: file.name,
            isPrimary: file.name === selectedPrimaryFileName,
            sourceKind: "queued" as const,
            physicalType: null as string | null,
            rowCount: null as number | null,
            columnCount: fileColumnHints[file.name]?.length ?? null
          }))
        ),
    [fileColumnHints, queuedTableFiles, selectedPrimaryFileName]
  );
  const availableColumnItems = React.useMemo(
    () => [
      ...queuedAvailableColumnItems,
      ...(projectColumnCatalog?.tables ?? []).flatMap((table) =>
        (table.column_details?.length ? table.column_details : table.columns.map((name) => ({ name }))).map((rawColumn) => {
          const column = rawColumn as {
            name: string;
            physical_type?: string;
          };
          return {
            key: `dataset:${table.dataset_snapshot_id}:${column.name}`,
            value: column.name,
            source: table.source_ref ?? table.dataset_snapshot_id,
            isPrimary: table.is_primary,
            sourceKind: "catalog" as const,
            physicalType: column.physical_type ?? null,
            rowCount: table.row_count,
            columnCount: table.column_count
          };
        })
      )
    ],
    [projectColumnCatalog?.tables, queuedAvailableColumnItems]
  );
  const targetDraft = target.trim();
  const persistedTarget = (project.target_column ?? "").trim();
  const targetChanged = targetDraft !== persistedTarget;
  const targetHasSaveAction = Boolean(targetDraft) || Boolean(persistedTarget);
  const canSetTarget = targetHasSaveAction && (targetChanged || targetDirty) && !targetSaving;
  const availableColumnValues = React.useMemo(
    () =>
      uniqueStrings(availableColumnItems.map((item) => item.value))
        .filter((value) => !isGeneratedCsvPlaceholderColumnName(value))
        .slice(0, 96),
    [availableColumnItems]
  );
  const relatedDataNotebooks = React.useMemo(
    () =>
      latestDatasetId
        ? notebooksForDataset(notebookIndex, latestDatasetId)
            .sort(compareDataSurfaceNotebooks)
            .slice(0, 5)
        : [],
    [latestDatasetId, notebookIndex]
  );

  React.useEffect(() => {
    if (targetDirty) return;
    setTarget(project.target_column ?? "");
  }, [project.target_column, targetDirty]);

  React.useEffect(() => {
    let active = true;
    api<ProjectColumnCatalog>(`/api/projects/${project.id}/data/columns`)
      .then((catalog) => {
        if (active) setProjectColumnCatalog(catalog);
      })
      .catch(() => {
        if (active) setProjectColumnCatalog(null);
      });
    return () => {
      active = false;
    };
  }, [project.id, datasetCatalogRefreshKey, dataIntakeColumnRefreshKey]);

  React.useEffect(() => {
    setSelectedExistingPrimaryArtifactId((current) => {
      if (current && tableArtifacts.some((artifact) => artifact.id === current)) return current;
      return primaryDataset?.artifact_id ?? "";
    });
  }, [primaryDataset?.artifact_id, tableArtifacts]);

  async function setProjectTarget(nextTarget: string | null) {
    const normalized = nextTarget?.trim() || null;
    setTargetSaving(true);
    setTargetSaveError(null);
    try {
      const updated = await api<Project>(`/api/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_column: normalized })
      });
      onProjectUpdated(updated);
      setTarget(updated.target_column ?? "");
      setTargetDirty(false);
      setTargetSavedNotice(text.targetSaved);
      onStatusMessage(
        normalized
          ? `${text.targetSaved}: ${normalized}`
          : text.clearTarget
      );
      void onObjectiveChanged();
      window.setTimeout(() => setTargetSavedNotice(null), 2400);
    } catch (err) {
      setTargetSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setTargetSaving(false);
    }
  }

  async function setProjectPrimaryTable(artifactId: string) {
    if (!artifactId) return;
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/datasets/primary/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_id: artifactId, locale })
      });
      onStatusMessage(textField(job.output.assistant_message) ?? text.primaryTableSaved);
      return job;
    }, { refreshMode: "data-intake" });
  }

  async function uploadDataBundle() {
    if (!canUploadDataBundle) return;
    const uploadFiles = [...queuedFiles];
    const uploadTotalBytes = uploadFiles.reduce((total, item) => total + item.size, 0);
    setUploadProgress(buildUploadProgress(uploadFiles, 0, uploadTotalBytes, true, "transferring"));
    const body = new FormData();
    uploadFiles.forEach((queuedFile) => body.append("files", queuedFile));
    if (target.trim()) body.append("target_column", target.trim());
    if (selectedPrimaryFileName) body.append("primary_filename", selectedPrimaryFileName);
    if (erHintNote.trim()) body.append("note", erHintNote.trim());
    body.append("locale", locale);
    let uploaded = false;
    await runAction(async () => {
      const job = await uploadFormData<Job>(
        `/api/projects/${project.id}/datasets/upload-bundle`,
        body,
        (event) => {
          const requestTotal = event.lengthComputable && event.total > 0 ? event.total : uploadTotalBytes;
          const estimatedFileBytes =
            requestTotal > 0 ? Math.min(uploadTotalBytes, (event.loaded / requestTotal) * uploadTotalBytes) : 0;
          setUploadProgress(buildUploadProgress(uploadFiles, estimatedFileBytes, uploadTotalBytes, true, "transferring"));
        },
        () => {
          setUploadProgress(buildUploadProgress(uploadFiles, uploadTotalBytes, uploadTotalBytes, true, "server_processing"));
        }
      );
      const hintArtifactIds = Array.isArray(job.output.relational_hint_artifact_ids)
        ? job.output.relational_hint_artifact_ids
        : [];
      const relationalArtifactId =
        textField(job.output.relational_catalog_artifact_id) ?? textField(hintArtifactIds[0]);
      uploaded = true;
      setUploadProgress(buildUploadProgress(uploadFiles, uploadTotalBytes, uploadTotalBytes, false, "complete"));
      if (relationalArtifactId) {
        await loadRelationalPreview(relationalArtifactId);
      }
      onStatusMessage(text.uploadCompleteChatMessage);
      return job;
    }, { refreshMode: "data-intake" });
    if (uploaded) {
      setErHintNote("");
    } else {
      setUploadProgress((current) => (current ? { ...current, active: false } : current));
    }
  }

  async function uploadRelationalSchemaHint() {
    if (!erHintFile) return;
    const body = new FormData();
    body.append("file", erHintFile);
    if (erHintNote.trim()) body.append("note", erHintNote.trim());
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/relational/schema-hints/upload`, {
        method: "POST",
        body
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Relational schema hint job" });
      const artifactId = textField(completedJob.output.relational_schema_hint_artifact_id);
      if (artifactId) {
        await loadRelationalPreview(artifactId);
      }
      return completedJob;
    });
    setErHintFile(null);
    setErHintNote("");
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
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 5 * 60_000, label: "Kaggle probe job" });
      setKaggleProbeResults((current) => ({ ...current, [benchmark.id]: completedJob.output }));
      return completedJob;
    });
  }

  async function fetchKaggleInventory(benchmark: BenchmarkDataset) {
    await runAction(async () => {
      const job = await api<Job>(`/api/benchmarks/${benchmark.id}/kaggle/inventory`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Kaggle inventory job" });
      setKaggleInventoryResults((current) => ({ ...current, [benchmark.id]: completedJob.output }));
      return completedJob;
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
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 60 * 60_000, label: "Kaggle download job" });
      setKaggleDownloadResults((current) => ({ ...current, [benchmark.id]: completedJob.output }));
      return completedJob;
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
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Benchmark scenario pack job" });
      const reportArtifactId = completedJob.output.benchmark_scenario_report_artifact_id;
      if (typeof reportArtifactId === "string") {
        await loadScenarioPreview(reportArtifactId);
      }
      return completedJob;
    });
  }

  async function createBenchmarkEvidencePack() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/benchmarks/evidence-pack`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Benchmark evidence pack job" });
      const reportArtifactId = textField(completedJob.output.benchmark_evidence_report_artifact_id);
      if (reportArtifactId) {
        await loadEvidencePreview(reportArtifactId);
      }
      return completedJob;
    });
  }

  async function createRelationalFeaturePlan() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-plan`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Relational feature plan job" });
      const reportArtifactId = textField(completedJob.output.relational_feature_report_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      }
      return completedJob;
    });
  }

  async function createRelationalFeatureRecipe() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-recipe/build`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 15 * 60_000, label: "Relational feature recipe job" });
      const reportArtifactId = textField(completedJob.output.relational_feature_recipe_report_artifact_id);
      const previewArtifactId = textField(completedJob.output.relational_feature_preview_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      } else if (previewArtifactId) {
        await loadRelationalPreview(previewArtifactId);
      }
      return completedJob;
    });
  }

  async function diagnoseRelationalFeatureScenarios() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/features/relational-scenarios/diagnose`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 15 * 60_000, label: "Relational feature scenario diagnostics job" });
      const reportArtifactId = textField(completedJob.output.relational_feature_scenario_report_artifact_id);
      const diagnosticsArtifactId = textField(completedJob.output.relational_feature_scenario_diagnostics_artifact_id);
      if (reportArtifactId) {
        await loadRelationalPreview(reportArtifactId);
      } else if (diagnosticsArtifactId) {
        await loadRelationalPreview(diagnosticsArtifactId);
      }
      return completedJob;
    });
  }

  async function createBenchmarkCollectionPlan() {
    await runAction(async () => {
      const job = await api<Job>(`/api/projects/${project.id}/benchmarks/collection-plan`, {
        method: "POST"
      });
      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Benchmark collection plan job" });
      const reportArtifactId = textField(completedJob.output.benchmark_collection_report_artifact_id);
      if (reportArtifactId) {
        await loadCollectionPreview(reportArtifactId);
      }
      return completedJob;
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
  const relationalHintArtifacts = artifacts.filter((artifact) =>
    ["relational_schema_hint", "relational_schema_hint_report"].includes(artifact.asset_type)
  );
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
  const latestProfileArtifact = profileArtifacts[0] ?? null;
  const latestQualityReportArtifact = qualityArtifacts.find((artifact) => artifact.asset_type === "data_quality_report") ?? null;
  const latestQualityGateArtifact = qualityArtifacts.find((artifact) => artifact.asset_type === "data_quality_gate") ?? null;
  const latestQualityArtifact = latestQualityReportArtifact ?? latestQualityGateArtifact;
  const dataEvidenceArtifact = latestQualityReportArtifact ?? latestQualityGateArtifact ?? latestProfileArtifact;
  const latestRelationalCatalog = relationalArtifacts[0] ?? null;
  const latestRelationalHint = relationalHintArtifacts.find((artifact) => artifact.asset_type === "relational_schema_hint") ?? null;
  const dataFocusRelationalArtifactId = latestRelationalCatalog?.id ?? latestRelationalHint?.id ?? null;
  const dataFocusNextAction = !latestDataset
    ? "Upload or import data"
    : !latestProfileArtifact
      ? "Run profiling from upload/import"
      : !latestQualityArtifact
        ? "Analyze quality"
        : dataFocusRelationalArtifactId
          ? "Review ER evidence"
          : "Review quality evidence";
  const dataFocusButtonLabel = !latestDataset
    ? "Upload Data"
    : !latestQualityArtifact
      ? "Check Quality"
      : dataFocusRelationalArtifactId
        ? "Open ER Map"
        : "Review Details";
  const dataFocusButtonDisabled = !latestDataset || busy;
  const dataEvidenceStatus = latestQualityArtifact
    ? String(latestQualityArtifact.metadata.severity ?? "quality recorded").replace(/_/g, " ")
    : latestProfileArtifact
      ? "profile ready"
      : latestDataset
        ? "needs quality"
        : "needs data";
  const dataEvidenceTone: EvidenceReaderMetric["tone"] = latestQualityArtifact
    ? String(latestQualityArtifact.metadata.severity ?? "").toLowerCase().includes("high") ||
      String(latestQualityArtifact.metadata.severity ?? "").toLowerCase().includes("block")
      ? "risk"
      : "ready"
    : latestDataset
      ? "warning"
      : "risk";
  const dataEvidenceTitle = latestQualityReportArtifact
    ? "Read the latest quality review before modeling"
    : latestQualityGateArtifact
      ? "Quality gates are recorded; review the risk evidence"
      : latestDataset
        ? "Profile exists; quality evidence is the next useful read"
        : "Start with a dataset, then let evidence guide the next move";
  const dataEvidenceBody = latestDataset
    ? "The first useful decision is whether this data is trustworthy enough for evaluation and runner work. Tablex keeps row counts, profile scope, objective status, quality risks, and relational evidence visible before any modeling claim."
    : "A project can exist before objective definition. Upload CSV/Parquet or import a benchmark first, then let Codex review possible task shapes, assumptions, and evaluation choices.";
  const dataEvidenceNextDetail = !latestDataset
    ? "Create a DatasetSnapshot. Objective definition can wait until the data has been inspected."
    : !latestQualityArtifact
      ? "Run the quality gate so leakage, missingness, duplicates, identity columns, and evaluation blockers become explicit evidence."
      : "Read the quality evidence first. Then inspect relational evidence only if the row meaning depends on tables or joins.";
  const dataEvidencePreviewTitle = latestQualityReportArtifact
    ? "Latest quality report"
    : latestQualityGateArtifact
      ? "Latest quality gate"
      : latestProfileArtifact
        ? "Latest profile artifact"
        : "No data evidence yet";
  const autoLoadedDataEvidenceRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    const preferredArtifact = latestRelationalCatalog ?? latestRelationalHint;
    if (!preferredArtifact) return;
    if (relationalPreview?.id === preferredArtifact.id) return;
    if (autoLoadedRelationalCatalogRef.current === preferredArtifact.id) return;
    autoLoadedRelationalCatalogRef.current = preferredArtifact.id;
    setRelationalPreviewLoadingId(preferredArtifact.id);
    setRelationalPreviewError(null);
    api<ArtifactPreview>(`/api/artifacts/${preferredArtifact.id}/preview`)
      .then((preview) => {
        setRelationalPreview(preview);
      })
      .catch((err: unknown) => {
        setRelationalPreviewError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setRelationalPreviewLoadingId(null);
      });
  }, [latestRelationalCatalog, latestRelationalHint, relationalPreview?.id]);

  React.useEffect(() => {
    if (!dataEvidenceArtifact) return;
    if (qualityPreview?.id === dataEvidenceArtifact.id) return;
    if (autoLoadedDataEvidenceRef.current === dataEvidenceArtifact.id) return;
    autoLoadedDataEvidenceRef.current = dataEvidenceArtifact.id;
    setQualityPreviewLoadingId(dataEvidenceArtifact.id);
    setQualityPreviewError(null);
    api<ArtifactPreview>(`/api/artifacts/${dataEvidenceArtifact.id}/preview`)
      .then((preview) => {
        setQualityPreview(preview);
      })
      .catch((err: unknown) => {
        setQualityPreviewError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setQualityPreviewLoadingId(null);
      });
  }, [dataEvidenceArtifact, qualityPreview?.id]);

  return (
    <div className="stack">
      <Panel id="dataset-upload" title="Dataset Upload" icon={<Upload size={18} />} className="data-primary-panel">
        <div className="data-intake-layout">
          <label
            className={`data-dropzone ${isDraggingData ? "dragging" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDraggingData(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDraggingData(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDraggingData(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setIsDraggingData(false);
              addQueuedUploadFiles(event.dataTransfer.files);
            }}
          >
            <input
              className="data-dropzone-input"
              type="file"
              multiple
              accept=".csv,.parquet,.png,.jpg,.jpeg,.svg,.pdf,.json,image/png,image/jpeg,image/svg+xml,application/pdf,application/json"
              onChange={(event) => {
                if (event.target.files) addQueuedUploadFiles(event.target.files);
                event.currentTarget.value = "";
              }}
            />
            <span className="data-dropzone-icon">
              <Upload size={26} />
            </span>
            <strong>Drop tables and ER evidence here</strong>
            <p>CSV or Parquet for one or many tables. Add PNG, SVG, PDF, or JSON ER hints in the same drop.</p>
            <small>
              {queuedFiles.length
                ? `${queuedTableFiles.length} table file(s), ${queuedErHintFiles.length} ER hint(s) queued`
                : "Target column can stay blank until Data Understanding."}
            </small>
          </label>
          <div className="data-intake-controls">
            <div className="field-stack target-field-stack">
              <label>{text.targetColumnLabel}</label>
              <div className="target-input-row">
                <input
                  list="objective-column-options"
                  value={target}
                  onChange={(event) => {
                    setTarget(event.target.value);
                    setTargetDirty(true);
                    setTargetSavedNotice(null);
                    setTargetSaveError(null);
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
                    event.preventDefault();
                    if (canSetTarget) void setProjectTarget(targetDraft);
                  }}
                  placeholder={text.targetPlaceholder}
                />
                <button className="primary-button" disabled={!canSetTarget} onClick={() => void setProjectTarget(targetDraft)} type="button">
                  {targetSaving ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                  {targetDraft ? text.setTarget : text.clearTarget}
                </button>
              </div>
              <datalist id="objective-column-options">
                {availableColumnValues.map((column) => (
                  <option key={column} value={column} />
                ))}
              </datalist>
              {targetSavedNotice ? <small className="field-success">{targetSavedNotice}</small> : null}
              {targetSaveError ? <small className="field-warning">{targetSaveError}</small> : null}
              <small className="field-hint">{text.targetCanWait}</small>
            </div>
            <div className="field-stack">
              <label>{text.primaryTableLabel}</label>
              <select
                value={selectedPrimaryFileName}
                disabled={!queuedTableFiles.length}
                onChange={(event) => setPrimaryFileName(event.target.value)}
              >
                {queuedTableFiles.length ? (
                  <>
                    <option value="">{text.primaryTableUndecided}</option>
                    {queuedTableFiles.map((queuedFile) => (
                      <option key={uploadFileKey(queuedFile)} value={queuedFile.name}>
                        {queuedFile.name}
                      </option>
                    ))}
                  </>
                ) : (
                  <option value="">Add a CSV or Parquet file</option>
                )}
              </select>
              <small>{text.primaryTableHelp}</small>
            </div>
            <div className="field-stack existing-primary-table">
              <label>{text.currentPrimaryTableLabel}</label>
              {tableArtifacts.length ? (
                <div className="target-input-row">
                  <select
                    value={selectedExistingPrimaryArtifactId}
                    disabled={dataIntakeBusy}
                    onChange={(event) => setSelectedExistingPrimaryArtifactId(event.target.value)}
                  >
                    <option value="">{text.primaryTableUndecided}</option>
                    {tableArtifacts.map((artifact) => {
                      const sourceName =
                        textField(artifact.metadata.source_filename) ??
                        textField(artifact.metadata.table_name) ??
                        artifact.name;
                      const matchingDataset = datasets.find((dataset) => dataset.artifact_id === artifact.id);
                      return (
                        <option key={artifact.id} value={artifact.id}>
                          {sourceName}
                          {matchingDataset?.is_primary ? ` · ${text.primaryTableCurrentBadge}` : ""}
                        </option>
                      );
                    })}
                  </select>
                  <button
                    className="primary-button"
                    disabled={dataIntakeBusy || !selectedExistingPrimaryChanged}
                    onClick={() => void setProjectPrimaryTable(selectedExistingPrimaryArtifactId)}
                    type="button"
                  >
                    <Check size={16} />
                    {text.savePrimaryTable}
                  </button>
                </div>
              ) : (
                <small>{text.noUploadedTables}</small>
              )}
              <small>{text.currentPrimaryTableHelp}</small>
            </div>
            {dataIntakeJobs.length ? (
              <DataIntakeStatusCard
                jobs={dataIntakeJobs}
                text={text}
                compact
              />
            ) : null}
            <div className="button-row">
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
            <div className="db-connector-card">
              <Database size={18} />
              <div>
                <strong>Database connectors</strong>
                <p>Connection profiles belong in Tablex. Credentials stay in a vault and are never passed to Codex.</p>
              </div>
              <span className="badge muted">next intake path</span>
            </div>
          </div>
        </div>
        {queuedFiles.length ? (
          <div className="queued-file-list">
            <div className={`queued-upload-callout ${uploadQueueStatusClass}`}>
              <div>
                <strong>{uploadQueueTitle}</strong>
                <small>{uploadQueueDetail}</small>
              </div>
              <button className="primary-button" disabled={!canSubmitDataBundle || dataIntakeBusy} onClick={() => void uploadDataBundle()} type="button">
                {dataIntakeBusy ? (
                  <Loader2 className="spin" size={16} />
                ) : currentUploadComplete ? (
                  <Check size={16} />
                ) : (
                  <Upload size={16} />
                )}
                {currentUploadComplete ? text.uploadQueuedFilesCompleteTitle : text.uploadSelectedFiles}
              </button>
            </div>
            {queuedTableFiles.length ? (
              <div className="queued-table-picker">
                <span>{text.queuedTablesTitle}</span>
                <div>
                  {queuedTableFiles.map((queuedFile) => (
                    <button
                      className={`queued-table-chip ${selectedPrimaryFileName === queuedFile.name ? "active" : ""}`}
                      key={uploadFileKey(queuedFile)}
                      onClick={() => setPrimaryFileName(queuedFile.name)}
                      type="button"
                    >
                      <Database size={14} />
                      <strong>{queuedFile.name}</strong>
                      <small>
                        {fileColumnHints[queuedFile.name]?.length
                          ? text.queuedColumnsCount.replace("{count}", String(fileColumnHints[queuedFile.name].length))
                          : formatBytes(queuedFile.size)}
                      </small>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            {uploadOverallVisible ? (
              <div className={`queued-file-overall ${uploadOverallIsActive ? "active" : "complete"}`}>
                <div>
                  <span>{uploadOverallLabel}</span>
                  <strong>{Math.round(uploadOverallPercent)}%</strong>
                  {uploadOverallDetail ? <small>{uploadOverallDetail}</small> : null}
                </div>
                <div className="progress-track" aria-label="Overall upload progress">
                  <div style={{ width: `${uploadOverallPercent}%` }} />
                </div>
              </div>
            ) : null}
            {queuedFiles.map((queuedFile) => {
              const kind = isTableUploadFile(queuedFile)
                ? "table"
                : isRelationalHintUploadFile(queuedFile)
                  ? "ER hint"
                  : "unsupported";
              const progress = uploadProgressByKey.get(uploadFileKey(queuedFile));
              const uploadState = uploadFileState(progress, uploadProgress);
              const percent = progress?.progress ?? 0;
              return (
                <div className={`queued-file-item ${kind === "unsupported" ? "unsupported" : ""} ${uploadState}`} key={uploadFileKey(queuedFile)}>
                  <span>{kind}</span>
                  <div className="queued-file-name">
                    <strong>{queuedFile.name}</strong>
                    <small>
                      {formatBytes(queuedFile.size)} · {uploadState}
                    </small>
                  </div>
                  <div className="queued-file-progress">
                    <div className="progress-track compact" aria-label={`${queuedFile.name} upload progress`}>
                      <div style={{ width: `${percent}%` }} />
                    </div>
                    <b>{Math.round(percent)}%</b>
                  </div>
                  <button
                    className="icon-button"
                    disabled={uploadProgress?.active}
                    onClick={() => removeQueuedUploadFile(queuedFile)}
                    title={`Remove ${queuedFile.name}`}
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}
        {unsupportedQueuedFiles.length ? (
          <div className="banner danger">Remove unsupported files before ingesting this bundle.</div>
        ) : null}
      </Panel>
      <FocusedEvidenceReader
        id="data-focus"
        eyebrow="Data Evidence Reader"
        title={dataEvidenceTitle}
        body={dataEvidenceBody}
        status={dataEvidenceStatus}
        statusTone={dataEvidenceTone}
        metrics={[
          { label: "Rows", value: latestDataset?.row_count ?? "-", tone: latestDataset ? "ready" : "risk" },
          { label: "Columns", value: latestDataset?.column_count ?? "-", tone: latestDataset ? "ready" : "risk" },
          { label: "Profiles", value: profileArtifacts.length, tone: latestProfileArtifact ? "ready" : "muted" },
          { label: "Quality", value: qualityArtifacts.length ? qualityArtifacts.length : "none", tone: latestQualityArtifact ? "ready" : "warning" }
        ]}
        nextLabel={dataFocusNextAction}
        nextDetail={dataEvidenceNextDetail}
        nextButtonLabel={dataFocusButtonLabel}
        nextDisabled={dataFocusButtonDisabled}
        onNext={() => {
          if (!latestDataset) return;
          if (!latestQualityArtifact) {
            void runAction(() => api(`/api/datasets/${latestDataset.id}/quality/run`, { method: "POST" }));
            return;
          }
          if (dataFocusRelationalArtifactId) {
            void loadRelationalPreview(dataFocusRelationalArtifactId);
          } else if (dataEvidenceArtifact) {
            void loadQualityPreview(dataEvidenceArtifact.id);
          }
        }}
        previewTitle={dataEvidencePreviewTitle}
        preview={qualityPreview}
        previewError={qualityPreviewError}
        previewLoading={Boolean(qualityPreviewLoadingId)}
        previewEmpty="Upload data or run the quality gate to see the first evidence artifact here."
        boundary="No silent row or feature dropping"
      />
      <Panel title={text.relatedNotebooks} icon={<BookOpen size={18} />}>
        {relatedDataNotebooks.length ? (
          <div className="related-notebook-list">
            {relatedDataNotebooks.map((item) => {
              return (
                <button
                  className="related-notebook-item"
                  key={item.notebook_artifact_id}
                  onClick={() => {
                    onOpenNotebookArtifact(item.artifact_ids.notebook);
                  }}
                  type="button"
                >
                  <BookOpen size={17} />
                  <div>
                    <strong>{item.title}</strong>
                    <small>
                      {notebookStatusLabel(item.status, text)} · {formatDate(item.created_at)}
                    </small>
                  </div>
                  <span>{text.openNotebookViewer}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <EmptyInline text={text.noRelatedNotebooks} />
        )}
      </Panel>
      <details className="data-supporting-shelves data-supporting-shelves-primary">
        <summary>
          <span>Supporting data shelves</span>
          <small>
            benchmark plans, imports, snapshots, profiles, and source artifacts
          </small>
        </summary>
        <div className="data-supporting-shelves-body">
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
        <details className="supporting-details">
          <summary>
            <span>Open benchmark import catalog</span>
            <small>{benchmarks.length} sources / credential gates and fixtures</small>
          </summary>
          <div className="supporting-details-body">
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
          </div>
        </details>
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
                formatJobStatus(job, text),
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
      <Panel title="Dataset Snapshots" icon={<Database size={18} />} className="data-snapshot-panel">
        {datasets.length ? (
          <Table
            headers={["Snapshot", "Source", "Rows", "Columns", "Notebooks", "Schema Hash"]}
            rows={datasets.map((dataset) => [
              dataset.id,
              <div className="cell-stack" key={`${dataset.id}-source`}>
                <span>{dataset.source_type}</span>
                <small>{dataset.source_ref ?? "-"}</small>
              </div>,
              dataset.row_count ?? "-",
              dataset.column_count ?? "-",
              <RelatedNotebookLinks
                key={`${dataset.id}-notebooks`}
                notebooks={notebooksForDataset(notebookIndex, dataset.id)}
                onOpen={onOpenNotebookArtifact}
                previewLoadingId={null}
                text={text}
              />,
              dataset.schema_hash.slice(0, 12)
            ])}
          />
        ) : (
          <EmptyInline text="Uploaded CSV or Parquet files will become DatasetSnapshot assets with schema, row count, and lineage." />
        )}
      </Panel>
      <Panel title="Profile Readiness" icon={<BarChart3 size={18} />} className="data-profile-panel">
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
      <Panel title="Source Artifacts" icon={<FileText size={18} />} className="data-source-panel">
        {datasetArtifacts.length ? (
          <Table
            headers={["Artifact", "Version", "Size"]}
            rows={datasetArtifacts.map((artifact) => [artifact.name, `v${artifact.version}`, formatBytes(artifact.size_bytes)])}
          />
        ) : (
          <EmptyInline text="Raw uploaded files are stored in the local artifact store with content hashes." />
        )}
      </Panel>
        </div>
      </details>
      <Panel id="relational-map" title="Relational Map" icon={<GitBranch size={18} />} className="data-relational-map-panel">
        <div className="relational-map-hero">
          <div>
            <div className="eyebrow">Relationship evidence</div>
            <h3>
              {latestRelationalCatalog
                ? "Start with the ER-style map"
                : latestRelationalHint
                  ? "Review the uploaded ER evidence"
                  : "Add a relational map when tables matter"}
            </h3>
            <p>
              Tablex treats inferred edges and uploaded diagrams as evidence. Confirm keys, cardinality, leakage risk, and
              prediction-time availability before a runner creates relational features.
            </p>
          </div>
          <div className="relational-map-metrics">
            <div>
              <span>Catalogs</span>
              <strong>{relationalArtifacts.length}</strong>
            </div>
            <div>
              <span>ER hints</span>
              <strong>{relationalHintArtifacts.filter((artifact) => artifact.asset_type === "relational_schema_hint").length}</strong>
            </div>
            <div>
              <span>Plans</span>
              <strong>{relationalFeatureArtifacts.length + relationalRecipeArtifacts.length + relationalScenarioArtifacts.length}</strong>
            </div>
          </div>
        </div>
        <div className="relational-command-row">
          <div className="relational-upload-row">
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.svg,.pdf,.json,image/png,image/jpeg,image/svg+xml,application/pdf,application/json"
              onChange={(event) => setErHintFile(event.target.files?.[0] ?? null)}
            />
            <input
              value={erHintNote}
              onChange={(event) => setErHintNote(event.target.value)}
              placeholder="Optional ER note"
            />
            <button className="secondary-button" disabled={!erHintFile || busy} onClick={() => void uploadRelationalSchemaHint()}>
              {busy ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
              Upload ER
            </button>
          </div>
          <div className="button-row">
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
        </div>
        {relationalPreviewError ? <div className="banner danger">{relationalPreviewError}</div> : null}
        {relationalPreviewLoadingId ? (
          <div className="banner muted">
            <Loader2 className="spin" size={16} />
            Loading relational map...
          </div>
        ) : null}
        {relationalPreview?.preview_available ? (
          isRelationalGraphPreview(relationalPreview) ? (
            <RelationalCatalogPreview preview={relationalPreview} />
          ) : isVisualArtifactPreview(relationalPreview) ? (
            <VisualArtifactPreview preview={relationalPreview} />
          ) : isHtmlArtifactPreview(relationalPreview) ? (
            <HtmlArtifactPreview preview={relationalPreview} />
          ) : (
            <TranslatablePreview preview={relationalPreview} />
          )
        ) : (
          <EmptyInline text={relationalPreview?.reason ?? "Import a multi-table benchmark or upload an ER diagram to see relationship evidence here."} />
        )}
        <div className="relational-guardrail-strip">
          <span>Evidence first, not a join contract.</span>
          <span>Feature work must respect EvaluationSpec and SplitManifest.</span>
          <span>Prediction-time availability must be confirmed before lift claims.</span>
        </div>
        <details className="supporting-details">
          <summary>
            <span>Supporting relational artifacts</span>
            <small>
              {relationalArtifacts.length} catalogs / {relationalHintArtifacts.length} uploads /{" "}
              {relationalFeatureArtifacts.length + relationalRecipeArtifacts.length + relationalScenarioArtifacts.length} plans
            </small>
          </summary>
          <div className="supporting-details-body">
            {relationalHintArtifacts.length ? (
              <Table
                headers={["Type", "File", "Parsed", "Created", "Actions"]}
                rows={relationalHintArtifacts.map((artifact) => [
                  artifact.asset_type,
                  String(artifact.metadata.source_filename ?? artifact.name),
                  `${String(artifact.metadata.parsed_table_count ?? "-")} tables / ${String(
                    artifact.metadata.parsed_relationship_count ?? "-"
                  )} rels`,
                  formatDate(artifact.created_at),
                  <div className="row-actions" key={artifact.id}>
                    <button
                      className="icon-button"
                      disabled={relationalPreviewLoadingId === artifact.id}
                      onClick={() => void loadRelationalPreview(artifact.id)}
                      title="Preview ER evidence"
                    >
                      {relationalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                    </button>
                    <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download ER evidence">
                      <Download size={16} />
                    </a>
                  </div>
                ])}
              />
            ) : (
              <EmptyInline text="Upload a PNG, JPEG, SVG, PDF, or JSON ER hint when the dataset meaning depends on table relationships." />
            )}
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
            ) : null}
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
            ) : null}
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
            ) : null}
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
            ) : null}
          </div>
        </details>
      </Panel>
      <details className="data-supporting-shelves data-supporting-shelves-secondary">
        <summary>
          <span>Scenarios, workflow results, and quality details</span>
          <small>
            {scenarioArtifacts.length} scenarios / {publicWorkflowJobs.length} workflows / {qualityArtifacts.length} quality artifacts
          </small>
        </summary>
        <div className="data-supporting-shelves-body">
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
      <Panel title="Data Quality Preview" icon={<FileText size={18} />} className="data-quality-preview-panel">
        {qualityPreviewError ? <div className="banner danger">{qualityPreviewError}</div> : null}
        {qualityPreview?.preview_available ? (
          <TranslatablePreview preview={qualityPreview} />
        ) : (
          <EmptyInline text={qualityPreview?.reason ?? "Analyze quality or select a quality artifact to inspect gates, guidance, and agent-context notes."} />
        )}
      </Panel>
        </div>
      </details>
    </div>
  );
}

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function compactRecordField(value: unknown) {
  if (typeof value === "string") return value.trim() || "-";
  if (!value || typeof value !== "object") return "-";
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entryValue]) => entryValue !== null && entryValue !== undefined && String(entryValue).trim() !== "")
    .slice(0, 3);
  if (!entries.length) return "-";
  return entries.map(([key, entryValue]) => `${key.replace(/_/g, " ")}: ${String(entryValue)}`).join("; ");
}

const tableUploadExtensions = new Set([".csv", ".parquet"]);
const relationalHintUploadExtensions = new Set([".png", ".jpg", ".jpeg", ".svg", ".pdf", ".json"]);

function uploadFileExtension(file: File) {
  const index = file.name.lastIndexOf(".");
  return index >= 0 ? file.name.slice(index).toLowerCase() : "";
}

function isTableUploadFile(file: File) {
  return tableUploadExtensions.has(uploadFileExtension(file));
}

function isRelationalHintUploadFile(file: File) {
  return relationalHintUploadExtensions.has(uploadFileExtension(file));
}

function uploadFileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function buildUploadProgress(
  files: File[],
  loadedBytes: number,
  totalBytes: number,
  active: boolean,
  phase: UploadBundleProgress["phase"] = active ? "transferring" : "complete"
): UploadBundleProgress {
  const safeTotal = Math.max(totalBytes, 0);
  const boundedLoaded = Math.max(0, Math.min(loadedBytes, safeTotal || loadedBytes));
  let offset = 0;
  const fileProgress = files.map((file) => {
    const start = offset;
    offset += file.size;
    const progress =
      file.size > 0 ? Math.max(0, Math.min(100, ((boundedLoaded - start) / file.size) * 100)) : boundedLoaded >= start ? 100 : 0;
    return {
      key: uploadFileKey(file),
      name: file.name,
      kind: isTableUploadFile(file) ? "table" : isRelationalHintUploadFile(file) ? "ER hint" : "unsupported",
      size: file.size,
      progress
    };
  });
  return {
    active,
    phase,
    overall: safeTotal > 0 ? Math.max(0, Math.min(100, (boundedLoaded / safeTotal) * 100)) : active ? 0 : 100,
    loadedBytes: Math.round(boundedLoaded),
    totalBytes: safeTotal,
    files: fileProgress
  };
}

function uploadFileState(progress: UploadFileProgress | undefined, uploadProgress: UploadBundleProgress | null) {
  if (!progress || !uploadProgress) {
    return "queued";
  }
  if (progress.progress >= 100) {
    return "uploaded";
  }
  if (!uploadProgress.active) {
    return "stopped";
  }
  return progress.progress > 0 ? "uploading" : "waiting";
}

async function readQueuedFileColumnHints(files: File[], setHints: React.Dispatch<React.SetStateAction<Record<string, string[]>>>) {
  await Promise.all(
    files.map(async (file) => {
      if (!isTableUploadFile(file)) return;
      const extension = uploadFileExtension(file);
      if (extension !== ".csv") {
        setHints((current) => ({ ...current, [file.name]: [] }));
        return;
      }
      const sample = await file.slice(0, 64 * 1024).text();
      setHints((current) => ({ ...current, [file.name]: parseCsvHeaderColumns(sample) }));
    })
  );
}

function parseCsvHeaderColumns(sample: string): string[] {
  const firstLine = sample.split(/\r?\n/, 1)[0] ?? "";
  const columns: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < firstLine.length; index += 1) {
    const char = firstLine[index];
    const next = firstLine[index + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === "," && !quoted) {
      columns.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  columns.push(current.trim());
  return uniqueStrings(columns.filter(Boolean)).filter((column) => !isGeneratedCsvPlaceholderColumnName(column));
}

function isGeneratedCsvPlaceholderColumnName(value: string): boolean {
  return /^column\d+$/i.test(value.trim());
}

function columnNamesFromSemanticCatalog(catalog: SemanticCatalog | null): string[] {
  if (!catalog) return [];
  return uniqueStrings(
    catalog.columns
      .map((column) => {
        if (typeof column === "string") return column;
        return textField(column.name) ?? textField(column.column_name) ?? textField(column.id);
      })
      .filter((column): column is string => Boolean(column))
  );
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    next.push(normalized);
  }
  return next;
}

function mergeArtifacts(current: Artifact[], incoming: Artifact[]): Artifact[] {
  if (!incoming.length) return current;
  const byId = new Map<string, Artifact>();
  for (const artifact of current) {
    byId.set(artifact.id, artifact);
  }
  for (const artifact of incoming) {
    byId.set(artifact.id, artifact);
  }
  return Array.from(byId.values()).sort((left, right) => {
    const leftTime = Date.parse(left.created_at ?? "");
    const rightTime = Date.parse(right.created_at ?? "");
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return rightTime - leftTime;
    }
    return left.id.localeCompare(right.id);
  });
}

function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanField(value: unknown): boolean {
  return value === true;
}

function recordField(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stringListField(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter((item) => item.trim()) : [];
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
      <Panel id="understanding-report" title="Data Understanding Report" icon={<FileText size={18} />}>
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
    <Panel id="assumption-review" title="Review Queue" icon={<ListChecks size={18} />}>
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
  const { text } = useLocale();
  const latestQualityGate = artifacts.find((artifact) => artifact.asset_type === "data_quality_gate") ?? null;
  const scenarioComparisonArtifacts = artifacts.filter((artifact) => artifact.asset_type === "evaluation_scenario_comparison");
  const approvalReviewArtifacts = artifacts.filter((artifact) => artifact.asset_type === "evaluation_approval_review");
  const [scenarioPreview, setScenarioPreview] = React.useState<ArtifactPreview | null>(null);
  const [scenarioPreviewError, setScenarioPreviewError] = React.useState<string | null>(null);
  const [scenarioPreviewLoadingId, setScenarioPreviewLoadingId] = React.useState<string | null>(null);
  const [approvalPreview, setApprovalPreview] = React.useState<ArtifactPreview | null>(null);
  const [approvalPreviewError, setApprovalPreviewError] = React.useState<string | null>(null);
  const [approvalPreviewLoadingId, setApprovalPreviewLoadingId] = React.useState<string | null>(null);
  const autoPreviewedScenarioRef = React.useRef<string | null>(null);

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

  const latestScenarioComparison = scenarioComparisonArtifacts[0] ?? null;
  const latestApprovedSpec = specs.find((spec) => spec.status === "approved") ?? null;
  const latestSpec = latestApprovedSpec ?? specs[0] ?? null;
  const promotableCandidate =
    candidates.find((candidate) => candidate.status === "primary_candidate") ??
    candidates.find((candidate) => candidate.status === "alternative") ??
    candidates[0] ??
    null;
  const evaluationStatus = latestApprovedSpec
    ? text.evaluationStatusApproved
    : latestScenarioComparison
      ? text.evaluationStatusComparisonReady
      : candidates.length
        ? text.evaluationStatusCandidatesDrafted
        : text.evaluationStatusNeedsDesign;
  const evaluationStatusTone: EvidenceReaderMetric["tone"] = latestApprovedSpec ? "ready" : candidates.length ? "warning" : "risk";
  const evaluationReaderTitle = latestApprovedSpec
    ? text.evaluationReaderApprovedTitle
    : latestScenarioComparison
      ? text.evaluationReaderComparisonTitle
      : candidates.length
        ? text.evaluationReaderCandidatesTitle
        : text.evaluationReaderNeedsDesignTitle;
  const evaluationReaderBody = text.evaluationReaderBody;
  const evaluationNextLabel = !candidates.length
    ? text.evaluationNextDesignCandidates
    : !latestScenarioComparison
      ? text.evaluationNextCompareScenarios
      : !latestSpec
        ? text.evaluationNextPromoteCandidate
        : latestSpec.status !== "approved"
          ? text.evaluationNextApproveSpec
          : text.evaluationNextGenerateSplit;
  const evaluationNextDetail = !candidates.length
    ? text.evaluationNextDesignCandidatesDetail
    : !latestScenarioComparison
      ? text.evaluationNextCompareScenariosDetail
      : !latestSpec
        ? text.evaluationNextPromoteCandidateDetail
        : latestSpec.status !== "approved"
          ? text.evaluationNextApproveSpecDetail
          : text.evaluationNextGenerateSplitDetail;
  const evaluationButtonDisabled =
    busy ||
    (!candidates.length
      ? false
      : !latestScenarioComparison
        ? false
        : !latestSpec
          ? !promotableCandidate
          : latestSpec.status === "approved"
            ? !["random", "stratified", "time", "group"].includes(latestSpec.split_type)
            : false);

  React.useEffect(() => {
    if (!latestScenarioComparison) return;
    if (scenarioPreview?.id === latestScenarioComparison.id) return;
    if (autoPreviewedScenarioRef.current === latestScenarioComparison.id) return;
    autoPreviewedScenarioRef.current = latestScenarioComparison.id;
    setScenarioPreviewLoadingId(latestScenarioComparison.id);
    setScenarioPreviewError(null);
    api<ArtifactPreview>(`/api/artifacts/${latestScenarioComparison.id}/preview`)
      .then((preview) => {
        setScenarioPreview(preview);
      })
      .catch((err: unknown) => {
        setScenarioPreviewError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setScenarioPreviewLoadingId(null);
      });
  }, [latestScenarioComparison, scenarioPreview?.id]);

  return (
    <div className="stack">
      <FocusedEvidenceReader
        id="evaluation-design"
        eyebrow={text.evaluationReaderEyebrow}
        title={evaluationReaderTitle}
        body={evaluationReaderBody}
        status={evaluationStatus}
        statusTone={evaluationStatusTone}
        metrics={[
          { label: text.evaluationMetricCandidates, value: candidates.length, tone: candidates.length ? "ready" : "risk" },
          { label: text.evaluationMetricSpecs, value: specs.length, tone: specs.length ? "ready" : "muted" },
          { label: text.evaluationMetricComparison, value: latestScenarioComparison ? text.evaluationMetricReady : text.evaluationMetricMissing, tone: latestScenarioComparison ? "ready" : "warning" },
          { label: text.evaluationMetricQuality, value: latestQualityGate ? text.evaluationMetricReady : text.evaluationMetricMissing, tone: latestQualityGate ? "ready" : "warning" }
        ]}
        nextEyebrow={text.notebookMetricNext}
        nextLabel={evaluationNextLabel}
        nextDetail={evaluationNextDetail}
        nextButtonLabel={evaluationNextLabel}
        nextDisabled={evaluationButtonDisabled}
        onNext={() => {
          if (!candidates.length) {
            void runAction(() => api(`/api/projects/${project.id}/evaluation/design`, { method: "POST" }));
            return;
          }
          if (!latestScenarioComparison) {
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/evaluation/compare`, { method: "POST" });
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Evaluation comparison job" });
              const artifactId = completedJob.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadScenarioPreview(artifactId);
              }
              return completedJob;
            });
            return;
          }
          if (!latestSpec && promotableCandidate) {
            void runAction(() => api(`/api/evaluation-candidates/${promotableCandidate.id}/promote`, { method: "POST" }));
            return;
          }
          if (latestSpec && latestSpec.status !== "approved") {
            void runAction(() => api(`/api/evaluation-specs/${latestSpec.id}/approve`, { method: "POST" }));
            return;
          }
          if (latestSpec) {
            void runAction(() => api(`/api/evaluation-specs/${latestSpec.id}/generate-split`, { method: "POST" }));
          }
        }}
        previewEyebrow={text.notebookReadThisNow}
        previewTitle={latestScenarioComparison ? text.evaluationPreviewLatestScenario : text.evaluationPreviewDecisionEvidence}
        preview={scenarioPreview}
        previewError={scenarioPreviewError}
        previewLoading={Boolean(scenarioPreviewLoadingId)}
        previewEmpty={text.evaluationPreviewEmpty}
        boundary={text.evaluationBoundaryExplicit}
      />
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void runAction(() => api(`/api/projects/${project.id}/evaluation/design`, { method: "POST" }))}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
          {text.evaluationActionDesignCandidates}
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/evaluation/compare`, { method: "POST" });
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Evaluation comparison job" });
              const artifactId = completedJob.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadScenarioPreview(artifactId);
              }
              return completedJob;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          {text.evaluationActionCompareScenarios}
        </button>
      </div>
      <Panel id="evaluation-candidates" title={text.evaluationCandidatesTitle} icon={<BarChart3 size={18} />}>
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
                    <dt>{text.evaluationCandidateMetric}</dt>
                    <dd>{candidate.primary_metric}</dd>
                  </div>
                  <div>
                    <dt>{text.evaluationCandidateStratify}</dt>
                    <dd>{candidate.stratify_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>{text.evaluationCandidateTime}</dt>
                    <dd>{candidate.time_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>{text.evaluationCandidateGroup}</dt>
                    <dd>{candidate.group_column || "-"}</dd>
                  </div>
                  <div>
                    <dt>{text.evaluationCandidateExcluded}</dt>
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
                  {text.evaluationCandidatePromote}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text={text.evaluationCandidatesEmpty} />
        )}
      </Panel>
      <Panel title={text.evaluationScenarioComparisonsTitle} icon={<ListChecks size={18} />}>
        {scenarioComparisonArtifacts.length ? (
          <Table
            headers={text.evaluationScenarioComparisonHeaders}
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
                  title={text.evaluationScenarioComparisonPreviewTitle}
                >
                  {scenarioPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.evaluationScenarioComparisonDownloadTitle}>
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.evaluationScenarioComparisonEmpty} />
        )}
        {scenarioPreviewError ? <div className="banner danger">{scenarioPreviewError}</div> : null}
        {scenarioPreview?.preview_available ? (
          <TranslatablePreview preview={scenarioPreview} />
        ) : (
          <EmptyInline text={scenarioPreview?.reason ?? text.evaluationScenarioComparisonSelectEmpty} />
        )}
      </Panel>
      <Panel title={text.evaluationQualityGateTitle} icon={<AlertTriangle size={18} />}>
        {latestQualityGate ? (
          <Table
            headers={text.evaluationQualityGateHeaders}
            rows={[
              [
                latestQualityGate.name,
                String(latestQualityGate.metadata.severity ?? "-"),
                String(latestQualityGate.metadata.dataset_snapshot_id ?? "-"),
                <a className="icon-link" key={latestQualityGate.id} href={`${apiBase}/api/artifacts/${latestQualityGate.id}/download`} title={text.evaluationQualityGateDownloadTitle}>
                  <Download size={16} />
                </a>
              ]
            ]}
          />
        ) : (
          <EmptyInline text={text.evaluationQualityGateEmpty} />
        )}
      </Panel>
      <Panel title={text.evaluationSpecsTitle} icon={<Check size={18} />}>
        {specs.length ? (
          <Table
            headers={text.evaluationSpecsHeaders}
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
                      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Evaluation approval review job" });
                      const artifactId = completedJob.output.artifact_id;
                      if (typeof artifactId === "string") {
                        await loadApprovalPreview(artifactId);
                      }
                      return completedJob;
                    })
                  }
                  title={text.evaluationCreateApprovalReviewTitle}
                >
                  <ListChecks size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || spec.status === "approved"}
                  onClick={() => void runAction(() => api(`/api/evaluation-specs/${spec.id}/approve`, { method: "POST" }))}
                  title={text.evaluationApproveSpecTitle}
                >
                  <Check size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={busy || spec.status !== "approved" || !["random", "stratified", "time", "group"].includes(spec.split_type)}
                  onClick={() =>
                    void runAction(() => api(`/api/evaluation-specs/${spec.id}/generate-split`, { method: "POST" }))
                  }
                  title={text.evaluationGenerateSplitTitle}
                >
                  <GitBranch size={16} />
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.evaluationSpecsEmpty} />
        )}
      </Panel>
      <Panel title={text.evaluationApprovalReviewsTitle} icon={<FileText size={18} />}>
        {approvalReviewArtifacts.length ? (
          <Table
            headers={text.evaluationApprovalReviewsHeaders}
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
                  title={text.evaluationApprovalReviewPreviewTitle}
                >
                  {approvalPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.evaluationApprovalReviewDownloadTitle}>
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.evaluationApprovalReviewsEmpty} />
        )}
        {approvalPreviewError ? <div className="banner danger">{approvalPreviewError}</div> : null}
        {approvalPreview?.preview_available ? (
          <TranslatablePreview preview={approvalPreview} />
        ) : (
          <EmptyInline text={approvalPreview?.reason ?? text.evaluationApprovalReviewSelectEmpty} />
        )}
      </Panel>
    </div>
  );
}

function StrategyBriefPanel({
  project,
  brief,
  busy,
  locale,
  text,
  onAction,
  onSave
}: {
  project: Project;
  brief: AdaptiveStrategyBrief | null;
  busy: boolean;
  locale: string;
  text: LocaleMessages;
  onAction: (action: StrategyAction) => void;
  onSave: () => Promise<void>;
}) {
  if (!brief) {
    return (
      <section id="strategy-brief-focus" className="strategy-brief-panel">
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
  const actionLabel = strategyActionDisplayLabel(action, locale, text);
  const actionReason = strategyActionDisplayReason(action, locale, text);
  const handoffObjective = displayTextOrFallback(
    textField(brief.codex_handoff.suggested_objective) ?? action.prompt ?? action.reason,
    locale,
    actionReason
  );
  const openItems =
    numericSummary(brief.summary.open_assumption_count) + numericSummary(brief.summary.open_question_count);
  const metrics = [
    { label: text.strategyArtifacts, value: numericSummary(brief.summary.artifact_count) },
    { label: text.strategyOpenItems, value: openItems },
    { label: text.strategyIdeas, value: numericSummary(brief.summary.idea_count) },
    { label: text.strategyRuns, value: numericSummary(brief.summary.experiment_run_count) }
  ];

  return (
    <section id="strategy-brief-focus" className="strategy-brief-panel">
      <div className="strategy-hero">
        <div className="strategy-hero-copy">
          <img src="/mascot/tablee-hero.png" alt="" aria-hidden="true" className="strategy-hero-mascot" />
          <div>
            <div className="eyebrow">{text.strategyBriefTitle}</div>
            <h2>{actionLabel}</h2>
            <p>{actionReason}</p>
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
          <div
            key={lane.lane_id}
            className={`strategy-lane ${strategyLaneTone(lane.status)}`}
            title={strategyLaneDisplayWhy(lane, locale, text)}
          >
            <span>{strategyLaneDisplayTitle(lane, locale, text)}</span>
            <strong>{formatStrategyStatus(lane.status, text)}</strong>
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

function strategyActionDisplayLabel(action: StrategyAction, locale: string, text: LocaleMessages): string {
  const display = action.display?.label ?? action.display_label;
  if (hasNonEmptyDisplayText(display)) return display as string;
  const fallback = strategyActionLabelFallback(action, text);
  return displayTextOrFallback(action.label, locale, fallback);
}

function strategyActionDisplayReason(action: StrategyAction, locale: string, text: LocaleMessages): string {
  const display = action.display?.reason ?? action.display_reason;
  if (hasNonEmptyDisplayText(display)) return display as string;
  const fallback = strategyActionReasonFallback(action, text);
  return displayTextOrFallback(action.reason, locale, fallback);
}

function strategyLaneDisplayTitle(lane: StrategyLane, locale: string, text: LocaleMessages): string {
  const display = lane.display?.title ?? lane.display_title;
  if (hasNonEmptyDisplayText(display)) return display as string;
  return displayTextOrFallback(lane.title, locale, text.strategyRecommendedAction);
}

function strategyLaneDisplayWhy(lane: StrategyLane, locale: string, text: LocaleMessages): string {
  const display = lane.display?.why ?? lane.display_why;
  if (hasNonEmptyDisplayText(display)) return display as string;
  return displayTextOrFallback(lane.why, locale, text.strategyBriefSubtitle);
}

function strategyActionLabelFallback(action: StrategyAction, text: LocaleMessages): string {
  if (action.label === "Upload data") return text.strategyActionUploadData;
  if (action.label === "Resolve blocking assumptions") return text.strategyActionResolveAssumptions;
  if (action.label === "Lock evaluation design") return text.strategyActionLockEvaluation;
  if (action.label === "Explore objective candidates") return text.focusUnderstandData;
  if (action.label === "Create ResearchPlan") return text.focusApproach;
  if (action.label === "Plan adaptive baseline") return text.focusExperiments;
  if (action.label === "Plan Codex AgentTask") return text.focusApproach;
  if (action.label === "Run or prepare the first approach") return text.focusExperiments;
  if (action.label === "Refresh decision report") return text.focusReports;
  return text.strategyRecommendedAction;
}

function strategyActionReasonFallback(action: StrategyAction, text: LocaleMessages): string {
  if (action.label === "Upload data") return text.focusUploadDataReason;
  if (action.label === "Resolve blocking assumptions") return text.focusAssumptionsReason;
  if (action.label === "Lock evaluation design") return text.focusEvaluationReason;
  if (action.label === "Explore objective candidates") return text.focusUnderstandDataReason;
  if (action.label === "Create ResearchPlan") return text.focusApproachReason;
  if (action.label === "Plan adaptive baseline") return text.focusApproachReason;
  if (action.label === "Plan Codex AgentTask") return text.focusApproachReason;
  if (action.label === "Run or prepare the first approach") return text.focusExperimentsReason;
  if (action.label === "Refresh decision report") return text.focusReportsReason;
  return text.strategyBriefSubtitle;
}

function RunnerHandoffFocus({
  artifact,
  readiness,
  busy,
  onPreview,
  onReadiness,
  onWorkspace,
  onRunStub,
  onRunCodex
}: {
  artifact: Artifact | null;
  readiness: RunnerReadinessFeedback | null;
  busy: boolean;
  onPreview: (artifact: Artifact) => void;
  onReadiness: (artifact: Artifact) => void;
  onWorkspace: (artifact: Artifact) => void;
  onRunStub: (artifact: Artifact) => void;
  onRunCodex: (artifact: Artifact) => void;
}) {
  if (!artifact) {
    return (
      <section id="approach-handoff" className="runner-handoff-focus empty">
        <div>
          <div className="eyebrow">Runner handoff</div>
          <h2>No controlled runner task yet</h2>
          <p>Ask Tablee for one focused action after data understanding or evaluation design. Tablex will keep the contract, artifacts, lineage, and safety rules in the harness.</p>
        </div>
      </section>
    );
  }
  const summary = recordField(artifact.metadata.agent_task_contract_summary);
  const taskType = textField(summary.task_type) ?? textField(artifact.metadata.task_type) ?? "agent_task";
  const label = textField(summary.label) ?? textField(artifact.metadata.runner_handoff_label) ?? taskType.replace(/_/g, " ");
  const objective = textField(summary.objective_summary) ?? textField(artifact.metadata.objective_summary) ?? "Open the contract preview to inspect the runner objective.";
  const nextAction = textField(summary.next_action) ?? "Review readiness before execution.";
  const requiredOutputs = numberField(summary.required_output_count) ?? numberField(artifact.metadata.required_output_count) ?? 0;
  const qualityChecks = numberField(summary.quality_check_count) ?? numberField(artifact.metadata.quality_check_count) ?? 0;
  const contextCount =
    numberField(summary.notebook_followup_context_count) ?? numberField(artifact.metadata.notebook_followup_context_count) ?? 0;
  const evaluationStatus = textField(summary.evaluation_status) ?? textField(artifact.metadata.evaluation_status) ?? "missing";
  const splitRequired = Boolean(summary.split_manifest_required ?? artifact.metadata.split_manifest_required);

  return (
    <section id="approach-handoff" className="runner-handoff-focus" aria-label="Runner handoff focus">
      <div className="runner-handoff-main">
        <div className="eyebrow">Runner handoff</div>
        <h2>{label}</h2>
        <p>{objective}</p>
        <div className="badge-row">
          <span className="badge">{taskType.replace(/_/g, " ")}</span>
          <span className={evaluationStatus === "approved" ? "badge" : "badge warning"}>
            evaluation: {evaluationStatus.replace(/_/g, " ")}
          </span>
          <span className={splitRequired ? "badge" : "badge muted"}>
            split manifest: {splitRequired ? "must respect" : "not locked"}
          </span>
        </div>
      </div>
      <div className="runner-handoff-side">
        <div className="runner-handoff-metrics">
          <Metric label="Outputs" value={requiredOutputs} />
          <Metric label="Checks" value={qualityChecks} />
          <Metric label="Context" value={contextCount} />
        </div>
        <div className="runner-next-action">
          <span>Next</span>
          <strong>{nextAction}</strong>
        </div>
        {readiness ? (
          <div className={`runner-readiness-result ${readiness.status}`}>
            <span>Readiness</span>
            <strong>{formatRunnerReadinessStatus(readiness)}</strong>
            {readiness.nextActions.length ? <p>{readiness.nextActions[0]}</p> : null}
          </div>
        ) : (
          <div className="runner-readiness-result pending">
            <span>Readiness</span>
            <strong>Not reviewed in this focus yet</strong>
            <p>Run readiness before execution so blockers stay visible here.</p>
          </div>
        )}
        <div className="runner-handoff-actions">
          <button className="primary-button" disabled={busy} onClick={() => onReadiness(artifact)}>
            {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
            Review readiness
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => onPreview(artifact)}>
            <Eye size={16} />
            Preview contract
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => onWorkspace(artifact)}>
            {busy ? <Loader2 className="spin" size={16} /> : <Layers size={16} />}
            Workspace
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => onRunStub(artifact)}>
            {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            Local stub
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => onRunCodex(artifact)}>
            {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
            Codex
          </button>
        </div>
      </div>
    </section>
  );
}

function formatRunnerReadinessStatus(feedback: RunnerReadinessFeedback) {
  if (feedback.status === "blocked") {
    return `${feedback.blockerCount} blocker${feedback.blockerCount === 1 ? "" : "s"} before execution`;
  }
  if (feedback.status === "ready_with_warnings") {
    return `${feedback.warningCount} warning${feedback.warningCount === 1 ? "" : "s"}; runner can proceed carefully`;
  }
  return `${feedback.passCount} checks passed; runner is ready`;
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

function formatStrategyStatus(status: string, text: LocaleMessages) {
  if (status === "ready") return researchPlanStatusLabel("done", text);
  if (status === "needs_context") return researchPlanStatusLabel("waiting", text);
  if (status === "needs_review") return researchPlanStatusLabel("blocked", text);
  if (status === "needs_decision") return researchPlanStatusLabel("blocked", text);
  if (status === "needs_plan") return researchPlanStatusLabel("pending", text);
  if (status === "needs_handoff") return researchPlanStatusLabel("pending", text);
  if (status === "needs_outputs") return researchPlanStatusLabel("pending", text);
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

function latestReadinessFeedbackForContract(
  artifacts: Artifact[],
  contractArtifact: Artifact | null
): RunnerReadinessFeedback | null {
  if (!contractArtifact) return null;
  const readinessArtifact = artifacts
    .filter(
      (artifact) =>
        artifact.asset_type === "agent_task_readiness_review" &&
        artifact.metadata.source_contract_artifact_id === contractArtifact.id
    )
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())[0];
  return readinessArtifact ? readinessFeedbackFromArtifact(readinessArtifact, contractArtifact.id) : null;
}

function readinessFeedbackFromArtifact(artifact: Artifact, contractArtifactId: string): RunnerReadinessFeedback {
  const firstAction = textField(artifact.metadata.first_next_action);
  return {
    contractArtifactId,
    status: textField(artifact.metadata.readiness_status) ?? "unknown",
    blockerCount: numberField(artifact.metadata.blocker_count) ?? 0,
    warningCount: numberField(artifact.metadata.warning_count) ?? 0,
    passCount: numberField(artifact.metadata.pass_count) ?? 0,
    nextActions: firstAction ? [firstAction] : [],
    source: "latest_artifact"
  };
}

function readinessFeedbackFromJob(job: Job, contractArtifactId: string): RunnerReadinessFeedback {
  return {
    contractArtifactId,
    status: textField(job.output.readiness_status) ?? "unknown",
    blockerCount: numberField(job.output.blocker_count) ?? 0,
    warningCount: numberField(job.output.warning_count) ?? 0,
    passCount: numberField(job.output.pass_count) ?? 0,
    nextActions: stringListField(job.output.next_actions).slice(0, 3),
    source: "current_review"
  };
}

function ApproachTab({
  project,
  strategyBrief,
  researchBriefs,
  ideas,
  artifacts,
  busy,
  locale,
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
  locale: string;
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
  const agentTaskContractArtifacts = artifacts
    .filter((artifact) => artifact.asset_type === "agent_task_contract")
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());
  const latestAgentTaskContract = agentTaskContractArtifacts[0] ?? null;
  const persistedReadinessFeedback = latestReadinessFeedbackForContract(artifacts, latestAgentTaskContract);
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
  const [runnerReadinessFeedback, setRunnerReadinessFeedback] = React.useState<RunnerReadinessFeedback | null>(null);
  const activeRunnerReadiness =
    runnerReadinessFeedback?.contractArtifactId === latestAgentTaskContract?.id
      ? runnerReadinessFeedback
      : persistedReadinessFeedback;
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

  async function previewContract(artifact: Artifact) {
    await loadTaskContractPreview(artifact.id);
  }

  async function prepareContractWorkspace(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/prepare-workspace`, {
      method: "POST"
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Agent workspace preparation job" });
    const workspaceArtifactId = completedJob.output.agent_workspace_manifest_artifact_id ?? completedJob.output.artifact_id;
    if (typeof workspaceArtifactId === "string") {
      await loadWorkspacePreview(workspaceArtifactId);
    }
    return completedJob;
  }

  async function reviewContractReadiness(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/readiness-review`, {
      method: "POST"
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Agent readiness review job" });
    const reportArtifactId = completedJob.output.agent_task_readiness_report_artifact_id ?? completedJob.output.artifact_id;
    if (typeof reportArtifactId === "string") {
      await loadTaskContractPreview(reportArtifactId);
    }
    setRunnerReadinessFeedback(readinessFeedbackFromJob(completedJob, artifact.id));
    return completedJob;
  }

  async function runContractLocalStub(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-local-stub`, {
      method: "POST"
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Local stub runner job" });
    const ingested = completedJob.output.ingested_artifact_ids;
    const reportArtifactId = Array.isArray(ingested) ? textField(ingested[0]) : null;
    if (reportArtifactId) {
      await loadTaskContractPreview(reportArtifactId);
    }
    return completedJob;
  }

  async function runContractCodex(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-codex`, {
      method: "POST"
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 30 * 60_000, label: "Codex runner job" });
    const ingested = completedJob.output.ingested_artifact_ids;
    const reportArtifactId = Array.isArray(ingested) ? textField(ingested[0]) : null;
    if (reportArtifactId) {
      await loadTaskContractPreview(reportArtifactId);
    }
    return completedJob;
  }

  return (
    <div className="stack">
      <StrategyBriefPanel
        project={project}
        brief={strategyBrief}
        busy={busy}
        locale={locale}
        text={text}
        onAction={onStrategyAction}
        onSave={() =>
          runAction(() =>
            api(`/api/projects/${project.id}/approach/strategy-brief`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ locale })
            })
          )
        }
      />
      <RunnerHandoffFocus
        artifact={latestAgentTaskContract}
        readiness={activeRunnerReadiness}
        busy={busy}
        onPreview={(artifact) => void previewContract(artifact)}
        onReadiness={(artifact) => void runAction(() => reviewContractReadiness(artifact))}
        onWorkspace={(artifact) => void runAction(() => prepareContractWorkspace(artifact))}
        onRunStub={(artifact) => void runAction(() => runContractLocalStub(artifact))}
        onRunCodex={(artifact) => void runAction(() => runContractCodex(artifact))}
      />
      <div className="toolbar">
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/approach/research-plan`, { method: "POST" });
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Research plan job" });
              const artifactId = completedJob.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchPlanPreview(artifactId);
              }
              return completedJob;
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
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Research source pack job" });
              const artifactId =
                completedJob.output.research_source_report_artifact_id ?? completedJob.output.research_source_pack_artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchSourcePreview(artifactId);
              }
              return completedJob;
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
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Research synthesis job" });
              const artifactId =
                completedJob.output.research_finding_synthesis_report_artifact_id ??
                completedJob.output.research_finding_synthesis_artifact_id;
              if (typeof artifactId === "string") {
                await loadResearchSynthesisPreview(artifactId);
              }
              return completedJob;
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
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Codex work planning" });
              const artifactId = completedJob.output.agent_task_contract_artifact_id ?? completedJob.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadTaskContractPreview(artifactId);
              }
              return completedJob;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Plan Codex Work
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
                      const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Research source stub job" });
                      const reportArtifactId = completedJob.output.research_findings_report_artifact_id;
                      if (typeof reportArtifactId === "string") {
                        await loadResearchSourcePreview(reportArtifactId);
                      }
                      return completedJob;
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
          <EmptyInline text="Research syntheses will consolidate controlled findings, citation audit state, follow-up requirements, and Codex work notes for flexible approach planning." />
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
          title="Codex work context"
          subtitle="Prepared context, research briefs, and Ideas that Codex can use or reject with a decision trace."
          countLabel={`${runnerHandoffCount} items`}
          defaultOpen={!strategyBrief}
        >
      <Panel title="Codex Work Requests" icon={<ListChecks size={18} />}>
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
                  onClick={() => void previewContract(artifact)}
                  title="Preview Codex work request"
                >
                  {taskContractPreviewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title="Download Codex work request">
                  <Download size={16} />
                </a>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => prepareContractWorkspace(artifact))}
                  title="Prepare controlled workspace"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Layers size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => reviewContractReadiness(artifact))}
                  title="Review runner readiness"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => runContractLocalStub(artifact))}
                  title="Run local stub"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() => void runAction(() => runContractCodex(artifact))}
                  title="Run Codex CLI"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
                </button>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text="Codex work requests will combine dataset context, approved evaluation constraints, assumptions, Skill/library recommendations, research queries, reporting requirements, and artifact expectations." />
        )}
        {taskContractPreviewError ? <div className="banner danger">{taskContractPreviewError}</div> : null}
        {taskContractPreview?.preview_available ? (
          <TranslatablePreview preview={taskContractPreview} />
        ) : (
          <EmptyInline text={taskContractPreview?.reason ?? "Plan or select a Codex work request to inspect the exact flexible context before execution."} />
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
          <EmptyInline text="Flexible candidate approaches will appear here as evidence-backed Ideas with prepared context for Codex, Skills, and controlled research." />
        )}
      </Panel>
        </ApproachDetailGroup>
        <ApproachDetailGroup
          title="Previews and manifests"
          subtitle="Inspect materialized context packs, experiment plans, and controlled workspaces after creating them."
          countLabel={`${previewCount} previews`}
          defaultOpen={previewCount > 0 && !strategyBrief}
        >
      <Panel title="Codex Context Pack Preview" icon={<FileText size={18} />}>
        {contextPreviewError ? <div className="banner danger">{contextPreviewError}</div> : null}
        {contextPreview?.preview_available ? (
          <TranslatablePreview preview={contextPreview} />
        ) : (
          <EmptyInline text={contextPreview?.reason ?? "Prepare and preview the context pack before Codex execution."} />
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
      <Panel title="Codex Workspace Preview" icon={<Layers size={18} />}>
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
  notebookIndex,
  busy,
  locale,
  text,
  runAction,
  onAskAgent,
  onOpenNotebookArtifact
}: {
  project: Project;
  jobs: Job[];
  runs: Run[];
  agentTaskResults: AgentTaskResult[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  busy: boolean;
  locale: string;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (message: string) => Promise<AgentChatResponse | void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
}) {
  const experimentJobs = jobs.filter((job) =>
    [
      "plan_baseline_strategy",
      "plan_agent_task",
      "run_baseline",
      "train_model_candidates",
      "run_public_benchmark_workflow",
      "run_agent_task",
      "create_experiment_plan",
      "compare_experiments",
      "draft_run_report",
      "analyze_evaluation_diagnostics",
      "generate_model_diagnostics_notebook",
      "materialize_model_diagnostics_artifacts"
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
      "marimo_notebook",
      "notebook_run_manifest",
      "notebook_report",
      "feature_importance",
      "permutation_importance",
      "model_diagnostics_artifact_pack",
      "model_diagnostics_artifact_report"
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
      focusNavigationAnchor("notebook-native-marimo-top");
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
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Baseline strategy plan job" });
              const artifactId = completedJob.output.baseline_strategy_plan_artifact_id;
              if (typeof artifactId === "string") {
                await loadPreview(artifactId);
              }
              return completedJob;
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
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Codex work planning" });
              const artifactId = completedJob.output.agent_task_contract_artifact_id ?? completedJob.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadPreview(artifactId);
              }
              return completedJob;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          Plan Codex Work
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
            headers={["Run", "Runner", "Status", "Model", "ModelVersion", "Features", "Primary Metric", "Spec", "Split", "Notebooks", "Actions"]}
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
                <RelatedNotebookLinks
                  key={`${run.id}-notebooks`}
                  notebooks={notebooksForRun(notebookIndex, run.id)}
                  onOpen={onOpenNotebookArtifact}
                  previewLoadingId={previewLoadingId}
                  text={text}
                />,
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
                      const job = await api<Job>(`/api/runs/${run.id}/model-diagnostics-artifacts`, { method: "POST" });
                      const completedJob = await runQueuedJobAndWait(job, {
                        timeoutMs: 10 * 60_000,
                        label: "Model diagnostics artifacts job"
                      });
                      const artifactId =
                        textField(completedJob.output.model_diagnostics_report_artifact_id) ??
                        textField(completedJob.output.model_diagnostics_artifact_pack_id);
                      if (artifactId) {
                        await loadPreview(artifactId);
                      }
                      return completedJob;
                    })
                  }
                  title="Materialize model evidence artifacts"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
                </button>
                <button
                  className="icon-button"
                  disabled={busy}
                  onClick={() =>
                    void runAction(async () => {
                      const job = await api<Job>(`/api/runs/${run.id}/analysis-notebook`, { method: "POST" });
                      const completedJob = await runQueuedJobAndWait(job, {
                        timeoutMs: 15 * 60_000,
                        label: "Model notebook job"
                      });
                      await openNotebookOrAskAgentToAuthor({
                        completedJob,
                        locale,
                        projectName: project.name,
                        notebookKind: `model diagnostics for ${run.id}`,
                        onOpenNotebookArtifact,
                        onAskAgent
                      });
                      return completedJob;
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
          <EmptyInline text="Baseline runs, Codex work runs, failed repair attempts, metrics, parameters, and linked artifacts will appear here." />
        )}
      </Panel>
      <Panel title="Codex Work Results" icon={<FileText size={18} />}>
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
                {isNativeNotebookSourceAssetType(artifact.asset_type) ? (
                  <button
                    className="icon-button"
                    onClick={() => onOpenNotebookArtifact(artifact.id)}
                    title={text.openNotebookInMarimo}
                  >
                    <BookOpen size={16} />
                  </button>
                ) : (
                  <button
                    className="icon-button"
                    disabled={previewLoadingId === artifact.id}
                    onClick={() => void loadPreview(artifact.id)}
                    title="Preview experiment artifact"
                  >
                    {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                  </button>
                )}
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
  analysisStory,
  previewRequest,
  busy,
  locale,
  runAction,
  onAskAgent
}: {
  project: Project;
  datasets: DatasetSnapshot[];
  runs: Run[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  analysisStory: AnalysisStorySurface | null;
  previewRequest: ArtifactPreviewRequest | null;
  busy: boolean;
  locale: string;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (message: string) => Promise<AgentChatResponse | void>;
}) {
  const { text } = useLocale();
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [nativeMarimoSession, setNativeMarimoSession] = React.useState<NativeMarimoSession | null>(null);
  const [nativeMarimoError, setNativeMarimoError] = React.useState<string | null>(null);
  const [nativeMarimoLoadingId, setNativeMarimoLoadingId] = React.useState<string | null>(null);
  const [selectedNotebookArtifactId, setSelectedNotebookArtifactId] = React.useState<string | null>(null);
  const [guideDraft, setGuideDraft] = React.useState("");
  const [guideResponse, setGuideResponse] = React.useState<string | null>(null);
  const [guideBusy, setGuideBusy] = React.useState(false);
  const latestDataset = datasets[0] ?? null;
  const latestRun = runs[0] ?? null;
  const notebookItems = React.useMemo(() => preferredNotebookItems(notebookIndex), [notebookIndex]);
  const recommendedNotebook = notebookIndex?.recommended_notebook ?? null;
  const selectedNotebook = React.useMemo(
    () => selectedNotebookArtifactId ? preferredNotebookForArtifact(notebookIndex, selectedNotebookArtifactId) : null,
    [notebookIndex, selectedNotebookArtifactId]
  );
  const selectedNotebookOverridesStory = Boolean(
    selectedNotebook && selectedNotebook.notebook_artifact_id !== recommendedNotebook?.notebook_artifact_id
  );
  const recommendedNotebookHasQualityIssue = isEmptyDiagnosticsNotebook(recommendedNotebook);
  const reviewNotebook = selectedNotebook ?? recommendedNotebook;
  const notebookFigureCount = React.useMemo(() => notebookItems.reduce((total, item) => total + notebookFigureCountForItem(item), 0), [notebookItems]);
  const executionArtifacts = artifacts.filter(
    (artifact) =>
      [
        "notebook_execution_plan",
        "notebook_figure_manifest",
        "notebook_evidence_bundle",
        "notebook_evidence_svg"
      ].includes(artifact.asset_type) ||
      (artifact.asset_type === "agent_task_contract" && typeof artifact.metadata.notebook_artifact_id === "string")
  );
  const reviewArtifacts = executionArtifacts;

  async function loadPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    try {
      setPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
      focusNavigationAnchor("notebook-native-marimo-top");
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoadingId(null);
    }
  }

  const openNativeMarimoArtifact = React.useCallback(async (artifactId: string, options?: { restart?: boolean }) => {
    setSelectedNotebookArtifactId(artifactId);
    setNativeMarimoLoadingId(artifactId);
    setNativeMarimoError(null);
    setPreview(null);
    setPreviewError(null);
    focusNavigationAnchor("notebook-native-marimo-top", 0);
    const params = new URLSearchParams({ wait_ready: "false" });
    if (options?.restart) params.set("restart", "true");
    try {
      setNativeMarimoSession(
        await api<NativeMarimoSession>(`/api/analysis-notebooks/${artifactId}/marimo-session?${params.toString()}`, {
          method: "POST"
        })
      );
      focusNavigationAnchor("notebook-native-marimo-top");
    } catch (err) {
      setNativeMarimoError(err instanceof Error ? err.message : String(err));
      focusNavigationAnchor("notebook-native-marimo-top");
    } finally {
      setNativeMarimoLoadingId(null);
    }
  }, []);

  const openNativeMarimo = React.useCallback(async (item: NotebookIndexItem) => {
    await openNativeMarimoArtifact(item.artifact_ids.notebook);
  }, [openNativeMarimoArtifact]);

  const restartNativeMarimoArtifact = React.useCallback(async (artifactId: string) => {
    await openNativeMarimoArtifact(artifactId, { restart: true });
  }, [openNativeMarimoArtifact]);

  async function generateDataNotebook() {
    const job = await api<Job>(`/api/projects/${project.id}/analysis-notebooks/data-understanding`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale })
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 15 * 60_000, label: "Data notebook job" });
    await openNotebookOrAskAgentToAuthor({
      completedJob,
      locale,
      projectName: project.name,
      notebookKind: "data understanding",
      onOpenNotebookArtifact: openNativeMarimoArtifact,
      onAskAgent
    });
    return completedJob;
  }

  async function generateModelNotebook(run: Run) {
    const job = await api<Job>(`/api/runs/${run.id}/analysis-notebook`, { method: "POST" });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 15 * 60_000, label: "Model notebook job" });
    await openNotebookOrAskAgentToAuthor({
      completedJob,
      locale,
      projectName: project.name,
      notebookKind: `model diagnostics for ${run.id}`,
      onOpenNotebookArtifact: openNativeMarimoArtifact,
      onAskAgent
    });
    return completedJob;
  }

  async function prepareResultNotebookEvidence() {
    const job = await api<Job>(`/api/projects/${project.id}/results/notebook-evidence`, { method: "POST" });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Result notebook evidence job" });
    await openNotebookOrAskAgentToAuthor({
      completedJob,
      locale,
      projectName: project.name,
      notebookKind: "result evidence",
      onOpenNotebookArtifact: openNativeMarimoArtifact,
      onAskAgent
    });
    return completedJob;
  }

  async function planNotebookExecution(item: NotebookIndexItem) {
    const job = await api<Job>(`/api/analysis-notebooks/${item.artifact_ids.notebook}/execution-plan`, {
      method: "POST"
    });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 5 * 60_000, label: "Notebook execution plan job" });
    const planArtifactId = completedJob.output.notebook_execution_plan_artifact_id;
    if (typeof planArtifactId === "string") {
      await loadPreview(planArtifactId);
    }
    return completedJob;
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
      notebook_evidence_svg: `${text.notebookEvidenceTitle} ${text.notebookMetricFigures}`,
      notebook_evidence_bundle: `${text.notebookEvidenceTitle} bundle`,
      notebook_figure_manifest: "Figure manifest",
      notebook_execution_plan: text.notebookRunnerRecordTitle,
      agent_task_contract: "Agent contract"
    };
    return labels[assetType] ?? assetType.replace(/_/g, " ");
  }

  const reviewEvidenceBundle = reviewNotebook
    ? latestArtifactForNotebook(reviewNotebook, ["notebook_evidence_bundle"])
    : null;
  const reviewEvidenceFigures = reviewNotebook ? artifactsForNotebook(reviewNotebook, ["notebook_evidence_svg"]) : [];
  const reviewSafetyArtifact = reviewNotebook
    ? latestArtifactForNotebook(reviewNotebook, [
        "notebook_figure_manifest",
        "notebook_execution_plan",
        "agent_task_contract"
      ])
    : null;
  const story = analysisStory?.story ?? null;
  const storyNotebook = reviewNotebook;
  const selectedNotebookArtifact = selectedNotebookArtifactId
    ? artifacts.find((artifact) => artifact.id === selectedNotebookArtifactId) ?? null
    : null;
  const nativeViewerArtifactId = selectedNotebookArtifactId ?? storyNotebook?.artifact_ids.notebook ?? null;
  const nativeViewerTitle =
    selectedNotebook?.title ??
    (selectedNotebookArtifact ? artifactDisplayTitle(selectedNotebookArtifact) : null) ??
    storyNotebook?.title ??
    story?.selected_source.title ??
    text.notebookNativeMarimoTitle;
  const storyReadOrder = selectedNotebookOverridesStory ? [] : story?.read_order ?? [];
  const manifestReadOrder = reviewNotebook?.quality_manifest?.read_order ?? [];
  const storyCards = selectedNotebookOverridesStory ? [] : story?.visual_story_cards ?? [];
  const manifestFindings = reviewNotebook?.quality_manifest?.key_findings ?? [];
  const storyCaveats = selectedNotebookOverridesStory ? [] : story?.caveats ?? [];
  const manifestLimitations = reviewNotebook?.quality_manifest?.limitations ?? [];
  const storyPrompts = selectedNotebookOverridesStory ? [] : story?.codex_prompts ?? [];
  const storyNotebookNeedsAttention = Boolean(storyNotebook && notebookNeedsAttention(storyNotebook));
  const hasReadableStoryEvidence = Boolean(storyNotebook && !storyNotebookNeedsAttention);
  const notebookFocusHeadline =
    (selectedNotebookOverridesStory ? reviewNotebook?.title : textField(story?.headline)) ??
    (reviewNotebook ? reviewNotebook.title : text.notebookCreateStoryFallbackTitle);
  const notebookFocusReason =
    (selectedNotebookOverridesStory ? reviewNotebook?.recommendation_reason : textField(story?.why_this_story)) ??
    (recommendedNotebookHasQualityIssue
      ? text.notebookModelDiagnosticsEmptyWarning
      : reviewNotebook
        ? reviewNotebook.recommendation_reason
        : text.notebookCreateStoryFallbackBody);
  const notebookFocusNext = storyNotebook
    ? text.notebookOpenMarimo
    : latestDataset
      ? text.notebookDataNotebook
      : text.focusUploadData;
  const autoPreviewedArtifactRef = React.useRef<string | null>(null);
  const prewarmedNativeMarimoArtifactsRef = React.useRef<Set<string>>(new Set());
  const handledPreviewRequestRef = React.useRef<number | null>(null);

  const prewarmNativeMarimoArtifact = React.useCallback((artifactId: string) => {
    const prewarmed = prewarmedNativeMarimoArtifactsRef.current;
    if (prewarmed.has(artifactId)) return;
    prewarmed.add(artifactId);
    void api<NativeMarimoSession>(`/api/analysis-notebooks/${artifactId}/marimo-session?wait_ready=false`, {
      method: "POST"
    }).catch(() => undefined);
  }, []);

  React.useEffect(() => {
    if (!storyNotebook || autoPreviewedArtifactRef.current === storyNotebook.artifact_ids.notebook) return;
    autoPreviewedArtifactRef.current = storyNotebook.artifact_ids.notebook;
    prewarmNativeMarimoArtifact(storyNotebook.artifact_ids.notebook);
  }, [prewarmNativeMarimoArtifact, storyNotebook]);

  React.useEffect(() => {
    const notebookArtifactIds = notebookItems
      .filter((item) => !notebookNeedsAttention(item))
      .map((item) => item.artifact_ids.notebook)
      .filter((artifactId) => artifactId.trim());
    for (const artifactId of notebookArtifactIds.slice(0, 3)) {
      prewarmNativeMarimoArtifact(artifactId);
    }
  }, [notebookItems, prewarmNativeMarimoArtifact]);

  React.useEffect(() => {
    if (!previewRequest || previewRequest.targetTab !== "Notebooks") return;
    if (handledPreviewRequestRef.current === previewRequest.nonce) return;
    handledPreviewRequestRef.current = previewRequest.nonce;
    const item =
      notebookItems.find(
        (candidate) =>
          candidate.notebook_artifact_id === previewRequest.artifactId ||
          candidate.artifact_ids.notebook === previewRequest.artifactId
      ) ?? notebookItems.find((candidate) => notebookItemReferencesArtifact(candidate, previewRequest.artifactId));
    if (item) {
      void openNativeMarimo(item);
    } else {
      void openNativeMarimoArtifact(previewRequest.artifactId);
    }
  }, [notebookItems, openNativeMarimo, openNativeMarimoArtifact, previewRequest]);

  async function askNotebookGuide(message: string) {
    const trimmed = message.trim();
    if (!trimmed) return;
    const storySource = story?.selected_source;
    const scopedSource = storySource?.artifact_id
      ? `[analysis-story:${storySource.source_type}:${storySource.artifact_id}]`
      : reviewNotebook
        ? `[notebook:${reviewNotebook.notebook_artifact_id}]`
        : "[analysis-story]";
    const instruction =
      "Reply as an interactive analysis guide. Use the provided notebook or story context, decide whether the user needs an explanation, a deeper analysis proposal, or a runner handoff, and explain the next useful move in human language.";
    setGuideBusy(true);
    try {
      const response = await onAskAgent(`${scopedSource} ${trimmed}. ${instruction}`);
      if (response && typeof response.assistant_message === "string") {
        setGuideResponse(response.assistant_message);
      }
    } finally {
      setGuideBusy(false);
    }
  }

  return (
    <div className="stack notebook-workbench">
      <section id="notebook-focus" className="notebook-focus-panel" aria-label={text.focusNotebooks}>
        <div className="notebook-focus-copy">
          <div className="eyebrow">{text.notebookFocusEyebrow}</div>
          <h2>{notebookFocusHeadline}</h2>
          <p>{notebookFocusReason}</p>
          <div className="badge-row">
            <span className={storyNotebookNeedsAttention ? "badge risk" : story ? "badge" : "badge muted"}>
              {storyNotebookNeedsAttention ? text.notebookNativeMarimoRuntimeError : story ? text.notebookStoryReady : text.notebookStoryPending}
            </span>
            <span className={hasReadableStoryEvidence ? "badge" : "badge risk"}>
              {hasReadableStoryEvidence ? text.notebookReadableEvidence : text.notebookCaptureNeeded}
            </span>
            {recommendedNotebookHasQualityIssue ? <span className="badge warning">{text.notebookEmptyDiagnosticsSkipped}</span> : null}
          </div>
        </div>
        <div className="notebook-focus-aside">
          <Metric label={text.notebookMetricNotebooks} value={notebookIndex?.counts.total ?? 0} />
          <Metric label={text.notebookMetricCaptured} value={notebookIndex?.counts.with_native_source ?? 0} />
          <Metric label={text.notebookMetricFigures} value={String(notebookFigureCount)} />
          <Metric label={text.notebookMetricRuns} value={runs.length} />
          <div className="notebook-focus-action">
            <span>{text.notebookMetricNext}</span>
            <strong>{notebookFocusNext}</strong>
            <button
              className="secondary-button"
              disabled={busy || (!storyNotebook && latestDataset === null) || Boolean(storyNotebook && nativeMarimoLoadingId === storyNotebook.artifact_ids.notebook)}
              onClick={() => {
                if (storyNotebook) {
                  void openNativeMarimo(storyNotebook);
                } else if (latestDataset) {
                  void runAction(generateDataNotebook);
                }
              }}
            >
              {(storyNotebook && nativeMarimoLoadingId === storyNotebook.artifact_ids.notebook) || busy ? (
                <Loader2 className="spin" size={16} />
              ) : storyNotebook ? (
                <BookOpen size={16} />
              ) : (
                <BookOpen size={16} />
              )}
              {storyNotebook ? text.notebookOpenMarimo : text.notebookDataNotebook}
            </button>
            <button
              className="secondary-button"
              disabled={busy || latestRun === null}
              onClick={() => void runAction(prepareResultNotebookEvidence)}
            >
              {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
              {text.notebookResultEvidence}
            </button>
          </div>
        </div>
      </section>
      <section id="notebook-native-marimo-top" className="analysis-story-preview">
        <div className="analysis-story-preview-head">
          <div>
            <div className="eyebrow">{text.notebookNativeMarimoTitle}</div>
            <h3>{nativeViewerTitle}</h3>
          </div>
          {nativeViewerArtifactId ? (
            <a className="icon-link" href={`${apiBase}/api/artifacts/${nativeViewerArtifactId}/download`} title={text.notebookDownloadCurrentStory}>
              <Download size={16} />
            </a>
          ) : null}
        </div>
        {nativeMarimoError ? (
          <div className="banner danger">
            <strong>{text.notebookNativeMarimoError}</strong>
            <span>{nativeMarimoError}</span>
          </div>
        ) : null}
        <div className={`native-marimo-stage${nativeMarimoLoadingId ? " loading" : ""}`}>
          {nativeMarimoSession ? (
            <NativeMarimoFrame session={nativeMarimoSession} onRestart={restartNativeMarimoArtifact} />
          ) : nativeMarimoLoadingId ? (
            <div className="native-marimo-frame-shell native-marimo-placeholder-shell">
              <NativeMarimoLoadingPanel />
            </div>
          ) : (
            <EmptyInline text={text.notebookNativeMarimoEmpty} />
          )}
          {nativeMarimoSession && nativeMarimoLoadingId ? (
            <div className="native-marimo-stage-overlay">
              <NativeMarimoLoadingPanel />
            </div>
          ) : null}
        </div>
      </section>
      <Panel id="analysis-story" title={text.notebookAnalysisStoryTitle} icon={<BarChart3 size={18} />}>
        {story || reviewNotebook ? (
          <div className="analysis-story-surface">
            <section className="analysis-story-hero">
              <div className="analysis-story-copy">
                <div className="eyebrow">{text.notebookReadThisNow}</div>
                <h3>{selectedNotebookOverridesStory ? reviewNotebook?.title : story?.headline ?? reviewNotebook?.title}</h3>
                <p>{selectedNotebookOverridesStory ? reviewNotebook?.recommendation_reason : story?.why_this_story || story?.deck || reviewNotebook?.recommendation_reason}</p>
                {recommendedNotebookHasQualityIssue ? (
                  <div className="banner warning compact">
                    {text.notebookModelDiagnosticsEmptyWarning}
                  </div>
                ) : null}
                <div className="badge-row">
                  <span className="badge">{notebookKindLabel(selectedNotebookOverridesStory ? reviewNotebook?.notebook_kind ?? "notebook" : story?.source_type ?? reviewNotebook?.notebook_kind ?? "notebook", text)}</span>
                  <span className="badge muted">{selectedNotebookOverridesStory ? reviewNotebook?.title : story?.selected_source.title ?? reviewNotebook?.title}</span>
                  {!selectedNotebookOverridesStory && story?.selected_source.status ? (
                    <span className={decisionReportStatusClass(story.selected_source.status)}>
                      {notebookReadinessText(story.selected_source.status, text)}
                    </span>
                  ) : null}
                  <span className={hasReadableStoryEvidence ? "badge" : "badge risk"}>
                    {hasReadableStoryEvidence ? text.notebookReadableEvidence : storyNotebookNeedsAttention ? text.notebookNativeMarimoRuntimeError : text.notebookNeedsCapture}
                  </span>
                </div>
              </div>
              <div className="analysis-story-actions">
                <button
                  className="primary-button"
                  disabled={!storyNotebook || nativeMarimoLoadingId === storyNotebook.artifact_ids.notebook}
                  onClick={() => {
                    if (storyNotebook) void openNativeMarimo(storyNotebook);
                  }}
                >
                  {storyNotebook && nativeMarimoLoadingId === storyNotebook.artifact_ids.notebook ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <BookOpen size={16} />
                  )}
                  {text.notebookOpenMarimo}
                </button>
                <button className="secondary-button" disabled={busy || latestDataset === null} onClick={() => void runAction(generateDataNotebook)}>
                  {busy ? <Loader2 className="spin" size={16} /> : <BookOpen size={16} />}
                  {text.notebookDataNotebook}
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => void runAction(prepareResultNotebookEvidence)}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  {text.notebookResultEvidence}
                </button>
              </div>
            </section>
            <div className="analysis-story-grid">
              <section className="analysis-story-section">
                <div className="mini-card-title">{text.notebookReadOrderTitle}</div>
                {storyReadOrder.length || manifestReadOrder.length ? (
                  <div className="analysis-read-list">
                    {storyReadOrder.length ? storyReadOrder.map((item, index) => (
                      <div className="analysis-read-row" key={`${textField(item.title) ?? "read"}-${index}`}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{textField(item.title) ?? text.notebookReviewItemFallback}</strong>
                          <p>{textField(item.why) ?? ""}</p>
                          {textField(item.artifact_hint) ? <small>{textField(item.artifact_hint)}</small> : null}
                        </div>
                      </div>
                    )) : manifestReadOrder.map((item, index) => (
                      <div className="analysis-read-row" key={`${textField(item.label) ?? textField(item.anchor) ?? "read"}-${index}`}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{textField(item.label) ?? textField(item.anchor) ?? text.notebookReviewItemFallback}</strong>
                          {textField(item.detail) ? <p>{textField(item.detail)}</p> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyInline text={text.notebookReadOrderEmpty} />
                )}
              </section>

              <section className="analysis-story-section">
                <div className="mini-card-title">{text.notebookWhatMattersTitle}</div>
                {storyCards.length || manifestFindings.length ? (
                  <div className="analysis-story-card-grid">
                    {storyCards.length ? storyCards.map((card, index) => (
                      <div className="analysis-story-card" key={`${textField(card.title) ?? "card"}-${index}`}>
                        <div className="badge-row">
                          <span className={decisionReportStatusClass(textField(card.status) ?? "review")}>
                            {notebookReadinessText(textField(card.status) ?? "review", text)}
                          </span>
                        </div>
                        <strong>{textField(card.title) ?? text.notebookStoryCardFallback}</strong>
                        <p>{textField(card.why_read) ?? ""}</p>
                        {textField(card.signal) ? <small>{textField(card.signal)}</small> : null}
                      </div>
                    )) : manifestFindings.map((finding, index) => (
                      <div className="analysis-story-card" key={`manifest-finding-${index}`}>
                        <strong>{text.memoryKindFinding} {index + 1}</strong>
                        <p>{finding}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyInline text={text.notebookStoryCardsEmpty} />
                )}
              </section>
            </div>

            <div className="analysis-story-grid compact">
              <section className="analysis-story-section">
                <div className="mini-card-title">{text.notebookCaveatsTitle}</div>
                {storyCaveats.length || manifestLimitations.length ? (
                  <ul className="analysis-plain-list">
                    {[...storyCaveats, ...manifestLimitations].filter((item, index, items) => items.indexOf(item) === index).slice(0, 7).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <EmptyInline text={text.notebookNoCaveat} />
                )}
              </section>
              <section className="analysis-story-section">
                <div className="mini-card-title">{text.notebookAskCodexNextTitle}</div>
                <div className="analysis-prompt-list">
                  {(storyPrompts.length
                    ? storyPrompts
                    : [
                        text.notebookPromptReadFirst,
                        text.notebookPromptNextAction,
                        text.notebookPromptWeakEvidence
                      ]
                  ).slice(0, 4).map((prompt) => (
                    <button
                      className="secondary-button"
                      disabled={busy || guideBusy}
                      key={prompt}
                      title={text.notebookAskAnalysisGuide}
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
                    placeholder={text.notebookGuidePlaceholder}
                  />
                  <button className="icon-button" disabled={busy || guideBusy || !guideDraft.trim()} title={text.notebookAskAnalysisGuide}>
                    {guideBusy ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
                  </button>
                </form>
                {guideResponse ? <div className="notebook-guide-response">{guideResponse}</div> : null}
              </section>
            </div>

            <details className="artifact-shelf analysis-supporting-shelf">
              <summary>{text.notebookSupportingSummary}</summary>
              <div className="analysis-supporting-grid">
                <div className="metric-grid compact">
                  <Metric label={text.notebookMetricNotebooks} value={notebookIndex?.counts.total ?? 0} />
                  <Metric label={text.notebookMetricCaptured} value={notebookIndex?.counts.with_native_source ?? 0} />
                  <Metric label={text.notebookMetricFigures} value={String(notebookFigureCount || reviewEvidenceFigures.length)} />
                </div>

                {reviewNotebook ? (
                  <div className="card-grid notebook-evidence-grid">
                    <div className="mini-card notebook-evidence-card primary">
                      <div className="mini-card-title">{text.notebookEvidenceTitle}</div>
                      <p>{text.notebookEvidenceDescription}</p>
                      <div className="badge-row">
                        <span className={reviewNotebook ? "badge" : "badge risk"}>
                          {reviewNotebook ? text.notebookReady : text.notebookCaptureNeeded}
                        </span>
                        {reviewEvidenceBundle ? <span className="badge muted">{text.notebookBundleSaved}</span> : null}
                      </div>
                        <div className="row-actions">
                          <button
                            className="secondary-button"
                            disabled={!reviewNotebook || nativeMarimoLoadingId === reviewNotebook.artifact_ids.notebook}
                            onClick={() => {
                              if (reviewNotebook) void openNativeMarimo(reviewNotebook);
                            }}
                          >
                            {reviewNotebook && nativeMarimoLoadingId === reviewNotebook.artifact_ids.notebook ? (
                              <Loader2 className="spin" size={16} />
                            ) : (
                              <BookOpen size={16} />
                            )}
                            {text.notebookOpen}
                          </button>
                          <button
                            className="secondary-button"
                            disabled={busy || latestRun === null}
                          onClick={() => void runAction(prepareResultNotebookEvidence)}
                        >
                          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                          {text.notebookResult}
                        </button>
                      </div>
                    </div>
                    <div className="mini-card notebook-evidence-card">
                      <div className="mini-card-title">{text.notebookRunnerRecordTitle}</div>
                      <p>{text.notebookRunnerRecordDescription}</p>
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
                          {text.notebookInspect}
                        </button>
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void runAction(() => planNotebookExecution(reviewNotebook))}
                        >
                          {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                          {text.notebookPlan}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : null}

                {notebookItems.length ? (
                  <Table
                    headers={[text.notebookTableNotebook, text.notebookTableState, text.notebookTableActions]}
                    rows={notebookItems.slice(0, 8).map((item) => [
                      <div className="cell-stack" key={`${item.notebook_artifact_id}-title`}>
                        <span>{item.title}</span>
                        <small>
                          {notebookKindLabel(item.notebook_kind, text)} | {notebookSourceLabel(item, text)}
                        </small>
                      </div>,
                      <div className="badge-row" key={`${item.notebook_artifact_id}-state`}>
                        <span className="badge muted">{notebookCoverageLabel(item, text)}</span>
                        <span className={notebookReadinessClass(item)}>{notebookReadinessLabel(item, text)}</span>
                        {item.notebook_artifact_id === reviewNotebook?.notebook_artifact_id ? <span className="badge">{text.notebookCurrent}</span> : null}
                      </div>,
                      <div className="row-actions" key={`${item.notebook_artifact_id}-actions`}>
                        <button
                          className="icon-button"
                          disabled={nativeMarimoLoadingId === item.artifact_ids.notebook}
                          onClick={() => void openNativeMarimo(item)}
                          title={text.notebookOpenMarimo}
                        >
                          {nativeMarimoLoadingId === item.artifact_ids.notebook ? <Loader2 className="spin" size={16} /> : <BookOpen size={16} />}
                        </button>
                          <a className="icon-link" href={`${apiBase}/api/artifacts/${item.artifact_ids.notebook}/download`} title={text.notebookDownloadMarimoSource}>
                          <Download size={16} />
                        </a>
                      </div>
                    ])}
                  />
                ) : (
                  <EmptyInline text={text.notebookHistoryEmpty} />
                )}

                {reviewArtifacts.length ? (
                  <Table
                    headers={[text.notebookArtifactTableArtifact, text.notebookArtifactTableStatus, text.notebookTableCreated, text.notebookTableActions]}
                    rows={reviewArtifacts.slice(0, 12).map((artifact) => [
                      <div className="cell-stack" key={`${artifact.id}-label`}>
                        <span>{notebookArtifactDisplayName(artifact.asset_type)}</span>
                        <small>{String(artifact.metadata.figure_id ?? artifact.metadata.notebook_kind ?? artifact.id)}</small>
                      </div>,
                      String(artifact.metadata.execution_status ?? "ready"),
                      formatDate(artifact.created_at),
                      <div className="row-actions" key={artifact.id}>
                        <button
                          className="icon-button"
                          disabled={previewLoadingId === artifact.id}
                          onClick={() => void loadPreview(artifact.id)}
                          title={text.notebookPreviewArtifactTitle}
                        >
                          {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                        </button>
                        <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.notebookDownloadArtifactTitle}>
                          <Download size={16} />
                        </a>
                      </div>
                    ])}
                  />
                ) : null}

                {previewError || preview?.preview_available || previewLoadingId ? (
                  <section className="notebook-supporting-preview">
                    <div className="mini-card-title">{text.notebookPreviewArtifactTitle}</div>
                    {previewError ? <div className="banner danger">{previewError}</div> : null}
                    {preview?.preview_available ? (
                      isVisualArtifactPreview(preview) ? (
                        <VisualArtifactPreview preview={preview} />
                      ) : isHtmlArtifactPreview(preview) ? (
                        <HtmlArtifactPreview preview={preview} />
                      ) : (
                        <TranslatablePreview preview={preview} />
                      )
                    ) : previewLoadingId ? (
                      <div className="banner muted">
                        <Loader2 className="spin" size={16} />
                        {text.artifactPreviewLoadingTitle}
                      </div>
                    ) : null}
                  </section>
                ) : null}
              </div>
            </details>
          </div>
        ) : (
          <div className="notebook-start-card">
            <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="notebook-start-mascot" />
            <div className="notebook-start-copy">
              <div className="eyebrow">{text.notebookStartHere}</div>
              <h3>{analysisStory?.empty_state?.headline ?? text.notebookCreateStoryFallbackTitle}</h3>
              <p>
                {analysisStory?.empty_state?.reason ??
                  text.notebookCreateStoryFallbackBody}
              </p>
              <div className="row-actions">
                <button
                  className="primary-button"
                  disabled={busy || latestDataset === null}
                  onClick={() => {
                    void runAction(generateDataNotebook);
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BookOpen size={16} />}
                  {text.notebookDataNotebook}
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => {
                    if (latestRun) void runAction(() => generateModelNotebook(latestRun));
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
                  {text.notebookModelNotebook}
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => void runAction(prepareResultNotebookEvidence)}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  {text.notebookResultEvidence}
                </button>
              </div>
            </div>
          </div>
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
  ideas,
  insights,
  busy,
  locale,
  text,
  runAction,
  onAskAgent,
  onOpenNotebookArtifact
}: {
  project: Project;
  reports: Report[];
  decisionReport: DecisionReportCurrent | null;
  artifacts: Artifact[];
  visualizations: VisualizationSpec[];
  notebookIndex: NotebookIndex | null;
  ideas: Idea[];
  insights: Insight[];
  busy: boolean;
  locale: string;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (message: string) => Promise<AgentChatResponse | void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
}) {
  const [reportPreview, setReportPreview] = React.useState<ArtifactPreview | null>(null);
  const [reportPreviewSource, setReportPreviewSource] = React.useState<{ type: "report" | "artifact"; id: string } | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const decisionArtifacts = artifacts.filter((artifact) =>
    ["decision_dashboard", "decision_report"].includes(artifact.asset_type)
  );
  const researchFindingArtifacts = artifacts.filter((artifact) => artifact.asset_type === "research_findings_report");
  const analysisNotebookArtifacts = artifacts.filter((artifact) =>
    [
      "analysis_notebook",
      "marimo_notebook",
      "notebook_run_manifest",
      "notebook_report",
      "notebook_execution_plan",
      "notebook_figure_manifest",
      "notebook_evidence_bundle",
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
  const notebookItems = React.useMemo(() => preferredNotebookItems(notebookIndex), [notebookIndex]);
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
    (decisionReport?.available ? text.decisionReportCurrentText : text.decisionReportMissingHeadline);
  const reportStatusTone: EvidenceReaderMetric["tone"] =
    readinessStatus === "ready" || readinessStatus === "decision_ready"
      ? "ready"
      : readinessStatus === "blocked" || readinessStatus === "missing"
        ? "risk"
        : "warning";
  const reportReaderBody = text.decisionReportBody;
  const reportNextLabel = currentDecisionReportId ? text.decisionReportNextOpen : text.decisionReportNextGenerate;
  const reportNextDetail = currentDecisionReportId
    ? text.decisionReportNextOpenDetail
    : text.decisionReportNextGenerateDetail;
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
      focusNavigationAnchor("decision-report-preview");
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
      focusNavigationAnchor("decision-report-preview");
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
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 5 * 60_000, label: "Notebook execution plan job" });
    const planArtifactId = completedJob.output.notebook_execution_plan_artifact_id;
    if (typeof planArtifactId === "string") {
      await loadArtifactPreview(planArtifactId);
    }
    return completedJob;
  }

  async function generateDecisionReport() {
    const job = await api<Job>(`/api/projects/${project.id}/decision-report/generate`, { method: "POST" });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Decision report job" });
    const reportId = textField(completedJob.output.report_id);
    if (reportId) {
      autoPreviewedReportRef.current = reportId;
      await loadReportPreview(reportId);
    }
    return completedJob;
  }

  const readingQueueItems = React.useMemo(() => {
    const items: Array<{
      id: string;
      kind: string;
      title: string;
      detail: string;
      createdAt: string;
      actionLabel: string;
      icon: React.ReactNode;
      open: () => void;
    }> = [];
    if (currentDecisionReportId) {
      items.push({
        id: `decision:${currentDecisionReportId}`,
        kind: text.insightDeliveryDecision,
        title: textField(decisionReport?.report?.title) ?? text.decisionReportCurrentText,
        detail: textField(decisionReport?.report?.summary) ?? text.decisionReportNextOpenDetail,
        createdAt: textField(decisionReport?.report?.created_at) ?? "",
        actionLabel: text.insightDeliveryOpenReport,
        icon: <FileText size={18} />,
        open: () => void loadReportPreview(currentDecisionReportId)
      });
    }
    for (const report of reports.slice(0, 8)) {
      if (report.id === currentDecisionReportId) continue;
      items.push({
        id: `report:${report.id}`,
        kind: text.insightDeliveryReport,
        title: report.title,
        detail: report.summary || report.report_type,
        createdAt: report.created_at,
        actionLabel: text.insightDeliveryOpenReport,
        icon: <FileText size={18} />,
        open: () => void loadReportPreview(report.id)
      });
    }
    for (const artifact of researchFindingArtifacts.slice(0, 6)) {
      items.push({
        id: `research:${artifact.id}`,
        kind: text.insightDeliveryResearch,
        title: textField(artifact.metadata.topic) ?? artifactDisplayTitle(artifact),
        detail: [
          artifact.metadata.source_count != null ? `${String(artifact.metadata.source_count)} source` : null,
          artifact.metadata.finding_count != null ? `${String(artifact.metadata.finding_count)} finding` : null
        ]
          .filter(Boolean)
          .join(" / "),
        createdAt: artifact.created_at,
        actionLabel: text.insightDeliveryOpenArtifact,
        icon: <Search size={18} />,
        open: () => void loadArtifactPreview(artifact.id)
      });
    }
    for (const item of notebookItems.slice(0, 6)) {
      items.push({
        id: `notebook:${item.notebook_artifact_id}`,
        kind: text.insightDeliveryNotebook,
        title: item.title,
        detail: item.recommendation_reason || notebookCoverageLabel(item),
        createdAt: item.created_at,
        actionLabel: text.insightDeliveryOpenNotebook,
        icon: <BookOpen size={18} />,
        open: () => onOpenNotebookArtifact(item.artifact_ids.notebook)
      });
    }
    const seen = new Set<string>();
    return items
      .filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      })
      .sort((left, right) => {
        const leftTime = Date.parse(left.createdAt || "");
        const rightTime = Date.parse(right.createdAt || "");
        return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
      })
      .slice(0, 8);
  }, [
    currentDecisionReportId,
    decisionReport,
    reports,
    researchFindingArtifacts,
    notebookItems,
    text,
    onOpenNotebookArtifact
  ]);

  return (
    <div className="stack">
      <Panel title={text.insightDeliveryTitle} icon={<Lightbulb size={18} />}>
        <div className="insight-delivery-head">
          <p>{text.insightDeliveryBody}</p>
        </div>
        {readingQueueItems.length ? (
          <div className="insight-delivery-grid">
            {readingQueueItems.map((item) => (
              <button className="insight-delivery-card" key={item.id} onClick={item.open} type="button">
                <span className="insight-delivery-icon">{item.icon}</span>
                <span className="insight-delivery-copy">
                  <span className="badge muted">{item.kind}</span>
                  <strong>{item.title}</strong>
                  <small>{item.detail || text.insightNoSummary}</small>
                </span>
                <span className="secondary-button">{item.actionLabel}</span>
              </button>
            ))}
          </div>
        ) : (
          <EmptyInline text={text.insightDeliveryEmpty} />
        )}
      </Panel>
      <FocusedEvidenceReader
        id="decision-report"
        eyebrow={text.decisionReportReader}
        title={readinessHeadline}
        body={reportReaderBody}
        status={displayStatusLabel(readinessStatus, text)}
        statusTone={reportStatusTone}
        metrics={[
          { label: text.decisionMetricReady, value: String(coverage.ready_count ?? 0), tone: "ready" },
          { label: text.decisionMetricNeedsAttention, value: String(coverage.attention_count ?? 0), tone: Number(coverage.attention_count ?? 0) ? "warning" : "muted" },
          { label: text.decisionMetricMissing, value: String(coverage.missing_count ?? 0), tone: Number(coverage.missing_count ?? 0) ? "risk" : "muted" },
          { label: text.decisionMetricSources, value: String(currentDecisionBundle?.source_assets.length ?? 0), tone: currentDecisionBundle?.source_assets.length ? "ready" : "muted" }
        ]}
        nextEyebrow={text.evidenceReaderNext}
        nextLabel={reportNextLabel}
        nextDetail={reportNextDetail}
        nextButtonLabel={currentDecisionReportId ? text.decisionReportOpenCurrent : text.decisionReportGenerateButton}
        nextDisabled={busy || Boolean(currentDecisionReportId && previewLoadingId === currentDecisionReportId)}
        onNext={() => {
          if (currentDecisionReportId) {
            void loadReportPreview(currentDecisionReportId);
          } else {
            void runAction(generateDecisionReport);
          }
        }}
        previewEyebrow={text.evidenceReaderReadFirst}
        previewTitle={currentDecisionReportId ? text.decisionReportCurrentText : text.decisionReportNoneYet}
        preview={reportPreview}
        previewError={previewError}
        previewLoading={Boolean(previewLoadingId)}
        previewLoadingLabel={text.evidenceReaderLoading}
        previewEmpty={text.decisionReportEmpty}
        previewSourceType={reportPreviewSource?.type ?? "report"}
        previewSourceId={reportPreviewSource?.id ?? currentDecisionReportId ?? undefined}
        boundary={text.decisionReportBoundary}
      />
      {currentDecisionBundle ? (
        <Panel title={text.insightReadThisFirstTitle} icon={<FileText size={18} />}>
          <div className="decision-read-grid">
            <div className="decision-read-column">
              <h3>{text.insightProvenTitle}</h3>
              {provenEvidence.length ? (
                provenEvidence.map((row) => (
                  <div className="decision-read-item" key={`proven-${textField(row.area) ?? JSON.stringify(row)}`}>
                    <strong>{textField(row.area) ?? "Evidence"}</strong>
                    <p>{textField(row.summary) ?? text.insightNoSummary}</p>
                  </div>
                ))
              ) : (
                <EmptyInline text={text.insightNoProven} />
              )}
            </div>
            <div className="decision-read-column">
              <h3>{text.insightAttentionTitle}</h3>
              {attentionEvidence.length ? (
                attentionEvidence.map((row) => (
                  <div className="decision-read-item" key={`attention-${textField(row.area) ?? JSON.stringify(row)}`}>
                    <strong>{textField(row.area) ?? "Evidence"}</strong>
                    <p>{textField(row.summary) ?? text.insightNoSummary}</p>
                  </div>
                ))
              ) : (
                <EmptyInline text={text.insightNoAttention} />
              )}
            </div>
          </div>
        </Panel>
      ) : null}
      {nextActions.length ? (
        <Panel title={text.insightNextActionsTitle} icon={<ListChecks size={18} />}>
          <div className="decision-next-list">
            {nextActions.slice(0, 5).map((item, index) => (
              <div className="decision-next-item" key={`${textField(item.title) ?? "action"}-${index}`}>
                <span>{String(item.priority ?? index + 1)}</span>
                <div>
                  <strong>{textField(item.title) ?? text.insightReviewNextAction}</strong>
                  <p>{textField(item.reason) ?? text.insightNoSummary}</p>
                  <small>{textField(item.target_tab) ?? "Reports"}</small>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
      <Panel title={text.evidenceCoverageTitle} icon={<ListChecks size={18} />}>
        {evidenceMap.length ? (
          <div className="decision-evidence-grid">
            {evidenceMap.map((row) => (
              <div className="decision-evidence-row" key={textField(row.area) ?? JSON.stringify(row)}>
                <div>
                  <strong>{textField(row.area) ?? "Evidence"}</strong>
                  <p>{textField(row.summary) ?? text.insightNoSummary}</p>
                </div>
                <span className={decisionReportStatusClass(textField(row.status) ?? "missing")}>
                  {(textField(row.status) ?? "missing").replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text={text.evidenceCoverageEmpty} />
        )}
      </Panel>
      <details className="report-supporting-details">
        <summary>
          <span>{text.supportingReportShelves}</span>
          <small>{text.supportingReportShelvesHint}</small>
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
          {text.draftReport}
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() => api(`/api/projects/${project.id}/visualizations/generate`, { method: "POST" }))
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
          {text.visualizationDashboard}
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
                const job = await api<Job>(`/api/projects/${project.id}/analysis-notebooks/data-understanding`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ locale })
                });
                const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 15 * 60_000, label: "Data notebook job" });
                await openNotebookOrAskAgentToAuthor({
                  completedJob,
                  locale,
                  projectName: project.name,
                  notebookKind: "data understanding",
                  onOpenNotebookArtifact,
                  onAskAgent
                });
                return completedJob;
              })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
          {text.prepareNotebookContext}
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(() => api(`/api/projects/${project.id}/insights/generate`, { method: "POST" }))
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Lightbulb size={16} />}
          {text.generateInsights}
        </button>
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/decision-dashboard/generate`, { method: "POST" });
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Decision dashboard job" });
              const reportId = completedJob.output.report_id;
              if (typeof reportId === "string") {
                await loadReportPreview(reportId);
              }
              return completedJob;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
          {text.decisionDashboard}
        </button>
        <button
          className="secondary-button"
          disabled={busy || guidedJourneySnapshots.length < 2}
          onClick={() =>
            void runAction(async () => {
              const job = await api<Job>(`/api/projects/${project.id}/guidance/snapshots/compare`, { method: "POST" });
              const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Guidance snapshot comparison job" });
              const reportId = completedJob.output.guided_journey_comparison_report_id;
              if (typeof reportId === "string") {
                await loadReportPreview(reportId);
              }
              return completedJob;
            })
          }
        >
          {busy ? <Loader2 className="spin" size={16} /> : <GitBranch size={16} />}
          {text.compareJourney}
        </button>
        </div>
      <Panel id="notebook-center" title={text.notebookCenterTitle} icon={<BarChart3 size={18} />}>
        {notebookIndex && notebookIndex.counts.total > 0 ? (
          <div className="stack">
            {recommendedNotebook ? (
              <div className="focus-card">
                <div>
                  <div className="eyebrow">{text.recommendedNotebook}</div>
                  <h3>{recommendedNotebook.title}</h3>
                  <p>{recommendedNotebook.recommendation_reason}</p>
                  <div className="badge-row">
                    <span className="badge">{recommendedNotebook.notebook_kind.replace(/_/g, " ")}</span>
                    <span className="badge muted">{notebookCoverageLabel(recommendedNotebook)}</span>
                    <span className="badge muted">{notebookSourceLabel(recommendedNotebook, text)}</span>
                  </div>
                </div>
                <div className="row-actions">
                  <button
                    className="secondary-button"
                    onClick={() => onOpenNotebookArtifact(recommendedNotebook.artifact_ids.notebook)}
                  >
                    <BookOpen size={16} />
                    {text.notebookOpenMarimo}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void runAction(() => planNotebookExecution(recommendedNotebook))}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                    {text.notebookPlanExecution}
                  </button>
                  <a
                    className="icon-link"
                    href={`${apiBase}/api/artifacts/${recommendedNotebook.artifact_ids.notebook}/download`}
                    title={text.notebookDownloadMarimoSource}
                  >
                    <Download size={16} />
                  </a>
                </div>
              </div>
            ) : null}
            <div className="metric-grid compact">
              <Metric label={text.notebookMetricNotebooks} value={notebookIndex.counts.total} />
              <Metric label={text.notebookMetricReports} value={notebookIndex.counts.with_report} />
              <Metric label={text.notebookMetricCaptured} value={notebookIndex.counts.with_native_source} />
            </div>
            <Table
              headers={[text.notebookTableNotebook, text.notebookTableSource, text.notebookTableCoverage, text.notebookTableCreated, text.notebookTableActions]}
              rows={notebookItems.slice(0, 8).map((item) => [
                <div className="cell-stack" key={`${item.notebook_artifact_id}-title`}>
                  <span>{item.title}</span>
                  <small>
                    {item.notebook_kind.replace(/_/g, " ")} · {notebookReadinessLabel(item, text)}
                  </small>
                </div>,
                notebookSourceLabel(item),
                notebookCoverageLabel(item),
                formatDate(item.created_at),
                <div className="row-actions" key={`${item.notebook_artifact_id}-actions`}>
                  <button
                    className={`icon-button ${notebookNeedsAttention(item) ? "danger" : ""}`}
                    onClick={() => onOpenNotebookArtifact(item.artifact_ids.notebook)}
                    title={notebookNeedsAttention(item) ? text.notebookNativeMarimoRuntimeError : text.notebookOpenMarimo}
                  >
                    {notebookNeedsAttention(item) ? <AlertTriangle size={16} /> : <BookOpen size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => planNotebookExecution(item))}
                    title={text.notebookPlanExecution}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                  </button>
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${item.artifact_ids.notebook}/download`} title={text.notebookDownloadMarimoSource}>
                    <Download size={16} />
                  </a>
                </div>
              ])}
            />
          </div>
        ) : (
          <EmptyInline text={text.notebookEmpty} />
        )}
      </Panel>
      <Panel id="ideas" title={text.reportShelfIdeasTitle} icon={<Lightbulb size={18} />}>
        {ideas.length ? (
          <div className="card-grid">
            {ideas.map((idea) => (
              <div key={idea.id} className="mini-card insight-card">
                <div className="mini-card-title">{idea.title}</div>
                <div className="badge-row">
                  <span className="badge">{idea.status}</span>
                  <span className="badge muted">{idea.approach_type.replace(/_/g, " ")}</span>
                  <span className="badge risk">{idea.risk_level.replace(/_/g, " ")}</span>
                  <span className="badge muted">priority {idea.priority}</span>
                </div>
                <p>{idea.hypothesis}</p>
                <dl className="facts">
                  <div>
                    <dt>Confidence</dt>
                    <dd>{Math.round(idea.confidence * 100)}%</dd>
                  </div>
                  <div>
                    <dt>Feature strategy</dt>
                    <dd>{compactRecordField(idea.feature_strategy)}</dd>
                  </div>
                  <div>
                    <dt>Modeling strategy</dt>
                    <dd>{compactRecordField(idea.modeling_strategy)}</dd>
                  </div>
                  <div>
                    <dt>Artifact</dt>
                    <dd>{idea.artifact_id ?? "-"}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text={text.reportShelfIdeasEmpty} />
        )}
      </Panel>
      <Panel id="insights" title={text.reportShelfInsightsTitle} icon={<Lightbulb size={18} />}>
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
          <EmptyInline text={text.reportShelfInsightsEmpty} />
        )}
      </Panel>
      <Panel id="research-findings" title={text.reportShelfResearchTitle} icon={<Search size={18} />}>
        {researchFindingArtifacts.length ? (
          <Table
            headers={[
              text.tableTopic,
              text.tableSources,
              text.tableFindings,
              text.tableStatus,
              text.tableCreated,
              text.tableActions
            ]}
            rows={researchFindingArtifacts.map((artifact) => [
              textField(artifact.metadata.topic) ?? artifact.name,
              String(artifact.metadata.source_count ?? "-"),
              String(artifact.metadata.finding_count ?? "-"),
              artifact.metadata.no_findings === true ? text.reportShelfResearchNoFindings : text.reportShelfResearchReady,
              formatDate(artifact.created_at),
              <div className="row-actions" key={artifact.id}>
                <button
                  className="icon-button"
                  disabled={previewLoadingId === artifact.id}
                  onClick={() => void loadArtifactPreview(artifact.id)}
                  title={text.memoryOpenResearch}
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.downloadReport}>
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.reportShelfResearchEmpty} />
        )}
      </Panel>
      <Panel id="reports" title={text.reportShelfReportsTitle} icon={<FileText size={18} />}>
        {reports.length ? (
          <Table
            headers={[text.tableTitle, text.tableType, text.tableStatus, text.tableArtifact, text.tableCreated, text.tableActions]}
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
                  title={text.previewReport}
                >
                  {previewLoadingId === report.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/reports/${report.id}/download`} title={text.downloadReport}>
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.reportShelfReportsEmpty} />
        )}
      </Panel>
      <Panel title={text.reportShelfAnalysisNotebooksTitle} icon={<BarChart3 size={18} />}>
        {analysisNotebookArtifacts.length ? (
          <Table
            headers={[text.tableType, text.tableKind, text.tableStatus, text.tableArtifact, text.tableCreated, text.tableActions]}
            rows={analysisNotebookArtifacts.map((artifact) => [
              artifact.asset_type,
              String(artifact.metadata.notebook_kind ?? "-"),
              String(artifact.metadata.execution_status ?? artifact.metadata.render_mode ?? "ready"),
              artifact.id,
              formatDate(artifact.created_at),
                <div className="row-actions" key={artifact.id}>
                  {isNativeNotebookSourceAssetType(artifact.asset_type) ? (
                    <button
                      className="icon-button"
                      onClick={() => onOpenNotebookArtifact(artifact.id)}
                      title={text.openNotebookInMarimo}
                    >
                      <BookOpen size={16} />
                    </button>
                  ) : (
                    <button
                      className="icon-button"
                      disabled={previewLoadingId === artifact.id}
                      onClick={() => void loadArtifactPreview(artifact.id)}
                      title={text.artifactPreviewOpenOriginal}
                    >
                      {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                    </button>
                  )}
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.downloadNotebookArtifact}>
                    <Download size={16} />
                  </a>
                </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.reportShelfAnalysisNotebooksEmpty} />
        )}
      </Panel>
      <Panel title={text.reportShelfGuidanceHistoryTitle} icon={<GitBranch size={18} />}>
        {guidedJourneyArtifacts.length ? (
          <div className="stack">
            <Table
              headers={[text.tableType, text.tableStage, text.tableFocus, text.tableVersion, text.tableCreated, text.tableActions]}
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
                    title={text.previewGuidanceArtifact}
                  >
                    {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                  </button>
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.downloadGuidanceArtifact}>
                    <Download size={16} />
                  </a>
                </div>
              ])}
            />
            <div className="metric-grid compact">
              <Metric label={text.guidanceSnapshots} value={guidedJourneySnapshots.length} />
              <Metric label={text.guidanceComparisons} value={guidedJourneyComparisons.length} />
              <Metric
                label={text.guidanceLatestStage}
                value={String(guidedJourneySnapshots[0]?.metadata.current_stage_id ?? "-")}
              />
              <Metric
                label={text.guidanceLatestFocus}
                value={String(guidedJourneySnapshots[0]?.metadata.recommended_focus_key ?? "-")}
              />
            </div>
          </div>
        ) : (
          <EmptyInline text={text.reportShelfGuidanceHistoryEmpty} />
        )}
      </Panel>
      <Panel title={text.reportShelfDecisionArtifactsTitle} icon={<ListChecks size={18} />}>
        {decisionArtifacts.length ? (
          <Table
            headers={[text.tableType, text.tableStatus, text.tableRisks, text.tableQuestions, text.tableArtifact, text.tableActions]}
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
                  title={text.previewDecisionArtifact}
                >
                  {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                </button>
                <a className="icon-link" href={`${apiBase}/api/artifacts/${artifact.id}/download`} title={text.downloadDecisionArtifact}>
                  <Download size={16} />
                </a>
              </div>
            ])}
          />
        ) : (
          <EmptyInline text={text.reportShelfDecisionArtifactsEmpty} />
        )}
      </Panel>
      <Panel title={text.visualizationDashboard} icon={<BarChart3 size={18} />}>
        {visualizations.length ? (
          <div className="stack">
            <Table
              headers={[text.tableTitle, text.tableType, text.tableStatus, text.tableRows, text.tableArtifact]}
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
          <EmptyInline text={text.reportShelfVisualizationDashboardEmpty} />
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

function notebookCoverageLabel(item: NotebookIndexItem, text?: LocaleMessages) {
  const labels = text ?? englishMessages;
  const declaredFigures = numericCoverageValue(item.coverage.declared_figure_count);
  const declaredFindings = numericCoverageValue(item.coverage.declared_finding_count);
  const declaredReadOrder = numericCoverageValue(item.coverage.declared_read_order_count);
  if (declaredFigures || declaredFindings || declaredReadOrder) {
    return [
      declaredFigures ? `${declaredFigures} ${labels.notebookCoverageFigures}` : null,
      declaredFindings ? `${declaredFindings} ${labels.notebookCoverageFindings}` : null,
      declaredReadOrder ? `${declaredReadOrder} ${labels.notebookCoverageReadOrder}` : null
    ].filter(Boolean).join(" / ");
  }
  const flags = [
    item.coverage.has_report ? labels.notebookCoverageReport : null,
    item.coverage.has_visualization ? labels.notebookCoverageVisual : null,
    item.coverage.has_manifest ? labels.notebookCoverageManifest : null,
    item.coverage.has_execution_plan ? labels.notebookCoveragePlan : null
  ].filter(Boolean);
  return flags.length ? flags.join(" / ") : labels.notebookCoverageSourceOnly;
}

function numericCoverageValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function notebookFigureCountForItem(item: NotebookIndexItem) {
  const coverageCount = Math.max(
    numericCoverageValue(item.coverage.evidence_figure_count),
    numericCoverageValue(item.coverage.declared_figure_count)
  );
  const qualityCount = typeof item.quality_manifest?.figure_count === "number" && Number.isFinite(item.quality_manifest.figure_count)
    ? Math.max(0, item.quality_manifest.figure_count)
    : 0;
  const linkedFigureCount = Array.isArray(item.artifact_ids.evidence_figures) ? item.artifact_ids.evidence_figures.length : 0;
  return Math.max(coverageCount, qualityCount, linkedFigureCount);
}

function isEmptyDiagnosticsNotebook(item: NotebookIndexItem | null) {
  if (!item || item.notebook_kind !== "model_diagnostics") return false;
  return String(item.content?.readiness ?? item.coverage.content_readiness ?? "") === "not_ready";
}

function notebookReadinessLabel(item: NotebookIndexItem, text?: LocaleMessages) {
  const readiness = String(item.content?.readiness ?? item.coverage.content_readiness ?? "unknown");
  const messages = text ?? englishMessages;
  const readinessLabels: Record<string, string> = {
    evidence_ready: messages.notebookReadinessEvidenceReady,
    narrative_ready: messages.notebookReadinessNarrativeReady,
    partial_review: messages.notebookReadinessPartialReview,
    not_ready: messages.notebookReadinessNotReady,
    source_only: messages.notebookCoverageSourceOnly,
    unknown: messages.notebookReadinessUnknown
  };
  return readinessLabels[readiness] ?? readiness.replace(/_/g, " ");
}

function notebookReadinessClass(item: NotebookIndexItem) {
  const readiness = String(item.content?.readiness ?? item.coverage.content_readiness ?? "unknown");
  if (readiness === "evidence_ready" || readiness === "narrative_ready") return "badge";
  if (readiness === "not_ready") return "badge risk";
  return "badge muted";
}

function notebookReadinessText(value: string, text: LocaleMessages) {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    evidence_ready: text.notebookReadinessEvidenceReady,
    narrative_ready: text.notebookReadinessNarrativeReady,
    partial_review: text.notebookReadinessPartialReview,
    not_ready: text.notebookReadinessNotReady,
    source_only: text.notebookCoverageSourceOnly,
    unknown: text.notebookReadinessUnknown,
    ready: text.notebookReady,
    review: text.notebookReadinessPartialReview,
    missing: text.statusNeedsAttention,
    needs_source: text.notebookCaptureNeeded
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}

function notebookStatusLabel(value: string, text: LocaleMessages) {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    ready: text.notebookStatusReady
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}

function notebookSourceLabel(item: NotebookIndexItem, text?: LocaleMessages) {
  const labels = text ?? englishMessages;
  if (item.run_id) return labels.notebookSourceRun;
  if (item.model_version_id) return labels.notebookSourceModel;
  if (item.dataset_snapshot_id) return labels.notebookSourceDataset;
  return labels.notebookSourceProject;
}

function notebookKindLabel(kind: string, text: LocaleMessages) {
  const normalized = kind.trim().toLowerCase();
  const labels: Record<string, string> = {
    data_understanding: text.notebookKindDataUnderstanding,
    model_diagnostics: text.notebookKindModelDiagnostics,
    agent_authored: text.notebookKindAgentAuthored,
    analysis_notebook: text.notebookKindAgentAuthored,
    eda_review: text.notebookDataReviewTitle
  };
  return labels[normalized] ?? kind.replace(/_/g, " ");
}

function notebooksForDataset(index: NotebookIndex | null, datasetSnapshotId: string): NotebookIndexItem[] {
  if (!index) return [];
  return sortRelatedNotebookItems(index.items.filter((item) => item.dataset_snapshot_id === datasetSnapshotId));
}

function compareDataSurfaceNotebooks(left: NotebookIndexItem, right: NotebookIndexItem): number {
  const leftNeedsAttention = notebookNeedsAttention(left);
  const rightNeedsAttention = notebookNeedsAttention(right);
  if (leftNeedsAttention !== rightNeedsAttention) return leftNeedsAttention ? 1 : -1;
  const kindPriority: Record<string, number> = {
    data_understanding: 0,
    eda_review: 1,
    agent_authored: 2,
    analysis_notebook: 2,
    model_diagnostics: 3
  };
  const leftPriority = kindPriority[left.notebook_kind] ?? 4;
  const rightPriority = kindPriority[right.notebook_kind] ?? 4;
  if (leftPriority !== rightPriority) return leftPriority - rightPriority;
  if (right.recommendation_score !== left.recommendation_score) return right.recommendation_score - left.recommendation_score;
  return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
}

function notebooksForRun(index: NotebookIndex | null, runId: string): NotebookIndexItem[] {
  if (!index) return [];
  return sortRelatedNotebookItems(index.items.filter((item) => item.run_id === runId || Boolean(item.related_run_ids?.includes(runId))));
}

function notebooksForModelVersion(index: NotebookIndex | null, modelVersionId: string): NotebookIndexItem[] {
  if (!index) return [];
  return sortRelatedNotebookItems(index.items.filter((item) => item.model_version_id === modelVersionId));
}

type RelationalCatalogTable = {
  table_name?: string;
  path?: string;
  role?: string;
  is_primary?: boolean;
  row_count?: number;
  column_count?: number;
  columns?: string[];
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
  source_filename?: string;
  media_kind?: string;
  table_count?: number;
  relationship_count?: number;
  tables?: RelationalCatalogTable[];
  relationships?: RelationalCatalogRelationship[];
  risk_notes?: string[];
  next_actions?: string[];
};

function isRelationalGraphPreview(preview: ArtifactPreview | null): boolean {
  return Boolean(preview && parseRelationalGraphPreview(preview));
}

function parseRelationalGraphPreview(preview: ArtifactPreview): RelationalCatalogPayload | null {
  if (!preview.preview) return null;
  try {
    const parsed = JSON.parse(preview.preview) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") return null;
    if (parsed.schema_version === "relational_catalog.v1") return parsed as RelationalCatalogPayload;
    if (parsed.schema_version === "relational_schema_hint.v1") return parsed as RelationalCatalogPayload;
    if (preview.asset_type !== "relational_schema_hint") return null;
    const tables = normalizeRelationalHintTables(parsed.tables);
    const relationships = normalizeRelationalHintRelationships(parsed.relationships);
    if (!tables.length && !relationships.length) return null;
    return {
      schema_version: "relational_schema_hint.v1",
      source_filename: preview.filename,
      media_kind: "structured_json",
      table_count: tables.length,
      relationship_count: relationships.length,
      tables,
      relationships,
      risk_notes: ["Uploaded ER hints are evidence, not confirmed join contracts."],
      next_actions: [
        "Confirm join keys and cardinality before feature work.",
        "Check prediction-time availability before using supporting tables.",
        "Route relational feature work through a controlled Codex work request."
      ]
    };
  } catch {
    return null;
  }
}

function normalizeRelationalHintTables(value: unknown): RelationalCatalogTable[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index): RelationalCatalogTable[] => {
    if (typeof item === "string") return [{ table_name: item, role: index === 0 ? "source table" : "support" }];
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const name = textField(record.table_name) ?? textField(record.name) ?? textField(record.id) ?? textField(record.path);
    if (!name) return [];
    const columns = Array.isArray(record.columns) ? record.columns.map((column) => String(column)).slice(0, 12) : [];
    return [
      {
        table_name: name,
        path: textField(record.path) ?? undefined,
        role: textField(record.role) ?? (index === 0 ? "source table" : "support"),
        is_primary: record.is_primary === true,
        column_count: numberField(record.column_count) ?? (columns.length || undefined),
        columns,
        key_candidates: columns
          .filter((column) => /(^id$|_id$|id_|key)/i.test(column))
          .slice(0, 3)
          .map((column) => ({ column, reason: "column name looks key-like" }))
      }
    ];
  });
}

function normalizeRelationalHintRelationships(value: unknown): RelationalCatalogRelationship[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): RelationalCatalogRelationship[] => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const leftTable = textField(record.left_table) ?? textField(record.from_table) ?? textField(record.source_table);
    const rightTable = textField(record.right_table) ?? textField(record.to_table) ?? textField(record.target_table);
    if (!leftTable || !rightTable) return [];
    return [
      {
        left_table: leftTable,
        right_table: rightTable,
        left_column: textField(record.left_column) ?? textField(record.from_column) ?? textField(record.source_column) ?? undefined,
        right_column: textField(record.right_column) ?? textField(record.to_column) ?? textField(record.target_column) ?? undefined,
        relation_type: textField(record.relation_type) ?? textField(record.cardinality) ?? "unknown",
        confidence: numberField(record.confidence) ?? undefined,
        evidence: textField(record.evidence) ?? undefined
      }
    ];
  });
}

function RelationalCatalogPreview({ preview }: { preview: ArtifactPreview }) {
  const catalog = React.useMemo(() => parseRelationalGraphPreview(preview), [preview]);
  if (!catalog) return <TranslatablePreview preview={preview} />;
  const tables = Array.isArray(catalog.tables) ? catalog.tables.slice(0, 12) : [];
  const relationships = Array.isArray(catalog.relationships) ? catalog.relationships.slice(0, 24) : [];
  const tableNames = new Set(tables.map((table) => table.table_name).filter(Boolean));
  const visibleRelationships = relationships.filter(
    (relationship) => relationship.left_table && relationship.right_table && tableNames.has(relationship.left_table) && tableNames.has(relationship.right_table)
  );
  const isHint = catalog.schema_version === "relational_schema_hint.v1" || preview.asset_type === "relational_schema_hint";
  const title = catalog.benchmark_name ?? catalog.source_filename ?? preview.name;
  return (
    <div className="relational-preview">
      <div className="relational-preview-header">
        <div>
          <div className="eyebrow">ER-style preview</div>
          <h3>{title}</h3>
          <p>
            {isHint
              ? "Uploaded ER hint rendered as a reviewable map. Use it to guide questions, not as an executable join contract."
              : "Tables and inferred relationship candidates from the RelationalCatalog. Treat edges as review prompts until join semantics are confirmed."}
          </p>
        </div>
        <div className="badge-row">
          <span className="badge">{catalog.table_count ?? tables.length} tables</span>
          <span className="badge muted">{relationships.length} relationships</span>
          <span className="badge risk">{isHint ? "uploaded evidence" : "inferred"}</span>
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
                <dd>{table.column_count ?? table.columns?.length ?? "-"}</dd>
              </div>
              <div>
                <dt>Keys</dt>
                <dd>{table.key_candidates?.slice(0, 3).map((key) => key.column).join(", ") || "-"}</dd>
              </div>
            </dl>
            {table.columns?.length ? <small className="relational-column-hint">{table.columns.slice(0, 5).join(", ")}</small> : null}
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
      {catalog.next_actions?.length ? (
        <div className="relational-next-actions">
          {catalog.next_actions.slice(0, 3).map((action) => (
            <span key={action}>{action}</span>
          ))}
        </div>
      ) : null}
      <details className="artifact-shelf">
        <summary>{isHint ? "Raw uploaded ER JSON" : "Advanced JSON catalog"}</summary>
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
                {table.row_count
                  ? `${table.row_count.toLocaleString()} rows / ${table.column_count ?? table.columns?.length ?? "-"} cols`
                  : `${table.column_count ?? table.columns?.length ?? "-"} columns`}
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

function leaderboardEntryModelLabel(entry: LeaderboardEntry) {
  const label = entry.model_label?.trim();
  if (label) return label.replace(/__/g, " · ").replace(/_/g, " ");
  const modelId = entry.model_id?.trim();
  if (modelId) return modelId.replace(/__/g, " · ").replace(/_/g, " ");
  return entry.run_id;
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

type AssetCategoryKey = "notebooks" | "reports" | "model_prediction" | "research" | "data" | "plans_records" | "other";

const assetTypeCategoryMap: Record<string, AssetCategoryKey> = {
  analysis_notebook: "notebooks",
  marimo_notebook: "notebooks",
  notebook_authoring_brief: "notebooks",
  notebook_evidence_bundle: "notebooks",
  notebook_evidence_svg: "notebooks",
  notebook_execution_plan: "notebooks",
  notebook_figure_manifest: "notebooks",
  notebook_quality_manifest: "notebooks",
  notebook_report: "notebooks",
  notebook_run_manifest: "notebooks",
  decision_dashboard: "reports",
  decision_report: "reports",
  decision_report_bundle: "reports",
  report: "reports",
  run_report: "reports",
  agent_session_report: "reports",
  agent_task_report: "reports",
  understanding_report: "reports",
  model_diagnostics_artifact_report: "reports",
  agent_session_figure: "notebooks",
  feature_importance: "model_prediction",
  permutation_importance: "model_prediction",
  model_diagnostics_artifact_pack: "model_prediction",
  prediction_pipeline: "model_prediction",
  prediction_input: "model_prediction",
  prediction_batch: "model_prediction",
  pilot_prediction_batch: "model_prediction",
  pilot_outcome_batch: "model_prediction",
  pilot_scoring_report: "model_prediction",
  pilot_validation_audit: "model_prediction",
  research_findings_report: "research",
  source_citation_manifest: "research",
  citation_audit_report: "research",
  research_plan: "plans_records",
  research_plan_revision: "plans_records",
  agent_context_pack: "plans_records",
  agent_task_contract: "plans_records",
  split_manifest: "plans_records",
  evaluation_spec: "plans_records",
  evaluation_candidate: "plans_records",
  dataset_snapshot: "data",
  uploaded_supporting_table: "data",
  uploaded_table: "data",
  upload_staging_file: "data",
  relational_catalog: "data",
  relational_schema_hint_upload: "data",
  relational_table_bundle_manifest: "data",
  semantic_catalog: "data",
  eda_profile: "data"
};

const assetCategoryOrder: Array<AssetCategoryKey | "all"> = [
  "all",
  "notebooks",
  "reports",
  "model_prediction",
  "research",
  "data",
  "plans_records",
  "other"
];

function assetCategoryForArtifact(artifact: Artifact): AssetCategoryKey {
  return assetCategoryForAssetType(artifact.asset_type);
}

function assetCategoryForAssetType(assetType: string): AssetCategoryKey {
  return assetTypeCategoryMap[assetType] ?? "other";
}

function assetResearchPlanNodeIds(artifact: Artifact, timeline: ResearchPlanTimelineResponse | null): Set<string> {
  const nodeIds = new Set<string>();
  for (const key of ["research_plan_node_id", "plan_node_id", "node_id"]) {
    const value = artifact.metadata[key];
    if (typeof value === "string" && value.trim()) nodeIds.add(value.trim());
  }
  for (const block of timeline?.blocks ?? []) {
    for (const link of block.attached_artifacts ?? []) {
      if (link.artifact_id === artifact.id) nodeIds.add(block.id);
    }
  }
  return nodeIds;
}

function assetCategoryLabel(key: AssetCategoryKey | "all", text: LocaleMessages) {
  if (key === "all") return text.assetCategoryAll;
  if (key === "notebooks") return text.assetCategoryNotebooks;
  if (key === "reports") return text.assetCategoryReports;
  if (key === "model_prediction") return text.assetCategoryModelPrediction;
  if (key === "research") return text.assetCategoryResearch;
  if (key === "data") return text.assetCategoryData;
  if (key === "plans_records") return text.assetCategoryPlansRecords;
  return text.assetCategoryOther;
}

function artifactDisplayTitle(artifact: Artifact): string {
  for (const key of ["title", "display_name", "report_title", "notebook_title", "model_label", "label"]) {
    const value = textField(artifact.metadata[key]);
    if (value) return value;
  }
  return artifact.name;
}

function artifactDetailLine(artifact: Artifact): string {
  return `${artifact.asset_type} · v${artifact.version}`;
}

function assetCategoryIconForArtifact(artifact: Artifact): React.ReactNode {
  const category = assetCategoryForArtifact(artifact);
  if (category === "notebooks") return <BookOpen size={18} />;
  if (category === "reports") return <FileText size={18} />;
  if (category === "model_prediction") return <BarChart3 size={18} />;
  if (category === "research") return <Search size={18} />;
  if (category === "data") return <Database size={18} />;
  if (category === "plans_records") return <ListChecks size={18} />;
  return <Library size={18} />;
}

function artifactOriginLabel(
  artifact: Artifact,
  timeline: ResearchPlanTimelineResponse | null,
  text: LocaleMessages
): string {
  const planNodeIds = Array.from(assetResearchPlanNodeIds(artifact, timeline));
  if (planNodeIds.length) {
    const planTitles = planNodeIds
      .map((nodeId) => timeline?.blocks.find((block) => block.id === nodeId)?.title ?? nodeId)
      .filter(Boolean)
      .slice(0, 2);
    if (planTitles.length) return `${text.assetOriginPlan}: ${planTitles.join(", ")}`;
  }
  const datasetId = textField(artifact.metadata.dataset_snapshot_id) ?? textField(artifact.metadata.dataset_id);
  if (datasetId) return `${text.assetOriginDataset}: ${datasetId}`;
  const runId =
    textField(artifact.metadata.run_id) ??
    textField(artifact.metadata.experiment_run_id) ??
    textField(artifact.metadata.best_run_id);
  if (runId) return `${text.assetOriginRun}: ${runId}`;
  const modelVersionId = textField(artifact.metadata.model_version_id);
  if (modelVersionId) return `${text.assetOriginModel}: ${modelVersionId}`;
  const jobId = textField(artifact.metadata.job_id);
  if (jobId) return `${text.assetOriginJob}: ${jobId}`;
  const workspacePath = textField(artifact.metadata.workspace_relative_path);
  if (workspacePath) return workspacePath;
  return text.assetOriginProject;
}

function artifactSearchText(
  artifact: Artifact,
  timeline: ResearchPlanTimelineResponse | null,
  text: LocaleMessages
): string {
  return [
    artifact.id,
    artifact.name,
    artifact.asset_type,
    artifactDisplayTitle(artifact),
    assetCategoryLabel(assetCategoryForArtifact(artifact), text),
    artifactOriginLabel(artifact, timeline, text)
  ]
    .join(" ")
    .toLowerCase();
}

const assetSearchPriorityByType: Record<string, number> = {
  analysis_notebook: 0,
  marimo_notebook: 0,
  decision_report: 0,
  run_report: 0,
  agent_session_report: 0,
  research_findings_report: 0,
  prediction_pipeline: 0,
  prediction_batch: 0,
  pilot_prediction_batch: 0,
  pilot_scoring_report: 0,
  pilot_validation_audit: 0,
  dataset_snapshot: 1,
  uploaded_table: 1,
  uploaded_supporting_table: 1,
  split_manifest: 1,
  evaluation_spec: 1,
  evaluation_candidate: 1
};

function assetInventorySearchPriority(artifact: Artifact): number {
  return assetSearchPriorityByType[artifact.asset_type] ?? (assetCategoryForArtifact(artifact) === "other" ? 3 : 2);
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
  project,
  artifacts,
  modelVersions,
  validationsByModelVersion,
  notebookIndex,
  researchPlanTimeline,
  libraryAssets,
  projectAssetReferences,
  previewRequest,
  busy,
  text,
  runAction,
  onEquipSkill,
  onCreateSkill,
  onOpenNotebookArtifact
}: {
  project: Project;
  artifacts: Artifact[];
  modelVersions: ModelVersion[];
  validationsByModelVersion: Record<string, ModelValidation[]>;
  notebookIndex: NotebookIndex | null;
  researchPlanTimeline: ResearchPlanTimelineResponse | null;
  libraryAssets: LibraryAsset[];
  projectAssetReferences: AssetReference[];
  previewRequest: ArtifactPreviewRequest | null;
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onEquipSkill: (asset: LibraryAsset) => Promise<void>;
  onCreateSkill: (draft: SkillDraft) => Promise<void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
}) {
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [assetSearch, setAssetSearch] = React.useState("");
  const [assetCategoryFilter, setAssetCategoryFilter] = React.useState<AssetCategoryKey | "all">("all");
  const [assetPlanFilter, setAssetPlanFilter] = React.useState("all");
  const validationRows = modelVersions.flatMap((modelVersion) =>
    (validationsByModelVersion[modelVersion.id] ?? []).map((validation) => ({
      modelVersion,
      validation
    }))
  );
  const notebookItems = React.useMemo(() => preferredNotebookItems(notebookIndex), [notebookIndex]);
  const planNodeOptions = React.useMemo(() => researchPlanTimeline?.blocks ?? [], [researchPlanTimeline]);
  const visibleArtifactRows = React.useMemo(
    () => {
      const query = assetSearch.trim().toLowerCase();
      const filtered = artifacts.filter((artifact) => {
        const category = assetCategoryForArtifact(artifact);
        const matchesCategory = assetCategoryFilter === "all" || category === assetCategoryFilter;
        const matchesSearch = !query || artifactSearchText(artifact, researchPlanTimeline, text).includes(query);
        const nodeIds = assetResearchPlanNodeIds(artifact, researchPlanTimeline);
        const matchesPlan = assetPlanFilter === "all" || nodeIds.has(assetPlanFilter);
        return matchesCategory && matchesSearch && matchesPlan;
      });
      return filtered.sort((left, right) => {
        if (query || assetCategoryFilter !== "all" || assetPlanFilter !== "all") {
          const priorityDelta = assetInventorySearchPriority(left) - assetInventorySearchPriority(right);
          if (priorityDelta !== 0) return priorityDelta;
        }
        return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
      });
    },
    [artifacts, assetCategoryFilter, assetPlanFilter, assetSearch, researchPlanTimeline, text]
  );
  const handledPreviewRequestRef = React.useRef<number | null>(null);

  async function loadPreview(artifactId: string) {
    setPreviewLoadingId(artifactId);
    setPreviewError(null);
    focusNavigationAnchor("assets-artifact-preview", 0);
    try {
      setPreview(await api<ArtifactPreview>(`/api/artifacts/${artifactId}/preview`));
      focusNavigationAnchor("assets-artifact-preview", 0);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
      focusNavigationAnchor("assets-artifact-preview", 0);
    } finally {
      setPreviewLoadingId(null);
    }
  }

  React.useEffect(() => {
    if (!previewRequest || previewRequest.targetTab !== "Assets") return;
    if (handledPreviewRequestRef.current === previewRequest.nonce) return;
    handledPreviewRequestRef.current = previewRequest.nonce;
    void loadPreview(previewRequest.artifactId);
  }, [previewRequest]);

  const assetInventoryPanel = (
    <Panel title={text.projectAssetsTitle} icon={<Library size={18} />}>
      <div className="asset-inventory-controls">
        <label>
          <span>{text.assetSearchLabel}</span>
          <input
            value={assetSearch}
            onChange={(event) => setAssetSearch(event.target.value)}
            placeholder={text.assetSearchPlaceholder}
          />
        </label>
        <label>
          <span>{text.assetCategoryFilter}</span>
          <select
            value={assetCategoryFilter}
            onChange={(event) => setAssetCategoryFilter(event.target.value as AssetCategoryKey | "all")}
          >
            {assetCategoryOrder.map((key) => (
              <option key={key} value={key}>
                {assetCategoryLabel(key, text)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{text.assetPlanNodeFilter}</span>
          <select value={assetPlanFilter} onChange={(event) => setAssetPlanFilter(event.target.value)}>
            <option value="all">{text.assetPlanNodeAll}</option>
            {planNodeOptions.map((block) => (
              <option key={block.id} value={block.id}>
                {block.title}
              </option>
            ))}
          </select>
        </label>
        <span className="badge muted">{visibleArtifactRows.length} / {artifacts.length}</span>
      </div>
      {visibleArtifactRows.length ? (
        <Table
          headers={[
            text.assetTableOutput,
            text.assetCategoryTable,
            text.assetTableCreated,
            text.assetTableOrigin,
            text.artifactTableSize,
            text.artifactTableActions
          ]}
          rows={visibleArtifactRows.slice(0, 160).map((artifact) => {
            const linkedNotebook = preferredNotebookForArtifact(notebookIndex, artifact.id);
            const directNotebookArtifactId = isNativeNotebookSourceAssetType(artifact.asset_type) ? artifact.id : null;
            const notebookArtifactId = directNotebookArtifactId ?? linkedNotebook?.artifact_ids.notebook ?? null;
            const planNodeIds = Array.from(assetResearchPlanNodeIds(artifact, researchPlanTimeline));
            return [
              <div className={`asset-output-cell${notebookArtifactId ? " notebook-openable" : ""}`} key={`${artifact.id}-name`}>
                <span className="asset-output-icon" aria-hidden="true">
                  {assetCategoryIconForArtifact(artifact)}
                </span>
                <div className="cell-stack">
                  <span>{artifactDisplayTitle(artifact)}</span>
                  <small>{artifactDetailLine(artifact)}</small>
                  {notebookArtifactId ? (
                    <small className="asset-notebook-affordance">
                      <BookOpen size={13} />
                      {text.notebookOpenMarimo}
                    </small>
                  ) : null}
                  {linkedNotebook ? <small>{text.relatedNotebooks}: {conciseNotebookTitle(linkedNotebook.title)}</small> : null}
                </div>
              </div>,
              <span className="badge" key={`${artifact.id}-category`}>
                {assetCategoryLabel(assetCategoryForArtifact(artifact), text)}
              </span>,
              formatDate(artifact.created_at),
              <div className="cell-stack" key={`${artifact.id}-origin`}>
                <span>{artifactOriginLabel(artifact, researchPlanTimeline, text)}</span>
                {planNodeIds.length ? <small>{planNodeIds.slice(0, 2).join(", ")}</small> : null}
              </div>,
              formatBytes(artifact.size_bytes),
              <div className="asset-actions" key={artifact.id}>
                {notebookArtifactId ? (
                  <button
                    className="asset-primary-action"
                    onClick={() => onOpenNotebookArtifact(notebookArtifactId)}
                    type="button"
                    title={text.openNotebookInMarimo}
                  >
                    <BookOpen size={18} />
                    <span>{text.notebookOpenMarimo}</span>
                  </button>
                ) : (
                  <button
                    className="asset-primary-action muted"
                    disabled={previewLoadingId === artifact.id}
                    onClick={() => void loadPreview(artifact.id)}
                    type="button"
                    title={text.previewArtifact}
                  >
                    {previewLoadingId === artifact.id ? <Loader2 className="spin" size={18} /> : <Eye size={18} />}
                    <span>{text.assetPreviewAction}</span>
                  </button>
                )}
                <div className="asset-secondary-actions">
                  {notebookArtifactId ? (
                    <button
                      aria-label={text.previewArtifact}
                      className="icon-button"
                      disabled={previewLoadingId === artifact.id}
                      onClick={() => void loadPreview(artifact.id)}
                      type="button"
                      title={text.previewArtifact}
                    >
                      {previewLoadingId === artifact.id ? <Loader2 className="spin" size={16} /> : <Eye size={16} />}
                    </button>
                  ) : null}
                  <a
                    aria-label={text.downloadArtifact}
                    className="icon-link"
                    href={`${apiBase}/api/artifacts/${artifact.id}/download`}
                    title={text.downloadArtifact}
                  >
                    <Download size={16} />
                  </a>
                </div>
              </div>
            ];
          })}
        />
      ) : (
        <EmptyInline text={text.projectAssetsEmpty} />
      )}
      {visibleArtifactRows.length > 160 ? <EmptyInline text={text.assetInventoryLimited.replace("{count}", String(visibleArtifactRows.length - 160))} /> : null}
    </Panel>
  );

  return (
    <div className="stack">
      {assetInventoryPanel}
      <Panel title="Model Versions" icon={<Layers size={18} />}>
        {modelVersions.length ? (
          <Table
            headers={["Name", "Version", "Type", "Metric", "Latest Validation", "Notebooks", "Package", "Actions"]}
            rows={modelVersions.map((modelVersion) => {
              const latestValidation = getLatestValidation(validationsByModelVersion[modelVersion.id] ?? []);
              return [
                modelVersion.name,
                `v${modelVersion.version}`,
                modelVersion.model_type.replace(/_/g, " "),
                formatModelMetric(modelVersion),
                formatValidationSummary(latestValidation),
                <RelatedNotebookLinks
                  key={`${modelVersion.id}-notebooks`}
                  notebooks={notebooksForModelVersion(notebookIndex, modelVersion.id)}
                  onOpen={onOpenNotebookArtifact}
                  previewLoadingId={previewLoadingId}
                  text={text}
                />,
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
      <Panel id="asset-notebooks" title={text.notebookCenterTitle} icon={<BookOpen size={18} />}>
        {notebookIndex && notebookIndex.counts.total > 0 ? (
          <div className="stack">
            <div className="metric-grid compact">
              <Metric label={text.notebookMetricNotebooks} value={notebookIndex.counts.total} />
              <Metric label={text.notebookMetricReports} value={notebookIndex.counts.with_report} />
              <Metric label={text.notebookMetricCaptured} value={notebookIndex.counts.with_native_source} />
            </div>
            <Table
              headers={[
                text.notebookTableNotebook,
                text.notebookTableSource,
                text.notebookTableCoverage,
                text.notebookTableCreated,
                text.notebookTableActions
              ]}
              rows={notebookItems.map((item) => [
                  <div className="cell-stack" key={`${item.notebook_artifact_id}-title`}>
                    <span>{item.title}</span>
                    <small>{notebookKindLabel(item.notebook_kind, text)} · {notebookReadinessLabel(item, text)}</small>
                  </div>,
                  notebookSourceLabel(item, text),
                  notebookCoverageLabel(item, text),
                  formatDate(item.created_at),
                  <div className="row-actions" key={`${item.notebook_artifact_id}-actions`}>
                    <button
                      className={`icon-button ${notebookNeedsAttention(item) ? "danger" : ""}`}
                      onClick={() => onOpenNotebookArtifact(item.artifact_ids.notebook)}
                      title={notebookNeedsAttention(item) ? text.notebookNativeMarimoRuntimeError : text.notebookOpenMarimo}
                    >
                      {notebookNeedsAttention(item) ? <AlertTriangle size={16} /> : <BookOpen size={16} />}
                    </button>
                    <a
                      className="icon-link"
                      href={`${apiBase}/api/artifacts/${item.artifact_ids.notebook}/download`}
                      title={text.notebookDownloadMarimoSource}
                    >
                      <Download size={16} />
                    </a>
                  </div>
                ])}
            />
          </div>
        ) : (
          <EmptyInline text={text.notebookEmpty} />
        )}
      </Panel>
      <LibraryTab
        project={project}
        assets={libraryAssets}
        references={projectAssetReferences}
        busy={busy}
        text={text}
        runAction={runAction}
        onEquipSkill={onEquipSkill}
        onCreateSkill={onCreateSkill}
      />
      <Panel id="assets-artifact-preview" title="Artifact Preview" icon={<FileText size={18} />}>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {preview ? (
          preview.preview_available ? (
            isHtmlArtifactPreview(preview) ? (
              <HtmlArtifactPreview preview={preview} />
            ) : (
              <div className="preview-block">
                <div className="preview-meta">
                  <span className="badge">{preview.content_type}</span>
                  <span className="badge muted">{formatBytes(preview.size_bytes)}</span>
                  {preview.truncated ? <span className="badge risk">truncated</span> : null}
                </div>
                <TranslatablePreview preview={preview} />
              </div>
            )
          ) : (
            <EmptyInline text={preview.reason ?? "Preview is not available for this artifact."} />
          )
        ) : (
          <EmptyInline text="Select an artifact preview action to inspect JSON, Markdown, CSV, or text outputs without leaving the workbench." />
        )}
        {preview ? (
          <ArtifactLineagePanel
            inputs={preview.lineage?.inputs ?? []}
            outputs={preview.lineage?.outputs ?? []}
            text={text}
          />
        ) : null}
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
  const { text } = React.useContext(LocaleContext);
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
              formatJobStatus(job, text),
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

function formatJobStatus(job: Job, text: LocaleMessages) {
  const statusLabel = workerStatusLabel(job.status, text);
  const status = job.error_message ? `${statusLabel}: ${job.error_message}` : statusLabel;
  if (job.approval_required && job.status === "queued") return `${status} / ${text.workerStatusApproved}`;
  if (job.approval_required) return `${status} / ${text.workerStatusApprovalRequired}`;
  return status;
}

function formatWorkflowState(value: string | null, text?: LocaleMessages) {
  if (!value) return "-";
  const normalized = value.toLowerCase();
  if (text) {
    if (normalized === "idle") return text.workflowIdle;
    if (normalized === "draft") return text.workflowDraft;
    if (normalized === "understanding_review") return text.workflowUnderstandingReview;
    if (normalized === "autonomous_loop") return text.workflowAutonomousLoop;
  }
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

function isDataIntakeJob(job: Job) {
  return ["upload_data_bundle", "select_primary_table"].includes(job.job_type);
}

function dataIntakeJobDetail(job: Job, text: LocaleMessages) {
  return (
    textField(job.output.assistant_message) ??
    textField(job.output.progress_message) ??
    textField(job.error_message) ??
    textField(job.input.primary_filename) ??
    textField(job.input.primary_table) ??
    textField(job.input.dataset_name) ??
    text.dataIntakeWorkingFallback
  );
}

function isMainAgentReplyWaitJob(job: Job) {
  return job.job_type === "agent_chat_turn" && job.status === "waiting_for_agent";
}

function canRetryJob(job: Job) {
  return ["failed", "cancelled", "timed_out"].includes(job.status) && job.attempt_count < job.max_attempts;
}

function LibraryTab({
  project,
  assets,
  references,
  busy,
  text,
  runAction,
  onEquipSkill,
  onCreateSkill
}: {
  project: Project;
  assets: LibraryAsset[];
  references: AssetReference[];
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onEquipSkill: (asset: LibraryAsset) => Promise<void>;
  onCreateSkill: (draft: SkillDraft) => Promise<void>;
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
      <SkillManagerPanel
        assets={assets}
        busy={busy}
        equippedSkills={equippedSkillItems(references, assets)}
        references={references}
        text={text}
        onCreateSkill={onCreateSkill}
        onEquipSkill={onEquipSkill}
      />
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
                onClick={() => void (asset.asset_type === "skill" ? onEquipSkill(asset) : runAction(() => api(`/api/projects/${project.id}/asset-references`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    target_asset_id: asset.id,
                    target_asset_version_id: asset.latest_version_id,
                    relation_type: "uses"
                  })
                })))}
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

function formatBytes(value: number | null) {
  if (value === null) return "-";
  if (value === 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function storageCategoryLabel(key: string, text: LocaleMessages) {
  if (key === "datasets") return text.storageDatasets;
  if (key === "artifacts") return text.storageArtifacts;
  if (key === "workspaces") return text.storageWorkspaces;
  if (key === "pipeline_envs") return text.storagePipelineEnvs;
  if (key === "marimo") return text.storageMarimo;
  if (key === "db") return text.storageDb;
  return key;
}

function formatCompactCount(value: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
