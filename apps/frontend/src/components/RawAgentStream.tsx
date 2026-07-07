import React from "react";
import { Loader2, Send } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type {
  AgentRawTranscript,
  AgentRawTranscriptLine,
  AgentRawTranscriptViewLine,
  RawAgentEvent,
  TurnState
} from "../types";
import { TurnStateBar, agentInputFormClassName, shouldSubmitTextarea, useStickyBottomScroll, type ChatSubmitShortcut } from "./AgentChatDock";

const apiBase = import.meta.env.VITE_API_BASE ?? "";

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function humanizeLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\w/g, (letter) => letter.toUpperCase());
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
  if (type === "item.completed" && itemType && itemType.includes("tool")) return toolName ? `Tool use: ${toolName}` : "Tool use";
  if (type === "item.completed" && itemType && (itemType.includes("command") || itemType.includes("exec"))) {
    return toolName ? `Command: ${toolName}` : "Command execution";
  }
  if (type === "item.completed" && itemType && (itemType.includes("patch") || itemType.includes("edit"))) return "Code edit";
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

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
}

function isActiveRawEvent(event: RawAgentEvent): boolean {
  return event.active === true;
}

export function RawAgentStream({
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
  const latestRawLine = rawLines[rawLines.length - 1] ?? null;
  const activeRawLineKey = latestRawLine ? `${latestRawLine.stream}-${latestRawLine.line_number}` : null;
  const rawTurnIsActive = turnState.owner === "agent" && turnState.state === "agent_running";
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
      <div className="raw-agent-log" ref={rawScroll.ref} onScroll={rawScroll.onScroll} onWheel={rawScroll.onWheel}>
        {rawLines.length ? (
          <>
            {rawLines.map((line) => (
              <RawTranscriptLineCard
                active={rawTurnIsActive && `${line.stream}-${line.line_number}` === activeRawLineKey}
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
          events.map((event, index) =>
            renderRawAgentEvent(event, { active: rawTurnIsActive && index === events.length - 1 })
          )
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

function renderRawAgentEvent(event: RawAgentEvent, options: { active?: boolean } = {}) {
  const active = options.active === true && isActiveRawEvent(event);
  return (
    <div className={`raw-agent-event ${active ? "is-active" : ""}`} key={event.id}>
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

