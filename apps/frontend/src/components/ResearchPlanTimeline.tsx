import React from "react";
import { Download } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { Artifact, ResearchPlanBlock, ResearchPlanBlockStatus, ResearchPlanContractValidation, ResearchPlanCurrentWork, ResearchPlanTimelineResponse, TurnState } from "../types";
import { RelatedOutputsDrawer, type RelatedOutputItem } from "./RelatedOutputsDrawer";

export function ResearchPlanTimeline({
  apiBase,
  blocks,
  contractValidation,
  currentWork,
  ignoredSourceArtifact,
  latestResearchPlan,
  locale,
  poweredOn,
  text,
  turnState
}: {
  apiBase: string;
  blocks: ResearchPlanBlock[];
  contractValidation: ResearchPlanContractValidation | null;
  currentWork: ResearchPlanCurrentWork | null;
  ignoredSourceArtifact: ResearchPlanTimelineResponse["ignored_source_artifact"] | null;
  latestResearchPlan: Artifact | null;
  locale: string;
  poweredOn: boolean;
  text: LocaleMessages;
  turnState: TurnState;
}) {
  const [expandedBlockId, setExpandedBlockId] = React.useState<string | null>(null);
  const timelineRef = React.useRef<HTMLDivElement | null>(null);
  const activeBlockRef = React.useRef<HTMLButtonElement | null>(null);
  const expandedBlock = blocks.find(
    (block) => block.id === expandedBlockId && ((block.subtasks?.length ?? 0) > 0 || (block.evidenceLinks?.length ?? 0) > 0)
  );
  const summary = researchPlanCompactSummary(blocks, text);
  const declaredCurrentBlock = currentWork?.node_id
    ? blocks.find((block) => block.id === currentWork.node_id) ?? null
    : null;
  const declaredCurrentWorkIsLive = researchPlanCurrentWorkIsLive(currentWork, poweredOn, turnState);
  const activeBlockKey = selectedResearchPlanBlockKey(blocks, currentWork, declaredCurrentWorkIsLive);
  const currentPositionText = researchPlanCurrentPositionText({
    blocks,
    currentWork,
    declaredCurrentBlock,
    poweredOn,
    text,
    turnState,
    locale
  });
  const contractNeedsRevision = Boolean(contractValidation && contractValidation.status === "needs_revision");
  const contractIssues = contractValidation?.issues?.slice(0, 3) ?? [];
  const ignoredSourceIssues = ignoredSourceArtifact?.contract_validation?.issues?.slice(0, 3) ?? [];

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
        {blocks.map((block, index) => {
          const displayTitle = displayTextOrFallback(block.title, locale, text.researchPlanSummaryBlock);
          const displaySubtitle = block.subtitle ? displayTextOrFallback(block.subtitle, locale, "") : "";
          const blockIsDeclaredCurrent = Boolean(currentWork?.node_id && block.id === currentWork.node_id);
          const blockIsLiveCurrentWork = blockIsDeclaredCurrent && declaredCurrentWorkIsLive;
          const blockIsCurrentButNotLive = blockIsDeclaredCurrent && !declaredCurrentWorkIsLive;
          const effectiveStatus = blockIsLiveCurrentWork ? "active" : block.status;
          const statusLabel = researchPlanBlockRuntimeAwareStatusLabel(block, currentWork, poweredOn, turnState, text);
          const runEvidenceCount = block.evidenceLinks?.filter((link) => link.outputKind === "run").length ?? 0;
          const otherEvidenceCount = (block.evidenceLinks?.length ?? 0) - runEvidenceCount;
          return (
            <React.Fragment key={block.id}>
              <button
                ref={block.id === activeBlockKey ? activeBlockRef : undefined}
                className={`research-plan-block ${effectiveStatus} ${block.isCurrentWork || blockIsLiveCurrentWork ? "current-work" : ""} ${blockIsCurrentButNotLive ? "current-work-paused" : ""} ${expandedBlockId === block.id ? "expanded" : ""}`}
                disabled={!block.onClick && !block.subtasks?.length && !block.evidenceLinks?.length}
                onClick={() => {
                  if (block.subtasks?.length || block.evidenceLinks?.length) {
                    setExpandedBlockId((current) => (current === block.id ? null : block.id));
                    return;
                  }
                  block.onClick?.();
                }}
                type="button"
              >
                <span>{block.eyebrow}</span>
                <strong>{displayTitle}</strong>
                {displaySubtitle ? <p>{displaySubtitle}</p> : null}
                {block.subtasks?.length ? (
                  <em className="research-plan-subtask-pill">
                    {block.subtasks.length} {block.subtasks.length === 1 ? text.planSubtaskSingular : text.planSubtaskPlural}
                  </em>
                ) : null}
                {runEvidenceCount ? (
                  <em className="research-plan-evidence-pill">
                    {runEvidenceCount} {text.metricRuns}
                  </em>
                ) : null}
                {otherEvidenceCount ? (
                  <em className="research-plan-evidence-pill">
                    {otherEvidenceCount} {text.researchPlanDetailEvidence}
                  </em>
                ) : null}
                <small>
                  {statusLabel}
                  {block.evidence ? ` · ${block.evidence}` : ""}
                </small>
              </button>
              {index < blocks.length - 1 ? <div className="research-plan-connector" aria-hidden="true" /> : null}
            </React.Fragment>
          );
        })}
      </div>
      {expandedBlock ? (
        <div className="research-plan-subtasks">
          <div className="research-plan-subtasks-head">
            <strong>{displayTextOrFallback(expandedBlock.title, locale, text.researchPlanSummaryBlock)}</strong>
            <span>{expandedBlock.subtasks?.length ? `${expandedBlock.subtasks.length} ${(expandedBlock.subtasks?.length ?? 0) === 1 ? text.planSubtaskSingular : text.planSubtaskPlural}` : text.researchPlanDetailEvidence}</span>
          </div>
          {expandedBlock.subtasks?.length ? (
            <div className="research-plan-subtask-list">
              {expandedBlock.subtasks.map((subtask) => (
                <button
                  className={`research-plan-subtask ${subtask.status}`}
                  disabled={!subtask.onClick}
                  key={subtask.id}
                  onClick={subtask.onClick}
                  type="button"
                >
                  <span className={navigatorStatusClass(subtask.status)}>{researchPlanStatusLabel(subtask.status, text)}</span>
                  <div>
                    <strong>{displayTextOrFallback(subtask.title, locale, text.researchPlanDetailEvidence)}</strong>
                    <p>{displayTextOrFallback(subtask.detail, locale, "")}</p>
                    {subtask.evidence ? <small>{subtask.evidence}</small> : null}
                  </div>
                </button>
              ))}
            </div>
          ) : null}
          {expandedBlock.evidenceLinks?.length ? (
            <RelatedOutputsDrawer
              downloadLabel={text.downloadArtifact}
              emptyText={text.projectAssetsEmpty}
              items={expandedBlock.evidenceLinks.map((link): RelatedOutputItem => ({
                id: link.id,
                kind: link.outputKind ?? "artifact",
                title: link.title,
                detail: link.detail,
                meta: link.evidence,
                onOpen: link.onClick,
                downloadUrl: link.artifactId ? `${apiBase}/api/artifacts/${link.artifactId}/download` : null
              }))}
              title={text.relatedOutputs}
            />
          ) : null}
        </div>
      ) : null}
      {currentPositionText ? (
        <div
          className={`research-plan-presence ${
            declaredCurrentBlock ? (declaredCurrentWorkIsLive ? "declared live" : "declared paused") : "unreported"
          }`}
        >
          <span>{text.researchPlanCurrentPosition}</span>
          <strong>{currentPositionText}</strong>
        </div>
      ) : null}
      {contractNeedsRevision ? (
        <div className="research-plan-contract-warning">
          <span>{text.researchPlanContractNeedsRevision}</span>
          <strong>
            {contractValidation?.error_count ?? 0} {text.researchPlanContractErrors} / {contractValidation?.warning_count ?? 0}{" "}
            {text.researchPlanContractWarnings}
          </strong>
          <p>{text.researchPlanContractNeedsRevisionDetail}</p>
          {contractIssues.length ? (
            <ul>
              {contractIssues.map((issue, index) => (
                <li key={`${issue.code ?? "issue"}-${index}`}>{issue.message ?? issue.code ?? issue.path}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {ignoredSourceArtifact ? (
        <div className="research-plan-contract-warning">
          <span>{text.researchPlanIgnoredSourceTitle}</span>
          <strong>{ignoredSourceArtifact.artifact_name ?? ignoredSourceArtifact.source_artifact_id}</strong>
          <p>{text.researchPlanIgnoredSourceDetail}</p>
          {ignoredSourceIssues.length ? (
            <ul>
              {ignoredSourceIssues.map((issue, index) => (
                <li key={`${issue.code ?? "ignored-source-issue"}-${index}`}>{issue.message ?? issue.code ?? issue.path}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="research-plan-footer">
        <span>
          {summary}
          {summary ? " · " : ""}
          {text.researchPlanTimelineHint}
        </span>
        {latestResearchPlan ? (
          <a className="icon-link" href={`${apiBase}/api/artifacts/${latestResearchPlan.id}/download`} title={text.downloadResearchPlan}>
            <Download size={16} />
          </a>
        ) : null}
      </div>
    </div>
  );
}

export function researchPlanCurrentWorkIsLive(
  currentWork: ResearchPlanCurrentWork | null,
  poweredOn: boolean,
  turnState: TurnState
): boolean {
  void turnState;
  if (!poweredOn || !currentWork?.node_id) return false;
  return currentWork.is_live === true;
}

function researchPlanCurrentWorkActivityLabel(currentWork: ResearchPlanCurrentWork | null, text: LocaleMessages): string {
  const state = currentWork?.activity_state;
  if (currentWork?.source === "research_plan_revision_status") return text.researchPlanPlannedPosition;
  if (state === "scheduled") return text.turnStateAgentScheduled;
  if (state === "paused") return text.agentPowerOff;
  if (state === "inactive") return text.turnStateNeedsAttention;
  return text.turnStateWorkerPending;
}

export function researchPlanBlockRuntimeAwareStatusLabel(
  block: ResearchPlanBlock,
  currentWork: ResearchPlanCurrentWork | null,
  poweredOn: boolean,
  turnState: TurnState,
  text: LocaleMessages
): string {
  if (currentWork?.node_id === block.id && !researchPlanCurrentWorkIsLive(currentWork, poweredOn, turnState)) {
    return researchPlanCurrentWorkActivityLabel(currentWork, text);
  }
  return researchPlanStatusLabel(block.status, text);
}

function selectedResearchPlanBlockKey(
  blocks: ResearchPlanBlock[],
  currentWork: ResearchPlanCurrentWork | null,
  currentWorkIsLive: boolean
): string {
  if (currentWorkIsLive && currentWork?.node_id && blocks.some((block) => block.id === currentWork.node_id)) {
    return currentWork.node_id;
  }
  return primaryResearchPlanFocusBlock(blocks)?.id ?? "";
}

export function primaryResearchPlanFocusBlock(blocks: ResearchPlanBlock[]): ResearchPlanBlock | null {
  const currentWorkBlock = blocks.find((block) => block.isCurrentWork);
  if (currentWorkBlock) return currentWorkBlock;
  const activeIndex = blocks.findIndex((block) => block.status === "active");
  return (
    blocks[activeIndex] ??
    blocks.find((block) => block.status === "blocked") ??
    blocks.find((block) => block.status === "pending") ??
    blocks.find((block) => block.status === "waiting") ??
    null
  );
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

function researchPlanCurrentPositionText({
  blocks,
  currentWork,
  declaredCurrentBlock,
  poweredOn,
  text,
  turnState,
  locale
}: {
  blocks: ResearchPlanBlock[];
  currentWork: ResearchPlanCurrentWork | null;
  declaredCurrentBlock: ResearchPlanBlock | null;
  poweredOn: boolean;
  text: LocaleMessages;
  turnState: TurnState;
  locale: string;
}): string {
  const plannedCurrentBlock = declaredCurrentBlock ?? blocks.find((block) => block.status === "active") ?? null;
  const plannedCurrentTitle = plannedCurrentBlock ? displayTextOrFallback(plannedCurrentBlock.title, locale, text.researchPlanSummaryBlock) : "";
  if (!poweredOn) {
    if (plannedCurrentTitle) return `${text.agentPowerOff} · ${text.researchPlanCurrentPosition}: ${plannedCurrentTitle}`;
    return text.agentPowerOff;
  }
  if (currentWork?.node_id && declaredCurrentBlock) {
    const title = displayTextOrFallback(declaredCurrentBlock.title, locale, currentWork.node_id);
    const summary = currentWork.summary ? displayTextOrFallback(currentWork.summary, locale, "") : "";
    const live = researchPlanCurrentWorkIsLive(currentWork, poweredOn, turnState);
    if (!live && turnState.state === "agent_running" && currentWork.source === "research_plan_revision_status") {
      return `${text.researchPlanCurrentWorkUnreported} · ${text.researchPlanCurrentPosition}: ${title}`;
    }
    const statePrefix = live ? "" : `${researchPlanCurrentWorkActivityLabel(currentWork, text)} · `;
    return `${statePrefix}${summary ? `${title}: ${summary}` : title}`;
  }
  if (turnState.state === "agent_running") {
    return text.researchPlanCurrentWorkUnreported;
  }
  return "";
}

export function researchPlanStatusLabel(status: ResearchPlanBlockStatus, text: LocaleMessages) {
  if (status === "done") return text.planStatusDone;
  if (status === "active") return text.planStatusActive;
  if (status === "blocked") return text.planStatusBlocked;
  if (status === "waiting") return text.planStatusWaiting;
  if (status === "skipped") return text.planStatusSkipped;
  return text.planStatusPending;
}

function displayTextOrFallback(value: string | null | undefined, locale: string | null | undefined, fallback: string): string {
  void locale;
  const text = (value ?? "").trim();
  return text ? text : fallback;
}

function navigatorStatusClass(status: string) {
  if (["ready_to_act", "ready", "low"].includes(status)) return "badge success";
  if (["blocked", "high", "needs_attention"].includes(status)) return "badge risk";
  if (["recover", "medium"].includes(status)) return "badge warning";
  return "badge muted";
}
