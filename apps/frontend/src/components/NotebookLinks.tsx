import React from "react";
import { AlertTriangle, BookOpen, Loader2 } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { LeaderboardEntry, NotebookIndex, NotebookIndexItem } from "../types";

export function notebooksForLeaderboardEntry(index: NotebookIndex | null, entry: LeaderboardEntry): NotebookIndexItem[] {
  if (!index) return [];
  const relatedNotebookArtifactIds = new Set([
    ...(entry.related_notebook_artifact_ids ?? []),
    ...(entry.related_notebooks ?? []).map((notebook) => notebook.artifact_id).filter(Boolean)
  ]);
  const seen = new Set<string>();
  const matched = index.items.filter((item) => {
    const matchesRun = item.run_id === entry.run_id || Boolean(item.related_run_ids?.includes(entry.run_id));
    const matchesModel = Boolean(entry.model_version_id && item.model_version_id === entry.model_version_id);
    const matchesArtifact = relatedNotebookArtifactIds.has(item.artifact_ids.notebook);
    if (!matchesRun && !matchesModel && !matchesArtifact) return false;
    if (seen.has(item.notebook_artifact_id)) return false;
    seen.add(item.notebook_artifact_id);
    return true;
  });
  return sortRelatedNotebookItemsForLeaderboardEntry(matched, entry);
}

export function notebooksForLeaderboardResults(index: NotebookIndex | null, leaderboard: LeaderboardEntry[]): NotebookIndexItem[] {
  if (!index) return [];
  const runIds = new Set(leaderboard.map((entry) => entry.run_id));
  const modelVersionIds = new Set(
    leaderboard.map((entry) => entry.model_version_id).filter((value): value is string => Boolean(value))
  );
  const relatedNotebookArtifactIds = new Set(
    leaderboard.flatMap((entry) => [
      ...(entry.related_notebook_artifact_ids ?? []),
      ...(entry.related_notebooks ?? []).map((notebook) => notebook.artifact_id).filter(Boolean)
    ])
  );
  const seen = new Set<string>();
  return sortRelatedNotebookItems(index.items.filter((item) => {
    const linkedToRun = Boolean(item.run_id && runIds.has(item.run_id)) || Boolean(item.related_run_ids?.some((runId) => runIds.has(runId)));
    const linkedToModel = Boolean(item.model_version_id && modelVersionIds.has(item.model_version_id));
    const linkedToArtifact = relatedNotebookArtifactIds.has(item.artifact_ids.notebook);
    if (!linkedToRun && !linkedToModel && !linkedToArtifact) return false;
    if (seen.has(item.notebook_artifact_id)) return false;
    seen.add(item.notebook_artifact_id);
    return true;
  }));
}

function notebookKindPriority(item: NotebookIndexItem) {
  if (item.notebook_kind === "model_diagnostics") return 0;
  if (item.notebook_kind === "model_comparison") return 0;
  if (item.notebook_kind === "data_understanding") return 2;
  return 1;
}

function notebookRunMatchPriority(item: NotebookIndexItem, entry: LeaderboardEntry) {
  if (item.run_id === entry.run_id) return 0;
  if (item.related_run_ids?.includes(entry.run_id)) return 1;
  if (entry.model_version_id && item.model_version_id === entry.model_version_id) return 1;
  return 2;
}

export function sortRelatedNotebookItemsForLeaderboardEntry(items: NotebookIndexItem[], entry: LeaderboardEntry) {
  return [...items].sort((left, right) => {
    const leftNeedsAttention = notebookNeedsAttention(left);
    const rightNeedsAttention = notebookNeedsAttention(right);
    if (leftNeedsAttention !== rightNeedsAttention) return leftNeedsAttention ? 1 : -1;
    const kindDelta = notebookKindPriority(left) - notebookKindPriority(right);
    if (kindDelta !== 0) return kindDelta;
    const runDelta = notebookRunMatchPriority(left, entry) - notebookRunMatchPriority(right, entry);
    if (runDelta !== 0) return runDelta;
    if (right.recommendation_score !== left.recommendation_score) return right.recommendation_score - left.recommendation_score;
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

export function notebookNeedsAttention(item: NotebookIndexItem) {
  return item.status === "needs_attention" || item.coverage.native_marimo_status === "runtime_error";
}

export function sortRelatedNotebookItems(items: NotebookIndexItem[]) {
  return [...items].sort((left, right) => {
    const leftNeedsAttention = notebookNeedsAttention(left);
    const rightNeedsAttention = notebookNeedsAttention(right);
    if (leftNeedsAttention !== rightNeedsAttention) return leftNeedsAttention ? 1 : -1;
    if (right.recommendation_score !== left.recommendation_score) return right.recommendation_score - left.recommendation_score;
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

export function preferredNotebookItems(index: NotebookIndex | null): NotebookIndexItem[] {
  return index ? sortRelatedNotebookItems(index.items) : [];
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

export function preferredNotebookForArtifact(index: NotebookIndex | null, artifactId: string): NotebookIndexItem | null {
  if (!index) return null;
  const directNotebook = index.items.find((item) => item.artifact_ids.notebook === artifactId);
  if (directNotebook) return directNotebook;
  return sortRelatedNotebookItems(index.items.filter((item) => notebookItemReferencesArtifact(item, artifactId)))[0] ?? null;
}

export function RelatedNotebookLinks({
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
    if (compact) return null;
    return <span className="related-notebook-empty">{text.noRelatedNotebooks}</span>;
  }
  const visible = notebooks.slice(0, compact ? 1 : 2);
  const hiddenCount = Math.max(0, notebooks.length - visible.length);
  return (
    <div className={`related-notebook-links ${compact ? "compact" : ""}`}>
      {visible.map((item) => {
        const artifactId = item.artifact_ids.notebook;
        const needsAttention = notebookNeedsAttention(item);
        return (
          <button
            className={`related-notebook-link ${needsAttention ? "needs-attention" : ""}`}
            disabled={previewLoadingId === artifactId}
            key={item.notebook_artifact_id}
            onClick={() => onOpen(artifactId)}
            title={needsAttention ? `${item.title} · ${text.notebookNativeMarimoRuntimeError}` : item.title}
            type="button"
          >
            {previewLoadingId === artifactId ? (
              <Loader2 className="spin" size={13} />
            ) : needsAttention ? (
              <AlertTriangle size={13} />
            ) : (
              <BookOpen size={13} />
            )}
            <span>{conciseNotebookTitle(item.title)}</span>
          </button>
        );
      })}
      {hiddenCount ? <span className="related-notebook-count">+{hiddenCount}</span> : null}
    </div>
  );
}

export function RelatedNotebookArtifactLinks({
  artifactIds,
  onOpen,
  previewLoadingId,
  text,
  compact = false
}: {
  artifactIds: string[];
  onOpen: (artifactId: string) => void;
  previewLoadingId: string | null;
  text: LocaleMessages;
  compact?: boolean;
}) {
  const uniqueArtifactIds = Array.from(new Set(artifactIds.filter(Boolean)));
  if (!uniqueArtifactIds.length) {
    if (compact) return null;
    return <span className="related-notebook-empty">{text.noRelatedNotebooks}</span>;
  }
  const visible = uniqueArtifactIds.slice(0, compact ? 1 : 2);
  const hiddenCount = Math.max(0, uniqueArtifactIds.length - visible.length);
  return (
    <div className={`related-notebook-links ${compact ? "compact" : ""}`}>
      {visible.map((artifactId, index) => (
        <button
          className="related-notebook-link"
          disabled={previewLoadingId === artifactId}
          key={artifactId}
          onClick={() => onOpen(artifactId)}
          title={text.notebookOpenMarimo}
          type="button"
        >
          {previewLoadingId === artifactId ? <Loader2 className="spin" size={13} /> : <BookOpen size={13} />}
          <span>{compact ? text.notebookOpenMarimo : `${text.notebookOpenMarimo} ${index + 1}`}</span>
        </button>
      ))}
      {hiddenCount ? <span className="related-notebook-count">+{hiddenCount}</span> : null}
    </div>
  );
}

export function conciseNotebookTitle(title: string) {
  const normalized = title.replace(/\s+/g, " ").trim();
  return normalized.length <= 34 ? normalized : `${normalized.slice(0, 33).trim()}...`;
}

