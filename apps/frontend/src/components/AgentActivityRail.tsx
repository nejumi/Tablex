import React from "react";
import { Activity, Eye, Loader2, Minus, Plus, Send, X } from "lucide-react";
import type { LocaleMessages } from "../copy";
import {
  tabItems,
  type AgentActivityResponse,
  type AgentWorkerEvent,
  type Job,
  type RequiredHumanDescription,
  type Tab,
  type TokenSeriesPoint
} from "../types";

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
  if (value === "Overview" || value === "Approach") return "Home";
  if (value === "Reports") return "Insight";
  if (value === "Library" || value === "Lineage") return "Assets";
  const match = tabItems.find((item) => item.id === value);
  return match ? match.id : fallback;
}

function tabLabel(tab: Tab, text: LocaleMessages) {
  const item = tabItems.find((candidate) => candidate.id === tab);
  return item ? text[item.labelKey] : tab;
}

function surfaceLabel(anchor: string) {
  const labels: Record<string, string> = {
    "dataset-upload": "Dataset Upload",
    "data-focus": "Data Evidence",
    "relational-map": "Relational Map",
    "research-plan": "Research Plan",
    "agent-workspace": "Agent Workspace",
    "agent-activity": "Agent Activity",
    "notebook-native-marimo-top": "Notebook",
    "result-readout": "Result Readout"
  };
  return labels[anchor] ?? anchor.replace(/[_-]+/g, " ");
}

export function AgentActivityRail({
  text,
  projectName,
  jobs,
  events,
  activity,
  tick,
  onWorkerMessage,
  onCancelWorker,
  onNavigateToTarget,
  onOpenArtifact
}: {
  text: LocaleMessages;
  projectName: string;
  jobs: Job[];
  events: AgentWorkerEvent[];
  activity: AgentActivityResponse | null;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
  onCancelWorker: (jobId: string) => Promise<void>;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
  onOpenArtifact: (artifactId: string, targetTab: Tab, anchor?: string | null) => void;
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
    const merged = mergeAgentWorkerEvents([...fromJobs, ...events, ...fromActivity], projectName);
    return merged
      .filter((event) => isVisibleWorkerEvent(event, now))
      .sort(compareWorkerEvents)
      .slice(0, 8);
  }, [activity, events, jobs, projectName, text, tick]);

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
          <span className="agent-scope-pill live">
            {text.agentActivityLiveOnly} {workerEvents.length}
          </span>
          <button
            className="icon-button"
            onClick={toggleMinimized}
            title={minimized ? text.agentActivityExpand : text.agentActivityMinimize}
            type="button"
          >
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
              onNavigateToTarget={onNavigateToTarget}
              onOpenArtifact={onOpenArtifact}
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
  onCancelWorker,
  onNavigateToTarget,
  onOpenArtifact
}: {
  event: AgentWorkerEvent;
  text: LocaleMessages;
  tick: number;
  onWorkerMessage: (message: string) => Promise<void>;
  onCancelWorker: (jobId: string) => Promise<void>;
  onNavigateToTarget: (tab: Tab, anchor?: string | null) => void;
  onOpenArtifact: (artifactId: string, targetTab: Tab, anchor?: string | null) => void;
}) {
  const [draft, setDraft] = React.useState("");
  const [cancelling, setCancelling] = React.useState(false);
  const displaySeries = animatedTokenSeries(event, tick);
  const maxTokens = Math.max(...displaySeries.map((point) => point.tokens), 1);
  const currentTokens = displaySeries[displaySeries.length - 1]?.tokens ?? 0;
  const cumulativeTokens = cumulativeTokenTotal(displaySeries);
  const isLive = isLiveWorkerStatus(event.status);
  const isWaiting = isWaitingWorkerStatus(event.status);
  const isTerminal = isTerminalWorkerStatus(event.status);
  const description = event.human_description;
  const title = description?.title || event.headline;
  const summary = description?.summary || event.detail;
  const elapsedFrom = event.started_at ?? event.created_at ?? event.updated_at ?? null;
  const elapsedUntil = isTerminal ? parseApiTimestamp(event.ended_at ?? event.updated_at ?? "") : Date.now() + tick;
  const elapsed = elapsedFrom ? formatElapsed(parseApiTimestamp(elapsedFrom), elapsedUntil) : "-";
  const canCancel = canCancelWorkerEvent(event);
  const artifactId = event.artifact_id ?? event.artifact_ids?.[0] ?? null;
  const explicitNotebookViewer = artifactId && event.target_tab === "Notebooks";
  const targetTab = explicitNotebookViewer ? "Notebooks" : event.target_tab ? tabFromString(event.target_tab, "Home") : null;
  const targetLabel = targetTab
    ? `${text.openSurface} ${tabLabel(targetTab, text)}${event.target_anchor ? ` · ${surfaceLabel(event.target_anchor)}` : ""}`
    : text.openSurface;
  function openTarget() {
    if (!targetTab) return;
    if (artifactId) {
      onOpenArtifact(artifactId, targetTab, event.target_anchor ?? null);
      return;
    }
    onNavigateToTarget(targetTab, event.target_anchor ?? null);
  }

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
          {targetTab ? (
            <button
              className="icon-button agent-worker-open"
              onClick={openTarget}
              title={targetLabel}
              type="button"
            >
              <Eye size={14} />
            </button>
          ) : null}
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
          {text.workerElapsedLabel}: <strong>{elapsed}</strong>
        </span>
      </div>
      {!isTerminal ? (
        <>
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
        </>
      ) : null}
    </section>
  );
}

export function optimisticWorkerEvent(projectId: string, message: string, text: LocaleMessages): AgentWorkerEvent {
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

function mergeAgentWorkerEvents(events: AgentWorkerEvent[], fallbackProjectName: string): AgentWorkerEvent[] {
  const byIdentity = new Map<string, AgentWorkerEvent>();
  for (const rawEvent of events) {
    const event = rawEvent.project_name ? rawEvent : { ...rawEvent, project_name: fallbackProjectName };
    const identity = agentWorkerEventIdentity(event);
    const existing = byIdentity.get(identity);
    byIdentity.set(identity, existing ? mergeAgentWorkerEvent(existing, event) : event);
  }
  return [...byIdentity.values()];
}

function agentWorkerEventIdentity(event: AgentWorkerEvent): string {
  if (event.agent_session_id) return `session:${event.agent_session_id}`;
  if (event.job_id && !event.job_id.startsWith("local-")) return `job:${event.job_id}:worker:${event.worker_id || "default"}`;
  return `worker:${event.worker_id}:${event.job_id ?? event.created_at ?? event.updated_at ?? "event"}`;
}

function mergeAgentWorkerEvent(left: AgentWorkerEvent, right: AgentWorkerEvent): AgentWorkerEvent {
  const primary = preferredAgentWorkerEvent(left, right);
  const secondary = primary === left ? right : left;
  const primaryTelemetryIsWeaker = primary.token_usage.is_estimate && !secondary.token_usage.is_estimate;
  return {
    ...secondary,
    ...primary,
    project_name: primary.project_name ?? secondary.project_name,
    human_description: primary.human_description ?? secondary.human_description,
    started_at: primary.started_at ?? secondary.started_at,
    run_after: primary.run_after ?? secondary.run_after,
    retry_state: primary.retry_state ?? secondary.retry_state,
    token_usage: primaryTelemetryIsWeaker ? secondary.token_usage : primary.token_usage
  };
}

function preferredAgentWorkerEvent(left: AgentWorkerEvent, right: AgentWorkerEvent): AgentWorkerEvent {
  const leftRank = workerStatusRank(left.status);
  const rightRank = workerStatusRank(right.status);
  if (leftRank !== rightRank) return leftRank < rightRank ? left : right;
  if (left.token_usage.is_estimate !== right.token_usage.is_estimate) {
    return left.token_usage.is_estimate ? right : left;
  }
  const leftDescriptionScore = Number(Boolean(left.human_description?.title || left.human_description?.summary));
  const rightDescriptionScore = Number(Boolean(right.human_description?.title || right.human_description?.summary));
  if (leftDescriptionScore !== rightDescriptionScore) return leftDescriptionScore > rightDescriptionScore ? left : right;
  const leftTime = parseApiTimestamp(left.updated_at ?? left.created_at ?? "") || 0;
  const rightTime = parseApiTimestamp(right.updated_at ?? right.created_at ?? "") || 0;
  return rightTime >= leftTime ? right : left;
}

function isLiveWorkerStatus(status: string) {
  return status === "running";
}

function isWaitingWorkerStatus(status: string) {
  return ["queued", "approval_required", "starting", "between_turns", "waiting_for_runner", "waiting_for_agent"].includes(status);
}

function isRunningWorkerStatus(status: string) {
  return isLiveWorkerStatus(status) || isWaitingWorkerStatus(status);
}

const QUEUED_WORKER_ACTIVITY_TTL_MS = 5 * 60 * 1000;
const TRANSIENT_WORKER_ACTIVITY_TTL_MS = 15 * 1000;
const FINISHED_WORKER_ACTIVITY_TTL_MS = 8 * 1000;

function isTerminalWorkerStatus(status: string) {
  return ["succeeded", "failed", "cancelled", "timed_out"].includes(status);
}

function timestampAgeMs(value: string | null | undefined, now: number): number | null {
  if (!value) return null;
  const timestamp = parseApiTimestamp(value);
  if (!Number.isFinite(timestamp)) return null;
  return now - timestamp;
}

function isRecentTimestamp(value: string | null | undefined, now: number, ttlMs: number) {
  const ageMs = timestampAgeMs(value, now);
  return ageMs !== null && ageMs >= 0 && ageMs < ttlMs;
}

function isScheduledForFuture(value: string | null | undefined, now: number) {
  if (!value) return false;
  const timestamp = parseApiTimestamp(value);
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

export function jobActiveForActivity(job: Job, now: number = Date.now()) {
  if (job.status === "running" || job.status === "approval_required") return true;
  if (job.status === "waiting_for_agent") return true;
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
  if (status === "waiting_for_agent") return explicitActive !== false;
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

export function hasLiveAgentOrModelActivity(
  jobs: Job[],
  events: AgentWorkerEvent[],
  activity: AgentActivityResponse | null
) {
  const now = Date.now();
  const allEvents = [...events, ...(activity?.workers ?? [])];
  return allEvents.some((event) => isActiveWorkerEventAt(event, now)) || jobs.some((job) => jobActiveForActivity(job, now));
}

function isVisibleWorkerEvent(event: AgentWorkerEvent, now: number) {
  const timestamp = parseApiTimestamp(event.updated_at ?? event.created_at ?? "");
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
  const leftTime = parseApiTimestamp(left.updated_at ?? left.created_at ?? "") || 0;
  const rightTime = parseApiTimestamp(right.updated_at ?? right.created_at ?? "") || 0;
  return rightTime - leftTime;
}

function workerStatusRank(status: string) {
  if (status === "running") return 0;
  if (status === "approval_required") return 1;
  if (["starting", "between_turns", "waiting_for_runner", "waiting_for_agent"].includes(status)) return 2;
  if (status === "queued") return 3;
  return 4;
}

function animatedTokenSeries(event: AgentWorkerEvent, tick: number): TokenSeriesPoint[] {
  if (!isLiveWorkerStatus(event.status)) return event.token_usage.series;
  return event.token_usage.series.map((point, index) => ({
    ...point,
    tokens: Math.max(1, Math.round(point.tokens + ((tick + index) % 3) * Math.max(4, Math.round(point.tokens * 0.035))))
  }));
}

export function workerStatusLabel(status: string, text: LocaleMessages) {
  if (status === "queued") return text.workerStatusQueued;
  if (status === "running") return text.workerStatusRunning;
  if (status === "approval_required") return text.workerStatusApproval;
  if (status === "waiting_for_agent") return text.workerStatusWaitingForAgent;
  if (["starting", "between_turns", "waiting_for_runner"].includes(status)) return text.workerStatusWaitingForRunner;
  if (status === "timed_out") return text.workerStatusTimedOut;
  if (status === "failed") return text.workerStatusFailed;
  if (status === "cancelled") return text.workerStatusCancelled;
  if (["succeeded", "failed", "cancelled", "timed_out"].includes(status)) return text.workerStatusFinished;
  return humanizeLabel(status);
}

export function humanizeLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isMainAgentReplyWaitJob(job: Job) {
  return job.job_type === "agent_chat_turn" && job.status === "waiting_for_agent";
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

function parseApiTimestamp(value: string) {
  const trimmed = value.trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  return Date.parse(hasTimezone ? trimmed : `${trimmed}Z`);
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

export function workerEventsFromJob(job: Job, now: number, text: LocaleMessages): AgentWorkerEvent[] {
  const outputEvents = job.output.worker_events;
  if (Array.isArray(outputEvents)) {
    const coercedEvents = outputEvents
      .map((event, index) => coerceWorkerEvent(event, job, index, now, text))
      .filter((event): event is AgentWorkerEvent => event !== null);
    if (coercedEvents.length) return coercedEvents;
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
      ended_at: job.ended_at,
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
  const status = ["running", "succeeded", "failed", "cancelled", "timed_out", "approval_required"].includes(job.status)
    ? job.status
    : eventStatus;
  const createdAt = typeof record.created_at === "string" ? record.created_at : job.created_at;
  const endedAt = typeof record.ended_at === "string" ? record.ended_at : job.ended_at;
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
    ended_at: endedAt,
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
  if (jobType.includes("upload") || jobType.includes("dataset") || jobType.includes("primary_table")) return "Data";
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
