import type {
  AgentChatMessage,
  AgentConversationTurn,
  AgentSession,
  AgentTranscriptEvent,
  Job,
  RawAgentEvent
} from "../types";
import { humanizeLabel, jobActiveForActivity } from "./AgentActivityRail";

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

export function buildRawAgentEvents(
  messages: AgentChatMessage[],
  jobs: Job[],
  transcriptEvents: AgentTranscriptEvent[] = [],
  agentSession: AgentSession | null = null
): RawAgentEvent[] {
  const sessionEvents = buildRawSessionEvents(transcriptEvents, agentSession);
  if (sessionEvents.length) {
    return dedupeRawAgentEvents([...sessionEvents, ...buildRawJobHarnessEvents(jobs)])
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
    const isHarnessControlEvent = composerMode === "autonomy_control_event" || composerMode === "autonomy_control_backfill";
    if (!isCodexCli && !active && !isHarnessControlEvent) return events;
    if (turn.user) {
      events.push({
        id: `raw-user-${index}-${turn.user.id ?? turn.user.text.slice(0, 18)}`,
        timestamp: turn.user.createdAt ?? turn.createdAt ?? now,
        source: "User",
        level: "prompt",
        title: isHarnessControlEvent ? "User control request" : "Prompt sent to Codex",
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
      source: isHarnessControlEvent ? "Tablex" : "Codex",
      level: composerStatus,
      title: isHarnessControlEvent
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
          ? [{ label: isHarnessControlEvent ? "Tablex event detail" : "Codex run metadata", value: turn.assistant.responseComposer }]
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

function buildRawJobHarnessEvents(jobs: Job[]): RawAgentEvent[] {
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
          body: latestJobHeadline(job),
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
        id: `raw-job-harness-${job.id}`,
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

function buildAgentConversationTurns(messages: AgentChatMessage[]): AgentConversationTurn[] {
  const turns: AgentConversationTurn[] = [];
  for (const message of messages) {
    const messageId = message.id ?? `${message.role}:${message.createdAt ?? turns.length}:${message.text.slice(0, 18)}`;
    const messageCreatedAt = message.createdAt ?? new Date().toISOString();
    if (message.role === "user") {
      turns.push({
        id: messageId,
        createdAt: messageCreatedAt,
        user: message
      });
      continue;
    }
    const lastTurn = turns[turns.length - 1];
    if (lastTurn && !lastTurn.assistant) {
      lastTurn.assistant = message;
      if (new Date(messageCreatedAt).getTime() < new Date(lastTurn.createdAt ?? messageCreatedAt).getTime()) {
        lastTurn.createdAt = messageCreatedAt;
      }
      continue;
    }
    turns.push({
      id: messageId,
      createdAt: messageCreatedAt,
      assistant: message
    });
  }
  return turns;
}

function latestJobHeadline(job: Job) {
  const output = job.output ?? {};
  return textField(output.agent_final_message) ?? textField(output.message) ?? textField(output.error) ?? textField(job.error_message) ?? null;
}

function agentSessionHasObservedCodexProcess(session: AgentSession | null): boolean {
  if (!session) return false;
  if (session.observed_runner_state === "running") return true;
  if (session.pid_is_observed_codex_process === true) return true;
  return (session.observed_codex_process_count ?? 0) > 0;
}

function isActiveAgentTurn(turn: AgentConversationTurn): boolean {
  if (!turn.assistant) return false;
  if (turn.assistant.transient) return true;
  const status = textField(turn.assistant.responseComposer?.status);
  return Boolean(status && ["queued", "running", "pending", "in_progress", "waiting_for_agent"].includes(status));
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
