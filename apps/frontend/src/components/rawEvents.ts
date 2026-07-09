import type {
  AgentChatMessage,
  AgentSession,
  AgentTranscriptEvent,
  Job,
  RawAgentEvent
} from "../types";
import { humanizeLabel } from "./AgentActivityRail";

export function buildRawAgentEvents(
  messages: AgentChatMessage[],
  jobs: Job[],
  transcriptEvents: AgentTranscriptEvent[] = [],
  agentSession: AgentSession | null = null
): RawAgentEvent[] {
  void messages;
  void jobs;
  const sessionEvents = buildRawSessionEvents(transcriptEvents, agentSession);
  if (sessionEvents.length) {
    return dedupeRawAgentEvents(sessionEvents)
      .sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
      .slice(-500);
  }
  return [];
}

function buildRawSessionEvents(events: AgentTranscriptEvent[], agentSession: AgentSession | null): RawAgentEvent[] {
  const mainEvents = events.filter(isMainSessionTranscriptEvent);
  return mainEvents.map((event) => {
    const payload = event.payload ?? {};
    const active = agentSessionHasObservedCodexProcess(agentSession);
    const isCodex = event.source === "codex_cli" || event.source === "codex_cli_stderr";
    return {
      id: `agent-session-${event.id}`,
      timestamp: event.created_at,
      source: isCodex ? "Codex" : event.source === "user" ? "User" : "Tablex",
      level: event.event_type,
      title: event.title ?? humanizeLabel(event.event_type),
      active: active && isCodex && event.event_index === mainEvents[mainEvents.length - 1]?.event_index,
      body: event.content,
      details: [
        ...(event.source === "codex_cli" ? [{ label: "Raw Codex JSONL event", value: payload }] : []),
        ...(event.source === "codex_cli_stderr" ? [{ label: "Codex stderr line", value: payload }] : []),
        ...(event.source === "user" ? [{ label: "User instruction", value: payload }] : []),
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

function isMainSessionTranscriptEvent(event: AgentTranscriptEvent): boolean {
  return event.source === "codex_cli" || event.source === "codex_cli_stderr" || event.source === "user";
}

function dedupeRawAgentEvents(events: RawAgentEvent[]) {
  const byId = new Map<string, RawAgentEvent>();
  events.forEach((event) => byId.set(event.id, event));
  return [...byId.values()];
}

function agentSessionHasObservedCodexProcess(session: AgentSession | null): boolean {
  if (!session) return false;
  if (session.observed_runner_state === "running") return true;
  if (session.pid_is_observed_codex_process === true) return true;
  return (session.observed_codex_process_count ?? 0) > 0;
}

export function maxTranscriptEventIndex(events: AgentTranscriptEvent[]): number | null {
  let maxIndex: number | null = null;
  for (const event of events) {
    if (maxIndex === null || event.event_index > maxIndex) maxIndex = event.event_index;
  }
  return maxIndex;
}

export function mergeTranscriptEvents(current: AgentTranscriptEvent[], incoming: AgentTranscriptEvent[]) {
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
