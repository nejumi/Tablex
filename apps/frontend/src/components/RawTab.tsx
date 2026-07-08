import type { LocaleMessages } from "../copy";
import type {
  AgentChatMessage,
  AgentRawTranscript,
  AgentSession,
  AgentTranscriptEvent,
  Job,
  TurnState
} from "../types";
import { RawAgentStream } from "./RawAgentStream";
import { buildRawAgentEvents } from "./rawEvents";

type ChatSubmitShortcut = "enter" | "shift_enter";

export function RawTab({
  busy,
  text,
  locale,
  messages,
  jobs,
  agentSession,
  agentTranscriptEvents,
  agentRawTranscript,
  submitShortcut,
  turnState,
  scrollResetKey,
  consoleDisabledReason,
  onSubmit
}: {
  busy: boolean;
  text: LocaleMessages;
  locale: string;
  messages: AgentChatMessage[];
  jobs: Job[];
  agentSession: AgentSession | null;
  agentTranscriptEvents: AgentTranscriptEvent[];
  agentRawTranscript: AgentRawTranscript | null;
  submitShortcut: ChatSubmitShortcut;
  turnState: TurnState;
  scrollResetKey: string;
  consoleDisabledReason?: string | null;
  onSubmit: (objective: string) => Promise<void>;
}) {
  const rawAgentEvents = buildRawAgentEvents(messages, jobs, agentTranscriptEvents, agentSession);
  return (
    <section className="detail raw-tab-surface">
      <RawAgentStream
        busy={busy}
        text={text}
        locale={locale}
        events={rawAgentEvents}
        rawTranscript={agentRawTranscript}
        submitShortcut={submitShortcut}
        turnState={turnState}
        scrollResetKey={scrollResetKey}
        consoleDisabledReason={consoleDisabledReason}
        onSubmit={onSubmit}
      />
    </section>
  );
}
