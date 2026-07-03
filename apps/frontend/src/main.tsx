import React from "react";
import ReactDOM from "react-dom/client";
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
  Upload,
  UserCircle,
  X
} from "lucide-react";
import "./styles.css";

type DisplayTheme = "light" | "dark";
type LocaleDirection = "ltr" | "rtl";
type LocaleSource = "built_in" | "dynamic";
type ChatSubmitShortcutSetting = "locale_default" | "enter" | "shift_enter";
type ChatSubmitShortcut = "enter" | "shift_enter";

type UserSettings = {
  locale: string;
  requestedLocale: string;
  dynamicLanguageRequest: string;
  displayTheme: DisplayTheme;
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

const userSettingsStorageKey = "tablex.userSettings.v1";
const dynamicLocaleStorageKey = "tablex.dynamicLocalePacks.v1";

const defaultUserSettings: UserSettings = {
  locale: "en-US",
  requestedLocale: "",
  dynamicLanguageRequest: "",
  displayTheme: "light",
  interventionCountdownSeconds: 15,
  agentModel: "codex-default",
  utilityModel: "utility-default",
  chatSubmitShortcut: "locale_default",
  userAvatarDataUrl: null
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
  activeProjects: "In Progress",
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
  tabHome: "Home",
  tabOverview: "Overview",
  tabData: "Data",
  tabInsight: "Insight",
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
  focusUnderstandData: "Understand the data before choosing an objective or evaluation",
  focusUnderstandDataReason:
    "The next useful decision depends on schema, possible task shapes, leakage risk, missingness, and semantic assumptions.",
  focusPriorResearch: "Research prior knowledge",
  focusPriorResearchReason:
    "Codex is collecting or deciding whether external, Kaggle, arXiv, or Skill evidence is needed before approach selection.",
  focusAssumptions: "Resolve risky assumptions",
  focusAssumptionsReason: "High-risk assumptions can silently invalidate evaluation or feature design if they are not reviewed.",
  focusEvaluation: "Lock a reliable evaluation design",
  focusEvaluationReason: "Review evaluation and split constraints before comparing models or agent approaches.",
  focusApproach: "Plan the next flexible agent approach",
  focusApproachReason: "Use the current evidence to ask Codex for the next scoped approach.",
  focusExperiments: "Run or inspect experiments",
  focusExperimentsReason: "The project needs run evidence, diagnostics, and reports before comparing approaches.",
  focusNotebooks: "Review notebook evidence",
  focusNotebooksReason: "Notebook previews and safe captures turn run evidence into inspectable findings before final reporting.",
  artifactPreviewHtmlBadge: "HTML preview",
  artifactPreviewSvgBadge: "SVG preview",
  artifactPreviewImageBadge: "image preview",
  artifactPreviewPdfBadge: "PDF preview",
  artifactPreviewTruncatedBadge: "truncated",
  artifactPreviewOpenOriginal: "Open original",
  artifactPreviewTruncatedWarning: "This preview is truncated. Download the artifact for the full notebook preview.",
  artifactPreviewFrameFailedWarning: "The embedded preview did not load. Open the original artifact in a new tab.",
  artifactPreviewEmptyWarning: "This preview artifact does not contain visible HTML content. Open the original artifact or inspect the source.",
  artifactPreviewLoadingTitle: "Loading preview",
  artifactPreviewLoadingBody: "The notebook preview is opening in this panel.",
  artifactPreviewSlowTitle: "Still rendering",
  artifactPreviewSlowBody: "Large notebook previews can take a moment. You can also open the artifact in a new tab.",
  artifactPreviewAvailableTitle: "Preview is available as an artifact.",
  artifactPreviewAvailableBody: "Open it in a new tab if the embedded frame stays blank.",
  artifactPreviewInspectSource: "Inspect preview source",
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
  decisionQuestion: "Decision question",
  saveDecisionBrief: "Save decision brief",
  settings: "User Settings",
  settingsHint: "Language, locale packs, and display preferences are stored locally for this workbench.",
  signInTitle: "Sign in to Tablex",
  signInBody: "Keep projects, language, avatar, and model preferences available across browsers.",
  email: "Email",
  password: "Password",
  passwordRequirement: "At least 10 characters with uppercase, lowercase, digit, and symbol.",
  displayName: "Display name",
  signIn: "Sign in",
  createFirstUser: "Create first user",
  signOut: "Sign out",
  signedInAs: "Signed in as",
  passwordAuth: "Password",
  googleAuthComingSoon: "Google sign-in is prepared for a later connector-backed phase.",
  authDisabledHint: "Local auth is disabled for this backend.",
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
  userProfile: "User profile",
  userAvatar: "User avatar",
  uploadUserAvatar: "Upload avatar",
  clearUserAvatar: "Reset avatar",
  userAvatarHint: "Stored locally in this browser. The default avatar is used when no image is selected.",
  generateUserAvatar: "Generate avatar candidates",
  userAvatarPrompt: "Avatar prompt",
  userAvatarPromptPlaceholder: "e.g. a calm data scientist with teal glasses, friendly and minimal",
  userAvatarGenerate: "Generate candidates",
  userAvatarGenerating: "Generating candidates",
  userAvatarCandidates: "Avatar candidates",
  userAvatarUseCandidate: "Use this avatar",
  userAvatarPromptRequired: "Enter an avatar prompt first.",
  userAvatarGenerationHint:
    "Uses the backend Codex image bridge by default. API credentials are only needed for an optional backend API provider, and candidates are not saved until you choose one.",
  userAvatarNoCandidates: "No generated candidates yet.",
  userAvatarProgressPreparing: "Preparing the Codex image request",
  userAvatarProgressGenerating: "Codex is generating avatar candidates",
  userAvatarProgressFinalizing: "Waiting for generated files",
  userAvatarElapsed: "Elapsed",
  intervention: "Intervention",
  models: "Models",
  agentModel: "Agent model",
  agentModelHint: "Used for planning, notebook authoring, modeling strategy, and autonomous reasoning.",
  utilityModel: "Utility model",
  utilityModelHint: "Used for translation, short summaries, UI wording, and conversation compression.",
  modelPlaceholder: "e.g. gpt-5.1, gpt-5.5-high, gpt-5-mini",
  interventionCountdown: "Full Auto intervention window",
  interventionCountdownHint:
    "Seconds to catch a Full Auto assumption or boundary before the agent continues. Set 0 to never show the dialog.",
  seconds: "seconds",
  chatInput: "Chat input",
  chatSubmitShortcut: "Send shortcut",
  chatSubmitShortcutHint:
    "IME composition is protected. Locale default uses Enter for English-like locales and Shift+Enter for languages where conversion is common.",
  submitShortcutLocaleDefault: "Locale default",
  submitShortcutEnter: "Enter sends",
  submitShortcutShiftEnter: "Shift+Enter sends",
  autonomyInterventionTitle: "Full Auto is about to continue",
  autonomyInterventionBody: "Tablex found a boundary or assumption. Catch it now to switch to Approval Based and review before continuing.",
  autonomyObjectiveInterventionTitle: "Codex will review the task objective",
  autonomyObjectiveInterventionBody:
    "Full Auto will ask Codex to reason from the data and project context instead of letting the harness infer a target with brittle rules. Catch this window to switch to Approval Based and review first.",
  autonomyInterventionContinue: "Let it continue",
  autonomyInterventionCatch: "Catch and review",
  autonomyInterventionDisabled: "Intervention dialog disabled",
  autonomyInterventionAssumed: "Full Auto continued with this assumption.",
  autonomyInterventionTarget: "Objective under review",
  autonomyInterventionDataset: "Dataset",
  autonomyInterventionTimeLeft: "Time left",
  fullAutoModeSelected: "Full Auto mode is selected. Press Start when data is ready; I will keep moving with explicit assumptions and boundaries.",
  approvalModeSelected: "Approval Based mode is selected. Press Start when data is ready; I will prepare evidence and wait before risky decisions.",
  stopAgentLoopUserMessage: "Stop agent loop",
  startAgentLoopUserMessage: "Start agent loop",
  agentLoopStopped: "Agent loop stopped.",
  agentLoopStarted: "Agent loop started.",
  createLocalizationTask: "Create AgentTask",
  localizationTaskHint:
    "Creates a harness-owned AgentTaskContract so Codex can later generate or revise a locale pack.",
  localizationTaskCreated: "Localization runner handoff saved.",
  noProjectForLocalization: "Select a project before creating a localization AgentTask.",
  agentChatTitle: "Agent Chat",
  agentChatSubtitle: "Persistent conversation, decisions, and reports. Live worker cards appear separately while work is running.",
  agentWorkspacePersistent: "Persistent workspace",
  agentChatPlaceholder: "Ask Tablee to explain status, discuss a target, or think through the next move",
  createAgentTaskContract: "Send",
  youAsked: "You asked",
  tableeAnswered: "Tablee answered",
  agentReplyPendingTitle: "Waiting for Codex",
  agentReplyPending: "Thinking and preparing the next useful response.",
  agentReplyWaitMetaStatus: "Agent",
  agentReplyWaitMetaOutput: "Last Codex output",
  agentReplyWaitMetaRaw: "Raw",
  agentReplyWaitMetaAgo: "ago",
  agentReplyFailed: "I could not complete that request. The error is recorded here so it does not disappear.",
  chatTurnStatus: "Status",
  earlierConversation: "Earlier conversation",
  nextActionLabel: "Next",
  downloadLatestAgentTaskContract: "Download latest AgentTaskContract",
  agentTaskContractCreated: "Runner handoff saved.",
  chatActionOpen: "Open",
  chatActionReview: "Review",
  chatChangedLabel: "Changed",
  chatReviewLabel: "Needs review",
  agentActivityTitle: "Agent Activity",
  agentActivitySubtitle: "Running and waiting work. Finished work is summarized in Agent Chat.",
  agentActivityLiveOnly: "Active work",
  turnStateObserved: "Observed state",
  turnStateSource: "Observed from Tablex jobs and local Codex process state.",
  turnStateWaitingForUser: "Your turn",
  turnStateAgentRunning: "Codex is working",
  turnStateWorkerPending: "Waiting for worker",
  turnStateAgentScheduled: "Codex will resume",
  turnStateStaleRunner: "Runner needs attention",
  turnStateNeedsAttention: "No live agent turn observed",
  turnStateUserTurnHint: "Codex is paused. The input field is ready for your next instruction.",
  turnStateAgentTurnHint: "Codex or a Tablex worker is active. You can still add a message to the workspace.",
  turnStateWorkerPendingHint: "A Tablex worker is waiting or running. Active work appears in the activity cards.",
  turnStateAgentScheduledHint: "Codex is not running at this instant, but Full Auto is scheduled to continue.",
  turnStateNeedsAttentionHint: "No live Codex turn is observed. Use the input field or Start when ready.",
  estimatedTokens: "Estimated tokens",
  currentTokens: "Current",
  cumulativeTokens: "Task total",
  telemetryEstimate: "live activity estimate",
  telemetryWaiting: "waiting to start",
  workerCancelLabel: "Cancel job",
  workerStatusQueued: "Waiting",
  workerStatusRunning: "Running",
  workerStatusApproval: "Approval",
  workerStatusWaitingForAgent: "Waiting for Codex",
  workerStatusWaitingForRunner: "Codex will retry",
  workerStatusFinished: "Finished",
  workerDisplayAutonomousSession: "Autonomous Session",
  workerDisplayTraining: "Training Worker",
  workerDisplayNotebook: "Notebook Worker",
  workerDisplayResearch: "Research Worker",
  workerDisplayAgentRunner: "Agent Runner",
  workerDisplayHarness: "Harness Worker",
  workerDisplayOrchestrator: "Tablee Orchestrator",
  workerOptimisticHeadline: "Reading your request and checking project context.",
  workerWaitingSummaryPrefix: "Waiting for a local worker to pick it up.",
  workerWaitingNoTelemetry: "No live token telemetry is available yet.",
  workerMainAgentWaitTitle: "Waiting for Codex reply",
  workerMainAgentWaitSummary: "Your message is in the main Codex session. The next Codex-authored update will appear in Chat.",
  workerRunBaselineTitle: "Train the adaptive baseline",
  workerRunBaselineSummary:
    "Use the approved evaluation design, train the current adaptive tabular baseline, and publish comparable run evidence for the Leaderboard.",
  workerTrainCandidatesTitle: "Train candidate models",
  workerTrainCandidatesSummary:
    "Train the candidate model set on the same split and metric surface so the Leaderboard can compare runs fairly.",
  workerRunCodexTaskTitle: "Run Codex on the prepared agent task",
  workerRunCodexTaskSummary:
    "Execute the prepared AgentTaskContract, then return artifacts, findings, and next recommendations to the harness.",
  workerContinueSessionTitle: "Continue the main Full Auto session",
  workerContinueSessionSummary:
    "Keep the autonomous data-science thread moving after child workers or Codex return control to the harness.",
  workerProjectLabel: "Project",
  workerJobLabel: "Job",
  workerElapsedLabel: "Elapsed",
  workerIdLabel: "ID",
  workerChatPlaceholder: "Message this worker",
  noAgentActivity: "Agent activity will appear after chat, jobs, or runner work starts.",
  missionControlTitle: "Mission Control",
  missionControlSubtitle:
    "Stay here for the next decision, the current plan, and the agent conversation. Evidence surfaces stay one click away.",
  autonomyMode: "Autonomy mode",
  autonomyPower: "Agent power",
  startAgent: "Start",
  stopAgent: "Stop",
  agentPowerReady: "Ready after data upload",
  agentPowerNeedsData: "Upload data to enable the agent run loop.",
  agentPowerOn: "Agent loop is on",
  agentPowerOff: "Agent loop is off",
  targetCanWait: "Target can be set now, derived by the agent, or confirmed after data understanding.",
  targetColumnLabel: "Objective / target",
  targetPlaceholder: "Choose a column, describe a derived target, or leave open",
  setTarget: "Set target",
  clearTarget: "Clear target",
  targetSaved: "Target saved",
  targetSuggestions: "Column suggestions",
  targetSuggestionsEmpty: "Upload or select a table to see column suggestions.",
  primaryTableLabel: "Primary table",
  primaryTableHelp: "Pick the table that defines one prediction row. Supporting tables stay available for Codex-designed joins and aggregation.",
  queuedTablesTitle: "Tables to upload",
  uploadCompleteChatMessage: "Upload completed. Data Understanding artifacts and the marimo notebook are being registered in this workspace.",
  approvalBasedMode: "Approval Based",
  approvalBasedModeHint: "Ask before risky decisions, external execution, evaluation changes, or deployment-facing steps.",
  fullAutoMode: "Full Auto",
  fullAutoModeHint: "Ask questions, record assumptions, and keep moving with explicit fallback policies.",
  researchPlanTitle: "Research Plan",
  researchPlanEmpty: "No active ResearchPlan yet. Start the agent or ask in Chat; Tablex will create planning artifacts when they are useful.",
  researchPlanTimelineHint: "Codex can append project-specific blocks as the work evolves.",
  researchPlanDetailNextAction: "Next action",
  researchPlanDetailDoneCriteria: "Done criteria",
  researchPlanDetailBlockers: "Blockers",
  researchPlanDetailEvidence: "Evidence",
  researchPlanDetailLocaleRefresh: "Display language",
  researchPlanLocaleRefreshDetail: "Codex needs to refresh this plan block in the selected locale.",
  researchPlanBlockLocaleRefreshTitle: "Display language refresh pending",
  researchPlanSummaryBlock: "block",
  researchPlanSummaryBlocks: "blocks",
  planBlockDataUpload: "Data upload",
  planBlockDataUploadPending: "Drop CSV/Parquet files or import a benchmark before the loop starts.",
  planBlockDataUploadDone: "DatasetSnapshot exists.",
  planBlockObjective: "Objective setting",
  planBlockObjectivePending: "Codex can propose the objective; it may be a column, derived aggregate, unsupervised task, or inverse-problem workflow.",
  planBlockObjectiveDone: "Objective evidence is registered.",
  planBlockObjectiveSkipped: "Full Auto delegated this to Codex and continued with an explicit assumption boundary.",
  planBlockObjectiveDelegated: "delegated to Codex",
  planBlockUnderstanding: "Data understanding",
  planBlockUnderstandingPending: "Profile schema, missingness, row semantics, leakage risk, and target-aware evidence when available.",
  planBlockUnderstandingNeedsNotebook: "Work evidence exists, but a reviewable data-understanding notebook is not registered yet.",
  planBlockUnderstandingDone: "Reviewable data-understanding evidence is available.",
  planBlockPriorResearch: "Prior knowledge research",
  planBlockPriorResearchPending: "Use Kaggle, arXiv, Skills, and Codex-selected sources to add evidence before approach selection.",
  planBlockPriorResearchActive: "Codex is working on this step; research evidence or a no-findings decision has not been registered yet.",
  planBlockPriorResearchPrepared: "Research context is prepared, but retrieved findings and a readable notebook are not registered yet.",
  planBlockPriorResearchDone: "Research or Skill evidence is available.",
  planBlockPriorResearchNoFindings: "Codex researched or reviewed this step and found no additional external findings worth adding.",
  planBlockCodexLane: "Codex work",
  planBlockCodexRunning: "Codex is working in this project workspace.",
  planBlockCodexWaiting: "Codex session is ready; the next live turn will appear here.",
  strategyActionUploadData: "Upload data",
  strategyActionUploadDataReason: "A project-specific strategy needs at least one DatasetSnapshot.",
  strategyActionExploreObjective: "Explore objective candidates",
  strategyActionExploreObjectiveReason:
    "Ask Codex to review whether the task is a direct target, derived aggregate, unsupervised workflow, or another project-specific objective.",
  strategyActionResolveAssumptions: "Resolve risky assumptions",
  strategyActionResolveAssumptionsReason: "Review assumptions that can affect evaluation, feature safety, or deployment-sensitive decisions.",
  strategyActionLockEvaluation: "Lock evaluation design",
  strategyActionLockEvaluationReason: "Approve the EvaluationSpec and SplitManifest before trusting model-comparison claims.",
  planStatusDone: "Done",
  planStatusActive: "Running",
  planStatusPending: "Next",
  planStatusBlocked: "Blocked",
  planStatusWaiting: "Waiting",
  planStatusSkipped: "Delegated",
  planSubtaskSingular: "subtask",
  planSubtaskPlural: "subtasks",
  planLaneEvaluation: "Evaluation design",
  planLaneBaseline: "Modeling experiments",
  planLaneReporting: "Reporting",
  planLaneNotebook: "Notebook analysis",
  openNotebookViewer: "Open notebook",
  notebookCreatedChatMessage: "A marimo notebook was saved as an asset and linked to its source context.",
  notebookLinkedAssetDetail: "Open the notebook viewer from this chat, the related dataset, model, run, or Assets.",
  relatedNotebooks: "Notebooks",
  noRelatedNotebooks: "No linked notebook yet",
  currentTaskTitle: "Current task",
  currentTaskIdle: "Idle",
  currentTaskEmpty: "No active task. Ask Tablee for the next useful move or start the agent.",
  currentTaskWaiting: "Waiting for worker",
  currentTaskWaitingBody: "This queued job will start when a local worker is available.",
  runWorkerOnce: "Run worker once",
  agentWorkspaceTitle: "Agent workspace",
  evidenceSurfacesTitle: "Evidence surfaces",
  supportingSurfacesTitle: "Supporting surfaces",
  ideasAndFindingsTitle: "Ideas & Findings",
  ideasAndFindingsEmpty: "Insights, domain knowledge, and candidate ideas will accumulate here as the agent learns.",
  ideasAndFindingsReady: "signals worth opening",
  openDeepDive: "Open deep dive",
  equippedSkillsTitle: "Equipped Skills",
  equippedSkillsEmpty: "No project skills equipped yet.",
  equippedSkillBadge: "E",
  skillPanelHint: "Choose reusable skills that Codex can reference during this project.",
  skillSelectPlaceholder: "Choose an existing Skill",
  skillEquipExisting: "Equip existing",
  skillCreateTitle: "Create a Skill",
  skillName: "Skill name",
  skillDescription: "Description",
  skillInstructions: "Instructions",
  skillTags: "Tags",
  skillCreateAndEquip: "Create & equip",
  skillNoAvailable: "No unequipped Skills are available. Seed the library or create one here.",
  agentModeChat: "Chat",
  agentModeRaw: "Raw",
  rawAgentTitle: "Raw Codex transcript",
  rawAgentEmpty: "No Codex execution transcript is available yet. Start the agent or send a message to begin.",
  rawAgentTail: "tail",
  rawAgentStdout: "stdout",
  rawAgentStderr: "stderr",
  rawAgentUpdated: "updated",
  rawAgentIndexedEvents: "Indexed transcript events",
  rawAgentRawJsonl: "Raw JSONL",
  rawAgentRawLine: "Raw line",
  rawAgentParsedEvent: "Parsed event",
  rawAgentOpenStdout: "Open full stdout",
  rawAgentOpenStderr: "Open full stderr",
  openSurface: "Open",
  strategyBriefTitle: "Adaptive Strategy Brief",
  strategyBriefSubtitle: "One guided next step from the current project evidence.",
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
  activeProjects: "進行中",
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
  tabHome: "ホーム",
  tabOverview: "概要",
  tabData: "データ",
  tabInsight: "インサイト",
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
  focusUnderstandData: "目的や評価を決める前にデータを理解する",
  focusUnderstandDataReason:
    "schema、あり得るタスク形状、leakage risk、missingness、semantic assumptionsを見てから次の意思決定をします。",
  focusPriorResearch: "従来知見を調査する",
  focusPriorResearchReason:
    "approach選択の前に、Codexが外部情報、Kaggle、arXiv、Skill由来の知見が必要かを調査または判断しています。",
  focusAssumptions: "リスクの高い仮定を確認する",
  focusAssumptionsReason: "高リスクの仮定を放置すると、評価や特徴量設計が静かに壊れる可能性があります。",
  focusEvaluation: "信頼できる評価設計を固定する",
  focusEvaluationReason: "モデル比較やagent approachの前に、評価設計と分割条件を確認します。",
  focusApproach: "次の柔軟なagent approachを計画する",
  focusApproachReason: "現時点の根拠を使って、Codexに次のapproachを検討させます。",
  focusExperiments: "実験を実行または確認する",
  focusExperimentsReason: "approachを比較する前に、run evidence、diagnostics、reportが必要です。",
  focusNotebooks: "notebook evidenceを確認する",
  focusNotebooksReason: "Notebook previewとsafe captureで、最終report前にrun evidenceを検査可能なfindingへ変換します。",
  artifactPreviewHtmlBadge: "HTMLプレビュー",
  artifactPreviewSvgBadge: "SVGプレビュー",
  artifactPreviewImageBadge: "画像プレビュー",
  artifactPreviewPdfBadge: "PDFプレビュー",
  artifactPreviewTruncatedBadge: "一部のみ",
  artifactPreviewOpenOriginal: "元のartifactを開く",
  artifactPreviewTruncatedWarning: "このプレビューは一部のみです。完全なNotebook previewはartifactを開いて確認してください。",
  artifactPreviewFrameFailedWarning: "埋め込みプレビューを読み込めませんでした。元のartifactを新しいタブで開いてください。",
  artifactPreviewEmptyWarning: "このpreview artifactには表示可能なHTML本文が見つかりません。元のartifactを開くか、ソースを確認してください。",
  artifactPreviewLoadingTitle: "プレビューを読み込み中",
  artifactPreviewLoadingBody: "このパネル内でNotebook previewを開いています。",
  artifactPreviewSlowTitle: "レンダリング中",
  artifactPreviewSlowBody: "大きいNotebook previewは表示に時間がかかることがあります。元のartifactを新しいタブで開くこともできます。",
  artifactPreviewAvailableTitle: "プレビューartifactがあります。",
  artifactPreviewAvailableBody: "埋め込み表示が空のままの場合は、新しいタブで開いてください。",
  artifactPreviewInspectSource: "プレビューソースを確認",
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
  decisionQuestion: "判断の問い",
  saveDecisionBrief: "Decision briefを保存",
  settings: "ユーザー設定",
  settingsHint: "言語、locale pack、表示設定をこのworkbenchのlocal設定として保存します。",
  signInTitle: "Tablexにログイン",
  signInBody: "プロジェクト、言語、アイコン、モデル設定をブラウザを跨いで保持します。",
  email: "メールアドレス",
  password: "パスワード",
  passwordRequirement: "10文字以上で、大文字・小文字・数字・記号をすべて含めてください。",
  displayName: "表示名",
  signIn: "ログイン",
  createFirstUser: "最初のユーザーを作成",
  signOut: "ログアウト",
  signedInAs: "ログイン中",
  passwordAuth: "パスワード",
  googleAuthComingSoon: "Googleログインは後続のconnector-backed phase用に境界だけ用意しています。",
  authDisabledHint: "このbackendではlocal authは無効です。",
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
  userProfile: "ユーザープロフィール",
  userAvatar: "ユーザーアイコン",
  uploadUserAvatar: "アイコンをアップロード",
  clearUserAvatar: "アイコンをリセット",
  userAvatarHint: "このブラウザのlocal設定に保存します。画像がない場合はデフォルトアイコンを使います。",
  generateUserAvatar: "アイコン候補を生成",
  userAvatarPrompt: "アイコン生成プロンプト",
  userAvatarPromptPlaceholder: "例: 落ち着いたデータサイエンティスト、ティール色の眼鏡、親しみやすくミニマル",
  userAvatarGenerate: "候補を生成",
  userAvatarGenerating: "候補を生成中",
  userAvatarCandidates: "アイコン候補",
  userAvatarUseCandidate: "このアイコンを使う",
  userAvatarPromptRequired: "先にアイコン生成プロンプトを入力してください。",
  userAvatarGenerationHint:
    "既定ではバックエンドのCodex画像生成bridgeを使います。API credentialは任意のbackend API provider用で、候補は選ぶまで保存しません。",
  userAvatarNoCandidates: "生成候補はまだありません。",
  userAvatarProgressPreparing: "Codex画像生成リクエストを準備中",
  userAvatarProgressGenerating: "Codexがアイコン候補を生成中",
  userAvatarProgressFinalizing: "生成ファイルの返却を待機中",
  userAvatarElapsed: "経過",
  intervention: "介入",
  models: "モデル",
  agentModel: "Agent用モデル",
  agentModelHint: "計画、Notebook執筆、モデリング方針、自律的な内省に使うモデルです。",
  utilityModel: "軽量タスク用モデル",
  utilityModelHint: "翻訳、短い要約、UI文面整形、会話履歴圧縮に使うモデルです。",
  modelPlaceholder: "例: gpt-5.1, gpt-5.5-high, gpt-5-mini",
  interventionCountdown: "Full Auto介入猶予",
  interventionCountdownHint:
    "Full Autoが仮定やboundaryを置いて進む前に、人間が捕まえられる秒数です。0ならダイアログを一切出しません。",
  seconds: "秒",
  chatInput: "Chat入力",
  chatSubmitShortcut: "送信ショートカット",
  chatSubmitShortcutHint:
    "IME変換中のEnterでは送信しません。Locale既定では、英語系はEnter送信、日本語など変換操作が多い言語はShift+Enter送信になります。",
  submitShortcutLocaleDefault: "Locale既定",
  submitShortcutEnter: "Enterで送信",
  submitShortcutShiftEnter: "Shift+Enterで送信",
  autonomyInterventionTitle: "Full Autoが続行しようとしています",
  autonomyInterventionBody: "Tablexが仮定またはboundaryを検出しました。ここで捕まえると承認ベースに切り替えて確認できます。",
  autonomyObjectiveInterventionTitle: "Codexがタスク目的を検討します",
  autonomyObjectiveInterventionBody:
    "ハーネスが脆いルールでターゲットを推定するのではなく、Full AutoはデータとProject contextをCodexに渡して目的を検討させます。ここで捕まえると承認ベースに切り替えて先に確認できます。",
  autonomyInterventionContinue: "そのまま続行",
  autonomyInterventionCatch: "捕まえて確認",
  autonomyInterventionDisabled: "介入ダイアログ無効",
  autonomyInterventionAssumed: "Full Autoはこの仮定で続行済みです。",
  autonomyInterventionTarget: "検討中の目的",
  autonomyInterventionDataset: "Dataset",
  autonomyInterventionTimeLeft: "残り",
  fullAutoModeSelected: "フルオートモードを選択しました。データが準備できたら開始してください。明示的な仮定とboundaryを置きながら前に進みます。",
  approvalModeSelected: "承認ベースモードを選択しました。データが準備できたら開始してください。根拠を準備し、リスクのある判断では承認を待ちます。",
  stopAgentLoopUserMessage: "Agent loopを停止",
  startAgentLoopUserMessage: "Agent loopを開始",
  agentLoopStopped: "Agent loopを停止しました。",
  agentLoopStarted: "Agent loopを開始しました。",
  createLocalizationTask: "AgentTaskを作成",
  localizationTaskHint:
    "Codexが将来locale packを生成・更新できるよう、Tablex管理のrunner handoffを保存します。",
  localizationTaskCreated: "Localization runner handoffを保存しました。",
  noProjectForLocalization: "Localization AgentTaskを作成する前にProjectを選択してください。",
  agentChatTitle: "Agent Chat",
  agentChatSubtitle: "永続的な会話、判断、結果報告の場です。実行中のworkerだけ右側にライブ表示されます。",
  agentWorkspacePersistent: "永続Workspace",
  agentChatPlaceholder: "例: 状況を説明して、ターゲットを相談したい、次に何を考えるべき？",
  createAgentTaskContract: "送信",
  youAsked: "あなたの依頼",
  tableeAnswered: "Tableeからの返答",
  agentReplyPendingTitle: "Codexの返答待ち",
  agentReplyPending: "受け取りました。分析エージェントの返答が届き次第、このチャットに残します。",
  agentReplyWaitMetaStatus: "Agent",
  agentReplyWaitMetaOutput: "最後のCodex出力",
  agentReplyWaitMetaRaw: "Raw",
  agentReplyWaitMetaAgo: "前",
  agentReplyFailed: "この依頼を完了できませんでした。消えないように、エラーをここに記録します。",
  chatTurnStatus: "状態",
  earlierConversation: "以前の会話",
  nextActionLabel: "次に開く",
  downloadLatestAgentTaskContract: "最新のAgentTaskContractをダウンロード",
  agentTaskContractCreated: "Runner handoffを保存しました。",
  chatActionOpen: "開く",
  chatActionReview: "確認",
  chatChangedLabel: "変更",
  chatReviewLabel: "要確認",
  agentActivityTitle: "Agent Activity",
  agentActivitySubtitle: "実行中または待機中のworkを表示します。完了後の要約はAgent Chatに残ります。",
  agentActivityLiveOnly: "稼働中",
  turnStateObserved: "観測状態",
  turnStateSource: "Tablexのjob状態とlocal Codex process状態から観測しています。",
  turnStateWaitingForUser: "あなたの入力待ち",
  turnStateAgentRunning: "Codexが作業中",
  turnStateWorkerPending: "worker待ち",
  turnStateAgentScheduled: "Codexが自動再開予定",
  turnStateStaleRunner: "runner状態の確認が必要",
  turnStateNeedsAttention: "実行中のAgent turnが観測されていません",
  turnStateUserTurnHint: "Codexは停止中です。入力欄が次の指示を受け取れる状態です。",
  turnStateAgentTurnHint: "CodexまたはTablex workerが動作中です。追加メッセージはworkspaceに残せます。",
  turnStateWorkerPendingHint: "Tablex workerが待機または実行中です。進行中の作業はアクティビティカードに表示されます。",
  turnStateAgentScheduledHint: "この瞬間のCodex processは観測されていませんが、Full Autoは継続予定です。",
  turnStateNeedsAttentionHint: "実行中のCodex turnは観測されていません。必要なら入力欄または開始ボタンから再開できます。",
  estimatedTokens: "推定tokens",
  currentTokens: "現在",
  cumulativeTokens: "累積",
  telemetryEstimate: "活動量の推定",
  telemetryWaiting: "開始待ち",
  workerCancelLabel: "キャンセル",
  workerStatusQueued: "待機中",
  workerStatusRunning: "実行中",
  workerStatusApproval: "承認待ち",
  workerStatusWaitingForAgent: "Codex返答待ち",
  workerStatusWaitingForRunner: "Codex再試行待ち",
  workerStatusFinished: "完了",
  workerDisplayAutonomousSession: "自律セッション",
  workerDisplayTraining: "学習Worker",
  workerDisplayNotebook: "ノートブックWorker",
  workerDisplayResearch: "調査Worker",
  workerDisplayAgentRunner: "Agent Runner",
  workerDisplayHarness: "Harness Worker",
  workerDisplayOrchestrator: "Tablee Orchestrator",
  workerOptimisticHeadline: "依頼を読み取り、プロジェクト文脈を確認しています。",
  workerWaitingSummaryPrefix: "local workerが拾うのを待っています。",
  workerWaitingNoTelemetry: "開始前のため、まだlive token telemetryはありません。",
  workerMainAgentWaitTitle: "Codexの返答待ち",
  workerMainAgentWaitSummary: "あなたの入力はメインCodexセッションに届いています。次のCodexによる説明がChatに表示されます。",
  workerRunBaselineTitle: "適応ベースラインを学習",
  workerRunBaselineSummary:
    "採用済みの評価設計を使って現在の適応型tabular baselineを学習し、Leaderboardで比較できるrun evidenceを保存します。",
  workerTrainCandidatesTitle: "候補モデルを学習",
  workerTrainCandidatesSummary:
    "同じsplitとmetric surfaceで候補モデルを学習し、Leaderboardで公平に比較できるようにします。",
  workerRunCodexTaskTitle: "準備済みAgent TaskをCodexで実行",
  workerRunCodexTaskSummary:
    "準備済みAgentTaskContractを実行し、artifact、finding、次の推奨をハーネスへ返します。",
  workerContinueSessionTitle: "メインFull Autoセッションを継続",
  workerContinueSessionSummary:
    "子workerやCodexが制御を返した後も、自律的なdata-science threadを止めずに進めます。",
  workerProjectLabel: "プロジェクト",
  workerJobLabel: "ジョブ",
  workerElapsedLabel: "経過",
  workerIdLabel: "ID",
  workerChatPlaceholder: "このworkerにメッセージ",
  noAgentActivity: "chat、job、runner workが始まるとagent activityが表示されます。",
  missionControlTitle: "Mission Control",
  missionControlSubtitle: "次の判断、現在の計画、Agentとの会話をここに集約します。根拠面にはワンクリックで移動できます。",
  autonomyMode: "自律モード",
  autonomyPower: "Agent電源",
  startAgent: "開始",
  stopAgent: "停止",
  agentPowerReady: "データアップロード後に開始できます",
  agentPowerNeedsData: "データをアップロードするとAgent run loopを開始できます。",
  agentPowerOn: "Agent loopはONです",
  agentPowerOff: "Agent loopはOFFです",
  targetCanWait: "ターゲットは今設定しても、Agentに作らせても、Data Understanding後に確定しても構いません。",
  targetColumnLabel: "目的 / ターゲット",
  targetPlaceholder: "列を選ぶ、派生ターゲットを書く、または未設定のまま進める",
  setTarget: "ターゲットを設定",
  clearTarget: "ターゲットを解除",
  targetSaved: "ターゲットを保存しました",
  targetSuggestions: "列候補",
  targetSuggestionsEmpty: "テーブルを追加または選択すると列候補が表示されます。",
  primaryTableLabel: "Primary table",
  primaryTableHelp: "予測1行の粒度を定義するテーブルを選びます。補助テーブルはCodexがjoin/aggregate設計に使えます。",
  queuedTablesTitle: "アップロード対象テーブル",
  uploadCompleteChatMessage: "アップロードが完了しました。Data Understanding artifactとmarimo notebookをこのworkspaceに登録しています。",
  approvalBasedMode: "承認ベース",
  approvalBasedModeHint: "重要判断、外部実行、評価変更、deployment関連は人間の承認を待ちます。",
  fullAutoMode: "フルオート",
  fullAutoModeHint: "質問は残しつつ、仮定とfallback policyを明示して前に進みます。",
  researchPlanTitle: "リサーチプラン",
  researchPlanEmpty: "有効なResearchPlanはまだありません。Agentを開始するかChatで依頼すると、必要な時にTablexが計画artifactを作ります。",
  researchPlanTimelineHint: "Codexが状況に応じてProject固有のブロックを右へ継ぎ足します。",
  researchPlanDetailNextAction: "次の行動",
  researchPlanDetailDoneCriteria: "完了条件",
  researchPlanDetailBlockers: "止めているもの",
  researchPlanDetailEvidence: "根拠",
  researchPlanDetailLocaleRefresh: "表示言語",
  researchPlanLocaleRefreshDetail: "Codexがこの計画ブロックを選択中の言語で更新する必要があります。",
  researchPlanBlockLocaleRefreshTitle: "表示言語の更新待ち",
  researchPlanSummaryBlock: "ブロック",
  researchPlanSummaryBlocks: "ブロック",
  planBlockDataUpload: "データアップロード",
  planBlockDataUploadPending: "CSV/Parquetを投入するか、benchmarkをimportするとloopを開始できます。",
  planBlockDataUploadDone: "DatasetSnapshotがあります。",
  planBlockObjective: "目的設定",
  planBlockObjectivePending: "目的は列、派生集計、教師なし、逆問題なども含めてCodexが提案できます。",
  planBlockObjectiveDone: "目的設定の根拠が登録されています。",
  planBlockObjectiveSkipped: "Full AutoはここをCodexに委譲し、明示的な仮定boundaryを残して先に進んでいます。",
  planBlockObjectiveDelegated: "Codexに委譲",
  planBlockUnderstanding: "データ理解",
  planBlockUnderstandingPending: "schema、欠損、行の意味、leakage risk、必要ならtarget-aware evidenceを確認します。",
  planBlockUnderstandingNeedsNotebook: "作業証跡はありますが、読めるData Understanding notebookはまだ登録されていません。",
  planBlockUnderstandingDone: "読めるData Understanding evidenceがあります。",
  planBlockPriorResearch: "従来知見の調査",
  planBlockPriorResearchPending: "Kaggle、arXiv、Skill、Codex裁量の情報源から知見を追加します。",
  planBlockPriorResearchActive: "Codexがこのステップを進めています。調査知見または追加調査不要の判断はまだ登録されていません。",
  planBlockPriorResearchPrepared: "調査コンテキストは準備済みですが、取得済みの知見と読めるNotebookはまだ登録されていません。",
  planBlockPriorResearchDone: "取得済みの調査知見と根拠があります。",
  planBlockPriorResearchNoFindings: "Codexが調査または確認し、追加すべき外部知見はないと判断しました。",
  planBlockCodexLane: "Codex作業",
  planBlockCodexRunning: "Codexがこのプロジェクトのworkspaceで作業中です。",
  planBlockCodexWaiting: "Codex sessionは準備済みです。次の実行ターンがここに表示されます。",
  strategyActionUploadData: "データをアップロード",
  strategyActionUploadDataReason: "Project固有のstrategyには少なくとも1つのDatasetSnapshotが必要です。",
  strategyActionExploreObjective: "目的候補を探索",
  strategyActionExploreObjectiveReason:
    "直接target、派生集計、教師なし、逆問題などを含めて、CodexにこのProject固有の目的をレビューさせます。",
  strategyActionResolveAssumptions: "重要な仮定を確認",
  strategyActionResolveAssumptionsReason: "評価、特徴量の安全性、deployment判断に影響する仮定だけを確認します。",
  strategyActionLockEvaluation: "評価設計を確定",
  strategyActionLockEvaluationReason: "モデル比較を信頼する前に、EvaluationSpecとSplitManifestを確定します。",
  planStatusDone: "完了",
  planStatusActive: "実行中",
  planStatusPending: "次",
  planStatusBlocked: "要確認",
  planStatusWaiting: "待機",
  planStatusSkipped: "委譲中",
  planSubtaskSingular: "サブタスク",
  planSubtaskPlural: "サブタスク",
  planLaneEvaluation: "評価設計",
  planLaneBaseline: "モデリング実験",
  planLaneReporting: "レポート作成",
  planLaneNotebook: "Notebook分析",
  openNotebookViewer: "ノートブックを開く",
  notebookCreatedChatMessage: "marimo notebookをAssetとして保存し、関連するコンテキストに紐づけました。",
  notebookLinkedAssetDetail: "このChat、関連するDataset、Model、Run、Assetsから同じNotebook viewerを開けます。",
  relatedNotebooks: "ノートブック",
  noRelatedNotebooks: "紐づくノートブックはまだありません",
  currentTaskTitle: "現在のタスク",
  currentTaskIdle: "待機中",
  currentTaskEmpty: "実行中のタスクはありません。次の一手をTableeに聞くか、Agentを開始してください。",
  currentTaskWaiting: "worker待ち",
  currentTaskWaitingBody: "local workerが利用可能になると、このqueued jobを開始します。",
  runWorkerOnce: "workerを1回実行",
  agentWorkspaceTitle: "Agent workspace",
  evidenceSurfacesTitle: "根拠面",
  supportingSurfacesTitle: "支援面",
  ideasAndFindingsTitle: "Ideas & Findings",
  ideasAndFindingsEmpty: "Agentが学んだinsight、domain knowledge、候補ideaがここに蓄積されます。",
  ideasAndFindingsReady: "件の開くべきシグナル",
  openDeepDive: "深掘りを開く",
  equippedSkillsTitle: "装備中SKILL",
  equippedSkillsEmpty: "このProjectに装備されたSkillはまだありません。",
  equippedSkillBadge: "E",
  skillPanelHint: "このProjectでCodexが参照するSkillを選択・作成します。",
  skillSelectPlaceholder: "既存Skillを選択",
  skillEquipExisting: "既存Skillを装備",
  skillCreateTitle: "Skillを作成",
  skillName: "Skill名",
  skillDescription: "説明",
  skillInstructions: "指示",
  skillTags: "タグ",
  skillCreateAndEquip: "作成して装備",
  skillNoAvailable: "未装備のSkillはありません。Libraryをseedするか、ここで作成してください。",
  agentModeChat: "Chat",
  agentModeRaw: "Raw",
  rawAgentTitle: "Codex生ログ",
  rawAgentEmpty: "Codexの実行transcriptはまだありません。Agentを開始するか、メッセージを送るとここに表示されます。",
  rawAgentTail: "tail",
  rawAgentStdout: "stdout",
  rawAgentStderr: "stderr",
  rawAgentUpdated: "更新",
  rawAgentIndexedEvents: "整形済みtranscript events",
  rawAgentRawJsonl: "Raw JSONL",
  rawAgentRawLine: "Raw line",
  rawAgentParsedEvent: "Parsed event",
  rawAgentOpenStdout: "stdout全文を開く",
  rawAgentOpenStderr: "stderr全文を開く",
  openSurface: "開く",
  strategyBriefTitle: "Adaptive Strategy Brief",
  strategyBriefSubtitle: "現在の根拠に基づく次の一手を表示します。",
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
      displayTheme: parsed.displayTheme === "dark" ? "dark" : "light",
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
    displayTheme: serverSettings.displayTheme === "dark" || serverSettings.displayTheme === "light" ? serverSettings.displayTheme : current.displayTheme,
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
    normalized.includes("japanese") ||
    normalized.includes("chinese") ||
    normalized.includes("korean")
  );
}

function localeLanguage(locale: string | null | undefined): string {
  return (locale ?? "").trim().replace("_", "-").split("-", 1)[0].toLowerCase();
}

function localeLooksJapanese(locale: string | null | undefined): boolean {
  const normalized = (locale ?? "").trim().toLowerCase().replace("_", "-");
  if (!normalized) return false;
  const language = normalized.split("-", 1)[0];
  return language === "ja" || normalized === "japanese" || normalized === "日本語" || normalized.startsWith("日本語");
}

function localeRequiresLocalizedDisplay(locale: string | null | undefined): boolean {
  const language = localeLanguage(locale);
  return Boolean(language && language !== "en");
}

function displayTextMatchesLocale(value: string | null | undefined, locale: string | null | undefined): boolean {
  const text = (value ?? "").trim();
  if (!text) return false;
  if (!localeRequiresLocalizedDisplay(locale)) return true;
  if (localeLooksJapanese(locale)) {
    const japaneseCharCount = text.match(/[\u3040-\u30ff\u3400-\u9fff]/g)?.length ?? 0;
    const latinLetterCount = text.match(/[A-Za-z]/g)?.length ?? 0;
    if (hasUnlocalizedLatinPhrase(text)) return false;
    return japaneseCharCount >= 2 && latinLetterCount <= Math.max(18, Math.floor(japaneseCharCount * 1.5));
  }
  return false;
}

function hasUnlocalizedLatinPhrase(value: string): boolean {
  const stripped = value.replace(/`[^`]*`/g, " ").replace(/https?:\/\/\S+/g, " ");
  return stripped
    .split(/[\u3040-\u30ff\u3400-\u9fff]+/)
    .some((fragment) => (fragment.match(/\b[A-Za-z][A-Za-z-]{2,}\b/g)?.length ?? 0) >= 2);
}

function localeSafeDisplayText(value: string | null | undefined, locale: string | null | undefined, fallback: string): string {
  const text = (value ?? "").trim();
  if (displayTextMatchesLocale(text, locale)) return text;
  return fallback;
}

function shouldSubmitTextarea(
  event: React.KeyboardEvent<HTMLTextAreaElement>,
  shortcut: ChatSubmitShortcut
): boolean {
  if (event.key !== "Enter") return false;
  if (event.nativeEvent.isComposing) return false;
  if (event.altKey || event.ctrlKey || event.metaKey) return false;
  return shortcut === "enter" ? !event.shiftKey : event.shiftKey;
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

type AutonomyMode = "approval_based" | "full_auto";
type TableeMotionState = "idle" | "awake" | "working";

type Project = {
  id: string;
  name: string;
  description: string | null;
  task_type: string | null;
  target_column: string | null;
  current_phase: string;
  status: string;
  autonomy_mode: AutonomyMode;
  created_by: string;
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

type SemanticCatalog = {
  id: string;
  project_id: string;
  dataset_snapshot_id: string;
  artifact_id: string | null;
  columns: Array<Record<string, unknown> | string>;
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

type RunnerReadinessFeedback = {
  contractArtifactId: string;
  status: string;
  blockerCount: number;
  warningCount: number;
  passCount: number;
  nextActions: string[];
  source: "latest_artifact" | "current_review";
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

type EvidenceReaderMetric = {
  label: string;
  value: React.ReactNode;
  tone?: "ready" | "warning" | "risk" | "muted";
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
    evidence_bundle: string | null;
    evidence_html: string | null;
    evidence_figures: string[];
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

type AnalysisStorySurface = {
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

type AnalysisStory = {
  source_type: string;
  headline: string;
  deck: string;
  why_this_story: string;
  selected_source: {
    source_type: string;
    title: string;
    artifact_id: string;
    preview_artifact_id: string | null;
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

type AutonomyIntervention = {
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

type PendingAutonomyIntervention = {
  payload: AutonomyIntervention;
  startedAt: number;
  durationSeconds: number;
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

type AgentRetryState = {
  event_type?: string;
  event_index?: number;
  created_at?: string;
  retry_delay_seconds?: number;
  failure_kind?: string;
  exit_code?: number;
  idle_timeout_seconds?: number;
};

type AgentWorkerEvent = {
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
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
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

type AgentSession = {
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

type AgentTranscriptEvent = {
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

type AgentRawTranscript = {
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

type AgentRawTranscriptLine = {
  line_number: number;
  text: string;
  parsed: Record<string, unknown> | null;
};

type AgentRawTranscriptViewLine = AgentRawTranscriptLine & {
  stream: "stdout" | "stderr";
};

type RequiredHumanDescription = {
  title: string;
  summary: string;
  source?: string;
};

type AgentChatAction = {
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
  entity_ids?: string[];
};

type AgentActionSummary = {
  schema_version: string;
  outcome: string;
  headline: string;
  what_changed: string[];
  what_needs_review: string[];
  next_step: { label?: string | null; target_tab?: string | null; target_anchor?: string | null; status?: string | null };
  boundaries: string[];
  actions: Array<Record<string, unknown>>;
};

type AgentChatResponse = {
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

type AgentChatHistoryTurn = Omit<AgentChatResponse, "job"> & {
  job_id: string | null;
  created_at: string;
};

type AgentChatMessage = {
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

type AgentConversationTurn = {
  id: string;
  user?: AgentChatMessage;
  assistant?: AgentChatMessage;
  createdAt?: string;
};

const AGENT_CHAT_MESSAGE_HISTORY_LIMIT = 240;

type ArtifactPreviewRequest = {
  artifactId: string;
  targetTab: Tab;
  anchor?: string | null;
  nonce: number;
};

type HomeMemoryItem = {
  id: string;
  kind: "idea" | "finding";
  title: string;
  summary: string;
  meta: string;
  cta: string;
  target_tab: string;
  target_anchor: string;
  created_at: string;
  signal_priority: number;
};

type EquippedSkillItem = {
  id: string;
  name: string;
  description: string | null;
  tags: string[];
  relation_type: string;
};

type SkillDraft = {
  name: string;
  description: string;
  instructions: string;
  tags: string;
};

type RawAgentEvent = {
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

type UploadFileProgress = {
  key: string;
  name: string;
  kind: string;
  size: number;
  progress: number;
};

type UploadBundleProgress = {
  active: boolean;
  overall: number;
  loadedBytes: number;
  totalBytes: number;
  files: UploadFileProgress[];
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
  turn_state: TurnState;
  workers: AgentWorkerEvent[];
};

type TurnState = {
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
  display_metric_name: string | null;
  display_metric_value: number | null;
  display_metric_available: boolean;
  display_metric_source: string;
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

type ResearchPlanBlockStatus = "done" | "active" | "pending" | "blocked" | "waiting" | "skipped";

type PendingAnchorNavigation = {
  anchor: string;
  nonce: number;
};

type ResearchPlanSubtask = {
  id: string;
  title: string;
  detail: string;
  status: ResearchPlanBlockStatus;
  evidence: string | null;
  targetTab?: Tab | null;
  targetAnchor?: string | null;
  onClick?: () => void;
};

type ResearchPlanBlock = {
  id: string;
  title: string;
  subtitle: string;
  status: ResearchPlanBlockStatus;
  eyebrow: string;
  evidence: string | null;
  subtasks?: ResearchPlanSubtask[];
  onClick?: () => void;
};

type ResearchPlanTimelineBlock = {
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
  localization_status?: "localized" | "needs_locale_refresh";
  missing_localization_fields?: string[];
  subtasks: Array<{
    id: string;
    title: string;
    detail: string;
    status: ResearchPlanBlockStatus;
    evidence: string | null;
    target_tab: string | null;
    target_anchor: string | null;
    localization_status?: "localized" | "needs_locale_refresh";
    missing_localization_fields?: string[];
  }>;
};

type ResearchPlanTimelineResponse = {
  schema_version: "research_plan_timeline.v1";
  project_id: string;
  source_artifact_id: string | null;
  response_locale?: string | null;
  generated_at: string;
  localization?: {
    requested_locale?: string | null;
    requires_explicit_locale?: boolean;
    missing_block_count?: number;
    missing_subtask_count?: number;
    blocks?: Array<{ id: string; title: string; missing_fields: string[] }>;
  };
  blocks: ResearchPlanTimelineBlock[];
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

type ResultReadout = {
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
  { id: "Reports", labelKey: "tabReports" },
  { id: "Assets", labelKey: "tabAssets" },
  { id: "Library", labelKey: "tabLibrary" },
  { id: "Jobs", labelKey: "tabJobs" },
  { id: "Lineage", labelKey: "tabLineage" }
] as const satisfies ReadonlyArray<{ id: string; labelKey: keyof LocaleMessages }>;
type Tab = (typeof tabItems)[number]["id"];
const topLevelTabIds = new Set<Tab>(["Home", "Data", "Insight", "Leaderboard", "Assets"]);
const hiddenLegacyTabIds = new Set<Tab>(["Overview", "Approach"]);
const primaryTabItems = tabItems.filter((item) => topLevelTabIds.has(item.id));
const supportingTabItems = tabItems.filter((item) => !topLevelTabIds.has(item.id) && !hiddenLegacyTabIds.has(item.id));
const supportingTabIdSet = new Set<Tab>(supportingTabItems.map((item) => item.id));

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
  if (value === "Overview" || value === "Approach") return "Home";
  if (value === "Reports" || value === "Notebooks") return "Insight";
  if (value === "Library" || value === "Lineage") return "Assets";
  const match = tabItems.find((item) => item.id === value);
  return match ? match.id : fallback;
}

function autoStartWorkerJobIds(actions: AgentChatAction[]): string[] {
  return actions
    .filter((action) => action.auto_start_worker && action.job_id)
    .map((action) => action.job_id)
    .filter((jobId): jobId is string => Boolean(jobId));
}

function notebookChatMessageFromJob(result: unknown, text: LocaleMessages): AgentChatMessage | null {
  if (!isJobResult(result)) return null;
  const sourceArtifactId = textField(result.output.analysis_notebook_artifact_id);
  const notebookHtmlArtifactId =
    textField(result.output.notebook_html_artifact_id) ??
    textField(result.output.notebook_evidence_html_artifact_id) ??
    textField(result.output.notebook_execution_html_artifact_id);
  if (!sourceArtifactId && !notebookHtmlArtifactId) return null;
  const artifactId = notebookPreviewArtifactIdFromJob(result);
  const notebookKind = textField(result.output.notebook_kind) ?? result.job_type.replace(/_/g, " ");
  const linkedContext = notebookLinkedContext(result.output);
  const previewArtifactId = artifactId ?? sourceArtifactId;
  if (!previewArtifactId) return null;
  const action: AgentChatAction = {
    type: "open_artifact",
    status: "ready",
    label: text.openNotebookViewer,
    target_tab: "Notebooks",
    target_anchor: "notebook-preview-top",
    detail: linkedContext || text.notebookLinkedAssetDetail,
    artifact_id: previewArtifactId,
    artifact_ids: [sourceArtifactId, artifactId].filter((value): value is string => Boolean(value))
  };
  return {
    id: `notebook-created:${result.id}:${previewArtifactId}`,
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

function notebookPreviewArtifactIdFromJob(job: Job): string | null {
  return (
    textField(job.output.preview_artifact_id) ??
    textField(job.output.notebook_evidence_html_artifact_id) ??
    textField(job.output.notebook_execution_html_artifact_id) ??
    textField(job.output.notebook_html_artifact_id) ??
    textField(job.output.notebook_report_artifact_id) ??
    textField(job.output.report_artifact_id) ??
    textField(job.output.analysis_notebook_artifact_id)
  );
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

function uploadFormData<T>(
  path: string,
  body: FormData,
  onProgress: (event: ProgressEvent<EventTarget>) => void
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBase}${path}`);
    xhr.upload.onprogress = onProgress;
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

function App() {
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
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const hydratedUserIdRef = React.useRef<string | null>(null);
  const moreTabsRef = React.useRef<HTMLDivElement | null>(null);
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

  const refreshProjects = React.useCallback(async (preferredProjectId?: string) => {
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
      if (preferredProjectId) {
        setSelectedProjectId(preferredProjectId);
      } else if (!selectedProjectId && data[0]) {
        setSelectedProjectId(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
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
    const response = await api<{ candidates: AvatarCandidate[] }>("/api/user/avatar-candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, count: 3 })
    });
    return response.candidates;
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
            <button
              key={project.id}
              className={project.id === selectedProjectId && viewMode === "project" ? "project-item active" : "project-item"}
              onClick={() => openProject(project.id)}
            >
              <span>{project.name}</span>
              <small>{formatWorkflowState(project.current_phase)}</small>
            </button>
          ))}
        </div>
        <CreateProjectForm
          text={text}
          onCreated={async (project) => {
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
              {primaryTabItems.map((item) => (
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
            </nav>
            <ProjectDetail
              project={activeProject}
              tab={tab}
              text={text}
              userSettings={userSettings}
              onTabChange={setTab}
              onProjectChanged={refreshProjects}
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

function numberFromSummary(value: unknown, fallback: number | string): number | string {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function projectInProgressForPortal(project: Project): boolean {
  return ["AUTONOMOUS_LOOP", "UNDERSTANDING_REVIEW"].includes(project.current_phase);
}

function AuthGate({
  status,
  text,
  error,
  onSubmit
}: {
  status: AuthStatus;
  text: LocaleMessages;
  error: string | null;
  onSubmit: (email: string, password: string, displayName: string | null) => Promise<void>;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setLocalError(null);
    try {
      await onSubmit(email.trim(), password, displayName.trim() || null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand">
          <img src="/mascot/tablee-success.svg" alt="" aria-hidden="true" />
          <div>
            <span>Tablex</span>
            <h1>{text.signInTitle}</h1>
            <p>{text.signInBody}</p>
          </div>
        </div>
        {error || localError ? <div className="banner danger">{localError ?? error}</div> : null}
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          <label>
            <span>{text.email}</span>
            <input
              autoComplete="email"
              autoFocus
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          {status.bootstrap_required ? (
            <label>
              <span>{text.displayName}</span>
              <input
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </label>
          ) : null}
          <label>
            <span>{text.password}</span>
            <input
              autoComplete={status.bootstrap_required ? "new-password" : "current-password"}
              minLength={10}
              pattern="(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{10,}"
              title={text.passwordRequirement}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <small>{text.passwordRequirement}</small>
          </label>
          <button className="primary-button" disabled={busy || !email.trim() || !password} type="submit">
            {busy ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
            {status.bootstrap_required ? text.createFirstUser : text.signIn}
          </button>
        </form>
        <div className="auth-provider-row">
          <span className="badge">{text.passwordAuth}</span>
          {status.google_auth_enabled ? (
            <span className="badge muted">Google</span>
          ) : (
            <small>{text.googleAuthComingSoon}</small>
          )}
        </div>
      </section>
    </main>
  );
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
  const activeCount = numberFromSummary(summary.active_project_count, projects.filter(projectInProgressForPortal).length);
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

  React.useEffect(() => {
    if (!avatarBusy || avatarStartedAt === null) return undefined;
    const tick = () => setAvatarElapsedSeconds(Math.max(0, Math.floor((Date.now() - avatarStartedAt) / 1000)));
    tick();
    const handle = window.setInterval(tick, 1000);
    return () => window.clearInterval(handle);
  }, [avatarBusy, avatarStartedAt]);

  function update(patch: Partial<UserSettings>) {
    setLocaleStatus(null);
    setAvatarStatus(null);
    onChange({ ...settings, ...patch });
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

function ProjectDetail({
  project,
  tab,
  text,
  userSettings,
  onTabChange,
  onProjectChanged
}: {
  project: Project;
  tab: Tab;
  text: LocaleMessages;
  userSettings: UserSettings;
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
  const visibleAgentChatMessages = React.useMemo(
    () => mergeAgentChatMessages(agentChatMessages, pendingAgentChatMessages),
    [agentChatMessages, pendingAgentChatMessages]
  );
  const liveAgentOrModelActivity = hasLiveAgentOrModelActivity(jobs, agentWorkerEvents, agentActivity);
  const tableeMotionState: TableeMotionState = liveAgentOrModelActivity
    ? "working"
    : project.current_phase === "AUTONOMOUS_LOOP"
      ? "awake"
      : "idle";
  const turnState = agentActivity?.turn_state ?? fallbackTurnState(project);
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
        resultReadoutData,
        visualizationsData,
        notebookIndexData,
        analysisStoryData,
        agentTaskResultsData,
        insightsData,
        libraryAssetsData,
        projectAssetReferencesData,
        lineageData,
        agentChatHistoryData,
        agentActivityData,
        agentSessionData,
        agentTranscriptData,
        agentRawTranscriptData,
        researchPlanTimelineData,
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
        api<Artifact[]>(`/api/projects/${project.id}/artifacts?limit=1000`),
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
        api<ResultReadout>(`/api/projects/${project.id}/results/readout`).catch(() => null),
        api<VisualizationSpec[]>(`/api/projects/${project.id}/visualizations`),
        api<NotebookIndex>(`/api/projects/${project.id}/analysis-notebooks`).catch(() => null),
        api<AnalysisStorySurface>(`/api/projects/${project.id}/analysis-story`).catch(() => null),
        api<AgentTaskResult[]>(`/api/projects/${project.id}/agent-task-results`),
        api<Insight[]>(`/api/projects/${project.id}/insights`),
        api<LibraryAsset[]>(`/api/assets`),
        api<AssetReference[]>(`/api/projects/${project.id}/asset-references`),
        api<LineageEdge[]>(`/api/projects/${project.id}/lineage`),
        api<AgentChatHistoryTurn[]>(`/api/projects/${project.id}/agent-chat/history`).catch(() => []),
        api<AgentActivityResponse>(`/api/projects/${project.id}/agent-activity`).catch(() => null),
        api<AgentSession | null>(`/api/projects/${project.id}/agent-session/current`).catch(() => null),
        api<AgentTranscriptEvent[]>(`/api/projects/${project.id}/agent-session/transcript`).catch(() => []),
        api<AgentRawTranscript>(`/api/projects/${project.id}/agent-session/raw-transcript`).catch(() => null),
        api<ResearchPlanTimelineResponse>(
          `/api/projects/${project.id}/research-plan/timeline?locale=${encodeURIComponent(userSettings.locale)}`
        ).catch(() => null),
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
      setResultReadout(resultReadoutData);
      setVisualizations(visualizationsData);
      setNotebookIndex(notebookIndexData);
      setAnalysisStory(analysisStoryData);
      setAgentTaskResults(agentTaskResultsData);
      setInsights(insightsData);
      setLibraryAssets(libraryAssetsData);
      setProjectAssetReferences(projectAssetReferencesData);
      setAgentChatMessages((current) => mergeAgentChatMessages(agentChatHistoryToMessages(agentChatHistoryData), current));
      setAgentActivity(agentActivityData);
      setAgentSession(agentSessionData);
      setAgentTranscriptEvents(agentTranscriptData);
      setAgentRawTranscript(agentRawTranscriptData);
      setResearchPlanTimeline(researchPlanTimelineData);
      transcriptSessionIdRef.current = agentSessionData?.id ?? null;
      transcriptSinceIndexRef.current = maxTranscriptEventIndex(agentTranscriptData);
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
  }, [project.id, userSettings.locale]);

  const refreshAgentActivity = React.useCallback(async () => {
    try {
      const [data, sessionData, rawTranscriptData, agentChatHistoryData, researchPlanTimelineData] = await Promise.all([
        api<AgentActivityResponse>(`/api/projects/${project.id}/agent-activity`),
        api<AgentSession | null>(`/api/projects/${project.id}/agent-session/current`).catch(() => null),
        api<AgentRawTranscript>(`/api/projects/${project.id}/agent-session/raw-transcript?limit=8`).catch(() => null),
        api<AgentChatHistoryTurn[]>(`/api/projects/${project.id}/agent-chat/history`).catch(() => []),
        api<ResearchPlanTimelineResponse>(
          `/api/projects/${project.id}/research-plan/timeline?locale=${encodeURIComponent(userSettings.locale)}`
        ).catch(() => null)
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
      setAgentSession(sessionData);
      setAgentRawTranscript(rawTranscriptData);
      if (researchPlanTimelineData) {
        setResearchPlanTimeline(researchPlanTimelineData);
      }
      setAgentChatMessages((current) => mergeAgentChatMessages(agentChatHistoryToMessages(agentChatHistoryData), current));
      setAgentTranscriptEvents((current) => {
        const next = sinceIndex === null ? transcriptData : mergeTranscriptEvents(current, transcriptData);
        transcriptSessionIdRef.current = sessionId;
        transcriptSinceIndexRef.current = maxTranscriptEventIndex(next);
        return next;
      });
    } catch {
      // The activity overlay is opportunistic; project refresh still surfaces hard errors.
    }
  }, [project.id, userSettings.locale]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

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
    const intervalMs = busy || liveAgentOrModelActivity ? 900 : project.current_phase === "AUTONOMOUS_LOOP" ? 2400 : 12000;
    const interval = window.setInterval(
      () => {
        setActivityTick((current) => current + 1);
        void refreshAgentActivity();
      },
      intervalMs
    );
    return () => window.clearInterval(interval);
  }, [busy, liveAgentOrModelActivity, project.current_phase, refreshAgentActivity]);

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

  function navigateToTarget(targetTab: Tab, targetAnchor?: string | null) {
    if (targetAnchor) setPendingAnchor({ anchor: targetAnchor, nonce: Date.now() });
    onTabChange(targetTab);
  }

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      const notebookMessage = notebookChatMessageFromJob(result, text);
      if (notebookMessage) {
        setAgentChatMessages((current) => upsertAgentChatMessages(current, [notebookMessage]));
      }
      await refresh();
      await onProjectChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
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
          locale: userSettings.locale,
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

  async function changeAutonomyMode(nextMode: AutonomyMode): Promise<void> {
    const currentMode = project.autonomy_mode ?? "approval_based";
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
      await api<Project>(`/api/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autonomy_mode: nextMode, locale: userSettings.locale })
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
    const poweredOn = project.current_phase === "AUTONOMOUS_LOOP";
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
      const job = await api<Job>(`/api/projects/${project.id}/autonomy/${poweredOn ? "stop" : "start"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: poweredOn
          ? JSON.stringify({ locale: userSettings.locale })
          : JSON.stringify({
              autonomy_mode: project.autonomy_mode,
              runner_mode: project.autonomy_mode === "full_auto" ? "codex_cli_if_available" : "harness_only",
              locale: userSettings.locale,
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
    const explicitNotebookViewer = action.artifact_id && action.target_tab === "Notebooks";
    const targetTab = explicitNotebookViewer ? "Notebooks" : tabFromString(action.target_tab, "Home");
    if (action.artifact_id) {
      setArtifactPreviewRequest({
        artifactId: action.artifact_id,
        targetTab,
        anchor: action.target_anchor ?? null,
        nonce: Date.now()
      });
    }
    navigateToTarget(targetTab, action.target_anchor ?? null);
  }

  function openHomeMemoryItem(item: HomeMemoryItem) {
    navigateToTarget(tabFromString(item.target_tab, "Insight"), item.target_anchor);
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
          jobs={jobs}
          events={agentWorkerEvents}
          activity={agentActivity}
          tick={activityTick}
          onWorkerMessage={submitAgentChatWithoutResponse}
          onCancelWorker={cancelWorkerJob}
        />
      {tab === "Home" && (
        <HomeTab
          project={project}
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
          locale={userSettings.locale}
          messages={visibleAgentChatMessages}
          submitShortcut={resolveChatSubmitShortcut(userSettings)}
          userAvatarSrc={userSettings.userAvatarDataUrl}
          latestContract={artifacts.find((artifact) => artifact.asset_type === "agent_task_contract") ?? null}
          tableeMotionState={tableeMotionState}
          turnState={turnState}
          agentSession={agentSession}
          agentTranscriptEvents={agentTranscriptEvents}
          agentRawTranscript={agentRawTranscript}
          onSubmitAgentChat={submitAgentChatWithoutResponse}
          onActionOpen={openAgentChatAction}
          onOpenMemoryItem={openHomeMemoryItem}
          onTabChange={onTabChange}
          onNavigateToTarget={navigateToTarget}
          onFocusAction={(action) => void runFocusAction(action)}
          onEquipSkill={(asset) => runAction(() => equipLibraryAsset(asset))}
          onCreateSkill={(draft) => runAction(() => createAndEquipSkill(draft))}
          onAutonomyModeChange={(mode) => void changeAutonomyMode(mode)}
          onAutonomyPowerToggle={() => void toggleAutonomyPower()}
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
          project={project}
          reports={reports}
          decisionReport={decisionReport}
          artifacts={artifacts}
          visualizations={visualizations}
          notebookIndex={notebookIndex}
          ideas={ideas}
          insights={insights}
          busy={busy}
          locale={userSettings.locale}
          runAction={runAction}
        />
      )}
      {tab === "Data" && (
        <DataTab
          project={project}
          datasets={datasets}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          benchmarks={benchmarks}
          jobs={jobs}
          busy={busy}
          text={text}
          locale={userSettings.locale}
          runAction={runAction}
          onOpenNotebookArtifact={(artifactId) => {
            setArtifactPreviewRequest({
              artifactId,
              targetTab: "Notebooks",
              anchor: "notebook-preview-top",
              nonce: Date.now()
            });
            navigateToTarget("Notebooks", "notebook-preview-top");
          }}
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
          notebookIndex={notebookIndex}
          busy={busy}
          text={text}
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
          analysisStory={analysisStory}
          previewRequest={artifactPreviewRequest}
          busy={busy}
          locale={userSettings.locale}
          runAction={runAction}
          onAskAgent={submitAgentChat}
        />
      )}
      {tab === "Leaderboard" && (
        <LeaderboardTab
          project={project}
          specs={specs}
          artifacts={artifacts}
          notebookIndex={notebookIndex}
          leaderboard={leaderboard}
          resultReadout={resultReadout}
          busy={busy}
          text={text}
          runAction={runAction}
          onAskAgent={submitAgentChat}
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
          ideas={ideas}
          insights={insights}
          busy={busy}
          locale={userSettings.locale}
          runAction={runAction}
        />
      )}
      {tab === "Assets" && (
        <AssetsTab
          project={project}
          artifacts={artifacts}
          modelVersions={modelVersions}
          validationsByModelVersion={validationsByModelVersion}
          notebookIndex={notebookIndex}
          libraryAssets={libraryAssets}
          projectAssetReferences={projectAssetReferences}
          busy={busy}
          text={text}
          runAction={runAction}
          onEquipSkill={(asset) => runAction(() => equipLibraryAsset(asset))}
          onCreateSkill={(draft) => runAction(() => createAndEquipSkill(draft))}
        />
      )}
      {tab === "Library" && (
        <LibraryTab
          project={project}
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
  onSubmitAgentChat,
  onActionOpen,
  onOpenMemoryItem,
  onTabChange,
  onNavigateToTarget,
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
  onSubmitAgentChat: (objective: string) => Promise<void>;
  onActionOpen: (action: AgentChatAction) => void;
  onOpenMemoryItem: (item: HomeMemoryItem) => void;
  onTabChange: (tab: Tab) => void;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
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
  const autonomyPoweredOn = project.current_phase === "AUTONOMOUS_LOOP";
  const canStartAutonomy = datasetCount > 0;
  const focusAction = recommendation.primaryAction;
  const [agentViewMode, setAgentViewMode] = React.useState<"chat" | "raw">("chat");
  const ideaFindingItems = buildIdeaFindingItems(ideas, insights);
  const equippedSkills = equippedSkillItems(projectAssetReferences, libraryAssets);
  const rawAgentEvents = buildRawAgentEvents(messages, jobs, agentTranscriptEvents, agentSession);
  const agentWorkspaceScrollResetKey = `${project.id}:${agentSession?.id ?? "no-agent-session"}`;
  const researchPlanBlocks = buildResearchPlanBlocks({
    project,
    datasetCount,
    artifacts,
    researchBriefs,
    researchPlanTimeline,
    notebookIndex,
    equippedSkills,
    jobs: planJobs,
    agentSession,
    turnState,
    agentTranscriptEvents,
    text,
    locale,
    onTabChange,
    onNavigateToTarget
  });
  const activeResearchPlanBlock = researchPlanBlocks.find((block) => block.status === "active") ?? null;
  const missionUsesPlanFocus = Boolean(activeResearchPlanBlock);
  const missionTitle = activeResearchPlanBlock?.title ?? recommendation.title;
  const missionReason = activeResearchPlanBlock?.subtitle ?? recommendation.reason;
  const missionRiskLevel = missionUsesPlanFocus ? "active" : (recommendation.riskLevel ?? "ready");
  const missionFocusLabel = missionUsesPlanFocus ? text.openSurface : (focusAction?.label ?? text.recommendedFocus);
  const missionFocusDisabled = busy || (!missionUsesPlanFocus && (!focusAction || focusAction.disabled));
  const handleMissionFocus = () => {
    if (missionUsesPlanFocus) {
      activeResearchPlanBlock?.onClick?.();
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
            <span className={navigatorStatusClass(missionRiskLevel)}>
              {missionRiskLevel.replace(/_/g, " ")}
            </span>
            <span className="badge muted">{formatWorkflowState(project.current_phase)}</span>
            <span className="badge muted">
              {project.target_column ? `target: ${project.target_column}` : "target not fixed"}
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

      <div className="mission-grid">
        <section className="mission-plan-panel">
          <div className="mission-panel-head">
            <div>
              <span>{text.researchPlanTitle}</span>
              <strong>
                {localeSafeDisplayText(
                  latestResearchPlan?.name ?? strategyBrief?.recommended_next_action.label,
                  locale,
                  text.researchPlanTimelineHint
                )}
              </strong>
            </div>
          </div>
          <ResearchPlanTimeline blocks={researchPlanBlocks} latestResearchPlan={latestResearchPlan} text={text} />
          <div className="mission-plan-facts">
            <Metric label="Datasets" value={projectStateLoaded ? datasetCount : "..."} />
            <Metric label="Runs" value={runs.length} />
            <Metric label="Risks" value={highRiskAssumptions.length} />
            <Metric label="Artifacts" value={projectStateLoaded ? totalArtifactCount : "..."} />
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

      <div className="mission-agent-layout">
        <div className="mission-agent-primary">
          <div className="mission-agent-head">
            <div className="mission-panel-title">
              <MessageSquare size={18} />
              <div>
                <strong>{text.agentWorkspaceTitle}</strong>
                <span>{text.missionControlSubtitle}</span>
              </div>
            </div>
            <div className="agent-view-toggle" aria-label="Agent display mode">
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
              onSubmit={onSubmitAgentChat}
            />
          )}
        </div>
        <aside className="mission-evidence-stack">
          <MissionSurfaceButton
            icon={<Database size={17} />}
            label={text.tabData}
            detail={
              projectStateLoaded
                ? `${datasetCount} datasets / ${project.target_column ? "target set" : "target open"}`
                : "..."
            }
            onClick={() => onTabChange("Data")}
          />
          <MissionSurfaceButton
            icon={<Lightbulb size={17} />}
            label={text.tabInsight}
            detail={`${insights.length} insights / ${reports.length} reports / ${recommendedNotebook ? "notebook ready" : "notebook open"}`}
            onClick={() => onTabChange("Insight")}
          />
          <MissionSurfaceButton
            icon={<BarChart3 size={17} />}
            label={text.tabLeaderboard}
            detail={
              topRun
                ? `#1 ${topRun.runner_type} ${metricLabel(topRun.display_metric_name)}=${formatMaybeNumber(topRun.display_metric_value)}`
                : "ranked model runs appear here"
            }
            onClick={() => onTabChange("Leaderboard")}
          />
          <MissionSurfaceButton
            icon={<Layers size={17} />}
            label={text.tabAssets}
            detail={
              projectStateLoaded
                ? `${totalArtifactCount} project artifacts / ${latestContract ? "runner contract ready" : "no contract yet"}`
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
              <span>Latest brief</span>
              <strong>{latestBrief.title}</strong>
              <small>{latestBrief.key_findings.slice(0, 2).join(" / ") || latestBrief.status}</small>
            </div>
          ) : null}
          {latestIdea ? (
            <div className="mission-note">
              <span>Latest idea</span>
              <strong>{latestIdea.title}</strong>
              <small>{latestIdea.hypothesis}</small>
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
  onToggle
}: {
  poweredOn: boolean;
  canStart: boolean;
  busy: boolean;
  mode: AutonomyMode;
  targetColumn: string | null;
  text: LocaleMessages;
  onToggle: () => void;
}) {
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
        <strong>{poweredOn ? text.agentPowerOn : canStart ? text.agentPowerReady : text.agentPowerNeedsData}</strong>
        <small>
          {mode === "full_auto" ? text.fullAutoMode : text.approvalBasedMode}
          {" · "}
          {targetColumn ? `target: ${targetColumn}` : text.targetCanWait}
        </small>
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
            <div className="equipped-skill" key={skill.id} title={skill.description ?? skill.name}>
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

function ResearchPlanTimeline({
  blocks,
  latestResearchPlan,
  text
}: {
  blocks: ResearchPlanBlock[];
  latestResearchPlan: Artifact | null;
  text: LocaleMessages;
}) {
  const [expandedBlockId, setExpandedBlockId] = React.useState<string | null>(null);
  const timelineRef = React.useRef<HTMLDivElement | null>(null);
  const activeBlockRef = React.useRef<HTMLButtonElement | null>(null);
  const expandedBlock = blocks.find((block) => block.id === expandedBlockId && block.subtasks?.length);
  const activeBlockKey = selectedResearchPlanBlockKey(blocks);
  const summary = researchPlanCompactSummary(blocks, text);

  React.useLayoutEffect(() => {
    if (!timelineRef.current || !activeBlockRef.current) return;
    const container = timelineRef.current;
    const active = activeBlockRef.current;
    const left = active.offsetLeft - container.clientWidth / 2 + active.clientWidth / 2;
    container.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
  }, [activeBlockKey, blocks.length]);

  return (
    <div className="research-plan-timeline-wrap">
      <div className="research-plan-timeline" aria-label={text.researchPlanTitle} ref={timelineRef}>
        {blocks.map((block, index) => (
          <React.Fragment key={block.id}>
            <button
              ref={block.id === activeBlockKey ? activeBlockRef : undefined}
              className={`research-plan-block ${block.status} ${expandedBlockId === block.id ? "expanded" : ""}`}
              disabled={!block.onClick && !block.subtasks?.length}
              onClick={() => {
                if (block.subtasks?.length) {
                  setExpandedBlockId((current) => (current === block.id ? null : block.id));
                  return;
                }
                block.onClick?.();
              }}
              type="button"
            >
              <span>{block.eyebrow}</span>
              <strong>{block.title}</strong>
              {block.subtitle ? <p>{block.subtitle}</p> : null}
              {block.subtasks?.length ? (
                <em className="research-plan-subtask-pill">
                  {block.subtasks.length} {block.subtasks.length === 1 ? text.planSubtaskSingular : text.planSubtaskPlural}
                </em>
              ) : null}
              <small>
                {researchPlanStatusLabel(block.status, text)}
                {block.evidence ? ` · ${block.evidence}` : ""}
              </small>
            </button>
            {index < blocks.length - 1 ? <div className="research-plan-connector" aria-hidden="true" /> : null}
          </React.Fragment>
        ))}
      </div>
      {expandedBlock ? (
        <div className="research-plan-subtasks">
          <div className="research-plan-subtasks-head">
            <strong>{expandedBlock.title}</strong>
            <span>
              {expandedBlock.subtasks?.length ?? 0}{" "}
              {(expandedBlock.subtasks?.length ?? 0) === 1 ? text.planSubtaskSingular : text.planSubtaskPlural}
            </span>
          </div>
          <div className="research-plan-subtask-list">
            {expandedBlock.subtasks?.map((subtask) => (
              <button
                className={`research-plan-subtask ${subtask.status}`}
                disabled={!subtask.onClick}
                key={subtask.id}
                onClick={subtask.onClick}
                type="button"
              >
                <span className={navigatorStatusClass(subtask.status)}>{researchPlanStatusLabel(subtask.status, text)}</span>
                <div>
                  <strong>{subtask.title}</strong>
                  <p>{subtask.detail}</p>
                  {subtask.evidence ? <small>{subtask.evidence}</small> : null}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className="research-plan-footer">
        <span>
          {summary}
          {summary ? " · " : ""}
          {text.researchPlanTimelineHint}
        </span>
        {latestResearchPlan ? (
          <a className="icon-link" href={`${apiBase}/api/artifacts/${latestResearchPlan.id}/download`} title="Download ResearchPlan">
            <Download size={16} />
          </a>
        ) : null}
      </div>
    </div>
  );
}

function buildResearchPlanBlocks({
  project,
  datasetCount,
  artifacts,
  researchBriefs,
  researchPlanTimeline,
  notebookIndex,
  equippedSkills,
  jobs,
  agentSession,
  turnState,
  agentTranscriptEvents,
  text,
  locale,
  onTabChange,
  onNavigateToTarget
}: {
  project: Project;
  datasetCount: number;
  artifacts: Artifact[];
  researchBriefs: ResearchBrief[];
  researchPlanTimeline: ResearchPlanTimelineResponse | null;
  notebookIndex: NotebookIndex | null;
  equippedSkills: EquippedSkillItem[];
  jobs: Job[];
  agentSession: AgentSession | null;
  turnState: TurnState;
  agentTranscriptEvents: AgentTranscriptEvent[];
  text: LocaleMessages;
  locale: string;
  onTabChange: (tab: Tab) => void;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
}): ResearchPlanBlock[] {
  const codexAuthoredBlocks = researchPlanBlocksFromTimeline(researchPlanTimeline, text, locale, onNavigateToTarget);
  const hasObjectiveEvidence = Boolean(project.target_column) || hasAnyArtifactType(artifacts, ["target_definition_proposal"]);
  const hasUnderstandingCompletionEvidence =
    hasAnyArtifactType(artifacts, ["data_understanding_complete"]) ||
    hasReviewableDataUnderstandingNotebook(notebookIndex);
  const hasUnderstandingWorkEvidence =
    hasUnderstandingCompletionEvidence ||
    hasAnyArtifactType(artifacts, ["agent_session_report", "agent_session_research_notebook", "eda_review_report", "understanding_report", "eda_profile"]) ||
    Boolean(latestAgentAuthoredDataUnderstandingName(artifacts));
  const hasDataUnderstandingNotebook = artifacts.some(isDataUnderstandingNotebookArtifact);
  const hasPriorResearchPreparation =
    researchBriefs.length > 0 ||
    equippedSkills.length > 0 ||
    hasAnyArtifactType(artifacts, ["research_plan", "research_source_pack", "research_source_report", "notebook_authoring_brief"]);
  const noFindingsResearchArtifact = researchNoFindingsArtifact(artifacts);
  const hasPriorResearchEvidence = hasAnyResolvedResearchArtifact(artifacts);
  const latestCodexMessage = latestCodexTranscriptMessage(agentTranscriptEvents, locale);
  const activeAgentSession = agentSessionShouldRemainVisible(agentSession) ? agentSession : null;
  const activeCodexTurn = agentSessionHasObservedCodexProcess(activeAgentSession);

  const primaryPlanJob = jobs.find((job) => jobActiveForActivity(job)) ?? jobs.find((job) => !isTerminalJob(job)) ?? null;
  const activeInitialBlockId = activeInitialResearchPlanBlockId(primaryPlanJob);
  const objectiveDelegatedToCodex =
    !hasObjectiveEvidence &&
    datasetCount > 0 &&
    project.autonomy_mode === "full_auto" &&
    project.current_phase === "AUTONOMOUS_LOOP";
  const dataUploadStatus = datasetCount > 0 ? "done" : "active";
  const objectiveStatus = hasObjectiveEvidence
    ? "done"
    : objectiveDelegatedToCodex
      ? "skipped"
    : activeInitialBlockId === "objective"
      ? "active"
      : datasetCount > 0
        ? "pending"
        : "waiting";
  const understandingStatus = hasUnderstandingCompletionEvidence
    ? "done"
    : activeInitialBlockId === "understanding"
      ? "active"
      : datasetCount > 0
        ? "pending"
        : "waiting";
  const priorResearchStatus = hasPriorResearchEvidence
    ? "done"
    : activeInitialBlockId === "prior_research"
      ? "active"
      : hasPriorResearchPreparation
        ? "pending"
      : hasUnderstandingCompletionEvidence
        ? "active"
        : "waiting";

  const blocks: ResearchPlanBlock[] = [
    {
      id: "data_upload",
      title: text.planBlockDataUpload,
      subtitle: datasetCount > 0 ? text.planBlockDataUploadDone : text.planBlockDataUploadPending,
      status: dataUploadStatus,
      eyebrow: "01",
      evidence: datasetCount > 0 ? `${datasetCount} DatasetSnapshot${datasetCount === 1 ? "" : "s"}` : null,
      onClick: () => onTabChange("Data")
    },
    {
      id: "objective",
      title: text.planBlockObjective,
      subtitle: hasObjectiveEvidence
        ? text.planBlockObjectiveDone
        : objectiveDelegatedToCodex
          ? text.planBlockObjectiveSkipped
          : text.planBlockObjectivePending,
      status: objectiveStatus,
      eyebrow: "02",
      evidence: project.target_column
        ? `target: ${project.target_column}`
        : objectiveDelegatedToCodex
          ? text.planBlockObjectiveDelegated
          : latestArtifactName(artifacts, "target_definition_proposal"),
      onClick: () => onTabChange("Assumptions")
    },
    {
      id: "understanding",
      title: text.planBlockUnderstanding,
      subtitle: hasUnderstandingCompletionEvidence
        ? text.planBlockUnderstandingDone
        : hasUnderstandingWorkEvidence
          ? text.planBlockUnderstandingNeedsNotebook
          : text.planBlockUnderstandingPending,
      status: understandingStatus,
      eyebrow: "03",
      evidence:
        latestDataUnderstandingNotebookName(artifacts) ??
        latestAgentAuthoredDataUnderstandingName(artifacts) ??
        latestArtifactName(artifacts, "understanding_report") ??
        latestArtifactName(artifacts, "eda_profile") ??
        latestArtifactName(artifacts, "eda_review_report"),
      onClick: () => {
        if (hasDataUnderstandingNotebook) {
          onNavigateToTarget("Notebooks", "notebook-preview-top");
        } else {
          onTabChange("Data");
        }
      }
    },
    {
      id: "prior_research",
      title: text.planBlockPriorResearch,
      subtitle: hasPriorResearchEvidence
        ? noFindingsResearchArtifact
          ? text.planBlockPriorResearchNoFindings
          : text.planBlockPriorResearchDone
        : priorResearchStatus === "active"
          ? text.planBlockPriorResearchActive
        : hasPriorResearchPreparation
          ? text.planBlockPriorResearchPrepared
          : text.planBlockPriorResearchPending,
      status: priorResearchStatus,
      eyebrow: "04",
      evidence:
        latestArtifactName(artifacts, "research_finding_synthesis") ??
        latestArtifactName(artifacts, "research_findings_report") ??
        noFindingsResearchArtifact?.name ??
        latestArtifactName(artifacts, "research_source_pack") ??
        (equippedSkills.length ? `${equippedSkills.length} Skill${equippedSkills.length === 1 ? "" : "s"}` : null) ??
        (researchBriefs.length ? `${researchBriefs.length} brief${researchBriefs.length === 1 ? "" : "s"}` : null),
      onClick: () => onNavigateToTarget("Notebooks", "notebook-preview-top")
    }
  ];
  const mergedBlocks = mergeInitialAnchorsWithCodexPlanBlocks(blocks, codexAuthoredBlocks);

  if (activeAgentSession && !codexAuthoredBlocks.length) {
    const planStatus = activeCodexTurn ? "active" : agentSessionPlanWaitingStatus(activeAgentSession);
    mergedBlocks.push({
      id: "agent_session",
      title: text.planBlockCodexLane,
      subtitle: latestCodexMessage ?? (activeCodexTurn ? text.planBlockCodexRunning : text.planBlockCodexWaiting),
      status: planStatus,
      eyebrow: `${blocks.length + 1}`.padStart(2, "0"),
      evidence: agentSessionPlanEvidence(activeAgentSession, text),
      onClick: () => onTabChange("Jobs")
    });
  }

  return appendObservedAgentPlanBlock(
    attachResearchPlanSubtasks(renumberResearchPlanBlocks(mergedBlocks), jobs, text, locale, onTabChange, { appendUnassigned: false }),
    turnState,
    text,
    locale,
    onTabChange
  );
}

function mergeInitialAnchorsWithCodexPlanBlocks(
  initialAnchors: ResearchPlanBlock[],
  codexBlocks: ResearchPlanBlock[]
): ResearchPlanBlock[] {
  if (!codexBlocks.length) return [...initialAnchors];
  const anchorIds = new Set([
    "data_upload",
    "data-upload",
    "upload_data",
    "objective",
    "objective_setting",
    "task_framing",
    "target_definition",
    "understanding",
    "data_understanding",
    "prior_research",
    "prior_knowledge_research",
    "research",
  ]);
  const codexProjectBlocks = codexBlocks.filter((block) => !anchorIds.has(block.id));
  return [...initialAnchors, ...codexProjectBlocks];
}

function renumberResearchPlanBlocks(blocks: ResearchPlanBlock[]): ResearchPlanBlock[] {
  return blocks.map((block, index) => ({ ...block, eyebrow: `${index + 1}`.padStart(2, "0") }));
}

function selectedResearchPlanBlockKey(blocks: ResearchPlanBlock[]): string {
  return (
    blocks.find((block) => block.status === "active")?.id ??
    blocks.find((block) => block.status === "blocked")?.id ??
    blocks.find((block) => block.status === "pending")?.id ??
    blocks.find((block) => block.status === "waiting")?.id ??
    ""
  );
}

function appendObservedAgentPlanBlock(
  blocks: ResearchPlanBlock[],
  turnState: TurnState,
  text: LocaleMessages,
  locale: string,
  onTabChange: (tab: Tab) => void
): ResearchPlanBlock[] {
  const agentOwnsTurn = turnState.owner === "agent" && ["agent_running", "agent_scheduled"].includes(turnState.state);
  if (!agentOwnsTurn) return blocks;
  const hasLiveBlock = blocks.some((block) => block.status === "active");
  if (hasLiveBlock) return blocks;
  const detail = localeSafeDisplayText(turnState.detail || turnState.label, locale, text.planBlockCodexRunning);
  return [
    ...blocks,
    {
      id: "observed_main_agent_session",
      title: turnStateLabel(turnState, text, locale),
      subtitle: detail,
      status: turnState.state === "agent_running" ? "active" : "pending",
      eyebrow: `${blocks.length + 1}`.padStart(2, "0"),
      evidence:
        typeof turnState.last_output_seconds_ago === "number"
          ? `${text.turnStateObserved} · ${formatElapsedSeconds(turnState.last_output_seconds_ago)}`
          : text.turnStateObserved,
      onClick: () => onTabChange("Home")
    }
  ];
}

function researchPlanBlocksFromTimeline(
  timeline: ResearchPlanTimelineResponse | null,
  text: LocaleMessages,
  locale: string,
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void
): ResearchPlanBlock[] {
  if (!timeline?.blocks.length) return [];
  const blocks = timeline.blocks.map((block, index) => {
    const targetTab = block.target_tab ? tabFromString(block.target_tab, "Home") : null;
    const subtasks: ResearchPlanSubtask[] = block.subtasks.map((subtask) => {
      const subtaskTab = subtask.target_tab ? tabFromString(subtask.target_tab, targetTab ?? "Home") : targetTab;
      return {
        id: subtask.id,
        title: localeSafeDisplayText(subtask.title, locale, text.researchPlanDetailLocaleRefresh),
        detail: localeSafeDisplayText(subtask.detail, locale, text.researchPlanLocaleRefreshDetail),
        status: subtask.status,
        evidence: subtask.evidence,
        targetTab: subtaskTab,
        targetAnchor: subtask.target_anchor,
        onClick: subtaskTab ? () => onNavigateToTarget(subtaskTab, subtask.target_anchor) : undefined
      };
    });
    subtasks.push(...derivedResearchPlanSubtasks(block, text, locale));
    return {
      id: block.id,
      title: localeSafeDisplayText(block.title, locale, text.researchPlanBlockLocaleRefreshTitle),
      subtitle: localeSafeDisplayText(block.subtitle, locale, block.localization_status === "needs_locale_refresh" ? text.researchPlanLocaleRefreshDetail : ""),
      status: block.status,
      eyebrow: `${index + 1}`.padStart(2, "0"),
      evidence: displayTextMatchesLocale(block.evidence, locale) ? block.evidence : null,
      subtasks,
      onClick: targetTab ? () => onNavigateToTarget(targetTab, block.target_anchor) : undefined
    };
  });
  return collapseUnlocalizedResearchPlanBlocks(blocks, text);
}

function derivedResearchPlanSubtasks(
  block: ResearchPlanTimelineBlock,
  text: LocaleMessages,
  locale: string
): ResearchPlanSubtask[] {
  const derived: ResearchPlanSubtask[] = [];
  if (block.localization_status === "needs_locale_refresh") {
    derived.push({
      id: `${block.id}:locale_refresh`,
      title: text.researchPlanDetailLocaleRefresh,
      detail: text.researchPlanLocaleRefreshDetail,
      status: block.status === "done" ? "pending" : block.status,
      evidence: block.missing_localization_fields?.length ? `${block.missing_localization_fields.length}` : null
    });
  }
  if (block.next_action) {
    derived.push({
      id: `${block.id}:next_action`,
      title: text.researchPlanDetailNextAction,
      detail: localeSafeDisplayText(block.next_action, locale, text.researchPlanLocaleRefreshDetail),
      status: block.status,
      evidence: displayTextMatchesLocale(block.phase, locale) ? block.phase ?? null : null
    });
  }
  if (block.done_criteria) {
    derived.push({
      id: `${block.id}:done_criteria`,
      title: text.researchPlanDetailDoneCriteria,
      detail: localeSafeDisplayText(block.done_criteria, locale, text.researchPlanLocaleRefreshDetail),
      status: block.status,
      evidence: null
    });
  }
  if (block.blockers?.length) {
    const blockerDetail = localeSafeDisplayText(block.blockers.join(" / "), locale, text.researchPlanLocaleRefreshDetail);
    derived.push({
      id: `${block.id}:blockers`,
      title: text.researchPlanDetailBlockers,
      detail: blockerDetail,
      status: "blocked",
      evidence: `${block.blockers.length}`
    });
  }
  const missingArtifacts = block.supporting_artifacts?.filter((artifact) => artifact.exists === false) ?? [];
  if (missingArtifacts.length) {
    derived.push({
      id: `${block.id}:missing_supporting_artifacts`,
      title: text.researchPlanDetailEvidence,
      detail: missingArtifacts
        .slice(0, 4)
        .map((artifact) => artifact.path)
        .join(" / "),
      status: "pending",
      evidence: `${missingArtifacts.length}`
    });
  }
  const existingArtifacts = block.supporting_artifacts?.filter((artifact) => artifact.exists !== false) ?? [];
  if (existingArtifacts.length) {
    derived.push({
      id: `${block.id}:supporting_artifacts`,
      title: text.researchPlanDetailEvidence,
      detail: existingArtifacts
        .slice(0, 4)
        .map((artifact) => artifact.path)
        .join(" / "),
      status: block.status === "blocked" ? "pending" : block.status,
      evidence: `${existingArtifacts.length}`
    });
  }
  return derived;
}

function collapseUnlocalizedResearchPlanBlocks(blocks: ResearchPlanBlock[], text: LocaleMessages): ResearchPlanBlock[] {
  const refreshTitle = text.researchPlanBlockLocaleRefreshTitle;
  const stableBlocks: ResearchPlanBlock[] = [];
  const refreshBlocks: ResearchPlanBlock[] = [];
  for (const block of blocks) {
    if (block.title === refreshTitle) {
      refreshBlocks.push(block);
    } else {
      stableBlocks.push(block);
    }
  }
  if (refreshBlocks.length <= 1) return blocks;
  const status: ResearchPlanBlockStatus = refreshBlocks.some((block) => block.status === "active") ? "active" : "pending";
  const refreshSummary: ResearchPlanBlock = {
    id: "research_plan_locale_refresh_group",
    title: refreshTitle,
    subtitle: text.researchPlanLocaleRefreshDetail,
    status,
    eyebrow: "",
    evidence: `${refreshBlocks.length} ${text.researchPlanSummaryBlocks}`
  };
  return [...stableBlocks, refreshSummary];
}

function researchPlanCompactSummary(blocks: ResearchPlanBlock[], text: LocaleMessages): string {
  if (!blocks.length) return "";
  const counts = blocks.reduce<Record<ResearchPlanBlockStatus, number>>(
    (acc, block) => {
      acc[block.status] += 1;
      return acc;
    },
    { done: 0, active: 0, pending: 0, blocked: 0, waiting: 0, skipped: 0 }
  );
  const parts = (Object.keys(counts) as ResearchPlanBlockStatus[])
    .filter((status) => counts[status] > 0)
    .map((status) => `${researchPlanStatusLabel(status, text)} ${counts[status]}`);
  const blockLabel = blocks.length === 1 ? text.researchPlanSummaryBlock : text.researchPlanSummaryBlocks;
  return `${blocks.length} ${blockLabel}: ${parts.join(" / ")}`;
}

function attachResearchPlanSubtasks(
  blocks: ResearchPlanBlock[],
  jobs: Job[],
  text: LocaleMessages,
  locale: string,
  onTabChange: (tab: Tab) => void,
  options: { appendUnassigned: boolean } = { appendUnassigned: true }
): ResearchPlanBlock[] {
  if (!jobs.length) return blocks;
  const blockIds = new Set(blocks.map((block) => block.id));
  const byBlock = new Map<string, ResearchPlanSubtask[]>();
  const unassigned: ResearchPlanSubtask[] = [];
  for (const job of jobs) {
    if (isMainAgentReplyWaitJob(job)) continue;
    const subtask = researchPlanSubtaskFromJob(job, text, locale, onTabChange);
    const blockId = researchPlanBlockIdForJob(job);
    if (blockId && blockIds.has(blockId)) {
      const existing = byBlock.get(blockId) ?? [];
      existing.push(subtask);
      byBlock.set(blockId, existing);
    } else if (!isTerminalJob(job)) {
      unassigned.push(subtask);
    }
  }
  const nextBlocks = blocks.map((block) => {
    const subtasks = byBlock.get(block.id) ?? [];
    if (!subtasks.length) return block;
    return {
      ...block,
      subtasks,
      status: researchPlanStatusWithSubtasks(block.status, subtasks),
      evidence: block.evidence ?? subtaskEvidenceSummary(subtasks, text)
    };
  });
  if (unassigned.length && options.appendUnassigned) {
    nextBlocks.push({
      id: "agent_work",
      title: text.planBlockCodexLane,
      subtitle: unassigned[0]?.detail ?? text.researchPlanTimelineHint,
      status: researchPlanStatusWithSubtasks("pending", unassigned),
      eyebrow: `${nextBlocks.length + 1}`.padStart(2, "0"),
      evidence: subtaskEvidenceSummary(unassigned, text),
      subtasks: unassigned,
      onClick: () => onTabChange("Jobs")
    });
  }
  return nextBlocks;
}

function latestCodexTranscriptMessage(events: AgentTranscriptEvent[], locale: string): string | null {
  for (const event of [...events].reverse()) {
    if (event.source !== "codex_cli") continue;
    if (event.title !== "Codex message" && event.event_type !== "item.completed") continue;
    const content = event.content?.trim();
    if (content && displayTextMatchesLocale(content, locale)) return content;
  }
  return null;
}

function agentSessionHasObservedCodexProcess(session: AgentSession | null): boolean {
  if (!session) return false;
  if (session.observed_runner_state === "running") return true;
  if (session.pid_is_observed_codex_process === true) return true;
  return (session.observed_codex_process_count ?? 0) > 0;
}

function agentSessionShouldRemainVisible(session: AgentSession | null): session is AgentSession {
  if (!session) return false;
  if (agentSessionHasObservedCodexProcess(session)) return true;
  if (session.observed_runner_state === "supervisor_should_continue") return true;
  return ["starting", "running", "between_turns", "waiting_for_runner"].includes(session.status);
}

function agentSessionPlanWaitingStatus(session: AgentSession): ResearchPlanBlockStatus {
  if (session.observed_runner_state === "supervisor_should_continue") return "pending";
  if (session.status === "waiting_for_runner") return "waiting";
  if (session.status === "starting" || session.status === "between_turns") return "pending";
  return "waiting";
}

function agentSessionPlanEvidence(session: AgentSession, text: LocaleMessages): string {
  if (agentSessionHasObservedCodexProcess(session)) return text.turnStateAgentRunning;
  if (session.observed_runner_state === "supervisor_should_continue") return text.turnStateAgentScheduled;
  if (session.status === "waiting_for_runner") return text.turnStateWorkerPending;
  return text.turnStateObserved;
}

function researchPlanSubtaskFromJob(
  job: Job,
  text: LocaleMessages,
  locale: string,
  onTabChange: (tab: Tab) => void
): ResearchPlanSubtask {
  const humanDescription = jobHumanDescription(job, text);
  return {
    id: job.id,
    title: localeSafeDisplayText(humanDescription.title, locale, workerDisplayName(job.job_type, text)),
    detail: localeSafeDisplayText(job.error_message ?? humanDescription.summary ?? latestJobHeadline(job), locale, text.researchPlanTimelineHint),
    status: researchPlanStatusFromJob(job),
    evidence: `${job.status} · ${formatDate(job.updated_at ?? job.created_at)}`,
    onClick: () => onTabChange(tabForResearchPlanJob(job))
  };
}

function researchPlanStatusFromJob(job: Job): ResearchPlanBlockStatus {
  if (job.status === "running") return "active";
  if (job.status === "approval_required") return "blocked";
  if (job.status === "queued" || job.status === "waiting_for_agent") return "waiting";
  if (job.status === "succeeded") return "done";
  if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") return "blocked";
  return "pending";
}

function researchPlanStatusWithSubtasks(
  currentStatus: ResearchPlanBlockStatus,
  subtasks: ResearchPlanSubtask[]
): ResearchPlanBlockStatus {
  if (subtasks.some((subtask) => subtask.status === "active")) return "active";
  if (subtasks.some((subtask) => subtask.status === "blocked")) return "blocked";
  if (currentStatus === "skipped") return "skipped";
  if (subtasks.some((subtask) => subtask.status === "waiting")) return "waiting";
  return currentStatus;
}

function subtaskEvidenceSummary(subtasks: ResearchPlanSubtask[], text: LocaleMessages) {
  return `${subtasks.length} ${subtasks.length === 1 ? text.planSubtaskSingular : text.planSubtaskPlural}`;
}

function researchPlanBlockIdForJob(job: Job): string | null {
  const initialBlockId = activeInitialResearchPlanBlockId(job);
  if (initialBlockId) return initialBlockId;
  const jobType = job.job_type.toLowerCase();
  if (jobType.includes("profile") || jobType.includes("quality") || jobType.includes("eda") || jobType.includes("understanding")) {
    return "understanding";
  }
  if (jobType.includes("target") || jobType.includes("objective") || jobType.includes("assumption")) {
    return "objective";
  }
  if (jobType.includes("research") || jobType.includes("source_pack") || jobType.includes("skill")) {
    return "prior_research";
  }
  if (jobType.includes("evaluation") || jobType.includes("split")) {
    return "evaluation";
  }
  if (jobType.includes("baseline") || jobType.includes("model") || jobType.includes("experiment") || jobType.includes("leaderboard")) {
    return "modeling";
  }
  if (jobType.includes("notebook") || jobType.includes("report") || jobType.includes("insight")) {
    return "reporting";
  }
  return null;
}

function tabForResearchPlanJob(job: Job): Tab {
  const jobType = job.job_type.toLowerCase();
  if (jobType.includes("profile") || jobType.includes("quality") || jobType.includes("eda") || jobType.includes("relational")) return "Data";
  if (jobType.includes("target") || jobType.includes("objective") || jobType.includes("assumption")) return "Assumptions";
  if (jobType.includes("evaluation") || jobType.includes("split")) return "Evaluation";
  if (jobType.includes("baseline") || jobType.includes("model") || jobType.includes("leaderboard")) return "Leaderboard";
  if (jobType.includes("experiment") || jobType.includes("agent_task")) return "Experiments";
  if (jobType.includes("notebook")) return "Notebooks";
  if (jobType.includes("research") || jobType.includes("report") || jobType.includes("insight") || jobType.includes("skill")) return "Insight";
  return "Jobs";
}

function activeInitialResearchPlanBlockId(job: Job | null): "data_upload" | "objective" | "understanding" | "prior_research" | null {
  if (!job || !jobActiveForActivity(job, Date.now())) return null;
  if (
    ["profile_dataset", "infer_assumptions", "create_data_understanding_notebook", "prepare_data_understanding_notebook_authoring"].includes(
      job.job_type
    )
  ) {
    return "understanding";
  }
  if (["create_research_source_pack", "run_research_source_pack_stub"].includes(job.job_type)) return "prior_research";
  if (job.job_type.includes("target_definition")) return "objective";
  return null;
}

function researchPlanStatusLabel(status: ResearchPlanBlockStatus, text: LocaleMessages) {
  if (status === "done") return text.planStatusDone;
  if (status === "active") return text.planStatusActive;
  if (status === "blocked") return text.planStatusBlocked;
  if (status === "waiting") return text.planStatusWaiting;
  if (status === "skipped") return text.planStatusSkipped;
  return text.planStatusPending;
}

function hasAnyArtifactType(artifacts: Artifact[], assetTypes: string[]) {
  const wanted = new Set(assetTypes);
  return artifacts.some((artifact) => wanted.has(artifact.asset_type));
}

function isDataUnderstandingNotebookArtifact(artifact: Artifact) {
  if (!["analysis_notebook", "marimo_notebook"].includes(artifact.asset_type)) return false;
  const notebookKind = String(artifact.metadata.notebook_kind ?? artifact.metadata.kind ?? "");
  if (notebookKind === "data_understanding") return true;
  const workspacePath = String(artifact.metadata.workspace_relative_path ?? "");
  return isDataUnderstandingArtifactName(`${artifact.name} ${workspacePath}`);
}

function latestDataUnderstandingNotebookName(artifacts: Artifact[]) {
  return artifacts
    .filter(isDataUnderstandingNotebookArtifact)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())[0]?.name ?? null;
}

function hasReviewableDataUnderstandingNotebook(notebookIndex: NotebookIndex | null) {
  return Boolean(
    notebookIndex?.items.some((item) => {
      if (item.notebook_kind !== "data_understanding") return false;
      const readiness = String(item.content?.readiness ?? item.coverage?.content_readiness ?? "");
      if (["not_ready", "source_only", "unknown", ""].includes(readiness)) return false;
      return true;
    })
  );
}

function latestAgentAuthoredDataUnderstandingName(artifacts: Artifact[]) {
  return artifacts
    .filter((artifact) => {
      if (!["agent_session_artifact", "agent_session_report"].includes(artifact.asset_type)) return false;
      return isDataUnderstandingArtifactName(artifact.name);
    })
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())[0]?.name ?? null;
}

function isDataUnderstandingArtifactName(value: string) {
  return /(^|[_\-\s])(data[_\-\s]?understanding|eda|exploration|visual[_\-\s]?story|notebook[_\-\s]?evidence|grandmaster[_\-\s]?eda)([_\-\s]|$)/.test(
    value.toLowerCase()
  );
}

function hasAnyResolvedResearchArtifact(artifacts: Artifact[]) {
  return artifacts.some((artifact) => {
    if (artifact.metadata.no_relevant_findings === true || artifact.metadata.codex_decision === "no_research_needed") {
      return true;
    }
    if (artifact.asset_type === "research_findings_report") {
      return artifact.metadata.external_network_accessed === true || artifact.metadata.has_only_stub_findings === false;
    }
    if (artifact.asset_type === "source_citation_manifest") {
      return artifact.metadata.external_network_accessed === true;
    }
    return ["research_finding_synthesis", "research_finding_synthesis_report", "agent_session_research_notebook"].includes(
      artifact.asset_type
    );
  });
}

function researchNoFindingsArtifact(artifacts: Artifact[]) {
  return artifacts.find(
    (artifact) => artifact.metadata.no_relevant_findings === true || artifact.metadata.codex_decision === "no_research_needed"
  ) ?? null;
}

function fallbackNavigationAnchor(anchor: string) {
  if (anchor === "notebook-preview-top") return document.getElementById("notebook-focus");
  return null;
}

function focusNavigationAnchor(anchor: string, delayMs = 90) {
  window.setTimeout(() => {
    const element = document.getElementById(anchor) ?? fallbackNavigationAnchor(anchor);
    if (!element) return;
    const top = Math.max(0, element.getBoundingClientRect().top + window.scrollY - 8);
    window.scrollTo({ top, behavior: "smooth" });
    element.classList.add("navigation-highlight");
    window.setTimeout(() => element.classList.remove("navigation-highlight"), 1400);
  }, delayMs);
}

function latestArtifactName(artifacts: Artifact[], assetType: string) {
  return latestArtifactByType(artifacts, assetType)?.name ?? null;
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

function memoryAnchor(prefix: "idea" | "finding", id: string) {
  return `${prefix}-${id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function confidenceLabel(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "confidence n/a";
  return `${Math.round(value * 100)}% confidence`;
}

function insightDeepDiveAnchor(insight: Insight) {
  const assetTypes = insight.source_asset_ids.map((source) => source.asset_type.toLowerCase());
  if (assetTypes.some((assetType) => assetType.includes("notebook"))) return "notebook-focus";
  if (assetTypes.some((assetType) => assetType.includes("report"))) return "reports";
  return memoryAnchor("finding", insight.id);
}

function buildIdeaFindingItems(ideas: Idea[], insights: Insight[]): HomeMemoryItem[] {
  return [
    ...ideas.map((idea) => ({
      id: idea.id,
      kind: "idea" as const,
      title: conciseMemoryText(idea.title, "Candidate idea", 90),
      summary: conciseMemoryText(
        idea.hypothesis || idea.rationale_md,
        "Review the saved rationale, expected artifacts, and proposed next experiment."
      ),
      meta: `Idea · ${idea.approach_type.replace(/_/g, " ")} · ${idea.risk_level.replace(/_/g, " ")}`,
      cta: "Open this exact idea",
      target_tab: "Insight",
      target_anchor: memoryAnchor("idea", idea.id),
      created_at: idea.created_at,
      signal_priority: 82
    })),
    ...insights.map((insight) => ({
      id: insight.id,
      kind: "finding" as const,
      title: conciseMemoryText(insight.title, "Finding", 90),
      summary: conciseMemoryText(insight.summary, "Review the saved evidence behind this finding."),
      meta: `Finding · ${insight.insight_type.replace(/_/g, " ")} · ${confidenceLabel(insight.confidence)}`,
      cta: insightDeepDiveAnchor(insight) === "notebook-focus" ? "Open notebook evidence" : "Open this exact finding",
      target_tab: "Insight",
      target_anchor: insightDeepDiveAnchor(insight),
      created_at: insight.created_at,
      signal_priority: homeInsightSignalPriority(insight)
    }))
  ].sort((left, right) => {
    const priorityDelta = right.signal_priority - left.signal_priority;
    if (priorityDelta !== 0) return priorityDelta;
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
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

function buildRawAgentEvents(
  messages: AgentChatMessage[],
  jobs: Job[],
  transcriptEvents: AgentTranscriptEvent[] = [],
  agentSession: AgentSession | null = null
): RawAgentEvent[] {
  const sessionEvents = buildRawSessionEvents(transcriptEvents, agentSession);
  if (sessionEvents.length) {
    return dedupeRawAgentEvents([...sessionEvents, ...buildRawJobSidecarEvents(jobs)])
      .sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
      .slice(-500);
  }
  const now = new Date().toISOString();
  const turns = buildAgentConversationTurns(messages);
  const chatEvents = turns.flatMap((turn, index) => {
    const events: RawAgentEvent[] = [];
    if (!turn.assistant) return events;
    const composerMode = textField(turn.assistant.responseComposer?.mode);
    const composerStatus = textField(turn.assistant.responseComposer?.status) ?? "pending";
    const active = isActiveAgentTurn(turn);
    const isCodexCli = composerMode === "codex_cli";
    const isHarnessSidecar = composerMode === "autonomy_control_event" || composerMode === "autonomy_control_backfill";
    if (!isCodexCli && !active && !isHarnessSidecar) return events;
    if (turn.user) {
      events.push({
        id: `raw-user-${index}-${turn.user.id ?? turn.user.text.slice(0, 18)}`,
        timestamp: turn.user.createdAt ?? turn.createdAt ?? now,
        source: "User",
        level: "prompt",
        title: isHarnessSidecar ? "User control request" : "Prompt sent to Codex",
        body: turn.user.text,
        payload: { text: turn.user.text }
      });
    }
    const promptPreamble = Array.isArray(turn.assistant.responseComposer?.prompt_preamble)
      ? turn.assistant.responseComposer.prompt_preamble.join("\n")
      : null;
    const command = textField(turn.assistant.responseComposer?.command);
    const stdoutTail = textField(turn.assistant.responseComposer?.stdout_tail);
    const stderrTail = textField(turn.assistant.responseComposer?.stderr_tail);
    const codexEvents = arrayRecords(turn.assistant.responseComposer?.events);
    if (codexEvents.length) {
      events.push(
        ...codexTranscriptEvents(codexEvents, {
          idPrefix: `raw-assistant-event-${index}-${turn.assistant.id ?? "turn"}`,
          timestamp: turn.assistant.createdAt ?? turn.createdAt ?? now,
          active,
          command,
          metadata: turn.assistant.responseComposer ?? null
        })
      );
      return events;
    }
    events.push({
      id: `raw-assistant-${index}-${turn.assistant.id ?? turn.assistant.text.slice(0, 18)}`,
      timestamp: turn.assistant.createdAt ?? turn.createdAt ?? now,
      source: isHarnessSidecar ? "Tablex" : "Codex",
      level: composerStatus,
      title: isHarnessSidecar
        ? "Tablex event"
        : active
          ? "Codex composer request is in flight"
          : "Codex exec transcript",
      active,
      body: active ? null : turn.assistant.text,
      details: [
        ...(command ? [{ label: "Codex command", value: command }] : []),
        ...(promptPreamble ? [{ label: "Codex prompt preamble", value: promptPreamble }] : []),
        ...(turn.assistant.responseBrief
          ? [{ label: "Exact prompt brief passed to Codex", value: turn.assistant.responseBrief }]
          : []),
        ...(stdoutTail ? [{ label: "Codex stdout", value: stdoutTail }] : []),
        ...(stderrTail ? [{ label: "Codex stderr", value: stderrTail }] : []),
        ...(turn.assistant.responseComposer
          ? [{ label: isHarnessSidecar ? "Tablex event detail" : "Codex run metadata", value: turn.assistant.responseComposer }]
          : [])
      ],
      payload: {
        text: turn.assistant.text,
        response_brief: turn.assistant.responseBrief ?? null,
        response_composer: turn.assistant.responseComposer ?? null
      }
    });
    return events;
  });
  return dedupeRawAgentEvents([...chatEvents, ...buildRawJobEvents(jobs)])
    .sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
    .slice(-200);
}

function buildRawSessionEvents(events: AgentTranscriptEvent[], agentSession: AgentSession | null): RawAgentEvent[] {
  return events.map((event) => {
    const payload = event.payload ?? {};
    const active = agentSessionHasObservedCodexProcess(agentSession);
    const isCodex = event.source === "codex_cli" || event.source === "codex_cli_stderr";
    return {
      id: `agent-session-${event.id}`,
      timestamp: event.created_at,
      source: isCodex ? "Codex" : event.source === "user" ? "User" : "Tablex",
      level: event.event_type,
      title: event.title ?? humanizeLabel(event.event_type),
      active: active && isCodex && event.event_index === events[events.length - 1]?.event_index,
      body: event.content,
      details: [
        ...(event.source === "codex_cli" ? [{ label: "Raw Codex JSONL event", value: payload }] : []),
        ...(event.source === "codex_cli_stderr" ? [{ label: "Codex stderr line", value: payload }] : []),
        ...(!isCodex ? [{ label: "Tablex event detail", value: payload }] : []),
        ...(agentSession && event.event_index === 0 ? [{ label: "Session detail", value: agentSession }] : [])
      ],
      payload: {
        agent_session_id: event.session_id,
        event_index: event.event_index,
        source: event.source,
        payload
      }
    };
  });
}

function buildRawJobSidecarEvents(jobs: Job[]): RawAgentEvent[] {
  return buildRawJobEvents(jobs).filter((event) => event.source !== "Codex" && event.source !== "Codex runner");
}

function buildRawJobEvents(jobs: Job[]): RawAgentEvent[] {
  return jobs.flatMap((job) => {
    if (!isRawRelevantJob(job)) return [];
    const events: RawAgentEvent[] = [];
    const output = job.output ?? {};
    const codexCli = output.codex_cli;
    if (codexCli && typeof codexCli === "object") {
      const codexRecord = codexCli as Record<string, unknown>;
      const codexEvents = arrayRecords(codexRecord.events);
      if (codexEvents.length) {
        events.push(
          ...codexTranscriptEvents(codexEvents, {
            idPrefix: `raw-job-codex-${job.id}`,
            timestamp: job.updated_at,
            active: jobActiveForActivity(job),
            command: textField(codexRecord.command),
            metadata: codexRecord
          })
        );
      } else {
        events.push({
          id: `raw-job-codex-${job.id}`,
          timestamp: job.updated_at,
          source: "Codex",
          level: textField(codexRecord.status) ?? job.status,
          title: "Codex CLI runner transcript",
          active: jobActiveForActivity(job),
          body: textField(output.agent_final_message),
          details: [
            { label: "Codex command", value: codexRecord.command ?? null },
            { label: "Codex stdout", value: codexRecord.stdout_tail ?? "" },
            { label: "Codex stderr", value: codexRecord.stderr_tail ?? "" },
            { label: "Codex run metadata", value: codexRecord }
          ],
          payload: { job_id: job.id, job_type: job.job_type, codex_cli: codexRecord }
        });
      }
    } else if (job.job_type === "run_planned_agent_task_codex" && jobActiveForActivity(job)) {
      events.push({
        id: `raw-job-state-${job.id}`,
        timestamp: job.updated_at,
        source: "Codex runner",
        level: job.status,
        title: "Codex runner has not emitted a transcript yet",
        active: jobActiveForActivity(job),
        body: latestJobHeadline(job),
        details: [{ label: "Job record", value: job }],
        payload: { job_id: job.id, job_type: job.job_type, status: job.status }
      });
    } else if (
      job.job_type === "start_autonomous_loop" ||
      job.job_type === "stop_autonomous_loop" ||
      job.job_type === "continue_autonomous_session"
    ) {
      events.push({
        id: `raw-job-sidecar-${job.id}`,
        timestamp: job.updated_at,
        source: "Tablex",
        level: job.status,
        title:
          job.job_type === "start_autonomous_loop"
            ? "Full Auto control job"
            : job.job_type === "continue_autonomous_session"
              ? "Autonomous session heartbeat"
              : "Autonomy stop control job",
        active: jobActiveForActivity(job),
        body: latestJobHeadline(job),
        details: [
          { label: "Tablex job output", value: output },
          { label: "Job record", value: job }
        ],
        payload: { job_id: job.id, job_type: job.job_type, status: job.status, output }
      });
    }
    return events;
  });
}

function codexTranscriptEvents(
  rawEvents: Record<string, unknown>[],
  options: {
    idPrefix: string;
    timestamp: string;
    active?: boolean;
    command?: string | null;
    metadata?: unknown;
  }
): RawAgentEvent[] {
  return rawEvents.map((event, index) => ({
    id: `${options.idPrefix}-${index}`,
    timestamp: textField(event.timestamp) ?? options.timestamp,
    source: "Codex",
    level: textField(event.type) ?? "event",
    title: codexEventTitle(event),
    active: options.active,
    body: codexEventBody(event),
    details: [
      ...(index === 0 && options.command ? [{ label: "Codex command", value: options.command }] : []),
      { label: "Raw Codex event", value: event },
      ...(index === rawEvents.length - 1 && options.metadata ? [{ label: "Codex run metadata", value: options.metadata }] : [])
    ],
    payload: event
  }));
}

function codexEventTitle(event: Record<string, unknown>) {
  const type = textField(event.type) ?? "Codex event";
  const item = objectRecord(event.item);
  const itemType = textField(item?.type);
  const toolName = textField(item?.name) ?? textField(item?.tool_name) ?? textField(item?.command);
  if (type === "thread.started") return "Thread started";
  if (type === "turn.started") return "Turn started";
  if (type === "turn.completed") return "Turn completed";
  if (type === "item.completed" && itemType === "agent_message") return "Codex message";
  if (type === "item.completed" && itemType && itemType.includes("tool")) {
    return toolName ? `Tool use: ${toolName}` : "Tool use";
  }
  if (type === "item.completed" && itemType && (itemType.includes("command") || itemType.includes("exec"))) {
    return toolName ? `Command: ${toolName}` : "Command execution";
  }
  if (type === "item.completed" && itemType && (itemType.includes("patch") || itemType.includes("edit"))) {
    return "Code edit";
  }
  if (type === "item.completed" && itemType) return humanizeLabel(itemType);
  return humanizeLabel(type);
}

function codexEventBody(event: Record<string, unknown>) {
  const item = objectRecord(event.item);
  const itemType = textField(item?.type);
  if (itemType === "agent_message") return textField(item?.text);
  const usage = objectRecord(event.usage);
  if (usage) {
    const input = usage.input_tokens;
    const output = usage.output_tokens;
    const reasoning = usage.reasoning_output_tokens;
    return `usage: input=${String(input ?? "-")}, output=${String(output ?? "-")}, reasoning=${String(reasoning ?? "-")}`;
  }
  return (
    textField(item?.text) ??
    textField(item?.aggregated_output) ??
    textField(item?.output) ??
    textField(item?.summary) ??
    textField(item?.command) ??
    textField(event.message) ??
    null
  );
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function isRawRelevantJob(job: Job) {
  return (
    Boolean(job.output?.codex_cli) ||
    job.job_type === "start_autonomous_loop" ||
    job.job_type === "continue_autonomous_session" ||
    job.job_type === "stop_autonomous_loop" ||
    (job.job_type === "run_planned_agent_task_codex" && jobActiveForActivity(job))
  );
}

function dedupeRawAgentEvents(events: RawAgentEvent[]) {
  const byId = new Map<string, RawAgentEvent>();
  events.forEach((event) => byId.set(event.id, event));
  return [...byId.values()];
}

function maxTranscriptEventIndex(events: AgentTranscriptEvent[]): number | null {
  let maxIndex: number | null = null;
  for (const event of events) {
    if (maxIndex === null || event.event_index > maxIndex) maxIndex = event.event_index;
  }
  return maxIndex;
}

function mergeTranscriptEvents(current: AgentTranscriptEvent[], incoming: AgentTranscriptEvent[]) {
  if (!incoming.length) return current;
  const byKey = new Map<string, AgentTranscriptEvent>();
  for (const event of current) {
    byKey.set(`${event.session_id}:${event.event_index}`, event);
  }
  for (const event of incoming) {
    byKey.set(`${event.session_id}:${event.event_index}`, event);
  }
  return [...byKey.values()]
    .sort((left, right) => left.event_index - right.event_index)
    .slice(-500);
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

function useStickyBottomScroll<T extends HTMLElement>(dependencyKey: string, resetKey?: string) {
  const ref = React.useRef<T | null>(null);
  const shouldStickRef = React.useRef(true);
  const mountedRef = React.useRef(false);
  const resetKeyRef = React.useRef(resetKey);

  const onScroll = React.useCallback(() => {
    const element = ref.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    shouldStickRef.current = distanceFromBottom <= 48;
  }, []);

  React.useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (resetKeyRef.current !== resetKey) {
      resetKeyRef.current = resetKey;
      mountedRef.current = false;
      shouldStickRef.current = true;
    }
    if (!mountedRef.current || shouldStickRef.current) {
      element.scrollTop = element.scrollHeight;
      shouldStickRef.current = true;
    }
    mountedRef.current = true;
  }, [dependencyKey, resetKey]);

  return { ref, onScroll };
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

function agentChatActionLabel(action: AgentChatAction, text: LocaleMessages) {
  const targetTab = action.artifact_id && action.target_tab === "Notebooks" ? "Notebooks" : tabFromString(action.target_tab, "Home");
  const verb = ["needs_review", "created", "recorded", "explained"].includes(action.status)
    ? text.chatActionReview
    : text.chatActionOpen;
  const anchorLabel = action.target_anchor ? ` · ${surfaceLabel(action.target_anchor)}` : "";
  return `${verb} ${tabLabel(targetTab, text)}${anchorLabel}`;
}

function surfaceLabel(anchor: string) {
  const labels: Record<string, string> = {
    "dataset-upload": "Dataset Upload",
    "data-focus": "Data Evidence",
    "relational-map": "Relational Map",
    "notebook-focus": "Notebook Focus",
    "notebook-center": "Notebook Center",
    "analysis-story": "Analysis Story",
    ideas: "Ideas",
    insights: "Insights",
    reports: "Reports",
    "evaluation-design": "Evaluation Design",
    "approach-handoff": "Runner Handoff"
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

function isActiveRawEvent(event: RawAgentEvent): boolean {
  return event.active === true;
}

function AgentChatSummaryCard({
  summary,
  text,
  onActionOpen
}: {
  summary: AgentActionSummary;
  text: LocaleMessages;
  onActionOpen: (action: AgentChatAction) => void;
}) {
  const targetTab = summary.next_step?.target_tab ? tabFromString(summary.next_step.target_tab, "Home") : null;
  const nextAnchor = summary.next_step?.target_anchor ?? null;
  const nextLabel = summary.next_step?.label ?? "Review the focused surface";
  const targetLabel = targetTab ? tabLabel(targetTab, text) : "";
  const summaryAction: AgentChatAction | null = targetTab
    ? {
        type: "summary_next_step",
        status: summary.next_step.status ?? summary.outcome,
        label: nextLabel,
        target_tab: targetTab,
        target_anchor: nextAnchor,
        detail: "Open the surface Tablex selected for this response."
      }
    : null;
  const needsReview = Array.isArray(summary.what_needs_review) ? summary.what_needs_review.slice(0, 3) : [];
  return (
    <div className="agent-chat-summary">
      {summaryAction ? (
        <button className="agent-chat-next-button" type="button" onClick={() => onActionOpen(summaryAction)}>
          <span>{text.nextActionLabel}</span>
          <strong>{nextLabel}</strong>
          <small>
            {targetLabel}
            {nextAnchor ? ` · ${surfaceLabel(nextAnchor)}` : ""}
          </small>
        </button>
      ) : null}
      {needsReview.length ? (
        <div className="agent-chat-summary-lists">
          <div>
            <span>{text.chatReviewLabel}</span>
            {needsReview.map((item) => (
              <small key={item}>{item}</small>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TurnStateBar({ text, locale, turnState }: { text: LocaleMessages; locale: string; turnState: TurnState }) {
  const observedAt = turnState.observed_at ? formatDate(turnState.observed_at) : null;
  const detail = turnStateDisplayDetail(turnState, text, locale);
  const rawObservation = turnStateRawObservationText(turnState, text);
  return (
    <div className={turnStateClassName(turnState)} title={text.turnStateSource}>
      <div className="turn-state-main">
        <span className="turn-state-dot" />
        <div>
          <span>{text.turnStateObserved}</span>
          <strong>{turnStateLabel(turnState, text, locale)}</strong>
        </div>
      </div>
      <p>{detail}</p>
      <div className="turn-state-meta">
        <span>{turnState.input_attention ? text.turnStateUserTurnHint : text.turnStateSource}</span>
        {rawObservation ? <span>{rawObservation}</span> : null}
        {observedAt ? <time>{observedAt}</time> : null}
      </div>
    </div>
  );
}

function turnStateRawObservationText(turnState: TurnState, text: LocaleMessages): string | null {
  const raw = turnState.raw_transcript;
  if (!raw) return null;
  const stdout = typeof raw.stdout_line_count === "number" ? raw.stdout_line_count : 0;
  const stderr = typeof raw.stderr_line_count === "number" ? raw.stderr_line_count : 0;
  if (stdout <= 0 && stderr <= 0) return null;
  return `${text.rawAgentStdout} ${stdout} / ${text.rawAgentStderr} ${stderr}`;
}

function turnStateDisplayDetail(turnState: TurnState, text: LocaleMessages, locale: string): string {
  if (turnState.state === "waiting_for_user") return text.turnStateUserTurnHint;
  if (turnState.state === "worker_pending") {
    return localeSafeDisplayText(turnState.detail, locale, text.turnStateWorkerPendingHint);
  }
  if (turnState.state === "agent_scheduled") {
    return localeSafeDisplayText(turnState.detail, locale, text.turnStateAgentScheduledHint);
  }
  if (turnState.state === "needs_attention") {
    return localeSafeDisplayText(turnState.detail, locale, text.turnStateNeedsAttentionHint);
  }
  if (turnState.state === "agent_running") {
    return localeSafeDisplayText(turnState.detail, locale, text.turnStateAgentTurnHint);
  }
  if (turnState.state === "stale_runner") {
    return localeSafeDisplayText(turnState.detail, locale, text.turnStateNeedsAttentionHint);
  }
  return localeSafeDisplayText(
    turnState.detail,
    locale,
    turnState.input_attention ? text.turnStateUserTurnHint : text.turnStateAgentTurnHint
  );
}

function agentInputFormClassName(turnState: TurnState, extraClassName = "") {
  return ["agent-chat-form", turnState.input_attention ? "is-user-turn" : "", extraClassName]
    .filter(Boolean)
    .join(" ");
}

function turnStateClassName(turnState: TurnState) {
  return `turn-state-bar is-${turnState.state.replace(/_/g, "-").replace(/[^a-z0-9-]/gi, "-")}`;
}

function turnStateLabel(turnState: TurnState, text: LocaleMessages, locale?: string) {
  switch (turnState.state) {
    case "agent_running":
      return text.turnStateAgentRunning;
    case "worker_pending":
      return text.turnStateWorkerPending;
    case "agent_scheduled":
      return text.turnStateAgentScheduled;
    case "stale_runner":
      return text.turnStateStaleRunner;
    case "needs_attention":
      return text.turnStateNeedsAttention;
    case "waiting_for_user":
      return text.turnStateWaitingForUser;
    default:
      return localeSafeDisplayText(turnState.label, locale, text.turnStateObserved);
  }
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

function RawAgentStream({
  busy,
  text,
  locale,
  events,
  rawTranscript,
  submitShortcut,
  turnState,
  scrollResetKey,
  onSubmit
}: {
  busy: boolean;
  text: LocaleMessages;
  locale: string;
  events: RawAgentEvent[];
  rawTranscript: AgentRawTranscript | null;
  submitShortcut: ChatSubmitShortcut;
  turnState: TurnState;
  scrollResetKey: string;
  onSubmit: (objective: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");
  const latestEvent = events[events.length - 1];
  const rawLines = React.useMemo<AgentRawTranscriptViewLine[]>(() => {
    if (!rawTranscript) return [];
    const lines = [
      ...(rawTranscript.stdout_tail_lines ?? []).map((line) => ({ ...line, stream: "stdout" as const })),
      ...(rawTranscript.stderr_tail_lines ?? []).map((line) => ({ ...line, stream: "stderr" as const }))
    ];
    return lines.sort(compareRawTranscriptViewLines);
  }, [rawTranscript]);
  const rawKey = rawLines.length
    ? `${rawTranscript?.session_id ?? "raw"}:${rawTranscript?.stdout_line_count ?? 0}:${
        rawTranscript?.stderr_line_count ?? 0
      }:${rawTranscript?.updated_at ?? ""}`
    : `${events.length}:${latestEvent?.id ?? "empty"}`;
  const activeRawLineKey =
    rawTranscript && rawTranscript.stdout_line_count > 0
      ? `stdout-${rawTranscript.stdout_line_count}`
      : rawLines.length
        ? `${rawLines[rawLines.length - 1].stream}-${rawLines[rawLines.length - 1].line_number}`
        : null;
  const rawScroll = useStickyBottomScroll<HTMLDivElement>(rawKey, scrollResetKey);

  async function submitDraft() {
    const objective = draft.trim();
    if (!objective) return;
    setDraft("");
    await onSubmit(objective);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await submitDraft();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!shouldSubmitTextarea(event, submitShortcut) || busy || !draft.trim()) return;
    event.preventDefault();
    void submitDraft();
  }

  return (
    <div className="raw-agent-stream">
      <div className="raw-agent-head">
        <div>
          <span>{text.rawAgentTitle}</span>
          <small>
            {rawLines.length ? rawTranscriptTailSummary(rawTranscript, rawLines, text) : `${events.length} transcript items`}
            {rawTranscript?.session_id
              ? ` · ${text.rawAgentStdout} ${rawTranscript.stdout_line_count} · ${text.rawAgentStderr} ${rawTranscript.stderr_line_count}`
              : ""}
            {rawTranscript?.updated_at ? ` · ${text.rawAgentUpdated} ${formatDate(rawTranscript.updated_at)}` : ""}
          </small>
        </div>
        {rawTranscript?.session_id ? (
          <div className="raw-agent-head-actions">
            {rawTranscript.stdout_download_url ? (
              <a
                className="secondary-button text-link-button"
                href={`${apiBase}${rawTranscript.stdout_download_url}`}
                target="_blank"
                rel="noreferrer"
              >
                {text.rawAgentOpenStdout}
              </a>
            ) : null}
            {rawTranscript.stderr_download_url ? (
              <a
                className="secondary-button text-link-button"
                href={`${apiBase}${rawTranscript.stderr_download_url}`}
                target="_blank"
                rel="noreferrer"
              >
                {text.rawAgentOpenStderr}
              </a>
            ) : null}
          </div>
        ) : null}
      </div>
      <TurnStateBar text={text} locale={locale} turnState={turnState} />
      <div className="raw-agent-log" ref={rawScroll.ref} onScroll={rawScroll.onScroll}>
        {rawLines.length ? (
          <>
            {rawLines.map((line) => (
              <RawTranscriptLineCard
                active={turnState.owner === "agent" && `${line.stream}-${line.line_number}` === activeRawLineKey}
                key={`${line.stream}-${line.line_number}`}
                line={line}
                text={text}
              />
            ))}
            {events.length ? (
              <details className="raw-agent-detail raw-agent-index">
                <summary>
                  {text.rawAgentIndexedEvents} ({events.length})
                </summary>
                <div className="raw-agent-index-list">{events.map((event) => renderRawAgentEvent(event))}</div>
              </details>
            ) : null}
          </>
        ) : events.length ? (
          events.map((event) => renderRawAgentEvent(event))
        ) : (
          <EmptyInline text={text.rawAgentEmpty} />
        )}
      </div>
      <form className={agentInputFormClassName(turnState, "raw-agent-form")} onSubmit={(event) => void submit(event)}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={text.agentChatPlaceholder}
          rows={3}
        />
        <button className="primary-button" disabled={busy || !draft.trim()} type="submit">
          {busy ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
          {text.createAgentTaskContract}
        </button>
      </form>
    </div>
  );
}

function compareRawTranscriptViewLines(left: AgentRawTranscriptViewLine, right: AgentRawTranscriptViewLine): number {
  const leftTime = rawTranscriptLineTimeMs(left);
  const rightTime = rawTranscriptLineTimeMs(right);
  if (leftTime !== null && rightTime !== null && leftTime !== rightTime) return leftTime - rightTime;
  return rawTranscriptLineFallbackOrder(left) - rawTranscriptLineFallbackOrder(right);
}

function rawTranscriptLineTimeMs(line: AgentRawTranscriptViewLine): number | null {
  const event = line.parsed;
  const parsedTimestamp =
    textField(event?.timestamp) ?? textField(event?.time) ?? textField(event?.created_at) ?? textField(event?.createdAt);
  const timestamp = parsedTimestamp ?? line.text.match(/\d{4}-\d{2}-\d{2}T[^\s]+/)?.[0] ?? null;
  if (!timestamp) return null;
  const value = Date.parse(timestamp);
  return Number.isFinite(value) ? value : null;
}

function rawTranscriptLineFallbackOrder(line: AgentRawTranscriptViewLine): number {
  const streamRank = line.stream === "stdout" ? 0 : 1;
  return streamRank * 1_000_000_000 + line.line_number;
}

function rawTranscriptTailSummary(
  rawTranscript: AgentRawTranscript | null,
  rawLines: AgentRawTranscriptViewLine[],
  text: LocaleMessages
): string {
  const stdoutTailCount = rawTranscript?.stdout_tail_lines?.length ?? 0;
  const stderrTailCount = rawTranscript?.stderr_tail_lines?.length ?? 0;
  const stdoutRange = rawTranscriptLineRange(rawTranscript?.stdout_tail_lines ?? []);
  const stderrRange = rawTranscriptLineRange(rawTranscript?.stderr_tail_lines ?? []);
  return [
    `${rawLines.length} ${text.rawAgentTail}`,
    `${text.rawAgentStdout} ${stdoutTailCount}${stdoutRange}`,
    `${text.rawAgentStderr} ${stderrTailCount}${stderrRange}`
  ].join(" · ");
}

function rawTranscriptLineRange(lines: AgentRawTranscriptLine[]): string {
  const first = lines[0]?.line_number;
  const last = lines[lines.length - 1]?.line_number;
  if (typeof first !== "number" || typeof last !== "number") return "";
  return first === last ? ` #${first}` : ` #${first}-#${last}`;
}

function RawTranscriptLineCard({
  line,
  active,
  text
}: {
  line: AgentRawTranscriptViewLine;
  active: boolean;
  text: LocaleMessages;
}) {
  const event = line.parsed;
  const view = rawCodexLineView(line);
  return (
    <div className={`raw-agent-event raw-cli-line ${view.kind} ${active ? "is-active" : ""}`}>
      <div className="raw-cli-gutter" aria-hidden="true">
        <span>#{line.line_number}</span>
        <b>{view.prompt}</b>
      </div>
      <div className="raw-cli-content">
        <div className="raw-cli-head">
          <strong>{view.title}</strong>
          <span>{view.level}</span>
        </div>
        {view.body ? <pre className="raw-cli-body">{view.body}</pre> : null}
        <details className="raw-agent-detail">
          <summary>{event ? text.rawAgentRawJsonl : text.rawAgentRawLine}</summary>
          <pre>{line.text}</pre>
        </details>
        {event ? (
          <details className="raw-agent-detail compact">
            <summary>{text.rawAgentParsedEvent}</summary>
            <pre>{rawDetailText(event)}</pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}

type RawCodexLineView = {
  kind: "stderr" | "message" | "command" | "tool" | "edit" | "lifecycle" | "event";
  prompt: string;
  title: string;
  level: string;
  body: string | null;
};

function rawCodexLineView(line: AgentRawTranscriptViewLine): RawCodexLineView {
  const event = line.parsed;
  if (!event) {
    return {
      kind: line.stream === "stderr" ? "stderr" : "event",
      prompt: line.stream === "stderr" ? "err" : "raw",
      title: line.stream === "stderr" ? "Codex stderr" : "Raw JSONL line",
      level: line.stream,
      body: line.text
    };
  }
  const eventType = textField(event.type) ?? "jsonl";
  const item = objectRecord(event.item);
  const itemType = textField(item?.type) ?? "";
  const command = textField(item?.command) ?? textField(item?.name) ?? textField(item?.tool_name);
  const output = textField(item?.aggregated_output) ?? textField(item?.output) ?? textField(item?.summary);
  if (line.stream === "stderr") {
    return { kind: "stderr", prompt: "err", title: "Codex stderr", level: eventType, body: line.text };
  }
  if (itemType === "agent_message") {
    return { kind: "message", prompt: "codex", title: "Codex", level: eventType, body: textField(item?.text) ?? null };
  }
  if (itemType.includes("command") || itemType.includes("exec")) {
    const commandBody = command ? `$ ${command}` : null;
    const body = [commandBody, output].filter(Boolean).join("\n\n") || codexEventBody(event) || null;
    return {
      kind: "command",
      prompt: eventType === "item.started" ? "$ ..." : "$",
      title: eventType === "item.started" ? "Command started" : "Command execution",
      level: itemType || eventType,
      body
    };
  }
  if (itemType.includes("tool")) {
    return {
      kind: "tool",
      prompt: "tool",
      title: command ? `Tool use: ${command}` : "Tool use",
      level: itemType || eventType,
      body: output ?? codexEventBody(event)
    };
  }
  if (itemType.includes("patch") || itemType.includes("edit")) {
    return {
      kind: "edit",
      prompt: "edit",
      title: "Code edit",
      level: itemType || eventType,
      body: output ?? codexEventBody(event)
    };
  }
  if (eventType === "thread.started" || eventType === "turn.started" || eventType === "turn.completed") {
    return { kind: "lifecycle", prompt: "sys", title: humanizeLabel(eventType), level: eventType, body: codexEventBody(event) };
  }
  return {
    kind: "event",
    prompt: "evt",
    title: codexEventTitle(event),
    level: itemType || eventType,
    body: codexEventBody(event)
  };
}

function renderRawAgentEvent(event: RawAgentEvent) {
  return (
    <div className={`raw-agent-event ${isActiveRawEvent(event) ? "is-active" : ""}`} key={event.id}>
      <div className="raw-agent-line">
        <span>{formatDate(event.timestamp)}</span>
        <b>{event.source}</b>
        <em>{event.level}</em>
        <strong>{event.title}</strong>
      </div>
      {event.body ? <div className="raw-agent-body">{event.body}</div> : null}
      {event.details?.map((detail) => (
        <details className="raw-agent-detail" key={detail.label}>
          <summary>{detail.label}</summary>
          <pre>{rawDetailText(detail.value)}</pre>
        </details>
      ))}
    </div>
  );
}

function rawDetailText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function UserAvatar({ src }: { src: string | null }) {
  if (src) {
    return <img className="chat-avatar user-avatar" src={src} alt="" aria-hidden="true" />;
  }
  return (
    <span className="chat-avatar user-avatar default" aria-hidden="true">
      <UserCircle size={23} />
    </span>
  );
}

function TableeAvatar({
  state,
  active
}: {
  state: TableeMotionState;
  active: boolean;
}) {
  return (
    <img
      src="/mascot/tablee-avatar.svg"
      alt=""
      aria-hidden="true"
      className={`chat-avatar tablee-avatar ${active ? "is-working" : state !== "idle" ? `is-${state}` : ""}`}
    />
  );
}

function agentChatWaitObservationItems(brief: Record<string, unknown> | null | undefined, text: LocaleMessages): string[] {
  const observation = objectRecord(brief?.agent_session_observation);
  if (!observation) return [];
  const items: string[] = [];
  const status = textField(observation.status);
  const turnIndex = numberField(observation.turn_index);
  if (status) {
    items.push(`${text.agentReplyWaitMetaStatus}: ${status}${turnIndex !== null ? ` · turn ${turnIndex}` : ""}`);
  }
  const lastOutputSeconds = numberField(observation.last_codex_output_seconds_ago);
  if (lastOutputSeconds !== null) {
    items.push(`${text.agentReplyWaitMetaOutput}: ${formatElapsedSeconds(lastOutputSeconds)} ${text.agentReplyWaitMetaAgo}`);
  }
  const raw = objectRecord(observation.raw_transcript);
  const stdout = numberField(raw?.stdout_line_count) ?? 0;
  const stderr = numberField(raw?.stderr_line_count) ?? 0;
  if (stdout > 0 || stderr > 0) {
    items.push(`${text.agentReplyWaitMetaRaw}: stdout ${stdout} / stderr ${stderr}`);
  }
  return items.slice(0, 3);
}

function AgentConversationTurnCard({
  turn,
  text,
  userAvatarSrc,
  tableeMotionState,
  onActionOpen
}: {
  turn: AgentConversationTurn;
  text: LocaleMessages;
  userAvatarSrc: string | null;
  tableeMotionState: TableeMotionState;
  onActionOpen: (action: AgentChatAction) => void;
}) {
  const assistant = turn.assistant;
  const active = isActiveAgentTurn(turn);
  const outcome = active ? "pending" : assistant?.actionSummary?.outcome;
  const outcomeLabel = active ? text.agentReplyPending : agentChatOutcomeLabel(outcome);
  const statusClass = agentChatOutcomeClass(outcome);
  const hasPrimaryNext = Boolean(assistant?.actionSummary?.next_step?.target_tab);
  const visibleActions = hasPrimaryNext ? [] : assistant?.actions?.slice(0, 2) ?? [];
  const waitObservationItems = active ? agentChatWaitObservationItems(assistant?.responseBrief, text) : [];
  return (
    <article className={`agent-turn-card ${active ? "is-active" : ""}`}>
      {turn.user ? (
        <section className="chat-message-row user">
          <div className="chat-message-stack">
            <div className="chat-message-meta">
              <span>{text.youAsked}</span>
              <small>{turn.createdAt ? formatDate(turn.createdAt) : text.chatTurnStatus}</small>
            </div>
            <div className="chat-bubble user">
              <p>{turn.user.text}</p>
            </div>
          </div>
          <UserAvatar src={userAvatarSrc} />
        </section>
      ) : null}
      {assistant ? (
        <section className="chat-message-row assistant">
          <TableeAvatar state={tableeMotionState} active={active} />
          <div className="chat-message-stack">
            <div className="chat-message-meta">
              <span>{active ? text.agentReplyPendingTitle : text.tableeAnswered}</span>
              {outcomeLabel ? <small className={statusClass}>{outcomeLabel}</small> : null}
            </div>
            <div className={`chat-bubble assistant ${active ? "pending" : ""}`}>
              {assistant.text.split("\n").map((line, index) => (
                <p key={`${index}-${line}`}>{line}</p>
              ))}
            </div>
            {waitObservationItems.length ? (
              <div className="agent-chat-wait-meta">
                {waitObservationItems.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            ) : null}
            {assistant.actionSummary ? (
              <AgentChatSummaryCard summary={assistant.actionSummary} text={text} onActionOpen={onActionOpen} />
            ) : null}
            {visibleActions.length ? (
              <div className="agent-turn-actions">
                {visibleActions.map((action) => (
                  <button
                    className="agent-chat-action-button"
                    key={`${action.type}-${action.label}`}
                    onClick={() => onActionOpen(action)}
                    type="button"
                  >
                    <span>{action.status.replace(/_/g, " ")}</span>
                    <strong>{action.label}</strong>
                    <small>{agentChatActionLabel(action, text)}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </section>
      ) : (
        <section className="chat-message-row assistant">
          <TableeAvatar state={tableeMotionState} active />
          <div className="chat-message-stack">
            <div className="chat-message-meta">
              <span>{text.agentReplyPendingTitle}</span>
              <small className="badge">{text.agentReplyPending}</small>
            </div>
            <div className="chat-bubble assistant pending">
              <p>{text.agentReplyPending}</p>
            </div>
          </div>
        </section>
      )}
    </article>
  );
}

function AgentChatDock({
  busy,
  text,
  locale,
  messages,
  submitShortcut,
  userAvatarSrc,
  latestContract,
  tableeMotionState,
  turnState,
  scrollResetKey,
  onSubmit,
  onActionOpen
}: {
  busy: boolean;
  text: LocaleMessages;
  locale: string;
  messages: AgentChatMessage[];
  submitShortcut: ChatSubmitShortcut;
  userAvatarSrc: string | null;
  latestContract: Artifact | null;
  tableeMotionState: TableeMotionState;
  turnState: TurnState;
  scrollResetKey: string;
  onSubmit: (objective: string) => Promise<void>;
  onActionOpen: (action: AgentChatAction) => void;
}) {
  const [draft, setDraft] = React.useState("");
  const turns = React.useMemo(() => buildAgentConversationTurns(messages), [messages]);
  const recentTurns = turns.slice(-5);
  const olderTurns = turns.slice(0, -5);
  const latestTurn = turns[turns.length - 1];
  const chatScroll = useStickyBottomScroll<HTMLDivElement>(
    `${turns.length}:${latestTurn?.id ?? "empty"}:${latestTurn?.user?.text.length ?? 0}:${latestTurn?.assistant?.text.length ?? 0}`,
    scrollResetKey
  );

  async function submitDraft() {
    const objective = draft.trim();
    if (!objective) return;
    setDraft("");
    await onSubmit(objective);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await submitDraft();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!shouldSubmitTextarea(event, submitShortcut) || busy || !draft.trim()) return;
    event.preventDefault();
    void submitDraft();
  }

  return (
    <div className="agent-chat-dock">
      <div className="agent-chat-header">
        <div className="agent-chat-heading">
          <div>
            <div className="agent-chat-title">
              <MessageSquare size={16} />
              {text.agentChatTitle}
            </div>
            <small>{text.agentChatSubtitle}</small>
          </div>
        </div>
        <div className="agent-chat-header-actions">
          <span className="agent-scope-pill">{text.agentWorkspacePersistent}</span>
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
      </div>
      <TurnStateBar text={text} locale={locale} turnState={turnState} />
      <div className="agent-chat-log" ref={chatScroll.ref} onScroll={chatScroll.onScroll}>
        {turns.length ? (
          <>
          {olderTurns.length ? (
            <details className="agent-chat-history">
              <summary>
                {text.earlierConversation}
                <span>{olderTurns.length}</span>
              </summary>
              <div className="agent-chat-history-list">
                {olderTurns.map((turn) => (
                  <AgentConversationTurnCard
                    key={turn.id}
                    turn={turn}
                    text={text}
                    userAvatarSrc={userAvatarSrc}
                    tableeMotionState={tableeMotionState}
                    onActionOpen={onActionOpen}
                  />
                ))}
              </div>
            </details>
          ) : null}
          {recentTurns.map((turn) => (
            <AgentConversationTurnCard
              key={turn.id}
              turn={turn}
              text={text}
              userAvatarSrc={userAvatarSrc}
              tableeMotionState={tableeMotionState}
              onActionOpen={onActionOpen}
            />
          ))}
          </>
        ) : (
          <EmptyInline text={text.agentChatPlaceholder} />
        )}
      </div>
      <form className={agentInputFormClassName(turnState)} onSubmit={(event) => void submit(event)}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
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
  onWorkerMessage,
  onCancelWorker
}: {
  text: LocaleMessages;
  jobs: Job[];
  events: AgentWorkerEvent[];
  activity: AgentActivityResponse | null;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
  onCancelWorker: (jobId: string) => Promise<void>;
}) {
  const [position, setPosition] = React.useState(() => loadAgentActivityPosition());
  const [minimized, setMinimized] = React.useState(() => loadAgentActivityMinimized());
  const dragStateRef = React.useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startLeft: number;
    startTop: number;
  } | null>(null);
  const workerEvents = React.useMemo(() => {
    const now = Date.now() + tick;
    const fromActivity = activity?.workers ?? [];
    const fromJobs = jobs.flatMap((job) => workerEventsFromJob(job, now, text));
    const merged = [...fromJobs, ...events, ...fromActivity];
    const byKey = new Map<string, AgentWorkerEvent>();
    merged.forEach((event) => {
      byKey.set(`${event.worker_id}-${event.job_id ?? event.agent_session_id ?? event.updated_at ?? event.created_at ?? "event"}`, event);
    });
    return [...byKey.values()]
      .filter((event) => isVisibleWorkerEvent(event, now))
      .sort(compareWorkerEvents)
      .slice(0, 8);
  }, [activity, events, jobs, text, tick]);

  if (!workerEvents.length) {
    return null;
  }

  function persistPosition(nextPosition: AgentActivityPosition) {
    setPosition(nextPosition);
    window.localStorage.setItem(agentActivityPositionStorageKey, JSON.stringify(nextPosition));
  }

  function toggleMinimized() {
    setMinimized((current) => {
      const next = !current;
      window.localStorage.setItem(agentActivityMinimizedStorageKey, next ? "1" : "0");
      return next;
    });
  }

  function handleDragStart(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button,a,input,textarea,select")) return;
    const rail = event.currentTarget.closest(".agent-activity-rail") as HTMLElement | null;
    if (!rail) return;
    const rect = rail.getBoundingClientRect();
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startLeft: rect.left,
      startTop: rect.top
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleDragMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const railWidth = minimized ? 244 : 352;
    const railHeight = minimized ? 64 : 560;
    const nextPosition = constrainAgentActivityPosition({
      left: drag.startLeft + event.clientX - drag.startX,
      top: drag.startTop + event.clientY - drag.startY
    }, railWidth, railHeight);
    setPosition(nextPosition);
  }

  function handleDragEnd(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragStateRef.current = null;
    const railWidth = minimized ? 244 : 352;
    const railHeight = minimized ? 64 : 560;
    persistPosition(
      constrainAgentActivityPosition(
        {
          left: drag.startLeft + event.clientX - drag.startX,
          top: drag.startTop + event.clientY - drag.startY
        },
        railWidth,
        railHeight
      )
    );
  }

  return (
    <aside
      className={`agent-activity-rail ${minimized ? "is-minimized" : ""}`}
      aria-label={text.agentActivityTitle}
      style={{ left: `${position.left}px`, top: `${position.top}px` }}
    >
      <div
        className="agent-activity-header"
        onPointerDown={handleDragStart}
        onPointerMove={handleDragMove}
        onPointerUp={handleDragEnd}
        onPointerCancel={handleDragEnd}
      >
        <div>
          <div className="agent-activity-title">
            <Activity size={16} />
            {text.agentActivityTitle}
          </div>
          <small>{text.agentActivitySubtitle}</small>
        </div>
        <div className="agent-activity-controls">
          <span className="agent-scope-pill live">{text.agentActivityLiveOnly}</span>
          <button className="icon-button" onClick={toggleMinimized} title={minimized ? "Expand" : "Minimize"} type="button">
            {minimized ? <Plus size={14} /> : <Minus size={14} />}
          </button>
        </div>
      </div>
      {!minimized && workerEvents.length ? (
        <div className="agent-worker-list">
          {workerEvents.map((event) => (
            <AgentWorkerCard
              key={`${event.worker_id}-${event.job_id ?? event.agent_session_id ?? event.updated_at ?? event.created_at}`}
              event={event}
              text={text}
              tick={tick}
              onWorkerMessage={onWorkerMessage}
              onCancelWorker={onCancelWorker}
            />
          ))}
        </div>
      ) : null}
    </aside>
  );
}

type AgentActivityPosition = { left: number; top: number };
const agentActivityPositionStorageKey = "tablex.agentActivity.position";
const agentActivityMinimizedStorageKey = "tablex.agentActivity.minimized";

function loadAgentActivityPosition(): AgentActivityPosition {
  const fallback = defaultAgentActivityPosition();
  try {
    const raw = window.localStorage.getItem(agentActivityPositionStorageKey);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<AgentActivityPosition>;
    if (typeof parsed.left !== "number" || typeof parsed.top !== "number") return fallback;
    return constrainAgentActivityPosition({ left: parsed.left, top: parsed.top }, 352, 560);
  } catch {
    return fallback;
  }
}

function loadAgentActivityMinimized(): boolean {
  return window.localStorage.getItem(agentActivityMinimizedStorageKey) === "1";
}

function defaultAgentActivityPosition(): AgentActivityPosition {
  if (typeof window === "undefined") return { left: 960, top: 82 };
  return {
    left: Math.max(14, window.innerWidth - 370),
    top: 82
  };
}

function constrainAgentActivityPosition(position: AgentActivityPosition, width: number, height: number): AgentActivityPosition {
  if (typeof window === "undefined") return position;
  const margin = 10;
  return {
    left: Math.max(margin, Math.min(position.left, Math.max(margin, window.innerWidth - Math.min(width, window.innerWidth - margin * 2) - margin))),
    top: Math.max(margin, Math.min(position.top, Math.max(margin, window.innerHeight - Math.min(height, window.innerHeight - margin * 2) - margin)))
  };
}

function AgentWorkerCard({
  event,
  text,
  tick,
  onWorkerMessage,
  onCancelWorker
}: {
  event: AgentWorkerEvent;
  text: LocaleMessages;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
  onCancelWorker: (jobId: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");
  const [cancelling, setCancelling] = React.useState(false);
  const displaySeries = animatedTokenSeries(event, tick);
  const maxTokens = Math.max(...displaySeries.map((point) => point.tokens), 1);
  const currentTokens = displaySeries[displaySeries.length - 1]?.tokens ?? 0;
  const cumulativeTokens = cumulativeTokenTotal(displaySeries);
  const isLive = isLiveWorkerStatus(event.status);
  const isWaiting = isWaitingWorkerStatus(event.status);
  const description = event.human_description;
  const title = description?.title || event.headline;
  const summary = description?.summary || event.detail;
  const elapsedFrom = event.started_at ?? event.created_at ?? event.updated_at ?? null;
  const elapsed = elapsedFrom ? formatElapsed(Date.parse(elapsedFrom), Date.now() + tick) : "-";
  const canCancel = canCancelWorkerEvent(event);

  async function submit(eventSubmit: React.FormEvent) {
    eventSubmit.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setDraft("");
    await onWorkerMessage(`[worker:${event.worker_id}] ${value}`);
  }

  async function cancel() {
    if (!canCancel || cancelling || !event.job_id) return;
    setCancelling(true);
    try {
      await onCancelWorker(event.job_id);
    } finally {
      setCancelling(false);
    }
  }

  return (
    <section className={`agent-worker-card ${event.status} ${isLive ? "active" : ""} ${isWaiting ? "waiting" : ""}`}>
      <div className="agent-worker-topline">
        <strong>{event.display_name}</strong>
        <div className="agent-worker-actions">
          <span className={isLive ? "live" : isWaiting ? "waiting" : ""}>{workerStatusLabel(event.status, text)}</span>
          {canCancel ? (
            <button
              className="agent-worker-cancel"
              disabled={cancelling}
              onClick={() => void cancel()}
              title={text.workerCancelLabel}
              type="button"
            >
              {cancelling ? <Loader2 className="spin" size={13} /> : <X size={14} />}
            </button>
          ) : null}
        </div>
      </div>
      <p>{title}</p>
      <small>{summary}</small>
      <div className="agent-worker-context">
        {event.project_name ? (
          <span>
            {text.workerProjectLabel}: <strong>{event.project_name}</strong>
          </span>
        ) : null}
        {event.job_type ? (
          <span>
            {text.workerJobLabel}: <strong>{humanizeLabel(event.job_type)}</strong>
          </span>
        ) : null}
        <span>
          {text.workerIdLabel}: <strong>{shortId(event.job_id ?? event.agent_session_id ?? event.worker_id)}</strong>
        </span>
        <span>
          {text.workerElapsedLabel}: <strong>{elapsed}</strong>
        </span>
      </div>
      <div className={`token-sparkline ${isLive ? "live" : isWaiting ? "waiting" : ""}`} aria-label={text.estimatedTokens}>
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
        <div>
          <span>{text.currentTokens}</span>
          <strong>{formatTokenCount(currentTokens)}</strong>
        </div>
        <div>
          <span>{text.cumulativeTokens}</span>
          <strong>{formatTokenCount(cumulativeTokens)}</strong>
        </div>
      </div>
      <small className="agent-worker-estimate">{isWaiting ? text.telemetryWaiting : text.telemetryEstimate}</small>
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

function optimisticWorkerEvent(projectId: string, message: string, text: LocaleMessages): AgentWorkerEvent {
  const now = new Date().toISOString();
  const base = Math.max(32, Math.min(160, message.length));
  return {
    worker_id: "agent-chat-orchestrator",
    display_name: text.workerDisplayOrchestrator,
    status: "running",
    headline: text.workerOptimisticHeadline,
    detail: message,
    job_id: `local-${Date.now()}`,
    project_id: projectId,
    target_tab: "Home",
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

function isLiveWorkerStatus(status: string) {
  return status === "running";
}

function isWaitingWorkerStatus(status: string) {
  return ["queued", "approval_required", "starting", "between_turns", "waiting_for_runner"].includes(status);
}

function isRunningWorkerStatus(status: string) {
  return isLiveWorkerStatus(status) || isWaitingWorkerStatus(status);
}

const QUEUED_WORKER_ACTIVITY_TTL_MS = 5 * 60 * 1000;
const TRANSIENT_WORKER_ACTIVITY_TTL_MS = 15 * 1000;
const FINISHED_WORKER_ACTIVITY_TTL_MS = 9 * 1000;

function isTerminalWorkerStatus(status: string) {
  return ["succeeded", "failed", "cancelled", "timed_out"].includes(status);
}

function timestampAgeMs(value: string | null | undefined, now: number): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return now - timestamp;
}

function isRecentTimestamp(value: string | null | undefined, now: number, ttlMs: number) {
  const ageMs = timestampAgeMs(value, now);
  return ageMs !== null && ageMs >= 0 && ageMs < ttlMs;
}

function isScheduledForFuture(value: string | null | undefined, now: number) {
  if (!value) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp > now;
}

function isActiveWorkerEventAt(event: AgentWorkerEvent, now: number) {
  if (!event.active || !isRunningWorkerStatus(event.status)) return false;
  if (event.status === "queued") {
    if (isScheduledForFuture(event.run_after, now)) return false;
    return isRecentTimestamp(event.created_at ?? event.updated_at, now, QUEUED_WORKER_ACTIVITY_TTL_MS);
  }
  return true;
}

function jobActiveForActivity(job: Job, now: number = Date.now()) {
  if (job.status === "running" || job.status === "approval_required") return true;
  if (job.status === "queued") {
    if (isScheduledForFuture(job.run_after, now)) return false;
    return isRecentTimestamp(job.created_at, now, QUEUED_WORKER_ACTIVITY_TTL_MS);
  }
  return false;
}

function eventActiveForActivity(
  status: string,
  explicitActive: boolean | undefined,
  createdAt: string | undefined,
  runAfter: string | null | undefined,
  now: number
) {
  if (status === "running" || status === "approval_required") return explicitActive !== false;
  if (status === "queued") {
    if (isScheduledForFuture(runAfter, now)) return false;
    return explicitActive !== false && isRecentTimestamp(createdAt, now, QUEUED_WORKER_ACTIVITY_TTL_MS);
  }
  return false;
}

function canCancelWorkerEvent(event: AgentWorkerEvent) {
  const jobId = event.job_id;
  if (!jobId) return false;
  return !jobId.startsWith("local-") && !isTerminalWorkerStatus(event.status);
}

function hasLiveAgentOrModelActivity(
  jobs: Job[],
  events: AgentWorkerEvent[],
  activity: AgentActivityResponse | null
) {
  const now = Date.now();
  const allEvents = [...events, ...(activity?.workers ?? [])];
  return allEvents.some((event) => isActiveWorkerEventAt(event, now)) || jobs.some((job) => jobActiveForActivity(job, now));
}

function isVisibleWorkerEvent(event: AgentWorkerEvent, now: number) {
  const timestamp = Date.parse(event.updated_at ?? event.created_at ?? "");
  if (event.job_id?.startsWith("local-") && Number.isFinite(timestamp) && now - timestamp > TRANSIENT_WORKER_ACTIVITY_TTL_MS) {
    return false;
  }
  if (isLiveWorkerStatus(event.status)) {
    if (isActiveWorkerEventAt(event, now)) return true;
    return Number.isFinite(timestamp) && now - timestamp < TRANSIENT_WORKER_ACTIVITY_TTL_MS;
  }
  if (isWaitingWorkerStatus(event.status)) {
    if (isActiveWorkerEventAt(event, now)) return true;
    return Number.isFinite(timestamp) && now - timestamp < TRANSIENT_WORKER_ACTIVITY_TTL_MS;
  }
  return Number.isFinite(timestamp) && now - timestamp < FINISHED_WORKER_ACTIVITY_TTL_MS;
}

function compareWorkerEvents(left: AgentWorkerEvent, right: AgentWorkerEvent) {
  const leftRank = workerStatusRank(left.status);
  const rightRank = workerStatusRank(right.status);
  if (leftRank !== rightRank) return leftRank - rightRank;
  const leftTime = Date.parse(left.updated_at ?? left.created_at ?? "") || 0;
  const rightTime = Date.parse(right.updated_at ?? right.created_at ?? "") || 0;
  return rightTime - leftTime;
}

function workerStatusRank(status: string) {
  if (status === "running") return 0;
  if (status === "approval_required") return 1;
  if (["starting", "between_turns", "waiting_for_runner"].includes(status)) return 2;
  if (status === "queued") return 3;
  return 3;
}

function animatedTokenSeries(event: AgentWorkerEvent, tick: number): TokenSeriesPoint[] {
  if (!isLiveWorkerStatus(event.status)) return event.token_usage.series;
  return event.token_usage.series.map((point, index) => ({
    ...point,
    tokens: Math.max(1, Math.round(point.tokens + ((tick + index) % 3) * Math.max(4, Math.round(point.tokens * 0.035))))
  }));
}

function workerStatusLabel(status: string, text: LocaleMessages) {
  if (status === "queued") return text.workerStatusQueued;
  if (status === "running") return text.workerStatusRunning;
  if (status === "approval_required") return text.workerStatusApproval;
  if (status === "waiting_for_agent") return text.workerStatusWaitingForAgent;
  if (["starting", "between_turns", "waiting_for_runner"].includes(status)) return text.workerStatusWaitingForRunner;
  if (["succeeded", "failed", "cancelled", "timed_out"].includes(status)) return text.workerStatusFinished;
  return humanizeLabel(status);
}

function shortId(value: string) {
  if (value.length <= 12) return value;
  return value.slice(0, 12);
}

function humanizeLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatElapsed(startMs: number, nowMs: number) {
  if (!Number.isFinite(startMs) || !Number.isFinite(nowMs)) return "-";
  const seconds = Math.max(0, Math.floor((nowMs - startMs) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function cumulativeTokenTotal(series: TokenSeriesPoint[]) {
  return series.reduce((sum, point) => sum + Math.max(0, point.tokens), 0);
}

function formatTokenCount(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(Math.round(value));
}

function coerceHumanDescription(raw: unknown): AgentWorkerEvent["human_description"] {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const title = typeof record.title === "string" ? record.title : undefined;
  const summary = typeof record.summary === "string" ? record.summary : typeof record.detail === "string" ? record.detail : undefined;
  const source = typeof record.source === "string" ? record.source : undefined;
  if (!title && !summary) return null;
  return { title, summary, source };
}

function jobHumanDescription(job: Job, text: LocaleMessages): RequiredHumanDescription {
  if (isMainAgentReplyWaitJob(job)) {
    return {
      title: text.workerMainAgentWaitTitle,
      summary: text.workerMainAgentWaitSummary,
      source: "main_agent_chat_wait_state"
    };
  }
  const fromOutput = coerceHumanDescription(job.output.human_description);
  if (fromOutput?.title || fromOutput?.summary) {
    return { title: fromOutput.title ?? jobHeadline(job), summary: fromOutput.summary ?? jobHeadline(job), source: fromOutput.source };
  }
  const fromContext = coerceHumanDescription(job.context.human_description);
  if (fromContext?.title || fromContext?.summary) {
    return { title: fromContext.title ?? jobHeadline(job), summary: fromContext.summary ?? jobHeadline(job), source: fromContext.source };
  }
  const defaultDescription = defaultJobHumanDescription(job, text);
  if (defaultDescription) return defaultDescription;
  const title = jobHeadline(job);
  if (job.status === "queued") {
    return {
      title,
      summary: `${text.workerWaitingSummaryPrefix} ${text.workerWaitingNoTelemetry}`,
      source: "job_status_fallback"
    };
  }
  return {
    title,
    summary: job.error_message ?? `${humanizeLabel(job.job_type)} is ${humanizeLabel(job.status)}.`,
    source: "job_status_fallback"
  };
}

function defaultJobHumanDescription(job: Job, text: LocaleMessages): RequiredHumanDescription | null {
  const waiting = job.status === "queued" ? `${text.workerWaitingSummaryPrefix} ` : "";
  if (job.job_type === "run_baseline") {
    return {
      title: text.workerRunBaselineTitle,
      summary: `${waiting}${text.workerRunBaselineSummary}`,
      source: "job_type_default"
    };
  }
  if (job.job_type === "train_model_candidates") {
    return {
      title: text.workerTrainCandidatesTitle,
      summary: `${waiting}${text.workerTrainCandidatesSummary}`,
      source: "job_type_default"
    };
  }
  if (job.job_type === "run_planned_agent_task_codex") {
    return {
      title: text.workerRunCodexTaskTitle,
      summary: `${waiting}${text.workerRunCodexTaskSummary}`,
      source: "job_type_default"
    };
  }
  if (job.job_type === "continue_autonomous_session") {
    return {
      title: text.workerContinueSessionTitle,
      summary: `${waiting}${text.workerContinueSessionSummary}`,
      source: "job_type_default"
    };
  }
  return null;
}

function workerEventsFromJob(job: Job, now: number, text: LocaleMessages): AgentWorkerEvent[] {
  const outputEvents = job.output.worker_events;
  if (Array.isArray(outputEvents)) {
    return outputEvents
      .map((event, index) => coerceWorkerEvent(event, job, index, now, text))
      .filter((event): event is AgentWorkerEvent => event !== null);
  }
  if (isTerminalJob(job)) {
    return [];
  }
  return [
    {
      worker_id: `job-${job.job_type}`,
      display_name: workerDisplayName(job.job_type, text),
      status: job.status,
      headline: jobHeadline(job),
      detail: job.error_message ?? jobHumanDescription(job, text).summary,
      job_id: job.id,
      job_type: job.job_type,
      project_id: job.project_id,
      target_tab: targetTabForJob(job.job_type),
      created_at: job.created_at,
      updated_at: job.updated_at,
      started_at: job.started_at,
      run_after: job.run_after,
      active: jobActiveForActivity(job, now),
      human_description: jobHumanDescription(job, text),
      token_usage: {
        source: job.status === "queued" ? "estimated_waiting_for_worker" : "estimated_until_runner_telemetry",
        is_estimate: true,
        series: estimatedJobTokens(job)
      }
    }
  ];
}

function coerceWorkerEvent(
  raw: unknown,
  job: Job,
  index: number,
  now: number,
  text: LocaleMessages
): AgentWorkerEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const eventStatus = typeof record.status === "string" ? record.status : job.status;
  const status = ["running", "succeeded", "failed", "cancelled", "approval_required"].includes(job.status)
    ? job.status
    : eventStatus;
  const createdAt = typeof record.created_at === "string" ? record.created_at : job.created_at;
  const runAfter = typeof record.run_after === "string" ? record.run_after : job.run_after;
  const explicitActive = typeof record.active === "boolean" ? record.active : undefined;
  const usage = record.token_usage;
  const series =
    usage && typeof usage === "object" && Array.isArray((usage as Record<string, unknown>).series)
      ? ((usage as Record<string, unknown>).series as unknown[])
          .map(coerceTokenPoint)
          .filter((item): item is TokenSeriesPoint => item !== null)
      : estimatedJobTokens(job);
  return {
    worker_id: typeof record.worker_id === "string" ? record.worker_id : `worker-${index}`,
    display_name: typeof record.display_name === "string" ? record.display_name : workerDisplayName(job.job_type, text),
    status,
    headline: typeof record.headline === "string" ? record.headline : jobHeadline(job),
    detail: typeof record.detail === "string" ? record.detail : jobHumanDescription(job, text).summary,
    job_id: typeof record.job_id === "string" ? record.job_id : job.id,
    job_type: typeof record.job_type === "string" ? record.job_type : job.job_type,
    project_id: typeof record.project_id === "string" ? record.project_id : job.project_id,
    project_name: typeof record.project_name === "string" ? record.project_name : null,
    target_tab: typeof record.target_tab === "string" ? record.target_tab : targetTabForJob(job.job_type),
    created_at: createdAt,
    updated_at: typeof record.updated_at === "string" ? record.updated_at : job.updated_at,
    started_at: typeof record.started_at === "string" ? record.started_at : job.started_at,
    run_after: runAfter,
    active: eventActiveForActivity(status, explicitActive ?? jobActiveForActivity(job, now), createdAt, runAfter, now),
    human_description: coerceHumanDescription(record.human_description) ?? jobHumanDescription(job, text),
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
    { step: job.status === "waiting_for_agent" ? "delivered" : "queued", tokens: base },
    { step: "context", tokens: base * 3 },
    { step: job.status, tokens: base * multiplier }
  ];
}

function workerDisplayName(jobType: string, text: LocaleMessages) {
  if (jobType === "continue_autonomous_session") return text.workerDisplayAutonomousSession;
  if (jobType.includes("train") || jobType.includes("baseline")) return text.workerDisplayTraining;
  if (jobType.includes("notebook")) return text.workerDisplayNotebook;
  if (jobType.includes("research")) return text.workerDisplayResearch;
  if (jobType.includes("agent")) return text.workerDisplayAgentRunner;
  return text.workerDisplayHarness;
}

function targetTabForJob(jobType: string): string | null {
  if (jobType.includes("autonomous")) return "Home";
  if (jobType.includes("train") || jobType.includes("baseline")) return "Leaderboard";
  if (jobType.includes("notebook")) return "Notebooks";
  if (jobType.includes("research") || jobType.includes("agent")) return "Home";
  if (jobType.includes("experiment")) return "Experiments";
  return null;
}

function jobHeadline(job: Job) {
  if (typeof job.output.assistant_message === "string") return job.output.assistant_message;
  return `${job.job_type.replace(/_/g, " ")} is ${job.status}`;
}

function FocusedEvidenceReader({
  id,
  eyebrow,
  title,
  body,
  status,
  statusTone = "muted",
  metrics,
  nextLabel,
  nextDetail,
  nextButtonLabel,
  nextDisabled = false,
  onNext,
  previewTitle = "Evidence preview",
  preview,
  previewError,
  previewLoading,
  previewEmpty,
  previewSourceType = "artifact",
  previewSourceId,
  boundary
}: {
  id: string;
  eyebrow: string;
  title: string;
  body: string;
  status: string;
  statusTone?: EvidenceReaderMetric["tone"];
  metrics: EvidenceReaderMetric[];
  nextLabel: string;
  nextDetail: string;
  nextButtonLabel: string;
  nextDisabled?: boolean;
  onNext?: () => void;
  previewTitle?: string;
  preview: ArtifactPreview | null;
  previewError?: string | null;
  previewLoading?: boolean;
  previewEmpty: string;
  previewSourceType?: "artifact" | "report";
  previewSourceId?: string;
  boundary: string;
}) {
  return (
    <section id={id} className="evidence-reader" aria-label={eyebrow}>
      <div className="evidence-reader-head">
        <div className="evidence-reader-copy">
          <div className="eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
          <p>{body}</p>
          <div className="badge-row">
            <span className={evidenceMetricClass(statusTone)}>{status}</span>
            <span className="badge muted">{boundary}</span>
          </div>
        </div>
        <div className="evidence-reader-metrics">
          {metrics.map((metric) => (
            <div className={evidenceMetricCardClass(metric.tone)} key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="evidence-reader-action">
        <div>
          <span>Next</span>
          <strong>{nextLabel}</strong>
          <p>{nextDetail}</p>
        </div>
        <button className="primary-button" disabled={nextDisabled} onClick={onNext} type="button">
          {previewLoading ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
          {nextButtonLabel}
        </button>
      </div>
      <div id={`${id}-preview`} className="evidence-reader-preview">
        <div className="evidence-reader-preview-head">
          <div className="eyebrow">Read this first</div>
          <h3>{previewTitle}</h3>
        </div>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {previewLoading ? (
          <div className="banner muted">
            <Loader2 className="spin" size={16} />
            Loading evidence...
          </div>
        ) : null}
        {preview?.preview_available ? (
          isVisualArtifactPreview(preview) ? (
            <VisualArtifactPreview preview={preview} />
          ) : isHtmlArtifactPreview(preview) ? (
            <HtmlArtifactPreview preview={preview} />
          ) : (
            <TranslatablePreview preview={preview} sourceType={previewSourceType} sourceId={previewSourceId ?? preview.id} />
          )
        ) : (
          <EmptyInline text={preview?.reason ?? previewEmpty} />
        )}
      </div>
    </section>
  );
}

function evidenceMetricClass(tone: EvidenceReaderMetric["tone"] = "muted") {
  if (tone === "ready") return "badge success";
  if (tone === "warning") return "badge warning";
  if (tone === "risk") return "badge risk";
  return "badge muted";
}

function evidenceMetricCardClass(tone: EvidenceReaderMetric["tone"] = "muted") {
  return `evidence-reader-metric ${tone}`;
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

function isVisualArtifactPreview(preview: ArtifactPreview | null): boolean {
  if (!preview?.preview_available) return false;
  return preview.content_type.startsWith("image/") || preview.content_type === "application/pdf";
}

function VisualArtifactPreview({ preview }: { preview: ArtifactPreview }) {
  const { text } = React.useContext(LocaleContext);
  const url = preview.preview?.startsWith("/api/") ? `${apiBase}${preview.preview}` : preview.preview ?? `${apiBase}/api/artifacts/${preview.id}/download`;
  const isPdf = preview.content_type === "application/pdf" || preview.filename.toLowerCase().endsWith(".pdf");
  return (
    <div className="preview-block">
      <div className="preview-toolbar">
        <div className="preview-meta">
          <span className="badge">{isPdf ? text.artifactPreviewPdfBadge : text.artifactPreviewImageBadge}</span>
          <span className="badge muted">{preview.filename}</span>
        </div>
        <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
          {text.artifactPreviewOpenOriginal}
        </a>
      </div>
      <div className="visual-preview-shell">
        {isPdf ? (
          <iframe className="visual-preview-frame" src={url} title={`${preview.name} preview`} />
        ) : (
          <img className="visual-preview-image" src={url} alt={`${preview.name} preview`} />
        )}
      </div>
    </div>
  );
}

function HtmlArtifactPreview({ preview }: { preview: ArtifactPreview }) {
  const { text } = React.useContext(LocaleContext);
  const isSvg = preview.content_type === "image/svg+xml" || preview.filename.toLowerCase().endsWith(".svg");
  const previewType = isSvg ? text.artifactPreviewSvgBadge : text.artifactPreviewHtmlBadge;
  const url = `${apiBase}/api/artifacts/${preview.id}/download`;
  const inlineUrl = `${apiBase}/api/artifacts/${preview.id}/inline-preview`;
  const inlineSource = typeof preview.preview === "string" && !preview.truncated ? htmlPreviewSrcDoc(preview) : null;
  const renderWithSrcDoc = Boolean(inlineSource);
  const probablyEmpty = htmlPreviewLooksEmpty(preview);
  const [frameFailed, setFrameFailed] = React.useState(false);
  const [frameLoaded, setFrameLoaded] = React.useState(false);
  const [frameSlow, setFrameSlow] = React.useState(false);
  const canRenderInline = Boolean(inlineSource) || (!isSvg && !probablyEmpty);

  React.useEffect(() => {
    setFrameFailed(false);
    setFrameLoaded(false);
    setFrameSlow(false);
    if (!canRenderInline) return undefined;
    const slowTimer = window.setTimeout(() => setFrameSlow(true), 2500);
    return () => window.clearTimeout(slowTimer);
  }, [preview.id, canRenderInline]);

  return (
    <div className="preview-block">
      <div className="preview-toolbar">
        <div className="preview-meta">
          <span className="badge">{previewType}</span>
          <span className="badge muted">{preview.filename}</span>
          {preview.truncated ? <span className="badge risk">{text.artifactPreviewTruncatedBadge}</span> : null}
        </div>
        <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
          {text.artifactPreviewOpenOriginal}
        </a>
      </div>
      {preview.truncated ? (
        <div className="banner warning">{text.artifactPreviewTruncatedWarning}</div>
      ) : null}
      {frameFailed ? (
        <div className="banner warning">{text.artifactPreviewFrameFailedWarning}</div>
      ) : null}
      {probablyEmpty ? (
        <div className="banner warning">{text.artifactPreviewEmptyWarning}</div>
      ) : null}
      {!canRenderInline ? (
        <div className="html-preview-fallback">
          <FileText size={22} />
          <div>
            <strong>{text.artifactPreviewAvailableTitle}</strong>
            <p>{text.artifactPreviewAvailableBody}</p>
          </div>
          <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
            {text.artifactPreviewOpenOriginal}
          </a>
        </div>
      ) : (
        <div className="html-preview-shell" aria-busy={!frameLoaded}>
          {!frameLoaded ? (
            <div className="html-preview-loading" role="status">
              <Loader2 className="spin" size={22} />
              <div>
                <strong>{frameSlow ? text.artifactPreviewSlowTitle : text.artifactPreviewLoadingTitle}</strong>
                <p>{frameSlow ? text.artifactPreviewSlowBody : text.artifactPreviewLoadingBody}</p>
              </div>
            </div>
          ) : null}
          <iframe
            key={preview.id}
            className="html-preview-frame"
            src={renderWithSrcDoc ? undefined : inlineUrl}
            srcDoc={renderWithSrcDoc ? inlineSource ?? undefined : undefined}
            sandbox="allow-scripts"
            title={`${preview.name} preview`}
            onError={() => setFrameFailed(true)}
            onLoad={() => {
              setFrameLoaded(true);
              setFrameSlow(false);
            }}
          />
        </div>
      )}
      {inlineSource ? (
        <details className="html-preview-source-fallback">
          <summary>{text.artifactPreviewInspectSource}</summary>
          <pre>{inlineSource}</pre>
        </details>
      ) : null}
    </div>
  );
}

function htmlPreviewSrcDoc(preview: ArtifactPreview) {
  const source = typeof preview.preview === "string" ? preview.preview : "";
  if (preview.content_type === "image/svg+xml" || preview.filename.toLowerCase().endsWith(".svg")) return source;
  const resetStyle =
    '<style id="tablex-preview-reset">html,body{background:#fff!important;color:#1f2933;color-scheme:light;min-height:100%;}body{box-sizing:border-box;}*,*:before,*:after{box-sizing:inherit;}</style>';
  if (source.includes("tablex-preview-reset")) return source;
  if (/<head[^>]*>/i.test(source)) return source.replace(/<head([^>]*)>/i, `<head$1>${resetStyle}`);
  return `${resetStyle}${source}`;
}

function htmlPreviewLooksEmpty(preview: ArtifactPreview) {
  if (preview.truncated || typeof preview.preview !== "string") return false;
  const source = preview.preview.trim();
  if (!source) return true;
  const structuralTags = /<(svg|canvas|img|table|iframe|script|div|section|article|main|pre|p|h[1-6])\b/i;
  const visibleText = source
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return visibleText.length < 2 && !structuralTags.test(source);
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
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
  onStatusMessage: (message: string) => void;
}) {
  const [queuedFiles, setQueuedFiles] = React.useState<File[]>([]);
  const [primaryFileName, setPrimaryFileName] = React.useState("");
  const [isDraggingData, setIsDraggingData] = React.useState(false);
  const [uploadProgress, setUploadProgress] = React.useState<UploadBundleProgress | null>(null);
  const [target, setTarget] = React.useState(project.target_column ?? "");
  const [targetSavedNotice, setTargetSavedNotice] = React.useState<string | null>(null);
  const [fileColumnHints, setFileColumnHints] = React.useState<Record<string, string[]>>({});
  const [latestSemanticCatalog, setLatestSemanticCatalog] = React.useState<SemanticCatalog | null>(null);
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
  const queuedTableFiles = queuedFiles.filter(isTableUploadFile);
  const queuedErHintFiles = queuedFiles.filter(isRelationalHintUploadFile);
  const unsupportedQueuedFiles = queuedFiles.filter((item) => !isTableUploadFile(item) && !isRelationalHintUploadFile(item));
  const selectedPrimaryFileName = primaryFileName || queuedTableFiles[0]?.name || "";
  const canUploadDataBundle = queuedFiles.length > 0 && unsupportedQueuedFiles.length === 0;
  const uploadProgressByKey = new Map((uploadProgress?.files ?? []).map((item) => [item.key, item]));
  const currentUploadComplete =
    uploadProgress !== null &&
    !uploadProgress.active &&
    uploadProgress.overall >= 100 &&
    queuedFiles.length > 0 &&
    queuedFiles.every((item) => uploadProgressByKey.get(uploadFileKey(item))?.progress === 100);
  const canSubmitDataBundle = canUploadDataBundle && !currentUploadComplete;
  const latestDataset = datasets[0] ?? null;
  const latestDatasetId = latestDataset?.id ?? null;
  const semanticColumns = React.useMemo(() => columnNamesFromSemanticCatalog(latestSemanticCatalog), [latestSemanticCatalog]);
  const queuedPrimaryColumns = React.useMemo(
    () => (selectedPrimaryFileName ? fileColumnHints[selectedPrimaryFileName] ?? [] : []),
    [fileColumnHints, selectedPrimaryFileName]
  );
  const targetSuggestions = React.useMemo(
    () => uniqueStrings([...queuedPrimaryColumns, ...semanticColumns]).slice(0, 48),
    [queuedPrimaryColumns, semanticColumns]
  );
  const relatedDataNotebooks = React.useMemo(
    () =>
      (notebookIndex?.items ?? [])
        .filter(
          (item) =>
            item.notebook_kind === "data_understanding" &&
            (!latestDatasetId || item.dataset_snapshot_id === latestDatasetId)
        )
        .slice(0, 5),
    [latestDatasetId, notebookIndex]
  );
  const targetDraft = target.trim();
  const targetChanged = targetDraft !== (project.target_column ?? "");
  const canSetTarget = targetChanged && !busy;

  React.useEffect(() => {
    setTarget(project.target_column ?? "");
  }, [project.target_column]);

  React.useEffect(() => {
    if (!latestDatasetId) {
      setLatestSemanticCatalog(null);
      return;
    }
    let active = true;
    api<SemanticCatalog>(`/api/datasets/${latestDatasetId}/schema`)
      .then((catalog) => {
        if (active) setLatestSemanticCatalog(catalog);
      })
      .catch(() => {
        if (active) setLatestSemanticCatalog(null);
      });
    return () => {
      active = false;
    };
  }, [latestDatasetId]);

  React.useEffect(() => {
    setPrimaryFileName((current) => {
      const tableNames = queuedFiles.filter(isTableUploadFile).map((item) => item.name);
      if (!tableNames.length) return "";
      return current && tableNames.includes(current) ? current : tableNames[0];
    });
  }, [queuedFiles]);

  function addQueuedUploadFiles(files: FileList | File[]) {
    const incoming = Array.from(files);
    if (!incoming.length) return;
    setUploadProgress(null);
    void readQueuedFileColumnHints(incoming, setFileColumnHints);
    setQueuedFiles((current) => {
      const seen = new Set(current.map(uploadFileKey));
      const next = [...current];
      for (const item of incoming) {
        const key = uploadFileKey(item);
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(item);
      }
      return next;
    });
  }

  function removeQueuedUploadFile(fileToRemove: File) {
    const key = uploadFileKey(fileToRemove);
    setUploadProgress(null);
    setFileColumnHints((current) => {
      const next = { ...current };
      delete next[fileToRemove.name];
      return next;
    });
    setQueuedFiles((current) => current.filter((item) => uploadFileKey(item) !== key));
  }

  async function setProjectTarget(nextTarget: string | null) {
    const normalized = nextTarget?.trim() || null;
    await runAction(async () => {
      const updated = await api<Project>(`/api/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_column: normalized })
      });
      setTarget(updated.target_column ?? "");
      setTargetSavedNotice(text.targetSaved);
      onStatusMessage(
        normalized
          ? `${text.targetSaved}: ${normalized}`
          : text.clearTarget
      );
      window.setTimeout(() => setTargetSavedNotice(null), 2400);
      return updated;
    });
  }

  async function uploadDataBundle() {
    if (!canUploadDataBundle) return;
    const uploadFiles = [...queuedFiles];
    const uploadTotalBytes = uploadFiles.reduce((total, item) => total + item.size, 0);
    setUploadProgress(buildUploadProgress(uploadFiles, 0, uploadTotalBytes, true));
    const body = new FormData();
    uploadFiles.forEach((queuedFile) => body.append("files", queuedFile));
    if (target.trim()) body.append("target_column", target.trim());
    if (selectedPrimaryFileName) body.append("primary_filename", selectedPrimaryFileName);
    if (erHintNote.trim()) body.append("note", erHintNote.trim());
    body.append("locale", locale);
    let uploaded = false;
    await runAction(async () => {
      const job = await uploadFormData<Job>(`/api/projects/${project.id}/datasets/upload-bundle`, body, (event) => {
        const requestTotal = event.lengthComputable && event.total > 0 ? event.total : uploadTotalBytes;
        const estimatedFileBytes =
          requestTotal > 0 ? Math.min(uploadTotalBytes, (event.loaded / requestTotal) * uploadTotalBytes) : 0;
        setUploadProgress(buildUploadProgress(uploadFiles, estimatedFileBytes, uploadTotalBytes, true));
      });
      const hintArtifactIds = Array.isArray(job.output.relational_hint_artifact_ids)
        ? job.output.relational_hint_artifact_ids
        : [];
      const relationalArtifactId =
        textField(job.output.relational_catalog_artifact_id) ?? textField(hintArtifactIds[0]);
      uploaded = true;
      setUploadProgress(buildUploadProgress(uploadFiles, uploadTotalBytes, uploadTotalBytes, false));
      if (relationalArtifactId) {
        await loadRelationalPreview(relationalArtifactId);
      }
      onStatusMessage(text.uploadCompleteChatMessage);
      return job;
    });
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
      const artifactId = textField(job.output.relational_schema_hint_artifact_id);
      if (artifactId) {
        await loadRelationalPreview(artifactId);
      }
      return job;
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
                  list="target-column-suggestions"
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder={text.targetPlaceholder}
                />
                <button className="primary-button" disabled={!canSetTarget} onClick={() => void setProjectTarget(targetDraft)} type="button">
                  <Check size={16} />
                  {targetDraft ? text.setTarget : text.clearTarget}
                </button>
              </div>
              <datalist id="target-column-suggestions">
                {targetSuggestions.map((column) => (
                  <option key={column} value={column} />
                ))}
              </datalist>
              {targetSavedNotice ? <small className="field-success">{targetSavedNotice}</small> : null}
              <div className="target-suggestion-strip">
                <span>{text.targetSuggestions}</span>
                {targetSuggestions.length ? (
                  targetSuggestions.slice(0, 10).map((column) => (
                    <button key={column} className="target-suggestion-chip" onClick={() => setTarget(column)} type="button">
                      {column}
                    </button>
                  ))
                ) : (
                  <small>{text.targetSuggestionsEmpty}</small>
                )}
              </div>
            </div>
            <div className="field-stack">
              <label>{text.primaryTableLabel}</label>
              <select
                value={selectedPrimaryFileName}
                disabled={!queuedTableFiles.length}
                onChange={(event) => setPrimaryFileName(event.target.value)}
              >
                {queuedTableFiles.length ? (
                  queuedTableFiles.map((queuedFile) => (
                    <option key={uploadFileKey(queuedFile)} value={queuedFile.name}>
                      {queuedFile.name}
                    </option>
                  ))
                ) : (
                  <option value="">Add a CSV or Parquet file</option>
                )}
              </select>
              <small>{text.primaryTableHelp}</small>
            </div>
            <div className="button-row">
              <button className="primary-button" disabled={!canSubmitDataBundle || busy} onClick={() => void uploadDataBundle()}>
                {busy ? <Loader2 className="spin" size={16} /> : currentUploadComplete ? <Check size={16} /> : <Upload size={16} />}
                {currentUploadComplete ? "Uploaded" : "Ingest Bundle"}
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
                      <small>{fileColumnHints[queuedFile.name]?.length ? `${fileColumnHints[queuedFile.name].length} columns` : formatBytes(queuedFile.size)}</small>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            {uploadProgress ? (
              <div className={`queued-file-overall ${uploadProgress.active ? "active" : "complete"}`}>
                <div>
                  <span>{uploadProgress.active ? "Uploading bundle" : "Bundle uploaded"}</span>
                  <strong>{Math.round(uploadProgress.overall)}%</strong>
                  <small>
                    {formatBytes(uploadProgress.loadedBytes)} / {formatBytes(uploadProgress.totalBytes)}
                  </small>
                </div>
                <div className="progress-track" aria-label="Overall upload progress">
                  <div style={{ width: `${uploadProgress.overall}%` }} />
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
              const previewArtifactId = notebookPreviewArtifactId(item);
              return (
                <button
                  className="related-notebook-item"
                  disabled={!previewArtifactId}
                  key={item.notebook_artifact_id}
                  onClick={() => {
                    if (previewArtifactId) onOpenNotebookArtifact(previewArtifactId);
                  }}
                  type="button"
                >
                  <BookOpen size={17} />
                  <div>
                    <strong>{item.title}</strong>
                    <small>
                      {item.status.replace(/_/g, " ")} · {formatDate(item.created_at)}
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
                onOpen={(artifactId) => void loadEvidencePreview(artifactId)}
                previewLoadingId={evidencePreviewLoadingId}
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

function buildUploadProgress(files: File[], loadedBytes: number, totalBytes: number, active: boolean): UploadBundleProgress {
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
  return uniqueStrings(columns.filter(Boolean));
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
    ? "approved spec"
    : latestScenarioComparison
      ? "comparison ready"
      : candidates.length
        ? "candidates drafted"
        : "needs design";
  const evaluationStatusTone: EvidenceReaderMetric["tone"] = latestApprovedSpec ? "ready" : candidates.length ? "warning" : "risk";
  const evaluationReaderTitle = latestApprovedSpec
    ? "Evaluation is approved; keep every run behind this contract"
    : latestScenarioComparison
      ? "Read the scenario comparison before promoting a primary spec"
      : candidates.length
        ? "Compare evaluation scenarios before adopting a split"
        : "Draft evaluation candidates before modeling claims";
  const evaluationReaderBody =
    "Tablex should keep metrics, split logic, leakage exclusions, and adoption risk visible before any leaderboard or runner result is trusted. Codex can propose approaches, but the harness owns EvaluationSpec and SplitManifest.";
  const evaluationNextLabel = !candidates.length
    ? "Design candidates"
    : !latestScenarioComparison
      ? "Compare scenarios"
      : !latestSpec
        ? "Promote primary candidate"
        : latestSpec.status !== "approved"
          ? "Approve EvaluationSpec"
          : "Generate SplitManifest";
  const evaluationNextDetail = !candidates.length
    ? "Create primary, alternative, and reference candidates so the tradeoff is explicit."
    : !latestScenarioComparison
      ? "Compare random/stratified/time/group feasibility against assumptions and quality risk."
      : !latestSpec
        ? "Promote only after reading the comparison; promotion is explicit and recorded."
        : latestSpec.status !== "approved"
          ? "Approval should remain a deliberate harness action, not an implicit chat side effect."
          : "Split generation is the handoff contract for downstream experiments and Codex runner work.";
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
        eyebrow="Evaluation Evidence Reader"
        title={evaluationReaderTitle}
        body={evaluationReaderBody}
        status={evaluationStatus}
        statusTone={evaluationStatusTone}
        metrics={[
          { label: "Candidates", value: candidates.length, tone: candidates.length ? "ready" : "risk" },
          { label: "Specs", value: specs.length, tone: specs.length ? "ready" : "muted" },
          { label: "Comparison", value: latestScenarioComparison ? "ready" : "missing", tone: latestScenarioComparison ? "ready" : "warning" },
          { label: "Quality", value: latestQualityGate ? "ready" : "missing", tone: latestQualityGate ? "ready" : "warning" }
        ]}
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
              const artifactId = job.output.artifact_id;
              if (typeof artifactId === "string") {
                await loadScenarioPreview(artifactId);
              }
              return job;
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
        previewTitle={latestScenarioComparison ? "Latest scenario comparison" : "Evaluation decision evidence"}
        preview={scenarioPreview}
        previewError={scenarioPreviewError}
        previewLoading={Boolean(scenarioPreviewLoadingId)}
        previewEmpty="Design and compare evaluation candidates to get a readable scenario comparison here."
        boundary="Approval and SplitManifest stay explicit"
      />
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
      <Panel id="evaluation-candidates" title="Evaluation Candidates" icon={<BarChart3 size={18} />}>
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
    <section id="strategy-brief-focus" className="strategy-brief-panel">
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
    const workspaceArtifactId = job.output.agent_workspace_manifest_artifact_id ?? job.output.artifact_id;
    if (typeof workspaceArtifactId === "string") {
      await loadWorkspacePreview(workspaceArtifactId);
    }
    return job;
  }

  async function reviewContractReadiness(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/readiness-review`, {
      method: "POST"
    });
    const reportArtifactId = job.output.agent_task_readiness_report_artifact_id ?? job.output.artifact_id;
    if (typeof reportArtifactId === "string") {
      await loadTaskContractPreview(reportArtifactId);
    }
    setRunnerReadinessFeedback(readinessFeedbackFromJob(job, artifact.id));
    return job;
  }

  async function runContractLocalStub(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-local-stub`, {
      method: "POST"
    });
    const ingested = job.output.ingested_artifact_ids;
    const reportArtifactId = Array.isArray(ingested) ? textField(ingested[0]) : null;
    if (reportArtifactId) {
      await loadTaskContractPreview(reportArtifactId);
    }
    return job;
  }

  async function runContractCodex(artifact: Artifact) {
    const job = await api<Job>(`/api/agent-task-contracts/${artifact.id}/run-codex`, {
      method: "POST"
    });
    const ingested = job.output.ingested_artifact_ids;
    const reportArtifactId = Array.isArray(ingested) ? textField(ingested[0]) : null;
    if (reportArtifactId) {
      await loadTaskContractPreview(reportArtifactId);
    }
    return job;
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
                  onClick={() => void previewContract(artifact)}
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
  notebookIndex,
  busy,
  text,
  runAction
}: {
  project: Project;
  jobs: Job[];
  runs: Run[];
  agentTaskResults: AgentTaskResult[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
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
      "notebook_html",
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
      focusNavigationAnchor("notebook-preview-top");
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
                onOpen={(artifactId) => void loadPreview(artifactId)}
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
                      const artifactId = textField(job.output.model_diagnostics_report_artifact_id) ?? textField(job.output.model_diagnostics_artifact_pack_id);
                      if (artifactId) {
                        await loadPreview(artifactId);
                      }
                      return job;
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
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale })
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

  async function prepareResultNotebookEvidence() {
    const job = await api<Job>(`/api/projects/${project.id}/results/notebook-evidence`, { method: "POST" });
    const htmlArtifactId =
      textField(job.output.notebook_evidence_html_artifact_id) ??
      textField(job.output.notebook_execution_html_artifact_id) ??
      textField(job.output.notebook_html_artifact_id) ??
      textField(job.output.analysis_notebook_artifact_id);
    if (htmlArtifactId) {
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
  const hasEvidenceCapture = Boolean(reviewNotebook?.coverage.has_execution_capture || reviewEvidenceHtml);
  const story = analysisStory?.story ?? null;
  const storyPreviewArtifactId = textField(story?.selected_source?.preview_artifact_id) ?? readablePreviewArtifactId;
  const storySourceType = textField(story?.source_type);
  const hasReadableStoryEvidence = Boolean(storyPreviewArtifactId || hasEvidenceCapture);
  const hasEdaReviewEvidence = Boolean(latestEdaReviewHtml || storySourceType === "eda_review");
  const notebookFocusHeadline =
    textField(story?.headline) ??
    (reviewNotebook ? reviewNotebook.title : "Create the first readable analysis story");
  const notebookFocusReason =
    textField(story?.why_this_story) ??
    (divertedFromEmptyDiagnostics
      ? "The latest diagnostics notebook has no useful model evidence, so Tablex is routing attention back to Data Understanding."
      : reviewNotebook
        ? reviewNotebook.recommendation_reason
        : "Run EDA Review first, then let Codex extend analysis only when the next human question is clear.");
  const notebookFocusNext = storyPreviewArtifactId
    ? "Open the current story"
    : latestDataset
      ? "Run EDA Review"
      : "Upload data first";
  const storyPrimaryActionType = textField(story?.primary_action?.action_type);
  const storyPrimaryEndpoint = textField(story?.primary_action?.endpoint);
  const autoPreviewedArtifactRef = React.useRef<string | null>(null);
  const handledPreviewRequestRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (!storyPreviewArtifactId || autoPreviewedArtifactRef.current === storyPreviewArtifactId) return;
    autoPreviewedArtifactRef.current = storyPreviewArtifactId;
    void loadPreview(storyPreviewArtifactId);
  }, [storyPreviewArtifactId]);

  React.useEffect(() => {
    if (!previewRequest || previewRequest.targetTab !== "Notebooks") return;
    if (handledPreviewRequestRef.current === previewRequest.nonce) return;
    handledPreviewRequestRef.current = previewRequest.nonce;
    void loadPreview(previewRequest.artifactId);
  }, [previewRequest]);

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
      <section id="notebook-focus" className="notebook-focus-panel" aria-label="Notebook reading focus">
        <div className="notebook-focus-copy">
          <div className="eyebrow">Notebook focus</div>
          <h2>{notebookFocusHeadline}</h2>
          <p>{notebookFocusReason}</p>
          <div className="badge-row">
            <span className={story ? "badge" : "badge muted"}>{story ? "story ready" : "story pending"}</span>
            <span className={hasReadableStoryEvidence ? "badge" : "badge risk"}>
              {hasReadableStoryEvidence ? "readable evidence" : "capture needed"}
            </span>
            <span className={hasEdaReviewEvidence ? "badge" : "badge warning"}>
              {hasEdaReviewEvidence ? "EDA review ready" : "EDA review not run"}
            </span>
            {divertedFromEmptyDiagnostics ? <span className="badge warning">empty diagnostics skipped</span> : null}
          </div>
        </div>
        <div className="notebook-focus-aside">
          <Metric label="Notebooks" value={notebookIndex?.counts.total ?? 0} />
          <Metric label="Captured" value={notebookIndex?.counts.with_execution_capture ?? 0} />
          <Metric label="Figures" value={String(story?.figure_refs.length ?? latestEdaReviewFigures.length)} />
          <Metric label="Runs" value={runs.length} />
          <div className="notebook-focus-action">
            <span>Next</span>
            <strong>{notebookFocusNext}</strong>
            <button
              className="secondary-button"
              disabled={busy || (!storyPreviewArtifactId && latestDataset === null)}
              onClick={() => {
                if (storyPreviewArtifactId) {
                  void loadPreview(storyPreviewArtifactId);
                } else if (latestDataset) {
                  void runAction(() => runEdaReview(latestDataset));
                }
              }}
            >
              {previewLoadingId === storyPreviewArtifactId || busy ? (
                <Loader2 className="spin" size={16} />
              ) : storyPreviewArtifactId ? (
                <Eye size={16} />
              ) : (
                <BarChart3 size={16} />
              )}
              {storyPreviewArtifactId ? "Open Story" : "Run EDA Review"}
            </button>
            <button
              className="secondary-button"
              disabled={busy || latestRun === null}
              onClick={() => void runAction(prepareResultNotebookEvidence)}
            >
              {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
              Result Evidence
            </button>
          </div>
        </div>
      </section>
      <Panel id="analysis-story" title="Analysis Story" icon={<BarChart3 size={18} />}>
        {story ? (
          <div className="analysis-story-surface">
            <section className="analysis-story-hero">
              <div className="analysis-story-copy">
                <div className="eyebrow">Read this now</div>
                <h3>{story.headline}</h3>
                <p>{story.why_this_story || story.deck}</p>
                {divertedFromEmptyDiagnostics ? (
                  <div className="banner warning compact">
                    A model diagnostics notebook exists, but it has no useful metric or prediction evidence yet. Tablex is routing you back to Data Understanding first.
                  </div>
                ) : null}
                <div className="badge-row">
                  <span className="badge">{story.source_type.replace(/_/g, " ")}</span>
                  <span className="badge muted">{story.selected_source.title}</span>
                  {story.selected_source.status ? (
                    <span className={decisionReportStatusClass(story.selected_source.status)}>
                      {story.selected_source.status.replace(/_/g, " ")}
                    </span>
                  ) : null}
                  <span className={hasEvidenceCapture || story.source_type === "eda_review" ? "badge" : "badge risk"}>
                    {hasEvidenceCapture || story.source_type === "eda_review" ? "readable evidence" : "needs capture"}
                  </span>
                </div>
              </div>
              <div className="analysis-story-actions">
                <button
                  className="primary-button"
                  disabled={!storyPreviewArtifactId || previewLoadingId === storyPreviewArtifactId}
                  onClick={() => {
                    if (storyPreviewArtifactId) void loadPreview(storyPreviewArtifactId);
                  }}
                >
                  {storyPreviewArtifactId && previewLoadingId === storyPreviewArtifactId ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <Eye size={16} />
                  )}
                  Open Story
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || latestDataset === null}
                  onClick={() => {
                    if (latestDataset) void runAction(() => runEdaReview(latestDataset));
                  }}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Run EDA Review
                </button>
                {reviewNotebook && storyPrimaryActionType === "api" && storyPrimaryEndpoint?.includes("execution-capture") ? (
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void runAction(() => captureNotebookExecution(reviewNotebook))}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                    Capture Evidence
                  </button>
                ) : null}
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => void runAction(prepareResultNotebookEvidence)}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Result Evidence
                </button>
              </div>
            </section>

            <section id="notebook-preview-top" className="analysis-story-preview">
              <div className="analysis-story-preview-head">
                <div>
                  <div className="eyebrow">Current story preview</div>
                  <h3>{story.selected_source.title}</h3>
                </div>
                {storyPreviewArtifactId ? (
                  <a className="icon-link" href={`${apiBase}/api/artifacts/${storyPreviewArtifactId}/download`} title="Download current story">
                    <Download size={16} />
                  </a>
                ) : null}
              </div>
              {previewError ? <div className="banner danger">{previewError}</div> : null}
              {preview?.preview_available ? (
                isHtmlArtifactPreview(preview) ? (
                  <HtmlArtifactPreview preview={preview} />
                ) : (
                  <TranslatablePreview preview={preview} />
                )
              ) : (
                <EmptyInline text="The selected story appears here immediately after you open it. If it is not available, run EDA Review or capture notebook evidence." />
              )}
            </section>

            <div className="analysis-story-grid">
              <section className="analysis-story-section">
                <div className="mini-card-title">Read order</div>
                {story.read_order.length ? (
                  <div className="analysis-read-list">
                    {story.read_order.map((item, index) => (
                      <div className="analysis-read-row" key={`${textField(item.title) ?? "read"}-${index}`}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{textField(item.title) ?? "Review item"}</strong>
                          <p>{textField(item.why) ?? ""}</p>
                          {textField(item.artifact_hint) ? <small>{textField(item.artifact_hint)}</small> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyInline text="No read order is available yet. Ask Codex to create one from the current artifacts." />
                )}
              </section>

              <section className="analysis-story-section">
                <div className="mini-card-title">What matters</div>
                {story.visual_story_cards.length ? (
                  <div className="analysis-story-card-grid">
                    {story.visual_story_cards.map((card, index) => (
                      <div className="analysis-story-card" key={`${textField(card.title) ?? "card"}-${index}`}>
                        <div className="badge-row">
                          <span className={decisionReportStatusClass(textField(card.status) ?? "review")}>
                            {(textField(card.status) ?? "review").replace(/_/g, " ")}
                          </span>
                        </div>
                        <strong>{textField(card.title) ?? "Story card"}</strong>
                        <p>{textField(card.why_read) ?? ""}</p>
                        {textField(card.signal) ? <small>{textField(card.signal)}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyInline text="Story cards will appear after EDA Review or notebook generation." />
                )}
              </section>
            </div>

            <div className="analysis-story-grid compact">
              <section className="analysis-story-section">
                <div className="mini-card-title">Caveats</div>
                {story.caveats.length ? (
                  <ul className="analysis-plain-list">
                    {story.caveats.slice(0, 5).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <EmptyInline text="No caveat has been raised for this story yet." />
                )}
              </section>
              <section className="analysis-story-section">
                <div className="mini-card-title">Ask Codex next</div>
                <div className="analysis-prompt-list">
                  {(story.codex_prompts.length
                    ? story.codex_prompts
                    : [
                        "What should I read first and why?",
                        "What is the next narrow analysis action?",
                        "Which evidence is still too weak to trust?"
                      ]
                  ).slice(0, 4).map((prompt) => (
                    <button
                      className="secondary-button"
                      disabled={busy || guideBusy}
                      key={prompt}
                      title="Ask the analysis guide"
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
                    placeholder="Ask Tablee about this analysis story..."
                  />
                  <button className="icon-button" disabled={busy || guideBusy || !guideDraft.trim()} title="Ask analysis guide">
                    {guideBusy ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
                  </button>
                </form>
                {guideResponse ? <div className="notebook-guide-response">{guideResponse}</div> : null}
              </section>
            </div>

            <details className="artifact-shelf analysis-supporting-shelf">
              <summary>Supporting notebooks and artifacts</summary>
              <div className="analysis-supporting-grid">
                <div className="metric-grid compact">
                  <Metric label="Notebooks" value={notebookIndex?.counts.total ?? 0} />
                  <Metric label="Captured" value={notebookIndex?.counts.with_execution_capture ?? 0} />
                  <Metric label="Figures" value={String(story.figure_refs.length || reviewEvidenceFigures.length)} />
                  <Metric label="Data Review" value={latestEdaReviewHtml ? "ready" : "not run"} />
                </div>

                {reviewNotebook ? (
                  <div className="card-grid notebook-evidence-grid">
                    <div className="mini-card notebook-evidence-card primary">
                      <div className="mini-card-title">Data Review</div>
                      <p>Harness-controlled EDA with findings, figures, read order, and Codex prompts.</p>
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
                      </div>
                    </div>
                    <div className="mini-card notebook-evidence-card primary">
                      <div className="mini-card-title">Notebook evidence</div>
                      <p>Static evidence capture keeps the notebook readable without leaving Tablex.</p>
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
                          Open
                        </button>
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void runAction(() => captureNotebookExecution(reviewNotebook))}
                        >
                          {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                          Capture
                        </button>
                        <button
                          className="secondary-button"
                          disabled={busy || latestRun === null}
                          onClick={() => void runAction(prepareResultNotebookEvidence)}
                        >
                          {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                          Result
                        </button>
                      </div>
                    </div>
                    <div className="mini-card notebook-evidence-card">
                      <div className="mini-card-title">Runner record</div>
                      <p>Plan, manifest, source, and safety policy for controlled Codex handoff.</p>
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
                ) : null}

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
                  <EmptyInline text="Notebook history will appear after Data Understanding or run-level diagnostics notebooks are generated." />
                )}

                {reviewArtifacts.length ? (
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
                ) : null}
              </div>
            </details>
          </div>
        ) : (
          <div className="notebook-start-card">
            <img src="/mascot/tablee-avatar.svg" alt="" aria-hidden="true" className="notebook-start-mascot" />
            <div className="notebook-start-copy">
              <div className="eyebrow">Start here</div>
              <h3>{analysisStory?.empty_state?.headline ?? "Create the first readable analysis story"}</h3>
              <p>
                {analysisStory?.empty_state?.reason ??
                  "Run EDA Review first. Then let Codex extend a marimo notebook only after the next human question is clear."}
              </p>
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
                <button
                  className="secondary-button"
                  disabled={busy || latestRun === null}
                  onClick={() => void runAction(prepareResultNotebookEvidence)}
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  Result Evidence
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
  runAction
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
  const reportStatusTone: EvidenceReaderMetric["tone"] =
    readinessStatus === "ready" || readinessStatus === "decision_ready"
      ? "ready"
      : readinessStatus === "blocked" || readinessStatus === "missing"
        ? "risk"
        : "warning";
  const reportReaderBody =
    "This is the project-level reading surface: current evidence, coverage gaps, risks, and next actions in one place. Reports summarize evidence; they do not invent missing experiment or approval evidence.";
  const reportNextLabel = currentDecisionReportId ? "Read the current decision report" : "Generate the first decision report";
  const reportNextDetail = currentDecisionReportId
    ? "Use this report to choose the next controlled human or runner action before scanning raw artifacts."
    : "Synthesize Data Review, assumptions, evaluation, notebooks, experiments, runner outputs, citations, and lineage into a single in-product report.";
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
      <FocusedEvidenceReader
        id="decision-report"
        eyebrow="Decision Report Reader"
        title={readinessHeadline}
        body={reportReaderBody}
        status={readinessStatus.replace(/_/g, " ")}
        statusTone={reportStatusTone}
        metrics={[
          { label: "Ready", value: String(coverage.ready_count ?? 0), tone: "ready" },
          { label: "Needs attention", value: String(coverage.attention_count ?? 0), tone: Number(coverage.attention_count ?? 0) ? "warning" : "muted" },
          { label: "Missing", value: String(coverage.missing_count ?? 0), tone: Number(coverage.missing_count ?? 0) ? "risk" : "muted" },
          { label: "Sources", value: String(currentDecisionBundle?.source_assets.length ?? 0), tone: currentDecisionBundle?.source_assets.length ? "ready" : "muted" }
        ]}
        nextLabel={reportNextLabel}
        nextDetail={reportNextDetail}
        nextButtonLabel={currentDecisionReportId ? "Open Current" : "Generate Decision Report"}
        nextDisabled={busy || Boolean(currentDecisionReportId && previewLoadingId === currentDecisionReportId)}
        onNext={() => {
          if (currentDecisionReportId) {
            void loadReportPreview(currentDecisionReportId);
          } else {
            void runAction(generateDecisionReport);
          }
        }}
        previewTitle={currentDecisionReportId ? "Current report text" : "No decision report yet"}
        preview={reportPreview}
        previewError={previewError}
        previewLoading={Boolean(previewLoadingId)}
        previewEmpty="Generate a decision report to read the current project state here."
        previewSourceType={reportPreviewSource?.type ?? "report"}
        previewSourceId={reportPreviewSource?.id ?? currentDecisionReportId ?? undefined}
        boundary="Reports are summaries, not approval"
      />
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
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ locale })
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
          Prepare Notebook Context
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
      <Panel id="notebook-center" title="Notebook Center" icon={<BarChart3 size={18} />}>
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
          <EmptyInline text="No authored notebook is available yet. Prepare notebook context, then let the agent write and register the notebook." />
        )}
      </Panel>
      <Panel id="ideas" title="Ideas" icon={<Lightbulb size={18} />}>
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
          <EmptyInline text="Agent ideas, domain observations, and improvement hypotheses will appear here with rationale and expected artifacts." />
        )}
      </Panel>
      <Panel id="insights" title="Insights" icon={<Lightbulb size={18} />}>
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
      <Panel id="reports" title="Reports" icon={<FileText size={18} />}>
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
  return (
    item.artifact_ids.evidence_html ??
    item.artifact_ids.execution_html ??
    item.artifact_ids.html_preview ??
    item.artifact_ids.report_artifact ??
    item.artifact_ids.notebook
  );
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

function notebooksForDataset(index: NotebookIndex | null, datasetSnapshotId: string): NotebookIndexItem[] {
  if (!index) return [];
  return index.items.filter((item) => item.dataset_snapshot_id === datasetSnapshotId);
}

function notebooksForRun(index: NotebookIndex | null, runId: string): NotebookIndexItem[] {
  if (!index) return [];
  return index.items.filter((item) => item.run_id === runId);
}

function notebooksForModelVersion(index: NotebookIndex | null, modelVersionId: string): NotebookIndexItem[] {
  if (!index) return [];
  return index.items.filter((item) => item.model_version_id === modelVersionId);
}

function notebooksForLeaderboardEntry(index: NotebookIndex | null, entry: LeaderboardEntry): NotebookIndexItem[] {
  if (!index) return [];
  const seen = new Set<string>();
  const matched = index.items.filter((item) => {
    const matchesRun = item.run_id === entry.run_id;
    const matchesModel = Boolean(entry.model_version_id && item.model_version_id === entry.model_version_id);
    if (!matchesRun && !matchesModel) return false;
    if (seen.has(item.notebook_artifact_id)) return false;
    seen.add(item.notebook_artifact_id);
    return true;
  });
  return matched;
}

function RelatedNotebookLinks({
  notebooks,
  onOpen,
  previewLoadingId,
  text,
  compact = false
}: {
  notebooks: NotebookIndexItem[];
  onOpen: (artifactId: string) => void;
  previewLoadingId: string | null;
  text: LocaleMessages;
  compact?: boolean;
}) {
  if (!notebooks.length) {
    return <span className="related-notebook-empty">{text.noRelatedNotebooks}</span>;
  }
  const visible = notebooks.slice(0, compact ? 1 : 2);
  const hiddenCount = Math.max(0, notebooks.length - visible.length);
  return (
    <div className={`related-notebook-links ${compact ? "compact" : ""}`}>
      {visible.map((item) => {
        const artifactId = notebookPreviewArtifactId(item);
        return (
          <button
            className="related-notebook-link"
            disabled={previewLoadingId === artifactId}
            key={item.notebook_artifact_id}
            onClick={() => onOpen(artifactId)}
            title={item.title}
            type="button"
          >
            {previewLoadingId === artifactId ? <Loader2 className="spin" size={13} /> : <BarChart3 size={13} />}
            <span>{compact ? text.relatedNotebooks : conciseNotebookTitle(item.title)}</span>
          </button>
        );
      })}
      {hiddenCount ? <span className="related-notebook-count">+{hiddenCount}</span> : null}
    </div>
  );
}

function conciseNotebookTitle(title: string) {
  const normalized = title.replace(/\s+/g, " ").trim();
  return normalized.length <= 34 ? normalized : `${normalized.slice(0, 33).trim()}...`;
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
        "Route relational feature work through a controlled AgentTaskContract."
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

function resultReadoutStatusTone(status: string, fallback: EvidenceReaderMetric["tone"]): EvidenceReaderMetric["tone"] {
  if (status === "ready_for_review") return "ready";
  if (status === "needs_attention" || status === "needs_decision_report" || status === "needs_diagnostics") return "warning";
  if (status === "needs_evaluation" || status === "needs_run") return "risk";
  return fallback;
}

const builtinLeaderboardMetrics = ["roc_auc", "pr_auc", "accuracy", "macro_f1", "f1", "log_loss", "rmse", "mae", "r2"];
const preferredMetricOrder = builtinLeaderboardMetrics;
const ignoredMetricKeys = new Set([
  "primary_metric_value",
  "train_count",
  "valid_count",
  "feature_count",
  "numeric_feature_count",
  "categorical_feature_count",
  "text_feature_count"
]);

function leaderboardMetricOptions(leaderboard: LeaderboardEntry[]) {
  const options = new Set<string>(builtinLeaderboardMetrics);
  leaderboard.forEach((entry) => {
    Object.entries(entry.metrics).forEach(([key, value]) => {
      if (ignoredMetricKeys.has(key)) return;
      if (typeof value === "number" && Number.isFinite(value)) options.add(key);
    });
    if (entry.primary_metric_name) options.add(entry.primary_metric_name);
  });
  return [...options].sort((left, right) => {
    const leftIndex = preferredMetricOrder.indexOf(left);
    const rightIndex = preferredMetricOrder.indexOf(right);
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex);
    }
    return left.localeCompare(right);
  });
}

function metricLabel(metric: string | null | undefined) {
  return metric ? metric.replace(/_/g, "-").toUpperCase() : "metric";
}

function LeaderboardTab({
  project,
  specs,
  artifacts,
  notebookIndex,
  leaderboard,
  resultReadout,
  busy,
  text,
  runAction,
  onAskAgent
}: {
  project: Project;
  specs: EvaluationSpec[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  leaderboard: LeaderboardEntry[];
  resultReadout: ResultReadout | null;
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (objective: string) => Promise<AgentChatResponse | void>;
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
  const approvedSpecCount = specs.filter((spec) => spec.status === "approved").length;
  const topEntry = leaderboard[0] ?? null;
  const leaderboardStatus = leaderboard.length
    ? approvedSpecCount && splitManifests.length
      ? "comparable"
      : "needs context"
    : "no runs yet";
  const leaderboardTone: EvidenceReaderMetric["tone"] = leaderboard.length
    ? approvedSpecCount && splitManifests.length
      ? "ready"
      : "warning"
    : "muted";

  async function analyzeTopRun(entry: LeaderboardEntry) {
    const job = await api<Job>(`/api/runs/${entry.run_id}/diagnostics`, { method: "POST" });
    const artifactIds = Array.isArray(job.output.artifact_ids) ? job.output.artifact_ids : [];
    const preferredArtifactId = typeof artifactIds[1] === "string" ? artifactIds[1] : typeof artifactIds[0] === "string" ? artifactIds[0] : null;
    if (preferredArtifactId) {
      await loadPreview(preferredArtifactId);
    }
    return job;
  }

  async function draftTopRunReport(entry: LeaderboardEntry) {
    const job = await api<Job>(`/api/runs/${entry.run_id}/report`, { method: "POST" });
    const artifactId = textField(job.output.artifact_id);
    if (artifactId) {
      await loadPreview(artifactId);
    }
    return job;
  }

  async function materializeTopRunModelEvidence(entry: LeaderboardEntry) {
    const job = await api<Job>(`/api/runs/${entry.run_id}/model-diagnostics-artifacts`, { method: "POST" });
    const artifactId =
      textField(job.output.model_diagnostics_report_artifact_id) ??
      textField(job.output.model_diagnostics_artifact_pack_id) ??
      textField(job.output.feature_importance_artifact_id);
    if (artifactId) {
      await loadPreview(artifactId);
    }
    return job;
  }

  async function prepareResultNotebookEvidence() {
    const job = await api<Job>(`/api/projects/${project.id}/results/notebook-evidence`, { method: "POST" });
    const htmlArtifactId =
      textField(job.output.notebook_evidence_html_artifact_id) ??
      textField(job.output.notebook_execution_html_artifact_id) ??
      textField(job.output.notebook_html_artifact_id) ??
      textField(job.output.analysis_notebook_artifact_id);
    if (htmlArtifactId) {
      await loadPreview(htmlArtifactId);
    }
    return job;
  }

  const readoutStatus = resultReadout?.status ?? leaderboardStatus;
  const readoutTone = resultReadoutStatusTone(readoutStatus, leaderboardTone);
  const metricOptions = leaderboardMetricOptions(leaderboard);
  const selectedMetric = topEntry?.display_metric_name ?? metricOptions[0] ?? null;
  const unavailableCount = selectedMetric ? leaderboard.filter((entry) => !entry.display_metric_available).length : 0;
  const topMetricName = selectedMetric ?? "metric";
  const diagnosticsReady = booleanField(resultReadout?.diagnostics.available) || diagnosticArtifacts.length > 0;
  const decisionReady = booleanField(resultReadout?.decision_report.available);

  async function setLeaderboardMetric(metric: string) {
    await api(`/api/projects/${project.id}/leaderboard/metric`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metric })
    });
  }

  return (
    <div className="stack">
      <section id="result-readout" className="leaderboard-surface" aria-label="Leaderboard">
        <div className="leaderboard-head">
          <div>
            <div className="eyebrow">Leaderboard</div>
            <h2>{leaderboard.length ? `${leaderboard.length} run${leaderboard.length === 1 ? "" : "s"} ranked by ${metricLabel(topMetricName)}` : "No ranked runs yet"}</h2>
            <div className="badge-row">
              <span className={evidenceMetricClass(readoutTone)}>{readoutStatus.replace(/_/g, " ")}</span>
              <span className={approvedSpecCount ? "badge success" : "badge warning"}>{approvedSpecCount ? "evaluation locked" : "evaluation missing"}</span>
              <span className={splitManifests.length ? "badge success" : "badge warning"}>{splitManifests.length ? "split ready" : "split missing"}</span>
              {unavailableCount ? <span className="badge warning">{unavailableCount} missing score</span> : null}
            </div>
          </div>
          <div className="leaderboard-controls">
            <label>
              <span>Metric</span>
              <select
                disabled={busy || !metricOptions.length}
                value={selectedMetric ?? ""}
                onChange={(event) => void runAction(() => setLeaderboardMetric(event.target.value))}
              >
                {metricOptions.map((metric) => (
                  <option key={metric} value={metric}>
                    {metricLabel(metric)}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => void onAskAgent(`Add or compute a new leaderboard metric for ${project.name}. Keep it as one metric across all runs and update the leaderboard view when available.`)}
              type="button"
            >
              {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
              Add metric
            </button>
            <div className="leaderboard-best-score">
              <span>Best score</span>
              <strong>{formatScore(topEntry?.display_metric_value ?? null)}</strong>
              <small>{metricLabel(topMetricName)} · {topEntry?.run_id ?? "no run"}</small>
            </div>
          </div>
        </div>
        {leaderboard.length ? (
          <div className="leaderboard-table-wrap">
            <Table
              headers={["Rank", "Run", "Score", "Model", "Evaluation", "Evidence", "Actions"]}
              rows={leaderboard.map((entry) => [
                <strong className="leaderboard-rank" key={`${entry.run_id}-rank`}>#{entry.rank}</strong>,
                <div className="cell-stack" key={`${entry.run_id}-run`}>
                  <span>{entry.run_id}</span>
                  <small>{entry.runner_type}</small>
                </div>,
                <div className="leaderboard-score-cell" key={`${entry.run_id}-score`}>
                  <strong>{formatScore(entry.display_metric_value)}</strong>
                  <small>{metricLabel(entry.display_metric_name)}</small>
                </div>,
                <div className="cell-stack" key={`${entry.run_id}-model`}>
                  <span>{formatBaseline(entry.metrics)}</span>
                  <small>{entry.model_version_id ?? "no model version"}</small>
                </div>,
                <div className="cell-stack" key={`${entry.run_id}-eval`}>
                  <span>{entry.evaluation_spec_id ?? "-"}</span>
                  <small>{entry.split_manifest_id ?? "no split"}</small>
                </div>,
                <div className="leaderboard-evidence-badges" key={`${entry.run_id}-evidence`}>
                  <span className={diagnosticsReady ? "badge success" : "badge muted"}>diagnostics</span>
                  <span className={decisionReady ? "badge success" : "badge warning"}>report</span>
                  <RelatedNotebookLinks
                    notebooks={notebooksForLeaderboardEntry(notebookIndex, entry)}
                    onOpen={(artifactId) => void loadPreview(artifactId)}
                    previewLoadingId={previewLoadingId}
                    text={text}
                    compact
                  />
                </div>,
                <div className="row-actions" key={`${entry.run_id}-actions`}>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => analyzeTopRun(entry))}
                    title="Analyze diagnostics"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => materializeTopRunModelEvidence(entry))}
                    title="Materialize model evidence"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(prepareResultNotebookEvidence)}
                    title="Open notebook evidence"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => draftTopRunReport(entry))}
                    title="Draft run report"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
                  </button>
                </div>
              ])}
            />
          </div>
        ) : (
          <EmptyInline text="Run a baseline or agent task after approving evaluation. Ranked runs will appear here." />
        )}
      </section>
      {(preview || previewError || previewLoadingId) ? (
        <Panel title="Selected Run Evidence" icon={<FileText size={18} />}>
          {previewError ? <div className="banner danger">{previewError}</div> : null}
          {previewLoadingId ? (
            <div className="banner muted">
              <Loader2 className="spin" size={16} />
              Loading evidence...
            </div>
          ) : null}
          {preview?.preview_available ? (
            isVisualArtifactPreview(preview) ? (
              <VisualArtifactPreview preview={preview} />
            ) : isHtmlArtifactPreview(preview) ? (
              <HtmlArtifactPreview preview={preview} />
            ) : (
              <TranslatablePreview preview={preview} />
            )
          ) : (
            <EmptyInline text={preview?.reason ?? "Select a run action to inspect its diagnostics, model evidence, notebook evidence, or report."} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}

function formatMetric(metrics: Record<string, unknown>) {
  const name = metrics.primary_metric_name;
  const value = metrics.primary_metric_value;
  if (typeof name !== "string" || typeof value !== "number") return "-";
  return `${name}: ${value.toFixed(6)}`;
}

function formatScore(value: number | null) {
  return value == null || !Number.isFinite(value) ? "-" : value.toFixed(6);
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
  project,
  artifacts,
  modelVersions,
  validationsByModelVersion,
  notebookIndex,
  libraryAssets,
  projectAssetReferences,
  busy,
  text,
  runAction,
  onEquipSkill,
  onCreateSkill
}: {
  project: Project;
  artifacts: Artifact[];
  modelVersions: ModelVersion[];
  validationsByModelVersion: Record<string, ModelValidation[]>;
  notebookIndex: NotebookIndex | null;
  libraryAssets: LibraryAsset[];
  projectAssetReferences: AssetReference[];
  busy: boolean;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onEquipSkill: (asset: LibraryAsset) => Promise<void>;
  onCreateSkill: (draft: SkillDraft) => Promise<void>;
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
                  onOpen={(artifactId) => void loadPreview(artifactId)}
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
  const statusLabel = job.status === "waiting_for_agent" ? text.workerStatusWaitingForAgent : job.status;
  const status = job.error_message ? `${statusLabel}: ${job.error_message}` : statusLabel;
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

function Panel({
  id,
  title,
  icon,
  children,
  className
}: {
  id?: string;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`panel ${className ?? ""}`}>
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

class WorkbenchErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { message: string | null }
> {
  state = { message: null };

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.message) {
      return (
        <div className="fatal-error">
          <img src="/mascot/tablee-empty.svg" alt="" aria-hidden="true" className="empty-state-mascot" />
          <h1>Tablex could not render this view.</h1>
          <p>{this.state.message}</p>
          <button className="primary-button" type="button" onClick={() => window.location.reload()}>
            <RefreshCw size={16} />
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function formatBytes(value: number | null) {
  if (value === null) return "-";
  if (value === 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <WorkbenchErrorBoundary>
      <App />
    </WorkbenchErrorBoundary>
  </React.StrictMode>
);
