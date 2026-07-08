import React from "react";
import { BarChart3, Download, FileText, ListChecks, Loader2, MessageSquare, PieChart, Play, Plus, Upload } from "lucide-react";
import type { LocaleMessages } from "../copy";
import { ArtifactLineagePanel } from "./ArtifactLineagePanel";
import { RelatedNotebookLinks, notebooksForLeaderboardEntry, notebooksForLeaderboardResults } from "./NotebookLinks";
import { RelatedOutputsDrawer, type RelatedOutputItem } from "./RelatedOutputsDrawer";
import type {
  AgentChatResponse,
  Artifact,
  ArtifactPreview,
  DatasetSnapshot,
  EvaluationSpec,
  EvidenceReaderMetric,
  Job,
  LeaderboardEntry,
  NotebookIndex,
  PilotDeploymentRead,
  PilotScoringReportRead,
  PilotValidationAuditRead,
  Project,
  ResultReadout,
  TranslationJobOutput,
  TranslationResult
} from "../types";

const apiBase = import.meta.env.VITE_API_BASE ?? "";
const SINGLE_PREDICTION_INPUT_KEY = "__single_prediction_input__";

type PredictionInputValidationReport = {
  status: "passed" | "failed" | string;
  missing_columns?: string[];
  unexpected_columns?: string[];
  observed_columns?: string[];
};

type PredictionInputUploadResponse = {
  schema_version: "prediction_input_upload.v1";
  artifact_id: string;
  artifact: Artifact;
  validation_report: PredictionInputValidationReport;
};

type UploadedPredictionInput = {
  artifactId: string;
  filename: string;
  validationReport: PredictionInputValidationReport;
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

type JobWaitOptions = {
  timeoutMs?: number;
  pollMs?: number;
  label?: string;
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

function textField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function booleanField(value: unknown): boolean {
  return value === true;
}

function predictionInputIsUsable(input: UploadedPredictionInput | undefined): boolean {
  return Boolean(input) && input?.validationReport.status !== "failed";
}

function predictionRunReady(
  entry: LeaderboardEntry,
  datasetId: string,
  uploadedInputs: Record<string, UploadedPredictionInput>
): boolean {
  const requiredTables = entry.pipeline_input_contract?.required_tables ?? [];
  if (requiredTables.length) {
    return requiredTables.every((table) => table.optional || predictionInputIsUsable(uploadedInputs[table.name]));
  }
  if (predictionInputIsUsable(uploadedInputs[SINGLE_PREDICTION_INPUT_KEY])) return true;
  return Boolean(datasetId);
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
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

function evidenceMetricClass(tone: EvidenceReaderMetric["tone"] = "muted") {
  if (tone === "ready") return "badge success";
  if (tone === "warning") return "badge warning";
  if (tone === "risk") return "badge risk";
  return "badge muted";
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function truncateLabel(value: string, length: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length <= length ? normalized : `${normalized.slice(0, Math.max(0, length - 3)).trim()}...`;
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

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
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

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
}

function predictionColumnText(column: { name: string; dtype?: string | null; required?: boolean }) {
  return [column.name, column.dtype, column.required === false ? "optional" : "required"].filter(Boolean).join(" · ");
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

function VisualArtifactPreview({ preview, text }: { preview: ArtifactPreview; text: LocaleMessages }) {
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

function HtmlArtifactPreview({ preview, text }: { preview: ArtifactPreview; text: LocaleMessages }) {
  const isSvg = preview.content_type === "image/svg+xml" || preview.filename.toLowerCase().endsWith(".svg");
  const previewType = isSvg ? text.artifactPreviewSvgBadge : text.artifactPreviewHtmlBadge;
  const url = `${apiBase}/api/artifacts/${preview.id}/download`;

  return (
    <div className="preview-block">
      <div className="preview-toolbar">
        <div className="preview-meta">
          <span className="badge">{previewType}</span>
          <span className="badge muted">{preview.filename}</span>
          {preview.truncated ? <span className="badge risk">{text.artifactPreviewTruncatedBadge}</span> : null}
        </div>
        <div className="row-actions">
          <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
            {text.artifactPreviewOpenOriginal}
          </a>
        </div>
      </div>
      {preview.truncated ? <div className="banner warning">{text.artifactPreviewTruncatedWarning}</div> : null}
      <div className="html-artifact-open-only">
        <FileText size={22} />
        <div>
          <strong>{text.artifactPreviewAvailableTitle}</strong>
          <p>{text.artifactPreviewAvailableBody}</p>
        </div>
        <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
          {text.artifactPreviewOpenOriginal}
        </a>
      </div>
    </div>
  );
}

function TranslatablePreview({
  preview,
  text,
  locale,
  sourceType = "artifact",
  sourceId
}: {
  preview: ArtifactPreview;
  text: LocaleMessages;
  locale: string;
  sourceType?: "artifact" | "report";
  sourceId?: string;
}) {
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
      const job = await api<Job>(
        sourceType === "report"
          ? `/api/reports/${effectiveSourceId}/translate`
          : `/api/artifacts/${effectiveSourceId}/translate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_locale: "en-US", target_locale: locale })
        }
      );
      await api<Job>(`/api/jobs/${job.id}/run`, { method: "POST" });
      const completedJob = await waitForJobCompletion(job.id, { timeoutMs: 60_000, label: "Translation job" });
      const output = completedJob.output as TranslationJobOutput;
      if (!output.translation) {
        throw new Error("Translation job completed without a translated preview.");
      }
      setTranslation({ ...output.translation, job: completedJob });
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
        <button className="secondary-button" disabled={busy || isSourceLocale || !preview.preview_available} onClick={() => void translate()}>
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

export function metricLabel(metric: string | null | undefined) {
  return metric ? metric.replace(/_/g, "-").toUpperCase() : "metric";
}

export function LeaderboardTab({
  project,
  specs,
  datasets,
  artifacts,
  notebookIndex,
  leaderboard,
  pilotDeployments,
  resultReadout,
  busy,
  locale,
  text,
  runAction,
  onAskAgent,
  onOpenNotebookArtifact
}: {
  project: Project;
  specs: EvaluationSpec[];
  datasets: DatasetSnapshot[];
  artifacts: Artifact[];
  notebookIndex: NotebookIndex | null;
  leaderboard: LeaderboardEntry[];
  pilotDeployments: PilotDeploymentRead[];
  resultReadout: ResultReadout | null;
  busy: boolean;
  locale: string;
  text: LocaleMessages;
  runAction: (action: () => Promise<unknown>) => Promise<void>;
  onAskAgent: (objective: string) => Promise<AgentChatResponse | void>;
  onOpenNotebookArtifact: (artifactId: string) => void;
}) {
  const splitManifests = artifacts.filter((artifact) => artifact.asset_type === "split_manifest");
  const [preview, setPreview] = React.useState<ArtifactPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = React.useState<string | null>(null);
  const [predictionEntry, setPredictionEntry] = React.useState<LeaderboardEntry | null>(null);
  const [predictionDatasetId, setPredictionDatasetId] = React.useState<string>("");
  const [predictionResultArtifactId, setPredictionResultArtifactId] = React.useState<string | null>(null);
  const [predictionUploadedInputs, setPredictionUploadedInputs] = React.useState<Record<string, UploadedPredictionInput>>({});
  const [predictionUploadError, setPredictionUploadError] = React.useState<string | null>(null);
  const [predictionDragKey, setPredictionDragKey] = React.useState<string | null>(null);
  const prewarmedNotebookArtifactsRef = React.useRef<Set<string>>(new Set());

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

  React.useEffect(() => {
    if (!predictionDatasetId && datasets.length) {
      setPredictionDatasetId(datasets[0].id);
    }
  }, [datasets, predictionDatasetId]);

  async function uploadPredictionInput(entry: LeaderboardEntry, file: File, tableName: string | null) {
    if (!entry.pipeline_artifact_id) return;
    const inputKey = tableName ?? SINGLE_PREDICTION_INPUT_KEY;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("pipeline_artifact_id", entry.pipeline_artifact_id);
    formData.append("table_name", tableName ?? "prediction_input");
    formData.append("batch_kind", "external_test");
    setPredictionUploadError(null);
    const uploaded = await api<PredictionInputUploadResponse>(`/api/projects/${project.id}/prediction-inputs`, {
      method: "POST",
      body: formData
    });
    setPredictionUploadedInputs((current) => ({
      ...current,
      [inputKey]: {
        artifactId: uploaded.artifact_id,
        filename: file.name,
        validationReport: uploaded.validation_report
      }
    }));
  }

  async function uploadPredictionInputFromFileList(entry: LeaderboardEntry, files: FileList | null, tableName: string | null) {
    const file = files?.[0];
    if (!file) return;
    try {
      await uploadPredictionInput(entry, file, tableName);
    } catch (err) {
      setPredictionUploadError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runPredictionForEntry(entry: LeaderboardEntry) {
    if (!entry.pipeline_artifact_id) return;
    const requiredTables = entry.pipeline_input_contract?.required_tables ?? [];
    const payload: Record<string, unknown> = {};
    if (requiredTables.length) {
      const tableMapping: Record<string, string> = {};
      for (const table of requiredTables) {
        const uploaded = predictionUploadedInputs[table.name];
        if (uploaded) {
          tableMapping[table.name] = uploaded.artifactId;
        } else if (!table.optional) {
          throw new Error(text.predictionMissingRequiredTable.replace("{table}", table.name));
        }
      }
      if (!Object.keys(tableMapping).length) throw new Error(text.predictionNoUploadedInputs);
      payload.input_artifact_ids_by_table = tableMapping;
    } else if (predictionUploadedInputs[SINGLE_PREDICTION_INPUT_KEY]) {
      payload.input_artifact_id = predictionUploadedInputs[SINGLE_PREDICTION_INPUT_KEY].artifactId;
    } else if (predictionDatasetId) {
      payload.dataset_snapshot_id = predictionDatasetId;
    } else {
      throw new Error(text.predictionNoUploadedInputs);
    }
    const job = await api<Job>(`/api/projects/${project.id}/pipelines/${entry.pipeline_artifact_id}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const completed = await runQueuedJobAndWait(job, { label: text.leaderboardActionPredict });
    const artifactId = textField(completed.output.artifact_id) ?? textField(completed.output.prediction_batch_artifact_id);
    setPredictionResultArtifactId(artifactId);
    if (artifactId) await loadPreview(artifactId);
  }
  const approvedSpecCount = specs.filter((spec) => spec.status === "approved").length;
  const topEntry = leaderboard[0] ?? null;
  const formalRunCount = leaderboard.filter((entry) => entry.evaluation_grade === "formal").length;
  const provisionalRunCount = leaderboard.length - formalRunCount;
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
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Run diagnostics job" });
    const artifactIds = Array.isArray(completedJob.output.artifact_ids) ? completedJob.output.artifact_ids : [];
    const preferredArtifactId = typeof artifactIds[1] === "string" ? artifactIds[1] : typeof artifactIds[0] === "string" ? artifactIds[0] : null;
    if (preferredArtifactId) {
      await loadPreview(preferredArtifactId);
    }
    return completedJob;
  }

  async function draftTopRunReport(entry: LeaderboardEntry) {
    const job = await api<Job>(`/api/runs/${entry.run_id}/report`, { method: "POST" });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Run report job" });
    const artifactId = textField(completedJob.output.artifact_id);
    if (artifactId) {
      await loadPreview(artifactId);
    }
    return completedJob;
  }

  async function materializeTopRunModelEvidence(entry: LeaderboardEntry) {
    const job = await api<Job>(`/api/runs/${entry.run_id}/model-diagnostics-artifacts`, { method: "POST" });
    const completedJob = await runQueuedJobAndWait(job, { timeoutMs: 10 * 60_000, label: "Model diagnostics artifacts job" });
    const artifactId =
      textField(completedJob.output.model_diagnostics_report_artifact_id) ??
      textField(completedJob.output.model_diagnostics_artifact_pack_id) ??
      textField(completedJob.output.feature_importance_artifact_id);
    if (artifactId) {
      await loadPreview(artifactId);
    }
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
      onOpenNotebookArtifact,
      onAskAgent
    });
    return completedJob;
  }

  const readoutStatus = resultReadout?.status ?? leaderboardStatus;
  const readoutTone = resultReadoutStatusTone(readoutStatus, leaderboardTone);
  const metricOptions = leaderboardMetricOptions(leaderboard);
  const selectedMetric = topEntry?.display_metric_name ?? metricOptions[0] ?? null;
  const unavailableCount = selectedMetric ? leaderboard.filter((entry) => !entry.display_metric_available).length : 0;
  const topMetricName = selectedMetric ?? "metric";
  const decisionReady = booleanField(resultReadout?.decision_report.available);
  const resultNotebooks = notebooksForLeaderboardResults(notebookIndex, leaderboard);

  const prewarmNativeMarimoArtifact = React.useCallback((artifactId: string) => {
    const normalized = artifactId.trim();
    if (!normalized || prewarmedNotebookArtifactsRef.current.has(normalized)) return;
    prewarmedNotebookArtifactsRef.current.add(normalized);
    void api(`/api/analysis-notebooks/${normalized}/marimo-session?wait_ready=false`, { method: "POST" }).catch(() => undefined);
  }, []);

  React.useEffect(() => {
    const artifactIds = new Set<string>();
    for (const notebook of resultNotebooks) {
      artifactIds.add(notebook.artifact_ids.notebook);
    }
    for (const entry of leaderboard.slice(0, 3)) {
      for (const notebook of notebooksForLeaderboardEntry(notebookIndex, entry)) {
        artifactIds.add(notebook.artifact_ids.notebook);
      }
      for (const notebook of entry.related_notebooks ?? []) {
        if (notebook.openable) artifactIds.add(notebook.artifact_id);
      }
    }
    for (const artifactId of Array.from(artifactIds).slice(0, 4)) {
      prewarmNativeMarimoArtifact(artifactId);
    }
  }, [leaderboard, notebookIndex, prewarmNativeMarimoArtifact, resultNotebooks]);

  async function setLeaderboardMetric(metric: string) {
    await api(`/api/projects/${project.id}/leaderboard/metric`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metric })
    });
  }

  function renderPredictionInputDropzone(entry: LeaderboardEntry, inputKey: string, tableName: string | null, label: string) {
    const uploaded = predictionUploadedInputs[inputKey];
    const validation = uploaded?.validationReport;
    const missing = validation?.missing_columns ?? [];
    const unexpected = validation?.unexpected_columns ?? [];
    return (
      <div
        className={`prediction-input-dropzone ${predictionDragKey === inputKey ? "dragging" : ""}`}
        key={inputKey}
        onDragLeave={() => setPredictionDragKey(null)}
        onDragOver={(event) => {
          event.preventDefault();
          setPredictionDragKey(inputKey);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setPredictionDragKey(null);
          void runAction(() => uploadPredictionInputFromFileList(entry, event.dataTransfer.files, tableName));
        }}
      >
        <div>
          <strong>{label}</strong>
          <span>{text.predictionDropHint}</span>
        </div>
        <label className="secondary-button">
          <Upload size={16} />
          {text.predictionChooseFile}
          <input
            hidden
            type="file"
            accept=".csv,.parquet,text/csv,application/vnd.apache.parquet"
            onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
              void runAction(() => uploadPredictionInputFromFileList(entry, event.target.files, tableName));
              event.currentTarget.value = "";
            }}
          />
        </label>
        {uploaded ? (
          <div className="prediction-input-validation">
            <span className={validation?.status === "failed" ? "badge warning" : "badge success"}>
              {validation?.status === "failed" ? text.predictionValidationFailed : text.predictionValidationPassed}
            </span>
            <small>{uploaded.filename}</small>
            {missing.length ? <small>{text.predictionMissingColumns.replace("{columns}", missing.join(", "))}</small> : null}
            {unexpected.length ? <small>{text.predictionUnexpectedColumns.replace("{columns}", unexpected.join(", "))}</small> : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="stack">
      <section id="result-readout" className="leaderboard-surface" aria-label={text.leaderboardTitle}>
        <div className="leaderboard-head">
          <div>
            <div className="eyebrow">{text.leaderboardTitle}</div>
            <h2>
              {leaderboard.length
                ? text.leaderboardRankedTitle
                    .replace("{count}", String(leaderboard.length))
                    .replace("{metric}", metricLabel(topMetricName))
                : text.leaderboardNoRunsTitle}
            </h2>
            <div className="badge-row">
              <span className={evidenceMetricClass(readoutTone)}>{readoutStatus.replace(/_/g, " ")}</span>
              <span className={approvedSpecCount ? "badge success" : "badge warning"}>
                {approvedSpecCount ? text.leaderboardEvaluationReady : text.leaderboardEvaluationMissing}
              </span>
              <span className={splitManifests.length ? "badge success" : "badge warning"}>
                {splitManifests.length ? text.leaderboardValidationReady : text.leaderboardValidationMissing}
              </span>
              {unavailableCount ? (
                <span className="badge warning">{text.leaderboardMissingScore.replace("{count}", String(unavailableCount))}</span>
              ) : null}
              {formalRunCount ? <span className="badge success">{text.leaderboardFormalBadge}</span> : null}
              {provisionalRunCount ? <span className="badge warning">{text.leaderboardProvisionalBadge}</span> : null}
            </div>
          </div>
          <div className="leaderboard-controls">
            <label>
              <span>{text.leaderboardMetricSelect}</span>
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
              {text.leaderboardAddMetric}
            </button>
            <div className="leaderboard-best-score">
              <span>{topEntry?.evaluation_grade === "formal" ? text.leaderboardBestScore : `${text.leaderboardBestScore} · ${text.leaderboardProvisionalBadge}`}</span>
              <strong>{formatScore(topEntry?.display_metric_value ?? null)}</strong>
              <small>{topEntry ? `${metricLabel(topMetricName)} · ${leaderboardEntryModelLabel(topEntry)}` : metricLabel(topMetricName)}</small>
            </div>
          </div>
        </div>
        {leaderboard.length ? (
          <>
          {resultNotebooks.length ? (
            <div className="leaderboard-result-notebooks">
              <div>
                <strong>{text.leaderboardResultNotebooks}</strong>
                <small>{text.leaderboardResultNotebooksBody}</small>
              </div>
              <RelatedNotebookLinks
                notebooks={resultNotebooks}
                onOpen={onOpenNotebookArtifact}
                previewLoadingId={previewLoadingId}
                text={text}
              />
            </div>
          ) : null}
          <div className="leaderboard-table-wrap">
            <Table
              headers={[
                text.leaderboardHeaderRank,
                text.leaderboardHeaderModel,
                text.leaderboardHeaderScore,
                text.leaderboardHeaderEvaluation,
                text.leaderboardHeaderEvidence,
                text.leaderboardHeaderActions
              ]}
              rows={leaderboard.map((entry) => [
                <strong className="leaderboard-rank" key={`${entry.run_id}-rank`}>#{entry.rank}</strong>,
                <div className="leaderboard-model-cell" key={`${entry.run_id}-model`}>
                  <strong>{leaderboardEntryModelLabel(entry)}</strong>
                  {entry.model_family ? <span className="badge muted">{entry.model_family.replace(/_/g, " ")}</span> : null}
                  {leaderboardEntryDescription(entry) ? <p>{leaderboardEntryDescription(entry)}</p> : null}
                  {leaderboardEntryFeatureSummary(entry) ? <small>{leaderboardEntryFeatureSummary(entry)}</small> : null}
                </div>,
                <div className="leaderboard-score-cell" key={`${entry.run_id}-score`}>
                  <strong>{formatScore(entry.display_metric_value)}</strong>
                  <small>{metricLabel(entry.display_metric_name)}</small>
                </div>,
                <div className="cell-stack" key={`${entry.run_id}-eval`}>
                  <span className={leaderboardEvaluationGradeClass(entry)}>
                    {leaderboardEvaluationGradeLabel(entry, text)}
                  </span>
                  <span>{entry.evaluation_spec_id ? text.leaderboardEvaluationReady : text.leaderboardEvaluationMissing}</span>
                  <small>{entry.split_manifest_id ? text.leaderboardValidationReady : text.leaderboardValidationMissing}</small>
                </div>,
                <div className="leaderboard-evidence-badges" key={`${entry.run_id}-evidence`}>
                  <span className={modelDiagnosticsBadgeClass(entry)}>{modelDiagnosticsStatusLabel(entry, text)}</span>
                  <small>{modelDiagnosticsChecksLabel(entry)}</small>
                  {openDeliverableExpectations(entry).length ? (
                    <span className="badge warning" title={deliverableExpectationsTitle(entry, text)}>
                      {text.deliverableExpectationsOpen.replace(
                        "{count}",
                        String(openDeliverableExpectations(entry).length)
                      )}
                    </span>
                  ) : null}
                  <span className={decisionReady ? "badge success" : "badge warning"}>
                    {decisionReady ? text.leaderboardEvidenceReportReady : text.leaderboardEvidenceReportMissing}
                  </span>
                  <RelatedOutputsDrawer
                    compact
                    downloadLabel={text.downloadArtifact}
                    emptyText={text.relatedOutputsEmpty}
                    items={relatedOutputItemsForLeaderboardEntry(entry, notebookIndex, text, onOpenNotebookArtifact, loadPreview)}
                    title={text.relatedOutputs}
                  />
                </div>,
                <div className="row-actions" key={`${entry.run_id}-actions`}>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => analyzeTopRun(entry))}
                    title={text.leaderboardActionAnalyzeDiagnostics}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => materializeTopRunModelEvidence(entry))}
                    title={text.leaderboardActionMaterializeEvidence}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <PieChart size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => {
                      const existingNotebook = notebooksForLeaderboardEntry(notebookIndex, entry)[0] ?? resultNotebooks[0] ?? null;
                      if (existingNotebook) {
                        onOpenNotebookArtifact(existingNotebook.artifact_ids.notebook);
                        return;
                      }
                      void runAction(prepareResultNotebookEvidence);
                    }}
                    title={text.leaderboardActionOpenNotebook}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <BarChart3 size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    onClick={() => void runAction(() => draftTopRunReport(entry))}
                    title={text.leaderboardActionDraftReport}
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy || !entry.pipeline_artifact_id}
                    onClick={() => {
                      setPredictionEntry(entry);
                      setPredictionResultArtifactId(null);
                      setPredictionUploadedInputs({});
                      setPredictionUploadError(null);
                    }}
                    title={entry.pipeline_artifact_id ? text.leaderboardActionPredict : text.pipelineBundleUnavailable}
                    type="button"
                  >
                    {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                  </button>
                  {entry.pipeline_artifact_id ? (
                    <a
                      className="icon-link"
                      href={`${apiBase}/api/experiment-runs/${entry.run_id}/pipeline-bundle`}
                      title={text.downloadPipelineBundle}
                    >
                      <Download size={16} />
                    </a>
                  ) : (
                    <button className="icon-button" disabled title={text.pipelineBundleUnavailable} type="button">
                      <Download size={16} />
                    </button>
                  )}
                </div>
              ])}
            />
          </div>
          {predictionEntry ? (
            <div className="leaderboard-prediction-panel">
              <div>
                <div className="eyebrow">{text.predictionDrawerTitle}</div>
                <h3>{leaderboardEntryModelLabel(predictionEntry)}</h3>
                <p>{text.predictionDrawerBody}</p>
              </div>
              {predictionEntry.pipeline_input_contract ? (
                <div className="prediction-contract">
                  {predictionEntry.pipeline_input_contract.columns.length ? (
                    <div>
                      <strong>{text.predictionExpectedColumns}</strong>
                      <div className="chip-row">
                        {predictionEntry.pipeline_input_contract.columns.map((column) => (
                          <span className="badge muted" key={column.name}>
                            {predictionColumnText(column)}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {predictionEntry.pipeline_input_contract.required_tables.length ? (
                    <div>
                      <strong>{text.predictionRequiredTables}</strong>
                      <div className="table-wrap compact">
                        <table>
                          <thead>
                            <tr>
                              <th>{text.artifactTableName}</th>
                              <th>{text.predictionTableRole}</th>
                              <th>{text.predictionExpectedColumns}</th>
                              <th>{text.predictionJoinKeys}</th>
                              <th>{text.predictionAsOfColumn}</th>
                              <th>{text.predictionHistoryWindow}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {predictionEntry.pipeline_input_contract.required_tables.map((table) => (
                              <tr key={table.name}>
                                <td>{table.name}</td>
                                <td>{table.role ?? "-"}</td>
                                <td>{table.columns.map((column) => predictionColumnText(column)).join(", ") || "-"}</td>
                                <td>{table.join_keys?.join(", ") || "-"}</td>
                                <td>{table.as_of_column ?? "-"}</td>
                                <td>{table.history_window ?? "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <EmptyInline text={text.predictionNoContract} />
              )}
              <div className="prediction-upload-section">
                <strong>{text.predictionUploadTitle}</strong>
                {predictionEntry.pipeline_input_contract?.required_tables.length ? (
                  <div className="prediction-table-inputs">
                    {predictionEntry.pipeline_input_contract.required_tables.map((table) =>
                      renderPredictionInputDropzone(
                        predictionEntry,
                        table.name,
                        table.name,
                        `${table.name}${table.optional ? ` · ${text.optional}` : ""}`
                      )
                    )}
                  </div>
                ) : (
                  renderPredictionInputDropzone(
                    predictionEntry,
                    SINGLE_PREDICTION_INPUT_KEY,
                    null,
                    text.predictionSingleInput
                  )
                )}
                {predictionUploadError ? <span className="badge warning">{predictionUploadError}</span> : null}
              </div>
              {datasets.length ? (
                <label className="field">
                  <span>{text.predictionInputDataset}</span>
                  <select value={predictionDatasetId} onChange={(event) => setPredictionDatasetId(event.target.value)}>
                    {datasets.map((dataset) => (
                      <option key={dataset.id} value={dataset.id}>
                        {dataset.source_ref ?? dataset.id} · {dataset.row_count ?? "-"} rows
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <EmptyInline text={text.predictionNoDatasets} />
              )}
              <div className="button-row">
                <button
                  className="primary-button"
                  disabled={busy || !predictionEntry.pipeline_artifact_id || !predictionRunReady(predictionEntry, predictionDatasetId, predictionUploadedInputs)}
                  onClick={() => void runAction(() => runPredictionForEntry(predictionEntry))}
                  type="button"
                >
                  {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
                  {text.predictionRun}
                </button>
                <button className="secondary-button" type="button" onClick={() => setPredictionEntry(null)}>
                  {text.close}
                </button>
                {predictionResultArtifactId ? (
                  <a className="secondary-button" href={`${apiBase}/api/artifacts/${predictionResultArtifactId}/download`}>
                    <Download size={16} />
                    {text.predictionDownload}
                  </a>
                ) : null}
              </div>
              {predictionResultArtifactId ? <span className="badge success">{text.predictionCompleted}</span> : null}
            </div>
          ) : null}
          </>
        ) : (
          <EmptyInline text={text.leaderboardEmpty} />
        )}
      </section>
      <section id="pilot-deployments" className="leaderboard-surface" aria-label={text.pilotDeploymentsTitle}>
        <div className="leaderboard-head">
          <div>
            <div className="eyebrow">{text.pilotDeploymentsTitle}</div>
            <h2>{text.pilotDeploymentsTitle}</h2>
            <p>{text.pilotDeploymentsBody}</p>
          </div>
        </div>
        {pilotDeployments.length ? (
          <div className="leaderboard-table-wrap">
            <Table
              headers={[
                text.pilotDeploymentModel,
                text.pilotDeploymentStatus,
                text.pilotDeploymentBatches,
                text.pilotDeploymentScore,
                text.pilotDeploymentAsOfViolations,
                text.pilotDeploymentAudit
              ]}
              rows={pilotDeployments.map((deployment) => {
                const latestReport = deployment.scoring_reports[0] ?? null;
                const latestAudit = deployment.validation_audits[0] ?? null;
                return [
                  <div className="leaderboard-model-cell" key={`${deployment.id}-pipeline`}>
                    <strong>{pilotDeploymentLabel(deployment, artifacts, text)}</strong>
                    <small>{formatDate(deployment.started_at)}</small>
                  </div>,
                  <span className={deployment.status === "active" ? "badge success" : "badge muted"} key={`${deployment.id}-status`}>
                    {deployment.status}
                  </span>,
                  <div className="cell-stack" key={`${deployment.id}-batches`}>
                    <span>{text.pilotPredictionCount.replace("{count}", String(deployment.prediction_batches.length))}</span>
                    <small>{text.pilotOutcomeCount.replace("{count}", String(deployment.outcome_batches.length))}</small>
                  </div>,
                  <div className="leaderboard-score-cell" key={`${deployment.id}-score`}>
                    <strong>{latestReport ? pilotReportMetricSummary(latestReport) : "-"}</strong>
                    <small>
                      {latestReport?.matched_rows != null
                        ? text.pilotMatchedRows.replace("{count}", String(latestReport.matched_rows))
                        : text.pilotNoScoringReport}
                    </small>
                  </div>,
                  <div className="cell-stack" key={`${deployment.id}-asof`}>
                    <span>{pilotAsOfViolationSummary(latestReport)}</span>
                    {latestReport ? (
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => void loadPreview(latestReport.artifact.id)}
                      >
                        {text.openSurface}
                      </button>
                    ) : null}
                  </div>,
                  <div className="cell-stack" key={`${deployment.id}-audit`}>
                    <span>{pilotAuditSummary(latestAudit, text)}</span>
                    {latestAudit?.next_iteration_focus ? <small>{truncateLabel(latestAudit.next_iteration_focus, 96)}</small> : null}
                    {latestAudit ? (
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => void loadPreview(latestAudit.artifact.id)}
                      >
                        {text.openSurface}
                      </button>
                    ) : null}
                  </div>
                ];
              })}
            />
          </div>
        ) : (
          <EmptyInline text={text.pilotDeploymentsEmpty} />
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
              <VisualArtifactPreview preview={preview} text={text} />
            ) : isHtmlArtifactPreview(preview) ? (
              <HtmlArtifactPreview preview={preview} text={text} />
            ) : (
              <TranslatablePreview preview={preview} text={text} locale={locale} />
            )
          ) : (
            <EmptyInline text={preview?.reason ?? "Select a run action to inspect its diagnostics, model evidence, notebook evidence, or report."} />
          )}
          {preview ? (
            <ArtifactLineagePanel
              inputs={preview.lineage?.inputs ?? []}
              outputs={preview.lineage?.outputs ?? []}
              text={text}
            />
          ) : null}
        </Panel>
      ) : null}
    </div>
  );
}

function formatScore(value: number | null) {
  return value == null || !Number.isFinite(value) ? "-" : value.toFixed(6);
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

function leaderboardEntryDescription(entry: LeaderboardEntry) {
  const description = entry.model_description?.trim() || entry.summary_md?.trim();
  if (description) return truncateLabel(description.replace(/\s+/g, " "), 180);
  return "";
}

function leaderboardEntryFeatureSummary(entry: LeaderboardEntry) {
  const featureSummary = entry.feature_summary?.trim();
  if (featureSummary) return featureSummary;
  const baseline = formatBaseline(entry.metrics);
  return baseline === "-" ? "" : baseline;
}

function leaderboardEvaluationGradeClass(entry: LeaderboardEntry) {
  return entry.evaluation_grade === "formal" ? "badge success" : "badge warning";
}

function leaderboardEvaluationGradeLabel(entry: LeaderboardEntry, text: LocaleMessages) {
  return entry.evaluation_grade === "formal" ? text.leaderboardFormalBadge : text.leaderboardProvisionalBadge;
}

const modelDiagnosticCheckLabels: Record<string, string> = {
  permutation_importance: "permutation",
  native_feature_importance: "tree/native",
  partial_dependence: "PDP",
  shap: "SHAP"
};

const relatedOutputAssetTypeKindMap: Record<string, RelatedOutputItem["kind"]> = {
  analysis_notebook: "notebook",
  marimo_notebook: "notebook",
  notebook_report: "notebook",
  model_diagnostics_artifact_report: "report",
  run_report: "report",
  feature_importance: "artifact",
  permutation_importance: "artifact",
  model_diagnostics_artifact_pack: "artifact",
  prediction_pipeline: "pipeline",
  research_findings_report: "research"
};

function modelDiagnosticsBadgeClass(entry: LeaderboardEntry) {
  const status = entry.model_diagnostics?.status ?? "missing";
  if (status === "ready") return "badge success";
  if (status === "partial" || status === "registered") return "badge warning";
  return "badge muted";
}

function modelDiagnosticsStatusLabel(entry: LeaderboardEntry, text: LocaleMessages) {
  const status = entry.model_diagnostics?.status ?? "missing";
  if (status === "ready") return text.modelDiagnosticsReady;
  if (status === "partial") return text.modelDiagnosticsPartial;
  if (status === "registered") return text.modelDiagnosticsRegistered;
  return text.modelDiagnosticsMissing;
}

function modelDiagnosticsChecksLabel(entry: LeaderboardEntry) {
  const checks = entry.model_diagnostics?.standard_checks ?? {};
  const parts = Object.entries(modelDiagnosticCheckLabels).map(([key, label]) => {
    const status = checks[key]?.status ?? "missing";
    return `${label}: ${status.replace(/_/g, " ")}`;
  });
  return parts.join(" / ");
}

function openDeliverableExpectations(entry: LeaderboardEntry) {
  return (entry.deliverable_expectations ?? []).filter((item) => item.status === "open");
}

function deliverableExpectationsTitle(entry: LeaderboardEntry, text: LocaleMessages) {
  return openDeliverableExpectations(entry)
    .map((item) => deliverableExpectationKindLabel(item.kind, text))
    .join(" / ");
}

function deliverableExpectationKindLabel(kind: string, text: LocaleMessages) {
  if (kind === "model_diagnostics_notebook") return text.deliverableExpectationModelDiagnosticsNotebook;
  if (kind === "pipeline_bundle") return text.deliverableExpectationPipelineBundle;
  if (kind === "validation_audit") return text.deliverableExpectationValidationAudit;
  if (kind === "research_findings") return text.deliverableExpectationResearchFindings;
  return kind.replace(/_/g, " ");
}

function relatedOutputItemsForLeaderboardEntry(
  entry: LeaderboardEntry,
  notebookIndex: NotebookIndex | null,
  text: LocaleMessages,
  onOpenNotebookArtifact: (artifactId: string) => void,
  loadPreview: (artifactId: string) => Promise<void>
): RelatedOutputItem[] {
  const seen = new Set<string>();
  const items: RelatedOutputItem[] = [];
  const add = (item: RelatedOutputItem) => {
    if (seen.has(item.id)) return;
    seen.add(item.id);
    items.push(item);
  };

  for (const notebook of notebooksForLeaderboardEntry(notebookIndex, entry)) {
    const artifactId = notebook.artifact_ids.notebook;
    add({
      id: `notebook:${artifactId}`,
      kind: "notebook",
      title: text.notebookKindModelDiagnostics,
      detail: notebook.title,
      meta: notebook.notebook_kind.replace(/_/g, " "),
      status: notebook.status,
      onOpen: () => onOpenNotebookArtifact(artifactId),
      downloadUrl: `${apiBase}/api/artifacts/${artifactId}/download`
    });
  }

  for (const relatedNotebook of entry.related_notebooks ?? []) {
    if (!relatedNotebook.openable || seen.has(`notebook:${relatedNotebook.artifact_id}`)) continue;
    add({
      id: `notebook:${relatedNotebook.artifact_id}`,
      kind: "notebook",
      title: text.notebookKindModelDiagnostics,
      detail: relatedNotebook.title ?? relatedNotebook.artifact_id,
      meta: relatedNotebook.notebook_kind?.replace(/_/g, " ") ?? null,
      status: relatedNotebook.status ?? relatedNotebook.native_marimo_status ?? null,
      onOpen: () => onOpenNotebookArtifact(relatedNotebook.artifact_id),
      downloadUrl: `${apiBase}/api/artifacts/${relatedNotebook.artifact_id}/download`
    });
  }

  if (entry.pipeline_artifact_id) {
    add({
      id: `pipeline:${entry.pipeline_artifact_id}`,
      kind: "pipeline",
      title: text.downloadPipelineBundle,
      detail: leaderboardEntryModelLabel(entry),
      meta: entry.pipeline_artifact_id,
      downloadUrl: `${apiBase}/api/experiment-runs/${entry.run_id}/pipeline-bundle`
    });
  }

  for (const [key, ref] of Object.entries(entry.model_diagnostics?.artifact_refs ?? {})) {
    add({
      id: `artifact:${ref.artifact_id}`,
      kind: relatedOutputKindForAssetType(ref.asset_type),
      title: key.replace(/_/g, " "),
      detail: ref.name ?? ref.artifact_id,
      meta: ref.asset_type.replace(/_/g, " "),
      onOpen: () => void loadPreview(ref.artifact_id),
      downloadUrl: relatedOutputDownloadUrl(ref.download_url, ref.artifact_id)
    });
  }

  for (const [key, check] of Object.entries(entry.model_diagnostics?.standard_checks ?? {})) {
    if (!check.artifact_id) continue;
    add({
      id: `artifact:${check.artifact_id}`,
      kind: "artifact",
      title: key.replace(/_/g, " "),
      detail: check.artifact_id,
      status: check.status.replace(/_/g, " "),
      onOpen: () => void loadPreview(check.artifact_id as string),
      downloadUrl: `${apiBase}/api/artifacts/${check.artifact_id}/download`
    });
  }

  return items;
}

function relatedOutputKindForAssetType(assetType: string): RelatedOutputItem["kind"] {
  return relatedOutputAssetTypeKindMap[assetType] ?? "artifact";
}

function relatedOutputDownloadUrl(downloadUrl: string | null | undefined, artifactId: string) {
  if (downloadUrl) return downloadUrl.startsWith("/api/") ? `${apiBase}${downloadUrl}` : downloadUrl;
  return `${apiBase}/api/artifacts/${artifactId}/download`;
}

function pilotDeploymentLabel(deployment: PilotDeploymentRead, artifacts: Artifact[], text: LocaleMessages) {
  const artifact = artifacts.find((item) => item.id === deployment.pipeline_artifact_id);
  return artifact?.name ?? text.pilotRegisteredPipeline;
}

function pilotReportMetricSummary(report: PilotScoringReportRead) {
  const metricEntries = Object.entries(report.metrics).filter(([, value]) => typeof value === "number" && Number.isFinite(value));
  if (!metricEntries.length) return "-";
  const [name, value] = metricEntries[0] as [string, number];
  return `${metricLabel(name)} ${formatScore(value)}`;
}

function pilotAsOfViolationSummary(report: PilotScoringReportRead | null) {
  if (!report) return "-";
  const count = report.as_of_violations.count;
  if (typeof count !== "number") return "-";
  return `${count}`;
}

function pilotAuditSummary(audit: PilotValidationAuditRead | null, text: LocaleMessages) {
  if (!audit) return text.pilotDeploymentAuditEmpty;
  const verdict = audit.scheme_verdict?.trim();
  const decompositionCount = audit.gap_decomposition.length;
  if (verdict && decompositionCount) return `${verdict.replace(/_/g, " ")} · ${decompositionCount}`;
  return verdict ? verdict.replace(/_/g, " ") : text.pilotDeploymentAudit;
}
