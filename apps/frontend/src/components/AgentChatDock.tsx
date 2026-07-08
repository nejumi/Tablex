import React from "react";
import { Download, Loader2, MessageSquare, Send, UserCircle } from "lucide-react";
import type { LocaleMessages } from "../copy";
import { tabItems, type AgentActionSummary, type AgentChatAction, type AgentChatMessage, type AgentConversationTurn, type Artifact, type TableeMotionState, type Tab, type TurnState } from "../types";

export type ChatSubmitShortcut = "enter" | "shift_enter";

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

export function useStickyBottomScroll<T extends HTMLElement>(dependencyKey: string, resetKey?: string) {
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

  const onWheel = React.useCallback((event: React.WheelEvent<T>) => {
    const element = ref.current;
    if (!element) return;
    const scrollableDistance = element.scrollHeight - element.clientHeight;
    if (scrollableDistance <= 0) return;
    const deltaY =
      event.deltaMode === WheelEvent.DOM_DELTA_LINE
        ? event.deltaY * 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
          ? event.deltaY * element.clientHeight
          : event.deltaY;
    const edgeTolerance = Math.max(8, Math.min(24, element.clientHeight * 0.02));
    const atTop = element.scrollTop <= edgeTolerance;
    const atBottom = scrollableDistance - element.scrollTop <= edgeTolerance;
    const shouldChainToPage = (deltaY < 0 && atTop) || (deltaY > 0 && atBottom);
    if (!shouldChainToPage) return;
    event.preventDefault();
    window.scrollBy({ top: deltaY, behavior: "auto" });
    shouldStickRef.current = deltaY > 0;
  }, []);

  return { ref, onScroll, onWheel };
}

export function shouldSubmitTextarea(event: React.KeyboardEvent<HTMLTextAreaElement>, shortcut: ChatSubmitShortcut): boolean {
  if (event.key !== "Enter") return false;
  if (event.nativeEvent.isComposing) return false;
  if (event.altKey || event.ctrlKey || event.metaKey) return false;
  return shortcut === "enter" ? !event.shiftKey : event.shiftKey;
}

function displayTextOrFallback(value: string | null | undefined, locale: string | null | undefined, fallback: string): string {
  void locale;
  const text = (value ?? "").trim();
  return text ? text : fallback;
}

function hasNonEmptyDisplayText(value: string | null | undefined): boolean {
  return Boolean((value ?? "").trim());
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatElapsedSeconds(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function tabFromString(value: string | null | undefined, fallback: Tab): Tab {
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

function agentChatActionLabel(action: AgentChatAction, text: LocaleMessages) {
  const targetTab = tabFromString(action.target_tab, "Home");
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
    ...(action.artifact_ids ?? []),
    action.job_id ?? "",
    ...(action.entity_ids ?? []),
    action.label
  ];
  return `${identityParts.join("|")}|${index}`;
}

function agentChatActionArtifactId(action: AgentChatAction): string | null {
  return [action.artifact_id, ...(action.artifact_ids ?? [])].filter((value): value is string => Boolean(value))[0] ?? null;
}

function agentChatActionIsPrimaryLink(action: AgentChatAction) {
  const targetTab = tabFromString(action.target_tab, "Home");
  if (["Notebooks", "Leaderboard", "Assets", "Data"].includes(targetTab)) return true;
  if (agentChatActionArtifactId(action)) return true;
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

function agentReplyProvenanceLabel(
  composer: Record<string, unknown> | null | undefined,
  text: LocaleMessages
): string | null {
  if (!composer) return null;
  const mode = textField(composer.mode);
  const status = textField(composer.status);
  if (mode === "main_codex_session" || status === "waiting_for_agent") return text.agentReplyProvenanceMainSession;
  if (mode === "autonomy_control_event" || mode === "autonomy_control_backfill" || mode === "explicit_ui_control") {
    return text.agentReplyProvenanceStatusUpdate;
  }
  if (
    mode === "codex_cli" ||
    mode === "codex_cli_if_available" ||
    mode === "structured_fallback" ||
    mode === "fallback" ||
    textField(composer.raw_surface) === "codex_exec"
  ) {
    return text.agentReplyProvenanceSavedState;
  }
  return null;
}

function isActiveAgentTurn(turn: AgentConversationTurn): boolean {
  if (!turn.assistant) return Boolean(turn.user?.transient);
  const status = String(turn.assistant.responseComposer?.status ?? "");
  return Boolean(turn.assistant.transient) && ["pending", "running", "queued", "in_progress", "waiting_for_agent"].includes(status);
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

export function TurnStateBar({ text, locale, turnState }: { text: LocaleMessages; locale: string; turnState: TurnState }) {
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
    return displayTextOrFallback(turnState.detail, locale, text.turnStateWorkerPendingHint);
  }
  if (turnState.state === "agent_scheduled") {
    return displayTextOrFallback(turnState.detail, locale, text.turnStateAgentScheduledHint);
  }
  if (turnState.state === "needs_attention") {
    return displayTextOrFallback(turnState.detail, locale, text.turnStateNeedsAttentionHint);
  }
  if (turnState.state === "agent_running") {
    return displayTextOrFallback(turnState.detail, locale, text.turnStateAgentTurnHint);
  }
  if (turnState.state === "stale_runner") {
    return displayTextOrFallback(turnState.detail, locale, text.turnStateNeedsAttentionHint);
  }
  return displayTextOrFallback(
    turnState.detail,
    locale,
    turnState.input_attention ? text.turnStateUserTurnHint : text.turnStateAgentTurnHint
  );
}

export function agentInputFormClassName(turnState: TurnState, extraClassName = "") {
  return ["agent-chat-form", turnState.input_attention ? "is-user-turn" : "", extraClassName]
    .filter(Boolean)
    .join(" ");
}

function turnStateClassName(turnState: TurnState) {
  return `turn-state-bar is-${turnState.state.replace(/_/g, "-").replace(/[^a-z0-9-]/gi, "-")}`;
}

export function turnStateLabel(turnState: TurnState, text: LocaleMessages, locale?: string) {
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
      return displayTextOrFallback(turnState.label, locale, text.turnStateObserved);
  }
}

export function UserAvatar({ src }: { src: string | null }) {
  if (src) {
    return <img className="chat-avatar user-avatar" src={src} alt="" aria-hidden="true" />;
  }
  return (
    <span className="chat-avatar user-avatar default" aria-hidden="true">
      <UserCircle size={23} />
    </span>
  );
}

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
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
  const progressRequestEventId = textField(brief?.progress_update_requested_event_id);
  const status = textField(observation.status);
  const turnIndex = numberField(observation.turn_index);
  if (status) {
    items.push(`${text.agentReplyWaitMetaStatus}: ${status}${turnIndex !== null ? ` · turn ${turnIndex}` : ""}`);
  }
  const lastOutputSeconds = numberField(observation.last_codex_output_seconds_ago);
  if (lastOutputSeconds !== null) {
    items.push(`${text.agentReplyWaitMetaOutput}: ${formatElapsedSeconds(lastOutputSeconds)} ${text.agentReplyWaitMetaAgo}`);
  }
  const lastChatUpdateSeconds = numberField(observation.last_chat_update_seconds_ago);
  if (lastChatUpdateSeconds !== null) {
    items.push(`${text.agentReplyWaitMetaChatUpdate}: ${formatElapsedSeconds(lastChatUpdateSeconds)} ${text.agentReplyWaitMetaAgo}`);
  }
  if (progressRequestEventId) {
    items.push(`${text.agentReplyWaitMetaProgressRequest}: ${text.agentReplyWaitMetaRequested}`);
  }
  const raw = objectRecord(observation.raw_transcript);
  const stdout = numberField(raw?.stdout_line_count) ?? 0;
  const stderr = numberField(raw?.stderr_line_count) ?? 0;
  if (stdout > 0 || stderr > 0) {
    items.push(`${text.agentReplyWaitMetaRaw}: stdout ${stdout} / stderr ${stderr}`);
  }
  return items.slice(0, 5);
}

function agentChatWaitLatestCodexMessage(brief: Record<string, unknown> | null | undefined): string | null {
  const observation = objectRecord(brief?.agent_session_observation);
  const latest = objectRecord(observation?.latest_codex_message);
  return textField(latest?.content);
}

function AgentConversationTurnCard({
  turn,
  text,
  userAvatarSrc,
  tableeMotionState,
  isLatestLiveTurn = true,
  onActionOpen
}: {
  turn: AgentConversationTurn;
  text: LocaleMessages;
  userAvatarSrc: string | null;
  tableeMotionState: TableeMotionState;
  isLatestLiveTurn?: boolean;
  onActionOpen: (action: AgentChatAction) => void;
}) {
  const assistant = turn.assistant;
  const active = isLatestLiveTurn && isActiveAgentTurn(turn);
  const outcome = active ? "pending" : assistant?.actionSummary?.outcome;
  const outcomeLabel = active ? text.agentReplyPending : agentChatOutcomeLabel(outcome);
  const statusClass = agentChatOutcomeClass(outcome);
  const provenanceLabel = assistant ? agentReplyProvenanceLabel(assistant.responseComposer, text) : null;
  const visibleActions = visibleAgentChatActions(assistant);
  const waitObservationItems = active ? agentChatWaitObservationItems(assistant?.responseBrief, text) : [];
  const latestCodexMessage = active ? agentChatWaitLatestCodexMessage(assistant?.responseBrief) : null;
  const visibleLatestCodexMessage =
    latestCodexMessage && hasNonEmptyDisplayText(latestCodexMessage) ? latestCodexMessage : null;
  const hasRawOnlyCodexMessage = Boolean(latestCodexMessage && !visibleLatestCodexMessage);
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
              {provenanceLabel ? <small className="badge muted">{provenanceLabel}</small> : null}
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
            {visibleLatestCodexMessage ? (
              <div className="agent-chat-wait-latest">
                <span>{text.agentReplyWaitMetaOutput}</span>
                <p>{visibleLatestCodexMessage}</p>
              </div>
            ) : hasRawOnlyCodexMessage ? (
              <div className="agent-chat-wait-latest">
                <span>{text.agentReplyWaitMetaRaw}</span>
                <p>{text.agentReplyWaitRawOutputPending}</p>
              </div>
            ) : null}
            {assistant.actionSummary ? (
              <AgentChatSummaryCard summary={assistant.actionSummary} text={text} onActionOpen={onActionOpen} />
            ) : null}
            {visibleActions.length ? (
              <div className="agent-turn-actions">
                {visibleActions.map((action, index) => (
                  <button
                    className="agent-chat-action-button"
                    key={agentChatActionKey(action, index)}
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

export function AgentChatDock({
  apiBase,
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
  apiBase: string;
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
  const latestActiveTurnId = latestTurn && isActiveAgentTurn(latestTurn) ? latestTurn.id : null;
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
      <div className="agent-chat-log" ref={chatScroll.ref} onScroll={chatScroll.onScroll} onWheel={chatScroll.onWheel}>
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
                    isLatestLiveTurn={turn.id === latestActiveTurnId}
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
              isLatestLiveTurn={turn.id === latestActiveTurnId}
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
